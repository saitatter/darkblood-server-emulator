"""Mailbox wire messages for Dark Blood Online.
from __future__ import annotations

Binary schemas recovered from:
- Opcode 2219/2220: eEGS_POST_REQUEST_LIST_REQ / ACK (handler 0x007AEF70, struct 0x00A55920).
- Opcode 2221/2222: eEGS_POST_SEND_REQ / ACK (sender 0x00795D70, handler 0x00795F40).
- Opcode 2223/2224: eEGS_POST_READ_REQ / ACK (sender 0x007963C0, handler 0x0075A660).
- Opcode 2225/2226: eEGS_POST_GET_APPEND_ITEM_REQ / ACK (sender 0x0079664C, handler 0x0077F8E0).
- Opcode 2227: eEGS_POST_NEW_ARRIVAL_NOT (handler 0x007965B0).
- Opcode 2234/2235: eEGS_POST_RETURN_REQ / ACK (sender 0x00A33907, handler 0x00771470).
- Opcode 2236/2237: eEGS_POST_DELETE_REQ / ACK (sender 0x007964EC, handler 0x007715F0).
"""
from __future__ import annotations
import struct
from dataclasses import dataclass, field

from darkblood.core.serialization.jser import WireError, read_varuint, varuint, wide_string
from darkblood.games.entities.items import Item
from darkblood.player_management.characters import read_wide


@dataclass
class PostEntry:
    """Mail header & payload struct (deserializer 0x00A55920, 0x8C bytes).

    Layout:
    Tag 0x1E
      i64 uid (+0)
      u8 post_type (+8: 0=normal, 1=system, 2=returned)
      i64 sender_uid (+9)
      bool is_read (+0x11)
      bool has_item (+0x12)
      bool can_return (+0x13)
      i32 remain_days (+0x14)
      i64 gold (+0x18)
      i64 send_time (+0x20)
      J-wstring sender_name (+0x28)
      J-wstring title (+0x44)
      J-wstring content (+0x60)
      Tag 0x10 + vector<Item> (+0x7c)
    """
    uid: int = 0
    post_type: int = 0
    sender_uid: int = 0
    is_read: bool = False
    has_item: bool = False
    can_return: bool = True
    remain_days: int = 30
    gold: int = 0
    send_time: int = 0
    sender_name: str = ''
    title: str = ''
    content: str = ''
    items: list[Item] = field(default_factory=list)

    def encode(self) -> bytes:
        b = bytearray(b'\x1e')
        b += struct.pack(
            '<qBq???iq',
            self.uid,
            self.post_type,
            self.sender_uid,
            self.is_read,
            self.has_item,
            self.can_return,
            self.remain_days,
            self.gold,
        )
        b += struct.pack('<q', self.send_time)
        b += wide_string(self.sender_name)
        b += wide_string(self.title)
        b += wide_string(self.content)
        b += b'\x10' + varuint(len(self.items)) + b''.join(item.encode() for item in self.items)
        return bytes(b)


@dataclass
class PostListReq:
    """Opcode 2219: eEGS_POST_REQUEST_LIST_REQ (0x007962F0)."""
    dummy: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'PostListReq':
        dummy = struct.unpack_from('<i', data, 0)[0] if len(data) >= 4 else 0
        return cls(dummy=dummy)

    def encode(self) -> bytes:
        return struct.pack('<i', self.dummy)


@dataclass
class PostListAck:
    """Opcode 2220: eEGS_POST_REQUEST_LIST_ACK response.

    Binary schema: Reader 0x007AEF70.
    u32 result (0), 2x tag 0x17 map (0x00784F30: inbox, outbox),
    u32 unread_count, bool notify.
    """
    result: int = 0
    inbox: list[PostEntry] = field(default_factory=list)
    outbox: list[PostEntry] = field(default_factory=list)
    unread_count: int = 0
    notify: bool = False

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<I', self.result)
        b = bytearray(struct.pack('<I', self.result))
        # Inbox map (tag 0x17)
        b += b'\x17' + varuint(len(self.inbox))
        for entry in self.inbox:
            b += b'\x0f' + struct.pack('<q', entry.uid) + entry.encode()
        # Outbox map (tag 0x17)
        b += b'\x17' + varuint(len(self.outbox))
        for entry in self.outbox:
            b += b'\x0f' + struct.pack('<q', entry.uid) + entry.encode()
        # unread_count and notify
        b += struct.pack('<I?', self.unread_count, self.notify)
        return bytes(b)


@dataclass
class PostSendReq:
    """Opcode 2221: eEGS_POST_SEND_REQ (0x00795D70).

    Payload wire:
    - J-wstring recipient
    - J-wstring title
    - tag 0x10 + vector<i64> attached item UIDs
    - i64 attached gold
    - i64 extra (COD requested gold)
    - bool is_cod
    """
    recipient: str = ''
    title: str = ''
    items: list[int] = field(default_factory=list)  # attached item UIDs
    gold: int = 0  # attached gold
    extra: int = 0  # COD price
    is_cod: bool = False

    @classmethod
    def decode(cls, data: bytes) -> 'PostSendReq':
        if not data:
            return cls()
        try:
            offset = 0
            recipient, offset = read_wide(data, offset)
            title, offset = read_wide(data, offset)
            items = []
            if offset < len(data) and data[offset] == 0x10:
                count, offset = read_varuint(data, offset + 1)
                for _ in range(count):
                    if offset + 8 <= len(data):
                        items.append(struct.unpack_from('<q', data, offset)[0])
                        offset += 8
            gold = 0
            extra = 0
            is_cod = False
            if offset + 8 <= len(data):
                gold = struct.unpack_from('<q', data, offset)[0]
                offset += 8
            if offset + 8 <= len(data):
                extra = struct.unpack_from('<q', data, offset)[0]
                offset += 8
            if offset < len(data):
                is_cod = bool(data[offset])
                offset += 1
            return cls(recipient=recipient, title=title, items=items, gold=gold, extra=extra, is_cod=is_cod)
        except Exception:
            return cls()

    def encode(self) -> bytes:
        b = bytearray(wide_string(self.recipient) + wide_string(self.title))
        b += b'\x10' + varuint(len(self.items))
        for uid in self.items:
            b += struct.pack('<q', uid)
        b += struct.pack('<qq?', self.gold, self.extra, self.is_cod)
        return bytes(b)


@dataclass
class PostSendAck:
    """Opcode 2222: eEGS_POST_SEND_ACK (0x00795F40).

    Payload wire:
    - i32 result
    - tag 0x10 + vector<Item> updated inventory items
    - i64 remain_gold
    - i16 daily_send_count
    - i16 max_daily_send_count
    """
    result: int = 0
    items: list = field(default_factory=list)
    remain_gold: int = 0
    daily_send_count: int = 1
    max_daily_send_count: int = 30

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        return (struct.pack('<i', self.result)
                + b'\x10' + varuint(len(self.items))
                + b''.join(i.encode() for i in self.items)
                + struct.pack('<qhh', self.remain_gold, self.daily_send_count, self.max_daily_send_count))


@dataclass
class PostReadReq:
    """Opcode 2223: eEGS_POST_READ_REQ (0x007963C0)."""
    mail_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'PostReadReq':
        if len(data) >= 8:
            return cls(mail_uid=struct.unpack_from('<q', data, 0)[0])
        return cls()

    def encode(self) -> bytes:
        return struct.pack('<q', self.mail_uid)


@dataclass
class PostReadAck:
    """Opcode 2224: eEGS_POST_READ_ACK (0x0075A660)."""
    result: int = 0
    mail_uid: int = 0

    def encode(self) -> bytes:
        return struct.pack('<iq', self.result, self.mail_uid)


@dataclass
class PostGetAppendItemReq:
    """Opcode 2225: eEGS_POST_GET_APPEND_ITEM_REQ (0x0079664C)."""
    mail_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'PostGetAppendItemReq':
        if len(data) >= 8:
            return cls(mail_uid=struct.unpack_from('<q', data, 0)[0])
        return cls()


@dataclass
class PostGetAppendItemAck:
    """Opcode 2226: eEGS_POST_GET_APPEND_ITEM_ACK (0x0077F8E0)."""
    result: int = 0
    mail_uid: int = 0
    gold: int = 0
    items: list = field(default_factory=list)

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        return (struct.pack('<iqq', self.result, self.mail_uid, self.gold)
                + b'\x10' + varuint(len(self.items))
                + b''.join(i.encode() for i in self.items))


@dataclass
class PostNewArrivalNot:
    """Opcode 2227: eEGS_POST_NEW_ARRIVAL_NOT (0x007965B0)."""
    def encode(self) -> bytes:
        return b''


@dataclass
class PostReturnReq:
    """Opcode 2234: eEGS_POST_RETURN_REQ (0x00A33907)."""
    mail_id: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'PostReturnReq':
        if len(data) >= 8:
            return cls(mail_id=struct.unpack_from('<q', data, 0)[0])
        return cls()


@dataclass
class PostReturnAck:
    """Opcode 2235: eEGS_POST_RETURN_ACK (0x00771470)."""
    result: int = 0
    mail_uids: list[int] = field(default_factory=list)

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        return (struct.pack('<i', self.result)
                + b'\x10' + varuint(len(self.mail_uids))
                + struct.pack(f'<{len(self.mail_uids)}q', *self.mail_uids))


@dataclass
class PostDeleteReq:
    """Opcode 2236: eEGS_POST_DELETE_REQ (0x007964EC)."""
    mail_uids: list[int] = field(default_factory=list)

    def encode(self) -> bytes:
        return b'\x10' + varuint(len(self.mail_uids)) + b''.join(struct.pack('<q', u) for u in self.mail_uids)

    @classmethod
    def decode(cls, data: bytes) -> 'PostDeleteReq':
        uids = []
        if len(data) >= 2 and data[0] == 0x10:
            count, offset = read_varuint(data, 1)
            for _ in range(count):
                if offset + 8 <= len(data):
                    uids.append(struct.unpack_from('<q', data, offset)[0])
                    offset += 8
        elif len(data) >= 8:
            uids.append(struct.unpack_from('<q', data, 0)[0])
        return cls(mail_uids=uids)


@dataclass
class PostDeleteAck:
    """Opcode 2237: eEGS_POST_DELETE_ACK (0x007715F0)."""
    result: int = 0
    mail_uids: list[int] = field(default_factory=list)

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        return (struct.pack('<i', self.result)
                + b'\x10' + varuint(len(self.mail_uids))
                + struct.pack(f'<{len(self.mail_uids)}q', *self.mail_uids))
