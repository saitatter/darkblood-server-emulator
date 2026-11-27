"""Quest request bodies that are parsed by hand (J-wstring tag followed by fixed fields)."""
import struct

from darkblood.core.serialization.jser import WireError, read_varuint, strip_prefix


def quest_id_after_tag(body: bytes) -> int:
    """2073/2346 bodies: J-wstring tag, then u32 quest id (0 if malformed)."""
    try:
        length, offset = read_varuint(body, 0)
        return struct.unpack_from('<I', body, offset + length)[0]
    except (WireError, struct.error):
        return 0


def parse_quest_start_body(body: bytes):
    """Parse 2073 body -> (quest_id, target_class, [skill_hash_1, skill_hash_2]).

    Observed wire format for 2073: J-wstring tag + u32 quest_id + optional 18-byte
    QuestSpecialInfo (i32 action_type, u16 target_class, u32 skill_1_hash,
    u32 skill_2_hash, u32 quest_id). For promotion trial quests (PromotionLv=1),
    the client populates target_class and the jhashes of the 2 chosen tempSkills.
    """
    try:
        length, offset = read_varuint(body, 0)
        tail_off = offset + length
        quest_id = struct.unpack_from('<I', body, tail_off)[0]
        if len(body) >= tail_off + 22:
            _, target_class, s1, s2, _ = struct.unpack_from('<iHIII', body, tail_off + 4)
            return quest_id, target_class, [s1, s2]
        return quest_id, 0xFFFF, []
    except (WireError, struct.error):
        return 0, 0xFFFF, []


def parse_quest_complete_body(body: bytes):
    """Parse 2076 body -> (quest_id, selected reward index); (0, -1) if malformed."""
    try:
        length, offset = read_varuint(body, 0)
        return struct.unpack_from('<Ii', body, offset + length)
    except (WireError, struct.error):
        return 0, -1


def parse_mission_id(body: bytes) -> str:
    """2113 body: 0x7FFFFFFF prefix + J-wstring mission id ('' if malformed)."""
    try:
        data = strip_prefix(body)
        length, offset = read_varuint(data, 0)
        return data[offset:offset + length].decode('utf-16le')
    except (WireError, UnicodeDecodeError):
        return ''


def to_i32(val: int) -> int:
    """Reinterpret an unsigned 32-bit value (e.g. a quest hash) as a signed int."""
    val &= 0xFFFFFFFF
    return val - 0x100000000 if val >= 0x80000000 else val
