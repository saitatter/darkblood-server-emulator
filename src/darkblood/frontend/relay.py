"""Square/room relay endpoint and relay PIDL (JoinGroup/JoinGroupACK)."""
import struct

from darkblood.core.serialization.jser import varuint
from darkblood.games.state import selected_character


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


def join_group_ack(group_host_id, members):
    from darkblood.core.network.proudnet import scalar
    body = b'' + varuint(len(members))
    for char_uid, host_id in members:
        body += b'' + struct.pack('<QI', char_uid, host_id)
    return (b'' + struct.pack('<HI', 3001, group_host_id)
            + scalar(len(body)) + body)


# ProudS2C (stub CNetClientImpl::S2CStub, vtable 0x00D6E5CC, dispatch
# 0x00B445E0) RMI ids start at 0xF619. 0xF619 reads, in order (readers
# 0x00B70D90 i32, 0x009493F0 ByteArray, 0x00B3F960 u32, 0x00B3F600 16 raw
# bytes, 0x00B3F930 u8): i32 group HostID, i32 member HostID, ByteArray,
# u32, ByteArray, ByteArray, u32, 16 bytes, bool, u32 -- the shape of
# ProudNet's P2PGroup_MemberJoin (custom field, event id, P2P AES and fast
# session keys, ...). Fields without a recovered meaning are sent as 0.
P2P_GROUP_MEMBER_JOIN = 0xF619

# Relay connections that joined the square group: HostID -> (transport, char UID).
# One group for now (single local square/channel).
GROUP_MEMBERS = {}


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


async def forward_reliable_relay(transport, payload):
    from darkblood.core.network.proudnet import read_scalar, scalar
    count, offset = read_scalar(payload, 1)
    dests = []
    for _ in range(count):
        host_id, frame_no = struct.unpack_from('<iI', payload, offset)
        offset += 8
        dests.append((host_id, frame_no))
    length, offset = read_scalar(payload, offset)
    data = payload[offset:offset + length]
    members = _live_members()
    for host_id, frame_no in dests:
        target = members.get(host_id)
        if target is None:
            transport.record('relay-drop', payload, dest=host_id)
            continue
        out = bytes([RELIABLE_RELAY2]) + struct.pack('<iI', transport.host_id, frame_no) + scalar(len(data)) + data
        target[0].writer.write(_frame(out))
    await transport.writer.drain()


def _frame(payload):
    from darkblood.core.network.proudnet import frame
    return frame(payload)


def _live_members():
    for host_id, (transport, _) in list(GROUP_MEMBERS.items()):
        if transport.writer.is_closing():
            del GROUP_MEMBERS[host_id]
    return GROUP_MEMBERS


async def relay_rmi(transport, rmi_id, args):
    import os
    transport.record('relay-rmi', args, rmi=RELAY_RMI[rmi_id])
    if rmi_id == 1001:
        if getattr(transport, 'char_id', None) is None:
            from darkblood.games.state import pending_relay
            transport.char_id = pending_relay.popleft() if pending_relay else selected_character['id']
        members = _live_members()
        newcomer = transport.host_id not in members
        members[transport.host_id] = (transport, transport.char_id)
        if newcomer:
            # Introduce the newcomer and every existing member to each other
            # (one shared key pair per pair of peers).
            for host_id, (other, char_id) in members.items():
                if host_id == transport.host_id:
                    continue
                aes_key, fast_key = os.urandom(16), os.urandom(16)
                await transport.send_payload(p2p_member_join(RELAY_GROUP_HOST_ID, host_id, aes_key, fast_key),
                                             note='P2P member join %d -> %d' % (host_id, transport.host_id))
                await other.send_payload(p2p_member_join(RELAY_GROUP_HOST_ID, transport.host_id, aes_key, fast_key),
                                         note='P2P member join %d -> %d' % (transport.host_id, host_id))
        roster = [(char_id, host_id) for host_id, (_, char_id) in members.items()]
        for host_id, (member, _) in members.items():
            if member is transport or newcomer:
                await member.send_payload(join_group_ack(RELAY_GROUP_HOST_ID, roster),
                                          note='relay JoinGroupACK 3001 (%d members)' % len(roster))
    elif rmi_id == 1002:
        GROUP_MEMBERS.pop(transport.host_id, None)
