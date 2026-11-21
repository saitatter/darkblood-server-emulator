"""Game connection session (JEvent dispatcher)."""
from darkblood.core.serialization.jser import WireError, event, parse_event
from darkblood.games.dispatcher import PacketDispatcher
from darkblood.games.handlers.arena import ArenaHandlers
from darkblood.games.handlers.commerce import CommerceHandlers
from darkblood.games.handlers.dungeon import DungeonHandlers
from darkblood.games.handlers.frontend import DEFAULT_ACCOUNT, FrontendHandlers, account_from_auth, welcome
from darkblood.games.handlers.inventory import InventoryHandlers
from darkblood.games.handlers.mail import MailHandlers
from darkblood.games.handlers.pets import PetHandlers
from darkblood.games.handlers.quests import QuestHandlers
from darkblood.games.handlers.skills import SkillHandlers
from darkblood.games.handlers.social import SocialHandlers
from darkblood.games.handlers.square import SquareHandlers


CONTROLLERS = (
    ('frontend', FrontendHandlers),
    ('social', SocialHandlers),
    ('mail', MailHandlers),
    ('square', SquareHandlers),
    ('commerce', CommerceHandlers),
    ('inventory', InventoryHandlers),
    ('skills', SkillHandlers),
    ('quests', QuestHandlers),
    ('dungeon', DungeonHandlers),
    ('arena', ArenaHandlers),
    ('pets', PetHandlers),
)


class GameSession:
    """Application layer: JEvent dispatch via PacketDispatcher and domain services.

    Domain services live in darkblood.games.handlers, one service per game domain.
    Only responses with recovered parsers belong there.
    """

    def __init__(self, transport):
        self.transport = transport
        self.account = DEFAULT_ACCOUNT
        self.authenticated = False
        self.active_char_id = None
        self.square_id = 1

        for name, controller_type in CONTROLLERS:
            setattr(self, name, controller_type(self))

    @property
    def char_id(self):
        return self.active_char_id or 0

    def current_char(self):
        if self.active_char_id is None:
            return None
        return self.store().get(self.account, self.active_char_id)

    async def on_connected(self):
        await self.transport.send_event(event(2), note='accept not (login)')

    async def on_5386(self, correlation, body):
        if self.authenticated:
            return
        account = account_from_auth(body)
        if account is None:
            self.transport.record('invalid-login', body)
            return
        self.account = account
        self.authenticated = True
        self.transport.record('login', body, account=account)
        await self.transport.send_event(
            welcome(account, self.store().account_uid(account)), note=f'welcome 5020 ({account})'
        )

    async def on_disconnect(self):
        await self.dungeon.leave_room()
        if self.active_char_id:
            from darkblood.games.world import GameWorldManager
            await GameWorldManager.get().remove_session_player(self)

    async def on_user_message(self, data):
        try:
            opcode, correlation, compressed, body = parse_event(data)
        except WireError as exc:
            self.transport.record('bad-event', data, error=str(exc))
            return
        self.transport.record('event', body, opcode=opcode, opcode_hex='0x%04x' % opcode,
                              correlation=correlation, compressed=compressed)
        if self.authenticated or opcode == 5386:
            await DISPATCHER.dispatch(self, opcode, correlation, body)
        else:
            self.transport.record('unauthenticated-event', body, opcode=opcode)

    _store = None

    @classmethod
    def store(cls):
        if cls._store is None:
            from darkblood.player_management.store import SqliteCharacterStore
            cls._store = SqliteCharacterStore()
        return cls._store

DISPATCHER = PacketDispatcher()
DISPATCHER.register_controller(GameSession)
for service_attr, service_type in CONTROLLERS:
    DISPATCHER.register_controller(service_type, service_attr)
