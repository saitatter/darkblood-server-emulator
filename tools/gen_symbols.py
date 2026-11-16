#!/usr/bin/env python3
"""Recover symbol names from the mapped client image for Ghidra.

Writes ``address<TAB>name<TAB>kind<TAB>source`` rows (kind: function | label):

* opcode handlers: research/client/handler_map.txt (written by the shim) joined
  with assets/opcodes.tsv -> ``On_<eERC/eEGS name>``
* lua_tinker bindings: ``push fn / push "Name" / push reg / call`` and
  ``mov eax, fn; push eax; push "Name"; push reg; call`` -> ``Lua_<Name>``
* MSVC RTTI: complete-object locators -> ``<Class>::vftable`` labels and, for
  slots owned by a single class, ``<Class>::vf<slot>`` function names

Names are evidence-backed but heuristic (a binding name is the Lua-visible
name, not necessarily the C++ method name). Usage:
    python tools/gen_symbols.py research/normal.bin -o research/symbols.tsv
"""
import argparse
import re
import struct
from collections import defaultdict
from pathlib import Path

import capstone

BASE = 0x400000
CODE_LO, CODE_HI = 0x401000, 0xC40000
ROOT = Path(__file__).resolve().parent.parent
IDENT = re.compile(rb'[A-Za-z_][A-Za-z0-9_]{1,63}\x00')


def u32(img, va):
    return struct.unpack_from('<I', img, va - BASE)[0]


def cstr(img, va):
    o = va - BASE
    if not 0 <= o < len(img):
        return None
    m = IDENT.match(img, o)
    return m.group()[:-1].decode() if m else None


def handlers():
    names = {}
    for line in open(ROOT / 'assets/opcodes.tsv', encoding='utf-8'):
        a = line.rstrip('\n').split('\t')
        if len(a) >= 2 and a[0].isdigit():
            names[int(a[0])] = a[1]
    hm = ROOT / 'research/client/handler_map.txt'
    if not hm.exists():
        return
    for line in open(hm):
        p = line.split()
        if len(p) < 4:
            continue
        op, fn = int(p[1], 16), int(p[3], 16)
        if CODE_LO <= fn < CODE_HI:
            yield fn, 'On_%s' % names.get(op, 'opcode_%d' % op), 'function', 'handler_map %d' % op


def lua_bindings(img):
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.skipdata = True
    window = []
    for ins in md.disasm(img[CODE_LO - BASE:CODE_HI - BASE], CODE_LO):
        window.append(ins)
        window = window[-5:]
        if ins.mnemonic != 'call' or len(window) < 4:
            continue
        a, b, c = window[-4], window[-3], window[-2]
        if not (c.mnemonic == 'push' and c.op_str in ('esi', 'edi', 'ebx', 'eax', 'ecx', 'edx')):
            continue
        if b.mnemonic != 'push' or not b.op_str.startswith('0x'):
            continue
        name = cstr(img, int(b.op_str, 16))
        fn = None
        if a.mnemonic == 'push' and a.op_str.startswith('0x'):
            fn = int(a.op_str, 16)
        elif a.mnemonic == 'push' and a.op_str == 'eax' and len(window) == 5:
            m = window[0]
            if m.mnemonic == 'mov' and m.op_str.startswith('eax, 0x'):
                fn = int(m.op_str[5:], 16)
        if name and fn and CODE_LO <= fn < CODE_HI:
            yield fn, 'Lua_%s' % name, 'function', 'lua_tinker binding @%x' % b.address


def rtti(img):
    """COL: sig 0, offset, cdOffset, pTypeDescriptor, pClassHierarchy."""
    owners = defaultdict(set)
    rows = []
    for m in re.finditer(rb'\.\?AV([A-Za-z0-9_@]+)@@\x00', img):
        td = m.start() - 8 + BASE
        cls = m.group(1).decode().split('@')
        cls = '::'.join(reversed(cls))
        for c in re.finditer(re.escape(struct.pack('<I', td)), img):
            col = c.start() - 12 + BASE
            if col < BASE or u32(img, col) != 0:
                continue
            offset = u32(img, col + 4)
            for v in re.finditer(re.escape(struct.pack('<I', col)), img):
                vt = v.start() + 4 + BASE
                label = '%s::vftable' % cls + ('' if offset == 0 else '_%x' % offset)
                rows.append((vt, label, 'label', 'RTTI COL %x' % col))
                slot = 0
                while True:
                    fn = u32(img, vt + slot * 4)
                    if not CODE_LO <= fn < CODE_HI or slot > 400:
                        break
                    owners[fn].add((cls, offset, slot))
                    slot += 1
    yield from rows
    for fn, refs in owners.items():
        classes = {r[0] for r in refs}
        if len(classes) == 1:
            cls, offset, slot = sorted(refs)[0]
            suffix = '' if offset == 0 else '_%x' % offset
            yield fn, '%s::vf%02x%s' % (cls, slot * 4, suffix), 'function', 'RTTI vtable slot'


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('image', type=Path, help='mapped image dump (VA - 0x400000 = offset)')
    ap.add_argument('-o', '--output', type=Path, required=True)
    a = ap.parse_args()
    img = a.image.read_bytes()
    best = {}
    priority = {'handler_map': 0, 'lua_tinker': 1, 'RTTI': 2}
    for src in (handlers(), lua_bindings(img), rtti(img)):
        for addr, name, kind, why in src:
            rank = priority[why.split()[0]]
            key = (addr, kind)
            if key not in best or rank < best[key][0]:
                best[key] = (rank, name, why)
    seen = defaultdict(int)
    with open(a.output, 'w', encoding='utf-8', newline='\n') as out:
        for (addr, kind), (_, name, why) in sorted(best.items()):
            seen[name] += 1
            if seen[name] > 1:
                name = '%s_%d' % (name, seen[name])
            out.write('%08x\t%s\t%s\t%s\n' % (addr, name, kind, why))
    counts = defaultdict(int)
    for (_, kind), (_, _, why) in best.items():
        counts[why.split()[0]] += 1
    print(dict(counts), '->', a.output)


if __name__ == '__main__':
    main()
