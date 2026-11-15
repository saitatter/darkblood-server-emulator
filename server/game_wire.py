"""JSerBuffer/JEvent envelope recovered from client 0xA1EB90/0xB35E50."""
import datetime
import struct


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
    # Reader 0xA496B0: wstring +0, u16 +1C, u64 +1E, bool +26, +27, +28.
    # Defaults follow constructor 0x74DF70; field meanings are not recovered.
    return wide_string(name) + struct.pack('<HQ???', u16, u64, flag_a, flag_b, flag_c)


# Experimental local server list (map key -> entry).
SERVERS = [(1, dict(name='Offline'))]


def square_entry(square_id, name, a=0, b=100, c=0):
    # Field meanings beyond id/name are not recovered yet.
    return struct.pack('<Q', square_id) + wide_string(name) + struct.pack('<III', a, b, c)


CHAR_SLOTS = 4  # first u8 of 2009: shown as "4 SLOT" on character select (observed)

SQUARES = [dict(square_id=1, name='Channel 1')]


def build_char_details(char):
    # struct 0xa52630
    b = bytearray()
    body_sliders = char.get('body', [100] * 5)[:5]
    b += varuint(len(body_sliders)) + bytes(body_sliders)  # 0xa48dd0
    b += varuint(0)  # 0xa48d50 (u32 array max 2)
    b += wide_string(char.get('name', 'Tester'))
    b += struct.pack('<QQQ', 0, 0, char.get('id', 1))
    b += struct.pack('<B', char.get('char_class', 1))
    b += struct.pack('<III', 0, 0, 0)
    b += struct.pack('<B', 0)
    b += struct.pack('<IQI', 0, 0, 0)
    b += struct.pack('<HHHH', 0, 0, 0, 0)
    # tag 0x1E + raw 24
    b += b'\x1e' + (b'\x00' * 24)
    b += struct.pack('<Q?HHHHII', 0, False, 0, 0, 0, 0, 0, 0)
    b += struct.pack('<f', 0.0)
    b += struct.pack('<QHHHHHHHH', 0, 0, 0, 0, 0, 0, 0, 0, 0)
    # 2 x 0xa49bb0 (tag 0x1E + u16, u32, u32)
    b += b'\x1e' + struct.pack('<HII', 0, 0, 0)
    b += b'\x1e' + struct.pack('<HII', 0, 0, 0)
    # bool + 0xa48b40 (tag 0x1E + raw 74)
    b += struct.pack('<?', False)
    b += b'\x1e' + (b'\x00' * 74)
    b += struct.pack('<I', 0)
    # 5 x tag 0x10 vectors
    for _ in range(5):
        b += b'\x10' + varuint(0)
    # tag 0x1E + raw 4
    b += b'\x1e' + (b'\x00' * 4)
    b += struct.pack('<H?HH', 0, False, 0, 0)
    # 2 x tag 0x17 maps
    b += b'\x17' + varuint(0)
    b += b'\x17' + varuint(0)
    b += struct.pack('<HQQQQI', 0, 0, 0, 0, 0, 0)
    # tag 0x10 vector
    b += b'\x10' + varuint(0)
    b += struct.pack('<?HH', False, 0, 0)
    b += struct.pack('<f', 0.0)
    b += struct.pack('<?H??', False, 0, False, False)
    b += wide_string('')
    return bytes(b)


def build_select_char_ack(char):
    # Handler 0x7AA4B0: u32 result (0), tag 0x1E + struct 0xA40760, tag 0x10 vector
    p = bytearray(struct.pack('<I', 0))
    p += b'\x1e'
    p += struct.pack('<I', 0)  # u32 field 0
    p += varuint(0)  # 0xa3ed30 max 3
    p += varuint(0)  # 0xa1e840 max 10
    # 0x4c7990: tag 0x1E + 0xa52630
    p += b'\x1e' + build_char_details(char)
    # fields after 0x4c7990 in 0xa40760:
    p += struct.pack('<QQQQBB', 0, 0, 0, 0, 0, 0)
    p += b'\x17' + varuint(0)  # 0xa40720
    p += b'\x10' + varuint(0)  # 0x558010
    p += b'\x10' + varuint(0)  # 0x4b9830
    p += b'\x10' + varuint(0)  # 0x4b2c30
    p += b'\x10' + varuint(0)  # 0xa3eec0
    p += b'\x17' + varuint(0)  # 0x4b1240
    p += b'\x17' + varuint(0)  # 0x76e560
    p += b'\x13' + varuint(0)  # 0x76a8c0
    p += b'\x17' + varuint(0)  # 0xa3e410
    p += struct.pack('<QII', 0, 0, 0)
    p += b'\x17' + varuint(0)  # 0xa3e450
    p += b'\x13' + varuint(0)  # 0x5ee0f0
    p += b'\x1e' + (b'\x00' * 18)  # 0x641e00 (tag 0x1E + raw 18)
    p += b'\x13' + varuint(0)  # 0x5ee0f0
    p += struct.pack('<QQQIQ', 0, 0, 0, 0, 0)
    p += struct.pack('<Q', 0)
    p += b'\x10' + varuint(0)  # 0x4b1a60
    p += struct.pack('<Q??', 0, False, False)
    p += struct.pack('<f', 0.0)
    p += struct.pack('<Q', 0)
    p += struct.pack('<Q', 0)
    p += b'\x17' + varuint(0)  # 0x485220
    p += b'\x17' + varuint(0)  # 0x485220
    p += wide_string('')  # 0xb35ab0
    # 0x74c1d0: tag 0x1E + 2 maps + bool
    p += b'\x1e' + b'\x17' + varuint(0) + b'\x17' + varuint(0) + struct.pack('<?', False)
    p += b'\x17' + varuint(0)  # 0xa3ea00
    p += struct.pack('<QQI', 0, 0, 0)
    p += b'\x10' + varuint(0)  # 0x4da660
    p += b'\x10' + varuint(0)  # 0x4da660
    p += struct.pack('<HQQ', 0, 0, 0)
    p += b'\x17' + varuint(0)  # 0x5f9190
    p += b'\x17' + varuint(0)  # 0x76aba0
    # 0xa1e8c0: tag 0x1E + map + u64 + bool + u64
    p += b'\x1e' + b'\x17' + varuint(0) + struct.pack('<Q?Q', 0, False, 0)
    p += b'\x10' + varuint(0)  # 0xa3edd0
    # 0xa1eea0: tag 0x1E + u32 + u64 + u64 + u64
    p += b'\x1e' + struct.pack('<IQQQ', 0, 0, 0, 0)
    # 0xa1e900: tag 0x1E + map + vector
    p += b'\x1e' + b'\x17' + varuint(0) + b'\x10' + varuint(0)
    p += struct.pack('<H', 0)
    p += b'\x10' + varuint(0)  # 0x4da660
    p += b'\x17' + varuint(0)  # 0x5f9150
    p += struct.pack('<H', 0)
    p += b'\x17' + varuint(0)  # 0x485220
    # in 0x007AA4B0: tag 0x10 + vector 0x004B9210
    p += b'\x10' + varuint(0)
    return bytes(p)


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
        await self.transport.send_event(welcome(), note='welcome 5020')

    async def on_user_message(self, data):
        try:
            opcode, correlation, compressed, body = parse_event(data)
        except WireError as exc:
            self.transport.record('bad-event', data, error=str(exc))
            return
        self.transport.record('event', body, opcode=opcode, opcode_hex='0x%04x' % opcode,
                              correlation=correlation, compressed=compressed)
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
        await self.transport.send_event(event(5029, struct.pack('<IQ', 0, square_id), correlation),
                                        note='join square ack')

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
        char = self.store().get(self.account, char_id)
        if not char:
            chars = self.store().characters(self.account)
            char = chars[0] if chars else dict(id=char_id, name=self.account, char_class=1)
        ack = build_select_char_ack(char)
        await self.transport.send_event(event(2007, ack, correlation),
                                        note='select char ack (%d)' % char_id)

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

    _store = None

    @classmethod
    def store(cls):
        if cls._store is None:
            from characters import CharacterStore
            cls._store = CharacterStore()
        return cls._store
