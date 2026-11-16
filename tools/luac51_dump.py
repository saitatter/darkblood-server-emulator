#!/usr/bin/env python3
"""Minimal Lua 5.1 bytecode reader for the client's lua_tinker-compiled dicts.

Prints each function's constants and, with --ops, a raw opcode listing. It is a
reading aid for recovering data tables (map ids, NPC ids, rewards); it is not a
decompiler. Header verified on Data/Dict files: ``1B 4C 75 61 51 00 01 04 04 04 08 00``
(Lua 5.1, little endian, int/size_t/Instruction = 4, lua_Number = 8, float).
"""
import argparse
import struct
import sys

OPNAMES = ('MOVE LOADK LOADBOOL LOADNIL GETUPVAL GETGLOBAL GETTABLE SETGLOBAL '
           'SETUPVAL SETTABLE NEWTABLE SELF ADD SUB MUL DIV MOD POW UNM NOT LEN '
           'CONCAT JMP EQ LT LE TEST TESTSET CALL TAILCALL RETURN FORLOOP FORPREP '
           'TFORLOOP SETLIST CLOSE CLOSURE VARARG').split()


class Reader:
    def __init__(self, data):
        self.d, self.p = data, 0

    def take(self, n):
        if self.p + n > len(self.d):
            raise ValueError('truncated chunk')
        b = self.d[self.p:self.p + n]
        self.p += n
        return b

    def u8(self):
        return self.take(1)[0]

    def int(self):
        return struct.unpack('<i', self.take(4))[0]

    def string(self):
        n = struct.unpack('<I', self.take(4))[0]
        return self.take(n)[:-1] if n else None


def read_function(r):
    f = {'source': r.string(), 'line': r.int(), 'lastline': r.int()}
    f['nups'], f['nparams'], f['vararg'], f['maxstack'] = r.u8(), r.u8(), r.u8(), r.u8()
    f['code'] = [struct.unpack('<I', r.take(4))[0] for _ in range(r.int())]
    consts = []
    for _ in range(r.int()):
        t = r.u8()
        if t == 0:
            consts.append(None)
        elif t == 1:
            consts.append(bool(r.u8()))
        elif t == 3:
            consts.append(struct.unpack('<d', r.take(8))[0])
        elif t == 4:
            consts.append(r.string())
        else:
            raise ValueError('bad constant type %d' % t)
    f['consts'] = consts
    f['protos'] = [read_function(r) for _ in range(r.int())]
    r.take(4 * r.int())                       # line info
    for _ in range(r.int()):                  # locals
        r.string(); r.int(); r.int()
    for _ in range(r.int()):                  # upvalue names
        r.string()
    return f


def load(data):
    if data[:12] != b'\x1bLuaQ\x00\x01\x04\x04\x04\x08\x00':
        raise ValueError('not a Lua 5.1 x86 chunk')
    r = Reader(data)
    r.take(12)
    return read_function(r)


def fmt_const(c):
    if isinstance(c, bytes):
        return repr(c.decode('cp949', 'replace'))
    if isinstance(c, float) and c.is_integer():
        return str(int(c))
    return repr(c)


def dump(f, ops=False, depth=0, path='main'):
    pad = '  ' * depth
    print('%sfunction %s line %d params %d consts %d code %d' % (
        pad, path, f['line'], f['nparams'], len(f['consts']), len(f['code'])))
    for i, c in enumerate(f['consts']):
        print('%s  K%-4d %s' % (pad, i, fmt_const(c)))
    if ops:
        for pc, ins in enumerate(f['code']):
            op, a = ins & 0x3f, (ins >> 6) & 0xff
            c, b = (ins >> 14) & 0x1ff, (ins >> 23) & 0x1ff
            bx = ins >> 14
            print('%s  %4d %-9s A=%d B=%d C=%d Bx=%d' % (pad, pc, OPNAMES[op], a, b, c, bx))
    for i, p in enumerate(f['protos']):
        dump(p, ops, depth + 1, '%s.%d' % (path, i))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('file')
    ap.add_argument('--ops', action='store_true', help='also list instructions')
    a = ap.parse_args()
    dump(load(open(a.file, 'rb').read()), a.ops)


if __name__ == '__main__':
    sys.exit(main())
