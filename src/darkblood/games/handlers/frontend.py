"""Frontend flow: server/channel lists, character list, creation and selection."""
import datetime
import struct

from darkblood.core.serialization.jser import event, varuint, wide_string
from darkblood.games.entities.character import Character
from darkblood.games.entities.items import Bag, Item
from darkblood.games.missions.quests import ActiveQuest
from darkblood.frontend.relay import RELAY_PORT
from darkblood.games.config import CHAR_SLOTS, SERVERS, SQUARES, db_entry, square_entry
from darkblood.games.network.messages import (JoinSquareAck, QuestHistoryNot, RelayAddressNot,
                                               SelectCharacterAck)
from darkblood.games.state import selected_character


def welcome():
    # 0x96AF60/0xA519A0. Experimental local session defaults, empty feature map.
    now = datetime.datetime.now()
    body = struct.pack('<IQ', 0, 1) + wide_string('OfflinePlayer')
    body += struct.pack('<II???Q', 0, 0, False, False, False, 0)
    body += b'\x17' + varuint(0)
    body += struct.pack('<IIB', 0, 0, 0) + wide_string('')
    body += struct.pack('<6H', now.year, now.month, now.day, now.hour, now.minute, now.second)
    body += struct.pack('<QQH', 0, 0, 0)
    return event(5020, body)


def build_char_details(char):
    """Serialize player details for struct 0x00A52630 using Character model."""
    c = char if isinstance(char, Character) else Character.from_dict(char)
    return c.encode_world_details()


def build_select_char_ack(char):
    """Serialize eEGS_SELECT_CHAR_ACK (2007) using SelectCharacterAck model."""
    c = char if isinstance(char, Character) else Character.from_dict(char)
    active = []
    if isinstance(char, dict):
        active = [ActiveQuest.from_store(q, r) for q, r in char.get('quests_active', {}).items()]
    bags, items = [], []
    if isinstance(char, dict):
        bags = [Bag(**b) for b in char.get('bags', [])]
        items = [Item(owner=char.get('id', -1), **i) for i in char.get('items', [])]
    return SelectCharacterAck(result=0, character=c, active_quests=active,
                              bags=bags, items=items).encode()


class FrontendHandlers:
    """Server/channel lists, character list, creation and selection."""

    async def on_2402(self, correlation, body):
        # eEGS_DB_LIST_GET_REQ -> eEGS_DB_LIST_GET_ACK, handler 0x775340:
        # u32 result (0xA1EA20), tag 0x17 (0xB35010), map (0x76AFD0).
        # Entry: tag 0x0F (0x754FC0), u32 key (0xB35300), value (0xA496B0).
        ack = struct.pack('<I', 0) + b'\x17' + varuint(len(SERVERS))
        for key, entry in SERVERS:
            ack += b'\x0f' + struct.pack('<I', key) + db_entry(**entry)
        await self.transport.send_event(event(2403, ack, correlation), note='DB list ack')

    async def on_2001(self, correlation, body):
        # eEGS_KNOCK_SQUARELIST_REQ (i32, u32 selected server key) ->
        # eEGS_KNOCK_SQUARELIST_ACK, handler 0x757810: u32 result; 0 proceeds
        # via 0x626390. 2003 (queue position NOT, 0x757840) is not needed.
        await self.transport.send_event(event(2002, struct.pack('<I', 0), correlation),
                                        note='knock square list ack')

    async def on_2021(self, correlation, body):
        # eEGS_SQUARELIST_REQ (i32, u32 server key) -> eEGS_SQUARELIST_ACK,
        # handler 0x77A550: u32 result, tag 0x10, vector (0x4B27F0) of
        # square entries (0xA49700): u64, wstring, u32, u32, u32.
        ack = struct.pack('<I', 0) + b'\x10' + varuint(len(SQUARES))
        for square in SQUARES:
            ack += square_entry(**square)
        await self.transport.send_event(event(2022, ack, correlation), note='square list ack')

    async def on_5028(self, correlation, body):
        # eERC_JOIN_SQUARE_REQ (i32, u64 square id) -> eERC_JOIN_SQUARE_ACK,
        # handler 0x757AD0: u32 result, u64 (stored at window+0xB0; assumed
        # to be the joined square id).
        square_id = struct.unpack_from('<Q', body, 4)[0] if len(body) >= 12 else 1
        await self.transport.send_event(event(5029, JoinSquareAck(result=0, square_id=square_id).encode(), correlation),
                                        note='join square ack')
        # eERC_SQUARE_CHANGE_RELAY_ADDRESS_NOT, handler 0x75AAE0: no result
        # word; implicit 0x1E struct = 6 raw bytes (0xA48910). Without it the
        # relay buffer stays zero and 2007's JP2PClient::Connect (0x7AAD98)
        # throws Proud error 14 "Unknown Internet address" in 0xB54B40.
        await self.transport.send_event(event(5134, RelayAddressNot(port=RELAY_PORT).encode()),
                                        note='relay address not')

    async def on_2008(self, correlation, body):
        # eEGS_GET_CHARLIST_REQ -> eEGS_GET_CHARLIST_ACK, handler 0x77CFA0.
        # The event u64 must match the client's stored session value.
        # Body: u32 result, tag 0x10 vector (0x7739E0) of tag 0x1E +
        # character (0xA4AB30), tag 0x10 vector (0x4B94C0), u8 slot count
        # (-> 0xF23330, shown as "N SLOT"), u8 (-> 0xF44E58), bool,
        # tag 0x17 map (0x7680E0), tag 0x13 container (0x6B9F80).
        from darkblood.player_management.characters import encode_character
        chars = self.store().characters(self.account)
        ack = struct.pack('<I', 0) + b'' + varuint(len(chars))
        for char in chars:
            ack += encode_character(char)  # element tag 0x1E is outside the checked range 15..26
        ack += (b'' + varuint(0) + struct.pack('<BB?', CHAR_SLOTS, 0, False)
                + b'' + varuint(0) + b'' + varuint(0))
        await self.transport.send_event(event(2009, ack, correlation),
                                        note='char list ack (%d)' % len(chars))

    async def on_2006(self, correlation, body):
        # eEGS_SELECT_CHAR_REQ (i32, u64 char id) -> eEGS_SELECT_CHAR_ACK (2007)
        char_id = struct.unpack_from('<Q', body, 4)[0] if len(body) >= 12 else 1
        selected_character['id'] = char_id
        char = self.store().get(self.account, char_id)
        if not char:
            chars = self.store().characters(self.account)
            char = chars[0] if chars else dict(id=char_id, name=self.account, char_class=1)
        from darkblood.player_management.characters import ensure_inventory
        if ensure_inventory(char) and self.store().get(self.account, char.get('id')):
            self.store().save()
        ack = build_select_char_ack(char)
        await self.transport.send_event(event(2007, ack, correlation),
                                        note='select char ack (%d)' % char_id)
        # eEGS_QUEST_HISTORY_REFRESH_NOT (handler 0x76C1E0): restore the
        # completed-quest set persisted by on_2076.
        done = [int(q) for q in char.get('quests_done', [])]
        await self.transport.send_event(event(2410, QuestHistoryNot(quest_ids=done).encode()),
                                        note='quest history not (%d)' % len(done))

    async def on_2012(self, correlation, body):
        # eEGS_CREATE_CHARACTER_REQ -> eEGS_CREATE_CHARACTER_ACK, handler
        # 0x758070: u32 result; if 0: character (0xA4AB30), u8 (-> 0xF44E58).
        from darkblood.player_management.characters import encode_character, parse_create_request
        request = parse_create_request(body)
        self.transport.record('create-character', body, **{k: str(v) for k, v in request.items()})
        char = self.store().create(self.account, request)
        if char is None:
            ack = struct.pack('<I', 1)  # experimental failure code (name in use)
        else:
            ack = struct.pack('<I', 0) + encode_character(char) + struct.pack('<B', 0)
        await self.transport.send_event(event(2013, ack, correlation), note='create character ack')

    async def on_2014(self, correlation, body):
        # eEGS_DELETE_CHARACTER_REQ -> eEGS_DELETE_CHARACTER_ACK (2015), handler 0x758370
        from darkblood.games.network.messages import DeleteCharacterReq, DeleteCharacterAck
        req = DeleteCharacterReq.decode(body)
        self.transport.record('delete-character', body, char_uid=req.char_uid)
        ok = self.store().delete(self.account, req.char_uid)
        result = 0 if ok else 1
        ack = DeleteCharacterAck(result=result, char_uid=req.char_uid, complete_time=0).encode()
        await self.transport.send_event(event(2015, ack, correlation), note=f'delete character ack ({req.char_uid})')
