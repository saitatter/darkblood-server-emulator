"""Counter achievements (DictAchieve Type 0) driven by 2446 division reports.

The client reports per-run division amounts after a dungeon (2446). Each
character keeps the summed total and the best single report per division;
an achievement completes when the relevant value reaches its GoalAmount
(summed when Accumulate is 1, best single report otherwise).
"""
import time

from darkblood.core.hashing import jhash
from darkblood.games.game_data.client_dict import achievements


def apply_division_report(char, amounts, now=None):
    """Merge a 2446 report into the character; return newly completed ids."""
    totals = char.setdefault('achieve_divisions', {})
    best = char.setdefault('achieve_best', {})
    for division, amount in amounts.items():
        key = str(division)
        totals[key] = totals.get(key, 0) + amount
        best[key] = max(best.get(key, 0), amount)
    done = char.setdefault('achievements', {})
    stamp = int(now if now is not None else time.time())
    completed = []
    for achieve_id, division, goal, accumulate in achievements():
        if achieve_id in done:
            continue
        source = totals if accumulate else best
        if source.get(str(division), 0) >= goal:
            done[achieve_id] = stamp
            completed.append(achieve_id)
    return completed


def division_totals(char):
    return {int(k): v for k, v in char.get('achieve_divisions', {}).items()}


def completed_entries(char, ids=None):
    """(hash, completed_at) for the character's completed achievements."""
    done = char.get('achievements', {})
    return [(jhash(achieve_id), done[achieve_id]) for achieve_id in (ids if ids is not None else done)]
