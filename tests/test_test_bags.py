"""Unit test for grant_test_bags helper."""
import unittest

from darkblood.player_management.characters import (
    EQUIP_CONTAINER, ensure_inventory, free_bag_slots, grant_test_bags)


class GrantTestBagsTest(unittest.TestCase):
    def test_enlarges_starting_bag_and_fills_free_slots(self):
        char = {'char_class': 1, 'items': []}
        ensure_inventory(char)
        self.assertEqual(free_bag_slots(char), 5)

        self.assertEqual(grant_test_bags(char), 5)
        bags = [b for b in char['bags'] if b['bag_id'] != EQUIP_CONTAINER]
        self.assertEqual(sorted(b['w2a'] for b in bags), [0, 1, 2, 3, 4])
        self.assertTrue(all(b['b29'] == 20 and b['code'] == 'Ibaga0003' for b in bags))
        ids = [b['bag_id'] for b in char['bags']]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertNotIn(2, ids)  # container 2 is dropped by the client
        self.assertEqual(free_bag_slots(char), 100)
        self.assertEqual(grant_test_bags(char), 0)


if __name__ == '__main__':
    unittest.main()
