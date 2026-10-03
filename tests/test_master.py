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
        self.dns_calls = []
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
        self.dns_calls.append((sub, host))
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
    def test_cookie_session_persists_without_exposing_token(self):
        with TestClient(create_app(self.config, self.remote, background=False)) as client:
            self.assertEqual({"role": None}, client.get("/api/session").json())
            login = client.post("/api/login", json={"username": "admin", "password": "admin-test", "code": ""})
            cookie = login.headers["set-cookie"]
            self.assertIn("HttpOnly", cookie)
            self.assertIn("SameSite=lax", cookie)
            self.assertIn("Max-Age=3600", cookie)
            state = client.get("/api/session")
            self.assertEqual("admin", state.json()["role"])
            self.assertNotIn("token", state.json())
            self.assertEqual(200, client.get("/api/admin/data").status_code)
            self.assertEqual("no-store", state.headers["cache-control"])

    def test_cookie_requires_origin_for_writes_and_logout_revokes_session(self):
        with TestClient(create_app(self.config, self.remote, background=False)) as client:
            token = client.post("/api/login", json={"username": "admin", "password": "admin-test"}).json()["token"]
            self.assertEqual(403, client.post("/api/logout", json={}).status_code)
            self.assertEqual(403, client.post("/api/logout", json={}, headers={"Origin": "http://testserver", "Sec-Fetch-Site": "cross-site"}).status_code)
            self.assertEqual(403, client.post("/api/logout", json={}, headers={"Origin": "http://evil.example"}).status_code)
            self.assertEqual(200, client.post("/api/logout", json={}, headers={"Origin": "http://testserver"}).status_code)
            self.assertNotIn("emby_session", client.cookies)
            self.assertEqual(401, client.get("/api/admin/data", headers={"Authorization": token}).status_code)

    def test_secure_cookie_on_https_and_configured_public_host(self):
        for origin in ("https://testserver", "http://panel.example.com"):
            with TestClient(create_app(self.config, self.remote, background=False), base_url=origin) as client:
                response = client.post("/api/login", json={"username": "admin", "password": "admin-test"})
                self.assertIn("Secure", response.headers["set-cookie"])

    def test_legacy_token_migrates_to_cookie_without_extending_session(self):
        token = self.service.login({"username": "admin", "password": "admin-test"}, "local")["token"]
        with self.db.connect(write=True) as db:
            expiry = time.time() + 3600
            db.execute("UPDATE sessions SET expire_time=? WHERE token=?", (expiry, token))
        with TestClient(create_app(self.config, self.remote, background=False)) as client:
            result = client.get("/api/session", headers={"Authorization": "Bearer " + token})
            lifetime = int(result.headers["set-cookie"].split("Max-Age=", 1)[1].split(";", 1)[0])
            self.assertGreater(lifetime, 3500)
            self.assertLessEqual(lifetime, 3600)
            self.assertEqual(expiry, result.json()["expires_at"])
            self.assertEqual(200, client.get("/api/admin/data").status_code)

    def test_expired_cookie_cleared_and_header_takes_precedence(self):
        with TestClient(create_app(self.config, self.remote, background=False)) as client:
            token = client.post("/api/login", json={"username": "admin", "password": "admin-test"}).json()["token"]
            self.assertEqual(401, client.get("/api/admin/data", headers={"Authorization": "invalid"}).status_code)
            self.assertIn("emby_session", client.cookies)
            with self.db.connect(write=True) as db:
                db.execute("UPDATE sessions SET expire_time=0 WHERE token=?", (token,))
            self.assertEqual(401, client.get("/api/session").status_code)
            self.assertNotIn("emby_session", client.cookies)

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
        self.assertEqual("succeeded", self.service.operation(result["operation_id"], user)["status"])
        with self.db.connect() as db:
            due = db.execute("SELECT next_run FROM operations WHERE id=?", (result["operation_id"],)).fetchone()[0]
        self.assertGreater(due, time.time() + 175)
        self.assertLess(due, time.time() + 181)
        self.immediate(result["operation_id"])
        self.run_next()
        self.assertNotIn((1, route["subdomain"]), self.remote.maps)
        self.assertIn((2, route["subdomain"]), self.remote.maps)

    def test_update_dns_failure_restores_old_node_origin(self):
        route, _, user = self.add_route()
        result = self.service.enqueue("update", {"id": route["id"], "node_id": 2, "target": "https://1.1.1.1"}, user)
        self.remote.fail_dns = True
        for _ in range(3):
            self.immediate(result["operation_id"])
            self.run_next()
        self.remote.fail_dns = False
        self.immediate(result["operation_id"])
        self.run_next()
        self.assertEqual(route["target"], self.remote.maps[(1, route["subdomain"])])
        self.assertNotIn((2, route["subdomain"]), self.remote.maps)
        self.assertEqual("failed", self.service.operation(result["operation_id"], user)["status"])

    def test_same_node_update_does_not_write_dns(self):
        route, _, user = self.add_route()
        self.remote.dns_calls.clear()
        self.remote.fail_dns = True
        result = self.service.enqueue("update", {"id": route["id"], "target": "https://1.1.1.1"}, user)
        self.run_next()
        self.assertEqual([], self.remote.dns_calls)
        self.assertEqual("succeeded", self.service.operation(result["operation_id"], user)["status"])

    def test_admin_update_visible_to_owner_but_not_other_users(self):
        route, _, user = self.add_route()
        other = self.register("Other")
        result = self.service.enqueue("update", {"id": route["id"], "node_id": 2}, self.admin)
        task_id = result["operation_id"]
        self.assertEqual("admin", self.service.operation(task_id, user)["username"])
        self.assertIn(task_id, [o["id"] for o in self.service.data(user)["operations"]])
        self.assertNotIn(task_id, [o["id"] for o in self.service.data(other)["operations"]])
        with self.assertRaises(BusinessError):
            self.service.operation(task_id, other)
        self.run_next()
        self.assertEqual("succeeded", self.service.operation(task_id, user)["status"])
        following = self.service.enqueue("update", {"id": route["id"], "target": "https://1.1.1.1"}, user)
        self.run_next()
        self.assertEqual("succeeded", self.service.operation(following["operation_id"], self.admin)["status"])

    def test_rapid_return_to_old_node_never_deletes_active_mapping(self):
        route, _, user = self.add_route()
        first = self.service.enqueue("update", {"id": route["id"], "node_id": 2}, user)["operation_id"]
        self.run_next()
        second = self.service.enqueue("update", {"id": route["id"], "node_id": 1, "target": "https://1.1.1.1"}, user)["operation_id"]
        self.run_next()
        self.immediate(first)
        self.run_next()
        self.assertEqual("https://1.1.1.1", self.remote.maps[(1, route["subdomain"])])
        self.immediate(second)
        self.run_next()
        self.assertNotIn((2, route["subdomain"]), self.remote.maps)

    def test_retirement_retry_does_not_relock_route_and_recovers_on_restart(self):
        route, _, user = self.add_route()
        task = self.service.enqueue("update", {"id": route["id"], "node_id": 2}, user)["operation_id"]
        self.run_next()
        with self.assertRaises(BusinessError):
            self.service.admin_action("/admin/delete_node", {"id": 1})
        self.immediate(task)
        claimed = self.service.claim()
        self.assertEqual("retiring", claimed["phase"])
        self.db.initialize()
        self.remote.fail_delete = True
        self.run_next()
        self.assertEqual("succeeded", self.service.operation(task, user)["status"])
        self.assertEqual("cleanup", self.service.operation(task, user)["phase"])
        self.remote.fail_delete = False
        following = self.service.enqueue("update", {"id": route["id"], "target": "https://1.1.1.1"}, user)["operation_id"]
        self.run_next()
        self.assertEqual("succeeded", self.service.operation(following, user)["status"])
        self.immediate(task)
        self.run_next()
        self.assertEqual("completed", self.service.operation(task, user)["phase"])

    def test_retirement_defers_while_route_change_is_claimed(self):
        route, _, user = self.add_route()
        task = self.service.enqueue("update", {"id": route["id"], "node_id": 2}, user)["operation_id"]
        self.run_next()
        self.service.enqueue("update", {"id": route["id"], "node_id": 1}, user)
        pending = self.service.claim()
        self.immediate(task)
        self.run_next()
        self.assertIn((1, route["subdomain"]), self.remote.maps)
        self.assertEqual("cleanup", self.service.operation(task, user)["phase"])
        self.service.execute(pending)
        self.immediate(task)
        self.run_next()
        self.assertIn((1, route["subdomain"]), self.remote.maps)

    def test_active_tasks_are_not_hidden_by_hundred_newer_records(self):
        route, _, user = self.add_route()
        task = self.service.enqueue("update", {"id": route["id"]}, self.admin)["operation_id"]
        with self.db.connect(write=True) as db:
            for i in range(105):
                db.execute("INSERT INTO operations(id,username,owner_username,action,resource,payload,status,phase,created_at,updated_at) VALUES(?,?,?,'update',?,'{}','succeeded','completed',?,?)",
                           (str(i), "admin", user["username"], "historical-" + str(i), time.time() + i, time.time()))
        self.assertEqual(task, self.service.data(user)["operations"][0]["id"])

    def test_retirement_ttl_uses_actual_value_and_auto_fallback(self):
        self.assertEqual(180, self.service.retirement_delay([{"ttl": 120}]))
        self.assertEqual(360, self.service.retirement_delay([{"ttl": 1}]))
        self.assertEqual(3660, self.service.retirement_delay([{"ttl": 3600}]))
        self.assertEqual(360, self.service.retirement_delay([]))

    def test_legacy_pending_cleanup_unlocks_without_losing_deadline_or_owner(self):
        route, previous, user = self.add_route()
        task = self.service.enqueue("update", {"id": route["id"], "node_id": 2}, self.admin)["operation_id"]
        self.run_next()
        with self.db.connect(write=True) as db:
            deadline = db.execute("SELECT next_run FROM operations WHERE id=?", (task,)).fetchone()[0]
            db.execute("UPDATE operations SET status='pending' WHERE id=?", (task,))
            db.execute("UPDATE operations SET phase='cleanup' WHERE id=?", (previous,))
            db.execute("ALTER TABLE operations DROP COLUMN owner_username")
        self.db.initialize()
        self.assertEqual("succeeded", self.service.operation(task, user)["status"])
        self.assertEqual(deadline, self.service.operation(task, user)["next_run"])
        self.assertEqual("cleanup", self.service.operation(task, user)["phase"])
        self.assertEqual("completed", self.service.operation(previous, user)["phase"])
        self.assertEqual(user["username"], self.service.operation(task, user)["owner_username"])
        self.assertIn((1, route["subdomain"]), self.remote.maps)

    def test_retirement_network_write_is_serialized_with_following_update(self):
        route, _, user = self.add_route()
        task = self.service.enqueue("update", {"id": route["id"], "node_id": 2}, user)["operation_id"]
        self.run_next()
        self.immediate(task)
        retiring = self.service.claim()
        self.service.enqueue("update", {"id": route["id"], "node_id": 1, "target": "https://1.1.1.1"}, user)
        following = self.service.claim()
        worker = self.remote.worker
        # Retirement sees the claimed foreground task and defers, then the update
        # holds the resource lock so a later retirement cannot race its writes.
        self.service.execute(retiring)
        self.immediate(task)
        retiring = self.service.claim()
        started, proceed = threading.Event(), threading.Event()
        def paused_update(node, action, sub, target):
            if action == "add":
                started.set()
                proceed.wait(3)
            return worker(node, action, sub, target)
        self.remote.worker = paused_update
        a = threading.Thread(target=self.service.execute, args=(following,))
        b = threading.Thread(target=self.service.execute, args=(retiring,))
        a.start()
        self.assertTrue(started.wait(2))
        b.start()
        time.sleep(.05)
        self.assertTrue(b.is_alive())
        proceed.set()
        a.join(3)
        b.join(3)
        self.assertFalse(a.is_alive() or b.is_alive())
        self.assertEqual("https://1.1.1.1", self.remote.maps[(1, route["subdomain"])])

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

    def test_public_branding_exposes_only_panel_name(self):
        app = create_app(self.config, self.remote, background=False)
        with TestClient(app) as client:
            response = client.get("/api/public/config")
            self.assertEqual(200, response.status_code)
            self.assertEqual({"panel_name": self.config.panel_name}, response.json())
            self.assertEqual("no-store", response.headers["cache-control"])

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
            self.assertEqual(404, client.get("/assets/ui/app.py").status_code)
            self.assertEqual(404, client.get("/assets/not-a-build-chunk.js").status_code)


if __name__ == "__main__":
    unittest.main()
