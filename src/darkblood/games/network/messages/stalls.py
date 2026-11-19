"""Dark Blood protocol wire messages - Personal Shop (Player Stalls) and Broker (Marketplace)."""
from dataclasses import dataclass, field
import struct
from typing import List, Tuple

from darkblood.core.serialization.jser import (
    read_varuint,
    read_wide,
    strip_prefix,
    varuint,
    wide_string,
)
from darkblood.games.entities.items import Item, UPDATE_OWNER


# --- Personal Shop (Player Stalls) ---

@dataclass
class StallItem:
    """Individual item offered in a player's personal stall."""
    item: Item
    price: int = 0  # AR price (i64)

    def encode(self) -> bytes:
        return b'\x1e' + self.item.encode() + struct.pack('<q', self.price)


@dataclass
class PersonalShopOpenReq:
    """Opcode 2340 (eEGS_PERSONALSHOP_START_REQ).

    Client initiates stall opening with title and items for sale.
    Wire format support:
      - Prefix (0x7FFFFFFF) if present.
      - Wide string title.
      - Tag 0x10 items vector of (item_uid: i64, count: i32, price: i64) or (item_uid, price).
    """
    title: str = ''
    items: list = field(default_factory=list)  # [(item_uid, count, price)]

    @classmethod
    def decode(cls, data: bytes) -> 'PersonalShopOpenReq':
        data = strip_prefix(data)
        if not data:
            return cls()

        offset = 0
        title = ''
        items = []

        # Read wide title if present
        if len(data) >= offset + 2:
            try:
                title, offset = read_wide(data, offset)
            except Exception:
                title = ''

        # Read items vector
        if offset < len(data) and data[offset] == 0x10:
            offset += 1
            count, offset = read_varuint(data, offset)
            for _ in range(count):
                if offset + 20 <= len(data):
                    uid, cnt, prc = struct.unpack_from('<qiq', data, offset)
                    items.append((uid, cnt, prc))
                    offset += 20
                elif offset + 16 <= len(data):
                    uid, prc = struct.unpack_from('<qq', data, offset)
                    items.append((uid, 1, prc))
                    offset += 16
                else:
                    break

        return cls(title=title, items=items)

    def encode(self) -> bytes:
        body = wide_string(self.title) + b'\x10' + varuint(len(self.items))
        for item in self.items:
            if len(item) >= 3:
                body += struct.pack('<qiq', item[0], item[1], item[2])
            elif len(item) == 2:
                body += struct.pack('<qiq', item[0], 1, item[1])
        return body


@dataclass
class PersonalShopOpenAck:
    """Opcode 2341 (eEGS_PERSONALSHOP_START_ACK).

    Server response confirming player stall opening.
    Wire format (0x00601AA0 -> FUN_00A55D70):
      - i32 result (0 = success)
      - If success, Tag 0x1E jPersonalShop struct:
          - i64 owner_uid
          - Tag 0x1E + 6 bytes fixed header/timestamp
          - Tag 0x10 vector of StallItem (Item + i64 price)
          - Tag 0x10 empty vector (sold items)
          - i64 unknown (0)
          - i16 unknown (0)
          - i32 remaining_seconds
          - bool active (True)
          - bool is_open (True)
      - Wide string title attached for UI display.
    """
    result: int = 0
    owner_uid: int = 0
    title: str = ''
    items: list = field(default_factory=list)  # [StallItem]
    expire_time: int = 86400

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)

        body = struct.pack('<i', 0)
        # Tag 0x1E jPersonalShop
        body += b'\x1e' + struct.pack('<q', self.owner_uid)
        body += b'\x1e' + struct.pack('<HBBBB', 2026, 11, 17, 12, 0)
        body += b'\x10' + varuint(len(self.items)) + b''.join(i.encode() for i in self.items)
        body += b'\x10\x80'  # empty vector
        body += struct.pack('<qhi??', 0, 0, self.expire_time, True, True)
        body += wide_string(self.title)
        return body


@dataclass
class PersonalShopCloseReq:
    """Opcode 2342 (eEGS_PERSONALSHOP_CLOSE_REQ)."""
    owner_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'PersonalShopCloseReq':
        data = strip_prefix(data)
        if len(data) >= 8:
            return cls(owner_uid=struct.unpack_from('<q', data, 0)[0])
        return cls()

    def encode(self) -> bytes:
        return struct.pack('<q', self.owner_uid)


@dataclass
class PersonalShopCloseAck:
    """Opcode 2343 (eEGS_PERSONALSHOP_CLOSE_ACK)."""
    result: int = 0
    owner_uid: int = 0

    def encode(self) -> bytes:
        return struct.pack('<iq', self.result, self.owner_uid)


@dataclass
class PersonalShopBuyReq:
    """Opcode 5242 (eERC_PERSONALSHOP_BUYITEM_REQ)."""
    seller_uid: int = 0
    item_uid: int = 0
    count: int = 1

    @classmethod
    def decode(cls, data: bytes) -> 'PersonalShopBuyReq':
        data = strip_prefix(data)
        if len(data) >= 20:
            sid, iid, cnt = struct.unpack_from('<qqi', data, 0)
            return cls(seller_uid=sid, item_uid=iid, count=cnt)
        elif len(data) >= 16:
            sid, iid = struct.unpack_from('<qq', data, 0)
            return cls(seller_uid=sid, item_uid=iid, count=1)
        return cls()

    def encode(self) -> bytes:
        return struct.pack('<qqi', self.seller_uid, self.item_uid, self.count)


@dataclass
class PersonalShopBuyAck:
    """Opcode 5243 (eERC_PERSONALSHOP_BUYITEM_ACK).

    Format (OneERC_PERSONALSHOP_BUYITEM_ACK):
      vecItemOut >> jPersonalShop >> nCurrentAr
    """
    result: int = 0
    gold: int = 0
    items: list = field(default_factory=list)        # [Item] granted/updated for buyer
    stall_items: list = field(default_factory=list)  # [StallItem] remaining in stall
    seller_uid: int = 0
    expire_time: int = 86400

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)

        body = struct.pack('<i', 0)
        # vecItemOut
        body += b'\x10' + varuint(len(self.items)) + b''.join(i.encode() for i in self.items)
        # jPersonalShop
        body += b'\x1e' + struct.pack('<q', self.seller_uid)
        body += b'\x1e' + struct.pack('<HBBBB', 2026, 11, 17, 12, 0)
        body += b'\x10' + varuint(len(self.stall_items)) + b''.join(i.encode() for i in self.stall_items)
        body += b'\x10\x80'
        body += struct.pack('<qhi??', 0, 0, self.expire_time, True, True)
        # nCurrentAr
        body += struct.pack('<q', self.gold)
        return body


@dataclass
class PersonalShopGetProductsReq:
    """Opcode 6021 (eERT_PERSONALSHOP_GET_PRODUCTS_REQ)."""
    seller_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'PersonalShopGetProductsReq':
        data = strip_prefix(data)
        if len(data) >= 8:
            return cls(seller_uid=struct.unpack_from('<q', data, 0)[0])
        return cls()

    def encode(self) -> bytes:
        return struct.pack('<q', self.seller_uid)


@dataclass
class PersonalShopGetProductsAck:
    """Opcode 6022 (eERT_PERSONALSHOP_GET_PRODUCTS_ACK)."""
    result: int = 0
    seller_uid: int = 0
    title: str = ''
    items: list = field(default_factory=list)  # [StallItem]
    expire_time: int = 86400

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)

        body = struct.pack('<iq', 0, self.seller_uid)
        body += wide_string(self.title)
        body += b'\x10' + varuint(len(self.items)) + b''.join(i.encode() for i in self.items)
        body += struct.pack('<i', self.expire_time)
        return body


@dataclass
class PersonalShopChangeNot:
    """Opcode 5250 (eERC_PERSONALSHOP_CHANGE_NOT). Broadcast stall update."""
    seller_uid: int = 0
    title: str = ''
    item_count: int = 0

    def encode(self) -> bytes:
        return struct.pack('<q', self.seller_uid) + wide_string(self.title) + struct.pack('<i', self.item_count)


@dataclass
class PersonalShopStartNot:
    """Opcode 5254 (eERC_PERSONALSHOP_START_NOT). Broadcast stall open."""
    seller_uid: int = 0
    title: str = ''

    def encode(self) -> bytes:
        return struct.pack('<q', self.seller_uid) + wide_string(self.title)


@dataclass
class PersonalShopCloseNot:
    """Opcode 5255 (eERC_PERSONALSHOP_CLOSE_NOT). Broadcast stall close."""
    seller_uid: int = 0

    def encode(self) -> bytes:
        return struct.pack('<q', self.seller_uid)


# --- Broker (Marketplace / Auction House) ---

@dataclass
class BrokerProduct:
    """Single item listing in the central Broker marketplace."""
    item: Item
    price: int = 0
    seller_name: str = ''
    expire_time: int = 86400
    unit_price: int = 0
    listing_id: int = 0

    def encode(self) -> bytes:
        return (b'\x1e' + self.item.encode()
                + struct.pack('<q', self.price)
                + wide_string(self.seller_name)
                + struct.pack('<iqq', self.expire_time, self.unit_price or self.price, self.listing_id))


@dataclass
class BrokerListReq:
    """Opcode 2262 (eEGS_BROKER_LIST_REQ)."""
    page: int = 0
    category: int = 0
    filter_name: str = ''

    @classmethod
    def decode(cls, data: bytes) -> 'BrokerListReq':
        data = strip_prefix(data)
        if len(data) >= 8:
            page, cat = struct.unpack_from('<ii', data, 0)
            filt = ''
            if len(data) > 8:
                try:
                    filt, _ = read_wide(data, 8)
                except Exception:
                    filt = ''
            return cls(page=page, category=cat, filter_name=filt)
        return cls()

    def encode(self) -> bytes:
        return struct.pack('<ii', self.page, self.category) + wide_string(self.filter_name)


@dataclass
class BrokerListAck:
    """Opcode 2263 (eEGS_BROKER_LIST_ACK). (0x005ADAC0)

    Wire format:
      i32 result (0 = success)
      Tag 0x1E:
        Tag 0x10 vector of BrokerProduct
        i32 page
        i32 total_count
    """
    result: int = 0
    products: list = field(default_factory=list)  # [BrokerProduct]
    page: int = 0
    total_count: int = 0

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        body = struct.pack('<i', 0) + b'\x1e\x10' + varuint(len(self.products))
        body += b''.join(p.encode() for p in self.products)
        body += struct.pack('<ii', self.page, self.total_count)
        return body


@dataclass
class BrokerMyListReq:
    """Opcode 2264 (eEGS_BROKER_MYLIST_REQ)."""
    @classmethod
    def decode(cls, data: bytes) -> 'BrokerMyListReq':
        return cls()

    def encode(self) -> bytes:
        return b''


@dataclass
class BrokerMyListAck:
    """Opcode 2265 (eEGS_BROKER_MYLIST_ACK). (0x005ADFF0)

    Wire format:
      i32 result (0 = success)
      Tag 0x10 vector of BrokerProduct
    """
    result: int = 0
    products: list = field(default_factory=list)  # [BrokerProduct]

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        return (struct.pack('<i', 0)
                + b'\x10' + varuint(len(self.products))
                + b''.join(p.encode() for p in self.products))


@dataclass
class BrokerRegistItemReq:
    """Opcode 2266 (eEGS_BROKER_REGIST_ITEM_REQ)."""
    item_uid: int = 0
    count: int = 1
    price: int = 0
    period_hours: int = 24

    @classmethod
    def decode(cls, data: bytes) -> 'BrokerRegistItemReq':
        data = strip_prefix(data)
        if len(data) >= 24:
            uid, cnt, prc, hrs = struct.unpack_from('<qiqi', data, 0)
            return cls(item_uid=uid, count=cnt, price=prc, period_hours=hrs)
        elif len(data) >= 20:
            uid, cnt, prc = struct.unpack_from('<qiq', data, 0)
            return cls(item_uid=uid, count=cnt, price=prc)
        return cls()

    def encode(self) -> bytes:
        return struct.pack('<qiqi', self.item_uid, self.count, self.price, self.period_hours)


@dataclass
class BrokerRegistItemAck:
    """Opcode 2267 (eEGS_BROKER_REGIST_ITEM_ACK)."""
    result: int = 0

    def encode(self) -> bytes:
        return struct.pack('<i', self.result)


@dataclass
class BrokerBuyItemReq:
    """Opcode 2268 (eEGS_BROKER_BUY_ITEM_REQ)."""
    listing_id: int = 0
    count: int = 1

    @classmethod
    def decode(cls, data: bytes) -> 'BrokerBuyItemReq':
        data = strip_prefix(data)
        if len(data) >= 12:
            lid, cnt = struct.unpack_from('<qi', data, 0)
            return cls(listing_id=lid, count=cnt)
        elif len(data) >= 8:
            lid = struct.unpack_from('<q', data, 0)[0]
            return cls(listing_id=lid, count=1)
        return cls()

    def encode(self) -> bytes:
        return struct.pack('<qi', self.listing_id, self.count)


@dataclass
class BrokerBuyItemAck:
    """Opcode 2269 (eEGS_BROKER_BUY_ITEM_ACK)."""
    result: int = 0
    gold: int = 0

    def encode(self) -> bytes:
        return struct.pack('<iq', self.result, self.gold)


@dataclass
class BrokerCancelReq:
    """Opcode 2270 (eEGS_BROKER_CANCEL_REQ)."""
    listing_id: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'BrokerCancelReq':
        data = strip_prefix(data)
        if len(data) >= 8:
            return cls(listing_id=struct.unpack_from('<q', data, 0)[0])
        return cls()

    def encode(self) -> bytes:
        return struct.pack('<q', self.listing_id)


@dataclass
class BrokerCancelAck:
    """Opcode 2271 (eEGS_BROKER_CANCEL_ACK). (0x00789882)"""
    result: int = 0

    def encode(self) -> bytes:
        return struct.pack('<i', self.result)


@dataclass
class BrokerPriceReq:
    """Opcode 2272 (eEGS_BROKER_PRICE_REQ)."""
    item_id: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'BrokerPriceReq':
        data = strip_prefix(data)
        if len(data) >= 4:
            return cls(item_id=struct.unpack_from('<i', data, 0)[0])
        return cls()

    def encode(self) -> bytes:
        return struct.pack('<i', self.item_id)


@dataclass
class BrokerPriceAck:
    """Opcode 2273 (eEGS_BROKER_PRICE_ACK)."""
    result: int = 0
    avg_price: int = 0
    min_price: int = 0

    def encode(self) -> bytes:
        return struct.pack('<iqq', self.result, self.avg_price, self.min_price)
