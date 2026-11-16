"""Unit tests for the SQLite character store and inventory initialization."""
import tempfile
import unittest
from pathlib import Path

from tests.common import ROOT  # ensures paths
from darkblood.player_management.characters import ensure_inventory
from darkblood.player_management.store import SqliteCharacterStore


class InventoryTest(unittest.TestCase):
    def test_ensure_inventory_adds_default_equipment_and_bag(self):
        char = {'id': 1, 'name': 'Thief', 'char_class': 4}
        changed = ensure_inventory(char)
        self.assertTrue(changed)
        self.assertIn('bags', char)
        self.assertIn('items', char)
        # Inventory bag uses container 3 (2 is ignored by 0x008354D0), capacity 5
        bag2 = next((b for b in char['bags'] if b.get('bag_id') == 3), None)
        self.assertIsNotNone(bag2)
        self.assertEqual(bag2['b29'], 5)
        self.assertEqual(bag2['code'], 'Ibaga0004')
        # Items list initialized
        self.assertIsInstance(char['items'], list)

        # Calling again on already populated char does not re-add
        self.assertFalse(ensure_inventory(char))


class SqliteCharacterStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / 'darkblood.db'
        self.store = SqliteCharacterStore(db_path=self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_sqlite_create_and_get_character(self):
        req = {'name': 'SqlHero', 'char_class': 2}
        char = self.store.create('PlayerAccount', req)
        self.assertIsNotNone(char)
        self.assertEqual(char['name'], 'SqlHero')
        self.assertEqual(char['id'], 1)
        self.assertEqual(char['level'], 1)

        found = self.store.get('PlayerAccount', 1)
        self.assertEqual(found['name'], 'SqlHero')
        chars = self.store.characters('PlayerAccount')
        self.assertEqual(len(chars), 1)

    def test_sqlite_duplicate_name_case_insensitive_rejected(self):
        self.store.create('Account1', {'name': 'Paladin', 'char_class': 1})
        dup = self.store.create('Account2', {'name': 'paladin', 'char_class': 2})
        self.assertIsNone(dup)

    def test_sqlite_delete_character(self):
        char = self.store.create('Acc', {'name': 'SqlToDel', 'char_class': 1})
        self.assertTrue(self.store.delete('Acc', char['id']))
        self.assertIsNone(self.store.get('Acc', char['id']))
        self.assertEqual(len(self.store.characters('Acc')), 0)
        self.assertFalse(self.store.delete('Acc', 999))


if __name__ == '__main__':
    unittest.main()


class DefaultEquipmentSlotTest(unittest.TestCase):
    def test_slots_follow_item_part_not_list_order(self):
        from darkblood.player_management.characters import equip_slot_for
        taken = set()
        warrior = ['Abelw0002', 'Abodw0002', 'Aglow0001', 'Ashow0001', 'Ahelw0000',
                   'Wlsww0001', 'AderW1N', 'Waxew0000']
        slots = {}
        for code in warrior:
            slot = equip_slot_for(code, taken)
            taken.add(slot)
            slots[code] = slot
        self.assertEqual(slots, {'Abelw0002': 5, 'Abodw0002': 2, 'Aglow0001': 3, 'Ashow0001': 4,
                                 'Ahelw0000': 13, 'Wlsww0001': 0, 'AderW1N': 6, 'Waxew0000': None})

    def test_knight_third_weapon_goes_to_bag(self):
        from darkblood.player_management.characters import equip_slot_for
        taken = {0}
        self.assertEqual(equip_slot_for('Ashik0001', taken), 1)
        taken.add(1)
        self.assertIsNone(equip_slot_for('Wmack0000', taken))
