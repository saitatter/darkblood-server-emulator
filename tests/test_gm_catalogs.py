"""Unit tests for launcher GM ID catalogs and command parameter parsing."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / 'tools' / 'launcher') not in sys.path:
    sys.path.insert(0, str(ROOT / 'tools' / 'launcher'))

from launcher_app.gm_catalogs import (  # noqa: E402
    catalog_categories,
    load_catalog,
    load_gm_pins,
    lookup_entry,
    move_item,
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

    def test_crafting_materials_and_fishing_items_are_listed(self):
        # making.lua / fishing.lua define gathered ore and caught fish (DictItem:LoadItem).
        ore = lookup_entry('item', 'IMnr20N')
        self.assertIsNotNone(ore)
        self.assertEqual(ore.category, 'Crafting Materials')
        self.assertIsNotNone(lookup_entry('item', 'ILurN1'))

    def test_item_category_menu_filters_sections_and_equipment_kinds(self):
        tree = dict(catalog_categories('item'))
        self.assertEqual(tree['Crafting Materials'], 'section:Crafting Materials')
        equipment = [label for label, _ in tree['Equipment']]
        self.assertIn('Weapons', equipment)
        self.assertIn('Lv 1–15', equipment)

        materials, total = search_catalog('item', '', limit=500, category='section:Crafting Materials')
        self.assertEqual(total, len(materials))
        self.assertTrue(all(m.category == 'Crafting Materials' for m in materials))
        weapons, _ = search_catalog('item', '', limit=50, category='kind:Weapons')
        self.assertTrue(weapons and all(m.id.startswith('W') for m in weapons))
        _, all_equipment = search_catalog('item', '', category='group:Equipment')
        _, low_level = search_catalog('item', '', category='section:Equipment (Lv 1–15)')
        self.assertGreater(all_equipment, low_level)
        self.assertEqual(catalog_categories('monster'), [])

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
                {'label': '25-Slot Bag', 'commands': ['%itemcall IbagU160 1']},
                {'label': 'Starter kit', 'commands': ['itemcall IRanCashEtc260 10', ' ', '%ar 500000']},
                {'label': 'Empty', 'commands': []},
                {'label': 'Old format', 'command': 'ar 1'},
            ]
            save_gm_pins(pins, path)
            loaded = load_gm_pins(path)
            self.assertEqual(loaded, [
                {'label': '25-Slot Bag', 'commands': ['itemcall IbagU160 1']},
                {'label': 'Starter kit', 'commands': ['itemcall IRanCashEtc260 10', 'ar 500000']},
            ])

    def test_move_item_reorders_and_clamps(self):
        items = ['a', 'b', 'c']
        self.assertEqual(move_item(items, 0, 1), 1)
        self.assertEqual(items, ['b', 'a', 'c'])
        self.assertEqual(move_item(items, 2, -5), 0)
        self.assertEqual(items, ['c', 'b', 'a'])
        self.assertEqual(move_item(items, 2, 1), 2)
        self.assertEqual(items, ['c', 'b', 'a'])

if __name__ == '__main__':
    unittest.main()
