import tempfile
import unittest
from pathlib import Path

from worker.configure_nginx import parse, plan, write_changes


class WorkerInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.main = self.root / "nginx.conf"
        (self.root / "conf.d").mkdir()
        (self.root / "stream.d").mkdir()
        (self.root / "stream.d" / "emby.conf").write_text(
            'map $ssl_preread_protocol $emby_backend { "" 127.0.0.1:12346; default 127.0.0.1:12347; }\n'
            'server { listen 12345; proxy_pass $emby_backend; ssl_preread on; }\n'
        )

    def tearDown(self):
        self.temp.cleanup()

    def configure(self, legacy_marker=False):
        write_changes(plan(self.main, legacy_marker))

    def alpine(self):
        self.main.write_text('include conf.d/*.conf;\nevents {}\nhttp { map $http_upgrade $connection_upgrade { default upgrade; "" close; } }\n')
        stream = self.root / "conf.d" / "stream.conf"
        stream.write_text('stream {\n    # system log settings must survive\n    access_log /var/log/nginx/stream.log;\n    include stream.d/*.conf;\n}\n')
        return stream

    def old_block(self):
        return f'# Emby Edge managed stream include\nstream {{\n    include {self.root.as_posix()}/stream.d/*.conf;\n}}\n'

    def test_alpine_relative_include_reused_without_edits(self):
        self.alpine()
        self.assertEqual({}, plan(self.main))

    def test_repair_previous_duplicate_and_keep_distribution_settings(self):
        stream = self.alpine()
        original_stream = stream.read_bytes()
        original_main = self.main.read_text()
        self.main.write_text(original_main + self.old_block())
        self.configure(True)
        self.assertEqual(original_main, self.main.read_text())
        self.assertEqual(original_stream, stream.read_bytes())
        self.assertEqual({}, plan(self.main))

    def test_debian_fresh_install_and_repeat_are_idempotent(self):
        self.main.write_text('events {}\nhttp { include conf.d/*.conf; }\n')
        self.configure()
        first = self.main.read_bytes()
        self.configure()
        self.assertEqual(first, self.main.read_bytes())
        self.assertEqual(1, self.main.read_text().count('stream {'))

    def test_custom_stream_reused_and_uninstall_keeps_other_servers(self):
        self.main.write_text('events {}\ninclude conf.d/*.conf;\nhttp {}\n')
        custom = self.root / 'conf.d' / 'tcp.conf'
        custom.write_text('stream {\n    server { listen 9000; proxy_pass 127.0.0.1:9001; }\n}\n')
        original = custom.read_text()
        self.configure()
        first = custom.read_bytes()
        self.configure()
        self.assertEqual(first, custom.read_bytes())
        write_changes(plan(self.main, remove=True))
        self.assertEqual(original, custom.read_text())

    def test_comments_and_http_includes_do_not_count_as_stream_configuration(self):
        self.main.write_text('events {}\n# stream { include stream.d/*.conf; }\nhttp {\n    include conf.d/*.conf;\n}\n')
        (self.root / 'conf.d' / 'site.conf').write_text('server { listen 80; location / { return 200 "stream { ${host} # }"; } }\n')
        self.configure()
        self.assertEqual(1, len([d for d in parse(self.main.read_text()) if d.words == ['stream']]))

    def test_nested_includes_are_resolved_relative_to_configuration_prefix(self):
        self.main.write_text('events {}\ninclude conf.d/*.conf;\nhttp {}\n')
        (self.root / 'conf.d' / 'tcp.conf').write_text('stream { include servers.conf; }\n')
        (self.root / 'servers.conf').write_text('include "stream.d/*.conf";\n')
        self.assertEqual({}, plan(self.main))

    def test_legacy_direct_include_is_removed_only_in_main_context(self):
        self.main.write_text('events {}\n' + f'include {self.root.as_posix()}/stream.d/*.conf;\n')
        self.configure(True)
        self.assertEqual(1, self.main.read_text().count('include '))
        self.assertEqual(1, self.main.read_text().count('stream {'))

    def test_ambiguous_unmanaged_duplicates_fail_without_writing(self):
        self.main.write_text('events {}\nstream {}\nstream {}\n')
        original = self.main.read_text()
        with self.assertRaisesRegex(ValueError, 'Multiple unmanaged'):
            self.configure()
        self.assertEqual(original, self.main.read_text())

    def test_recursive_include_fails_without_writing(self):
        self.main.write_text('events {}\ninclude nginx.conf;\n')
        original = self.main.read_bytes()
        with self.assertRaisesRegex(ValueError, 'Recursive'):
            self.configure()
        self.assertEqual(original, self.main.read_bytes())

    def test_uninstall_does_not_remove_distribution_include(self):
        self.alpine()
        self.assertEqual({}, plan(self.main, remove=True))

    def test_uninstall_removes_only_managed_block(self):
        self.main.write_text('events {}\nhttp {}\n')
        original = self.main.read_text()
        self.configure()
        write_changes(plan(self.main, remove=True))
        self.assertEqual(original, self.main.read_text())


if __name__ == '__main__':
    unittest.main()
