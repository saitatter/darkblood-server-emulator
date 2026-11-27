"""Party subsystem domain entities and PartyManager singleton."""
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


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
            is_leader=True,
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

        existing_target_party = self.get_player_party(target_id)
        if existing_target_party is not None:
            # A 1-member party is only an unaccepted outgoing invite, not an
            # active multi-player party; dissolve it so the player can be invited.
            if len(existing_target_party.members) <= 1:
                self.leave_party(target_id)
            else:
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
        existing_target_party = self.get_player_party(target_id)
        if existing_target_party is not None:
            if len(existing_target_party.members) <= 1 and existing_target_party is not party:
                self.leave_party(target_id)
            else:
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
            is_leader=False,
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
                except (ConnectionError, OSError) as e:
                    logger.debug("Failed party broadcast to char %d: %s", cid, e)
