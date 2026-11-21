"""Tests for typed WireMessage inference, JSerBufferWriter, and single-char store saves."""
from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

from tests.common import ROOT  # noqa: F401
from darkblood.core.serialization.wire import (
    Const, JSerBufferWriter, Lit, Map, Raw, Set, Vector, WireMessage,
    f32, h32, i32, i64, u16, u8, wstr,
)
from darkblood.player_management.store import SqliteCharacterStore


@dataclass
class _Nested(WireMessage):
    tag: u8 = 0
    label: wstr = ''


@dataclass
class _TypedPacket(WireMessage):
    OPCODE: ClassVar[int] = 9999
    uid: i64 = 0
    item_hash: h32 = 0
    count: u16 = 1
    ratio: f32 = 0.5
    raw_tail: Raw[4] = bytes(4)
    flags: Set[u16] = field(default_factory=list)
    entries: Vector[_Nested] = field(default_factory=list)
    prices: Map[i32, f32] = field(default_factory=dict)


@dataclass
class _WithConstAndLit(WireMessage):
    result: i32 = 0
    value: u16 = 0
    _WIRE_OK_INDEX: ClassVar[int] = 1
    _WIRE_LAYOUT: ClassVar[tuple] = (
        'result',
        Lit(b'\xaa\xbb'),
        Const(u8, 7),
        'value',
    )


class WireTypingTest(unittest.TestCase):
    def test_typed_message_roundtrip_without_struct_pack(self):
        msg = _TypedPacket(
            uid=42, item_hash=-1, count=5, ratio=1.25, raw_tail=b'\x01\x02',
            flags=[9, 2, 5],
            entries=[_Nested(tag=1, label='Sword'), _Nested(tag=2, label='Shield')],
            prices={10: 2.5, 3: 1.0},
        )
        raw = msg.encode()
        decoded = _TypedPacket.decode(raw)
        self.assertEqual(decoded.uid, 42)
        self.assertEqual(decoded.item_hash, 0xFFFFFFFF)
        self.assertEqual(decoded.count, 5)
        self.assertAlmostEqual(decoded.ratio, 1.25)
        self.assertEqual(decoded.raw_tail, b'\x01\x02\x00\x00')
        self.assertEqual(decoded.flags, [2, 5, 9])  # sets serialize sorted
        self.assertEqual(decoded.entries, msg.entries)
        self.assertEqual(decoded.prices, {3: 1.0, 10: 2.5})

    def test_ok_only_const_and_lit(self):
        err = _WithConstAndLit(result=63, value=123)
        self.assertEqual(len(err.encode()), 4)
        self.assertEqual(_WithConstAndLit.decode(err.encode()), _WithConstAndLit(result=63, value=0))

        ok = _WithConstAndLit(result=0, value=0x1234)
        self.assertEqual(ok.encode(), b'\x00\x00\x00\x00\xaa\xbb\x07\x34\x12')
        self.assertEqual(_WithConstAndLit.decode(ok.encode()), ok)

    def test_jser_writer_primitives(self):
        w = JSerBufferWriter()
        w.write_h32(-1)
        w.write_u16(2)
        w.write_ipv4('127.0.0.1')
        self.assertEqual(w.to_bytes(), b'\xff\xff\xff\xff\x02\x00\x7f\x00\x00\x01')

    def test_sqlite_save_char_updates_single_character(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SqliteCharacterStore(db_path=Path(tmp) / 'test.db')
            c1 = store.create('Acc', {'name': 'HeroOne', 'char_class': 1})
            c2 = store.create('Acc', {'name': 'HeroTwo', 'char_class': 2})
            c1['level'] = 12
            c2['level'] = 99  # unsaved in DB if we only call save_char for c1
            store.save_char('Acc', c1['id'])

            reloaded = SqliteCharacterStore(db_path=Path(tmp) / 'test.db')
            self.assertEqual(reloaded.get('Acc', c1['id'])['level'], 12)
            self.assertEqual(reloaded.get('Acc', c2['id'])['level'], 1)


if __name__ == '__main__':
    unittest.main()
