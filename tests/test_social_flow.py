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

        self.run_async(self.with_server(scenario))


if __name__ == '__main__':
    unittest.main()
