import copy
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from starlette.testclient import TestClient

from master.app import create_app
from master.backups import RequestGate, digest
from master.security import BusinessError, password_verify
import test_master


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_master.MasterTests()
        self.fixture.setUp()
        self.service = self.fixture.service
        self.db = self.fixture.db
        self.backups = self.service.backups
        self.route, _, self.user = self.fixture.add_route()

    def tearDown(self):
        self.fixture.tearDown()

    def edited(self, change):
        backup = self.backups.export()
        change(backup["data"])
        backup["checksum"] = digest({k: v for k, v in backup.items() if k != "checksum"})
        return backup

    def restore(self, backup, token="admin-test-token"):
        preview = self.backups.preview(backup, token)
        return self.backups.restore({"backup": backup, "confirmation": preview["confirmation"]}, token)

    def test_round_trip_password_quota_codes_and_private_safety_backup(self):
        backup = self.backups.export()
        self.service.admin_action("/admin/update_user_limit", {"username": "Tester", "route_limit": 12})
        result = self.restore(backup)
        self.assertEqual(1, result["tasks"])
        with self.db.connect() as db:
            user = db.execute("SELECT * FROM users WHERE username='Tester'").fetchone()
            self.assertEqual(3, user["route_limit"])
            self.assertTrue(password_verify("test-password", user["password_hash"]))
            self.assertEqual(0, db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])
        safety = json.loads(self.backups.saved_path(result["safety_backup"]).read_text())
        self.assertEqual(12, safety["data"]["users"][0]["route_limit"])
        self.fixture.run_next()
        self.assertEqual(backup["data"]["routes"], self.backups.export()["data"]["routes"])

    def test_import_into_empty_panel_reconciles_existing_dns(self):
        backup = self.backups.export()
        with self.db.connect(write=True) as db:
            for table in ("routes", "users", "nodes", "auth_codes", "operations"):
                db.execute("DELETE FROM " + table)
        self.restore(backup)
        self.fixture.run_next()
        self.assertEqual(self.route["target"], self.fixture.remote.maps[(1, self.route["subdomain"])])

    def test_checksum_domain_schema_hashes_and_associations_rejected_without_writes(self):
        original = self.backups.export()
        damaged = copy.deepcopy(original)
        damaged["data"]["users"][0]["route_limit"] = 99
        with self.assertRaises(BusinessError):
            self.restore(damaged)
        changes = [
            lambda data: data["routes"][0].update(node_id=999),
            lambda data: data["users"][0].update(password_hash="$argon2id$v=19$m=999999,t=2,p=1$x$x"),
            lambda data: data["routes"][0].update(target="http://127.0.0.1"),
            lambda data: data["users"].append(dict(data["users"][0], username="tester")),
            lambda data: data["auth_codes"][0].update(bound_user="Missing"),
            lambda data: data["users"][0].update(route_limit=True),
            lambda data: data["nodes"][0].update(port="99999"),
        ]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(BusinessError):
                self.restore(self.edited(change))
        for key, value in (("base_domain", "another.example"), ("version", 2)):
            backup = copy.deepcopy(original)
            backup[key] = value
            backup["checksum"] = digest({k: v for k, v in backup.items() if k != "checksum"})
            with self.assertRaises(BusinessError):
                self.restore(backup)
        self.assertEqual(original["data"], self.backups.export()["data"])

    def test_restore_requires_unchanged_data_valid_preview_and_same_session(self):
        backup = self.backups.export()
        preview = self.backups.preview(backup, "one")["confirmation"]
        with self.assertRaises(BusinessError):
            self.backups.restore({"backup": backup, "confirmation": preview}, "two")
        with patch("master.backups.time.time", return_value=time.time() + 700), self.assertRaises(BusinessError):
            self.backups.restore({"backup": backup, "confirmation": preview}, "one")
        self.service.admin_action("/admin/update_announcement", {"text": "new"})
        with self.assertRaises(BusinessError):
            self.backups.restore({"backup": backup, "confirmation": preview}, "one")

    def test_active_route_tasks_block_export_and_import(self):
        backup = self.backups.export()
        preview = self.backups.preview(backup, "admin")["confirmation"]
        self.service.enqueue("update", {"id": self.route["id"], "target": "https://1.1.1.1"}, self.user)
        for action in (self.backups.export, lambda: self.backups.restore({"backup": backup, "confirmation": preview}, "admin")):
            with self.assertRaises(BusinessError):
                action()

    def test_malformed_preview_signature_is_rejected(self):
        backup = self.backups.export()
        preview = self.backups.preview(backup, "admin")["confirmation"]
        for key in ("signature", "fingerprint"):
            with self.subTest(key=key), self.assertRaises(BusinessError):
                self.backups.restore({"backup": backup, "confirmation": {**preview, key: "\u4e2d"}}, "admin")

    def test_safety_backup_failure_leaves_live_data_unchanged(self):
        backup = self.backups.export()
        with patch.object(self.backups, "save", side_effect=BusinessError("Disk full", 503)), self.assertRaises(BusinessError):
            self.restore(backup)
        self.assertEqual(backup["data"], self.backups.export()["data"])

    def test_database_failure_rolls_back_and_keeps_safety_copy(self):
        backup = self.backups.export()
        with self.db.connect(write=True) as db:
            db.execute("CREATE TRIGGER fail_restore BEFORE INSERT ON users BEGIN SELECT RAISE(ABORT, 'injected'); END")
        with self.assertRaises(Exception):
            self.restore(backup)
        self.assertEqual(backup["data"], self.backups.export()["data"])
        self.assertEqual(1, len(self.backups.saved()))

    def test_restore_retries_then_recovers_without_losing_desired_state(self):
        backup = self.edited(lambda data: data["routes"][0].update(target="https://1.1.1.1"))
        self.restore(backup)
        self.fixture.remote.fail_dns = True
        operation_id = self.fixture.run_next()
        with self.db.connect() as db:
            self.assertEqual("https://1.1.1.1", db.execute("SELECT target FROM routes").fetchone()[0])
            self.assertEqual("pending", db.execute("SELECT status FROM operations WHERE id=?", (operation_id,)).fetchone()[0])
        self.fixture.remote.fail_dns = False
        self.fixture.immediate(operation_id)
        self.fixture.run_next()
        with self.db.connect() as db:
            self.assertEqual("succeeded", db.execute("SELECT status FROM operations WHERE id=?", (operation_id,)).fetchone()[0])

    def test_cross_node_restore_keeps_old_mapping_until_ttl_and_removes_extras(self):
        backup = self.edited(lambda data: data["routes"][0].update(node_id=2))
        self.restore(backup)
        operation_id = self.fixture.run_next()
        self.assertIn((1, self.route["subdomain"]), self.fixture.remote.maps)
        self.assertIn((2, self.route["subdomain"]), self.fixture.remote.maps)
        with self.db.connect() as db:
            self.assertGreater(db.execute("SELECT next_run FROM operations WHERE id=?", (operation_id,)).fetchone()[0], time.time() + 350)
        self.fixture.immediate(operation_id)
        self.fixture.run_next()
        self.assertNotIn((1, self.route["subdomain"]), self.fixture.remote.maps)
        backup = self.edited(lambda data: data["routes"].clear())
        self.restore(backup)
        self.fixture.run_next()
        self.assertNotIn((2, self.route["subdomain"]), self.fixture.remote.maps)
        self.assertNotIn(self.route["subdomain"], self.fixture.remote.records)

    def test_dns_conflict_is_not_overwritten(self):
        backup = self.backups.export()
        self.fixture.remote.records[self.route["subdomain"]] = "9.9.9.9"
        self.restore(backup)
        self.fixture.run_next()
        self.assertEqual("9.9.9.9", self.fixture.remote.records[self.route["subdomain"]])

    def test_api_permissions_download_preview_and_restore(self):
        app = create_app(self.fixture.config, self.fixture.remote, background=False)
        with TestClient(app) as client:
            self.assertEqual(401, client.get("/api/admin/backups/export").status_code)
            login = client.post("/api/login", json={"username": "Tester", "password": "test-password"}).json()
            headers = {"Authorization": login["token"]}
            self.assertEqual(403, client.post("/api/admin/backups/restore", headers=headers, json={}).status_code)
            login = client.post("/api/login", json={"username": "admin", "password": "admin-test"}).json()
            headers = {"Authorization": login["token"]}
            result = client.get("/api/admin/backups/export", headers=headers)
            self.assertIn("attachment", result.headers["content-disposition"])
            self.assertEqual("no-store", result.headers["cache-control"])
            backup = result.json()
            preview = client.post("/api/admin/backups/preview", headers=headers, json={"backup": backup}).json()
            restored = client.post("/api/admin/backups/restore", headers=headers, json={"backup": backup, "confirmation": preview["confirmation"]})
            self.assertEqual(200, restored.status_code)
            saved = client.get("/api/admin/backups/list", headers=headers).json()["backups"]
            self.assertEqual(1, len(saved))
            self.assertEqual(200, client.get("/api/admin/backups/saved/" + saved[0]["name"], headers=headers).status_code)
            self.assertEqual(404, client.get("/api/admin/backups/saved/panel.db", headers=headers).status_code)

    def test_gate_waits_for_inflight_login_and_rejects_new_requests(self):
        gate = RequestGate()
        started, release, exclusive = threading.Event(), threading.Event(), threading.Event()
        def login():
            with gate.enter():
                started.set()
                release.wait(2)
        def restore():
            with gate.enter(exclusive=True):
                exclusive.set()
        reader = threading.Thread(target=login)
        writer = threading.Thread(target=restore)
        reader.start()
        started.wait(1)
        writer.start()
        deadline = time.monotonic() + 1
        while not gate.restoring and time.monotonic() < deadline:
            time.sleep(.001)
        try:
            self.assertFalse(exclusive.is_set())
            with self.assertRaises(BusinessError):
                with gate.enter():
                    pass
        finally:
            release.set()
            reader.join(2)
            writer.join(2)
        self.assertTrue(exclusive.is_set())
