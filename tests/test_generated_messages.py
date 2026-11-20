"""Checks that generated message modules match schemas/*.jsch."""
import subprocess
import sys
import unittest

from tests.common import ROOT


class GeneratedMessagesTest(unittest.TestCase):
    def test_generated_modules_are_current(self):
        proc = subprocess.run([sys.executable, str(ROOT / 'tools' / 'gen_messages.py'), '--check'],
                              cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_schema_errors_are_reported(self):
        sys.path.insert(0, str(ROOT / 'tools'))
        try:
            import gen_messages
        finally:
            sys.path.pop(0)
        names = gen_messages.client_names()
        cases = {
            'message 2219 X reply\nend\n': 'does not look like a reply',
            'message 999999 X request\nend\n': 'not in assets/opcodes.tsv',
            'message 2223 X request\n  mystery a\nend\n': 'unknown type',
            'message 2225 X request\n  rest a\n  i64 c\nend\n': 'rest must be the last field',
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
