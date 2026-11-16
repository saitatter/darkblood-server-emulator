"""Unit tests for CharacterStore and inventory initialization."""
import tempfile
import unittest
from pathlib import Path

from tests.common import ROOT  # ensures paths
from darkblood.player_management.characters import CharacterStore, ensure_inventory, EQUIP_CONTAINER


class CharacterStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'characters.json'
        self.store = CharacterStore(path=self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_and_get_character(self):
        req = {'name': 'Hero', 'char_class': 1}
        char = self.store.create('PlayerAccount', req)
        self.assertIsNotNone(char)
        self.assertEqual(char['name'], 'Hero')
        self.assertEqual(char['id'], 1)
        self.assertEqual(char['level'], 1)
        self.assertFalse(char['tutorial_cleared'])

        # Retrieval by account and id
        found = self.store.get('PlayerAccount', 1)
        self.assertEqual(found['name'], 'Hero')

        # List all for account
        chars = self.store.characters('PlayerAccount')
        self.assertEqual(len(chars), 1)

    def test_duplicate_name_case_insensitive_rejected(self):
        self.store.create('Account1', {'name': 'Knight', 'char_class': 1})
        dup = self.store.create('Account2', {'name': 'knight', 'char_class': 2})
        self.assertIsNone(dup)

    def test_delete_character(self):
        char = self.store.create('Acc', {'name': 'ToDel', 'char_class': 1})
        self.assertTrue(self.store.delete('Acc', char['id']))
        self.assertIsNone(self.store.get('Acc', char['id']))
        self.assertEqual(len(self.store.characters('Acc')), 0)
        # Deleting non-existent returns False
        self.assertFalse(self.store.delete('Acc', 999))

    def test_ensure_inventory_adds_default_equipment_and_bag(self):
        char = {'id': 1, 'name': 'Thief', 'char_class': 4}
        changed = ensure_inventory(char)
        self.assertTrue(changed)
        self.assertIn('bags', char)
        self.assertIn('items', char)
        # Bag container 2 has capacity 5
        bag2 = next((b for b in char['bags'] if b.get('bag_id') == 2), None)
        self.assertIsNotNone(bag2)
        self.assertEqual(bag2['b29'], 5)
        self.assertEqual(bag2['code'], 'Ibaga0004')
        # Items list initialized
        self.assertIsInstance(char['items'], list)

        # Calling again on already populated char does not re-add
        self.assertFalse(ensure_inventory(char))


if __name__ == '__main__':
    unittest.main()
