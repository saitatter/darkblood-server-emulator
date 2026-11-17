"""Dark Blood protocol wire messages - Skills domain."""
from dataclasses import dataclass, field
import struct

from darkblood.core.hashing import jhash
from darkblood.core.serialization.jser import read_varuint, varuint, wide_string
from darkblood.games.entities.character import Character, layer_net_id
from darkblood.games.entities.items import Item

def encode_skill_map(skills: dict, speeches: dict = None, locked=()) -> bytes:
    """Tag 0x17 learned-skill map, element reader 0x004ACB80.

    Shared by 2698 (0x007A74A0) and 2007 (0x004B1240 inside 0x00A40760).
    Element: tag 0x0F, u16 key, u16 skill_index, u8 level, wstring speech,
    bool locked, bool unknown (sent 0).
    """
    speeches = speeches or {}
    locked = {int(x) for x in locked}
    out = bytearray(b'\x17') + varuint(len(skills))
    for sidx, lvl in sorted((int(k), int(v)) for k, v in skills.items()):
        out += b'\x0f' + struct.pack('<HHB', sidx, sidx, lvl)
        out += wide_string(speeches.get(str(sidx), ''))
        out += struct.pack('<??', sidx in locked, False)
    return bytes(out)


@dataclass
class LearnSkillReq:
    """Opcode 2050: eEGS_LEARN_SKILL_REQ (0x00780000.c:9504).

    Wire format: u16 sKindNameIndex + u8 ucLevel (3 bytes).
    """
    skill_index: int = 0
    level: int = 1

    @classmethod
    def decode(cls, data: bytes) -> 'LearnSkillReq':
        if len(data) >= 3:
            sidx, lvl = struct.unpack_from('<HB', data, 0)
            return cls(skill_index=sidx, level=lvl)
        return cls()

@dataclass
class LearnSkillAck:
    """Opcode 2051: eEGS_LEARN_SKILL_ACK (On_eEGS_LEARN_SKILL_ACK 0x0078DBE0).

    Wire format: i32 result + u16 sKindNameIndex + u8 ucLevel + i32 nRemainSP + i64 nRemainGold.
    """
    result: int = 0
    skill_index: int = 0
    level: int = 1
    remain_sp: int = 100
    remain_gold: int = 10000

    def encode(self) -> bytes:
        return struct.pack('<iHBiq', self.result, self.skill_index, self.level, self.remain_sp, self.remain_gold)

@dataclass
class UpdateSkillLockedReq:
    """Opcode 2117: eEGS_UPDATE_SKILL_LOCKED_REQ (0x00790000.c:1390).

    Wire format: i16 sKindNameIndex + bool bLocked.
    """
    skill_index: int = 0
    locked: bool = False

    @classmethod
    def decode(cls, data: bytes) -> 'UpdateSkillLockedReq':
        if len(data) >= 3:
            skill_index, locked = struct.unpack_from('<h?', data, 0)
            return cls(skill_index=skill_index, locked=locked)
        return cls()

@dataclass
class UpdateSkillLockedAck:
    """Opcode 2118: eEGS_UPDATE_SKILL_LOCKED_ACK (On_eEGS_UPDATE_SKILL_LOCKED_ACK 0x00752C70).

    Wire format: i32 result + i16 sKindNameIndex + bool bLocked.
    """
    result: int = 0
    skill_index: int = 0
    locked: bool = False

    def encode(self) -> bytes:
        return struct.pack('<ih?', self.result, self.skill_index, self.locked)

@dataclass
class ModifySkillSpeechReq:
    """Opcode 2053: eEGS_MODIFY_SKILL_SPEECH_REQ (0x00780000.c:9674).

    Wire format: u16 sKindNameIndex + wide string strSpeech.
    """
    skill_index: int = 0
    speech: str = ''

    @classmethod
    def decode(cls, data: bytes) -> 'ModifySkillSpeechReq':
        if len(data) >= 2:
            sidx = struct.unpack_from('<H', data, 0)[0]
            speech = ''
            if len(data) > 2:
                rem = data[2:]
                speech = rem.decode('utf-16le', errors='replace')
            return cls(skill_index=sidx, speech=speech)
        return cls()

@dataclass
class ModifySkillSpeechAck:
    """Opcode 2054: eEGS_MODIFY_SKILL_SPEECH_ACK (On_eEGS_MODIFY_SKILL_SPEECH_ACK 0x0078E090).

    Wire format: i32 result + u16 sKindNameIndex + wide string strSpeech.
    """
    result: int = 0
    skill_index: int = 0
    speech: str = ''

    def encode(self) -> bytes:
        return struct.pack('<iH', self.result, self.skill_index) + wide_string(self.speech)

@dataclass
class DeleteSkillSpeechReq:
    """Opcode 2055: eEGS_DELETE_SKILL_SPEECH_REQ (0x00780000.c:9708).

    Wire format: u16 sKindNameIndex.
    """
    skill_index: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'DeleteSkillSpeechReq':
        if len(data) >= 2:
            return cls(skill_index=struct.unpack_from('<H', data, 0)[0])
        return cls()

@dataclass
class DeleteSkillSpeechAck:
    """Opcode 2056: eEGS_DELETE_SKILL_SPEECH_ACK (On_eEGS_DELETE_SKILL_SPEECH_ACK 0x0078E270).

    Wire format: i32 result + u16 sKindNameIndex.
    """
    result: int = 0
    skill_index: int = 0

    def encode(self) -> bytes:
        return struct.pack('<iH', self.result, self.skill_index)

@dataclass
class InitSkillNot:
    """Opcode 2280: eEGS_INIT_SKILL_NOT (0x00797740)."""
    result: int = 0
    sp: int = 0

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        return struct.pack('<ii', self.result, self.sp) + b'\x17\x80'

@dataclass
class UseLearnSkillItemReq:
    """Opcode 2111: eEGS_USE_LEARN_SKILL_ITEM_REQ."""
    item_uid: int = 0
    skill_id: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'UseLearnSkillItemReq':
        if len(data) >= 10:
            item_uid, skill_id = struct.unpack_from('<qh', data, 0)
            return cls(item_uid=item_uid, skill_id=skill_id)
        return cls()

@dataclass
class UseLearnSkillItemAck:
    """Opcode 2112: eEGS_USE_LEARN_SKILL_ITEM_ACK (0x0078BCD0)."""
    result: int = 0
    skill_id: int = 0
    skill_level: int = 1
    item_code: int = 0
    count: int = 1
    items: list = field(default_factory=list)
    sp: int = 0

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        return (struct.pack('<ihBii', self.result, self.skill_id, self.skill_level, self.item_code, self.count)
                + b'\x10' + varuint(len(self.items))
                + b''.join(i.encode() for i in self.items)
                + struct.pack('<i', self.sp))

@dataclass
class InsertApNot:
    """Opcode 2109: eEGS_INSERT_AP_NOT (0x00790480)."""
    current_ap: int = 0
    total_ap: int = 0

    def encode(self) -> bytes:
        return struct.pack('<ii', self.current_ap, self.total_ap)

@dataclass
class LearnSkillListReq:
    """Opcode 2697: eEGS_LEARN_SKILL_LIST_REQ (0x007A73D0).

    Wire format:
      [optional i32 prefix = 0x7fffffff]
      tag 0x10 (std::vector)
      varuint count
      for each:
        tag 0x0F
        u16 skill_index
        u8 level
    """
    skills: list = field(default_factory=list)  # [(skill_index, level), ...]

    @classmethod
    def decode(cls, data: bytes) -> 'LearnSkillListReq':
        from darkblood.core.serialization.jser import strip_prefix
        data = strip_prefix(data)
        if not data:
            return cls()
        offset = 0
        skills = []
        try:
            if data[offset] == 0x10:
                offset += 1
            count, offset = read_varuint(data, offset)
            for _ in range(count):
                if offset < len(data) and data[offset] == 0x0f:
                    offset += 1
                if offset + 3 <= len(data):
                    sidx, lvl = struct.unpack_from('<HB', data, offset)
                    offset += 3
                    skills.append((sidx, lvl))
        except Exception:
            pass
        return cls(skills=skills)

@dataclass
class LearnSkillListAck:
    """Opcode 2698: eEGS_LEARN_SKILL_LIST_ACK (On_opcode_2698 0x007A74A0).

    Wire format:
      i32 result (0 = success)
      tag 0x17 (std::map)
      varuint count
      for each:
        tag 0x0F
        u16 skill_index (key)
        u16 skill_index (val)
        u8 level
        wide_string speech (empty: varuint(0) = b'\x80')
        bool locked (b'\x00')
        bool unknown (b'\x00')
      i32 remain_sp
      i64 remain_gold
    """
    result: int = 0
    skills: dict = field(default_factory=dict)  # {skill_index: level}
    remain_sp: int = 100
    remain_gold: int = 10000

    def encode(self) -> bytes:
        buf = bytearray()
        buf.extend(struct.pack('<i', self.result))
        buf.extend(encode_skill_map(self.skills))
        buf.extend(struct.pack('<iq', self.remain_sp, self.remain_gold))
        return bytes(buf)

