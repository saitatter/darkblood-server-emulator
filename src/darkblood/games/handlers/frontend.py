"""Frontend flow: server/channel lists, character list, creation and selection."""
import datetime
import struct
import time

from darkblood.core.network.proudnet import RELAY_PORT
from darkblood.core.serialization.jser import event, varuint, wide_string
from darkblood.games.entities.character import Character, delete_seconds_left
from darkblood.games.entities.items import DEPOT_CONTAINER, EQUIPPED, Bag, Item
from darkblood.games.missions.quests import ActiveQuest
from darkblood.games.handlers.skills import learned_skill_map
from darkblood.games.config import CHAR_SLOTS, SERVERS, SQUARES, db_entry, square_entry
from darkblood.games.network.messages import (
    DeleteCharacterAck,
    DeleteCharacterReq,
    DepotInfo,
    DepotSlotInfo,
    JoinSquareAck,
    QuestHistoryNot,
    RelayAddressNot,
    QuickSlot,
    SelectCharacterAck,
    UndeleteCharacterAck,
)

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
    # nAuthLevel=1 unlocks the native GM console (JAppPageCheat / 0x004EF790).
    from darkblood.core import options
    auth_level = 1 if options.get('gm_mode') else 0
    body += struct.pack('<II???Q', 0, auth_level, False, options.get('adult_content'), False, 0)
    body += b'\x17' + varuint(0)
    body += struct.pack('<IIB', 0, 0, 0) + wide_string('')
    body += struct.pack('<6H', now.year, now.month, now.day, now.hour, now.minute, now.second)
    body += struct.pack('<QQH', 0, 0, 0)
    return event(5020, body)


def build_char_details(char):
    """Serialize player details for struct 0x00A52630 using Character model."""
    c = char if isinstance(char, Character) else Character.from_dict(char)
    return c.encode_world_details()


def _build_depot_info(char_dict: dict) -> DepotInfo:
    """Build a DepotInfo entry for 2007 SelectCharacterAck (0x00A40380)."""
    char_uid = int(char_dict.get('id', 1))
    extend_remain = list(char_dict.get('depot_extend_remain', [0, 0]))
    while len(extend_remain) < 2:
        extend_remain.append(0)
    slots = [
        DepotSlotInfo(active=remain > 0, slot_index=idx if remain > 0 else 0xFFFF,
                      expire_date=0, remain_sec=max(0, int(remain)))
        for idx, remain in enumerate(extend_remain[:2])
    ]
    depot_items = [
        Item(owner=char_uid, **i)
        for i in char_dict.get('items', [])
        if i.get('container') == DEPOT_CONTAINER
    ]
    return DepotInfo(
        char_uid=char_uid,
        gold=int(char_dict.get('depot_gold', 0)),
        char_name=char_dict.get('name', ''),
        items=depot_items,
        slots=slots,
        share_expire_time=0,
    )


def build_select_char_ack(char, account_chars=None):
    """Serialize eEGS_SELECT_CHAR_ACK (2007) using SelectCharacterAck model."""
    c = char if isinstance(char, Character) else Character.from_dict(char)
    active = []
    if isinstance(char, dict):
        active = [ActiveQuest.from_store(q, r) for q, r in char.get('quests_active', {}).items()]
    bags, items, depots = [], [], {}
    if isinstance(char, dict):
        bags = [Bag(**b) for b in char.get('bags', [])]
        items = [Item(owner=char.get('id', -1), **i) for i in char.get('items', [])
                 if i.get('container') != DEPOT_CONTAINER]
        depot_sources = account_chars if account_chars is not None else [char]
        for entry in depot_sources:
            if isinstance(entry, dict) and 'id' in entry:
                depots[int(entry['id'])] = _build_depot_info(entry)
    return SelectCharacterAck(
        result=0,
        character=c,
        depots=depots,
        active_quests=sorted(active, key=lambda q: q.uid),
        bags=bags,
        items=items,
        skills=learned_skill_map(char.get('skills', {}), char.get('skill_speeches', {}),
                                 char.get('locked_skills', []),
                                 char.get('skill_show_cooltime', [])) if isinstance(char, dict) else {},
        quickslots=[QuickSlot(*q) for q in sorted(
            (q['type'], q['slot'], q['ref_id'], q['ref_uid'])
            for q in (char.get('quickslots', {}) if isinstance(char, dict) else {}).values()
            if 'slot' in q)],
        daily_dun_enter_counts={
            str(k): int(v) for k, v in (char.get('daily_dun_enter_counts', {}) if isinstance(char, dict) else {}).items()
        },
        daily_dun_clear_counts={
            str(k): int(v) for k, v in (char.get('daily_dun_clear_counts', {}) if isinstance(char, dict) else {}).items()
        },
        waypoints=_build_waypoints_map(char) if isinstance(char, dict) else {},
        citadel_play_count=int(char.get('citadel_play_count', 3)) if isinstance(char, dict) else 3,
    ).encode()


def _build_waypoints_map(char: dict) -> dict:
    """Build {layer_net_id: WaypointData} for 2007 SelectCharacterAck (0x00A3EA00)."""
    from darkblood.games.handlers.square import waypoint_data
    out = {}
    for raw_lid in char.get('waypoints', []):
        lid = int(raw_lid)
        out[lid] = waypoint_data(lid)
    return out


from darkblood.games.dispatcher import packet_handler
from darkblood.games.handlers.base import BaseDomainService


class FrontendHandlers(BaseDomainService):
    """Server/channel lists, character list, creation and selection."""

    @packet_handler(2402)
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

    @packet_handler(2001)
    async def handle_knock_square_list(self, correlation: int, body: bytes):
        """Opcode 2001 (eEGS_KNOCK_SQUARELIST_REQ) -> 2002 (eEGS_KNOCK_SQUARELIST_ACK).

        Client handler: 0x00757810.
        Pings square cluster before requesting the channel list. Result 0 proceeds.
        """
        await self.transport.send_event(event(2002, struct.pack('<I', 0), correlation),
                                        note='knock square list ack')

    @packet_handler(2021)
    async def handle_get_square_list(self, correlation: int, body: bytes):
        """Opcode 2021 (eEGS_SQUARELIST_REQ) -> 2022 (eEGS_SQUARELIST_ACK).

        Client handler: 0x0077A550.
        Returns available channels (squares) and current player density loads.
        """
        ack = struct.pack('<I', 0) + b'\x10' + varuint(len(SQUARES))
        for square in SQUARES:
            ack += square_entry(**square)
        await self.transport.send_event(event(2022, ack, correlation), note='square list ack')

    @packet_handler(5028)
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
        previous = world.get_player(self.session.active_char_id)
        if previous and previous.session is self.session and previous.square_id != square_id:
            player = world.register_player(self.session, previous.char_id, previous.char_data, square_id=square_id)
            await world.broadcast_player_departure(previous)
            await world.broadcast_player_spawn(player)

    @packet_handler(2008)
    async def handle_get_char_list(self, correlation: int, body: bytes):
        """Opcode 2008 (eEGS_GET_CHARLIST_REQ) -> 2009 (eEGS_GET_CHARLIST_ACK).

        Client handler: 0x0077CFA0.
        Serializes character slots for the account, including 3D model appearances,
        levels, classes, and equipped gear previews.
        """
        now = int(time.time())
        for char in self.store().characters(self.account):
            if char.get('delete_time') and char['delete_time'] <= now:
                self.store().delete(self.account, char['id'])
        await self._send_character_list(correlation)

    async def _send_character_list(self, correlation: int):
        from darkblood.player_management.characters import encode_character
        chars = self.store().characters(self.account)
        ack = struct.pack('<I', 0) + b'\x10' + varuint(len(chars))
        for char in chars:
            ack += encode_character(char)
        # Second vector: Item records (0x004B94C0) copied by 0x00538DF0 into
        # the character-select item list. Sent empty, every model showed the
        # bare class default (only the class weapon/shield). Worn items carry
        # their character's id as owner so each model gets its own gear.
        worn = [Item(owner=char['id'], **item) for char in chars
                for item in char.get('items', []) if item.get('container') == EQUIPPED]
        ack += b'\x10' + varuint(len(worn)) + b''.join(item.encode() for item in worn)
        ack += (struct.pack('<BB?', CHAR_SLOTS, 0, False)
                + b'\x17' + varuint(0) + b'\x13' + varuint(0))
        await self.transport.send_event(event(2009, ack, correlation),
                                        note='char list ack (%d)' % len(chars))

    @packet_handler(2006)
    async def handle_select_character(self, correlation: int, body: bytes):
        """Opcode 2006 (eEGS_SELECT_CHAR_REQ) -> 2007 (eEGS_SELECT_CHAR_ACK).

        Client handler: 0x007AA4B0.
        Loads full character data (attributes, active quests, equipment, inventory bags)
        and sends quest completion history refresh (2410).
        """
        char_id = struct.unpack_from('<Q', body, 4)[0] if len(body) >= 12 else 0
        char = self.store().get(self.account, char_id)
        if char is None:
            await self.transport.send_event(event(2007, struct.pack('<I', 1), correlation),
                                            note='select char fail (no character)')
            return
        from darkblood.games.world import GameWorldManager
        world = GameWorldManager.get()
        if self.session.active_char_id != char_id:
            await self.session.dungeon.leave_room()
            await world.remove_session_player(self.session)
        self.session.active_char_id = char_id
        from darkblood.games.progression import active_penalty_notice, refresh_character_timers
        if refresh_character_timers(char):
            self.save_char()
        ack = build_select_char_ack(char, account_chars=self.store().characters(self.account))
        await self.transport.send_event(event(2007, ack, correlation),
                                        note='select char ack (%d)' % char_id)
        done = [int(q) for q in char.get('quests_done', [])]
        await self.transport.send_event(event(2410, QuestHistoryNot(quest_ids=done).encode()),
                                        note='quest history not (%d)' % len(done))
        for ptype in (0, 1):
            pen_not = active_penalty_notice(char, penalty_type=ptype)
            if pen_not is not None:
                await self.transport.send_event(
                    event(2085, pen_not.encode()),
                    note=f'restore dungeon penalty (type={ptype}, count={pen_not.penalty_level}, '
                         f'step={pen_not.penalty_id}, elapsed={pen_not.duration}s)',
                )
        self.session.start_timer_loop()
        # Register in GameWorldManager and broadcast mutual character spawns
        try:
            player = world.register_player(self.session, char_id, char, square_id=self.session.square_id)
            player.loading = True  # town load starts now; peers follow its 5124
            await world.broadcast_player_spawn(player)
        except Exception:
            pass

    @packet_handler(2012)
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
        if char is not None:
            # 2013 adds the new model. Only 2009 applies its worn-item previews.
            await self._send_character_list(correlation)

    @packet_handler(DeleteCharacterReq)
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
                self.save_char()
            complete_time = delete_seconds_left(char['delete_time'])
        ack = DeleteCharacterAck(result=0 if char else 1, char_uid=req.char_uid,
                                 complete_time=complete_time).encode()
        await self.transport.send_event(event(2015, ack, correlation),
                                        note=f'delete character ack ({req.char_uid}, {complete_time} s left)')

    @packet_handler(2246)
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
            self.save_char()
        ack = UndeleteCharacterAck(result=0 if char else 1, char_uid=req.char_uid).encode()
        await self.transport.send_event(event(2247, ack, correlation),
                                        note=f'undelete character ack ({req.char_uid})')

    @packet_handler(2323)
    async def handle_char_nick_change_by_integrate(self, correlation: int, body: bytes):
        """Opcode 2323 (eEGS_CHAR_NICK_CHANGE_BY_INTEGRATE_REQ) -> 2324 (0x0075AD10)."""
        from darkblood.games.network.messages.lobby import (
            CharNickChangeByIntegrateAck, CharNickChangeByIntegrateReq,
        )
        req = CharNickChangeByIntegrateReq.decode(body)
        new_nick = req.new_nick.strip()
        char = self.store().get(self.account, req.char_uid)
        if not char or not new_nick:
            await self.reply(CharNickChangeByIntegrateAck(result=1), correlation,
                             note='char nick change by integrate fail')
            return
        char['name'] = new_nick
        self.store().save_char(self.account, req.char_uid)
        await self.reply(CharNickChangeByIntegrateAck(result=0, char_uid=req.char_uid, new_nick=new_nick),
                         correlation, note=f'char nick change by integrate ack ({new_nick})')

    @packet_handler(2404)
    async def handle_event_delete_character(self, correlation: int, body: bytes):
        """Opcode 2404 (eEGS_EVENT_DELETE_CHARACTER_REQ) -> 2405 (0x0075AF00)."""
        from darkblood.games.network.messages.lobby import EventDeleteCharacterAck, EventDeleteCharacterReq
        req = EventDeleteCharacterReq.decode(body)
        deleted = self.store().delete(self.account, req.char_uid)
        await self.reply(
            EventDeleteCharacterAck(result=0 if deleted else 1, delete_char_uid=req.char_uid),
            correlation, note=f'event delete character ack ({req.char_uid}, deleted={deleted})',
        )

    @packet_handler(2441)
    async def handle_char_slot_extend(self, correlation: int, body: bytes):
        """Opcode 2441 (eEGS_CHARSLOT_EXTEND_REQ) -> 2442 (0x00781000)."""
        from darkblood.games.network.messages.lobby import CharSlotExtendAck, CharSlotExtendReq
        req = CharSlotExtendReq.decode(body)
        self.transport.record('char-slot-extend-req', body, item_uid=req.item_uid)
        await self.reply(CharSlotExtendAck(result=0, limit_create_char=6, items=[]), correlation,
                         note='char slot extend ack')

    @packet_handler(5128)
    async def handle_implied_join_layer(self, correlation: int, body: bytes):
        """Opcode 5128 (eERC_IMPLIED_JOIN_LAYER_REQ, 0x00797480) -> 5031 JoinLayerAck."""
        from darkblood.games.network.messages.lobby import ImpliedJoinLayerReq
        req = ImpliedJoinLayerReq.decode(body)
        layer_body = struct.pack('<iq', 0x7FFFFFFF, req.layer_net_id)
        await self.session.square.handle_join_layer(correlation, layer_body)
