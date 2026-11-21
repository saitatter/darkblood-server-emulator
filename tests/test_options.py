"""darkblood_options.ini round trip, network/launcher config, and server use."""
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
        expected_defaults = {key: default for key, (_, default, _, _) in options.OPTIONS.items()}
        self.assertEqual(options.read(), expected_defaults)
        self.assertEqual(options.read_network(), {'host': '127.0.0.1', 'port': 9400, 'relay_port': 9401})
        self.assertEqual(options.read_launcher(), {'account': 'OfflinePlayer', 'clients': 1})

        options.write({
            'skip_logos': True,
            'skip_tutorial_always': True,
            'borderless_fullscreen': False,
            'adult_content': False,
        })
        text = options.OPTIONS_PATH.read_text(encoding='utf-8')
        self.assertIn('[client]', text)
        self.assertIn('[network]', text)
        self.assertIn('skip_tutorial_always = 1', text)  # the shim reads it with GetPrivateProfileInt
        self.assertIn('borderless_fullscreen = 0', text)
        self.assertEqual(options.read()['adult_content'], False)
        self.assertEqual(options.read()['borderless_fullscreen'], False)
        self.assertEqual(options.read()['auto_reconnect'], True)

    def test_network_and_launcher_round_trip_and_preservation(self):
        options.write_all(
            values={'skip_logos': True},
            network={'host': '192.168.1.42', 'port': 9500, 'relay_port': 9501},
            launcher={'account': 'Tester', 'clients': 2},
        )
        cfg = options.read_all()
        self.assertEqual(cfg['network'], {'host': '192.168.1.42', 'port': 9500, 'relay_port': 9501})
        self.assertEqual(cfg['launcher'], {'account': 'Tester', 'clients': 2})
        self.assertTrue(cfg['options']['skip_logos'])

        # Updating only boolean options must preserve [network] and [launcher].
        options.write({'adult_content': False})
        cfg2 = options.read_all()
        self.assertEqual(cfg2['network'], {'host': '192.168.1.42', 'port': 9500, 'relay_port': 9501})
        self.assertEqual(cfg2['launcher'], {'account': 'Tester', 'clients': 2})
        self.assertFalse(cfg2['options']['adult_content'])

    def test_network_validation(self):
        self.assertEqual(
            options.validate_network(' 10.0.0.5 ', '9400', '9401'),
            {'host': '10.0.0.5', 'port': 9400, 'relay_port': 9401},
        )
        with self.assertRaises(ValueError):
            options.validate_network('', 9400, 9401)
        with self.assertRaises(ValueError):
            options.validate_network('bad host', 9400, 9401)
        with self.assertRaises(ValueError):
            options.validate_network('127.0.0.1', 0, 9401)
        with self.assertRaises(ValueError):
            options.validate_network('127.0.0.1', 9400, 70000)

    def test_every_option_has_patch_metadata(self):
        valid_cats = {cid for cid, _ in options.CATEGORIES}
        for key in options.OPTIONS:
            self.assertIn(key, options.PATCH_META)
            cat, src = options.PATCH_META[key]
            self.assertIn(cat, valid_cats)
            self.assertTrue(src)

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
