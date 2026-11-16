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


async def relay_rmi(transport, rmi_id, args):
    transport.record('relay-rmi', args, rmi=RELAY_RMI[rmi_id])
    if rmi_id == 1001:
        members = [(selected_character['id'], transport.host_id)]
        await transport.send_payload(join_group_ack(RELAY_GROUP_HOST_ID, members),
                                     note='relay JoinGroupACK 3001')
