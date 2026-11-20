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

                prefix = struct.pack('<I', 0x7fffffff)
                room_name = wide('Shared test')
                room_options = struct.pack('<iihh', -1, -1, -1, 4)
                host.send_event(5001, prefix + room_name + room_options)
                _, created = await host.expect_event(5002)
                room_id = struct.unpack_from('<q', created, 4)[0]
                self.assertEqual(created[12:12 + len(room_name)], room_name)
                self.assertEqual(struct.unpack_from('<hh', created, 12 + len(room_name)), (4, 1))  # max, current users
                room_info = created[4:-10]
                relay = bytes.fromhex('7f000001b924')
                self.assertEqual(created[-6:], relay)

                # A truncated create request must leave the current room open.
                host.send_event(5001, prefix + room_name + room_options[:-1])
                _, error = await host.expect_event(5002)
                self.assertEqual(error, struct.pack('<I', results.INVALID_STATE))

                # Live create body: 0x7FFFFFFF prefix, title, gate, dungeon, diff, max users.
                gate = 0x3c00d7a1
                host.send_event(5001, struct.pack('<i', 0x7fffffff) + wide('Gate room')
                                + struct.pack('<iihh', gate, 0x1234, -1, 4))
                _, gate_room = await host.expect_event(5002)
                gate_info = gate_room[4:-10]
                self.assertEqual(struct.unpack_from('<q', gate_info)[0] > room_id, True)
                self.assertIn(wide('Gate room'), gate_info)

                gate_live = gate_info  # one member, waiting (state 8): same as the create ack
                # 2010: nPage, bWait, nGateID, nMapID, sDiff -> the gate's open rooms.
                guest.send_event(2010, struct.pack('<ii?iih', 0x7fffffff, 0, True, gate, -1, -1))
                _, listing = await guest.expect_event(2011)
                self.assertEqual(listing, struct.pack('<I?i', 0, True, 0) + bytes.fromhex('1081') + gate_live
                                 + struct.pack('<i', 0))
                # 5060 (row click) -> 5061: result, room uid, two empty vectors.
                gate_room_id = struct.unpack_from('<q', gate_info)[0]
                guest.send_event(5060, struct.pack('<iq', 0x7fffffff, gate_room_id))
                _, info = await guest.expect_event(5061)
                # One member (the host): square UID, char UID, i32, name, class, i16, level, ...
                self.assertEqual(info[:14], struct.pack('<Iq', 0, gate_room_id) + bytes.fromhex('1081'))
                member = info[14:-2]
                self.assertEqual(struct.unpack_from('<qq', member), ((0x1F << 54) | 1, host_id))
                name = wide('RoomHost')
                self.assertEqual(member[20:20 + len(name)], name)
                self.assertEqual(len(member), 20 + len(name) + 1 + 2 + 1 + 16 + 74 + 1)
                self.assertEqual(info[-2:], bytes.fromhex('1080'))
                # 5047 (Join in View party info) -> 5048 to the host with the requester.
                guest.send_event(5047, struct.pack('<iq', 0x7fffffff, gate_room_id))
                _, request = await host.expect_event(5048)
                self.assertEqual(request[:12], struct.pack('<Iq', 0, gate_room_id))
                self.assertEqual(struct.unpack_from('<q', request, 20)[0], guest_id)
                self.assertIn(wide('RoomGuest'), request)
                guest.send_event(5060, struct.pack('<iq', 0x7fffffff, gate_room_id + 99))
                _, info = await guest.expect_event(5061)
                self.assertEqual(info, struct.pack('<I', results.ROOM_NOT_EXISTS))
                guest.send_event(2010, struct.pack('<ii?iih', 0x7fffffff, 0, False, gate + 1, -1, -1))
                _, listing = await guest.expect_event(2011)
                self.assertEqual(listing, struct.pack('<I?i', 0, False, 0) + bytes.fromhex('1080') + struct.pack('<i', 0))

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
                # jRoomInfo: id, name, max users, current users (now 2), ...
                at = 8 + len(wide('Shared test')) + 2
                joined_info = room_info[:at] + struct.pack('<h', 2) + room_info[at + 2:]
                self.assertEqual(joined, (b'\0' * 4 + joined_info + struct.pack('<q', host_id) + b'\x10\x82'
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

                # Party name edit (5011 -> 5012) and looting mode button (5088 -> 5089).
                host.send_event(5011, struct.pack('<q', room_id) + wide('Renamed'), correlation=51)
                correlation, renamed = await host.expect_event(5012)
                self.assertEqual(correlation, 51)
                self.assertEqual(struct.unpack_from('<I', renamed)[0], 0)
                self.assertIn(wide('Renamed'), renamed)
                guest.send_event(5011, struct.pack('<q', room_id) + wide('Nope'), correlation=52)
                _, refused = await guest.expect_event(5012)
                self.assertEqual(refused, struct.pack('<I', results.INVALID_STATE))
                host.send_event(5088, struct.pack('<i', 0x7fffffff) + b'', correlation=53)
                correlation, looting = await host.expect_event(5089)
                self.assertEqual((correlation, looting), (53, b''))
                _, synced = await guest.expect_event(5089)
                self.assertEqual(synced, b'')

                host.send_event(5005)
                await host.expect_event(5006)
                _, departure = await guest.expect_event(5036)
                self.assertEqual(departure, struct.pack('<Iq', 0, host_id))
                guest.send_event(5003, struct.pack('<q', room_id))
                _, error = await guest.expect_event(5004)
                self.assertEqual(error, struct.pack('<I', results.ROOM_NOT_EXISTS))

                bare_room_name = wide('Another room')
                host.send_event(5001, bare_room_name + room_options)
                _, created = await host.expect_event(5002)
                new_room_id = struct.unpack_from('<q', created, 4)[0]
                self.assertEqual(created[12:12 + len(bare_room_name)], bare_room_name)
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
