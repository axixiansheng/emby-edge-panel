import base64
import hashlib
import hmac
import ipaddress
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .security import BusinessError


class Integrations:
    def __init__(self, config):
        self.config = config

    def request(self, url, data=None, method="GET", headers=None):
        request = urllib.request.Request(
            url, data=None if data is None else json.dumps(data).encode(),
            method=method, headers={"Content-Type": "application/json", **(headers or {})},
        )
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                result = json.loads(response.read(1024 * 1024))
        except urllib.error.HTTPError as error:
            # Never expose upstream payloads: they can contain credentials or origin details.
            raise RuntimeError("Upstream HTTP " + str(error.code)) from None
        except (OSError, ValueError):
            raise RuntimeError("Upstream unavailable or invalid response") from None
        return result

    def worker(self, node, action, sub, target):
        import time
        timestamp = int(time.time())
        signature = hmac.new(
            node["secret_key"].encode(), f"{timestamp}:{action}:{sub}:{target}".encode(), hashlib.sha256
        ).hexdigest()
        host = node["host"]
        if ":" in host:
            host = "[" + host + "]"
        result = self.request(
            f"http://{host}:{node['port']}/api/sync",
            {"action": action, "subdomain": sub, "target": target,
             "base_domain": self.config.base_domain, "t": timestamp, "sign": signature},
            "POST",
        )
        if result.get("ok") is not True:
            raise RuntimeError("Worker rejected operation")
        if action == "add" and not result.get("ready"):
            # Legacy v3.0 acknowledges before its one-second reload timer fires.
            time.sleep(1.25)

    def health(self, node):
        import time
        timestamp = str(int(time.time()))
        signature = hmac.new(node["secret_key"].encode(), timestamp.encode(), hashlib.sha256).hexdigest()
        host = "[" + node["host"] + "]" if ":" in node["host"] else node["host"]
        result = self.request(
            f"http://{host}:{node['port']}/api/health",
            headers={"X-Emby-Timestamp": timestamp, "X-Emby-Signature": signature},
        )
        if result.get("ok") is not True:
            raise RuntimeError("Worker health check rejected")

    def dns_snapshot(self, sub):
        full_name = sub + "." + self.config.base_domain
        base = f"https://api.cloudflare.com/client/v4/zones/{self.config.cf_zone}/dns_records"
        headers = {"Authorization": "Bearer " + self.config.cf_token}
        result = self.request(base + "?" + urllib.parse.urlencode({"name": full_name}), headers=headers)
        if not result.get("success"):
            raise RuntimeError("Cloudflare DNS lookup rejected")
        return result.get("result", [])

    def dns_restore(self, sub, records):
        if not records:
            self.dns(sub)
            return
        if len(records) != 1:
            raise RuntimeError("DNS snapshot requires administrator review")
        current = self.dns_snapshot(sub)
        if len(current) > 1:
            raise RuntimeError("Multiple DNS records exist; administrator review required")
        record = records[0]
        base = f"https://api.cloudflare.com/client/v4/zones/{self.config.cf_zone}/dns_records"
        headers = {"Authorization": "Bearer " + self.config.cf_token}
        data = {key: record[key] for key in ("type", "name", "content", "ttl", "proxied")}
        result = self.request(
            base + "/" + current[0]["id"] if current else base,
            data, "PUT" if current else "POST", headers,
        )
        if not result.get("success"):
            raise RuntimeError("Cloudflare DNS restore rejected")

    def dns(self, sub, host=None):
        full_name = sub + "." + self.config.base_domain
        base = f"https://api.cloudflare.com/client/v4/zones/{self.config.cf_zone}/dns_records"
        headers = {"Authorization": "Bearer " + self.config.cf_token}
        records = self.dns_snapshot(sub)
        if host is None:
            for record in records:
                result = self.request(base + "/" + record["id"], method="DELETE", headers=headers)
                if not result.get("success"):
                    raise RuntimeError("Cloudflare DNS deletion rejected")
            if self.dns_snapshot(sub):
                raise RuntimeError("Cloudflare DNS confirmation mismatch")
            return
        try:
            address = ipaddress.ip_address(host)
            kind = "AAAA" if address.version == 6 else "A"
        except ValueError:
            kind = "CNAME"
        if len(records) > 1:
            raise RuntimeError("Multiple DNS records exist; administrator review required")
        data = {"type": kind, "name": full_name, "content": host, "proxied": False, "ttl": 120}
        if records and all(records[0].get(key) == value for key, value in data.items()):
            return
        result = self.request(
            base + "/" + records[0]["id"] if records else base,
            data, "PUT" if records else "POST", headers,
        )
        if not result.get("success"):
            raise RuntimeError("Cloudflare DNS update rejected")
        confirmed = self.dns_snapshot(sub)
        if len(confirmed) != 1 or not all(confirmed[0].get(key) == value for key, value in data.items()):
            raise RuntimeError("Cloudflare DNS confirmation mismatch")

    def certificate(self, node_id):
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?", node_id):
            raise BusinessError("Invalid node ID")
        directory = Path(self.config.cert_dir)
        try:
            plaintext = json.dumps({
                "base_domain": self.config.base_domain,
                "certificate": (directory / "fullchain.pem").read_text(),
                "private_key": (directory / "privkey.pem").read_text(),
            }).encode()
        except OSError:
            raise BusinessError("Certificate unavailable; renew on master host", 503)
        nonce = os.urandom(12)
        key = hashlib.sha256(self.config.secret.encode()).digest()
        encrypted = AESGCM(key).encrypt(nonce, plaintext, node_id.encode())
        return {"nonce": base64.b64encode(nonce).decode(), "ciphertext": base64.b64encode(encrypted).decode()}
