"""Quest state carried in 2007 (active-quest map 0x00A3E450)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from darkblood.core.serialization.jser import to_i32 as _i32
from darkblood.core.serialization.wire import *  # noqa: F403


@dataclass
class ActiveQuest(WireMessage):
    """One entry of the active-quest map in 2007 (reader 0x00A3E450 -> 0x00A209B0).

    Element: tag 0x0F, u32 key (0xB35300) = quest id, then the implicit value
    struct 0x00A49BE0 (0x29 bytes): i64 quest UID, i64 start time, u32 quest id,
    bool tracked, u32 array 0x00A48E50 (varint count, max 5) of mission counters.
    """
    quest_id: int
    uid: i64
    tracked: bool = True
    counters: list = field(default_factory=list)
    start_time: i64 = 0

    _WIRE_LAYOUT: ClassVar[tuple] = (
        Lit(b'\x0f'),
        Computed(i32, lambda s: _i32(s.quest_id)),
        'uid',
        'start_time',
        Computed(i32, lambda s: _i32(s.quest_id)),
        'tracked',
        Computed(Array[i32], lambda s: list(s.counters)[:5]),
    )

    def encode_entry(self) -> bytes:
        return self.encode()

    @classmethod
    def from_store(cls, quest_id, record) -> 'ActiveQuest':
        if isinstance(record, dict):
            return cls(int(quest_id), int(record.get('uid', 1)), bool(record.get('tracked', True)),
                       list(record.get('counters', [])))
        return cls(int(quest_id), int(record))  # older stores kept only the UID
