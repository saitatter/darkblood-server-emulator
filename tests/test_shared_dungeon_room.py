"""Two headless clients join the same dungeon room and see member changes."""

import struct

from tests.common import CHAT_TAIL, ServerTestCase, chat_request, create_request, lobby_flow, wide
from darkblood.core.hashing import jhash
from darkblood.games.entities.character import Character
from darkblood.games.network import results
from darkblood.games.network.messages import ChangeRoomInfoAck, ChatReq, GetInviteListAck
from darkblood.games.network.messages.dungeon import RoomInfo
from darkblood.games.network.messages.party import PartyInviteNot
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

                # Town chat (channel 1) reaches the other player in the square; a
                # whisper (channel 2) reaches only the named player.
                host.send_event(5040, chat_request('hello town', channel=1), correlation=40)
                correlation, echo = await host.expect_event(5041)
                self.assertEqual(correlation, 40)
                _, heard = await guest.expect_event(5041)
                self.assertEqual(heard, echo)
                self.assertIn(wide('RoomHost'), heard)
                self.assertIn(wide('hello town'), heard)
                whisper = ChatReq(channel=2, target='RoomHost', message='psst').encode()
                guest.send_event(5040, whisper)
                _, whisper_ack = await guest.expect_event(5041)
                _, whispered = await host.expect_event(5041)
                self.assertIn(wide('psst'), whispered)
                self.assertEqual(whisper_ack, whispered)
                from darkblood.games.network.messages import ChatAck
                decoded_whisper = ChatAck.decode(whispered)
                self.assertEqual(decoded_whisper.sender, 'RoomGuest')
                self.assertEqual(decoded_whisper.target, 'RoomHost')
                self.assertEqual(decoded_whisper.server_key, 31)

                # Find user (2024, live body: low/high level, page, job 7, layer -1,
                # square UID) lists the other player; a level range above it does not.
                guest.send_event(2024, struct.pack('<iiiBqq', 1, 99, 0, 7, -1, 1))
                _, found = await guest.expect_event(2025)
                users = GetInviteListAck.decode(found).users
                self.assertEqual([(u.char_uid, u.name) for u in users], [(host_id, 'RoomHost')])
                guest.send_event(2024, struct.pack('<iiiBqq', 50, 60, 0, 7, -1, 1))
                _, none = await guest.expect_event(2025)
                self.assertEqual(GetInviteListAck.decode(none).users, [])

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
                # +0x31 is the stress shown in the row's gauge (0x00756F40).
                host_stress = GameSession.store().get('OfflinePlayer', host_id).get('stress', 0)
                self.assertEqual(struct.unpack_from('<h', member, 20 + len(name) + 1)[0], host_stress)
                self.assertEqual(info[-2:], bytes.fromhex('1080'))
                # 5047 (Join in View party info) -> 5048 to the host with the requester.
                guest.send_event(5047, struct.pack('<iq', 0x7fffffff, gate_room_id), correlation=36)
                _, request = await host.expect_event(5048)
                self.assertEqual(request[:12], struct.pack('<Iq', 0, gate_room_id))
                self.assertEqual(struct.unpack_from('<q', request, 20)[0], guest_id)
                self.assertIn(wide('RoomGuest'), request)
                # The host's Accept sends 5049 for the requester (AcceptJoinRoomREQ):
                # the requester joins at once, answered on its 5047 correlation.
                host.send_event(5049, struct.pack('<iq?q', 0x7fffffff, 1, False, guest_id))
                correlation, joined = await guest.expect_event(5004)
                self.assertEqual((correlation, struct.unpack_from('<Iq', joined)), (36, (0, gate_room_id)))
                await host.expect_event(5035)
                guest.send_event(5005)
                await guest.expect_event(5006)
                await host.expect_event(5036)
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
                                          + member_bytes(host_id) + member_bytes(guest_id) + relay + b'\x01\0'))  # free for all
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

                # Party info OK (5011 -> 5012 to everyone) and looting checkbox (5088 -> 5089).
                def room_info(name, max_users, gate, map_id, diff):
                    # Live layout: cur_users, state and the i64s are uninitialised garbage.
                    return (struct.pack('<q', room_id) + wide(name)
                            + struct.pack('<hhiqqiih', max_users, -13499, 0xB3861A, 0x4696031A00F4E254, -1,
                                          gate, map_id, diff))
                host.send_event(5011, room_info('Renamed', 3, 7, 0x1234, 2), correlation=51)
                correlation, renamed = await host.expect_event(5012)
                self.assertEqual(correlation, 51)
                ack = ChangeRoomInfoAck.decode(renamed)
                self.assertEqual((ack.result, ack.room.name, ack.room.max_users, ack.room.cur_users),
                                 (0, 'Renamed', 3, 2))
                self.assertEqual((ack.room.gate_id, ack.room.map_id, ack.room.diff), (7, 0x1234, 2))
                _, member_view = await guest.expect_event(5012)
                self.assertEqual(member_view, renamed)
                guest.send_event(5011, room_info('Nope', 4, 7, 0x1234, 2), correlation=52)
                _, refused = await guest.expect_event(5012)
                self.assertEqual(refused, struct.pack('<I', results.INVALID_STATE))
                host.send_event(5088, struct.pack('<i?', 0x7fffffff, True), correlation=53)
                correlation, looting = await host.expect_event(5089)
                self.assertEqual((correlation, looting), (53, struct.pack('<i?', 0, True)))  # result, echoed mode
                _, synced = await guest.expect_event(5089)
                self.assertEqual(synced, looting)

                # The host opens the dungeon gate: the member enters it too (5044), so
                # both clients reach the P2P loading barrier, and sees the map choice.
                host.send_event(5043, struct.pack('<i', 0x7fffffff) + wide('Act1_G2'), correlation=54)
                correlation, gate_ack = await host.expect_event(5044)
                self.assertEqual(correlation, 54)
                _, member_gate = await guest.expect_event(5044)
                self.assertEqual(member_gate, gate_ack)  # same gate; neither has history yet

                from darkblood.games.network.messages import AgainSelectDungeonAck, AgainSelectDungeonReq

                guest.send_event(5052, AgainSelectDungeonReq().encode())
                _, reopened = await guest.expect_event(5053)
                self.assertEqual(AgainSelectDungeonAck.decode(reopened).gate_id, 'Act1_G2')

                host.send_event(5043, struct.pack('<i', 0x7fffffff) + wide('Act1_G1'))
                await host.expect_event(5044)
                await guest.expect_event(5044)
                host.send_event(5009, struct.pack('<i', 0x7fffffff) + wide('Act1_G1_A10') + b'\x00')
                _, chosen = await host.expect_event(5010)
                _, member_chosen = await guest.expect_event(5010)
                self.assertEqual(member_chosen, chosen)
                # Start: the member gets the host's 5014 for the same map.
                host.send_event(5013, struct.pack('<i', 0x7fffffff) + wide('Act1_G1_A10'), correlation=55)
                correlation, started = await host.expect_event(5014)
                self.assertEqual(correlation, 55)
                _, member_started = await guest.expect_event(5014)
                self.assertEqual(member_started, started)
                self.assertIn(wide('Act1_G1_A10'), started)
                # u32 result, u16 player_count (2 -> Loading_Party.mp3), u32 shared seed,
                # then peer_skills keyed by each member's UID.
                self.assertEqual(struct.unpack_from('<IH', started), (0, 2))
                for uid in (host_id, guest_id):
                    self.assertIn(b'\x0f' + struct.pack('<q', uid) + b'\x17', started)
                # Only the host's client reports kills and the finish: both members
                # get the kill's EXP and the result screen with an entry for each.
                kill = struct.pack('<iII', 0x7fffffff, jhash('1npi01n0') & 0xFFFFFFFF, 0x03000fa2)
                host.send_event(5063, kill)
                _, host_exp = await host.expect_event(5086)
                _, guest_exp = await guest.expect_event(5086)
                self.assertEqual(struct.unpack_from('<i', host_exp, 12), struct.unpack_from('<i', guest_exp, 12))
                self.assertGreater(struct.unpack_from('<i', guest_exp, 12)[0], 0)
                # 5017 (0x007AD380): bVictory << mapPartyScoreList << mapPartyDPS << nTotalMosterHP.
                # Verify rank comes from score / total_monster_hp (dungeonrank.lua), NOT mapPartyDPS:
                # host 4000/10000 = 0.40 -> A (3), guest 2500/10000 = 0.25 -> B (2),
                # party 6500/10000 = 0.65 -> S (4), even though DPS values are > 200.
                from darkblood.core.serialization.wire import JSerBufferWriter
                from darkblood.games.network.messages import FinishGameAck
                w5017 = JSerBufferWriter()
                w5017.write_bool(True)
                for m in ({host_id: 4000, guest_id: 2500}, {host_id: 290, guest_id: 240}):
                    w5017.write_u8(0x17)
                    w5017.write_varuint(len(m))
                    for k, v in sorted(m.items()):
                        w5017.write_u8(0x0F)
                        w5017.write_i64(k)
                        w5017.write_i32(v)
                w5017.write_i32(10000)  # nTotalMosterHP
                host.send_event(5017, w5017.to_bytes(), correlation=56)
                correlation, result = await host.expect_event(5018)
                self.assertEqual(correlation, 56)
                _, member_result = await guest.expect_event(5018)
                self.assertEqual(member_result, result)
                parsed_result = FinishGameAck.decode(result)
                self.assertEqual(parsed_result.rewards[host_id].rank, 3)
                self.assertEqual(parsed_result.rewards[guest_id].rank, 2)
                self.assertEqual(parsed_result.rank_first, 4)
                self.assertEqual(parsed_result.rank_final, 4)
                self.assertEqual(parsed_result.box_grade, 2)
                for uid in (host_id, guest_id):
                    self.assertIn(b'\x0f' + struct.pack('<q', uid), result)

                # Closing the dungeon gate or finishing a run (5045, back to square)
                # returns BOTH host and party members to town (5046) while keeping
                # the party intact (no 5036).
                host.send_event(5045, struct.pack('<i', 0x7fffffff))
                await host.expect_event(5046)
                await guest.expect_event(5046)
                guest.send_event(5060, struct.pack('<iq', 0x7fffffff, room_id))
                _, still = await guest.expect_event(5061)
                self.assertEqual(struct.unpack_from('<Iq', still), (0, room_id))
                self.assertEqual(still[12:14], bytes.fromhex('1082'))  # two members

                # A guest returning independently keeps the party run open for the host.
                host.send_event(5013, struct.pack('<i', 0x7fffffff) + wide('Act1_G1_A10'))
                await host.expect_event(5014)
                await guest.expect_event(5014)
                guest.send_event(5045, correlation=65)
                correlation, _ = await guest.expect_event(5046)
                self.assertEqual(correlation, 65)
                guest.send_event(5003, struct.pack('<q', room_id))
                _, active_room = await guest.expect_event(5004)
                self.assertEqual(struct.unpack_from("<I", active_room), (0,))
                self.assertEqual(RoomInfo.decode(active_room[4:]).state, 1)

                host.send_event(5017, w5017.to_bytes())
                _, last_result = await host.expect_event(5018)
                self.assertEqual(set(FinishGameAck.decode(last_result).rewards), {host_id})
                host.send_event(5045)
                await host.expect_event(5046)

                # 5021 hands the room host over (5022 to every member); only the
                # host may ask, and the target must be in the room.
                guest.send_event(5021, struct.pack('<iq', 0x7fffffff, guest_id), correlation=61)
                correlation, refused = await guest.expect_event(5022)
                self.assertEqual((correlation, refused), (61, struct.pack('<I', results.INVALID_STATE)))
                host.send_event(5021, struct.pack('<iq', 0x7fffffff, 424242), correlation=62)
                _, refused = await host.expect_event(5022)
                self.assertEqual(refused, struct.pack('<I', results.NO_EXIST_CHAR))
                host.send_event(5021, struct.pack('<iq', 0x7fffffff, guest_id), correlation=63)
                correlation, handed = await host.expect_event(5022)
                self.assertEqual((correlation, handed), (63, struct.pack('<Iq', 0, guest_id)))
                _, seen = await guest.expect_event(5022)
                self.assertEqual(seen, handed)
                guest.send_event(5021, struct.pack('<q', host_id))  # header word is optional
                _, back = await guest.expect_event(5022)
                self.assertEqual(back, struct.pack('<Iq', 0, host_id))
                _, seen = await host.expect_event(5022)
                self.assertEqual(seen, back)

                host.send_event(5005)
                await host.expect_event(5006)
                _, departure = await guest.expect_event(5036)
                self.assertEqual(departure, struct.pack('<Iq', 0, host_id))
                _, promoted = await guest.expect_event(5022)
                self.assertEqual(promoted, struct.pack('<Iq', 0, guest_id))
                # Guest leaves the room too, closing it.
                guest.send_event(5005)
                await guest.expect_event(5006)
                guest.send_event(5003, struct.pack('<q', room_id))
                _, error = await guest.expect_event(5004)
                self.assertEqual(error, struct.pack('<I', results.ROOM_NOT_EXISTS))

                bare_room_name = wide('Another room')
                host.send_event(5001, bare_room_name + room_options)
                _, created = await host.expect_event(5002)
                new_room_id = struct.unpack_from('<q', created, 4)[0]
                self.assertEqual(created[12:12 + len(bare_room_name)], bare_room_name)
                self.assertNotEqual(new_room_id, room_id)
                # Invite (5049: square UID, bool, char UID) carries the host's room as
                # nInviteRoomUID; Accept without a room UID sends 5054, which joins it.
                host.send_event(5049, struct.pack('<iq?q', 0x7fffffff, 1, False, guest_id))
                _, notice = await guest.expect_event(5051)
                invite = PartyInviteNot.decode(notice)
                self.assertEqual((invite.room_uid, invite.room_name, invite.inviter_uid),
                                 (new_room_id, 'Another room', host_id))
                guest.send_event(5054, struct.pack('<iqq', 0x7fffffff, 1, host_id))
                _, joined_again = await guest.expect_event(5004)
                self.assertEqual(struct.unpack_from('<Iq', joined_again), (0, new_room_id))
                await host.expect_event(5035)
                await guest.close()
                _, departure = await host.expect_event(5036)
                self.assertEqual(departure, struct.pack('<Iq', 0, guest_id))
            finally:
                await guest.close()

        self.run_async(self.with_server(scenario))
