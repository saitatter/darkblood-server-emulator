"""Tests for relay server handshake and isolation."""
import unittest

from tests.common import ServerTestCase
from darkblood.frontend import relay


class RelayFlowTest(ServerTestCase):
    def test_relay_handshake_without_welcome(self):
        import asyncio

        async def scenario(client):
            await client.connect()
            client.send_event(2131)
            try:
                payload = await asyncio.wait_for(client.expect(0x02), 0.5)
            except asyncio.TimeoutError:
                payload = None
            return payload

        self.assertIsNone(self.run_async(self.with_server(scenario, role='relay')))


if __name__ == '__main__':
    unittest.main()
