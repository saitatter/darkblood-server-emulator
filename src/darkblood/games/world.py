"""Multi-client Game World Manager.

Coordinates town square channels, instanced dungeons, player visibility
broadcasts (Opcode 5096 UpdateCharInfoNot), and direct player-to-player
interactions (chat whispers, 1v1 duels, party invites, trade sessions).
"""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from darkblood.core.serialization.jser import event
from darkblood.games.entities.character import Character

logger = logging.getLogger(__name__)


@dataclass
class WorldPlayer:
    """Connected character in the active game world."""
    session: any
    char_id: int
    char_data: dict
    square_id: int = 1
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    angle: float = 0.0


class GameWorldManager:
    """Central singleton managing active world instances and player presence."""

    _instance = None

    def __init__(self):
        self.players: Dict[int, WorldPlayer] = {}  # char_id -> WorldPlayer
        self.squares: Dict[int, Set[int]] = {}     # square_id -> set of char_ids

    @classmethod
    def get(cls) -> 'GameWorldManager':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register_player(self, session, char_id: int, char_data: dict, square_id: int = 1) -> WorldPlayer:
        """Register a character entering the world."""
        # Clean up existing registration if reconnecting
        self.unregister_player(char_id)

        player = WorldPlayer(
            session=session,
            char_id=char_id,
            char_data=char_data,
            square_id=square_id
        )
        self.players[char_id] = player
        self.squares.setdefault(square_id, set()).add(char_id)
        return player

    def unregister_player(self, char_id: int):
        """Remove player on disconnect or return to character select."""
        player = self.players.pop(char_id, None)
        if player:
            square_players = self.squares.get(player.square_id, set())
            square_players.discard(char_id)

    def get_player(self, char_id: int) -> Optional[WorldPlayer]:
        return self.players.get(char_id)

    def get_players_in_square(self, square_id: int) -> List[WorldPlayer]:
        cids = self.squares.get(square_id, set())
        return [self.players[cid] for cid in cids if cid in self.players]

    async def broadcast_to_square(self, square_id: int, ev: bytes, exclude_char_id: Optional[int] = None, note: str = ""):
        """Broadcast an event payload to all players in a square channel."""
        for cid in list(self.squares.get(square_id, set())):
            if cid == exclude_char_id:
                continue
            p = self.players.get(cid)
            if p and p.session and getattr(p.session, 'transport', None):
                try:
                    await p.session.transport.send_event(ev, note=note)
                except Exception as e:
                    logger.debug("Failed broadcast to char %d: %s", cid, e)

    async def broadcast_player_spawn(self, new_player: WorldPlayer):
        """Broadcast Opcode 5096 (eERC_UPDATE_CHAR_INFO_NOT) for mutual player visibility.

        Sends the new player's visual model (struct 0x00A52630) to all players in
        the same square, and delivers existing players' models to the new player.
        """
        from darkblood.games.handlers.frontend import build_char_details
        new_char = Character.from_dict(new_player.char_data)
        new_details = build_char_details(new_char)
        spawn_ev = event(5096, b'\x1e' + new_details)

        # Notify others in square of newcomer
        await self.broadcast_to_square(
            new_player.square_id,
            spawn_ev,
            exclude_char_id=new_player.char_id,
            note=f"spawn player {new_char.name} ({new_player.char_id}) to square"
        )

        # Send existing players in square to newcomer
        for cid in list(self.squares.get(new_player.square_id, set())):
            if cid == new_player.char_id:
                continue
            existing = self.players.get(cid)
            if existing:
                c = Character.from_dict(existing.char_data)
                details = build_char_details(c)
                try:
                    await new_player.session.transport.send_event(
                        event(5096, b'\x1e' + details),
                        note=f"spawn existing player {c.name} ({cid}) for newcomer"
                    )
                except Exception as e:
                    logger.debug("Failed sending player %d to newcomer: %s", cid, e)
