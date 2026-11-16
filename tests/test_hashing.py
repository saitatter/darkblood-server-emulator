"""Unit tests for string and data hashing functions."""
import unittest

from tests.common import ROOT  # ensures paths are set
from darkblood.core import hashing


class HashingTest(unittest.TestCase):
    def test_jhash_matches_client_djb2(self):
        # 0x00B3AD70: h = 5381; h = h * 33 + (signed byte) over UTF-16LE bytes.
        self.assertEqual(hashing.jhash(''), 5381)
        self.assertEqual(hashing.jhash('A'), ((5381 * 33 + 0x41) * 33) & 0xffffffff)
        self.assertEqual(hashing.jhash('Act1'), 0x5F98AFAE)
        self.assertEqual(hashing.jhash('Act1_G1_A10'), 0x32ADCD46)

    def test_jhash_known_item_codes(self):
        self.assertIsInstance(hashing.jhash('Ibaga0004'), int)
        self.assertIsInstance(hashing.jhash('Ihppa0001'), int)
        self.assertIsInstance(hashing.jhash('Q0001S01'), int)


if __name__ == '__main__':
    unittest.main()
