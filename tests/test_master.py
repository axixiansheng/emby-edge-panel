import base64
import hashlib
import hmac
import json
import os
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from starlette.testclient import TestClient

from master.app import create_app
from master.config import Config
from master.database import Database
from master.integrations import Integrations
from master.security import BusinessError, password_verify, target_url
from master.service import Service


class FakeRemote:
    def __init__(self):
        self.maps, self.records, self.calls = {}, {}, []
        self.fail_dns = False
        self.fail_delete = False
        self.delay = 0

    def worker(self, node, action, sub, target):
        if self.delay:
            time.sleep(self.delay)
        self.calls.append((node["id"], action, sub, target))
        if action == "delete" and self.fail_delete:
            raise RuntimeError("Worker unreachable")
        if action == "add":
            self.maps[(node["id"], sub)] = target
        else:
            self.maps.pop((node["id"], sub), None)

    def dns(self, sub, host=None):
        if self.fail_dns:
            raise RuntimeError("DNS unavailable")
        if host is None:
            self.records.pop(sub, None)
        else:
            self.records[sub] = host

    def dns_snapshot(self, sub):
        if sub in self.records:
            return [{"content": self.records[sub], "ttl": 120}]
        return []

    def dns_restore(self, sub, records):
        self.dns(sub, records[0]["content"] if records else None)

    def health(self, node):
        return None


class MasterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = Config(str(Path(self.temp.name) / "panel.db"), "admin-test",
                             "cf-test", "zone-test", "example.com", "Test Panel",
                             "panel.example.com", "secret-test", self.temp.name)
        self.db = Database(self.config.db_file)
        self.db.initialize()
        self.remote = FakeRemote()
        self.service = Service(self.config, self.db, self.remote)
        self.admin = {"username": "admin", "role": "admin"}
        with self.db.connect(write=True) as db:
            for number in (1, 2):
                db.execute("INSERT INTO nodes(id,name,host,port,secret_key,is_online,public_port) VALUES(?,?,?,?,?,1,?)",
                           (number, "Node" + str(number), "8.8.8." + str(number), "12345", "key", "45678"))

    def tearDown(self):
        self.service.close()
        self.temp.cleanup()

    def register(self, name="Tester", limit=3, code=None):
        if code is None:
            code = self.service.admin_action("/admin/generate", {"route_limit": limit})["code"]
        result = self.service.login({"username": name, "password": "test-password", "code": code}, name)
        return self.service.session(result["token"])

    def add_route(self, user=None, suffix="one"):
        user = user or self.register()
        result = self.service.enqueue("add", {"node_id": 1, "subdomain": suffix, "target": "https://8.8.8.8"}, user)
        self.run_next()
        with self.db.connect() as db:
            row = db.execute("SELECT * FROM routes WHERE subdomain=?", (user["username"].lower() + "-" + suffix,)).fetchone()
        return dict(row), result["operation_id"], user

    def run_next(self):
        operation = self.service.claim()
        self.assertIsNotNone(operation)
        self.service.execute(operation)
        return operation["id"]

    def immediate(self, operation_id):
        with self.db.connect(write=True) as db:
            db.execute("UPDATE operations SET next_run=0 WHERE id=?", (operation_id,))

    def test_50_concurrent_registrations_have_no_client_queue(self):
        codes = [self.service.admin_action("/admin/generate", {"route_limit": 3})["code"] for _ in range(50)]
        start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(lambda pair: self.register("User" + str(pair[0]), code=pair[1]), enumerate(codes)))
        elapsed = time.perf_counter() - start
        self.assertEqual(50, len(results))
        with self.db.connect() as db:
            self.assertEqual(50, db.execute("SELECT COUNT(*) FROM users").fetchone()[0])
            self.assertEqual(50, db.execute("SELECT COUNT(*) FROM auth_codes WHERE is_used=1").fetchone()[0])
        print(f"\n50 concurrent registrations: {elapsed:.3f}s")

    def test_single_code_cannot_be_redeemed_twice(self):
        code = self.service.admin_action("/admin/generate", {"route_limit": 3})["code"]
        def attempt(number):
            try:
                return self.register("Race" + str(number), code=code)
            except BusinessError:
                return None
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(attempt, range(8)))
        self.assertEqual(1, sum(item is not None for item in results))

    def test_case_insensitive_duplicate_registration(self):
        self.register("MixedCase")
        with self.assertRaises(BusinessError):
            self.register("mixedcase")

    def test_case_insensitive_login(self):
        self.register("MixedCase")
        result = self.service.login({"username": "mixedcase", "password": "test-password"}, "new-ip")
        self.assertEqual("MixedCase", self.service.session(result["token"])["username"])

    def test_legacy_passwords(self):
        password = "old-password"
        legacy = hashlib.sha256(password.encode()).hexdigest()
        fixed = hashlib.pbkdf2_hmac("sha256", password.encode(), b"emby-panel-v1", 240000).hex()
        self.assertTrue(password_verify(password, legacy))
        self.assertTrue(password_verify(password, fixed))
        self.assertFalse(password_verify("wrong", fixed))

    def test_quoted_docker_environment_preserves_existing_configuration(self):
        with patch.dict(os.environ, {
            "EMBY_ENV_FILE": str(Path(self.temp.name, "missing.env")),
            "PANEL_PASSWORD": '"test$literal-password"', "CF_API_TOKEN": '"token"',
            "CF_ZONE_ID": '"zone"', "BASE_DOMAIN": '"example.com"',
            "GLOBAL_SECRET_KEY": '"secret"', "PANEL_NAME": '"Test Panel"',
        }):
            config = Config.load()
        self.assertEqual("test$literal-password", config.panel_password)
        self.assertEqual("example.com", config.base_domain)
        self.assertEqual("Test Panel", config.panel_name)

    def test_concurrent_route_quota_reserves_pending_operations(self):
        user = self.register(limit=1)
        def attempt(number):
            try:
                return self.service.enqueue("add", {"node_id": 1, "subdomain": str(number), "target": "https://8.8.8.8"}, user)
            except BusinessError:
                return None
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(attempt, range(8)))
        self.assertEqual(1, sum(item is not None for item in results))

    def test_same_node_origin_update_never_deletes_new_route(self):
        route, _, user = self.add_route()
        self.remote.calls.clear()
        operation = self.service.enqueue("update", {"id": route["id"], "node_id": 1, "target": "https://1.1.1.1"}, user)
        self.run_next()
        self.assertEqual("https://1.1.1.1", self.remote.maps[(1, route["subdomain"])])
        self.assertFalse(any(call[1] == "delete" for call in self.remote.calls))
        self.assertEqual("succeeded", self.service.operation(operation["operation_id"], user)["status"])

    def test_cross_node_migration_preserves_old_worker_until_dns_ttl(self):
        route, _, user = self.add_route()
        result = self.service.enqueue("update", {"id": route["id"], "node_id": 2}, user)
        self.run_next()
        self.assertIn((1, route["subdomain"]), self.remote.maps)
        self.assertIn((2, route["subdomain"]), self.remote.maps)
        self.assertEqual("cleanup", self.service.operation(result["operation_id"], user)["phase"])
        self.immediate(result["operation_id"])
        self.run_next()
        self.assertNotIn((1, route["subdomain"]), self.remote.maps)
        self.assertIn((2, route["subdomain"]), self.remote.maps)

    def test_update_dns_failure_restores_same_node_origin(self):
        route, _, user = self.add_route()
        result = self.service.enqueue("update", {"id": route["id"], "target": "https://1.1.1.1"}, user)
        self.remote.fail_dns = True
        for _ in range(3):
            self.immediate(result["operation_id"])
            self.run_next()
        self.remote.fail_dns = False
        self.immediate(result["operation_id"])
        self.run_next()
        self.assertEqual(route["target"], self.remote.maps[(1, route["subdomain"])])
        self.assertEqual("failed", self.service.operation(result["operation_id"], user)["status"])

    def test_existing_unmanaged_dns_is_never_deleted_on_add_failure(self):
        user = self.register()
        self.remote.records["tester-foreign"] = "9.9.9.9"
        result = self.service.enqueue("add", {"node_id": 1, "subdomain": "foreign", "target": "https://8.8.8.8"}, user)
        for _ in range(4):
            self.immediate(result["operation_id"])
            self.run_next()
        self.assertEqual("9.9.9.9", self.remote.records["tester-foreign"])
        self.assertEqual("failed", self.service.operation(result["operation_id"], user)["status"])

    def test_delete_cleanup_is_durable_and_blocks_node_deletion(self):
        route, _, user = self.add_route()
        result = self.service.enqueue("delete", {"id": route["id"]}, user)
        self.remote.fail_delete = True
        self.run_next()
        self.assertNotIn(route["subdomain"], self.remote.records)
        self.assertEqual("cleanup", self.service.operation(result["operation_id"], user)["phase"])
        with self.assertRaises(BusinessError):
            self.service.admin_action("/admin/delete_node", {"id": 1})
        self.remote.fail_delete = False
        self.immediate(result["operation_id"])
        self.run_next()
        self.assertEqual("succeeded", self.service.operation(result["operation_id"], user)["status"])

    def test_restart_recovers_claimed_operation(self):
        user = self.register()
        result = self.service.enqueue("add", {"node_id": 1, "subdomain": "restart", "target": "https://8.8.8.8"}, user)
        self.service.claim()
        self.db.initialize()
        self.run_next()
        self.assertEqual("succeeded", self.service.operation(result["operation_id"], user)["status"])

    def test_duplicate_operation_is_rejected(self):
        route, _, user = self.add_route()
        self.service.enqueue("delete", {"id": route["id"]}, user)
        with self.assertRaises(BusinessError):
            self.service.enqueue("update", {"id": route["id"]}, user)

    def test_user_cannot_edit_another_users_route(self):
        route, op_id, owner = self.add_route()
        other = self.register("Other")
        with self.assertRaises(BusinessError):
            self.service.enqueue("delete", {"id": route["id"]}, other)
        with self.assertRaises(BusinessError):
            self.service.operation(op_id, other)
        self.assertEqual(owner["username"], self.service.data(owner)["routes"][0]["user"])
        self.assertEqual([], self.service.data(other)["routes"])

    def test_slow_worker_does_not_lock_registration(self):
        user = self.register()
        self.service.enqueue("add", {"node_id": 1, "subdomain": "slow", "target": "https://8.8.8.8"}, user)
        self.remote.delay = 1
        thread = threading.Thread(target=self.run_next)
        thread.start()
        time.sleep(.05)
        start = time.perf_counter()
        self.register("FastUser")
        elapsed = time.perf_counter() - start
        thread.join()
        self.assertLess(elapsed, .9)

    def test_target_rejects_private_ip_and_nginx_injection(self):
        for value in ("http://127.0.0.1", "http://10.0.0.1", "http://[::1]", 'https://example.com/";evil;', "ftp://example.com", "https://u:p@example.com", "https://example.com/#fragment"):
            with self.subTest(value=value), self.assertRaises(BusinessError):
                target_url(value)

    def test_worker_certificate_protocol_compatible(self):
        Path(self.temp.name, "fullchain.pem").write_text("certificate")
        Path(self.temp.name, "privkey.pem").write_text("private-key")
        remote = Integrations(self.config)
        data = remote.certificate("node-test")
        key = hashlib.sha256(self.config.secret.encode()).digest()
        decrypted = AESGCM(key).decrypt(base64.b64decode(data["nonce"]), base64.b64decode(data["ciphertext"]), b"node-test")
        self.assertEqual("example.com", json.loads(decrypted)["base_domain"])

    def test_api_validation_permissions_and_logout(self):
        app = create_app(self.config, self.remote, background=False)
        with TestClient(app) as client:
            self.assertEqual(200, client.get("/healthz").status_code)
            self.assertEqual(200, client.get("/").status_code)
            self.assertEqual(200, client.get("/panel").status_code)
            self.assertEqual(200, client.get("/admin-panel").status_code)
            self.assertEqual(200, client.get("/assets/panel.js").status_code)
            self.assertEqual(404, client.get("/assets/config.py").status_code)
            self.assertEqual(400, client.post("/api/login", json=[]).status_code)
            self.assertEqual(413, client.post("/api/login", content=b"x" * 65537).status_code)
            self.assertEqual(403, client.post("/api/login", json={}, headers={"Origin": "https://evil.com"}).status_code)
            self.assertEqual(401, client.get("/api/admin/data").status_code)
            login = client.post("/api/login", json={"username": "admin", "password": "admin-test"})
            self.assertEqual(200, login.status_code)
            token = login.json()["token"]
            headers = {"Authorization": token}
            self.assertEqual(200, client.get("/api/admin/data", headers=headers).status_code)
            self.assertEqual(404, client.post("/api/admin/unknown", json={}, headers=headers).status_code)
            self.assertEqual(200, client.post("/api/logout", json={}, headers=headers).status_code)
            self.assertEqual(401, client.get("/api/admin/data", headers=headers).status_code)

    def test_user_admin_endpoint_forbidden(self):
        self.register()
        app = create_app(self.config, self.remote, background=False)
        with TestClient(app) as client:
            login = client.post("/api/login", json={"username": "Tester", "password": "test-password"})
            headers = {"Authorization": login.json()["token"]}
            self.assertEqual(403, client.get("/api/admin/data", headers=headers).status_code)
            self.assertEqual(403, client.post("/api/admin/update_announcement", json={"text": "bad"}, headers=headers).status_code)

    def test_frontend_assets_keep_security_headers_and_closed_allowlist(self):
        app = create_app(self.config, self.remote, background=False)
        with TestClient(app) as client:
            for name in ("index.html", "panel.js", "panel.css", "lucide.min.js", "edge-mark.svg", "edge-mesh.svg", "edge-glass.webp", "manrope-latin.woff2", "noto-ui.woff2"):
                with self.subTest(asset=name):
                    response = client.get("/assets/" + name)
                    self.assertEqual(200, response.status_code)
                    self.assertEqual("no-cache", response.headers["cache-control"])
                    self.assertEqual("nosniff", response.headers["x-content-type-options"])
                    self.assertIn("script-src 'self'", response.headers["content-security-policy"])
                    self.assertNotIn("'unsafe-inline'", response.headers["content-security-policy"])
                    if name.endswith(".svg"):
                        self.assertIn("image/svg+xml", response.headers["content-type"])
            self.assertEqual(404, client.get("/assets/security.py").status_code)
            self.assertEqual(404, client.get("/assets/unknown.svg").status_code)


if __name__ == "__main__":
    unittest.main()
