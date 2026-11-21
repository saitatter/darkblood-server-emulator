"""Party and world presence survive square changes and overlapping reconnects."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

from tests.common import ServerTestCase
from darkblood.core.serialization.jser import parse_event
from darkblood.games.session import GameSession
from darkblood.games.world import GameWorldManager, PartyManager


class WorldSessionTest(ServerTestCase):
    def setUp(self):
        previous_world = GameWorldManager._instance
        previous_parties = PartyManager._instance
        self.addCleanup(setattr, GameWorldManager, '_instance', previous_world)
        self.addCleanup(setattr, PartyManager, '_instance', previous_parties)
        self.world = GameWorldManager._instance = GameWorldManager()
        self.parties = PartyManager._instance = PartyManager()

    def make_session(self, char_id):
        transport = SimpleNamespace(send_event=AsyncMock())
        session = GameSession(transport)
        session.active_char_id = char_id
        return session

    def test_square_change_keeps_party_and_rebinds_connection(self):
        original = self.make_session(101)
        replacement = self.make_session(101)
        self.world.register_player(original, 101, {}, square_id=1)
        party = self.parties.create_party(101, 'Leader', session=original)
        self.parties.invite_player(101, 202)

        self.world.register_player(original, 101, {}, square_id=2)
        self.assertIs(self.parties.get_player_party(101), party)
        self.assertNotIn(101, {player.char_id for player in self.world.get_players_in_square(1)})
        self.assertIn(101, {player.char_id for player in self.world.get_players_in_square(2)})

        self.world.register_player(replacement, 101, {}, square_id=2)
        self.assertIs(self.parties.get_player_party(101), party)
        self.assertEqual(party.pending_invites, {202})
        self.assertIs(party.members[101].session, replacement)

        async def scenario():
            await self.parties.broadcast_to_party(party.party_id, b'party update')
            replacement.transport.send_event.assert_awaited_once()
            original.transport.send_event.assert_not_awaited()

        self.run_async(scenario())

    def test_old_disconnect_and_leave_requests_keep_reconnected_player(self):
        async def scenario():
            original = self.make_session(101)
            replacement = self.make_session(101)
            observer = self.make_session(202)
            self.world.register_player(original, 101, {})
            player = self.world.register_player(replacement, 101, {})
            self.world.register_player(observer, 202, {})
            party = self.parties.create_party(101, 'Leader', session=replacement)

            await original.on_disconnect()
            await original.square.handle_leave_layer(7, b'')
            await original.square.handle_leave_square(8, b'')

            self.assertIs(self.world.get_player(101), player)
            self.assertIs(self.parties.get_player_party(101), party)
            observer.transport.send_event.assert_not_awaited()
            self.assertEqual(
                [parse_event(call.args[0])[0] for call in original.transport.send_event.await_args_list],
                [5038, 5033],
            )

        self.run_async(scenario())

    def test_current_disconnect_removes_party_and_notifies_once(self):
        async def scenario():
            departing = self.make_session(101)
            observer = self.make_session(202)
            self.world.register_player(departing, 101, {}, square_id=7)
            self.world.register_player(observer, 202, {}, square_id=7)
            self.parties.create_party(101, 'Leader', session=departing)

            await departing.square.handle_leave_layer(1, b'')
            await departing.on_disconnect()

            self.assertIsNone(self.world.get_player(101))
            self.assertIsNone(self.parties.get_player_party(101))
            self.assertNotIn(101, {player.char_id for player in self.world.get_players_in_square(7)})
            # One departure: 5039 removes the peer from the layer (5022 is reserved for eERC_CHANGE_ROOMHOST_ACK).
            self.assertEqual(
                [parse_event(call.args[0])[0] for call in observer.transport.send_event.await_args_list],
                [5039],
            )

        self.run_async(scenario())
