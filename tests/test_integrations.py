import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from master.integrations import Integrations


class DNSConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.remote = Integrations(SimpleNamespace(base_domain="example.com", cf_zone="zone", cf_token="test"))
        self.record = {"id": "record", "type": "A", "name": "test.example.com", "content": "8.8.8.8", "proxied": False, "ttl": 120}

    def test_changed_record_is_read_back_after_write(self):
        changed = {**self.record, "content": "1.1.1.1"}
        self.remote.request = Mock(side_effect=[{"success": True, "result": [self.record]}, {"success": True}, {"success": True, "result": [changed]}])
        self.remote.dns("test", "1.1.1.1")
        self.assertEqual(3, self.remote.request.call_count)
        self.assertEqual("PUT", self.remote.request.call_args_list[1].args[2])

    def test_unchanged_record_is_confirmed_without_write(self):
        self.remote.request = Mock(return_value={"success": True, "result": [self.record]})
        self.remote.dns("test", "8.8.8.8")
        self.assertEqual(1, self.remote.request.call_count)

    def test_successful_write_with_stale_read_back_is_not_success(self):
        self.remote.request = Mock(side_effect=[{"success": True, "result": [self.record]}, {"success": True}, {"success": True, "result": [self.record]}])
        with self.assertRaisesRegex(RuntimeError, "confirmation mismatch"):
            self.remote.dns("test", "1.1.1.1")

    def test_read_back_checks_type_proxy_and_ttl_not_only_host(self):
        for key, value in (("type", "CNAME"), ("proxied", True), ("ttl", 300)):
            with self.subTest(key=key):
                bad = {**self.record, "content": "1.1.1.1", key: value}
                self.remote.request = Mock(side_effect=[{"success": True, "result": [self.record]}, {"success": True}, {"success": True, "result": [bad]}])
                with self.assertRaisesRegex(RuntimeError, "confirmation mismatch"):
                    self.remote.dns("test", "1.1.1.1")

    def test_delete_requires_empty_read_back(self):
        self.remote.request = Mock(side_effect=[{"success": True, "result": [self.record]}, {"success": True}, {"success": True, "result": []}])
        self.remote.dns("test")
        self.assertEqual("DELETE", self.remote.request.call_args_list[1].kwargs["method"])
        self.remote.request = Mock(side_effect=[{"success": True, "result": [self.record]}, {"success": True}, {"success": True, "result": [self.record]}])
        with self.assertRaisesRegex(RuntimeError, "confirmation mismatch"):
            self.remote.dns("test")

    def test_create_requires_matching_read_back(self):
        self.remote.request = Mock(side_effect=[{"success": True, "result": []}, {"success": True}, {"success": True, "result": [self.record]}])
        self.remote.dns("test", "8.8.8.8")
        self.assertEqual("POST", self.remote.request.call_args_list[1].args[2])
