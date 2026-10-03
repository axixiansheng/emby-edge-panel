import hashlib
import hmac
import json
import logging
import secrets
import sqlite3
import threading
import time

from .security import BusinessError, hostname, integer, password_hash, password_verify, subdomain, target_url, text, username
from .backups import Backups, RequestGate

logger = logging.getLogger("emby-panel")
SESSION_TTL = 3600


class Service:
    def __init__(self, config, database, integrations):
        self.config, self.db, self.remote = config, database, integrations
        self.stop, self.wake = threading.Event(), threading.Event()
        self.threads, self.failures = [], {}
        self.login_lock = threading.Lock()
        self.route_locks = [threading.Lock() for _ in range(64)]
        self.gate = RequestGate()
        self.backups = Backups(self)

    def start(self):
        for name, target in (("routes-0", self.operation_loop), ("routes-1", self.operation_loop), ("health", self.heartbeat_loop)):
            thread = threading.Thread(target=target, name=name, daemon=True)
            thread.start()
            self.threads.append(thread)

    def close(self):
        self.stop.set()
        self.wake.set()
        deadline = time.monotonic() + 40
        for thread in self.threads:
            thread.join(timeout=max(0, deadline - time.monotonic()))
        if not any(thread.is_alive() for thread in self.threads):
            self.db.close()

    def session(self, token, activity=False, activity_age=0):
        with self.db.connect(write=activity) as db:
            now = time.time()
            row = db.execute("SELECT username,role,expire_time FROM sessions WHERE token=? AND expire_time>?", (token, now)).fetchone()
            if row is None:
                raise BusinessError("Session expired", 401)
            if row["role"] == "user":
                user = db.execute("SELECT expire_time FROM users WHERE username=?", (row["username"],)).fetchone()
                if user is None or user[0] <= now:
                    raise BusinessError("Account expired", 401)
            result = dict(row)
            if activity:
                result["expire_time"] = max(row["expire_time"], now + SESSION_TTL - activity_age)
                db.execute("UPDATE sessions SET expire_time=? WHERE token=?", (result["expire_time"], token))
            return result

    def login(self, data, client_ip):
        name = username(text(data, "username", 24))
        password, code = text(data, "password", 1024), text(data, "code", 128)
        now = time.time()
        with self.login_lock:
            self.failures = {key: value for key, value in self.failures.items() if value[1] > now - 900}
            attempts, last = self.failures.get(client_ip, (0, 0))
            if attempts >= 10 and last > now - 900:
                raise BusinessError("Too many login attempts; retry in 15 minutes", 429)
        if not password:
            raise BusinessError("Password is required")
        role = "user"
        if name == "admin" and not code:
            valid = hmac.compare_digest(password.encode(), self.config.panel_password.encode())
            role = "admin"
        elif code:
            if name.lower() == "admin":
                raise BusinessError("Username is reserved")
            with self.db.connect() as db:
                available = db.execute("SELECT 1 FROM auth_codes WHERE code=? AND is_used=0", (code,)).fetchone()
            if not available:
                with self.login_lock:
                    attempts = self.failures.get(client_ip, (0, 0))[0]
                    self.failures[client_ip] = (attempts + 1, now)
                raise BusinessError("Authorization code is invalid or already used", 403)
            # Hash outside the short SQLite writer transaction.
            hashed = password_hash(password)
            try:
                with self.db.connect(write=True) as db:
                    if db.execute("SELECT 1 FROM users WHERE username=? COLLATE NOCASE", (name,)).fetchone():
                        raise BusinessError("Username already exists", 409)
                    record = db.execute("SELECT route_limit,is_used FROM auth_codes WHERE code=?", (code,)).fetchone()
                    if record is None or record["is_used"]:
                        raise BusinessError("Authorization code is invalid or already used", 403)
                    changed = db.execute("UPDATE auth_codes SET is_used=1,bound_user=? WHERE code=? AND is_used=0", (name, code)).rowcount
                    if changed != 1:
                        raise BusinessError("Authorization code already used", 409)
                    db.execute("INSERT INTO users(username,password_hash,expire_time,route_limit) VALUES(?,?,?,?)",
                               (name, hashed, now + 3650 * 86400, record["route_limit"]))
                    token = self.new_session(db, name, role, now)
            except sqlite3.IntegrityError:
                raise BusinessError("Username or authorization code conflict", 409)
            with self.login_lock:
                self.failures.pop(client_ip, None)
            return {"token": token, "role": role, "expires_at": now + SESSION_TTL, "server_time": now}
        else:
            with self.db.connect() as db:
                record = db.execute(
                    "SELECT * FROM users WHERE username=? COLLATE NOCASE ORDER BY username=? DESC LIMIT 1", (name, name)
                ).fetchone()
            valid = password_verify(password, record["password_hash"] if record else "")
            if valid:
                if record["expire_time"] < now:
                    raise BusinessError("Account expired", 403)
                name = record["username"]
                if not record["password_hash"].startswith("$argon2id$"):
                    hashed = password_hash(password)
                    with self.db.connect(write=True) as db:
                        db.execute("UPDATE users SET password_hash=? WHERE username=?", (hashed, name))
        if not valid:
            with self.login_lock:
                attempts = self.failures.get(client_ip, (0, 0))[0]
                self.failures[client_ip] = (attempts + 1, now)
            raise BusinessError("Invalid username or password", 403)
        with self.login_lock:
            self.failures.pop(client_ip, None)
        with self.db.connect(write=True) as db:
            token = self.new_session(db, name, role, now)
        return {"token": token, "role": role, "expires_at": now + SESSION_TTL, "server_time": now}

    @staticmethod
    def new_session(db, name, role, now):
        token = secrets.token_hex(32)
        db.execute("INSERT INTO sessions VALUES(?,?,?,?)", (token, name, role, now + SESSION_TTL))
        return token

    def bootstrap(self, data):
        timestamp = integer(data.get("t"), 1, 9999999999)
        node_id = text(data, "node_id", 40).lower()
        expected = hmac.new(self.config.secret.encode(), f"{timestamp}:worker-bootstrap:{node_id}".encode(), hashlib.sha256).hexdigest()
        if abs(time.time() - timestamp) > 60 or not hmac.compare_digest(expected, text(data, "sign", 128)):
            raise BusinessError("Invalid or expired signature", 403)
        return self.remote.certificate(node_id)

    @staticmethod
    def node(db, node_id, require_online=True):
        row = db.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
        if row is None:
            raise BusinessError("Node not found", 404)
        if require_online and not row["is_online"]:
            raise BusinessError("Node is offline", 409)
        return dict(row)

    def enqueue(self, action, data, session):
        name, admin = session["username"], session["role"] == "admin"
        operation_id, now = secrets.token_hex(16), time.time()
        if action == "add":
            suffix = subdomain(text(data, "subdomain", 32).lower())
            sub = subdomain(name.lower() + "-" + suffix)
            target = target_url(text(data, "target"), resolve=True)
            node_id = integer(data.get("node_id"), 1, 2147483647)
        else:
            route_id = integer(data.get("id"), 1, 2147483647)
            new_target = text(data, "target") if action == "update" else ""
            if new_target:
                new_target = target_url(new_target, resolve=True)
        with self.db.connect(write=True) as db:
            if action == "add":
                if db.execute("SELECT 1 FROM routes WHERE subdomain=?", (sub,)).fetchone():
                    raise BusinessError("Route prefix already exists", 409)
                if not admin:
                    count = db.execute("SELECT COUNT(*) FROM routes WHERE username=?", (name,)).fetchone()[0]
                    pending = db.execute(
                        "SELECT COUNT(*) FROM operations WHERE username=? AND action='add' AND phase='apply' AND status IN ('pending','running')", (name,)
                    ).fetchone()[0]
                    limit = db.execute("SELECT route_limit FROM users WHERE username=?", (name,)).fetchone()[0]
                    if count + pending >= limit:
                        raise BusinessError("Route quota reached", 403)
                self.node(db, node_id)
                payload = {"sub": sub, "target": target, "node_id": node_id, "username": name}
            else:
                route = db.execute("SELECT * FROM routes WHERE id=?", (route_id,)).fetchone()
                if route is None or (not admin and route["username"] != name):
                    raise BusinessError("Route not found or access denied", 404)
                sub, payload = route["subdomain"], dict(route)
                payload.update(sub=sub, old_node_id=route["node_id"], old_target=route["target"])
                if action == "update":
                    payload["target"] = new_target or route["target"]
                    payload["node_id"] = integer(data.get("node_id") or route["node_id"], 1, 2147483647)
                    self.node(db, payload["node_id"])
            try:
                db.execute(
                    "INSERT INTO operations(id,username,owner_username,action,resource,payload,status,created_at,updated_at) VALUES(?,?,?,?,?,?,'pending',?,?)",
                    (operation_id, name, payload["username"], action, sub, json.dumps(payload), now, now),
                )
            except sqlite3.IntegrityError:
                raise BusinessError("This route already has an active operation", 409)
        self.wake.set()
        return {"msg": "Operation accepted", "operation_id": operation_id}

    def operation(self, operation_id, session):
        with self.db.connect() as db:
            row = db.execute("SELECT id,username,owner_username,resource,action,status,phase,attempts,error,next_run,created_at,updated_at FROM operations WHERE id=?", (operation_id,)).fetchone()
        if row is None or (session["role"] != "admin" and session["username"] not in (row["username"], row["owner_username"])):
            raise BusinessError("Operation not found", 404)
        return dict(row)

    def claim(self):
        with self.db.connect() as db:
            candidate = db.execute("""SELECT id FROM operations WHERE next_run<=? AND
                (status='pending' OR (status='succeeded' AND phase='cleanup'))
                ORDER BY status='pending' DESC,created_at LIMIT 1""", (time.time(),)).fetchone()
        if candidate is None:
            return None
        with self.db.connect(write=True) as db:
            row = db.execute("""SELECT * FROM operations WHERE id=? AND next_run<=? AND
                (status='pending' OR (status='succeeded' AND phase='cleanup'))""", (candidate[0], time.time())).fetchone()
            if row:
                if row["status"] == "succeeded":
                    db.execute("UPDATE operations SET phase='retiring' WHERE id=?", (row["id"],))
                else:
                    db.execute("UPDATE operations SET status='running',updated_at=? WHERE id=?", (time.time(), row["id"]))
        result = dict(row) if row else None
        if result and result["status"] == "succeeded":
            result["phase"] = "retiring"
        return result

    def operation_loop(self):
        while not self.stop.is_set():
            try:
                operation = self.claim()
                if operation:
                    self.execute(operation)
                    continue
            except Exception:
                logger.exception("operation-loop-error")
            self.wake.wait(1)
            self.wake.clear()

    def execute(self, operation):
        # Serialize network writes for the same name, including delayed retirement.
        lock = self.route_locks[int(hashlib.sha256(operation["resource"].encode()).hexdigest(), 16) % len(self.route_locks)]
        with lock:
            if operation["status"] == "succeeded":
                return self.retire(operation)
            return self.execute_foreground(operation)

    @staticmethod
    def retirement_delay(records):
        return max([0 if records else 300] + [300 if record.get("ttl", 1) == 1 else record.get("ttl", 300) for record in records]) + 60

    def retire(self, operation):
        payload = json.loads(operation["payload"])
        sub = operation["resource"]
        try:
            with self.db.connect() as db:
                old = payload["old"] if operation["action"] == "restore" else self.node(db, payload["old_node_id"], require_online=False)
                current = db.execute("SELECT n.host,n.port FROM routes r JOIN nodes n ON n.id=r.node_id WHERE r.subdomain=?", (sub,)).fetchone()
                busy = db.execute("SELECT 1 FROM operations WHERE resource=? AND status IN ('pending','running')", (sub,)).fetchone()
            if current and (current["host"], str(current["port"])) == (old["host"], str(old["port"])):
                # A -> B -> A: this endpoint is active again, never remove its map.
                self.complete_retirement(operation["id"])
                return
            if busy:
                with self.db.connect(write=True) as db:
                    db.execute("UPDATE operations SET phase='cleanup',next_run=? WHERE id=?", (time.time() + 1, operation["id"]))
                return
            self.remote.worker(old, "delete", sub, "")
            self.complete_retirement(operation["id"])
        except Exception as error:
            attempts = operation["attempts"] + 1
            logger.warning("retirement-retry id=%s error=%s", operation["id"], error)
            with self.db.connect(write=True) as db:
                db.execute("UPDATE operations SET phase='cleanup',attempts=?,next_run=?,error=? WHERE id=?",
                           (attempts, time.time() + min(300, 2 ** min(attempts, 8)), str(error)[:300], operation["id"]))

    def complete_retirement(self, operation_id):
        with self.db.connect(write=True) as db:
            db.execute("UPDATE operations SET phase='completed',error='',next_run=0 WHERE id=?", (operation_id,))

    def execute_foreground(self, operation):
        if operation["action"] == "restore":
            return self.execute_restore(operation)
        payload = json.loads(operation["payload"])
        action, sub = operation["action"], payload["sub"]
        try:
            with self.db.connect() as db:
                node = self.node(db, payload["node_id"], require_online=False)
                old = self.node(db, payload["old_node_id"], require_online=False) if "old_node_id" in payload else None
            if operation["phase"] == "rollback":
                if payload.get("worker_touched"):
                    if action != "add":
                        self.remote.worker(old, "add", sub, payload["old_target"])
                if payload.get("dns_touched"):
                    self.remote.dns_restore(sub, payload["dns_before"])
                if payload.get("worker_touched"):
                    if action == "add" or (node["host"], str(node["port"])) != (old["host"], str(old["port"])):
                        self.remote.worker(node, "delete", sub, "")
                self.finish(operation["id"], "failed", operation["error"])
                return
            if operation["phase"] == "apply":
                if "dns_before" not in payload:
                    records = self.remote.dns_snapshot(sub)
                    if action == "add" and records:
                        raise BusinessError("DNS name already exists; choose another route prefix", 409)
                    if action != "add" and any(record["content"] != old["host"] for record in records):
                        raise BusinessError("DNS record differs from managed route; administrator review required", 409)
                    if len(records) > 1:
                        raise BusinessError("DNS record differs from managed route; administrator review required", 409)
                    payload["dns_before"] = records
                    self.save_payload(operation["id"], payload)
                if action in ("add", "update"):
                    payload["worker_touched"] = True
                    self.save_payload(operation["id"], payload)
                    self.remote.worker(node, "add", sub, payload["target"])
                    if action == "add" or not payload["dns_before"] or node["host"] != old["host"]:
                        payload["dns_touched"] = True
                        self.save_payload(operation["id"], payload)
                        self.remote.dns(sub, node["host"])
                else:
                    payload["dns_touched"] = True
                    self.save_payload(operation["id"], payload)
                    self.remote.dns(sub)
                # Database state and cleanup checkpoint commit atomically.
                migrating = action == "update" and (node["host"], str(node["port"])) != (old["host"], str(old["port"]))
                delay = self.retirement_delay(payload["dns_before"]) if node["host"] != (old or node)["host"] else 0
                with self.db.connect(write=True) as db:
                    if action == "add":
                        db.execute("INSERT INTO routes(username,subdomain,target,node_id) VALUES(?,?,?,?)",
                                   (payload["username"], sub, payload["target"], payload["node_id"]))
                    elif action == "update":
                        db.execute("UPDATE routes SET target=?,node_id=? WHERE id=?", (payload["target"], payload["node_id"], payload["id"]))
                    else:
                        db.execute("DELETE FROM routes WHERE id=?", (payload["id"],))
                    db.execute(
                        "UPDATE operations SET phase='cleanup',attempts=0,status=?,next_run=?,updated_at=? WHERE id=?",
                        ("succeeded" if migrating else "running", time.time() + delay if migrating else 0, time.time(), operation["id"]),
                    )
                    if migrating:
                        db.execute("UPDATE operations SET error='' WHERE id=?", (operation["id"],))
                        db.execute("INSERT INTO operation_logs(action,status,detail,created_at) VALUES('route_operation','succeeded',?,?)", (operation["id"], time.time()))
                operation.update(phase="cleanup", attempts=0)
                if migrating:
                    return
            if action == "delete":
                self.remote.worker(node, "delete", sub, "")
            elif action == "update" and (node["host"], str(node["port"])) != (old["host"], str(old["port"])):
                self.remote.worker(old, "delete", sub, "")
            self.finish(operation["id"], "succeeded")
        except Exception as error:
            logger.warning("operation-failed id=%s phase=%s error=%s", operation["id"], operation["phase"], error)
            attempts, phase = operation["attempts"] + 1, operation["phase"]
            if phase == "apply" and attempts >= 3:
                phase, attempts = "rollback", 0
            with self.db.connect(write=True) as db:
                db.execute(
                    "UPDATE operations SET status='pending',phase=?,attempts=?,next_run=?,error=?,updated_at=? WHERE id=?",
                    (phase, attempts, time.time() + min(300, 2 ** min(attempts, 8)), str(error)[:300], time.time(), operation["id"]),
                )

    def save_payload(self, operation_id, payload):
        with self.db.connect(write=True) as db:
            db.execute("UPDATE operations SET payload=?,updated_at=? WHERE id=?", (json.dumps(payload), time.time(), operation_id))

    def execute_restore(self, operation):
        payload = json.loads(operation["payload"])
        node, old, sub = payload["node"], payload["old"], payload["sub"]
        phase = operation["phase"]
        try:
            migrating = node and old and (node["host"], node["port"]) != (old["host"], old["port"])
            if phase == "apply":
                if "dns_before" not in payload:
                    records = self.remote.dns_snapshot(sub)
                    allowed = {item["host"] for item in (node, old) if item}
                    if len(records) > 1 or any(record["content"] not in allowed for record in records):
                        raise BusinessError("Restore DNS conflict; administrator review required", 409)
                    payload["dns_before"] = records
                    self.save_payload(operation["id"], payload)
                if node:
                    target = target_url(payload["target"], resolve=True)
                    self.remote.worker(node, "add", sub, target)
                    self.remote.dns(sub, node["host"])
                else:
                    self.remote.dns(sub)
                delay = self.retirement_delay(payload["dns_before"]) if migrating and node["host"] != old["host"] else 0
                with self.db.connect(write=True) as db:
                    db.execute("UPDATE operations SET phase='cleanup',status=?,attempts=0,next_run=?,error='',updated_at=? WHERE id=?",
                               ("succeeded" if migrating else "running", time.time() + delay, time.time(), operation["id"]))
                    if migrating:
                        db.execute("INSERT INTO operation_logs(action,status,detail,created_at) VALUES('route_operation','succeeded',?,?)", (operation["id"], time.time()))
                phase = "cleanup"
                operation["attempts"] = 0
                if migrating:
                    return
            if old and (not node or migrating):
                self.remote.worker(old, "delete", sub, "")
            self.finish(operation["id"], "succeeded")
        except Exception as error:
            attempts = operation["attempts"] + 1
            logger.warning("restore-task-failed id=%s phase=%s error=%s", operation["id"], phase, error)
            with self.db.connect(write=True) as db:
                db.execute("UPDATE operations SET status='pending',phase=?,attempts=?,next_run=?,error=?,updated_at=? WHERE id=?",
                           (phase, attempts, time.time() + min(300, 2 ** min(attempts, 8)), str(error)[:300], time.time(), operation["id"]))

    def finish(self, operation_id, status, error=""):
        with self.db.connect(write=True) as db:
            db.execute("UPDATE operations SET status=?,phase=CASE WHEN ?='succeeded' THEN 'completed' ELSE phase END,error=?,updated_at=? WHERE id=?", (status, status, error, time.time(), operation_id))
        self.db.audit("route_operation", status, operation_id)

    def heartbeat_loop(self):
        failures = {}
        while not self.stop.is_set():
            try:
                with self.db.connect() as db:
                    nodes = [dict(row) for row in db.execute("SELECT * FROM nodes")]
                failures = {key: value for key, value in failures.items() if key in {node["id"] for node in nodes}}
                for node in nodes:
                    if self.stop.is_set():
                        return
                    try:
                        self.remote.health(node)
                        failures[node["id"]], online = 0, 1
                    except Exception:
                        failures[node["id"]] = failures.get(node["id"], 0) + 1
                        online = 0 if failures[node["id"]] >= 3 else node["is_online"]
                    if online != node["is_online"]:
                        with self.db.connect(write=True) as db:
                            db.execute("UPDATE nodes SET is_online=? WHERE id=? AND host=? AND port=? AND secret_key=?",
                                       (online, node["id"], node["host"], node["port"], node["secret_key"]))
                with self.db.connect(write=True) as db:
                    db.execute("DELETE FROM sessions WHERE expire_time<?", (time.time(),))
                    db.execute("DELETE FROM operation_logs WHERE created_at<?", (time.time() - 90 * 86400,))
                    db.execute("DELETE FROM operations WHERE status IN ('succeeded','failed') AND phase NOT IN ('cleanup','retiring') AND updated_at<?", (time.time() - 90 * 86400,))
            except Exception:
                logger.exception("health-loop-error")
            self.stop.wait(60)

    def admin_action(self, path, data):
        if path == "/admin/generate":
            limit = integer(data.get("route_limit", 3))
            code = secrets.token_urlsafe(6) + "_" + str(limit) + "_" + secrets.token_urlsafe(12)
            with self.db.connect(write=True) as db:
                db.execute("INSERT INTO auth_codes(code,duration,is_used,bound_user,route_limit) VALUES(?,?,0,'',?)", (code, limit, limit))
            return {"msg": "Code generated", "code": code}
        if path == "/admin/add_node":
            name, host = text(data, "name", 80), hostname(text(data, "host", 253))
            port, public = str(integer(data.get("port"), 1, 65535)), str(integer(data.get("public_port"), 1, 65535))
            key = text(data, "key", 256)
            if not name or not key:
                raise BusinessError("Node name and secret are required")
            with self.db.connect(write=True) as db:
                if db.execute("SELECT 1 FROM nodes WHERE host=? AND port=?", (host, port)).fetchone():
                    raise BusinessError("Node endpoint already exists", 409)
                db.execute("INSERT INTO nodes(name,host,port,secret_key,is_online,public_port) VALUES(?,?,?,?,0,?)", (name, host, port, key, public))
            return {"msg": "Node added; waiting for signed health check"}
        if path == "/admin/delete_node":
            node_id = integer(data.get("id"), 1, 2147483647)
            with self.db.connect(write=True) as db:
                if db.execute("SELECT 1 FROM routes WHERE node_id=?", (node_id,)).fetchone():
                    raise BusinessError("Migrate all routes before deleting this node", 409)
                pending = db.execute("SELECT payload FROM operations WHERE status IN ('pending','running') OR (status='succeeded' AND phase IN ('cleanup','retiring'))").fetchall()
                if any(node_id in (p.get("node_id"), p.get("old_node_id"), (p.get("node") or {}).get("id"), (p.get("old") or {}).get("id")) for p in (json.loads(row[0]) for row in pending)):
                    raise BusinessError("Node has unfinished operations", 409)
                db.execute("DELETE FROM nodes WHERE id=?", (node_id,))
            return {"msg": "Node removed"}
        if path == "/admin/update_user_limit":
            name, limit = text(data, "username", 24), integer(data.get("route_limit"), 0, 1000)
            with self.db.connect(write=True) as db:
                if db.execute("UPDATE users SET route_limit=? WHERE username=?", (limit, name)).rowcount != 1:
                    raise BusinessError("User not found", 404)
            return {"msg": "Quota updated"}
        if path == "/admin/update_announcement":
            value = text(data, "text", 10000)
            with self.db.connect(write=True) as db:
                db.execute("INSERT INTO settings VALUES('announcement',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (value,))
            return {"msg": "Announcement published"}
        raise BusinessError("Not found", 404)

    def data(self, session):
        admin = session["role"] == "admin"
        with self.db.connect() as db:
            announcement = db.execute("SELECT value FROM settings WHERE key='announcement'").fetchone()
            nodes = [dict(row) for row in db.execute("SELECT id,name,host,port,public_port,is_online AS online FROM nodes ORDER BY id")]
            params = () if admin else (session["username"],)
            routes = [dict(row) for row in db.execute(
                """SELECT r.id,r.username AS user,r.subdomain,r.target,r.node_id,n.name AS node_name,
                   COALESCE(NULLIF(n.public_port,''),n.port) AS node_port FROM routes r
                   LEFT JOIN nodes n ON r.node_id=n.id""" + ("" if admin else " WHERE r.username=?") + " ORDER BY r.id DESC", params)]
            result = {
                "base_domain": self.config.base_domain, "panel_name": self.config.panel_name, "panel_domain": self.config.panel_domain,
                "announcement": announcement[0] if announcement else "", "routes": routes,
                "nodes": nodes if admin else [{"id": row["id"], "name": row["name"], "online": row["online"]} for row in nodes],
                "operations": [dict(row) for row in db.execute(
                    "SELECT id,username,owner_username,action,resource,status,phase,attempts,error,next_run,updated_at FROM operations" +
                    ("" if admin else " WHERE username=? OR owner_username=?") + " ORDER BY status IN ('pending','running') DESC,created_at DESC LIMIT 100", () if admin else params * 2)],
            }
            if admin:
                result["active_tasks"] = db.execute("SELECT COUNT(*) FROM operations WHERE status IN ('pending','running')").fetchone()[0]
                result["cleanup_tasks"] = db.execute("SELECT COUNT(*) FROM operations WHERE status='succeeded' AND phase IN ('cleanup','retiring')").fetchone()[0]
                result["codes"] = [dict(row) for row in db.execute("SELECT code,route_limit AS dur,is_used AS used,bound_user AS user FROM auth_codes ORDER BY is_used,code")]
                result["users"] = [{**dict(row), "expire": time.strftime("%Y-%m-%d", time.localtime(row["expire_time"]))}
                                   for row in db.execute("""SELECT u.username,u.expire_time,u.route_limit,COUNT(r.id) AS route_count
                                      FROM users u LEFT JOIN routes r ON r.username=u.username GROUP BY u.username ORDER BY u.username""")]
            else:
                row = db.execute("SELECT expire_time,route_limit FROM users WHERE username=?", params).fetchone()
                result.update(username=session["username"], expire=time.strftime("%Y-%m-%d", time.localtime(row[0])), route_limit=row[1])
            return result
