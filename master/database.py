import sqlite3
import threading
import time
from contextlib import contextmanager, nullcontext
from pathlib import Path


class Database:
    def __init__(self, path):
        self.path = path
        self.writer = threading.RLock()
        self.anchor = None

    @contextmanager
    def connect(self, write=False):
        # Only SQLite transactions use this lock; hashing and network I/O never do.
        with self.writer if write else nullcontext():
            connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
            connection.row_factory = sqlite3.Row
            try:
                connection.execute("PRAGMA busy_timeout=10000")
                connection.execute("PRAGMA foreign_keys=ON")
                if write:
                    connection.execute("BEGIN IMMEDIATE")
                yield connection
                if write:
                    connection.commit()
            except BaseException:
                if write:
                    connection.rollback()
                raise
            finally:
                connection.close()

    def close(self):
        if self.anchor is not None:
            self.anchor.close()
            self.anchor = None

    def initialize(self):
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.close()
        # Keep WAL open between requests instead of checkpointing on the last close.
        self.anchor = sqlite3.connect(self.path, timeout=10, isolation_level=None, check_same_thread=False)
        self.anchor.execute("PRAGMA journal_mode=WAL")
        with self.connect(write=True) as db:
            for statement in (
                "CREATE TABLE IF NOT EXISTS users(username TEXT PRIMARY KEY,password_hash TEXT,expire_time REAL,route_limit INTEGER DEFAULT 3)",
                "CREATE TABLE IF NOT EXISTS auth_codes(code TEXT PRIMARY KEY,duration INTEGER,is_used INTEGER,bound_user TEXT,route_limit INTEGER)",
                "CREATE TABLE IF NOT EXISTS routes(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT,subdomain TEXT,target TEXT,node_id INTEGER)",
                "CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT)",
                "CREATE TABLE IF NOT EXISTS nodes(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,host TEXT,port TEXT,secret_key TEXT,is_online INTEGER DEFAULT 1,public_port TEXT)",
                "CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,username TEXT,role TEXT,expire_time REAL)",
                "CREATE TABLE IF NOT EXISTS operation_logs(id INTEGER PRIMARY KEY AUTOINCREMENT,action TEXT,route_id INTEGER,status TEXT,detail TEXT,created_at REAL)",
                """CREATE TABLE IF NOT EXISTS operations(
                    id TEXT PRIMARY KEY,username TEXT NOT NULL,action TEXT NOT NULL,
                    resource TEXT NOT NULL,payload TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',
                    phase TEXT NOT NULL DEFAULT 'apply',attempts INTEGER NOT NULL DEFAULT 0,
                    next_run REAL NOT NULL DEFAULT 0,error TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,updated_at REAL NOT NULL)""",
            ):
                db.execute(statement)
            additions = {
                "users": {"password_hash": "TEXT", "route_limit": "INTEGER DEFAULT 3"},
                "auth_codes": {"route_limit": "INTEGER"},
                "nodes": {"is_online": "INTEGER DEFAULT 1", "public_port": "TEXT"},
            }
            for table, columns in additions.items():
                existing = {row["name"] for row in db.execute("PRAGMA table_info(" + table + ")")}
                for name, definition in columns.items():
                    if name not in existing:
                        db.execute("ALTER TABLE " + table + " ADD COLUMN " + name + " " + definition)
            db.execute("UPDATE auth_codes SET route_limit=duration WHERE route_limit IS NULL")
            db.execute("UPDATE users SET route_limit=3 WHERE route_limit IS NULL OR route_limit<0")
            for statement in (
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_routes_subdomain ON routes(subdomain)",
                "CREATE INDEX IF NOT EXISTS idx_routes_username ON routes(username)",
                "CREATE INDEX IF NOT EXISTS idx_sessions_expire ON sessions(expire_time)",
                "CREATE INDEX IF NOT EXISTS idx_operations_pending ON operations(status,next_run)",
                """CREATE UNIQUE INDEX IF NOT EXISTS idx_operations_resource
                   ON operations(resource) WHERE status IN ('pending','running')""",
            ):
                db.execute(statement)
            # Duplicate legacy names remain usable; new writes explicitly check NOCASE.
            db.execute("CREATE INDEX IF NOT EXISTS idx_users_lookup ON users(username COLLATE NOCASE)")
            db.execute("UPDATE operations SET status='pending' WHERE status='running'")
            db.execute("DELETE FROM sessions WHERE expire_time<?", (time.time(),))
            # Cap legacy seven-day sessions without extending any existing deadline.
            maximum_expiry = time.time() + 3600
            db.execute("UPDATE sessions SET expire_time=? WHERE expire_time>?", (maximum_expiry, maximum_expiry))

    def audit(self, action, status, detail="", route_id=None):
        with self.connect(write=True) as db:
            db.execute(
                "INSERT INTO operation_logs(action,route_id,status,detail,created_at) VALUES(?,?,?,?,?)",
                (action, route_id, status, detail[:500], time.time()),
            )
