import struct

from darkblood.core.serialization.jser import event
from darkblood.games.network.messages import CurrentCashAck, RouletteManagerInfoAck, StoreInfoAck, TamingMonsterDeleteAck, TamingMonsterInsertAck


class CommerceHandlers:
    """Stores, cash, roulette, pets and alarm settings."""

    async def on_2065(self, correlation, body):
        # eEGS_GET_STORE_INFO_REQ (i32, u32 npc id; observed when talking to a
        # shop NPC) -> eEGS_GET_STORE_INFO_ACK 2066: empty store.
        npc_id = struct.unpack_from('<I', body, 4)[0] if len(body) >= 8 else 0
        from darkblood.games.game_data import client_dict
        npc, items = client_dict.items_for_npc(npc_id)
        ack = StoreInfoAck(npc_id=npc_id, items=items).encode()
        await self.transport.send_event(event(2066, ack, correlation),
                                        note='store info ack (%s, %d items)' % (npc or '%08x' % npc_id, len(items)))

    async def on_2369(self, correlation, body):
        # eEGS_BILLING_GET_CURRENT_CASH_REQ -> 2370: u32 result + 12 raw bytes (zeros).
        await self.transport.send_event(event(2370, CurrentCashAck().encode(), correlation),
                                        note='current cash ack')

    async def on_2390(self, correlation, body):
        # eEGS_ROULETTE_MANAGER_INFO_REQ -> eEGS_ROULETTE_MANAGER_INFO_ACK (2391), handler 0x6CC6B0:
        # u32 result (0), untagged 21 bytes (0xA48B80).
        ack = RouletteManagerInfoAck().encode()
        await self.transport.send_event(event(2391, ack, correlation), note='roulette manager info ack')

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

    async def on_2119(self, correlation, body):
        # eEGS_ALARM_UPDATE_REQ (observed: i32 0x7FFFFFFF, i16, tag 0x10
        # vector<i32>) -> eEGS_ALARM_UPDATE_ACK 2120 (handler 0x771150):
        # u32 result, i16, tag 0x10 vector<i32> (0x4D6E60). Echo the
        # requested settings so the client keeps what it asked for.
        rest = body[4:] if len(body) >= 7 else b'\x00\x00\x10\x80'
        await self.transport.send_event(event(2120, struct.pack('<I', 0) + rest, correlation),
                                        note='alarm update ack')
