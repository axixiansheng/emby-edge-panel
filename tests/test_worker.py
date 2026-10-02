import hashlib
import hmac
import importlib.util
import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        env = Path(self.temp.name, ".env")
        env.write_text("SECRET_KEY=test-key\n")
        spec = importlib.util.spec_from_file_location("test_agent", Path(__file__).parents[1] / "worker" / "agent.py")
        self.agent = importlib.util.module_from_spec(spec)
        with patch.dict(os.environ, {"EMBY_AGENT_ENV_FILE": str(env)}):
            spec.loader.exec_module(self.agent)
        self.agent.URL_MAP = str(Path(self.temp.name, "url.map"))
        self.agent.SNI_MAP = str(Path(self.temp.name, "sni.map"))
        self.agent.atomic_write(self.agent.URL_MAP, ['    "old.example.com" "https://old.example.org";\n'])
        self.agent.atomic_write(self.agent.SNI_MAP, ['    "old.example.com" "old.example.org";\n'])
        self.server = self.agent.http.server.ThreadingHTTPServer(("127.0.0.1", 0), self.agent.AgentHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, target="https://emby.example.org/path/?token=/", sign=True, body=None):
        timestamp = int(time.time())
        data = {"t": timestamp, "action": "add", "subdomain": "user-main", "target": target, "base_domain": "example.com"}
        data["sign"] = hmac.new(b"test-key", f"{timestamp}:add:user-main:{target}".encode(), hashlib.sha256).hexdigest() if sign else "bad"
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.server.server_port}/api/sync",
            data=json.dumps(data if body is None else body).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            response = urllib.request.urlopen(req)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    def test_success_acknowledges_ready_after_reload(self):
        with patch.object(self.agent.subprocess, "run") as run:
            status, data = self.request()
        self.assertEqual(200, status)
        self.assertTrue(data["ready"])
        self.assertEqual(["nginx", "-t"], run.call_args_list[0].args[0])
        self.assertEqual(["nginx", "-s", "reload"], run.call_args_list[1].args[0])
        self.assertIn("?token=/", Path(self.agent.URL_MAP).read_text())

    def test_invalid_nginx_update_restores_previous_maps(self):
        original = Path(self.agent.URL_MAP).read_text(), Path(self.agent.SNI_MAP).read_text()
        with patch.object(self.agent.subprocess, "run", side_effect=[subprocess.CalledProcessError(1, "nginx"), None]):
            status, data = self.request()
        self.assertEqual(503, status)
        self.assertFalse(data["ok"])
        self.assertEqual(original, (Path(self.agent.URL_MAP).read_text(), Path(self.agent.SNI_MAP).read_text()))

    def test_invalid_signature_object_and_injection_rejected(self):
        self.assertEqual(403, self.request(sign=False)[0])
        self.assertEqual(400, self.request(body=[])[0])
        self.assertEqual(400, self.request(target='https://example.org/";evil;')[0])


if __name__ == "__main__":
    unittest.main()
