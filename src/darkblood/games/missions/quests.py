"""Quest state carried in 2007 (active-quest map 0x00A3E450)."""
from dataclasses import dataclass, field

from darkblood.core.serialization.jser import to_i32 as _i32
from darkblood.core.serialization.wire import JSerBufferWriter


@dataclass
class ActiveQuest:
    """One entry of the active-quest map in 2007 (reader 0x00A3E450 -> 0x00A209B0).

    Element: tag 0x0F, u32 key (0xB35300) = quest id, then the implicit value
    struct 0x00A49BE0 (0x29 bytes, initialised by 0x00A5CF80): i64 quest UID,
    i64 start time, u32 quest id, bool tracked, u32 array 0x00A48E50 (varint
    count, max 5) of mission counters. Layout confirmed against 0x00A60960,
    which the 2074 handler calls with (UID, server time from 0x00946570,
    quest id) and sets tracked = (tracked quests < 5, counted by 0x00A5E250).
    The start time's unit is not recovered; 0 is sent.
    """
    quest_id: int
    uid: int
    tracked: bool = True
    counters: list = field(default_factory=list)
    start_time: int = 0

    def encode_entry(self) -> bytes:
        qid = _i32(self.quest_id)
        w = JSerBufferWriter()
        w.write_u8(0x0F)
        w.write_i32(qid)
        w.write_i64(self.uid)
        w.write_i64(self.start_time)
        w.write_i32(qid)
        w.write_bool(self.tracked)
        counters = list(self.counters)[:5]
        w.write_varuint(len(counters))
        for c in counters:
            w.write_i32(c)
        return w.to_bytes()

    @classmethod
    def from_store(cls, quest_id, record) -> 'ActiveQuest':
        if isinstance(record, dict):
            return cls(int(quest_id), int(record.get('uid', 1)), bool(record.get('tracked', True)),
                       list(record.get('counters', [])))
        return cls(int(quest_id), int(record))  # older stores kept only the UID
