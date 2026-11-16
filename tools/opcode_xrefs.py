#!/usr/bin/env python3
"""Cross-reference every JEvent opcode with the client functions that send or
dispatch it.

Inputs: the mapped image (research/normal.bin), function boundaries from the
Ghidra export (research/decompiled/functions.tsv, tools/ExportDecompiled.java),
names/pairs from server/data/opcodes.tsv and opcode_pairs.tsv, and the
connect-time handler map (research/client/handler_map.txt) when present.

Detected patterns (assembly level, per function):
  send      push <opcode> followed within 4 instructions by a call to an event
            constructor (0x00408C60 JEvent(opcode,-1,-1), 0x007AEE00).
  dispatch  comparisons of an event id: `sub/add reg, imm` chains and
            `cmp reg, imm` (value = running offset + imm), plus jump tables
            `cmp reg, N; ja; jmp [reg*4+T]` (values off..off+N). Only values
            that are named opcodes count, and a function needs two such values
            unless the single one is an _ACK/_NOT.
  register  `mov eax, fn ... mov edx, opcode ... call 0x0075F080` (static
            JUserClient handler registration) and the runtime handler map.

Output: research/opcode_xrefs.tsv
  opcode, name, response(from pairs), senders, dispatchers, handlers
This is heuristic static evidence; confirm a handler before relying on it.
"""
import argparse
import re
import struct
from collections import defaultdict
from pathlib import Path

import capstone

BASE = 0x400000
ROOT = Path(__file__).resolve().parent.parent
CONSTRUCTORS = {0x408C60, 0x7AEE00}
REGISTER = 0x75F080
REGS = ('eax', 'ebx', 'ecx', 'edx', 'esi', 'edi', 'ebp')


def load_names():
    names, pairs = {}, {}
    for line in open(ROOT / 'server/data/opcodes.tsv', encoding='utf-8'):
        a = line.rstrip('\n').split('\t')
        if a[0].isdigit():
            names[int(a[0])] = a[1]
    p = ROOT / 'server/data/opcode_pairs.tsv'
    if p.exists():
        for line in open(p, encoding='utf-8'):
            a = line.rstrip('\n').split('\t')
            if a[0].isdigit():
                pairs[int(a[0])] = int(a[1])
    return names, pairs


def functions(path):
    for line in open(path, encoding='utf-8'):
        a = line.rstrip('\n').split('\t')
        if len(a) >= 3 and a[0] != 'address':
            yield int(a[0], 16), a[1], int(a[2])


def imm(text):
    try:
        return int(text, 16) if text.startswith('0x') else int(text)
    except ValueError:
        return None


def scan_function(md, img, start, size, names):
    sends, dispatch = set(), set()
    code = img[start - BASE:start - BASE + max(size, 1)]
    offs = {}
    pending_push = []
    last_cmp = None
    for ins in md.disasm(code, start):
        mn, ops = ins.mnemonic, [o.strip() for o in ins.op_str.split(',')]
        if mn == 'push' and imm(ops[0]) in names:
            pending_push.append((imm(ops[0]), 4))
        elif mn == 'call' and ops[0].startswith('0x'):
            if int(ops[0], 16) in CONSTRUCTORS:
                sends.update(op for op, _ in pending_push)
            pending_push = []
        pending_push = [(op, n - 1) for op, n in pending_push if n > 1]
        if len(ops) == 2 and ops[0] in REGS:
            reg, value = ops[0], imm(ops[1])
            if mn == 'sub' and value is not None:
                offs[reg] = offs.get(reg, 0) + value
                dispatch.add(offs[reg])
            elif mn == 'add' and value is not None and value >= 0x80000000:
                offs[reg] = offs.get(reg, 0) + (0x100000000 - value)
                dispatch.add(offs[reg])
            elif mn == 'cmp' and value is not None:
                last_cmp = (reg, offs.get(reg, 0), value)
                dispatch.add(offs.get(reg, 0) + value)
            elif mn in ('mov', 'movzx', 'lea', 'xor', 'pop'):
                offs.pop(reg, None)
        if mn == 'jmp' and '*4' in ins.op_str and last_cmp:
            reg, off, count = last_cmp
            if count < 0x200:
                dispatch.update(range(off, off + count + 1))
    named = {v for v in dispatch if v in names}
    if len(named) < 2:
        named = {v for v in named if names[v].endswith(('_ACK', '_NOT', '_AKC'))}
    return sends, named


def static_registrations(img):
    found = defaultdict(set)
    code = img[0x1000:0xC40000 - BASE]
    for m in re.finditer(rb'\xb8(....)', code, re.S):
        fn = struct.unpack('<I', m.group(1))[0]
        if not 0x401000 <= fn < 0xC40000:
            continue
        s = m.start() + 0x1000
        w = img[s:s + 60]
        j = w.find(b'\xba', 5, 40)
        if j < 0:
            continue
        op = struct.unpack_from('<I', w, j + 1)[0]
        k = w.find(b'\xe8', j + 5, 55)
        if k < 0 or not 0 < op < 0x3000:
            continue
        if s + BASE + k + 5 + struct.unpack_from('<i', w, k + 1)[0] == REGISTER:
            found[op].add(fn)
    return found


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--image', type=Path, default=ROOT / 'research/normal.bin')
    ap.add_argument('--functions', type=Path, default=ROOT / 'research/decompiled/functions.tsv')
    ap.add_argument('-o', '--output', type=Path, default=ROOT / 'research/opcode_xrefs.tsv')
    a = ap.parse_args()
    img = a.image.read_bytes()
    names, pairs = load_names()
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    fnames = {}
    senders, dispatchers = defaultdict(set), defaultdict(set)
    for start, name, size in functions(a.functions):
        fnames[start] = name
        s, d = scan_function(md, img, start, size, names)
        for op in s:
            senders[op].add(start)
        for op in d:
            dispatchers[op].add(start)
    handlers = static_registrations(img)
    hm = ROOT / 'research/client/handler_map.txt'
    if hm.exists():
        for line in open(hm):
            p = line.split()
            if len(p) >= 4:
                try:
                    op, fn = int(p[1], 16), int(p[3], 16)
                except ValueError:
                    continue
                if 0x401000 <= fn < 0xC40000:
                    handlers[op].add(fn)

    def fmt(addrs):
        return ' '.join('%08x' % x for x in sorted(addrs or ()))

    with open(a.output, 'w', encoding='utf-8', newline='\n') as out:
        out.write('opcode\tname\tresponse\tsenders\tdispatchers\thandlers\n')
        for op in sorted(names):
            out.write('%d\t%s\t%s\t%s\t%s\t%s\n' % (
                op, names[op], pairs.get(op, ''), fmt(senders.get(op)), fmt(dispatchers.get(op)),
                fmt(handlers.get(op))))
    covered = sum(1 for op in names if names[op].endswith(('_ACK', '_NOT'))
                  and (dispatchers.get(op) or handlers.get(op)))
    total = sum(1 for op in names if names[op].endswith(('_ACK', '_NOT')))
    sent = sum(1 for op in names if senders.get(op))
    print('opcodes with a sender: %d; ACK/NOT with a receiver: %d/%d -> %s' % (
        sent, covered, total, a.output))


if __name__ == '__main__':
    main()
