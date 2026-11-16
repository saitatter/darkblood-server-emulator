#!/usr/bin/env python3
"""Name the protector call stubs (`nop; call 0x600xxxxx`) of the analysed image.

The packer replaces `call [IAT]` with `nop; call <target>`, where the target is
a per-session address (DLL code or a private thunk). research/normal.bin keeps
the targets of one session; a read-only dump of another session
(tools/dump_stubs.py) holds the same call sites with that session's targets.
For each site this script reads the current target, follows simple thunks in
private regions (jmp rel/abs, jmp [abs], push imm; ret, mov reg, imm; jmp reg),
and resolves the final address to ``module!export`` using the export tables of
the DLL files on disk. Old targets are then named by majority vote.

    python tools/resolve_stubs.py research/stubs -o research/stub_names.tsv
Output rows: old_target  name  sites  agreement
"""
import argparse
import json
import struct
from collections import Counter, defaultdict
from pathlib import Path

import pefile

BASE = 0x400000
ROOT = Path(__file__).resolve().parent.parent


class Memory:
    def __init__(self, dump_dir):
        meta = json.loads((dump_dir / 'regions.json').read_text())
        self.regions = []
        for r in meta['regions']:
            f = dump_dir / ('%08x.bin' % r['base'])
            if f.exists():
                self.regions.append((r['base'], f.read_bytes()))
        self.modules = sorted((m['base'], m['size'], m['path']) for m in meta['modules'])

    def read(self, va, n):
        for base, data in self.regions:
            if base <= va < base + len(data):
                return data[va - base:va - base + n]
        return None

    def module(self, va):
        for base, size, path in self.modules:
            if base <= va < base + size:
                return base, path
        return None


class Exports:
    def __init__(self):
        self.cache = {}

    def name(self, base, path, va):
        if path not in self.cache:
            table = {}
            try:
                pe = pefile.PE(path, fast_load=True)
                pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_EXPORT']])
                for s in getattr(pe, 'DIRECTORY_ENTRY_EXPORT', None).symbols if hasattr(pe, 'DIRECTORY_ENTRY_EXPORT') else []:
                    label = s.name.decode(errors='replace') if s.name else 'ord%d' % s.ordinal
                    table[s.address] = label
            except Exception:
                pass
            self.cache[path] = table
        mod = Path(path).name
        return '%s!%s' % (mod, self.cache[path].get(va - base, '+0x%x' % (va - base)))


def follow(mem, va, depth=0):
    """Follow private-region thunks; return the first address inside a module."""
    if depth > 8 or mem.module(va):
        return va
    code = mem.read(va, 16)
    if not code:
        return va
    op = code[0]
    if op == 0xE9:                                   # jmp rel32
        return follow(mem, va + 5 + struct.unpack_from('<i', code, 1)[0], depth + 1)
    if op == 0xFF and code[1] == 0x25:               # jmp [abs]
        ptr = mem.read(struct.unpack_from('<I', code, 2)[0], 4)
        return follow(mem, struct.unpack('<I', ptr)[0], depth + 1) if ptr else va
    if op == 0x68 and code[5] == 0xC3:               # push imm; ret
        return follow(mem, struct.unpack_from('<I', code, 1)[0], depth + 1)
    if 0xB8 <= op <= 0xBF and code[5] == 0xFF and 0xE0 <= code[6] <= 0xE7:  # mov r, imm; jmp r
        return follow(mem, struct.unpack_from('<I', code, 1)[0], depth + 1)
    return va


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('dump', type=Path)
    ap.add_argument('--image', type=Path, default=ROOT / 'research/normal.bin')
    ap.add_argument('-o', '--output', type=Path, default=ROOT / 'research/stub_names.tsv')
    a = ap.parse_args()
    old = a.image.read_bytes()
    mem, exports = Memory(a.dump), Exports()
    votes = defaultdict(Counter)
    unresolved = 0
    for off in range(0x1000, min(len(old), 0xC40000 - BASE) - 6):
        if old[off] != 0x90 or old[off + 1] != 0xE8:
            continue
        site = off + BASE + 1
        old_target = (site + 5 + struct.unpack_from('<i', old, off + 2)[0]) & 0xFFFFFFFF
        if BASE <= old_target < BASE + len(old):
            continue  # ordinary call into the image
        cur = mem.read(site - 1, 6)
        if not cur or cur[1] != 0xE8:
            unresolved += 1
            continue
        target = follow(mem, (site + 5 + struct.unpack_from('<i', cur, 2)[0]) & 0xFFFFFFFF)
        mod = mem.module(target)
        if not mod:
            unresolved += 1
            continue
        votes[old_target][exports.name(mod[0], mod[1], target)] += 1
    with open(a.output, 'w', encoding='utf-8', newline='\n') as out:
        out.write('old_target\tname\tsites\tagreement\n')
        for t in sorted(votes):
            name, n = votes[t].most_common(1)[0]
            total = sum(votes[t].values())
            out.write('%08x\t%s\t%d\t%.2f\n' % (t, name, total, n / total))
    print('%d stub targets named, %d sites unresolved -> %s' % (len(votes), unresolved, a.output))


if __name__ == '__main__':
    main()
