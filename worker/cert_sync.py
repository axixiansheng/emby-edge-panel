#!/usr/bin/env python3
import base64
import hashlib
import hmac
import json
import os
import subprocess
import tempfile
import time
import urllib.request

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ENV_FILE = "/opt/emby_agent/.env"
CERT_DIR = "/etc/ssl/emby"


def load_env():
    values = {}
    with open(ENV_FILE, encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"\'')
    return values


def atomic_write(path, content, mode):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".emby-cert-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    env = load_env()
    master = env["MASTER_IP"]
    secret = env["SECRET_KEY"]
    node_id = env["NODE_ID"]
    timestamp = int(time.time())
    signature = hmac.new(
        secret.encode(),
        f"{timestamp}:worker-bootstrap:{node_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    request = urllib.request.Request(
        f"http://{master}/api/worker/bootstrap",
        data=json.dumps({"t": timestamp, "node_id": node_id, "sign": signature}).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "Host": "emby-worker-bootstrap"},
    )
    with urllib.request.urlopen(request, timeout=190) as response:
        result = json.load(response)
    if "ciphertext" not in result or "nonce" not in result:
        raise RuntimeError(result.get("msg", "Master did not return a certificate"))
    key = hashlib.sha256(secret.encode()).digest()
    plaintext = AESGCM(key).decrypt(
        base64.b64decode(result["nonce"]),
        base64.b64decode(result["ciphertext"]),
        node_id.encode(),
    )
    data = json.loads(plaintext.decode())
    old_certificate = ""
    certificate_path = os.path.join(CERT_DIR, "fullchain.pem")
    if os.path.exists(certificate_path):
        with open(certificate_path, encoding="utf-8") as handle:
            old_certificate = handle.read()
    atomic_write(certificate_path, data["certificate"], 0o644)
    atomic_write(os.path.join(CERT_DIR, "privkey.pem"), data["private_key"], 0o600)
    if old_certificate and old_certificate != data["certificate"]:
        subprocess.run(["nginx", "-s", "reload"], check=False)
    print(data["base_domain"])


if __name__ == "__main__":
    main()
