"""Unit tests for launcher GM ID catalogs and command parameter parsing."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / 'tools' / 'launcher') not in sys.path:
    sys.path.insert(0, str(ROOT / 'tools' / 'launcher'))

from launcher_app.gm_catalogs import (  # noqa: E402
    load_catalog,
    load_gm_pins,
    lookup_entry,
    parse_command_params,
    save_gm_pins,
    search_catalog,
    suggest_pin_label,
)


class GmCatalogsTest(unittest.TestCase):
    def test_all_catalogs_load_with_ids_and_names(self):
        for name, minimum in (
            ('item', 5000),
            ('monster', 1000),
            ('skill', 400),
            ('quest', 1000),
            ('buff', 1000),
            ('npc', 300),
            ('mount', 20),
        ):
            entries = load_catalog(name)
            self.assertGreaterEqual(len(entries), minimum, f'{name} catalog unexpectedly small')
            self.assertTrue(any(e.name for e in entries), f'{name} catalog missing names')

    def test_search_and_lookup_item_by_name_and_id(self):
        bag = lookup_entry('item', 'IbagU160')
        self.assertIsNotNone(bag)
        self.assertIn('Santa', bag.name)

        matches, total = search_catalog('item', 'santa starlight bag')
        self.assertGreaterEqual(total, 1)
        self.assertTrue(any(m.id == 'IbagU160' for m in matches))

        # Equipment items from items_equipment.md are merged into the 'item' catalog
        eq = lookup_entry('item', 'AbelF10N')
        self.assertIsNotNone(eq)
        self.assertTrue(eq.name)

    def test_parse_command_params_identifies_catalogs_and_choices(self):
        specs = parse_command_params('<item_id> [count=1] [expire_min]')
        self.assertEqual([s.name for s in specs], ['item_id', 'count', 'expire_min'])
        self.assertEqual(specs[0].catalog, 'item')
        self.assertTrue(specs[0].required)
        self.assertFalse(specs[1].required)
        self.assertEqual(specs[1].default, '1')

        buff_specs = parse_command_params('<buff_id> [monster_id]')
        self.assertEqual([(s.name, s.catalog) for s in buff_specs], [('buff_id', 'buff'), ('monster_id', 'monster')])

        mount_specs = parse_command_params('<mount_id | off>')
        self.assertEqual(len(mount_specs), 1)
        self.assertEqual(mount_specs[0].catalog, 'mount')
        self.assertEqual(mount_specs[0].choices, ['off'])

        enum_specs = parse_command_params('<weapon | cloth> <level>')
        self.assertEqual(enum_specs[0].choices, ['weapon', 'cloth'])
        self.assertIsNone(enum_specs[0].catalog)
        self.assertEqual(enum_specs[1].name, 'level')

        self.assertEqual(parse_command_params('—'), [])

    def test_gm_pins_roundtrip_and_suggested_label(self):
        self.assertEqual(suggest_pin_label('itemcall IbagU160 1'), "Santa's Starlight Bag")
        self.assertEqual(suggest_pin_label('itemcall IbagU160 3'), "Santa's Starlight Bag x3")
        self.assertEqual(suggest_pin_label('%ar 500000'), 'ar 500000')

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'gm_pins.json'
            self.assertEqual(load_gm_pins(path), [])
            pins = [
                {'label': '25-Slot Bag', 'command': '%itemcall IbagU160 1'},
                {'label': 'Card Pack x10', 'command': 'itemcall IRanCashEtc260 10'},
            ]
            save_gm_pins(pins, path)
            loaded = load_gm_pins(path)
            self.assertEqual(loaded, [
                {'label': '25-Slot Bag', 'command': 'itemcall IbagU160 1'},
                {'label': 'Card Pack x10', 'command': 'itemcall IRanCashEtc260 10'},
            ])


if __name__ == '__main__':
    unittest.main()
