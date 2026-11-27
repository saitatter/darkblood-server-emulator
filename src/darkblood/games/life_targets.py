"""Server-wide state of the town GTargets (fishing holes, gathering nodes, crafting stations).

The client hides a gathering node (DictTarget AlwaysShow=0) until the server marks
it active (5125 on town load, 5126 afterwards): JGTarget::Update 0x007F8CD0 ->
0x007F83D0. A type-0 (gathering) target can only be used in state 0, i.e. active
(0x007F78C0, 0x007F7700). Fishing holes and crafting stations are always active.

Gathering nodes follow their DictTarget entry: EnableRate is read as the share of
nodes of one kind that are active at a time, RegenSecond as the delay before a
depleted node can return, and RegenProb as the chance per regeneration check that
an eligible node returns. These readings of the three fields are assumptions;
the server-side algorithm of the original service is not known.

The launcher option gather_respawn_time (options.NUMERIC_OPTIONS) multiplies
RegenSecond, read live on every check.
"""
import math
import random
import time

from darkblood.core import options
from darkblood.core.hashing import jhash
from darkblood.games.game_data.life_skills import FISHING, GATHERING, MAKING, town_gtargets
from darkblood.games.network.messages import TargetState


def regen_seconds(kind) -> float:
    """RegenSecond of a DictTarget entry scaled by the gather_respawn_time option."""
    return kind['regen_second'] * options.number('gather_respawn_time')


def square_of_layer(layer_id: int):
    """Town square name of a layer net id (high dword = jhash(SquareID)), or None."""
    high = (int(layer_id) >> 32) & 0xFFFFFFFF
    for square in town_gtargets():
        if jhash(square) & 0xFFFFFFFF == high:
            return square
    return None


class LifeTargetState:
    """Active flags of every town GTarget, per square, with gathering regeneration."""

    def __init__(self, rng=None):
        self.rng = rng or random.Random()
        self._targets = {}      # square -> {uid: DictTarget entry}
        self._active = {}       # square -> {uid: bool}
        self._depleted = {}     # (square, uid) -> time the node was gathered
        self._last_check = {}   # (square, target id) -> time of the last regeneration check

    def _square(self, square, now):
        if square not in self._active:
            targets = dict(town_gtargets().get(square, ()))
            self._targets[square] = targets
            active = {uid: kind['kind'] in (FISHING, MAKING) for uid, kind in targets.items()}
            for target_id, uids in self._groups(targets).items():
                rate = targets[uids[0]]['enable_rate']
                for uid in self.rng.sample(uids, self._quota(rate, len(uids))):
                    active[uid] = True
                self._last_check[(square, target_id)] = now
            self._active[square] = active
        return self._active[square]

    @staticmethod
    def _groups(targets):
        groups = {}
        for uid, kind in sorted(targets.items()):
            if kind['kind'] == GATHERING:
                groups.setdefault(kind['id'], []).append(uid)
        return groups

    @staticmethod
    def _quota(rate, count):
        return min(count, max(1, math.ceil(rate * count))) if count else 0

    def states(self, square, now=None):
        """TargetState list for 5125: every target of the square with its active flag."""
        active = self._square(square, time.time() if now is None else now)
        return [TargetState(target_uid=uid, is_active=flag, is_jackpot=False) for uid, flag in active.items()]

    def target(self, square, uid):
        """DictTarget entry of a map object, or None."""
        self._square(square, time.time())
        return self._targets.get(square, {}).get(int(uid))

    def is_active(self, square, uid):
        return bool(self._square(square, time.time()).get(int(uid)))

    def deplete(self, square, uid, now=None):
        """Mark a gathered node inactive; returns its TargetState, or None if it was not active."""
        now = time.time() if now is None else now
        active = self._square(square, now)
        uid = int(uid)
        if not active.get(uid) or self._targets[square][uid]['kind'] != GATHERING:
            return None
        active[uid] = False
        self._depleted[(square, uid)] = now
        return TargetState(target_uid=uid, is_active=False, is_jackpot=False)

    def regenerate(self, now=None):
        """Return depleted/inactive nodes whose check is due: {square: [TargetState]} of the changes."""
        now = time.time() if now is None else now
        changes = {}
        for square, active in self._active.items():
            targets = self._targets[square]
            for target_id, uids in self._groups(targets).items():
                key = (square, target_id)
                kind = targets[uids[0]]
                delay = regen_seconds(kind)
                # Measured from the last check, so a changed multiplier applies at once.
                if now - self._last_check.get(key, float('-inf')) < max(1.0, delay):
                    continue
                self._last_check[key] = now
                missing = self._quota(kind['enable_rate'], len(uids)) - sum(active[u] for u in uids)
                eligible = [u for u in uids if not active[u]
                            and now - self._depleted.get((square, u), 0) >= delay]
                self.rng.shuffle(eligible)
                for uid in eligible:
                    if missing <= 0:
                        break
                    if self.rng.random() < kind['regen_prob']:
                        active[uid] = True
                        self._depleted.pop((square, uid), None)
                        missing -= 1
                        changes.setdefault(square, []).append(
                            TargetState(target_uid=uid, is_active=True, is_jackpot=False))
        return changes
