"""Unit tests for tools/multibox.py tiling layout and 1-4 client account resolution."""
import sys
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent / 'tools'
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

if sys.platform == 'win32':
    import gamectl  # noqa: E402
    import multibox  # noqa: E402


@unittest.skipUnless(sys.platform == 'win32', 'tools/multibox.py is Windows-only')
class MultiboxLayoutAndAccountsTest(unittest.TestCase):
    def test_default_accounts_up_to_four(self):
        self.assertEqual(
            multibox.default_accounts(4),
            ['OfflinePlayer', 'Player2', 'Player3', 'Player4'],
        )
        self.assertEqual(
            multibox.default_accounts(2, skip=2),
            ['Player3', 'Player4'],
        )

    def test_resolve_accounts_bounds_and_padding(self):
        with self.assertRaises(gamectl.GameError):
            multibox.resolve_accounts(0)
        with self.assertRaises(gamectl.GameError):
            multibox.resolve_accounts(5)

        self.assertEqual(
            multibox.resolve_accounts(4),
            ['OfflinePlayer', 'Player2', 'Player3', 'Player4'],
        )
        self.assertEqual(
            multibox.resolve_accounts(4, accounts=['Alpha', 'Player2']),
            ['Alpha', 'Player2', 'OfflinePlayer', 'Player3'],
        )

    def test_compute_tile_rects_auto_grid_and_row(self):
        area = (0, 0, 2560, 1392)

        # 1 client -> 1x1
        self.assertEqual(multibox.compute_tile_rects(area, 1), [(0, 0, 2560, 1392)])

        # 2 clients -> 2x1 side-by-side
        self.assertEqual(
            multibox.compute_tile_rects(area, 2),
            [(0, 0, 1280, 960), (1280, 0, 1280, 960)],
        )

        # 3 clients -> 2x2 grid (first 3 quadrants)
        self.assertEqual(
            multibox.compute_tile_rects(area, 3),
            [(0, 0, 1280, 696), (1280, 0, 1280, 696), (0, 696, 1280, 696)],
        )

        # 4 clients -> 2x2 grid (all 4 quadrants)
        self.assertEqual(
            multibox.compute_tile_rects(area, 4),
            [
                (0, 0, 1280, 696),
                (1280, 0, 1280, 696),
                (0, 696, 1280, 696),
                (1280, 696, 1280, 696),
            ],
        )

        # Explicit row layout for 4 clients
        self.assertEqual(
            multibox.compute_tile_rects(area, 4, layout='row'),
            [
                (0, 0, 640, 480),
                (640, 0, 640, 480),
                (1280, 0, 640, 480),
                (1920, 0, 640, 480),
            ],
        )

        with self.assertRaises(gamectl.GameError):
            multibox.compute_tile_rects(area, 2, layout='invalid')


if __name__ == '__main__':
    unittest.main()
