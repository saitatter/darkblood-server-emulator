"""Square/room relay endpoint and relay PIDL (JoinGroup/JoinGroupACK)."""
import asyncio
import os
import struct
from dataclasses import dataclass, field
from itertools import count

from darkblood.core.network.proudnet import FAST_KEY_BITS, ProtocolError, frame, read_scalar, scalar
from darkblood.core.serialization.jser import varuint


# Square relay endpoint (opcode 5134). Reader 0xA48910 copies 6 raw bytes
# into the buffer at [handler owner + 0x6C]; JP2PFactory::Connect (0x956A90)
# uses them as IPv4 address bytes in network order + u16 little-endian port
# (observed: shim logged connect() -> 127.0.0.1:9401 before redirection).
RELAY_PORT = 9401


def relay_address(port=RELAY_PORT):
    return bytes([127, 0, 0, 1]) + struct.pack('<H', port)


# Relay PIDL (game-defined, not ProudNet internal). Proxy C2S vtable 0xD1CD80:
#   1001 JoinGroup  (0x956420/0x956500), 1002 LeaveGroup (0x9565E0/0x9566C0)
#   args: u32 group type, {i64, i64} (0x977610), i64 character UID (0xB6D3B0)
# Stub S2C (0x9567A0, JS2CStub 0x96C220):
#   3001 JoinGroupACK: u32 group HostID (-> factory+0x6C, 0x963CE0),
#   ByteArray (scalar length + bytes) holding a JSerBuffer:
#   tag 0x10, varuint count, entries {u64 char UID, u32 HostID}
#   (0x90DD90 / 0x90CC90 / 0x6AD6C0). 0x96BC60 then expects a P2P link to
#   every member except the local character.
RELAY_RMI = {1001: 'JoinGroup', 1002: 'LeaveGroup'}


RELAY_GROUP_HOST_ID = 0x10000  # local choice; any HostID distinct from peers


def join_group_ack(group_host_id, members):
    """RMI 3001 JoinGroupACK: i32 group HostID + ByteArray roster.

    The roster is read by 0x00963CE0 -> 0x0090DD90: tag 0x10, varuint count,
    then per member u64 char UID (0x00B35430) and i32 HostID (0x00B35300).
    The pair check 0x006AFA10 (type 0x0F) consumes no wire byte, so pairs are
    untagged: a 0x0F byte here shifted every key (live: key 0x30F for UID 3).
    The client stores the pairs in the JP2PClient map that JP2PClient::SendTo
    (0x0095C1E0) searches, so a wrong roster silently drops all town P2P.
    """
    body = b'\x10' + varuint(len(members))
    for char_uid, host_id in members:
        body += struct.pack('<QI', char_uid, host_id)
    return (b'\x01' + struct.pack('<HI', 3001, group_host_id)
            + scalar(len(body)) + body)


# ProudS2C (stub CNetClientImpl::S2CStub, vtable 0x00D6E5CC, dispatch
# 0x00B445E0) RMI ids start at 0xF619. 0xF619 reads, in order (readers
# 0x00B70D90 i32, 0x009493F0 ByteArray, 0x00B3F960 u32, 0x00B3F600 16 raw
# bytes, 0x00B3F930 u8): i32 group HostID, i32 member HostID, ByteArray,
# u32, ByteArray, ByteArray, u32, 16 bytes, bool, u32 -- the shape of
# ProudNet's P2PGroup_MemberJoin (custom field, event id, P2P AES and fast
# session keys, ...). Fields without a recovered meaning are sent as 0.
P2P_GROUP_MEMBER_JOIN = 0xF619

P2P_GROUP_MEMBER_LEAVE = 0xF61E


def p2p_member_join(group_host_id, member_host_id, aes_key, fast_key, event_id=0):
    from darkblood.core.network.proudnet import blob
    return (b'\x01' + struct.pack('<Hii', P2P_GROUP_MEMBER_JOIN, group_host_id, member_host_id)
            + blob(b'') + struct.pack('<I', event_id) + blob(aes_key) + blob(fast_key)
            + struct.pack('<I', 0) + b'\x00' * 16 + struct.pack('<?I', False, 0))


# Peer-to-peer traffic relayed by the server (no direct P2P/UDP here).
# C->S 0x15 (ReliableRelay1, live): scalar destination count, per
# destination {i32 HostID, u32 frame number}, scalar length, frame bytes of
# the sender's reliable stream to that peer.
# S->C 0x19 (ReliableRelay2, handler 0x00B5DA70): i32 sender HostID, u32
# frame number (0x00B70740, 4 bytes), scalar length (0x00B70A50) + bytes;
# the client feeds them into that peer's stream (0x00B83EA0) and dispatches
# the messages inside (0x00B5F900).
RELIABLE_RELAY1, RELIABLE_RELAY2 = 0x15, 0x19


@dataclass
class RelayGroup:
    host_id: int
    members: dict = field(default_factory=dict)


class RelayGroups:
    """Group membership and reliable forwarding for one relay listener."""

    def __init__(self):
        self.groups = {}
        self.memberships = {}
        self.host_ids = count(RELAY_GROUP_HOST_ID)
        self.lock = asyncio.Lock()

    @staticmethod
    def group_key(kind, scope_uid, layer_uid, char_id):
        if kind == 0 and scope_uid == -1:
            # The first town JoinGroup can precede the client learning the
            # square UID. Use the game-world registration when it is available.
            from darkblood.games.world import GameWorldManager
            player = GameWorldManager.get().get_player(char_id)
            scope_uid = player.square_id if player else 1
        return kind, scope_uid, layer_uid

    @staticmethod
    async def send(member, payload, note):
        if not member.writer.is_closing():
            try:
                await member.send_payload(payload, note=note)
            except (ConnectionError, OSError):
                pass

    async def handle_rmi(self, transport, rmi_id, args):
        transport.record('relay-rmi', args, rmi=RELAY_RMI[rmi_id])
        if len(args) != struct.calcsize('<Iqqq'):
            raise ProtocolError('Invalid relay group arguments')
        kind, scope_uid, layer_uid, char_id = struct.unpack('<Iqqq', args)
        if char_id <= 0:
            raise ProtocolError('Invalid relay character UID')
        key = self.group_key(kind, scope_uid, layer_uid, char_id)
        async with self.lock:
            if rmi_id == 1001:
                if getattr(transport, 'char_id', None) != char_id:
                    await self.remove(transport, notify_departing=True)
                    transport.char_id = char_id
                await self.join(transport, key)
            elif (getattr(transport, 'char_id', None) == char_id
                  and self.memberships.get(transport) == key):
                await self.remove(transport, notify_departing=True)

    async def join(self, transport, key):
        newcomer = self.memberships.get(transport) != key
        if newcomer:
            await self.remove(transport, notify_departing=True)
            if key not in self.groups:
                self.groups[key] = RelayGroup(next(self.host_ids))
            self.memberships[transport] = key
        group = self.groups[key]
        if newcomer:
            for other in group.members.values():
                aes_key, fast_key = os.urandom(16), os.urandom(FAST_KEY_BITS // 8)
                await self.send(transport, p2p_member_join(group.host_id, other.host_id, aes_key, fast_key),
                                'relay peer joined')
                await self.send(other, p2p_member_join(group.host_id, transport.host_id, aes_key, fast_key),
                                'relay peer joined')
            group.members[transport.host_id] = transport
        roster = [(member.char_id, member.host_id) for member in group.members.values()]
        for member in group.members.values():
            if member is transport or newcomer:
                await self.send(member, join_group_ack(group.host_id, roster),
                                'relay JoinGroupACK 3001 (%d members)' % len(roster))

    async def remove(self, transport, notify_departing=False):
        key = self.memberships.pop(transport, None)
        if key is None:
            return
        group = self.groups[key]
        del group.members[transport.host_id]
        if not group.members:
            del self.groups[key]
        # ProudS2C 0xF61E reads member HostID then group HostID.
        payload = b'\x01' + struct.pack('<HII', P2P_GROUP_MEMBER_LEAVE, transport.host_id, group.host_id)
        for other in group.members.values():
            await self.send(other, payload, 'relay peer left')
        if notify_departing:
            await self.send(transport, payload, 'relay group left')

    async def disconnect(self, transport):
        async with self.lock:
            await self.remove(transport)

    async def forward(self, transport, payload):
        result = read_scalar(payload, 1)
        if result is None:
            raise ProtocolError('Truncated relay destination count')
        n, offset = result
        if not 0 <= n <= (len(payload) - offset) // 8:
            raise ProtocolError('Invalid relay destination count')
        end = offset + 8 * n
        result = read_scalar(payload, end)
        if result is None:
            raise ProtocolError('Truncated relay payload length')
        length, start = result
        if length < 0 or start + length != len(payload):
            raise ProtocolError('Invalid relay payload length')

        async with self.lock:
            group = self.groups.get(self.memberships.get(transport))
            if group is None:
                return
            for host_id, frame_no in struct.iter_unpack('<iI', payload[offset:end]):
                target = group.members.get(host_id)
                if target is None or target.writer.is_closing():
                    transport.record('relay-drop', payload, dest=host_id)
                    continue
                out = (bytes([RELIABLE_RELAY2]) + struct.pack('<iI', transport.host_id, frame_no)
                       + scalar(length) + payload[start:])
                target.writer.write(frame(out))
