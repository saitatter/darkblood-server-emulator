"""Character level stats, level-up AP, skill learning costs and achievements."""
import re
from functools import lru_cache
from darkblood.games.game_data.loader import (
    bundled_asset,
    ASSETS_DIR, tsv_rows, _env_override, _section, _top_entries, data_root,
)


CLASS_SECTION_MAP = {
    0: 'LoadStatWarrior',
    1: 'LoadStatKnight',
    2: 'LoadStatHunter',
    3: 'LoadStatMage',
    4: 'LoadStatThief',
    5: 'LoadStatFighter',
    6: 'LoadStatWHunter',
}


@lru_cache(maxsize=None)
def char_level_stats():
    """Returns mapping (char_class, level) -> {'upexp', 'hp', 'mp'}."""
    override = _env_override('charstat.lua')
    tsv = bundled_asset('char_stats.tsv', override)
    if tsv:
        out = {}
        for parts in tsv_rows(tsv):
            if len(parts) >= 5:
                cls_id, lv, hp, mp, upexp = parts[:5]
                out[(int(cls_id), int(lv))] = {
                    'hp': int(float(hp)),
                    'mp': int(float(mp)),
                    'upexp': int(float(upexp)),
                }
        return out

    path = override or (data_root() / 'charstat.lua')
    out = {}
    if not path.exists():
        return out

    text = path.read_text(encoding='utf-8', errors='replace')
    for cls_id, sec_name in CLASS_SECTION_MAP.items():
        sec_start = text.find(sec_name)
        if sec_start == -1:
            continue
        sec_end = text.find('assert(DictChar:', sec_start + 1)
        sec_text = text[sec_start:sec_end] if sec_end != -1 else text[sec_start:]
        for block in re.split(r'\{\s*\n', sec_text):
            m_lvl = re.search(r'Level = (\d+)', block)
            m_exp = re.search(r'UPExp = ([\d.]+)', block)
            m_hp = re.search(r'HealthPoint = ([\d.]+)', block)
            m_mp = re.search(r'ManaPoint = ([\d.]+)', block)
            if m_lvl and m_exp:
                lvl = int(m_lvl.group(1))
                out[(cls_id, lvl)] = {
                    'upexp': int(float(m_exp.group(1))),
                    'hp': int(float(m_hp.group(1))) if m_hp else 100,
                    'mp': int(float(m_mp.group(1))) if m_mp else 100,
                }
    return out


def char_level_stat(char_class: int, level: int) -> dict:
    """Returns stat dictionary for (char_class, level) with fallback formula."""
    stats = char_level_stats()
    res = stats.get((char_class, level)) or stats.get((char_class & 0x0F, level))
    if res:
        return res
    return {
        'upexp': int(144 * (1.5 ** (level - 1))),
        'hp': 200 + level * 150,
        'mp': 50 + level * 20,
    }


@lru_cache(maxsize=1)
def level_up_ap():
    """AP awarded at each level in the client's DictChar:LoadLevelUp table."""
    override = _env_override('levelup.lua')
    tsv = bundled_asset('levelup_ap.tsv', override)
    if tsv:
        out = {}
        for parts in tsv_rows(tsv):
            if len(parts) >= 2:
                out[int(parts[0])] = int(parts[1])
        return out

    path = override or (data_root() / 'levelup.lua')
    if not path.is_file():
        return {}
    return {int(level): int(ap) for ap, level in re.findall(
        r'\{\s*GainAP\s*=\s*(\d+)\s*,\s*Level\s*=\s*(\d+)\s*\}',
        path.read_text(encoding='utf-8', errors='replace'))}


@lru_cache(maxsize=None)
def skill_costs():
    """{(skill index, level): (DemandPoint SP, DemandAr)} from skill and making tables."""
    override = _env_override('skill.lua')
    tsv = bundled_asset('skills.tsv', override)
    if tsv:
        out = {}
        for parts in tsv_rows(tsv):
            if len(parts) >= 4:
                out[(int(parts[0]), int(parts[1]))] = (int(parts[2]), int(parts[3]))
        return out

    root = override.parent if override else data_root()
    out = {}
    for filename in ('skill.lua', 'making.lua', 'gathering.lua', 'fishing.lua'):
        path = override if (filename == 'skill.lua' and override) else (root / filename)
        if not path.exists():
            continue
        text = path.read_text(encoding='utf-8', errors='replace')
        for blk in re.findall(r'assert\(DictSkill:LoadSkill\(\{(.*?)\n\}\), "DictSkill:LoadSkill"\)', text, re.S):
            for entry in re.split(r'\n  \{\n', '\n' + blk)[1:]:
                idx = re.search(r'(?:^|\n)    NameIndex = "?(\d+)"?,?', entry)
                lv = re.search(r'(?:^|\n)    Lv = (\d+)', entry)
                if not (idx and lv):
                    continue
                sp = re.search(r'(?:^|\n)    DemandPoint = (\d+)', entry)
                ar = re.search(r'(?:^|\n)    DemandAr = (\d+)', entry)
                out[(int(idx.group(1)), int(lv.group(1)))] = (
                    int(sp.group(1)) if sp else 0,
                    int(ar.group(1)) if ar else 0,
                )
    return out


def skill_learn_cost(skill_index: int, current: int, target: int):
    """(SP, AR) to raise a skill from level current to target."""
    costs = skill_costs()
    sp = ar = 0
    for level in range(current + 1, target + 1):
        s, a = costs.get((skill_index, level), (0, 0))
        sp, ar = sp + s, ar + a
    return sp, ar


@lru_cache(maxsize=None)
def achievement_table():
    """Every DictAchieve:LoadAchieveInfo entry: [(achieve_id, type, division, goal, accumulate)].

    goal is 0 for entries without GoalAmount (group types 2/3 use
    GroupCondition and are completed through the client's 2444 report).
    """
    override = _env_override('achieve.lua')
    tsv = bundled_asset('achievements.tsv', override)
    if tsv:
        out = []
        for parts in tsv_rows(tsv):
            if len(parts) >= 5:
                out.append((parts[0], int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4])))
        return out
    path = override or (data_root() / 'achieve.lua')
    if not path.exists():
        return []
    section = _section(path.read_text(encoding='utf-8', errors='replace'), 'DictAchieve:LoadAchieveInfo')
    out = []
    for entry in _top_entries(section):
        fields = dict(re.findall(r'^    (\w+) = "?([^",{]*)"?,?$', entry, re.M))
        if 'AchieveID' not in fields:
            continue
        out.append((fields['AchieveID'], int(fields.get('Type') or 0), int(fields.get('AchieveDivision') or 0),
                    int(float(fields.get('GoalAmount') or 0)), int(fields.get('Accumulate') or 0)))
    return out


def achievements():
    """Counter achievements: [(achieve_id, division, goal, accumulate)] for Type 0 with a goal.

    A Type 0 achievement completes when its AchieveDivision counter reaches
    GoalAmount: summed over runs when Accumulate is 1, within one report when 0.
    """
    return [(a, d, g, acc) for a, kind, d, g, acc in achievement_table() if kind == 0 and g > 0]

