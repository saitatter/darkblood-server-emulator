"""Launcher modules must import every standard-library module they use.

v0.5's launcher called `time.monotonic()` in the update progress callback
without `import time`; the NameError surfaced only while downloading, so every
0.5 -> 0.6 self-update failed. This catches `<module>.<attr>` uses of common
stdlib modules that are never bound in the file.
"""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER_FILES = sorted((ROOT / 'tools' / 'launcher').rglob('*.py'))
STDLIB_MODULES = frozenset((
    'ast', 'collections', 'ctypes', 'datetime', 'functools', 'hashlib', 'io', 'itertools', 'json',
    'logging', 'math', 'os', 'platform', 'random', 're', 'shlex', 'shutil', 'socket', 'string',
    'struct', 'subprocess', 'sys', 'tempfile', 'threading', 'time', 'traceback', 'urllib', 'uuid',
    'webbrowser', 'zipfile',
))


def unbound_module_uses(source: str):
    tree = ast.parse(source)
    bound = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                bound.add((alias.asname or alias.name).split('.')[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bound.add(node.id)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
    used = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            name = node.value.id
            if name in STDLIB_MODULES and name not in bound:
                used.add((name, node.lineno))
    return sorted(used)


class LauncherImportsTest(unittest.TestCase):
    def test_detects_missing_import(self):
        self.assertEqual(unbound_module_uses('def f():\n    return time.monotonic()\n'), [('time', 2)])
        self.assertEqual(unbound_module_uses('import time\ndef f():\n    return time.monotonic()\n'), [])

    def test_launcher_modules_import_what_they_use(self):
        self.assertTrue(LAUNCHER_FILES)
        problems = {}
        for path in LAUNCHER_FILES:
            missing = unbound_module_uses(path.read_text(encoding='utf-8'))
            if missing:
                problems[str(path.relative_to(ROOT))] = missing
        self.assertEqual(problems, {})


if __name__ == '__main__':
    unittest.main()
