"""Extract the GTarget objects (fishing holes, gathering nodes, crafting stations) of the town maps.

A `.map` file is a 32-byte header followed by one zlib stream (the header holds
the inflated size at +0x1C). In the inflated data every map object record is

    03 80 80 | u32 uid (high byte 0x05) | u32 ResourceNum | u32 ResourceIdx |
    u32 layer | 01 00 00 00 00 01 | f32 x | f32 y | ...

(ResourceNum, ResourceIdx) select the DictTarget entry (fishing.lua,
gathering.lua, making.lua), e.g. 743/0 = Fish_ACT1_N0 and 252/0 = G1mscA01n0.
The uid is the GTarget UID that 5125/5126 TargetState entries refer to
(JGTarget+0x1C, matched by JGTarget::Update 0x007F8CD0). The layer field is
the town layer (zone) index; it is kept for reference.

Usage: python tools/client_data/extract_gtargets.py [--maps DIR] [--check]
Writes assets/gtargets.tsv (square, uid, resource_num, resource_idx, layer, x, y).
"""
import argparse
import re
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MAPS = ROOT.parent / 'darkblood-client-data' / 'files' / 'data' / 'map' / 'mywork'
OUTPUT = ROOT / 'assets' / 'gtargets.tsv'

# Town square (SQUARE_IDS) -> map file.
TOWN_MAPS = {'Act1': 'act1.map', 'Act2': 'act2.map', 'Act4': 'act4.map'}

RECORD = re.compile(rb'\x03\x80\x80(.{3}\x05)(.{4})(.{4})(.{4})\x01\x00\x00\x00\x00\x01(.{4})(.{4})', re.S)
PREFIX = re.compile(rb'\x03\x80\x80.{3}\x05', re.S)


def map_objects(path: Path):
    """[(uid, resource_num, resource_idx, layer, x, y)] of one .map file."""
    data = path.read_bytes()
    raw = zlib.decompress(data[0x20:])
    expected = struct.unpack_from('<I', data, 0x1C)[0]
    if len(raw) != expected:
        raise ValueError(f'{path.name}: inflated {len(raw)} bytes, header says {expected}')
    objects = []
    for m in RECORD.finditer(raw):
        uid, num, idx, layer = (struct.unpack('<I', m.group(i))[0] for i in range(1, 5))
        x, y = (struct.unpack('<f', m.group(i))[0] for i in (5, 6))
        objects.append((uid, num, idx, layer, x, y))
    if len(objects) != len(PREFIX.findall(raw)):
        raise ValueError(f'{path.name}: {len(PREFIX.findall(raw))} object prefixes, {len(objects)} parsed')
    return objects


def render(maps_dir: Path) -> str:
    lines = ['square\tuid\tresource_num\tresource_idx\tlayer\tx\ty']
    for square, name in TOWN_MAPS.items():
        for uid, num, idx, layer, x, y in map_objects(maps_dir / name):
            lines.append(f'{square}\t{uid}\t{num}\t{idx}\t{layer}\t{x:.1f}\t{y:.1f}')
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--maps', type=Path, default=DEFAULT_MAPS, help='folder with act1.map, act2.map, act4.map')
    parser.add_argument('--check', action='store_true', help='exit 1 if assets/gtargets.tsv is stale')
    args = parser.parse_args(argv)
    text = render(args.maps)
    if args.check:
        current = OUTPUT.read_text(encoding='utf-8') if OUTPUT.exists() else ''
        if current != text:
            print(f'{OUTPUT.relative_to(ROOT)} is stale; run tools/client_data/extract_gtargets.py')
            return 1
        return 0
    OUTPUT.write_bytes(text.encode('utf-8'))
    print(f'Wrote {OUTPUT.relative_to(ROOT)}: {text.count(chr(10)) - 1} map objects')
    return 0


if __name__ == '__main__':
    sys.exit(main())
