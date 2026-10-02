import ast
import tempfile
import unittest
from pathlib import Path

from master.security import password_hash, password_verify
from tools.prepare_legacy_rollback import prepare


class RollbackTests(unittest.TestCase):
    def test_argon2_password_round_trip_and_wrong_password(self):
        stored = password_hash("new-password")
        self.assertTrue(stored.startswith("$argon2id$v=19$m=19456,t=2,p=1$"))
        self.assertTrue(password_verify("new-password", stored))
        self.assertFalse(password_verify("wrong-password", stored))

    def test_legacy_login_patch_only_changes_password_verification(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp, "app.py")
            source.write_text("def login(db_user, pwd):\n    if db_user[0] not in (hash_pwd(pwd), legacy_hash_pwd(pwd)):\n        return False\n    return True\n")
            prepare(source, Path(__file__).parents[1] / "master" / "security.py")
            tree = ast.parse(source.read_text())
            condition = tree.body[1].body[0].test
            self.assertIsInstance(condition, ast.UnaryOp)
            self.assertEqual("_verify_password", condition.operand.func.id)
            self.assertTrue(Path(temp, "legacy_security.py").exists())

    def test_unrecognized_legacy_code_is_not_modified(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp, "app.py")
            original = "print('not a legacy master')\n"
            source.write_text(original)
            with self.assertRaises(RuntimeError):
                prepare(source, Path(__file__).parents[1] / "master" / "security.py")
            self.assertEqual(original, source.read_text())
