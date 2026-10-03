import sys
import tempfile
import time
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from master.app import create_app
from master.config import Config
from master.database import Database
from master.security import password_hash


class Remote:
    def __init__(self):
        self.records = {"tester1-main": "8.8.8.8", "tester1-secondary": "8.8.8.8"}

    def health(self, node):
        if node["id"] == 3:
            raise OSError("Test offline node")

    def worker(self, *args):
        pass

    def dns_snapshot(self, sub):
        return [{"content": self.records[sub], "ttl": 120}] if sub in self.records else []

    def dns(self, sub, host=None):
        if host:
            self.records[sub] = host
        else:
            self.records.pop(sub, None)

    def dns_restore(self, sub, records):
        self.dns(sub, records[0]["content"] if records else None)


with tempfile.TemporaryDirectory(prefix="emby-ui-test-") as directory:
    config = Config(str(Path(directory) / "panel.db"), "test-admin", "unused", "unused", "example.com", "Emby Edge", "panel.example.com", "unused", "unused")
    database = Database(config.db_file)
    database.initialize()
    with database.connect(write=True) as db:
        db.execute("INSERT INTO users VALUES(?,?,?,?)", ("Tester1", password_hash("test-user"), time.time() + 86400 * 365, 5))
        for number in (1, 2, 3):
            db.execute("INSERT INTO nodes VALUES(?,?,?,?,?,?,?)", (number, "Test node " + str(number), "8.8.8.8" if number == 1 else "1.1.1.1", str(12340 + number), "test-key", int(number != 3), "54321"))
        for name in ("tester1-main", "tester1-secondary"):
            db.execute("INSERT INTO routes(username,subdomain,target,node_id) VALUES(?,?,?,1)", ("Tester1", name, "https://8.8.8.8:8096"))
        db.execute("INSERT INTO settings VALUES('announcement','Test announcement')")
    database.close()
    uvicorn.run(create_app(config, Remote()), host="127.0.0.1", port=18767, log_level="warning")
