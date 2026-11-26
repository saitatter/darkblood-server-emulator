"""Checks that generated message modules match schemas/*.jsch."""
import subprocess
import sys
import unittest

from tests.common import ROOT


class GeneratedMessagesTest(unittest.TestCase):
    def test_generated_modules_are_current(self):
        proc = subprocess.run([sys.executable, str(ROOT / 'tools' / 'codegen' / 'gen_messages.py'), '--check'],
                              cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_schema_errors_are_reported(self):
        sys.path.insert(0, str(ROOT / 'tools' / 'codegen'))
        try:
            import gen_messages
        finally:
            sys.path.pop(0)
        names = gen_messages.client_names()
        cases = {
            'message 2220 X header\nend\n': 'only client-sent messages carry the header word',
            'message 999999 X\nend\n': 'not in assets/opcodes.tsv',
            'message 2223 X\n  mystery a\nend\n': 'unknown type',
            'message 2225 X\n  rest a\n  i64 c\nend\n': 'rest must be the last field',
            'message 2220 X ok_only\n  i64 uid\nend\n': 'ok_only needs a scalar first field named result',
            'message 2220 X\n  vector<?> items\nend\n': 'must be anonymous',
        }
        import tempfile
        from pathlib import Path
        for body, message in cases.items():
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'bad.jsch'
                path.write_text('domain bad\n' + body, encoding='utf-8')
                with self.assertRaises(gen_messages.SchemaError) as ctx:
                    gen_messages.Parser(path, names).parse()
                self.assertIn(message, str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
