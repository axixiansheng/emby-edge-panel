import hashlib
import hmac
import json
import math
import os
import re
import secrets
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .security import BusinessError, hostname, subdomain, target_url, username

MAX_BACKUP_BYTES = 8 * 1024 * 1024
TABLES = {
    "users": ("username", "password_hash", "expire_time", "route_limit"),
    "auth_codes": ("code", "duration", "is_used", "bound_user", "route_limit"),
    "nodes": ("id", "name", "host", "port", "secret_key", "is_online", "public_port"),
    "routes": ("id", "username", "subdomain", "target", "node_id"),
    "settings": ("key", "value"),
}


def encoded(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


class RequestGate:
    """Keep normal requests concurrent, drain them only for a data restore."""

    def __init__(self):
        self.condition = threading.Condition()
        self.active = 0
        self.restoring = False

    @contextmanager
    def enter(self, exclusive=False):
        with self.condition:
            if self.restoring:
                raise BusinessError("Data restore in progress; retry shortly", 503)
            if exclusive:
                self.restoring = True
                if not self.condition.wait_for(lambda: self.active == 0, timeout=10):
                    self.restoring = False
                    raise BusinessError("Active requests; retry restore shortly", 409)
            else:
                self.active += 1
        try:
            yield
        finally:
            with self.condition:
                if exclusive:
                    self.restoring = False
                else:
                    self.active -= 1
                self.condition.notify_all()


class Backups:
    def __init__(self, service):
        self.service = service
        self.db, self.config = service.db, service.config
        self.directory = Path(self.db.path).parent / "backups"

    @staticmethod
    def tables(db):
        return {table: [dict(row) for row in db.execute(
            "SELECT " + ",".join(columns) + " FROM " + table + " ORDER BY " + columns[0]
        )] for table, columns in TABLES.items()}

    @staticmethod
    def idle(db):
        if db.execute("SELECT 1 FROM operations WHERE status IN ('pending','running') LIMIT 1").fetchone():
            raise BusinessError("Wait for all route tasks before backup or restore", 409)

    def envelope(self, tables):
        result = {"format": "emby-edge-data", "version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
                  "base_domain": self.config.base_domain, "panel_name": self.config.panel_name, "data": tables}
        result["checksum"] = digest(result)
        if len(encoded(result)) > MAX_BACKUP_BYTES:
            raise BusinessError("Backup exceeds size limit", 413)
        return result

    def export(self):
        with self.db.connect() as db:
            db.execute("BEGIN")
            self.idle(db)
            return self.envelope(self.tables(db))

    def fingerprint(self, tables):
        # Node heartbeat changes are not business edits and must not invalidate previews.
        return digest({**tables, "nodes": [{k: v for k, v in node.items() if k != "is_online"} for node in tables["nodes"]]})

    def validate(self, backup):
        def reject():
            raise BusinessError("Invalid or damaged backup")

        def string(value, limit, empty=False):
            if not isinstance(value, str) or len(value) > limit or (not empty and not value) or "\x00" in value:
                reject()

        def number(value, low, high, integer=True):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high or (integer and not isinstance(value, int)):
                reject()

        try:
            if not isinstance(backup, dict) or len(encoded(backup)) > MAX_BACKUP_BYTES:
                reject()
            if backup.get("format") != "emby-edge-data" or type(backup.get("version")) is not int or backup["version"] != 1:
                raise BusinessError("Unsupported backup format or version")
            checksum = backup.get("checksum")
            if not isinstance(checksum, str) or not hmac.compare_digest(checksum, digest({k: v for k, v in backup.items() if k != "checksum"})):
                reject()
            if backup.get("base_domain") != self.config.base_domain:
                raise BusinessError("Backup domain does not match this panel")
            string(backup.get("created_at"), 64)
            datetime.fromisoformat(backup["created_at"])
            string(backup.get("panel_name"), 200)
            tables = backup["data"]
            if not isinstance(tables, dict) or set(tables) != set(TABLES):
                reject()
            for table, columns in TABLES.items():
                rows = tables[table]
                if not isinstance(rows, list) or len(rows) > 10000:
                    reject()
                keys = set()
                for row in rows:
                    if not isinstance(row, dict) or set(row) != set(columns):
                        reject()
                    key = row[columns[0]]
                    if key in keys:
                        reject()
                    keys.add(key)
            names = set()
            for user in tables["users"]:
                string(user["username"], 24)
                username(user["username"])
                if user["username"].lower() in names or user["username"].lower() == "admin":
                    reject()
                names.add(user["username"].lower())
                number(user["expire_time"], 0, 253402300799, False)
                number(user["route_limit"], 0, 1000)
                value = user["password_hash"]
                string(value, 512)
                modern = re.fullmatch(r"\$argon2id\$v=19\$m=19456,t=2,p=1\$[A-Za-z0-9+/]{22}\$[A-Za-z0-9+/]{43}", value)
                legacy = re.fullmatch(r"[0-9a-f]{64}", value)
                pbkdf = re.fullmatch(r"pbkdf2_sha256\$(\d{6,7})\$([0-9a-f]{2,128})\$[0-9a-f]{64}", value)
                if not (modern or legacy or (pbkdf and len(pbkdf[2]) % 2 == 0 and 100000 <= int(pbkdf[1]) <= 1000000)):
                    reject()
            exact_names = {row["username"] for row in tables["users"]}
            endpoints = set()
            for node in tables["nodes"]:
                number(node["id"], 1, 2147483647)
                string(node["name"], 80)
                string(node["host"], 253)
                host = hostname(node["host"])
                for key in ("port", "public_port"):
                    string(node[key], 5)
                    if not node[key].isdigit() or not 1 <= int(node[key]) <= 65535:
                        reject()
                string(node["secret_key"], 256)
                number(node["is_online"], 0, 1)
                endpoint = (host, int(node["port"]))
                if endpoint in endpoints:
                    reject()
                endpoints.add(endpoint)
            ids = {node["id"] for node in tables["nodes"]}
            subs = set()
            for route in tables["routes"]:
                number(route["id"], 1, 2147483647)
                number(route["node_id"], 1, 2147483647)
                string(route["username"], 24)
                string(route["subdomain"], 63)
                subdomain(route["subdomain"])
                if route["username"] not in exact_names or route["node_id"] not in ids or route["subdomain"] in subs:
                    reject()
                subs.add(route["subdomain"])
                string(route["target"], 2048)
                if target_url(route["target"]) != route["target"]:
                    reject()
            for code in tables["auth_codes"]:
                string(code["code"], 128)
                number(code["duration"], 0, 100000)
                number(code["route_limit"], 1, 1000)
                number(code["is_used"], 0, 1)
                string(code["bound_user"], 24, True)
                if (code["is_used"] and code["bound_user"] not in exact_names) or (not code["is_used"] and code["bound_user"]):
                    reject()
            for setting in tables["settings"]:
                string(setting["key"], 100)
                string(setting["value"], 10000, True)
            return tables
        except (KeyError, TypeError, ValueError, OverflowError, RecursionError):
            reject()

    def signature(self, checksum, current, expires, token):
        value = encoded([checksum, current, expires, hashlib.sha256(token.encode()).hexdigest()])
        return hmac.new(self.config.secret.encode(), value, hashlib.sha256).hexdigest()

    def preview(self, backup, token):
        tables = self.validate(backup)
        with self.db.connect() as db:
            db.execute("BEGIN")
            self.idle(db)
            current = self.tables(db)
        fingerprint, expires = self.fingerprint(current), int(time.time()) + 600
        changes = {}
        for table, columns in TABLES.items():
            old = {row[columns[0]]: row for row in current[table]}
            new = {row[columns[0]]: row for row in tables[table]}
            changes[table] = {"current": len(old), "incoming": len(new), "added": len(new.keys() - old.keys()),
                              "removed": len(old.keys() - new.keys()), "updated": sum(old[key] != new[key] for key in old.keys() & new.keys())}
        return {"counts": changes, "created_at": backup["created_at"], "base_domain": backup["base_domain"],
                "confirmation": {"expires": expires, "fingerprint": fingerprint,
                                 "signature": self.signature(backup["checksum"], fingerprint, expires, token)}}

    def save(self, backup):
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        name = "before-restore-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(6) + ".json"
        path = self.directory / name
        try:
            with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as out:
                out.write(encoded(backup))
                out.flush()
                os.fsync(out.fileno())
            # The recovery file is durable before the live transaction can commit.
            if os.name == "posix":
                descriptor = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            return name
        except OSError:
            raise BusinessError("Could not save safety backup; restore cancelled", 503) from None

    def saved_path(self, name):
        if not isinstance(name, str) or not re.fullmatch(r"before-restore-\d{8}T\d{6}Z-[0-9a-f]{12}\.json", name):
            raise BusinessError("Backup not found", 404)
        path = self.directory / name
        if path.is_symlink() or not path.is_file():
            raise BusinessError("Backup not found", 404)
        return path

    def saved(self):
        if not self.directory.exists():
            return []
        result = []
        for path in sorted(self.directory.glob("before-restore-*.json"), reverse=True)[:20]:
            if path.is_symlink() or not path.is_file():
                continue
            info = path.stat()
            result.append({"name": path.name, "size": info.st_size, "created_at": info.st_mtime})
        return result

    def restore(self, data, token):
        backup, confirmation = data.get("backup"), data.get("confirmation")
        tables = self.validate(backup)
        if not isinstance(confirmation, dict):
            raise BusinessError("Preview this backup before restoring", 409)
        expires, fingerprint, signature = (confirmation.get(key) for key in ("expires", "fingerprint", "signature"))
        if type(expires) is not int or expires < time.time() or expires > time.time() + 601 or not isinstance(fingerprint, str) or not isinstance(signature, str) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint) or not re.fullmatch(r"[0-9a-f]{64}", signature):
            raise BusinessError("Backup preview expired; validate again", 409)
        if not hmac.compare_digest(signature, self.signature(backup["checksum"], fingerprint, expires, token)):
            raise BusinessError("Backup preview expired; validate again", 409)
        with self.db.connect(write=True) as db:
            self.idle(db)
            current = self.tables(db)
            if not hmac.compare_digest(fingerprint, self.fingerprint(current)):
                raise BusinessError("Panel data changed; validate backup again", 409)
            saved = self.save(self.envelope(current))
            jobs = self.reconciliation(current, tables)
            db.execute("DELETE FROM operations")
            db.execute("DELETE FROM operation_logs")
            db.execute("DELETE FROM sessions WHERE token<>?", (token,))
            for table in reversed(TABLES):
                db.execute("DELETE FROM " + table)
            for table, columns in TABLES.items():
                db.executemany("INSERT INTO " + table + "(" + ",".join(columns) + ") VALUES(" + ",".join("?" for _ in columns) + ")",
                               [tuple(row[column] for column in columns) for row in tables[table]])
            db.execute("UPDATE nodes SET is_online=0")
            now = time.time()
            for payload in jobs:
                db.execute("INSERT INTO operations(id,username,action,resource,payload,status,created_at,updated_at) VALUES(?,?,'restore',?,?,'pending',?,?)",
                           (secrets.token_hex(16), payload["username"], payload["sub"], json.dumps(payload), now, now))
            db.execute("INSERT INTO operation_logs(action,status,detail,created_at) VALUES('data_restore','succeeded',?,?)", (saved, now))
        self.service.wake.set()
        return {"msg": "Data restored", "safety_backup": saved, "tasks": len(jobs), "counts": {key: len(value) for key, value in tables.items()}}

    @staticmethod
    def reconciliation(current, incoming):
        old_routes = {row["subdomain"]: row for row in current["routes"]}
        new_routes = {row["subdomain"]: row for row in incoming["routes"]}
        old_nodes = {row["id"]: row for row in current["nodes"]}
        new_nodes = {row["id"]: row for row in incoming["nodes"]}
        jobs = []
        for sub in sorted(old_routes.keys() | new_routes.keys()):
            old, new = old_routes.get(sub), new_routes.get(sub)
            jobs.append({"sub": sub, "username": new["username"] if new else "admin", "target": new["target"] if new else "",
                         "node": new_nodes[new["node_id"]] if new else None, "old": old_nodes[old["node_id"]] if old else None})
        return jobs
