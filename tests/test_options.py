"""darkblood_options.ini round trip and server use (adult content in the welcome)."""
import struct
import tempfile
import unittest
from pathlib import Path

from tests.common import ROOT  # noqa: F401  (sets up sys.path)
from darkblood.core import options
from darkblood.core.serialization import jser
from darkblood.games.handlers.frontend import welcome


class OptionsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.saved = options.OPTIONS_PATH
        options.OPTIONS_PATH = Path(self.tmp.name) / 'darkblood_options.ini'
        self.addCleanup(setattr, options, 'OPTIONS_PATH', self.saved)

    def test_defaults_and_round_trip(self):
        self.assertEqual(options.read(), {'skip_logos': False, 'skip_tutorial_always': False,
                                          'adult_content': True})
        options.write({'skip_logos': True, 'skip_tutorial_always': True, 'adult_content': False})
        text = options.OPTIONS_PATH.read_text(encoding='utf-8')
        self.assertIn('[client]', text)
        self.assertIn('skip_tutorial_always = 1', text)  # the shim reads it with GetPrivateProfileInt
        self.assertEqual(options.read()['adult_content'], False)

    def _adult_flag(self):
        _, _, _, body = jser.parse_event(welcome())
        length, offset = jser.read_varuint(body, 12)
        return struct.unpack_from('<II???', body, offset + length)[3]

    def test_welcome_follows_adult_option(self):
        options.write({'adult_content': True})
        self.assertTrue(self._adult_flag())
        options.write({'adult_content': False})
        self.assertFalse(self._adult_flag())


if __name__ == '__main__':
    unittest.main()
