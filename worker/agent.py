#!/usr/bin/env python3
import hashlib
import hmac
import http.server
import json
import os
import re
import subprocess
import threading
import time
from urllib.parse import urlparse

ENV_FILE = "/opt/emby_agent/.env"
URL_MAP = "/etc/nginx/emby_url.map"
SNI_MAP = "/etc/nginx/emby_sni.map"
MAX_BODY = 1024 * 1024
MAX_CLOCK_SKEW = 60


def load_env():
    values = {}
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    values[key.strip()] = value.split("#", 1)[0].strip().strip('"\'')
    return values


SECRET_KEY = load_env().get("SECRET_KEY", "")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY is missing")

file_lock = threading.Lock()
reload_lock = threading.Lock()
reload_timer = None


def valid_subdomain(value):
    return bool(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", value or ""))


def valid_base_domain(value):
    return bool(re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", value or ""))


def parse_target(value):
    target = value.strip().rstrip("/")
    if not target.startswith(("http://", "https://")):
        target = "https://" + target
    parsed = urlparse(target)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Invalid target")
    return target, parsed.hostname


def atomic_write(path, lines):
    temp_path = path + ".tmp"
    with open(temp_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.writelines(lines)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temp_path, 0o640)
    os.replace(temp_path, path)


def reload_nginx():
    global reload_timer
    with reload_lock:
        if reload_timer:
            reload_timer.cancel()
        reload_timer = threading.Timer(
            1.0, subprocess.run, args=(["nginx", "-s", "reload"],),
            kwargs={"check": False},
        )
        reload_timer.daemon = True
        reload_timer.start()


class AgentHandler(http.server.BaseHTTPRequestHandler):
    server_version = "EmbyWorker/3.0"

    def address_string(self):
        return self.client_address[0]

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.client_address[0], fmt % args), flush=True)

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def verify_health_signature(self):
        timestamp = self.headers.get("X-Emby-Timestamp", "")
        signature = self.headers.get("X-Emby-Signature", "")
        try:
            timestamp_value = int(timestamp)
        except ValueError:
            return False
        if abs(time.time() - timestamp_value) > MAX_CLOCK_SKEW:
            return False
        expected = hmac.new(
            SECRET_KEY.encode("utf-8"), timestamp.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    def do_GET(self):
        if self.path != "/api/health":
            return self.send_json(404, {"ok": False, "error": "Not found"})
        if not self.verify_health_signature():
            return self.send_json(403, {"ok": False, "error": "Signature invalid"})
        return self.send_json(200, {"ok": True, "version": "3.0", "time": int(time.time())})

    def do_POST(self):
        if self.path != "/api/sync":
            return self.send_json(404, {"ok": False, "error": "Not found"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self.send_json(400, {"ok": False, "error": "Invalid length"})
        if length <= 0 or length > MAX_BODY:
            return self.send_json(413, {"ok": False, "error": "Invalid body size"})
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return self.send_json(400, {"ok": False, "error": "Invalid JSON"})

        try:
            timestamp = int(data.get("t", 0))
        except (TypeError, ValueError):
            return self.send_json(403, {"ok": False, "error": "Timestamp invalid"})
        if abs(time.time() - timestamp) > MAX_CLOCK_SKEW:
            return self.send_json(403, {"ok": False, "error": "Timestamp expired"})

        action = str(data.get("action", ""))
        subdomain = str(data.get("subdomain", "")).strip().lower()
        target = str(data.get("target", "")).strip()
        base_domain = str(data.get("base_domain", "")).strip().lower()
        if action not in ("add", "delete"):
            return self.send_json(400, {"ok": False, "error": "Invalid action"})
        if not valid_subdomain(subdomain) or not valid_base_domain(base_domain):
            return self.send_json(400, {"ok": False, "error": "Invalid domain"})

        message = f"{timestamp}:{action}:{subdomain}:{target}".encode("utf-8")
        expected = hmac.new(SECRET_KEY.encode("utf-8"), message, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, str(data.get("sign", ""))):
            return self.send_json(403, {"ok": False, "error": "Signature invalid"})

        full_domain = f"{subdomain}.{base_domain}"
        if action == "add":
            try:
                target_url, target_sni = parse_target(target)
            except ValueError:
                return self.send_json(400, {"ok": False, "error": "Invalid target"})
        else:
            target_url, target_sni = "", ""

        with file_lock:
            url_lines = open(URL_MAP, encoding="utf-8").readlines() if os.path.exists(URL_MAP) else []
            sni_lines = open(SNI_MAP, encoding="utf-8").readlines() if os.path.exists(SNI_MAP) else []
            marker = f'"{full_domain}"'
            url_lines = [line for line in url_lines if marker not in line]
            sni_lines = [line for line in sni_lines if marker not in line]
            if action == "add":
                url_lines.append(f'    "{full_domain}" "{target_url}";\n')
                sni_lines.append(f'    "{full_domain}" "{target_sni}";\n')
            atomic_write(URL_MAP, url_lines)
            atomic_write(SNI_MAP, sni_lines)

        reload_nginx()
        return self.send_json(200, {"ok": True, "action": action, "domain": full_domain})


if __name__ == "__main__":
    http.server.ThreadingHTTPServer(("127.0.0.1", 8081), AgentHandler).serve_forever()
