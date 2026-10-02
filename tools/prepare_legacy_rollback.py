"""Add modern password verification to restored legacy code without changing its business logic."""
import ast
import os
import shutil
import sys
from pathlib import Path


class LoginCompatibility(ast.NodeTransformer):
    def __init__(self):
        self.changed = 0

    def visit_Compare(self, node):
        left = node.left
        if (
            len(node.ops) == 1 and isinstance(node.ops[0], ast.NotIn)
            and isinstance(left, ast.Subscript) and isinstance(left.value, ast.Name)
            and left.value.id == "db_user" and isinstance(left.slice, ast.Constant)
            and left.slice.value == 0 and len(node.comparators) == 1
            and isinstance(node.comparators[0], ast.Tuple)
        ):
            calls = node.comparators[0].elts
            names = [call.func.id for call in calls if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)]
            if names == ["hash_pwd", "legacy_hash_pwd"]:
                self.changed += 1
                return ast.copy_location(
                    ast.UnaryOp(op=ast.Not(), operand=ast.Call(
                        func=ast.Name(id="_verify_password", ctx=ast.Load()),
                        args=[ast.Name(id="pwd", ctx=ast.Load()), left], keywords=[],
                    )), node,
                )
        return self.generic_visit(node)


def prepare(source, security_source):
    source, security_source = Path(source), Path(security_source)
    tree = ast.parse(source.read_text(encoding="utf-8"))
    transformer = LoginCompatibility()
    tree = transformer.visit(tree)
    if transformer.changed != 1:
        raise RuntimeError("Unrecognized legacy password check; refusing to modify restored code")
    tree.body.insert(0, ast.ImportFrom(module="legacy_security", names=[ast.alias(name="password_verify", asname="_verify_password")], level=0))
    ast.fix_missing_locations(tree)
    compiled = ast.unparse(tree) + "\n"
    compile(compiled, str(source), "exec")
    shutil.copyfile(security_source, source.with_name("legacy_security.py"))
    temporary = source.with_suffix(".compat.tmp")
    temporary.write_text(compiled, encoding="utf-8")
    os.chmod(temporary, 0o750)
    os.replace(temporary, source)


if __name__ == "__main__":
    prepare(sys.argv[1], sys.argv[2])
