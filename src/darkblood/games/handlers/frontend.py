"""Frontend flow: server/channel lists, character list, creation and selection."""
import datetime
import struct

from darkblood.core.serialization.jser import event, varuint, wide_string
from darkblood.games.entities.character import Character
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
)
from darkblood.games.state import selected_character


def welcome():
    """Build initial session handshake greeting for 0x96AF60 / 0xA519A0."""
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
    return SelectCharacterAck(
        result=0,
        character=c,
        active_quests=active,
        bags=bags,
        items=items
    ).encode()


class FrontendHandlers:
    """Server/channel lists, character list, creation and selection."""

    async def handle_get_server_list(self, correlation: int, body: bytes):
        """Opcode 2402 (eEGS_DB_LIST_GET_REQ) -> 2403 (eEGS_DB_LIST_GET_ACK).

        Client handler: 0x00775340.
        Returns the list of game server clusters (world entries) with status,
        population, and display tags.
        """
        ack = struct.pack('<I', 0) + b'\x17' + varuint(len(SERVERS))
        for key, entry in SERVERS:
            ack += b'\x0f' + struct.pack('<I', key) + db_entry(**entry)
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
        await self.transport.send_event(
            event(5029, JoinSquareAck(result=0, square_id=square_id).encode(), correlation),
            note='join square ack'
        )
        # eERC_SQUARE_CHANGE_RELAY_ADDRESS_NOT (5134)
        await self.transport.send_event(
            event(5134, RelayAddressNot(port=RELAY_PORT).encode()),
            note='relay address not'
        )
        # Register in GameWorldManager only if a character has already been selected
        if self.active_char_id:
            try:
                from darkblood.games.world import GameWorldManager
                char = self.store().get(self.account, self.active_char_id)
                if char:
                    player = GameWorldManager.get().register_player(self, self.active_char_id, char, square_id=square_id)
                    await GameWorldManager.get().broadcast_player_spawn(player)
            except Exception:
                pass

    async def handle_get_char_list(self, correlation: int, body: bytes):
        """Opcode 2008 (eEGS_GET_CHARLIST_REQ) -> 2009 (eEGS_GET_CHARLIST_ACK).

        Client handler: 0x0077CFA0.
        Serializes character slots for the account, including 3D model appearances,
        levels, classes, and equipped gear previews.
        """
        from darkblood.player_management.characters import encode_character
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
            player = GameWorldManager.get().register_player(self, char_id, char, square_id=1)
            await GameWorldManager.get().broadcast_player_spawn(player)
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

        Client handler: 0x00758370.
        Removes character record from the account store.
        """
        req = DeleteCharacterReq.decode(body)
        self.transport.record('delete-character', body, char_uid=req.char_uid)
        ok = self.store().delete(self.account, req.char_uid)
        result = 0 if ok else 1
        ack = DeleteCharacterAck(result=result, char_uid=req.char_uid, complete_time=0).encode()
        await self.transport.send_event(event(2015, ack, correlation), note=f'delete character ack ({req.char_uid})')

    # Opcode backward-compatibility aliases
    on_2402 = handle_get_server_list
    on_2001 = handle_knock_square_list
    on_2021 = handle_get_square_list
    on_5028 = handle_join_square
    on_2008 = handle_get_char_list
    on_2006 = handle_select_character
    on_2012 = handle_create_character
    on_2014 = handle_delete_character
