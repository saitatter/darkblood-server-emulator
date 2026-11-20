"""Two headless clients join the same dungeon room and see member changes."""

import struct

from tests.common import ServerTestCase, create_request, lobby_flow, wide
from darkblood.games.entities.character import Character
from darkblood.games.network import results
from darkblood.games.session import GameSession
from headless_client import HeadlessClient


class SharedDungeonRoomTest(ServerTestCase):
    def test_join_roster_and_member_departure(self):
        async def enter(client, name):
            await lobby_flow(client)
            client.send_event(2012, create_request(name))
            _, created = await client.expect_event(2013)
            uid = struct.unpack_from('<q', created, 10)[0]
            client.send_event(2006, struct.pack('<iq', 0x7fffffff, uid))
            await client.expect_event(2007)
            return uid

        def member_bytes(uid):
            char = GameSession.store().get('OfflinePlayer', uid)
            base = Character.from_dict(char).encode_world_details()
            return (base + b'\xff' * 16 + b'\x00' * 12 + b'\xff' * 16 + b'\x00' * 4
                    + bytes.fromhex('da0701000100000000000000') * 2 + b'\x00' * 4)

        async def scenario(host):
            guest = HeadlessClient(port=host.port)
            try:
                host_id = await enter(host, 'RoomHost')
                guest_id = await enter(guest, 'RoomGuest')

                host.send_event(5001, wide('Shared test') + struct.pack('<iihh', -1, -1, -1, 4))
                _, created = await host.expect_event(5002)
                room_id = struct.unpack_from('<q', created, 4)[0]
                room_info = created[4:-10]
                relay = bytes.fromhex('7f000001b924')
                self.assertEqual(created[-6:], relay)

                # Live create body: 0x7FFFFFFF prefix, title, gate, dungeon, diff, max users.
                gate = 0x3c00d7a1
                host.send_event(5001, struct.pack('<i', 0x7fffffff) + wide('Gate room')
                                + struct.pack('<iihh', gate, 0x1234, -1, 4))
                _, gate_room = await host.expect_event(5002)
                gate_info = gate_room[4:-10]
                self.assertEqual(struct.unpack_from('<q', gate_info)[0] > room_id, True)
                self.assertIn(wide('Gate room'), gate_info)

                # 2010: nPage, bWait, nGateID, nMapID, sDiff -> the gate's open rooms.
                guest.send_event(2010, struct.pack('<ii?iih', 0x7fffffff, 0, True, gate, -1, -1))
                _, listing = await guest.expect_event(2011)
                self.assertEqual(listing, struct.pack('<I?i', 0, True, 0) + bytes.fromhex('1081') + gate_info
                                 + struct.pack('<i', 1))
                guest.send_event(2010, struct.pack('<ii?iih', 0x7fffffff, 0, False, gate + 1, -1, -1))
                _, listing = await guest.expect_event(2011)
                self.assertEqual(listing, struct.pack('<I?i', 0, False, 0) + bytes.fromhex('1080') + struct.pack('<i', 1))

                # The host moves back to the first room for the rest of the flow.
                host.send_event(5001, wide('Shared test') + struct.pack('<iihh', -1, -1, -1, 4))
                _, created = await host.expect_event(5002)
                room_id = struct.unpack_from('<q', created, 4)[0]
                room_info = created[4:-10]

                guest.send_event(5003, struct.pack('<q', room_id + 100))
                _, error = await guest.expect_event(5004)
                self.assertEqual(error, struct.pack('<I', results.ROOM_NOT_EXISTS))

                guest.send_event(5003, struct.pack('<iq', 0x7fffffff, room_id), correlation=35)
                correlation, joined = await guest.expect_event(5004)
                self.assertEqual(correlation, 35)
                self.assertEqual(joined, (b'\0' * 4 + room_info + struct.pack('<q', host_id) + b'\x10\x82'
                                          + member_bytes(host_id) + member_bytes(guest_id) + relay + b'\0\0'))
                _, notice = await host.expect_event(5035)
                self.assertEqual(notice, member_bytes(guest_id) + b'\0')

                guest.send_event(5005)
                await guest.expect_event(5006)
                _, departure = await host.expect_event(5036)
                self.assertEqual(departure, struct.pack('<Iq', 0, guest_id))

                guest.send_event(5003, struct.pack('<q', room_id))
                _, rejoined = await guest.expect_event(5004)
                self.assertEqual(rejoined, joined)
                await host.expect_event(5035)

                host.send_event(5005)
                await host.expect_event(5006)
                _, departure = await guest.expect_event(5036)
                self.assertEqual(departure, struct.pack('<Iq', 0, host_id))
                guest.send_event(5003, struct.pack('<q', room_id))
                _, error = await guest.expect_event(5004)
                self.assertEqual(error, struct.pack('<I', results.ROOM_NOT_EXISTS))

                host.send_event(5001, wide('Another room') + struct.pack('<iihh', -1, -1, -1, 4))
                _, created = await host.expect_event(5002)
                new_room_id = struct.unpack_from('<q', created, 4)[0]
                self.assertNotEqual(new_room_id, room_id)
                guest.send_event(5003, struct.pack('<q', new_room_id))
                _, joined_again = await guest.expect_event(5004)
                self.assertEqual(struct.unpack_from('<Iq', joined_again), (0, new_room_id))
                await host.expect_event(5035)
                await guest.close()
                _, departure = await host.expect_event(5036)
                self.assertEqual(departure, struct.pack('<Iq', 0, guest_id))
            finally:
                await guest.close()

        self.run_async(self.with_server(scenario))
