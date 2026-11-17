"""Game connection session (JEvent dispatcher)."""
import struct
import zlib

from darkblood.core.serialization.jser import WireError, parse_event
from darkblood.games.handlers.arena import ArenaHandlers
from darkblood.games.handlers.commerce import CommerceHandlers
from darkblood.games.handlers.dungeon import DungeonHandlers
from darkblood.games.handlers.frontend import FrontendHandlers, welcome
from darkblood.games.handlers.quests import QuestHandlers
from darkblood.games.handlers.social import SocialHandlers
from darkblood.games.handlers.square import SquareHandlers


class GameSession(FrontendHandlers, SocialHandlers, SquareHandlers, CommerceHandlers,
                  QuestHandlers, DungeonHandlers, ArenaHandlers):
    """Application layer: JEvent dispatch to ``on_<opcode>`` handlers.

    Handlers live in darkblood.games.handlers, one mixin per game domain.
    Only responses with recovered parsers belong there.
    """

    def __init__(self, transport):
        self.transport = transport
        self.account = 'OfflinePlayer'  # single local account (Steam shim persona)
        self.active_char_id = None

    def current_char(self):
        """The selected character record (process-wide selection from 2006),
        else the account's first character, else None."""
        from darkblood.games.state import selected_character
        char = None
        if selected_character.get('id') is not None:
            char = self.store().get(self.account, selected_character['id'])
        if not char:
            chars = self.store().characters(self.account)
            char = chars[0] if chars else None
        return char

    async def on_connected(self):
        if getattr(self.transport.server, 'role', 'game') != 'game':
            return
        await self.transport.send_event(welcome(), note='welcome 5020')

    async def on_disconnect(self):
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
