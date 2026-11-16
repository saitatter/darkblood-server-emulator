"""JSerBuffer/JEvent envelope recovered from client 0xA1EB90/0xB35E50."""
import datetime
import struct
import zlib

from models import (
    BackToSquareAck,
    ChannelSquare,
    Character,
    ClearTutorialAck,
    CreateRoomAck,
    CurrentCashAck,
    FriendListAck,
    GameServer,
    GTargetListAck,
    GuildOrAttendanceAck,
    JoinSquareAck,
    layer_net_id,
    NpcFirstMeetAck,
    PostListAck,
    QuestHistoryNot,
    QuestCompleteAck,
    QuestStartAck,
    RelayAddressNot,
    RoomInfoListAck,
    RouletteManagerInfoAck,
    SelectCharacterAck,
    StoreInfoAck,
    TamingMonsterDeleteAck,
    TamingMonsterInsertAck,
    TutorialQuestStartAck,
    varuint,
    wide_string,
)


def varuint(value):
    if not 0 <= value <= 0xffffffff:
        raise ValueError('JSerBuffer length must fit uint32')
    result = bytearray()
    while value >= 128:
        result.append(value & 127)
        value >>= 7
    result.append(value | 128)
    return bytes(result)


def wide_string(text):
    raw = text.encode('utf-16le')
    return varuint(len(raw)) + raw


def event(opcode, body=b'', correlation=0):
    # Nonempty body includes a compression boolean; empty body omits it.
    return (struct.pack('<IQ', opcode, correlation) + varuint(len(body))
            + (b'\x00' + body if body else b''))


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


def db_entry(name, u16=0, u64=0, flag_a=False, flag_b=False, flag_c=True):
    return GameServer(name=name, u16=u16, u64=u64, flag_a=flag_a, flag_b=flag_b, flag_c=flag_c).encode()


# Experimental local server list (map key -> entry).
SERVERS = [(1, dict(name='Offline'))]


def square_entry(square_id, name, a=0, b=100, c=0):
    return ChannelSquare(square_id=square_id, name=name, a=a, load=b, c=c).encode()


# Square relay endpoint (opcode 5134). Reader 0xA48910 copies 6 raw bytes
# into the buffer at [handler owner + 0x6C]; JP2PFactory::Connect (0x956A90)
# uses them as IPv4 address bytes in network order + u16 little-endian port
# (observed: shim logged connect() -> 127.0.0.1:9401 before redirection).
RELAY_PORT = 9401


def relay_address(port=RELAY_PORT):
    return bytes([127, 0, 0, 1]) + struct.pack('<H', port)


# Relay PIDL (game-defined, not ProudNet internal). Proxy C2S vtable 0xD1CD80:
#   1001 JoinGroup  (0x956420/0x956500), 1002 LeaveGroup (0x9565E0/0x9566C0)
#   args: u32 group type, {i64, i64} (0x977610), i64 (0xB6D3B0)
# Stub S2C (0x9567A0, JS2CStub 0x96C220):
#   3001 JoinGroupACK: u32 group HostID (-> factory+0x6C, 0x963CE0),
#   ByteArray (scalar length + bytes) holding a JSerBuffer:
#   tag 0x10, varuint count, entries {tag 0x0F, u64 char UID, u32 HostID}
#   (0x90DD90 / 0x90CC90 / 0x6AD6C0). 0x96BC60 then expects a P2P link to
#   every member except the local character.
RELAY_RMI = {1001: 'JoinGroup', 1002: 'LeaveGroup'}
RELAY_GROUP_HOST_ID = 0x10000  # local choice; any HostID distinct from peers
selected_character = {'id': 0}  # set by 2006 on the game connection


def join_group_ack(group_host_id, members):
    from proudnet import scalar
    body = b'' + varuint(len(members))
    for char_uid, host_id in members:
        body += b'' + struct.pack('<QI', char_uid, host_id)
    return (b'' + struct.pack('<HI', 3001, group_host_id)
            + scalar(len(body)) + body)


async def relay_rmi(transport, rmi_id, args):
    transport.record('relay-rmi', args, rmi=RELAY_RMI[rmi_id])
    if rmi_id == 1001:
        members = [(selected_character['id'], transport.host_id)]
        await transport.send_payload(join_group_ack(RELAY_GROUP_HOST_ID, members),
                                     note='relay JoinGroupACK 3001')


CHAR_SLOTS = 4  # first u8 of 2009: shown as "4 SLOT" on character select (observed)

SQUARES = [dict(square_id=1, name='Channel 1')]


def build_char_details(char):
    """Serialize player details for struct 0x00A52630 using Character model."""
    c = char if isinstance(char, Character) else Character.from_dict(char)
    return c.encode_world_details()


def build_select_char_ack(char):
    """Serialize eEGS_SELECT_CHAR_ACK (2007) using SelectCharacterAck model."""
    c = char if isinstance(char, Character) else Character.from_dict(char)
    return SelectCharacterAck(result=0, character=c).encode()


class WireError(ValueError):
    pass


def read_varuint(data, offset):
    value = shift = 0
    while True:
        if offset >= len(data):
            raise WireError('Truncated J-varuint')
        byte = data[offset]
        offset += 1
        value |= (byte & 127) << shift
        if byte & 128:
            return value, offset
        shift += 7
        if shift > 35:
            raise WireError('J-varuint too long')


def parse_event(data):
    """Return (opcode, correlation, compressed, body) for a JEvent."""
    if len(data) < 13:
        raise WireError('Truncated JEvent header')
    opcode, correlation = struct.unpack_from('<IQ', data)
    size, offset = read_varuint(data, 12)
    if size == 0:
        return opcode, correlation, False, b''
    if offset + 1 + size > len(data):
        raise WireError('Truncated JEvent body')
    return opcode, correlation, bool(data[offset]), data[offset + 1:offset + 1 + size]


class GameSession:
    """Application layer. Only responses with recovered parsers belong here."""

    def __init__(self, transport):
        self.transport = transport
        self.account = 'OfflinePlayer'  # single local account (Steam shim persona)

    async def on_connected(self):
        if getattr(self.transport.server, 'role', 'game') != 'game':
            return
        await self.transport.send_event(welcome(), note='welcome 5020')

    async def on_user_message(self, data):
        try:
            opcode, correlation, compressed, body = parse_event(data)
        except WireError as exc:
            self.transport.record('bad-event', data, error=str(exc))
            return
        if compressed and len(body) > 6 and body[4] == 0x78:
            # Observed (2073, 2216, 2346): u32 inflated size + zlib stream.
            # 2203 also sets the flag with a plain body, so inflate only when
            # a zlib header follows and the size matches; otherwise keep it.
            try:
                inflated = zlib.decompress(body[4:])
                if len(inflated) == struct.unpack_from('<I', body)[0]:
                    body = inflated
            except zlib.error:
                pass
        self.transport.record('event', body, opcode=opcode, opcode_hex='0x%04x' % opcode,
                              correlation=correlation, compressed=compressed)
        if getattr(self.transport.server, 'role', 'game') != 'game':
            self.transport.record('relay-event', body, opcode=opcode)
            return
        handler = getattr(self, 'on_%d' % opcode, None)
        if handler is None:
            self.transport.record('unhandled-event', body, opcode=opcode)
            return
        await handler(correlation, body)

    async def on_2203(self, correlation, body):
        # eEGS_COMPUTER_STAT_NOT: client hardware report; notification only.
        pass

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
        from characters import encode_character
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
        from characters import encode_character, parse_create_request
        request = parse_create_request(body)
        self.transport.record('create-character', body, **{k: str(v) for k, v in request.items()})
        char = self.store().create(self.account, request)
        if char is None:
            ack = struct.pack('<I', 1)  # experimental failure code (name in use)
        else:
            ack = struct.pack('<I', 0) + encode_character(char) + struct.pack('<B', 0)
        await self.transport.send_event(event(2013, ack, correlation), note='create character ack')

    async def on_2219(self, correlation, body):
        # eEGS_POST_REQUEST_LIST_ACK (2220), handler 0x7AEF70:
        # result, two tagged maps, u32 unread count, bool notification flag.
        # Empty mailbox is a local offline default; notification stays false.
        ack = PostListAck().encode()
        await self.transport.send_event(event(2220, ack, correlation),
                                        note='empty post list ack')

    async def on_2131(self, correlation, body):
        # eEGS_FRIEND_LIST_REQUEST_REQ -> eEGS_FRIEND_LIST_REQUEST_ACK (2132), handler 0x7712E0:
        # u32 result (0), tag 0x17 map (0x76AE20). Empty map is b'\x17\x00'.
        ack = FriendListAck().encode()
        await self.transport.send_event(event(2132, ack, correlation), note='friend list ack')

    async def on_2569(self, correlation, body):
        # Opcode 2569 -> 2570 ACK, handler 0x772160:
        # u32 result (0), tag 0x17 map (0x76AE20). Empty map is b'\x17\x00'.
        ack = GuildOrAttendanceAck().encode()
        await self.transport.send_event(event(2570, ack, correlation), note='opcode 2570 ack')

    async def on_2082(self, correlation, body):
        # eEGS_CLEAR_TUTORIAL_REQ -> eEGS_CLEAR_TUTORIAL_ACK (2083), handler 0x77EEB0:
        # u32 result (0), tag 0x10 vector (0x4B9210). Empty vector is b'\x10\x00'.
        # Persist tutorial completion in character storage so tutorial is skipped.
        char_id = selected_character.get('id', 1)
        char = self.store().get(self.account, char_id)
        if char:
            char['tutorial_cleared'] = True
            self.store().save()
        ack = ClearTutorialAck().encode()
        await self.transport.send_event(event(2083, ack, correlation), note='clear tutorial ack')

    async def on_2094(self, correlation, body):
        # eEGS_NPC_FIRST_MEET_REQ -> eEGS_NPC_FIRST_MEET_ACK (2095), handler 0x752B60:
        # body: i32 dummy (0x7FFFFFFF), u32 npc_id.
        # ack: u32 result (0), u32 npc_id.
        npc_id = struct.unpack_from('<I', body, 4)[0] if len(body) >= 8 else 0
        ack = NpcFirstMeetAck(result=0, npc_id=npc_id).encode()
        await self.transport.send_event(event(2095, ack, correlation),
                                        note='npc first meet ack (npc %d)' % npc_id)

    async def on_5045(self, correlation, body):
        # eERC_BACK_TO_SQUARE_REQ -> eERC_BACK_TO_SQUARE_ACK (5046), handler 0x7897F0.
        # Request body layout not recovered; the reply schema is in BackToSquareAck.
        ack = BackToSquareAck(square_uid=SQUARES[0]['square_id']).encode()
        await self.transport.send_event(event(5046, ack, correlation),
                                        note='back to square ack')

    async def on_5124(self, correlation, body):
        # eERC_GTARGET_LIST_REQ (empty, fire-and-forget from SquarePlay 0x6F9AB9)
        # -> eERC_GTARGET_LIST_ACK 5125: u32 result + empty 0x10 vector.
        await self.transport.send_event(event(5125, GTargetListAck().encode(), correlation),
                                        note='gtarget list ack')

    async def on_2065(self, correlation, body):
        # eEGS_GET_STORE_INFO_REQ (i32, u32 npc id; observed when talking to a
        # shop NPC) -> eEGS_GET_STORE_INFO_ACK 2066: empty store.
        npc_id = struct.unpack_from('<I', body, 4)[0] if len(body) >= 8 else 0
        import client_dict
        npc, items = client_dict.items_for_npc(npc_id)
        ack = StoreInfoAck(npc_id=npc_id, items=items).encode()
        await self.transport.send_event(event(2066, ack, correlation),
                                        note='store info ack (%s, %d items)' % (npc or '%08x' % npc_id, len(items)))

    async def on_2073(self, correlation, body):
        # eEGS_QUEST_START_REQ (zlib body; observed: wstring, u32 quest id =
        # jhash('Q0001S01'), ...) -> eEGS_QUEST_START_ACK 2074, case in
        # JAppPageTalkBox dispatcher 0x659F00 -> 0x659790.
        quest_id = 0
        try:
            length, offset = read_varuint(body, 0)
            quest_id = struct.unpack_from('<I', body, offset + length)[0]
        except (WireError, struct.error):
            pass
        char = self.store().get(self.account, selected_character.get('id', 1))
        active = char.setdefault('quests_active', {}) if char else {}
        uid = active.get(str(quest_id)) or max([0] + list(active.values())) + 1
        active[str(quest_id)] = uid
        if char:
            self.store().save()
        ack = QuestStartAck(quest_id=quest_id, quest_uid=uid).encode()
        await self.transport.send_event(event(2074, ack, correlation),
                                        note='quest start ack (%08x)' % quest_id)

    async def on_2010(self, correlation, body):
        # eEGS_GET_ROOMINFOLIST_REQ (sender 0x7AB140) -> 2011: no open rooms.
        await self.transport.send_event(event(2011, RoomInfoListAck().encode(), correlation),
                                        note='room info list ack')

    async def on_5001(self, correlation, body):
        # eERC_CREATE_ROOM_REQ (writer 0x58B060): wstring name, i32, i32, i16,
        # i16 (observed: "_singleplay", -1, -1, -1, 1) -> 5002 CREATE_ROOM_ACK.
        name, a, b, c, d = '', -1, -1, -1, 1
        try:
            length, offset = read_varuint(body, 0)
            name = body[offset:offset + length].decode('utf-16le')
            a, b, c, d = struct.unpack_from('<iihh', body, offset + length)
        except (WireError, struct.error, UnicodeDecodeError):
            pass
        self.room_id = getattr(self, 'room_id', 0) + 1
        ack = CreateRoomAck(room_id=self.room_id, name=name, req_a=a, req_b=b, req_c=c, req_d=d,
                            host_uid=selected_character.get('id', 0),
                            relay_port=RELAY_PORT).encode()
        await self.transport.send_event(event(5002, ack, correlation),
                                        note='create room ack (%s)' % name)

    async def on_2076(self, correlation, body):
        # eEGS_QUEST_COMPLETE_REQ (same observed prefix as 2073: wstring, u32
        # quest id) -> eEGS_QUEST_COMPLETE_ACK 2077. No rewards offline yet.
        quest_id = 0
        try:
            length, offset = read_varuint(body, 0)
            quest_id = struct.unpack_from('<I', body, offset + length)[0]
        except (WireError, struct.error):
            pass
        char = self.store().get(self.account, selected_character.get('id', 1)) or {}
        total = Character.from_dict(char).u66 if char else Character().u66
        if char:  # persist completion (sent back in 2410 at the next selection)
            char.setdefault('quests_active', {}).pop(str(quest_id), None)
            done = char.setdefault('quests_done', [])
            if quest_id not in done:
                done.append(quest_id)
            self.store().save()
        ack = QuestCompleteAck(quest_id=quest_id, total=total).encode()
        await self.transport.send_event(event(2077, ack, correlation),
                                        note='quest complete ack (%08x)' % quest_id)

    async def on_2119(self, correlation, body):
        # eEGS_ALARM_UPDATE_REQ (observed: i32 0x7FFFFFFF, i16, tag 0x10
        # vector<i32>) -> eEGS_ALARM_UPDATE_ACK 2120 (handler 0x771150):
        # u32 result, i16, tag 0x10 vector<i32> (0x4D6E60). Echo the
        # requested settings so the client keeps what it asked for.
        rest = body[4:] if len(body) >= 7 else b'\x00\x00\x10\x80'
        await self.transport.send_event(event(2120, struct.pack('<I', 0) + rest, correlation),
                                        note='alarm update ack')

    async def on_2369(self, correlation, body):
        # eEGS_BILLING_GET_CURRENT_CASH_REQ -> 2370: u32 result + 12 raw bytes (zeros).
        await self.transport.send_event(event(2370, CurrentCashAck().encode(), correlation),
                                        note='current cash ack')

    async def on_2346(self, correlation, body):
        # eEGS_TUTORIAL_QUEST_START_REQ -> eEGS_TUTORIAL_QUEST_START_ACK (2347), handler 0x6481E0:
        # u32 result (0 = success).
        ack = TutorialQuestStartAck().encode()
        await self.transport.send_event(event(2347, ack, correlation), note='tutorial quest start ack')

    async def on_2348(self, correlation, body):
        # eEGS_TAMEING_MONSTER_INSERT_REQ -> eEGS_TAMEING_MONSTER_INSERT_ACK (2349), handler 0x771A00:
        # u32 result (0 = success) + tag 0x10 vector.
        ack = TamingMonsterInsertAck().encode()
        await self.transport.send_event(event(2349, ack, correlation), note='taming monster insert ack')

    async def on_2350(self, correlation, body):
        # eEGS_TAMEING_MONSTER_DELETE_REQ -> eEGS_TAMEING_MONSTER_DELETE_ACK (2351), handler 0x771BB0:
        # u32 result (0 = success) + tag 0x10 vector.
        ack = TamingMonsterDeleteAck().encode()
        await self.transport.send_event(event(2351, ack, correlation), note='taming monster delete ack')

    async def on_2390(self, correlation, body):
        # eEGS_ROULETTE_MANAGER_INFO_REQ -> eEGS_ROULETTE_MANAGER_INFO_ACK (2391), handler 0x6CC6B0:
        # u32 result (0), untagged 21 bytes (0xA48B80).
        ack = RouletteManagerInfoAck().encode()
        await self.transport.send_event(event(2391, ack, correlation), note='roulette manager info ack')

    async def on_0(self, correlation, body):
        # Application-level keepalive heartbeat sent by client periodically.
        pass

    async def on_2084(self, correlation, body):
        # eEGS_CLEAR_OPENING_NOT: client notification that opening cinematic/sequence has ended.
        pass

    async def on_2353(self, correlation, body):
        # eEGS_TUTORIAL_MONSTER_DEAD_NOT, sender 0x799E60: notification only.
        pass

    async def on_2352(self, correlation, body):
        # eEGS_IP_ADDRESS_NOT: client LAN/WAN IP notification only.
        pass

    async def on_5030(self, correlation, body):
        # eERC_JOIN_LAYER_REQ (i32, u64 nJoinLayerNetID, u8) -> eERC_JOIN_LAYER_ACK
        # (5031), handler 0x787A70. Read order (tools/extract_schemas.py) matches
        # 5046: u32 result, u64, u64, tag 0x10 vector {i32,bool,bool}, bool, u64.
        # The former `u8 0` after the two u64 failed the 0x10 tag check, so the
        # client kept resending 5030 (observed live: layer jhash('Act1') << 32).
        layer_id = struct.unpack_from('<Q', body, 4)[0] if len(body) >= 12 else layer_net_id()
        ack = BackToSquareAck(square_uid=SQUARES[0]['square_id'], layer_net_id=layer_id).encode()
        await self.transport.send_event(event(5031, ack, correlation),
                                        note='join layer ack (%d)' % layer_id)

    async def on_2016(self, correlation, body):
        # eEGS_ENTER_MAPTOOL_REQ -> eEGS_ENTER_MAPTOOL_ACK (2017), handler 0x757D20:
        # u32 result (0 -> triggers scene transition 5 via 0x6DBFD0)
        await self.transport.send_event(event(2017, struct.pack('<I', 0), correlation),
                                        note='enter maptool ack')

    async def on_5013(self, correlation, body):
        # eERC_START_GAME_REQ -> eERC_START_GAME_ACK (5014), handler 0x7880A0/0x788199:
        # u32 result (0), u16 unk1, u32 unk2, tag 0x0B (empty string),
        # 3x tag 0x17 (empty maps), tag 0 (end of tags) -> triggers scene transition 9 (world)
        ack = struct.pack('<IHI', 0, 0, 0) + b'\x0b\x00\x17\x00\x17\x00\x17\x00\x00'
        await self.transport.send_event(event(5014, ack, correlation),
                                        note='start game ack')

    _store = None

    @classmethod
    def store(cls):
        if cls._store is None:
            from characters import CharacterStore
            cls._store = CharacterStore()
        return cls._store
