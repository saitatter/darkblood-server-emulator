"""Multi-client Game World Manager and Party Subsystem.

Coordinates town square channels, player visibility
broadcasts (Opcode 5096 UpdateCharInfoNot), square join/leave presence notifications
(Opcode 5021/5022), and party management (Opcodes 2100-2107, 5049-5056).
"""
import asyncio
import logging
import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from darkblood.core.serialization.jser import event, wide_string
from darkblood.games.entities.character import Character, layer_net_id
from darkblood.games.network.messages.lobby import JoinLayerNot, PageCharTemp
from darkblood.games.network.messages.system import UpdateCharInfoNot
from darkblood.games.network.messages.party import (
    PartyAcceptInviteNot, PartyInfoNot, PartyInviteNot, PartyMemberInfo,
    UserJoinSquareNot, UserLeaveSquareNot
)

logger = logging.getLogger(__name__)


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
        from darkblood.games.config import OFFLINE_SERVER_ID
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
            server_bits=OFFLINE_SERVER_ID << 54,  # key in bits 54-58 (0x00A614A0)
        )

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
        existing_players = []
        for existing in self.get_players_in_square(new_player.square_id, new_player.layer_id):
            if existing.char_id == new_player.char_id:
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
                    server_bits=OFFLINE_SERVER_ID << 54,  # key in bits 54-58 (0x00A614A0)
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
        await self.broadcast_to_square(player.square_id, event(5039, struct.pack('<Iq', 0, player.char_id)),
                                       exclude_char_id=player.char_id, layer_id=layer_id,
                                       note=f"leave layer not ({player.char_id})")

    async def broadcast_player_departure(self, player: WorldPlayer):
        await self.broadcast_layer_leave(player, player.layer_id)
        await self.broadcast_user_leave(player.char_id, player.square_id)

    async def remove_session_player(self, session):
        """Send departure once, for the session that owns the registration."""
        player = self.unregister_player(session.active_char_id, session=session)
        if player is not None:
            await self.broadcast_player_departure(player)

# =========================================================================
# Party Subsystem Domain Entities & Manager
# =========================================================================

@dataclass
class PartyMember:
    """Active member of a player party."""
    char_id: int
    char_name: str
    char_class: int = 0
    level: int = 1
    session: any = None
    is_leader: bool = False


@dataclass
class Party:
    """Co-op party containing up to max_members characters."""
    party_id: int
    leader_id: int
    members: Dict[int, PartyMember] = field(default_factory=dict)
    pending_invites: Set[int] = field(default_factory=set)
    max_members: int = 4

    def is_full(self) -> bool:
        return len(self.members) >= self.max_members

    def member_ids(self) -> List[int]:
        return list(self.members.keys())


class PartyManager:
    """Central singleton managing player parties, rosters, and invitations."""

    _instance = None

    def __init__(self):
        self.parties: Dict[int, Party] = {}        # party_id -> Party
        self.player_party: Dict[int, int] = {}     # char_id -> party_id
        self._next_party_id: int = 1

    @classmethod
    def get(cls) -> 'PartyManager':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def create_party(self, leader_id: int, leader_name: str, leader_class: int = 0,
                     level: int = 1, session: any = None) -> Party:
        """Create a new party with leader_id as the host."""
        self.leave_party(leader_id)

        party_id = self._next_party_id
        self._next_party_id += 1

        leader = PartyMember(
            char_id=leader_id,
            char_name=leader_name,
            char_class=leader_class,
            level=level,
            session=session,
            is_leader=True
        )
        party = Party(party_id=party_id, leader_id=leader_id)
        party.members[leader_id] = leader
        self.parties[party_id] = party
        self.player_party[leader_id] = party_id
        return party

    def get_party(self, party_id: int) -> Optional[Party]:
        return self.parties.get(party_id)

    def get_player_party(self, char_id: int) -> Optional[Party]:
        pid = self.player_party.get(char_id)
        if pid:
            return self.parties.get(pid)
        return None

    def invite_player(self, inviter_id: int, target_id: int,
                      inviter_name: str = '', inviter_class: int = 0,
                      inviter_level: int = 1, session: any = None) -> Tuple[int, Optional[Party]]:
        """Invite target_id to inviter_id's party.

        Returns (result_code, party):
            result 0: Success
            result 1: Target already in a party
            result 2: Party full
            result 3: Not party leader
        """
        if not target_id or target_id == inviter_id:
            return 1, None

        if target_id in self.player_party:
            return 1, None

        party = self.get_player_party(inviter_id)
        if party is None:
            party = self.create_party(inviter_id, inviter_name, inviter_class, inviter_level, session)
        else:
            if party.leader_id != inviter_id:
                return 3, party
            if party.is_full():
                return 2, party

        party.pending_invites.add(target_id)
        return 0, party

    def accept_invite(self, target_id: int, party: Optional[Party], target_name: str = '',
                      target_class: int = 0, level: int = 1, session: any = None) -> Tuple[int, Optional[Party]]:
        """Consume a pending invitation to the specified party.

        Returns (result_code, party):
            result 0: Success
            result 1: Party not found
            result 2: Party full
            result 3: Target has no usable invitation
        """
        if party is None or self.get_party(party.party_id) is not party:
            return 1, None
        if target_id <= 0 or target_id not in party.pending_invites:
            return 3, None
        if self.get_player_party(target_id) is not None:
            return 3, None

        if party.is_full():
            party.pending_invites.discard(target_id)
            return 2, None

        party.pending_invites.remove(target_id)

        member = PartyMember(
            char_id=target_id,
            char_name=target_name or f"Player_{target_id}",
            char_class=target_class,
            level=level,
            session=session,
            is_leader=False
        )
        party.members[target_id] = member
        self.player_party[target_id] = party.party_id
        return 0, party

    def leave_party(self, char_id: int) -> Tuple[int, Optional[Party]]:
        """Leave current party. If leader leaves, promotes the next member.

        Returns (result_code, remaining_party_or_None).
        """
        party = self.get_player_party(char_id)
        if party is None:
            return 1, None

        party.members.pop(char_id, None)
        self.player_party.pop(char_id, None)

        if not party.members:
            self.parties.pop(party.party_id, None)
            return 0, None

        # Promote next member to leader if host departed
        if party.leader_id == char_id:
            next_leader_id = next(iter(party.members.keys()))
            party.leader_id = next_leader_id
            party.members[next_leader_id].is_leader = True

        return 0, party

    def kick_player(self, leader_id: int, target_id: int) -> Tuple[int, Optional[Party]]:
        """Party leader kicks a member.

        Returns (result_code, party):
            result 0: Success
            result 1: Party not found
            result 2: Caller is not the party leader
            result 3: Target is not in the party
        """
        party = self.get_player_party(leader_id)
        if party is None:
            return 1, None
        if party.leader_id != leader_id:
            return 2, party
        if target_id not in party.members:
            return 3, party

        party.members.pop(target_id, None)
        self.player_party.pop(target_id, None)
        return 0, party

    async def broadcast_to_party(self, party_id: int, ev: bytes, exclude_char_id: Optional[int] = None, note: str = ""):
        """Broadcast an event payload to all active members of a party."""
        party = self.parties.get(party_id)
        if not party:
            return
        for cid, member in list(party.members.items()):
            if cid == exclude_char_id:
                continue
            sess = member.session
            if sess and getattr(sess, 'transport', None):
                try:
                    await sess.transport.send_event(ev, note=note)
                except Exception as e:
                    logger.debug("Failed party broadcast to char %d: %s", cid, e)


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
