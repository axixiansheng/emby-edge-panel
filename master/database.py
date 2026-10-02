import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


class Database:
    def __init__(self, path):
        self.path = path

    @contextmanager
    def connect(self, write=False):
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA foreign_keys=ON")
        try:
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

    def initialize(self):
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
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

    def audit(self, action, status, detail="", route_id=None):
        with self.connect(write=True) as db:
            db.execute(
                "INSERT INTO operation_logs(action,route_id,status,detail,created_at) VALUES(?,?,?,?,?)",
                (action, route_id, status, detail[:500], time.time()),
            )
