"""Character level, ability point, and stress (fatigue) accounting."""
import time
from darkblood.games.game_data.client_dict import char_level_stat, level_up_ap, skill_learn_cost
from darkblood.games.network.messages import (
    ChangeDungeonPenaltyNot,
    LevelUpNot,
    StressChangedNot,
)


MAX_LEVEL = 60
MAX_AP = 0x7fffffff
MAX_STRESS = 330
STRESS_PER_DUNGEON_ROOM = 2
STRESS_RECOVERY_INTERVAL_SEC = 60

# DungeonPenalty.lua (DictDunPenalty:LoadLeavePenalty / LoadWipeoutPenalty):
# Count 1..3 -> 60% / 70% / 80% HP/MP reduction; 5 recovery steps over 600s.
PENALTY_TOTAL_SEC = 600
PENALTY_STEP_THRESHOLDS = (40, 90, 210, 450, 600)
MAX_PENALTY_COUNT = 3


def ap_at_level(level):
    return level_up_ap().get(level, 3 if level < 20 else 4)


def total_ap(char):
    if 'total_ap' in char:
        return char['total_ap']
    spent = sum(skill_learn_cost(int(index), 0, level)[0]
                for index, level in char.get('skills', {}).items())
    earned = sum(ap_at_level(level) for level in range(2, char.get('level', 1) + 1))
    return min(MAX_AP, max(earned, char.get('sp', 0) + spent))


def add_ap(char, amount):
    total = total_ap(char)
    remaining = char.get('sp', 0) + amount
    new_total = total + amount
    if not (0 <= remaining <= new_total <= MAX_AP):
        raise ValueError('AP balance out of range')
    char.update(sp=remaining, total_ap=new_total)


def advance_level(char, level, exp):
    total = total_ap(char)
    gain = sum(ap_at_level(n) for n in range(char.get('level', 1) + 1, level + 1))
    stats = char_level_stat(int(char.get('char_class', 0)), level)
    char.update(level=level, exp=exp, max_hp=stats['hp'], max_mp=stats['mp'],
                sp=min(MAX_AP, char.get('sp', 0) + gain), total_ap=min(MAX_AP, total + gain))


def level_up_not(char):
    """5087 for a character dict; both AP array entries hold the remaining AP, as in 2007."""
    return LevelUpNot(ap_slots=[char['sp'], char['sp']], char_uid=char['id'], new_level=char['level'],
                      exp=char['exp'], total_ap=char['total_ap'])


def _today_str(now=None):
    return time.strftime('%Y-%m-%d', time.localtime(time.time() if now is None else now))


def refresh_stress(char, now=None):
    """Apply daily midnight reset and passive town/offline recovery (1 per minute).

    Returns True if the character's stress state changed.
    """
    now = time.time() if now is None else float(now)
    today = _today_str(now)
    changed = False

    prev_date = char.get('stress_date')
    if prev_date and prev_date != today:
        if char.get('stress', 0) != 0 or char.get('today_cronos_stress', 0) != 0:
            changed = True
        char['stress'] = 0
        char['today_cronos_stress'] = 0
        char['stress_date'] = today
        char['stress_updated_at'] = now
        return changed

    if not prev_date:
        char['stress_date'] = today

    stress = max(0, min(MAX_STRESS, int(char.get('stress', 0))))
    last_ts = char.get('stress_updated_at')
    if last_ts is None:
        char['stress_updated_at'] = now
        return changed

    if stress > 0 and now > last_ts:
        ticks = int((now - float(last_ts)) // STRESS_RECOVERY_INTERVAL_SEC)
        if ticks > 0:
            recovered = min(stress, ticks)
            char['stress'] = stress - recovered
            char['stress_updated_at'] = float(last_ts) + ticks * STRESS_RECOVERY_INTERVAL_SEC
            changed = True
    elif stress == 0:
        char['stress_updated_at'] = now
    return changed


def consume_stress(char, amount=STRESS_PER_DUNGEON_ROOM, now=None):
    """Increase character stress (fatigue) on dungeon entry / room transition.

    Clamped to [0, MAX_STRESS]. Returns True if stress changed.
    """
    now = time.time() if now is None else float(now)
    refresh_stress(char, now=now)
    old = max(0, min(MAX_STRESS, int(char.get('stress', 0))))
    new = max(0, min(MAX_STRESS, old + int(amount)))
    char['stress'] = new
    char['stress_date'] = _today_str(now)
    char['stress_updated_at'] = now
    if new > old:
        char['today_cronos_stress'] = int(char.get('today_cronos_stress', 0)) + (new - old)
    return new != old


def set_stress(char, stress, stress_pcb=None, stress_week=None, now=None):
    """Set stress fields directly (used by GM cheat 2130 and recovery items)."""
    now = time.time() if now is None else float(now)
    char['stress'] = max(0, min(MAX_STRESS, int(stress)))
    if stress_pcb is not None:
        char['stress_pcb'] = max(0, min(MAX_STRESS, int(stress_pcb)))
    if stress_week is not None:
        char['stress_week'] = max(0, min(MAX_STRESS, int(stress_week)))
    char['stress_date'] = _today_str(now)
    char['stress_updated_at'] = now


def stress_changed_not(char):
    """Build 2023 StressChangedNot (0x00789E00) for a character dict."""
    return StressChangedNot(
        stress=max(0, min(MAX_STRESS, int(char.get('stress', 0)))),
        stress_pcb=max(0, min(MAX_STRESS, int(char.get('stress_pcb', 0)))),
        stress_week=max(0, min(MAX_STRESS, int(char.get('stress_week', 0)))),
        today_cronos_stress=int(char.get('today_cronos_stress', 0)),
    )


def _penalty_keys(penalty_type: int):
    prefix = 'wipeout_penalty' if penalty_type else 'leave_penalty'
    return f'{prefix}_count', f'{prefix}_started_at', f'{prefix}_step'


def penalty_step_for_elapsed(elapsed: float) -> int:
    """Map elapsed seconds since penalty start to DungeonPenalty.lua step index (0..4) or -1 if expired."""
    if elapsed < 0:
        return 0
    for idx, threshold in enumerate(PENALTY_STEP_THRESHOLDS):
        if elapsed < threshold:
            return idx
    return -1


def apply_dungeon_penalty(char, penalty_type: int = 0, now=None):
    """Apply or escalate a dungeon leave/wipeout penalty (Count 1..3) and return 2085 notice.

    Client On_eEGS_CHANGE_DUNGEON_PENALTY_NOT (0x0078FA70) passes duration to FUN_00a8f090:
      end_ms = (total_sec - duration) * 1000 + now_ms
    So duration is ELAPSED seconds (0 on initial application -> full 600s countdown).
    """
    now = time.time() if now is None else float(now)
    k_cnt, k_start, k_step = _penalty_keys(penalty_type)
    prev_start = float(char.get(k_start, 0) or 0)
    prev_cnt = int(char.get(k_cnt, 0) or 0)
    if prev_cnt > 0 and prev_start > 0 and (now - prev_start) < PENALTY_TOTAL_SEC:
        cnt = min(MAX_PENALTY_COUNT, prev_cnt + 1)
    else:
        cnt = 1
    char[k_cnt] = cnt
    char[k_start] = now
    char[k_step] = 0
    return ChangeDungeonPenaltyNot(
        in_dungeon=True,
        is_penalty=bool(penalty_type),
        penalty_level=cnt,
        penalty_id=0,
        duration=0,
    )


def refresh_dungeon_penalty(char, penalty_type: int = 0, now=None):
    """Advance or expire a persisted dungeon penalty based on wall-clock elapsed time.

    Returns (changed: bool, notice: ChangeDungeonPenaltyNot | None).
    """
    now = time.time() if now is None else float(now)
    k_cnt, k_start, k_step = _penalty_keys(penalty_type)
    cnt = int(char.get(k_cnt, 0) or 0)
    started_at = float(char.get(k_start, 0) or 0)
    if cnt <= 0 or started_at <= 0:
        return False, None

    elapsed = max(0.0, now - started_at)
    new_step = penalty_step_for_elapsed(elapsed)
    old_step = int(char.get(k_step, 0))

    if new_step < 0:
        char[k_cnt] = 0
        char[k_start] = 0
        char[k_step] = -1
        return True, ChangeDungeonPenaltyNot(
            in_dungeon=False,
            is_penalty=bool(penalty_type),
            penalty_level=0,
            penalty_id=-1,
            duration=-1,
        )

    if new_step != old_step:
        char[k_step] = new_step
        return True, ChangeDungeonPenaltyNot(
            in_dungeon=False,
            is_penalty=bool(penalty_type),
            penalty_level=cnt,
            penalty_id=new_step,
            duration=int(elapsed),
        )
    return False, None


def active_penalty_notice(char, penalty_type: int = 0, now=None):
    """Return a silent 2085 notice to restore an active penalty on character login, or None."""
    now = time.time() if now is None else float(now)
    refresh_dungeon_penalty(char, penalty_type=penalty_type, now=now)
    k_cnt, k_start, k_step = _penalty_keys(penalty_type)
    cnt = int(char.get(k_cnt, 0) or 0)
    started_at = float(char.get(k_start, 0) or 0)
    if cnt <= 0 or started_at <= 0:
        return None
    elapsed = max(0.0, now - started_at)
    step = penalty_step_for_elapsed(elapsed)
    if step < 0:
        return None
    char[k_step] = step
    return ChangeDungeonPenaltyNot(
        in_dungeon=False,
        is_penalty=bool(penalty_type),
        penalty_level=cnt,
        penalty_id=step,
        duration=int(elapsed),
    )


def clear_dungeon_penalty(char, penalty_type: int = 0):
    """Immediately clear an active dungeon penalty (e.g. via 2086 BuyLifeWater)."""
    k_cnt, k_start, k_step = _penalty_keys(penalty_type)
    char[k_cnt] = 0
    char[k_start] = 0
    char[k_step] = -1
    return ChangeDungeonPenaltyNot(
        in_dungeon=False,
        is_penalty=bool(penalty_type),
        penalty_level=0,
        penalty_id=-1,
        duration=-1,
    )


def life_water_cost(char, penalty_type: int = 0, now=None) -> int:
    """Compute AR cost to clear an active dungeon penalty from DictDunPenalty:LoadLifeWater."""
    from darkblood.games.game_data.client_dict import life_water_prices
    now = time.time() if now is None else float(now)
    refresh_dungeon_penalty(char, penalty_type=penalty_type, now=now)
    k_cnt, k_start, _ = _penalty_keys(penalty_type)
    cnt = int(char.get(k_cnt, 0) or 0)
    started_at = float(char.get(k_start, 0) or 0)
    if cnt <= 0 or started_at <= 0:
        return 0
    step = penalty_step_for_elapsed(max(0.0, now - started_at))
    if step < 0:
        return 0
    lv = max(1, min(MAX_LEVEL, int(char.get('level', 1))))
    steps = life_water_prices().get(lv)
    if steps and step < len(steps):
        return int(steps[step])
    return max(100, lv * 500 * (5 - step) // 5)


def refresh_depot_timers(char, now=None) -> bool:
    """Update depot_extend_remain from persisted depot_extend_expires timestamps."""
    now = time.time() if now is None else float(now)
    expires = char.get('depot_extend_expires')
    if not isinstance(expires, list):
        return False
    remain = list(char.get('depot_extend_remain', [0, 0]))
    while len(remain) < len(expires):
        remain.append(0)
    changed = False
    for idx, exp_ts in enumerate(expires):
        new_rem = max(0, int(float(exp_ts) - now)) if exp_ts else 0
        if remain[idx] != new_rem:
            remain[idx] = new_rem
            changed = True
    if changed:
        char['depot_extend_remain'] = remain
    return changed


CITADEL_WEEKLY_INIT = 3
CITADEL_MAX_PLAY_COUNT = 7


def refresh_dungeon_entry_limits(char, now=None) -> bool:
    """Refresh daily dungeon enter/clear counts and Fortress (Citadel) challenge count.

    UI_3408: "Charged a challenge opportunity daily. Challenge opportunity is initialized
    at every Monday. Consumes each time to enter Dungeons in the Fortress."
    """
    import datetime
    now = time.time() if now is None else float(now)
    today = datetime.datetime.fromtimestamp(now).date()
    today_str = today.isoformat()
    iso = today.isocalendar()
    week_str = f'{iso[0]}-W{iso[1]:02d}'
    changed = False

    if char.get('dun_enter_day') != today_str:
        char['dun_enter_day'] = today_str
        char['daily_dun_enter_counts'] = {}
        char['daily_dun_clear_counts'] = {}
        changed = True

    previous_week = char.get('citadel_week')
    if previous_week != week_str or 'citadel_play_count' not in char:
        missed_days = today.weekday() if previous_week and 'citadel_play_count' in char else 0
        char['citadel_week'] = week_str
        char['citadel_last_day'] = today_str
        char['citadel_play_count'] = min(CITADEL_MAX_PLAY_COUNT, CITADEL_WEEKLY_INIT + missed_days)
        changed = True
    elif char.get('citadel_last_day') != today_str:
        try:
            last_day = datetime.date.fromisoformat(char.get('citadel_last_day', ''))
        except (TypeError, ValueError):
            last_day = today - datetime.timedelta(days=1)
        elapsed_days = (today - last_day).days
        if elapsed_days > 0:
            char['citadel_last_day'] = today_str
            cur = int(char['citadel_play_count'])
            char['citadel_play_count'] = min(CITADEL_MAX_PLAY_COUNT, cur + elapsed_days)
            changed = True

    return changed


def refresh_character_timers(char, now=None) -> bool:
    """Refresh all persisted wall-clock timers on a character (stress, penalties, depot, dungeon limits)."""
    now = time.time() if now is None else float(now)
    changed = False
    if refresh_stress(char, now=now):
        changed = True
    for ptype in (0, 1):
        p_changed, _ = refresh_dungeon_penalty(char, penalty_type=ptype, now=now)
        if p_changed:
            changed = True
    if refresh_depot_timers(char, now=now):
        changed = True
    if refresh_dungeon_entry_limits(char, now=now):
        changed = True
    return changed
