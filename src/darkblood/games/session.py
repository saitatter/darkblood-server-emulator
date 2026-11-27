"""Game connection session (JEvent dispatcher)."""
import asyncio
from darkblood.core.serialization.jser import WireError, event, parse_event
from darkblood.games.dispatcher import PacketDispatcher, packet_handler
from darkblood.games.handlers.arena import ArenaHandlers
from darkblood.games.handlers.commerce import CommerceHandlers
from darkblood.games.handlers.dungeon import DungeonHandlers
from darkblood.games.handlers.frontend import DEFAULT_ACCOUNT, FrontendHandlers, account_from_auth, welcome
from darkblood.games.handlers.gm import GmHandlers
from darkblood.games.handlers.inventory import InventoryHandlers
from darkblood.games.handlers.life_skills import LifeSkillHandlers
from darkblood.games.handlers.mail import MailHandlers
from darkblood.games.handlers.pets import PetHandlers
from darkblood.games.handlers.quests import QuestHandlers
from darkblood.games.handlers.skills import SkillHandlers
from darkblood.games.handlers.social import SocialHandlers
from darkblood.games.handlers.square import SquareHandlers
from darkblood.games.progression import (
    refresh_depot_timers,
    refresh_dungeon_penalty,
    refresh_stress,
    stress_changed_not,
    refresh_character_timers,
)
from darkblood.games.world import GameWorldManager
from darkblood.player_management.store import SqliteCharacterStore


CONTROLLERS = (
    ('frontend', FrontendHandlers),
    ('social', SocialHandlers),
    ('mail', MailHandlers),
    ('square', SquareHandlers),
    ('life', LifeSkillHandlers),
    ('commerce', CommerceHandlers),
    ('inventory', InventoryHandlers),
    ('skills', SkillHandlers),
    ('quests', QuestHandlers),
    ('dungeon', DungeonHandlers),
    ('arena', ArenaHandlers),
    ('pets', PetHandlers),
    ('gm', GmHandlers),
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
        self._timer_task = None

        for name, controller_type in CONTROLLERS:
            setattr(self, name, controller_type(self))

    def start_timer_loop(self, interval: float = 5.0):
        """Start (or restart) the per-session periodic cooldown/stress/penalty ticker."""
        self.stop_timer_loop()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._timer_task = loop.create_task(self._run_timer_loop(interval))

    def stop_timer_loop(self):
        task = getattr(self, '_timer_task', None)
        if task is not None and not task.done():
            task.cancel()
        self._timer_task = None

    async def tick_timers(self, now=None):
        """Run one timer tick: live town stress recovery (2023) and penalty step/expiry (2085)."""
        char = self.current_char()
        if char is None:
            return
        dirty = False
        # Passive stress recovery (-1/min) ticks while outside a dungeon;
        # summoned pet Energy drains by 1 every 30s while inside a dungeon.
        if not getattr(self.dungeon, 'in_dungeon', False):
            self.pets.pet_energy_last_tick = None
            if refresh_stress(char, now=now):
                dirty = True
                await self.transport.send_event(
                    event(2023, stress_changed_not(char).encode()),
                    note=f"stress timer tick ({char['stress']})",
                )
        elif await self.pets.tick_dungeon_energy(char, now=now):
            dirty = True
        # Dungeon leave (0) and wipeout (1) penalty recovery steps & expiration.
        for ptype in (0, 1):
            p_changed, notice = refresh_dungeon_penalty(char, penalty_type=ptype, now=now)
            if p_changed:
                dirty = True
                if notice is not None:
                    await self.transport.send_event(
                        event(2085, notice.encode()),
                        note=f'dungeon penalty tick (type={ptype}, step={notice.penalty_id}, elapsed={notice.duration})',
                    )
        if refresh_depot_timers(char, now=now):
            dirty = True
        if dirty:
            self.store().save_char(self.account, self.active_char_id)
        # Server-wide gathering node regeneration (5126); any ticking session advances it.
        await self.life.tick_regeneration(now)

    async def _run_timer_loop(self, interval: float):
        try:
            while True:
                await asyncio.sleep(interval)
                await self.tick_timers()
        except (asyncio.CancelledError, ConnectionError, OSError):
            return

    @property
    def char_id(self):
        return self.active_char_id or 0

    def current_char(self):
        if self.active_char_id is None:
            return None
        return self.store().get(self.account, self.active_char_id)

    async def on_connected(self):
        await self.transport.send_event(event(2), note='accept not (login)')

    @packet_handler(5386)
    async def handle_authenticate_steam_user(self, correlation, body):
        """Opcode 5386 (eERC_AUTHENTICATE_STEAM_GAMEUSER_REQ) -> 5020 welcome."""
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
        self.stop_timer_loop()
        self.life.stop_fishing()
        self.arena.leave_room()
        await self.dungeon.leave_room()
        if self.active_char_id:
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
            cls._store = SqliteCharacterStore(timer_refresher=refresh_character_timers)
        return cls._store

DISPATCHER = PacketDispatcher()
DISPATCHER.register_controller(GameSession)
for service_attr, service_type in CONTROLLERS:
    DISPATCHER.register_controller(service_type, service_attr)
