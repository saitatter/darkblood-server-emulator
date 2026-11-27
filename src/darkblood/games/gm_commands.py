"""Shared GM command mutations used by both in-game GmHandlers and the launcher GM bridge."""
from __future__ import annotations

import time
from typing import Callable, List, Optional, Tuple

from darkblood.core.hashing import jhash
from darkblood.games.entities.character import mark_base_count
from darkblood.games.entities.items import EQUIPPED, Item, UPDATE_OWNER
from darkblood.games.game_data import client_dict
from darkblood.games.network.messages.skills import DualSkillActiveNot
from darkblood.games.network.messages.system import StressChangedNot
from darkblood.games.progression import (
    MAX_LEVEL,
    add_ap,
    advance_level,
    set_stress,
    stress_changed_not,
    total_ap,
)
from darkblood.player_management.characters import add_reward_items, gold_of

_RUNE_CODES = tuple(
    [f'MMrk{i:03d}' for i in range(181)]
    + ['IAMk1R190', 'IRor1R278', 'IRor1R325', 'IRpr1R277', 'IRpr1R324']
)


def apply_level_up(char: dict, target_level: int) -> Tuple[int, Optional[int]]:
    """Set character level (1..MAX_LEVEL) and unlock Rune Slate at Lv 30+.

    Returns ``(clamped_level, mark_base_cnt_or_none)``.
    """
    target = max(1, min(int(target_level), MAX_LEVEL))
    advance_level(char, target, exp=0)
    mark_base: Optional[int] = None
    if target >= 30:
        mark_base = max(int(char.get('mark_base_cnt', 0)), mark_base_count(target))
        char['mark_active'] = True
        char['mark_base_cnt'] = mark_base
    return target, mark_base


def apply_ar_delta(char: dict, delta: int) -> int:
    """Adjust character AR (gold) by delta, clamped at 0."""
    cur_ar = max(0, gold_of(char) + int(delta))
    char['gold'] = cur_ar
    return cur_ar


def apply_ap_delta(char: dict, delta: int) -> Tuple[int, int]:
    """Add AP to character and return ``(current_sp, total_ap)``."""
    add_ap(char, int(delta))
    return int(char.get('sp', 0)), int(char.get('total_ap', 0))


def apply_rebirth_coins_delta(char: dict, delta: int) -> int:
    """Adjust rebirth coins by delta, clamped at 0."""
    total = max(0, int(char.get('rebirth_coins', 3)) + int(delta))
    char['rebirth_coins'] = total
    return total


def apply_stress(
    char: dict,
    daily: int,
    pcbang: Optional[int] = None,
    weekly: Optional[int] = None,
) -> StressChangedNot:
    """Set character stress values (clamped 0..330) and return the wire notice."""
    s_daily = max(0, min(330, int(daily)))
    s_pcb = max(0, min(330, int(pcbang))) if pcbang is not None else int(char.get('stress_pcb', 0))
    s_week = max(0, min(330, int(weekly))) if weekly is not None else int(char.get('stress_week', 0))
    set_stress(char, s_daily, s_pcb, s_week)
    return stress_changed_not(char)


def resolve_item_code_by_hash(item_id: int) -> Optional[str]:
    """Resolve a JHash item ID back to its item code string."""
    target = item_id & 0xFFFFFFFF
    for table in (client_dict.item_int_fields(), client_dict.item_durabilities()):
        for code in table:
            if jhash(code) == target:
                return code
    for entries in client_dict.store_items().values():
        for code, _ in entries:
            if jhash(code) == target:
                return code
    for code in _RUNE_CODES:
        if jhash(code) == target:
            return code
    return None


def apply_item_call(char: dict, code: str, count: int = 1, owner: int = UPDATE_OWNER) -> List[Item]:
    """Grant ``code x count`` to ``char`` and return wire ``Item`` objects."""
    added = add_reward_items(char, [(code, max(1, int(count)))])
    return [Item(owner=owner, **entry) for entry in added]


def apply_clear_bag(char: dict) -> List[Item]:
    """Delete all non-equipped items from ``char`` and return tombstone ``Item``s."""
    deleted: List[Item] = []
    kept = []
    for it in char.get('items', []):
        if it.get('container') == EQUIPPED:
            kept.append(it)
        else:
            deleted.append(Item(
                code=it.get('code', ''),
                uid=it.get('uid', 0),
                owner=-1,
                container=it.get('container', 3),
                slot=it.get('slot', 0),
                count=0,
            ))
    char['items'] = kept
    return deleted


def apply_equip_upgrade(
    char: dict,
    target_level: int,
    slot_filter: Callable[[dict], bool],
) -> List[Item]:
    """Set upgrade level (0..20) on matching equipped items and return wire updates."""
    lv = max(0, min(20, int(target_level)))
    changed: List[Item] = []
    for it in char.get('items', []):
        if slot_filter(it):
            it['upgrade'] = lv
            changed.append(Item(owner=UPDATE_OWNER, **it))
    return changed


def apply_equip_durability(char: dict, value: int) -> List[Item]:
    """Set durability on all equipped items and return wire updates."""
    val = max(0, int(value))
    changed: List[Item] = []
    for it in char.get('items', []):
        if it.get('container') == EQUIPPED:
            it['durability'] = val
            changed.append(Item(owner=UPDATE_OWNER, **it))
    return changed


def apply_depot_expand(char: dict, days: int = 30) -> None:
    """Extend personal depot rental timer to at least ``days`` days."""
    from darkblood.games.progression import extend_depot_rental

    extend_depot_rental(char, 0, int(days) * 86400, minimum=True)


def apply_learn_skill(char: dict, skill_id: int, skill_level: int) -> Tuple[int, int]:
    """Set a skill's learned level (minimum 1) and return ``(skill_id, level)``."""
    sidx = int(skill_id)
    slv = max(1, int(skill_level))
    char.setdefault('skills', {})[str(sidx)] = slv
    return sidx, slv


def apply_skill_reset(char: dict) -> int:
    """Clear learned skills, refund total AP, and return refunded SP."""
    char['skills'] = {}
    sp = total_ap(char)
    char['sp'] = sp
    return sp


def apply_quest_reset(char: dict) -> None:
    """Clear all active quests on a character."""
    char['quests_active'] = {}
    char['quests'] = []


def apply_dual_skill(char: dict, add_days: int = 30, now: Optional[int] = None) -> DualSkillActiveNot:
    """Extend Dual Skill expiration by ``add_days`` and return the activation notice."""
    days = max(1, int(add_days))
    ts = int(time.time()) if now is None else int(now)
    base_exp = max(ts, int(char.get('dual_skill_expire', 0)))
    char['dual_skill_expire'] = base_exp + days * 86400
    remain_sec = char['dual_skill_expire'] - ts
    cur_idx = int(char.get('dual_skill_index', 0))
    return DualSkillActiveNot(
        extend_time=remain_sec,
        add_day=days,
        cur_dual_skill_index=cur_idx,
        item_id=jhash('IDSk1Cash269'),
    )
