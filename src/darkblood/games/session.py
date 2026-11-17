"""Game connection session (JEvent dispatcher)."""
import struct
import zlib

from darkblood.core.serialization.jser import WireError, event, parse_event
from darkblood.games.handlers.arena import ArenaHandlers
from darkblood.games.handlers.commerce import CommerceHandlers
from darkblood.games.handlers.dungeon import DungeonHandlers
from darkblood.games.handlers.frontend import FrontendHandlers, welcome
from darkblood.games.handlers.inventory import InventoryHandlers
from darkblood.games.handlers.quests import QuestHandlers
from darkblood.games.handlers.skills import SkillHandlers
from darkblood.games.handlers.social import SocialHandlers
from darkblood.games.handlers.square import SquareHandlers


class GameSession(FrontendHandlers, SocialHandlers, SquareHandlers, CommerceHandlers,
                  InventoryHandlers, SkillHandlers, QuestHandlers, DungeonHandlers,
                  ArenaHandlers):
    """Application layer: JEvent dispatch to ``on_<opcode>`` handlers.

    Handlers live in darkblood.games.handlers, one mixin per game domain.
    Only responses with recovered parsers belong there.
    """

    def __init__(self, transport):
        self.transport = transport
        self.account = 'OfflinePlayer'  # single local account (Steam shim persona)
        self.active_char_id = None

    @property
    def char_id(self):
        """This connection's selected character (2006), else the last one
        selected by any connection."""
        if self.active_char_id is not None:
            return self.active_char_id
        from darkblood.games.state import selected_character
        return selected_character.get('id', 1)

    def current_char(self):
        """This connection's selected character record, else the account's
        first character, else None."""
        char = self.store().get(self.account, self.char_id)
        if not char:
            chars = self.store().characters(self.account)
            char = chars[0] if chars else None
        return char

    async def on_connected(self):
        if getattr(self.transport.server, 'role', 'game') != 'game':
            return
        # Login: 2 eE_ACCEPT_NOT makes the client send 5386 with its Steam
        # ticket (0x007AE730 -> 0x0078A160); on_5386 picks the account and
        # sends the welcome. Clients that never answer (an old shim without
        # GetAuthSessionTicket) get the default account after a short wait.
        import asyncio
        self.authenticated = False
        await self.transport.send_event(event(2), note='accept not (login)')
        self._welcome_fallback = asyncio.ensure_future(self._fallback_welcome())

    async def _fallback_welcome(self):
        import asyncio
        await asyncio.sleep(3)
        if not self.authenticated:
            await self._send_welcome(self.account, note='welcome 5020 (no 5386, default account)')

    async def _send_welcome(self, account, note):
        self.authenticated = True
        self.account = account
        await self.transport.send_event(welcome(account, self.store().account_uid(account)), note=note)

    async def on_5386(self, correlation, body):
        from darkblood.games.handlers.frontend import account_from_auth
        account = account_from_auth(body) or self.account
        if getattr(self, 'authenticated', False):
            return
        fallback = getattr(self, '_welcome_fallback', None)
        if fallback:
            fallback.cancel()
        self.transport.record('login', body, account=account)
        await self._send_welcome(account, note='welcome 5020 (%s)' % account)

    async def on_disconnect(self):
        fallback = getattr(self, '_welcome_fallback', None)
        if fallback:
            fallback.cancel()
        if self.active_char_id:
            from darkblood.games.world import GameWorldManager
            GameWorldManager.get().unregister_player(self.active_char_id)

    async def on_user_message(self, data):
        try:
            opcode, correlation, compressed, body = parse_event(data)
        except WireError as exc:
            self.transport.record('bad-event', data, error=str(exc))
            return
        if compressed and len(body) > 6 and body[4] == 0x78:
            # Observed (2073, 2216, 2346): u32 inflated size + zlib stream.
            # 2203 also sets the flag with a plain body, so inflate only when
            # a zlib header follows and the size matches; otherwise keep it.
            try:
                inflated = zlib.decompress(body[4:])
                if len(inflated) == struct.unpack_from('<I', body)[0]:
                    body = inflated
            except zlib.error:
                pass
        self.transport.record('event', body, opcode=opcode, opcode_hex='0x%04x' % opcode,
                              correlation=correlation, compressed=compressed)
        if getattr(self.transport.server, 'role', 'game') != 'game':
            self.transport.record('relay-event', body, opcode=opcode)
            return
        handler = getattr(self, 'on_%d' % opcode, None)
        if handler is None:
            self.transport.record('unhandled-event', body, opcode=opcode)
            return
        await handler(correlation, body)

    _store = None

    @classmethod
    def store(cls):
        if cls._store is None:
            from darkblood.player_management.store import SqliteCharacterStore
            cls._store = SqliteCharacterStore()
        return cls._store
