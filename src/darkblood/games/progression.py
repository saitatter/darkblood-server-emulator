"""Character level, ability point, and stress (fatigue) accounting."""
import time
from darkblood.games.game_data.client_dict import char_level_stat, level_up_ap, skill_learn_cost


MAX_LEVEL = 60
MAX_AP = 0x7fffffff
MAX_STRESS = 330
STRESS_PER_DUNGEON_ROOM = 2
STRESS_RECOVERY_INTERVAL_SEC = 60


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
    from darkblood.games.network.messages import LevelUpNot
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
    from darkblood.games.network.messages.system import StressChangedNot
    return StressChangedNot(
        stress=max(0, min(MAX_STRESS, int(char.get('stress', 0)))),
        stress_pcb=max(0, min(MAX_STRESS, int(char.get('stress_pcb', 0)))),
        stress_week=max(0, min(MAX_STRESS, int(char.get('stress_week', 0)))),
        today_cronos_stress=int(char.get('today_cronos_stress', 0)),
    )
