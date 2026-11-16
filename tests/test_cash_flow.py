"""Cash shop balance: 2369 -> 2370 (u32 result, u64 cash, u32 mileage; 0x004CFDF0)."""
import struct
import unittest

from tests.common import ServerTestCase, lobby_flow
from darkblood.games import session


class CashFlowTest(ServerTestCase):
    def test_current_cash_reports_account_balance(self):
        async def scenario(client):
            await lobby_flow(client)
            store = session.GameSession.store()
            store.set_account_cash('OfflinePlayer', 0)
            self.assertEqual(store.add_account_cash('OfflinePlayer', 12345), 12345)
            client.send_event(2369, b'')
            _, ack = await client.expect_event(2370)
            self.assertEqual(struct.unpack('<IqI', ack), (0, 12345, 0))
            self.assertEqual(store.add_account_cash('OfflinePlayer', -99999), 0)

        self.run_async(self.with_server(scenario))


if __name__ == '__main__':
    unittest.main()
