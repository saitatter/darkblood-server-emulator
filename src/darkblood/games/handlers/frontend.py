"""Frontend flow: server/channel lists, character list, creation and selection."""
import datetime
import struct
import time

from darkblood.core.serialization.jser import event, varuint, wide_string
from darkblood.games.entities.character import Character, delete_seconds_left
from darkblood.games.entities.items import Bag, Item
from darkblood.games.missions.quests import ActiveQuest
from darkblood.frontend.relay import RELAY_PORT
from darkblood.games.config import CHAR_SLOTS, SERVERS, SQUARES, db_entry, square_entry
from darkblood.games.network.messages import (
    DeleteCharacterAck,
    DeleteCharacterReq,
    JoinSquareAck,
    QuestHistoryNot,
    RelayAddressNot,
    SelectCharacterAck,
    UndeleteCharacterAck,
)
from darkblood.games.state import selected_character

# Pending deletion delay: the client's own text says characters are held for
# 2 days (UI_PUB_006). The client receives the seconds left, not a date.
CHAR_DELETE_DELAY = 2 * 24 * 3600


DEFAULT_ACCOUNT = 'OfflinePlayer'
ACCOUNT_TICKET = b'DBACC:'


def account_from_auth(body: bytes):
    """Account name from a 5386 eERC_AUTHENTICATE_STEAM_GAMEUSER_REQ body.

    Built by 0x0078A160 after 2 eE_ACCEPT_NOT (handler 0x007AE730): it holds
    the SteamID (SteamUser +8) and the auth ticket (SteamUser +0x34). The
    shim's ticket is "DBACC:" + account name (DARKBLOOD_ACCOUNT); the exact
    field layout around it is not recovered, so the marker is searched.
    """
    pos = body.find(ACCOUNT_TICKET)
    if pos < 0:
        return None
    name = bytearray()
    # Live body (2026-11-17): 00 88 "DBACC:Player2;" then unrelated text
    # ("... bytes=13 data=...") without a separator, so the shim ends the
    # name with ';'.
    for b in body[pos + len(ACCOUNT_TICKET):]:
        if b == 0x3B or not 0x20 < b < 0x7f or len(name) >= 32:
            break
        name.append(b)
    return name.decode('ascii') or None


def welcome(account=DEFAULT_ACCOUNT, account_uid=1):
    """5020 eERC_AUTHENTICATE_GAMEUSER_ACK greeting (0x96AF60 / 0xA519A0)."""
    now = datetime.datetime.now()
    body = struct.pack('<IQ', 0, account_uid) + wide_string(account)
    # Flag tuple: (nAccountID, nAuthLevel, bFlag1, m_bAdultUser, bFlag3, nReserved)
    # m_bAdultUser=True unlocks the Blood Effect in client options (JNetUserMgr+0x4C / 0x00577860).
    from darkblood.core import options
    body += struct.pack('<II???Q', 0, 0, False, options.get('adult_content'), False, 0)
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
    return SelectCharacterAck(
        result=0,
        character=c,
        active_quests=active,
        bags=bags,
        items=items,
        skills=char.get('skills', {}) if isinstance(char, dict) else {},
        skill_speeches=char.get('skill_speeches', {}) if isinstance(char, dict) else {},
        locked_skills=char.get('locked_skills', []) if isinstance(char, dict) else [],
        quickslots=[(q['type'], q['slot'], q['ref_id'], q['ref_uid'])
                    for q in (char.get('quickslots', {}) if isinstance(char, dict) else {}).values()
                    if 'slot' in q],
    ).encode()


from darkblood.games.handlers.base import BaseDomainService


class FrontendHandlers(BaseDomainService):
    """Server/channel lists, character list, creation and selection."""

    async def handle_get_server_list(self, correlation: int, body: bytes):
        """Opcode 2402 (eEGS_DB_LIST_GET_REQ) -> 2403 (eEGS_DB_LIST_GET_ACK).

        Client handler: 0x00775340.
        Returns the list of game server clusters (world entries) with status,
        population, and display tags.
        """
        # The u16 after the name is the account's character count on that
        # server: the row filler 0x0062E760 prints it, or UI_191 ("None")
        # when it is below 1. Single offline server, so all characters count.
        char_count = len(self.store().characters(self.account))
        ack = struct.pack('<I', 0) + b'\x17' + varuint(len(SERVERS))
        for key, entry in SERVERS:
            ack += b'\x0f' + struct.pack('<I', key) + db_entry(**dict(entry, u16=char_count))
        await self.transport.send_event(event(2403, ack, correlation), note='DB list ack')

    async def handle_knock_square_list(self, correlation: int, body: bytes):
        """Opcode 2001 (eEGS_KNOCK_SQUARELIST_REQ) -> 2002 (eEGS_KNOCK_SQUARELIST_ACK).

        Client handler: 0x00757810.
        Pings square cluster before requesting the channel list. Result 0 proceeds.
        """
        await self.transport.send_event(event(2002, struct.pack('<I', 0), correlation),
                                        note='knock square list ack')

    async def handle_get_square_list(self, correlation: int, body: bytes):
        """Opcode 2021 (eEGS_SQUARELIST_REQ) -> 2022 (eEGS_SQUARELIST_ACK).

        Client handler: 0x0077A550.
        Returns available channels (squares) and current player density loads.
        """
        ack = struct.pack('<I', 0) + b'\x10' + varuint(len(SQUARES))
        for square in SQUARES:
            ack += square_entry(**square)
        await self.transport.send_event(event(2022, ack, correlation), note='square list ack')

    async def handle_join_square(self, correlation: int, body: bytes):
        """Opcode 5028 (eERC_JOIN_SQUARE_REQ) -> 5029 (eERC_JOIN_SQUARE_ACK).

        Client handler: 0x00757AD0.
        Connects the client session to a chosen town channel and delivers relay address.
        """
        square_id = struct.unpack_from('<Q', body, 4)[0] if len(body) >= 12 else 1
        self.session.square_id = square_id
        await self.transport.send_event(
            event(5029, JoinSquareAck(result=0, square_id=square_id).encode(), correlation),
            note='join square ack'
        )
        # eERC_SQUARE_CHANGE_RELAY_ADDRESS_NOT (5134)
        await self.transport.send_event(
            event(5134, RelayAddressNot(port=RELAY_PORT).encode()),
            note='relay address not'
        )
        from darkblood.games.world import GameWorldManager
        world = GameWorldManager.get()
        previous = world.get_player(self.active_char_id)
        if previous and previous.session is self.session and previous.square_id != square_id:
            player = world.register_player(self.session, previous.char_id, previous.char_data, square_id=square_id)
            await world.broadcast_player_departure(previous)
            await world.broadcast_player_spawn(player)
            await world.broadcast_user_join(player)

    async def handle_get_char_list(self, correlation: int, body: bytes):
        """Opcode 2008 (eEGS_GET_CHARLIST_REQ) -> 2009 (eEGS_GET_CHARLIST_ACK).

        Client handler: 0x0077CFA0.
        Serializes character slots for the account, including 3D model appearances,
        levels, classes, and equipped gear previews.
        """
        from darkblood.player_management.characters import encode_character
        now = int(time.time())
        for char in self.store().characters(self.account):
            if char.get('delete_time') and char['delete_time'] <= now:
                self.store().delete(self.account, char['id'])
        chars = self.store().characters(self.account)
        ack = struct.pack('<I', 0) + b'\x10' + varuint(len(chars))
        for char in chars:
            ack += encode_character(char)
        ack += (b'\x10' + varuint(0) + struct.pack('<BB?', CHAR_SLOTS, 0, False)
                + b'\x17' + varuint(0) + b'\x13' + varuint(0))
        await self.transport.send_event(event(2009, ack, correlation),
                                        note='char list ack (%d)' % len(chars))

    async def handle_select_character(self, correlation: int, body: bytes):
        """Opcode 2006 (eEGS_SELECT_CHAR_REQ) -> 2007 (eEGS_SELECT_CHAR_ACK).

        Client handler: 0x007AA4B0.
        Loads full character data (attributes, active quests, equipment, inventory bags)
        and sends quest completion history refresh (2410).
        """
        char_id = struct.unpack_from('<Q', body, 4)[0] if len(body) >= 12 else 1
        selected_character['id'] = char_id
        self.active_char_id = char_id
        from darkblood.games.state import pending_relay
        pending_relay.append(char_id)
        char = self.store().get(self.account, char_id)
        if not char:
            chars = self.store().characters(self.account)
            char = chars[0] if chars else dict(id=char_id, name=self.account, char_class=1)
        ack = build_select_char_ack(char)
        await self.transport.send_event(event(2007, ack, correlation),
                                        note='select char ack (%d)' % char_id)
        done = [int(q) for q in char.get('quests_done', [])]
        await self.transport.send_event(event(2410, QuestHistoryNot(quest_ids=done).encode()),
                                        note='quest history not (%d)' % len(done))
        # Register in GameWorldManager and broadcast mutual character spawns
        try:
            from darkblood.games.world import GameWorldManager
            player = GameWorldManager.get().register_player(self.session or self, char_id, char,
                                                            square_id=self.square_id)
            await GameWorldManager.get().broadcast_player_spawn(player)
            await GameWorldManager.get().broadcast_user_join(player)
        except Exception:
            pass

    async def handle_create_character(self, correlation: int, body: bytes):
        """Opcode 2012 (eEGS_CREATE_CHARACTER_REQ) -> 2013 (eEGS_CREATE_CHARACTER_ACK).

        Client handler: 0x00758070.
        Validates unique name and custom sliders, creates character record, and assigns
        starter weapon and class armor set.
        """
        from darkblood.player_management.characters import encode_character, parse_create_request
        request = parse_create_request(body)
        self.transport.record('create-character', body, **{k: str(v) for k, v in request.items()})
        char = self.store().create(self.account, request)
        if char is None:
            ack = struct.pack('<I', 1)  # Name already taken
        else:
            ack = struct.pack('<I', 0) + encode_character(char) + struct.pack('<B', 0)
        await self.transport.send_event(event(2013, ack, correlation), note='create character ack')

    async def handle_delete_character(self, correlation: int, body: bytes):
        """Opcode 2014 (eEGS_DELETE_CHARACTER_REQ) -> 2015 (eEGS_DELETE_CHARACTER_ACK).

        Client handler: 0x00758370. Sent by DeleteSelectedCharacter(true)
        (0x006F1DD0 -> 0x007892D0) after the second confirmation box.
        The client then marks the slot as pending deletion (0x006F02E0: +0x5D = 1,
        +0x5E = complete_time) and offers "Cancel Delete" (2246).
        The record is kept until the delay ends (purged by handle_get_char_list).
        complete_time is the number of seconds left: the list passes +0x5E to
        the duration formatter 0x0074F1D0 (divides by 86400/3600/60).
        """
        req = DeleteCharacterReq.decode(body)
        self.transport.record('delete-character', body, char_uid=req.char_uid)
        char = self.store().get(self.account, req.char_uid)
        complete_time = 0
        if char:
            if not char.get('delete_time'):
                char['delete_time'] = int(time.time()) + CHAR_DELETE_DELAY
                self.store().save()
            complete_time = delete_seconds_left(char['delete_time'])
        ack = DeleteCharacterAck(result=0 if char else 1, char_uid=req.char_uid,
                                 complete_time=complete_time).encode()
        await self.transport.send_event(event(2015, ack, correlation),
                                        note=f'delete character ack ({req.char_uid}, {complete_time} s left)')

    async def handle_undelete_character(self, correlation: int, body: bytes):
        """Opcode 2246 (eEGS_UNDELETE_CHARACTER_REQ) -> 2247 (eEGS_UNDELETE_CHARACTER_ACK).

        Sent by UndeleteSelectedCharacter (0x006F1FE0 -> 0x00796BA0), body like
        2014 (live: ffffff7f + i64 uid). Handler 0x0075A8A0 clears the slot's
        pending deletion on result 0.
        """
        req = DeleteCharacterReq.decode(body)
        char = self.store().get(self.account, req.char_uid)
        if char:
            char.pop('delete_time', None)
            self.store().save()
        ack = UndeleteCharacterAck(result=0 if char else 1, char_uid=req.char_uid).encode()
        await self.transport.send_event(event(2247, ack, correlation),
                                        note=f'undelete character ack ({req.char_uid})')

    # Opcode backward-compatibility aliases
    on_2402 = handle_get_server_list
    on_2001 = handle_knock_square_list
    on_2021 = handle_get_square_list
    on_5028 = handle_join_square
    on_2008 = handle_get_char_list
    on_2006 = handle_select_character
    on_2012 = handle_create_character
    on_2014 = handle_delete_character
    on_2246 = handle_undelete_character
