"""Dark Blood protocol wire messages - Quests domain."""
from dataclasses import dataclass, field
import struct

from darkblood.core.hashing import jhash
from darkblood.core.serialization.jser import read_varuint, varuint, wide_string
from darkblood.games.entities.character import Character, layer_net_id
from darkblood.games.entities.items import Item

@dataclass
class QuestStartAck:
    """Opcode 2074: eEGS_QUEST_START_ACK (JAppPageTalkBox, case 0x659F00 -> 0x659790).

    Field names from the handler's read-failure message
    ("iQuestID >> iQuestUID >> jInfo >> vecItem"): u32 result, i32 iQuestID
    (jhash of the quest key, e.g. 'Q0001S01'), i64 iQuestUID, tag 0x1e +
    jInfo = 18 raw bytes (0x00A48A90; the client initialises it as i32 -1,
    u16 0xFFFF, 3 x i32 -1, sent unchanged here), tag 0x10 vecItem (item vector
    0x4B9210, empty). The quest UID is a local counter.
    """
    result: int = 0
    quest_id: int = 0
    quest_uid: int = 1

    def encode(self) -> bytes:
        qid = self.quest_id - (1 << 32) if self.quest_id >= 1 << 31 else self.quest_id
        info = struct.pack('<iHiii', -1, 0xFFFF, -1, -1, -1)
        return struct.pack('<Iiq', self.result, qid, self.quest_uid) + info + b'\x10' + varuint(0)

@dataclass
class QuestUpdateNot:
    """Opcode 2075: eEGS_QUEST_UPDATE_NOT (JAppPageQuestDlg::On_eEGS_QUEST_UPDATE_NOT, 0x0061c7e0).

    Wire format: tag 0x10 vector of quest objective updates.
    Each element: tag 0x1e (struct) + 12 bytes:
      i32 quest_id (jhash, e.g. jhash('Q0882S01'))
      i32 objective_index (0-based)
      i32 count (current progress / kill count)
    """
    updates: list = field(default_factory=list)  # [(quest_id, objective_index, count)]

    def encode(self) -> bytes:
        body = b'\x10' + varuint(len(self.updates))
        for qid, obj_idx, count in self.updates:
            q_signed = qid - (1 << 32) if qid >= 1 << 31 else qid
            body += b'\x1e' + struct.pack('<iii', q_signed, obj_idx, count)
        return body

@dataclass
class QuestHistoryNot:
    """Opcode 2410: eEGS_QUEST_HISTORY_REFRESH_NOT (handler 0x0076C1E0).

    Names from the read-failure message ("setQuestHistory >> bWeekly"): tag
    0x13 set of i32 quest ids (jhash of 'Q....S..'), bool bWeekly.
    """
    quest_ids: list = field(default_factory=list)
    weekly: bool = False

    def encode(self) -> bytes:
        body = b'\x13' + varuint(len(self.quest_ids))
        for q in sorted(self.quest_ids):
            body += struct.pack('<i', q - (1 << 32) if q >= 1 << 31 else q)
        return body + struct.pack('<?', self.weekly)

@dataclass
class QuestCompleteAck:
    """Opcode 2077: eEGS_QUEST_COMPLETE_ACK (JAppPageTalkBox, case 0x659F00 -> 0x656870).

    u32 result, then implicit struct jAck (reader 0x00A55B70), consumed by
    0x00656870 (local offsets confirmed against the reader):
      +0x00 i32 quest id (0x00A7B390 lookup)
      +0x04 i32 index passed to 0x00A88560 (-1 skips its table; 0 observed safe)
      +0x08 jInfo 18 raw bytes; first i32 1/2 selects extra actions (2 =
            class change, "GAME_241"); -1 = none
      +0x1A i32 (not read by the consumer)
      +0x1E i64 new gold total: diff with player +0x70 (= 2007 details +0x45,
            Character.u66) is announced ("GAME_783"), then stored
      +0x26 tag 0x10 item vector (0x004B94C0) -> inventory insert 0x007741D0
      +0x36 tag 0x17 map (0x004B0310), meaning unknown
      +0x42 i32 shown as floating number type 0xC when the quest's reward
            field (+0x19C of the quest prop) is positive: reward EXP
      +0x46 i32 floating number type 0xE when positive: reward GP
    The consumer never writes the player's EXP; the server persists it and
    the client sees it at the next selection.
    """
    result: int = 0
    quest_id: int = 0
    total: int = 0
    exp: int = 0
    gp: int = 0
    items: list = field(default_factory=list)  # [Item]

    def encode(self) -> bytes:
        qid = self.quest_id - (1 << 32) if self.quest_id >= 1 << 31 else self.quest_id
        info = struct.pack('<iHiii', -1, 0xFFFF, -1, -1, -1)
        return (struct.pack('<Iii', self.result, qid, 0) + info + struct.pack('<iq', 0, self.total)
                + b'\x10' + varuint(len(self.items)) + b''.join(i.encode() for i in self.items)
                + b'\x17' + varuint(0)
                + struct.pack('<ii', self.exp, self.gp))

@dataclass
class TutorialQuestStartAck:
    """Opcode 2347: eEGS_TUTORIAL_QUEST_START_ACK response.

    Binary schema: Reader 0x006481E0.
    u32 result (0 = success).
    """
    result: int = 0

    def encode(self) -> bytes:
        return struct.pack('<I', self.result)

@dataclass
class QuestGiveupReq:
    """Opcode 2078: eEGS_QUEST_GIVEUP_REQ."""
    quest_id: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'QuestGiveupReq':
        if len(data) >= 4:
            return cls(quest_id=struct.unpack_from('<I', data, 0)[0])
        return cls()

@dataclass
class QuestGiveupAck:
    """Opcode 2079: eEGS_QUEST_GIVEUP_ACK (0x006223B0)."""
    result: int = 0
    quest_id: int = 0

    def encode(self) -> bytes:
        return struct.pack('<iI', self.result, self.quest_id) + b'\x1e\x10\x80'

@dataclass
class QuestFailReq:
    """Opcode 2080: eEGS_QUEST_FAIL_REQ."""
    quest_id: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'QuestFailReq':
        if len(data) >= 4:
            return cls(quest_id=struct.unpack_from('<I', data, 0)[0])
        return cls()

@dataclass
class QuestFailAck:
    """Opcode 2081: eEGS_QUEST_FAIL_ACK (0x006223B0)."""
    result: int = 0
    quest_id: int = 0

    def encode(self) -> bytes:
        return struct.pack('<iI', self.result, self.quest_id) + b'\x1e\x10\x80'


# --- Enchanting & Upgrade Opcodes (2254-2259, 2284-2285, 2672-2673) ---

@dataclass
class ClearTutorialAck:
    """Opcode 2083: eEGS_CLEAR_TUTORIAL_ACK response.

    Binary schema: Reader 0x0077EEB0.
    u32 result (0 = success) + tag 0x10 vector (0x4B9210).
    Transitions the client into Town Scene (Scene 9) via 0x006DBFA0(9).
    """
    result: int = 0
    elements: list = field(default_factory=list)

    def encode(self) -> bytes:
        return (struct.pack('<I', self.result) + b'\x10' + varuint(len(self.elements))
                + b''.join(item.encode() for item in self.elements))

@dataclass
class GuideBeginnerUpdateReq:
    """Opcode 2358: eEGS_GUIDE_BEGINNER_UPDATE_REQ (0x0079A3B0).

    Sent by the client to update completed/viewed beginner guide IDs.
    Wire format: i32 prefix (0x7FFFFFFF) + vector (tag 0x10) of u32 guide IDs.
    """
    prefix: int = 0x7FFFFFFF
    guide_ids: list = field(default_factory=list)

    @classmethod
    def decode(cls, data: bytes) -> 'GuideBeginnerUpdateReq':
        if len(data) < 4:
            return cls()
        prefix = struct.unpack_from('<i', data, 0)[0]
        offset = 4
        guide_ids = []
        if offset < len(data) and data[offset] == 0x10:
            offset += 1
            count, offset = read_varuint(data, offset)
            for _ in range(count):
                if offset + 4 <= len(data):
                    guide_ids.append(struct.unpack_from('<I', data, offset)[0])
                    offset += 4
        return cls(prefix=prefix, guide_ids=guide_ids)
