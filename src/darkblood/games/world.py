"""Multi-client Game World Manager and Party Subsystem.

Coordinates town square channels, player visibility
broadcasts (Opcode 5096 UpdateCharInfoNot), square join/leave presence notifications
(Opcode 5021/5022), and party management (Opcodes 2100-2107, 5049-5056).
"""
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from darkblood.core.network.proudnet import SQUARE_UID_MASK, square_uid
from darkblood.core.serialization.jser import event
from darkblood.games.entities.character import Character, layer_net_id
from darkblood.games.network.messages.lobby import JoinLayerNot, LeaveLayerNot, PageCharTemp
from darkblood.games.network.messages.system import UpdateCharInfoNot
from darkblood.games.network.messages.party import UserJoinSquareNot, UserLeaveSquareNot
from darkblood.games.party import Party, PartyManager, PartyMember

logger = logging.getLogger(__name__)

__all__ = [
    'GameWorldManager',
    'Party',
    'PartyManager',
    'PartyMember',
    'SQUARE_UID_MASK',
    'WorldPlayer',
    'square_uid',
]


@dataclass
class WorldPlayer:
    """Connected character in the active game world."""
    session: any
    char_id: int
    char_data: dict
    square_id: int = 1
    layer_id: int = field(default_factory=layer_net_id)
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    angle: float = 0.0
    # Set from 2006 until the client is ready for town peers. Live timing:
    # 5027 sent 1 ms after 2006 (before the client's 2219) was never shown;
    # 5027 at +0.9 s (after 2219, before the relay JoinGroup) was shown;
    # 5027 only after 5124 (+10 s, after JoinGroup) was not shown either.
    # 2131 (+2 s, just before JoinGroup) ends the wait; 5124 is a fallback.
    loading: bool = False


class GameWorldManager:
    """Central singleton managing active world instances and player presence."""

    _instance = None

    def __init__(self):
        self.players: Dict[int, WorldPlayer] = {}  # char_id -> WorldPlayer
        self._squares: Dict[int, Dict[int, Set[int]]] = {}

    @classmethod
    def get(cls) -> 'GameWorldManager':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register_player(self, session, char_id: int, char_data: dict, square_id: int = 1) -> WorldPlayer:
        """Register a character entering the world."""
        # Re-entering a square or replacing a connection keeps party membership.
        previous = self.players.get(char_id)
        if previous:
            self._remove_presence(previous)

        player = WorldPlayer(
            session=session,
            char_id=char_id,
            char_data=char_data,
            square_id=square_id
        )
        # The client enters town on the layer from 2007/5046, i.e. the stored one.
        stored_layer = (char_data or {}).get('join_layer_net_id')
        if stored_layer is not None:
            player.layer_id = stored_layer
        self.players[char_id] = player
        self._add_presence(player)
        party = PartyManager.get().get_player_party(char_id)
        if party:
            party.members[char_id].session = session
        return player

    def _add_presence(self, player: WorldPlayer):
        layers = self._squares.setdefault(player.square_id, {})
        layers.setdefault(player.layer_id, set()).add(player.char_id)

    def _remove_presence(self, player: WorldPlayer):
        layers = self._squares[player.square_id]
        occupants = layers[player.layer_id]
        occupants.remove(player.char_id)
        if not occupants:
            del layers[player.layer_id]
        if not layers:
            del self._squares[player.square_id]

    def change_layer(self, session, layer_id: int):
        player = self.players.get(session.active_char_id)
        if player is None or player.session is not session:
            return None, None
        previous_layer = player.layer_id
        if previous_layer != layer_id:
            self._remove_presence(player)
            player.layer_id = layer_id
            self._add_presence(player)
        return player, previous_layer

    def unregister_player(self, char_id: int, session=None) -> Optional[WorldPlayer]:
        """Remove player on disconnect or return to character select."""
        player = self.players.get(char_id)
        if session is not None and (player is None or player.session is not session):
            return None
        player = self.players.pop(char_id, None)
        if player:
            self._remove_presence(player)
        # Also clean up any active party membership
        PartyManager.get().leave_party(char_id)
        return player

    def get_player(self, char_id: int) -> Optional[WorldPlayer]:
        return self.players.get(char_id)

    def get_players_in_square(self, square_id: int, layer_id: Optional[int] = None) -> List[WorldPlayer]:
        layers = self._squares.get(square_id, {})
        groups = layers.values() if layer_id is None else (layers.get(layer_id, ()),)
        return [self.players[cid] for occupants in groups for cid in occupants]

    async def broadcast_to_square(self, square_id: int, ev: bytes, exclude_char_id: Optional[int] = None,
                                  note: str = "", layer_id: Optional[int] = None):
        """Broadcast an event payload to all players in a square channel."""
        for p in self.get_players_in_square(square_id, layer_id):
            if p.char_id == exclude_char_id or self.players.get(p.char_id) is not p:
                continue
            if layer_id is not None and p.layer_id != layer_id:
                continue
            if p.loading:
                continue
            if p and p.session and getattr(p.session, 'transport', None):
                try:
                    await p.session.transport.send_event(ev, note=note)
                except Exception as e:
                    logger.debug("Failed broadcast to char %d: %s", p.char_id, e)

    async def broadcast_player_spawn(self, new_player: WorldPlayer):
        """Broadcast Opcode 5027 (eERC_JOIN_LAYER_NOT) and Opcode 5096 (eERC_UPDATE_CHAR_INFO_NOT)
        for mutual player visibility in the town square.

        5027 instantiates the JUser entity (JNetUserMgr::SetPeerInfo_At via Reader 0x00A494B0).
        5096 updates the 3D model, visual equipment (0x00A52630), and guild name.
        """
        from darkblood.games.handlers.frontend import build_char_details
        new_char = _town_character(new_player)
        new_p_data = dict(
            char_id=new_player.char_id,
            name=new_char.name,
            char_class=new_char.char_class,
            level=new_char.level,
            x=new_player.x,
            y=new_player.y,
            z=new_player.z,
            guild_uid=getattr(new_char, 'guild_uid', 0),
            guild_name=getattr(new_char, 'guild_name', '') or '',
            server_bits=square_uid(new_player.square_id),
        )

        if new_player.loading:
            return  # announced both ways once ready (player_ready)

        # 1. Notify others in square of newcomer
        layer_not_ev = event(5027, JoinLayerNot(players=[PageCharTemp(**new_p_data)]).encode())
        await self.broadcast_to_square(
            new_player.square_id,
            layer_not_ev,
            exclude_char_id=new_player.char_id,
            layer_id=new_player.layer_id,
            note=f"join layer not 5027 for {new_char.name} ({new_player.char_id})"
        )

        new_details = UpdateCharInfoNot(character=new_char,
                                        guild_name=getattr(new_char, 'guild_name', '') or '').encode()
        spawn_ev = event(5096, new_details)
        await self.broadcast_to_square(
            new_player.square_id,
            spawn_ev,
            exclude_char_id=new_player.char_id,
            layer_id=new_player.layer_id,
            note=f"update char info 5096 for {new_char.name} ({new_player.char_id})"
        )

        # 2. Send existing players in square to newcomer
        await self.send_existing_players(new_player)

    async def player_ready(self, session):
        """5124 after a town load: the client can now show its peers."""
        player = self.players.get(getattr(session, 'active_char_id', None))
        if player is None or player.session is not session or not player.loading:
            return
        player.loading = False
        await self.broadcast_player_spawn(player)

    async def send_existing_players(self, new_player: WorldPlayer):
        if new_player.loading:
            return
        existing_players = []
        for existing in self.get_players_in_square(new_player.square_id, new_player.layer_id):
            if existing.char_id == new_player.char_id or existing.loading:
                continue
            existing_players.append((existing, _town_character(existing)))

        if existing_players:
            ex_data_list = [
                dict(
                    char_id=ep.char_id,
                    name=ec.name,
                    char_class=ec.char_class,
                    level=ec.level,
                    x=ep.x,
                    y=ep.y,
                    z=ep.z,
                    guild_uid=getattr(ec, 'guild_uid', 0),
                    guild_name=getattr(ec, 'guild_name', '') or '',
                    server_bits=square_uid(ep.square_id),
                )
                for ep, ec in existing_players
            ]
            try:
                await new_player.session.transport.send_event(
                    event(5027, JoinLayerNot(players=[PageCharTemp(**p) for p in ex_data_list]).encode()),
                    note=f"join layer not 5027 with {len(ex_data_list)} players for newcomer"
                )
            except Exception as e:
                logger.debug("Failed sending 5027 to newcomer: %s", e)

            for ep, ec in existing_players:
                details = UpdateCharInfoNot(character=ec, guild_name=getattr(ec, 'guild_name', '') or '').encode()
                try:
                    await new_player.session.transport.send_event(
                        event(5096, details),
                        note=f"update char info 5096 for {ec.name} ({ep.char_id}) to newcomer"
                    )
                except Exception as e:
                    logger.debug("Failed sending 5096 to newcomer: %s", e)

    async def broadcast_user_join(self, player: WorldPlayer):
        """Broadcast Opcode 5021 (eERC_USER_JOIN_SQUARE_NOT) to square occupants."""
        c = _town_character(player) if player.char_data else None
        join_not = UserJoinSquareNot(
            char_id=player.char_id,
            square_id=player.square_id,
            x=player.x,
            y=player.y,
            z=player.z,
            angle=player.angle,
            char_class=c.char_class if c else 0,
            level=c.level if c else 1,
            char_name=c.name if c else ""
        )
        await self.broadcast_to_square(
            player.square_id,
            event(5021, join_not.encode()),
            exclude_char_id=player.char_id,
            note=f"user join square not ({player.char_id})"
        )

    async def broadcast_user_leave(self, char_id: int, square_id: int, reason: int = 0):
        """Broadcast Opcode 5022 (eERC_USER_LEAVE_SQUARE_NOT) to square occupants."""
        leave_not = UserLeaveSquareNot(char_id=char_id, reason=reason)
        await self.broadcast_to_square(
            square_id,
            event(5022, leave_not.encode()),
            exclude_char_id=char_id,
            note=f"user leave square not ({char_id})"
        )

    async def broadcast_layer_leave(self, player: WorldPlayer, layer_id: int):
        """5039 removes the departed character from the old layer on the client."""
        await self.broadcast_to_square(
            player.square_id,
            event(5039, LeaveLayerNot(result=0, char_uid=player.char_id).encode()),
            exclude_char_id=player.char_id,
            layer_id=layer_id,
            note=f"leave layer not ({player.char_id})",
        )

    async def broadcast_player_departure(self, player: WorldPlayer):
        await self.broadcast_layer_leave(player, player.layer_id)

    async def remove_session_player(self, session):
        """Send departure once, for the session that owns the registration."""
        player = self.unregister_player(session.active_char_id, session=session)
        if player is not None:
            await self.broadcast_player_departure(player)

def _town_character(player: 'WorldPlayer') -> Character:
    """Character details for peers, carrying the player's current town layer.

    The details (0x00A52630) include nJoinLayerNetID (+0x5F). It used to
    carry the stored default layer, so after a 5030 layer change the peer's
    JUser reported a different layer than the viewer and stayed hidden.
    """
    char = Character.from_dict(player.char_data)
    if player.layer_id is not None:
        char.join_layer_net_id = player.layer_id
    return char
