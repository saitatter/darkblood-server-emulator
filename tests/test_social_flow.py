"""Tests for social handlers: mailbox, friends, invite lists, web notices, and NPC interactions."""
import struct
import unittest

from tests.common import ServerTestCase, create_request, lobby_flow


class SocialFlowTest(ServerTestCase):
    def test_social_messages_and_notices(self):
        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('Socialite'))
            _, created = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', created, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)

            # 1. Post list (2219 -> 2220)
            client.send_event(2219, struct.pack('<i', 0x7fffffff))
            _, ack2220 = await client.expect_event(2220)
            self.assertEqual(struct.unpack_from('<i', ack2220)[0], 0)

            # 2. Friend list (2131 -> 2132)
            client.send_event(2131)
            _, ack2132 = await client.expect_event(2132)
            self.assertEqual(struct.unpack_from('<i', ack2132)[0], 0)

            # 3. Attendance / Guild (2569 -> 2570)
            client.send_event(2569)
            _, ack2570 = await client.expect_event(2570)
            self.assertEqual(struct.unpack_from('<i', ack2570)[0], 0)

            # 4. Invite list (2024 -> 2025)
            client.send_event(2024, b'\x1e\x00')
            _, ack2025 = await client.expect_event(2025)
            self.assertEqual(struct.unpack_from('<i', ack2025)[0], 0)
            self.assertEqual(ack2025[4:], b'\x10\x80')

            # 5. Http notice check (2594 -> 2595)
            client.send_event(2594, b'')
            _, ack2595 = await client.expect_event(2595)
            self.assertEqual(struct.unpack_from('<i?', ack2595), (0, False))

            # 6. Play option update (2216: fire and forget)
            client.send_event(2216, struct.pack('<q', char_id) + b'\x1e\x00')

            # 7. NPC first meet (2094 -> 2095)
            client.send_event(2094, struct.pack('<iI', 0x7fffffff, 0xeaec51bd))
            _, ack2095 = await client.expect_event(2095)
            self.assertEqual(struct.unpack_from('<II', ack2095), (0, 0xeaec51bd))

            # 8. Friend list add (2139 -> 2140: returns 0xCE player offline / not found)
            fname = 'Buddy'.encode('utf-16le') + b'\x00\x00'
            client.send_event(2139, fname)
            _, ack2140 = await client.expect_event(2140)
            self.assertEqual(struct.unpack_from('<i', ack2140)[0], 0xCE)

            # 9. Friend list delete (2135 -> 2136)
            client.send_event(2135, struct.pack('<q', 123456))
            _, ack2136 = await client.expect_event(2136)
            self.assertEqual(struct.unpack_from('<iq', ack2136), (0, 123456))

            # 10. Use speaker megaphone (2128 -> 2129)
            spk_msg = 'Party at town!'.encode('utf-16le') + b'\x00\x00'
            client.send_event(2128, struct.pack('<q', 888) + spk_msg + struct.pack('<q', 0))
            _, ack2129 = await client.expect_event(2129)
            self.assertEqual(struct.unpack_from('<iq', ack2129), (0, 888))

            # 11. Guild create proposal (5121 -> 5122)
            gname = 'Vanguard'.encode('utf-16le') + b'\x00\x00'
            client.send_event(5121, gname)
            _, ack5122 = await client.expect_event(5122)
            self.assertEqual(struct.unpack_from('<i', ack5122)[0], 0)

            # 12. Guild create (2150 -> 2151)
            client.send_event(2150, gname)
            _, ack2151 = await client.expect_event(2151)
            self.assertEqual(struct.unpack_from('<iq', ack2151), (0, 1001))

            # 13. Friend list update memo (2133 -> 2134)
            memo = 'Best ally'.encode('utf-16le') + b'\x00\x00'
            client.send_event(2133, struct.pack('<q', 123456) + memo)
            _, ack2134 = await client.expect_event(2134)
            self.assertEqual(struct.unpack_from('<iq', ack2134), (0, 123456))

            # 14. Guild invite (2160 -> 2161)
            target = 'FriendHero'.encode('utf-16le') + b'\x00\x00'
            client.send_event(2160, target)
            _, ack2161 = await client.expect_event(2161)
            self.assertEqual(struct.unpack_from('<i', ack2161)[0], 0)

            # 15. Guild leave (2162 -> 2163)
            client.send_event(2162, b'')
            _, ack2163 = await client.expect_event(2163)
            self.assertEqual(struct.unpack_from('<i', ack2163)[0], 0)

            # 16. Guild person join (2155 -> 2156)
            client.send_event(2155, struct.pack('<q', 2002))
            _, ack2156 = await client.expect_event(2156)
            self.assertEqual(struct.unpack_from('<i', ack2156)[0], 0)

            # 17. Guild money deposit (2179 -> 2180)
            client.send_event(2179, struct.pack('<q', 500))
            _, ack2180 = await client.expect_event(2180)
            self.assertEqual(struct.unpack_from('<i', ack2180)[0], 0)

            # 18. Guild money withdraw (2181 -> 2182)
            client.send_event(2181, struct.pack('<q', 200))
            _, ack2182 = await client.expect_event(2182)
            self.assertEqual(struct.unpack_from('<i', ack2182)[0], 0)

            # 19. Guild level up (2183 -> 2184)
            client.send_event(2183, b'')
            _, ack2184 = await client.expect_event(2184)
            self.assertEqual(struct.unpack_from('<i', ack2184)[0], 0)

            # 20. Guild notice modify (2185 -> 2186)
            gnotice = 'Guild rules apply'.encode('utf-16le') + b'\x00\x00'
            client.send_event(2185, gnotice)
            _, ack2186 = await client.expect_event(2186)
            self.assertEqual(struct.unpack_from('<i', ack2186)[0], 0)

            # 21. Guild notice delete (2188 -> 2189)
            client.send_event(2188, b'')
            _, ack2189 = await client.expect_event(2189)
            self.assertEqual(struct.unpack_from('<i', ack2189)[0], 0)

            # 22. Guild all skill init (2214 -> 2215)
            client.send_event(2214, b'')
            _, ack2215 = await client.expect_event(2215)
            self.assertEqual(struct.unpack_from('<i', ack2215)[0], 0)

            # 23. Mailbox send (2221 -> 2222)
            client.send_event(2221, b'')
            _, ack2222 = await client.expect_event(2222)
            self.assertEqual(struct.unpack_from('<i', ack2222)[0], 0)

            # 24. Mailbox read (2223 -> 2224)
            client.send_event(2223, struct.pack('<q', 888))
            _, ack2224 = await client.expect_event(2224)
            self.assertEqual(struct.unpack_from('<iq', ack2224), (0, 888))

            # 25. Mailbox get append item (2225 -> 2226)
            client.send_event(2225, struct.pack('<q', 888))
            _, ack2226 = await client.expect_event(2226)
            self.assertEqual(struct.unpack_from('<iq', ack2226[:12]), (0, 888))

            # 26. Mailbox delete (2236 -> 2237)
            client.send_event(2236, struct.pack('<q', 888))
            _, ack2237 = await client.expect_event(2237)
            self.assertEqual(struct.unpack_from('<i', ack2237)[0], 0)

            # 27. Chat message (5040 -> 5041)
            chat_bytes = b'\x00' + 'Hello from test'.encode('utf-16le')
            client.send_event(5040, chat_bytes)
            _, ack5041 = await client.expect_event(5041)
            self.assertEqual(struct.unpack_from('<iB', ack5041[:5]), (0, 0))

            # 28. Chat GM command /gold
            gm_gold = b'\x00' + '/gold 5000'.encode('utf-16le')
            client.send_event(5040, gm_gold)
            _, ack_gold = await client.expect_event(5041)
            self.assertEqual(struct.unpack_from('<iB', ack_gold[:5]), (0, 0))

            # 29. Chat GM command /levelup (triggers 5087 LevelUpNot followed by 5041 ChatAck)
            gm_lvl = b'\x00' + '/levelup 2'.encode('utf-16le')
            client.send_event(5040, gm_lvl)
            _, not5087 = await client.expect_event(5087)
            self.assertGreater(len(not5087), 0)
            _, ack_lvl = await client.expect_event(5041)
            self.assertEqual(struct.unpack_from('<iB', ack_lvl[:5]), (0, 0))

            # 30. Chat GM command /sp
            gm_sp = b'\x00' + '/sp 10'.encode('utf-16le')
            client.send_event(5040, gm_sp)
            _, ack_sp = await client.expect_event(5041)
            self.assertEqual(struct.unpack_from('<iB', ack_sp[:5]), (0, 0))

            # 31. Character nickname change (2310 -> 2311)
            from darkblood.core.serialization.jser import wide_string
            nick_payload = wide_string('RenamedHero') + struct.pack('<q', 123)
            client.send_event(2310, nick_payload)
            _, ack2311 = await client.expect_event(2311)
            self.assertEqual(struct.unpack_from('<i', ack2311)[0], 0)

            # 32. Guild name change (2314 -> 2315)
            gname_payload = wide_string('RenamedGuild') + struct.pack('<q', 456)
            client.send_event(2314, gname_payload)
            _, ack2315 = await client.expect_event(2315)
            self.assertEqual(struct.unpack_from('<i', ack2315)[0], 0)

            # 33. Keyboard custom key set (2319 -> 2320)
            client.send_event(2319, b'\x01\x02\x03\x04')
            _, ack2320 = await client.expect_event(2320)
            self.assertEqual(struct.unpack_from('<i', ack2320)[0], 0)

            # 34. Request teaching / mentorship (5351 -> 5352)
            client.send_event(5351, struct.pack('<q', 12345))
            _, ack5352 = await client.expect_event(5352)
            self.assertEqual(struct.unpack_from('<i', ack5352)[0], 0)

            # 35. Accept request teaching (5353 -> 5354)
            client.send_event(5353, struct.pack('<q', 54321))
            _, ack5354 = await client.expect_event(5354)
            self.assertEqual(struct.unpack_from('<i', ack5354)[0], 0)

        self.run_async(self.with_server(scenario))


if __name__ == '__main__':
    unittest.main()
