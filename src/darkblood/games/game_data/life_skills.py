"""Life-skill targets: fishing holes, gathering nodes and crafting stations.

Sources (client dict files):
- DictTarget:LoadFishing / LoadGathering / LoadMaking: the target kinds, keyed by
  (ResourceNum, ResourceIdx) as the town map objects reference them.
- DictKairo:LoadGathering: what a gathering node yields (ge000NN, sent in 2177).
- DictKairo:LoadFishing + DictRandomBox:LoadRandomBoxGroup (fishing.lua): the
  weighted catch groups of each fishing hole.
- DictSkill:LoadSkill (fishing.lua, gathering.lua): MaxProficiency per skill level.
- DictItem:LoadItem (fishing.lua) Type 45: fishing baits; AdjValue is the casting time
  reduction in seconds (the fishing page shows "Casting time reduced by N s").
- DictItem:LoadItem (fishing.lua) Type 46: caught fish that raise the fishing
  proficiency by AdjValue when used ("Increases the proficiency of the fisher by N").

The town map objects themselves come from assets/gtargets.tsv
(tools/client_data/extract_gtargets.py).
"""
import json
from functools import lru_cache

from darkblood.games.game_data.loader import (
    _env_override,
    bundled_asset,
    data_root,
    lua_table,
    lua_tables,
    tsv_rows,
)

FISHING = 'fishing'
GATHERING = 'gathering'
MAKING = 'making'
BAIT_ITEM_TYPE = 45
PROFICIENCY_ITEM_TYPE = 46
FISHING_PROFICIENCY = 9    # ProficiencyType of DictKairo:LoadFishing and the 9009 Fishing skill


def _read(name):
    path = _env_override(name) or (data_root() / name)
    return path.read_text(encoding='utf-8', errors='replace') if path.exists() else ''


def _from_lua() -> dict:
    fishing, gathering, making = _read('fishing.lua'), _read('gathering.lua'), _read('making.lua')
    targets = []
    for kind, text, loader in ((FISHING, fishing, 'DictTarget:LoadFishing'),
                               (GATHERING, gathering, 'DictTarget:LoadGathering'),
                               (MAKING, making, 'DictTarget:LoadMaking')):
        for t in lua_tables(text, loader):
            targets.append(dict(
                kind=kind, id=t['ID'], resource_num=int(t['ResourceNum']), resource_idx=int(t['ResourceIdx']),
                always_show=bool(t.get('AlwaysShow', 1)), demand_lv=int(t.get('DemandLv', 0)),
                req_skill=int(t.get('ReqSkillIdx', 0)), req_skill_lv=int(t.get('ReqSkillLv', 0)),
                req_proficiency=float(t.get('ReqProficiency', 0)), req_item=t.get('ReqItemID', ''),
                enable_rate=float(t.get('EnableRate', 1)), regen_second=int(t.get('RegenSecond', 0)),
                regen_prob=float(t.get('RegenProb', 1)),
            ))
    gathering_kairo = [dict(
        id=k['ID'], target=k['TargetID'], proficiency_type=int(k['ProficiencyType']),
        proficiency_up=float(k.get('SuccessProficiencyUp', 0)), jackpot_prob=float(k.get('AddProb', 0)),
        items=[[code, int(count), float(prob)] for code, count, prob in k.get('ItemIN', [])],
        jackpot_items=[[code, int(count), float(prob)] for code, count, prob in k.get('ItemAddIN', [])],
        req_items=list(k.get('ReqItem', [])),
    ) for k in lua_tables(gathering, 'DictKairo:LoadGathering')]
    fishing_kairo = [dict(
        id=k['ID'], target=k['TargetID'], proficiency_type=int(k['ProficiencyType']),
        max_time=int(k.get('MaxTime', 60)),
        groups=[[gid, float(prob)] for gid, prob in k.get('ItemGroup', [])],
    ) for k in lua_tables(fishing, 'DictKairo:LoadFishing')]
    fish_groups = {g['GroupID']: [[code, int(count), float(prob)] for code, count, prob in g.get('ResultItem', [])]
                   for g in lua_tables(fishing, 'DictRandomBox:LoadRandomBoxGroup')}
    all_skills = (lua_tables(fishing, 'DictSkill:LoadSkill') + lua_tables(gathering, 'DictSkill:LoadSkill')
                  + lua_tables(making, 'DictSkill:LoadSkill'))
    # Profession levels (Type "p": 9000-9009): proficiency cap and learning requirements.
    skills = [dict(skill=int(s['NameIndex']), level=int(s['Lv']), max_proficiency=float(s.get('MaxProficiency', 0)),
                   proficiency_type=int(s['ProficiencyType']), id=s.get('ID', ''),
                   demand_lv=int(s.get('DemandLv', 0)), demand_proficiency=float(s.get('DemandProficiency', 0)))
              for s in all_skills if 'ProficiencyType' in s]
    # Recipe skills (Type "m", e.g. 10032 "Wmake33"): learned with AR, need a profession level.
    recipes = [dict(skill=int(s['NameIndex']), level=int(s['Lv']), id=s.get('ID', ''),
                    demand_lv=int(s.get('DemandLv', 0)), demand_skill=list(s.get('DemandSkill', [])))
               for s in all_skills if s.get('Type') == 'm']
    # DictKairo:LoadMaking (9 sections): one crafting recipe each, sent as 2177/2496 by
    # JAppPageMakingKairo 0x00727140 (kairo +0xAC BuyPrice is checked against AR first).
    making_kairo = [dict(
        id=k['ID'], target=k.get('TargetID', ''), proficiency_type=int(k['ProficiencyType']),
        req_skill=int(k.get('ReqSkillNameIdx', 0)), req_skill_lv=int(k.get('ReqSkillLv', 0)),
        req_proficiency=float(k.get('ReqProficiency', 0)), buy_price=int(k.get('BuyPrice', 0)),
        success_rate=float(k.get('SuccessRate', 1)),
        success_up=float(k.get('SuccessProficiencyUp', 0)), fail_up=float(k.get('FailProficiencyUp', 0)),
        req_items=[[code, int(count)] for code, count in k.get('ReqItem', [])],
        items=[[code, int(count), float(prob)] for code, count, prob in k.get('ItemIN', [])],
        fail_items=[[code, int(count), float(prob)] for code, count, prob in k.get('FailIN', [])],
    ) for k in lua_tables(making, 'DictKairo:LoadMaking')]
    fishing_items = lua_tables(fishing, 'DictItem:LoadItem')
    baits = {i['ItemID']: int(i.get('AdjValue', 0)) for i in fishing_items if i.get('Type') == BAIT_ITEM_TYPE}
    proficiency_items = {i['ItemID']: int(i.get('AdjValue', 0)) for i in fishing_items
                         if i.get('Type') == PROFICIENCY_ITEM_TYPE}
    return dict(targets=targets, gathering=gathering_kairo, fishing=fishing_kairo, making=making_kairo,
                fish_groups=fish_groups, skills=skills, recipes=recipes, baits=baits,
                proficiency_items=proficiency_items)


@lru_cache(maxsize=None)
def life_data() -> dict:
    """The life-skill tables (see module docstring), from assets/life_targets.json or the dict files."""
    override = _env_override('fishing.lua') or _env_override('gathering.lua')
    path = bundled_asset('life_targets.json', override)
    if path:
        return json.loads(path.read_text(encoding='utf-8'))
    return _from_lua()


@lru_cache(maxsize=None)
def target_kinds() -> dict:
    """(ResourceNum, ResourceIdx) -> DictTarget entry."""
    return {(t['resource_num'], t['resource_idx']): t for t in life_data()['targets']}


@lru_cache(maxsize=None)
def gathering_kairo() -> dict:
    """Gathering Kairo id (ge000NN) -> yield entry."""
    return {k['id']: k for k in life_data()['gathering']}


@lru_cache(maxsize=None)
def making_kairo() -> dict:
    """Crafting Kairo id (e.g. Wmake33_Info) -> recipe entry (DictKairo:LoadMaking)."""
    return {k['id']: k for k in life_data().get('making', [])}


@lru_cache(maxsize=None)
def life_skill_levels() -> dict:
    """(profession skill NameIndex, level) -> profession level entry (cap and requirements)."""
    return {(s['skill'], s['level']): s for s in life_data()['skills']}


@lru_cache(maxsize=None)
def recipe_skills() -> dict:
    """(recipe skill NameIndex, level) -> recipe skill entry (DemandLv, DemandSkill ids)."""
    return {(r['skill'], r['level']): r for r in life_data().get('recipes', [])}


@lru_cache(maxsize=None)
def skill_level_by_id() -> dict:
    """Profession skill ID (e.g. spnw19301) -> (NameIndex, level), for DemandSkill."""
    return {s['id']: (s['skill'], s['level']) for s in life_data()['skills'] if s.get('id')}


@lru_cache(maxsize=None)
def fishing_kairo() -> dict:
    """Fishing target id (Fish_ACT1_N0) -> catch entry."""
    return {k['target']: k for k in life_data()['fishing']}


def fish_group(group_id):
    """[(ItemID, count, weight)] of one fishing catch group."""
    return [tuple(entry) for entry in life_data()['fish_groups'].get(group_id, [])]


def bait_time_reduction(code):
    """Casting time reduction (seconds) of a fishing bait, or None if `code` is not a bait."""
    return life_data().get('baits', {}).get(code)


def fishing_proficiency_gain(code):
    """Fishing proficiency an item adds when used (Type 46), or None."""
    return life_data().get('proficiency_items', {}).get(code)


def max_proficiency(skill_index, skill_level) -> float:
    """MaxProficiency of a life skill at the learned level (0 when not learned)."""
    best = 0.0
    for s in life_data()['skills']:
        if s['skill'] == skill_index and s['level'] <= skill_level:
            best = max(best, s['max_proficiency'])
    return best


@lru_cache(maxsize=None)
def town_gtargets() -> dict:
    """Square name -> [(uid, DictTarget entry)] for the map objects that are life-skill targets."""
    path = bundled_asset('gtargets.tsv')
    out = {}
    if path is None:
        return out
    kinds = target_kinds()
    for row in tsv_rows(path):
        if len(row) < 4:
            continue
        kind = kinds.get((int(row[2]), int(row[3])))
        if kind is not None:
            out.setdefault(row[0], []).append((int(row[1]), kind))
    return out
