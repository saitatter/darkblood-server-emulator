#!/usr/bin/env python3
"""Draft message schemas from the client's JSerBuffer read calls.

For each registered handler in research/opcode_xrefs.tsv (or functions given on
the command line) the function body is disassembled linearly and every call is
classified:

  scalar readers (type code passed to 0x00A48AF0, byte size to 0x00B34FC0):
    0xB350C0 i8   0xB35150 u8   0xB351E0 i16  0xB35270 u16  0xB35300 i32
    0xB35390 u32  0xB35430 i64  0xB354D0 u64  0xB35560 f32  0xB355F0 f64
    0xB35680 bool 0xB356F0 time(i64)
  0xB35AB0 wstring, 0xB35A40/0xB358D0 wstring variants, 0xB35860/0xB35940 string,
  0xB357F0 varint, 0xB35760 raw bytes, 0xB35010(tag) container tag check,
  0x00A1EA20 result (u32, peeked by handlers), 0x00A1E6A0/0x00B34F60 reader
  begin/end (omitted; a handler's scan stops at its first reader end).

Calls to other functions are followed (depth-limited) when they themselves read
fields, producing nested ``struct FUN_xxxxxxxx { ... }`` blocks. Loops and
branches are flattened in address order, so vectors show their element reader
once and conditional fields appear unconditionally. Treat the output as a
draft to confirm against the pseudocode and a headless test.

    python tools/codegen/extract_schemas.py                 # all handlers -> research/schemas.txt
    python tools/codegen/extract_schemas.py 0x77EEB0 ...    # print selected functions
"""
import argparse
import struct
import sys
from functools import lru_cache
from pathlib import Path

import capstone

BASE = 0x400000
ROOT = Path(__file__).resolve().parents[2]
PRIMS = {
    0xB350C0: 'i8', 0xB35150: 'u8', 0xB351E0: 'i16', 0xB35270: 'u16',
    0xB35300: 'i32', 0xB35390: 'u32', 0xB35430: 'i64', 0xB354D0: 'u64',
    0xB35560: 'f32', 0xB355F0: 'f64', 0xB35680: 'bool', 0xB356F0: 'time64',
    0xB35AB0: 'wstring', 0xB35A40: 'wstring', 0xB358D0: 'wstring',
    0xB35860: 'string', 0xB35940: 'string', 0xB357F0: 'varint',
    0xB35760: 'bytes', 0xA1EA20: 'u32 result',
}
TAG = 0xB35010
READER_END = 0xB34F60
SKIP = {0xA1E6A0, 0xB34F60, 0xB34F20, 0xB34F40}
TAGS = {0x0F: 'tag0F', 0x10: 'vector', 0x13: 'set?', 0x17: 'map', 0x1A: 'tag1A', 0x1E: 'struct'}


class Extractor:
    def __init__(self, img, sizes):
        self.img, self.sizes = img, sizes
        self.md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)

    def body(self, fn):
        size = self.sizes.get(fn, 0)
        if not size or size > 0x4000:
            size = min(size or 0x400, 0x4000)
        return self.md.disasm(self.img[fn - BASE:fn - BASE + size], fn)

    @lru_cache(maxsize=None)
    def fields(self, fn, depth=0):
        out, last_push, pushes = [], None, []
        for ins in self.body(fn):
            if ins.mnemonic == 'push':
                try:
                    value = int(ins.op_str, 16) if ins.op_str.startswith('0x') else int(ins.op_str)
                except ValueError:
                    value = None
                pushes = (pushes + [value])[-2:]
                last_push = value
                continue
            if ins.mnemonic in ('ret', 'retn') and ins.address > fn + 4 and not out:
                break
            if ins.mnemonic != 'call' or not ins.op_str.startswith('0x'):
                continue
            tgt = int(ins.op_str, 16)
            if tgt == 0xB35760 and len(pushes) == 2 and pushes[0] is not None:
                out.append('bytes[%d]' % pushes[0])  # push size; push dst
            elif tgt in PRIMS:
                out.append(PRIMS[tgt])
            elif tgt == TAG:
                out.append('tag 0x%02X %s' % (last_push or 0, TAGS.get(last_push, '')))
            elif tgt == READER_END and depth == 0 and out:
                break  # handler finished reading; later calls use the data
            elif tgt in SKIP or not 0x401000 <= tgt < 0xC40000:
                pass
            elif depth < 4 and tgt in self.sizes:
                sub = self.fields(tgt, depth + 1)
                if sub:
                    out.append(('FUN_%08x' % tgt, sub))
            last_push, pushes = None, []
        return tuple(out)


def case_handlers(ex, dispatcher, opcode):
    """Functions called by the switch case of `opcode` inside `dispatcher`.

    Tracks `sub/add reg, imm` running offsets and `cmp reg, imm`; the case is
    the je target (or the fall-through of jne) right after the comparison
    that yields `opcode`. Returns the calls made before the case's first
    ret/jmp, excluding reader helpers.
    """
    insns = list(ex.body(dispatcher))
    offs, hits = {}, []
    for i, ins in enumerate(insns):
        ops = [o.strip() for o in ins.op_str.split(',')]
        if len(ops) != 2 or not ops[1].startswith('0x'):
            if ins.mnemonic in ('mov', 'movzx') and ops:
                offs.pop(ops[0], None)
            continue
        value = int(ops[1], 16)
        reg = ops[0]
        if ins.mnemonic == 'sub':
            offs[reg] = offs.get(reg, 0) + value
            hit = offs[reg]
        elif ins.mnemonic == 'add' and value >= 0x80000000:
            offs[reg] = offs.get(reg, 0) + 0x100000000 - value
            hit = offs[reg]
        elif ins.mnemonic == 'cmp':
            hit = offs.get(reg, 0) + value
        else:
            if ins.mnemonic in ('mov', 'movzx'):
                offs.pop(reg, None)
            continue
        if hit == opcode and i + 1 < len(insns):
            nxt = insns[i + 1]
            if nxt.mnemonic == 'je' and nxt.op_str.startswith('0x'):
                hits.append(int(nxt.op_str, 16))
            elif nxt.mnemonic == 'jne' and i + 2 < len(insns):
                hits.append(insns[i + 2].address)
    by_addr = {ins.address: k for k, ins in enumerate(insns)}
    calls = []
    for target in hits:
        k = by_addr.get(target)
        while k is not None and k < len(insns):
            ins = insns[k]
            if ins.mnemonic in ('ret', 'jmp'):
                break
            if ins.mnemonic == 'call' and ins.op_str.startswith('0x'):
                tgt = int(ins.op_str, 16)
                if tgt not in PRIMS and tgt not in SKIP and tgt != TAG and tgt in ex.sizes:
                    calls.append(tgt)
            k += 1
    return calls


def jump_table_cases(ex, fn):
    """Decode `add/sub reg, K; cmp reg, N; ja; [movzx r2, byte [reg+T1];]
    jmp [r*4+T2]` dispatchers. Returns {opcode: [called functions]} using the
    first non-helper call of each case block."""
    insns = list(ex.body(fn))
    img = ex.img
    out = {}
    for i, ins in enumerate(insns):
        if ins.mnemonic != 'jmp' or '*4 +' not in ins.op_str:
            continue
        window = insns[max(0, i - 6):i]
        base = n = t1 = None
        for w in window:
            ops = [o.strip() for o in w.op_str.split(',')]
            if w.mnemonic == 'add' and len(ops) == 2 and ops[1].startswith('0x'):
                v = int(ops[1], 16)
                base = (0x100000000 - v) if v >= 0x80000000 else -v
            elif w.mnemonic == 'sub' and len(ops) == 2 and ops[1].startswith('0x'):
                base = int(ops[1], 16)
            elif w.mnemonic == 'cmp' and len(ops) == 2 and ops[1].startswith('0x'):
                n = int(ops[1], 16)
            elif w.mnemonic == 'movzx' and 'byte ptr [' in w.op_str and '+ 0x' in w.op_str:
                t1 = int(w.op_str.rsplit('+ ', 1)[1].rstrip(']'), 16)
        if base is None or n is None or n > 0x400:
            continue
        t2 = int(ins.op_str.rsplit('+ ', 1)[1].rstrip(']'), 16)
        for k in range(n + 1):
            try:
                idx = img[t1 - BASE + k] if t1 else k
                target = struct.unpack_from('<I', img, t2 - BASE + idx * 4)[0]
            except (IndexError, struct.error):
                break
            calls = []
            for c in ex.md.disasm(img[target - BASE:target - BASE + 24], target):
                if c.mnemonic in ('ret', 'jmp'):
                    break
                if c.mnemonic == 'call' and c.op_str.startswith('0x'):
                    tgt = int(c.op_str, 16)
                    if tgt not in PRIMS and tgt not in SKIP and tgt in ex.sizes:
                        calls.append(tgt)
            if calls:
                out.setdefault(base + k, []).extend(calls[:1])
    return out


def render(items, indent='  '):
    lines = []
    for item in items:
        if isinstance(item, tuple):
            name, sub = item
            lines.append('%sstruct %s {' % (indent, name))
            lines.extend(render(sub, indent + '  '))
            lines.append('%s}' % indent)
        else:
            lines.append(indent + item)
    return lines


def load_sizes():
    sizes = {}
    for line in open(ROOT / 'research/decompiled/functions.tsv', encoding='utf-8'):
        a = line.rstrip('\n').split('\t')
        if len(a) >= 3 and a[0] != 'address':
            sizes[int(a[0], 16)] = int(a[2])
    return sizes


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('functions', nargs='*', help='function VAs to print instead of all handlers')
    ap.add_argument('-o', '--output', type=Path, default=ROOT / 'research/schemas.txt')
    a = ap.parse_args()
    ex = Extractor((ROOT / 'research/normal.bin').read_bytes(), load_sizes())
    if a.functions:
        for f in a.functions:
            fn = int(f, 16)
            print('FUN_%08x' % fn)
            print('\n'.join(render(ex.fields(fn))))
        return 0
    count = cases = tables = 0
    names = {}
    for line in open(ROOT / 'assets/opcodes.tsv', encoding='utf-8'):
        q = line.rstrip('\n').split('\t')
        if q[0].isdigit():
            names[int(q[0])] = q[1]
    # Jump-table dispatchers anywhere in the client (two-level tables included).
    table_cases = {}
    for fn in ex.sizes:
        for op, fns in jump_table_cases(ex, fn).items():
            if names.get(op, '').endswith(('_ACK', '_NOT', '_AKC')):
                table_cases.setdefault(op, set()).update((fn, h) for h in fns)
    with open(a.output, 'w', encoding='utf-8', newline='\n') as out:
        for line in open(ROOT / 'research/opcode_xrefs.tsv', encoding='utf-8'):
            p = line.rstrip('\n').split('\t')
            if p[0] == 'opcode' or len(p) < 6:
                continue
            if not p[5] and int(p[0]) in table_cases:
                for d, fn in sorted(table_cases[int(p[0])]):
                    items = ex.fields(fn)
                    if items:
                        out.write('%s %s  table case in %08x -> %08x\n' % (p[0], p[1], d, fn))
                        out.write('\n'.join(render(items)) + '\n\n')
                        tables += 1
                continue
            if p[5]:
                for h in p[5].split():
                    items = ex.fields(int(h, 16))
                    out.write('%s %s  handler %s\n' % (p[0], p[1], h))
                    out.write('\n'.join(render(items)) + '\n\n')
                    count += 1
            elif p[4] and p[1].endswith(('_ACK', '_NOT', '_AKC')):
                for d in p[4].split():
                    for fn in case_handlers(ex, int(d, 16), int(p[0])):
                        items = ex.fields(fn)
                        if not items:
                            continue
                        out.write('%s %s  case in %s -> %08x\n' % (p[0], p[1], d, fn))
                        out.write('\n'.join(render(items)) + '\n\n')
                        cases += 1
    print('%d dispatcher-case schemas, %d jump-table case schemas' % (cases, tables))
    print('%d handler schemas -> %s' % (count, a.output))
    return 0


if __name__ == '__main__':
    sys.exit(main())
