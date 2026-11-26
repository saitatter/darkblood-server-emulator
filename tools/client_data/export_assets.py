#!/usr/bin/env python3
"""Export normalized server assets from extracted client Lua data.

Reads decompiled Lua dictionaries from $DARKBLOOD_CLIENT_DATA (or
../darkblood-client-data/lua_src/data/dict) and outputs clean, self-contained
TSV and JSON assets into assets/ so the server can run without external client data.
"""
import json
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / 'src'))

from darkblood.games.game_data import client_dict

ASSETS_DIR = REPO_ROOT / 'assets'


def export_starter_equipment():
    data = client_dict.default_equipment()
    lines = ['class_id\titem_code']
    for cls_id, items in sorted(data.items()):
        for item in items:
            lines.append(f"{cls_id}\t{item}")
    out = ASSETS_DIR / 'starter_equipment.tsv'
    out.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f"Exported {len(lines)-1} starter equipment rows to {out.name}")


def export_char_stats():
    data = client_dict.char_level_stats()
    lines = ['class_id\tlevel\thp\tmp\tupexp']
    for (cls_id, lv), stats in sorted(data.items()):
        lines.append(f"{cls_id}\t{lv}\t{stats['hp']}\t{stats['mp']}\t{stats['upexp']}")
    out = ASSETS_DIR / 'char_stats.tsv'
    out.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f"Exported {len(lines)-1} char stats rows to {out.name}")


def export_levelup_ap():
    data = client_dict.level_up_ap()
    lines = ['level\tgain_ap']
    for lv, ap in sorted(data.items()):
        lines.append(f"{lv}\t{ap}")
    out = ASSETS_DIR / 'levelup_ap.tsv'
    out.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f"Exported {len(lines)-1} levelup AP rows to {out.name}")


def export_life_water():
    data = client_dict.life_water_prices()
    lines = ['level\tstep0\tstep1\tstep2\tstep3\tstep4']
    for lv, steps in sorted(data.items()):
        lines.append(f"{lv}\t" + '\t'.join(str(x) for x in steps[:5]))
    out = ASSETS_DIR / 'life_water.tsv'
    out.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f"Exported {len(lines)-1} life water price rows to {out.name}")


def export_item_durabilities():
    data = client_dict.item_durabilities()
    lines = ['item_code\tmax_durability']
    for item, dur in sorted(data.items()):
        lines.append(f"{item}\t{dur}")
    out = ASSETS_DIR / 'item_durabilities.tsv'
    out.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f"Exported {len(lines)-1} item durability rows to {out.name}")


def export_equip_index():
    data = client_dict.equip_index()
    lines = ['item_id\tgrade\tdemand_lv\tdemand_class']
    for item_id, grade, lv, cls in data:
        lines.append(f"{item_id}\t{grade}\t{lv}\t{cls}")
    out = ASSETS_DIR / 'equip_index.tsv'
    out.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f"Exported {len(lines)-1} equip index rows to {out.name}")


def export_item_fields():
    data = client_dict.item_int_fields()
    lines = ['item_id\tbuy_price\tsell_price\tbag_size\trepair_price']
    for iid, fields in sorted(data.items()):
        buy = fields.get('BuyPrice', 0)
        sell = fields.get('SellPrice', 0)
        bag = fields.get('BagSize', 0)
        repair = fields.get('RepairPrice', 0)
        if buy != 0 or sell != 0 or bag != 0 or repair != 0:
            lines.append(f"{iid}\t{buy}\t{sell}\t{bag}\t{repair}")
    out = ASSETS_DIR / 'item_fields.tsv'
    out.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f"Exported {len(lines)-1} item fields rows to {out.name}")


def export_npcs_and_stores():
    npc_data = client_dict.npc_stores()
    npc_lines = ['npc_id\tstores']
    for _, (npc_id, stores) in sorted(npc_data.items(), key=lambda x: x[1][0]):
        npc_lines.append(f"{npc_id}\t{','.join(stores)}")
    (ASSETS_DIR / 'npcs.tsv').write_text('\n'.join(npc_lines) + '\n', encoding='utf-8')
    print(f"Exported {len(npc_lines)-1} NPC entries to npcs.tsv")

    store_data = client_dict.store_items()
    store_lines = ['store_id\titem_code\tcount']
    for sid, items in sorted(store_data.items()):
        for it, cnt in items:
            store_lines.append(f"{sid}\t{it}\t{cnt}")
    (ASSETS_DIR / 'stores.tsv').write_text('\n'.join(store_lines) + '\n', encoding='utf-8')
    print(f"Exported {len(store_lines)-1} store item rows to stores.tsv")


def export_monsters():
    data = client_dict.monsters()
    lines = ['monster_id\thp\tlv\texp\tdrop_cnt']
    for _, mon in sorted(data.items(), key=lambda x: x[1]['id']):
        lines.append(f"{mon['id']}\t{mon['hp']}\t{mon['lv']}\t{mon['exp']}\t{mon['drop_cnt']}")
    out = ASSETS_DIR / 'monsters.tsv'
    out.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f"Exported {len(lines)-1} monster rows to {out.name}")


def export_money_drops():
    data = client_dict.money_drops()
    lines = ['item_code\tgold_min\tgold_max']
    for iid, (lo, hi) in sorted(data.items()):
        lines.append(f"{iid}\t{lo}\t{hi}")
    out = ASSETS_DIR / 'money_drops.tsv'
    out.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f"Exported {len(lines)-1} money drop rows to {out.name}")


def export_skills():
    data = client_dict.skill_costs()
    lines = ['skill_index\tlevel\tdemand_sp\tdemand_ar']
    for (idx, lv), (sp, ar) in sorted(data.items()):
        lines.append(f"{idx}\t{lv}\t{sp}\t{ar}")
    out = ASSETS_DIR / 'skills.tsv'
    out.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f"Exported {len(lines)-1} skill cost rows to {out.name}")


def export_map_gates():
    data = client_dict.gate_dungeons()
    lines = ['gate_id\tdungeon_ids']
    for gid, dlist in sorted(data.items()):
        lines.append(f"{gid}\t{','.join(dlist)}")
    out = ASSETS_DIR / 'map_gates.tsv'
    out.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f"Exported {len(lines)-1} map gate rows to {out.name}")


def export_dungeon_maps():
    """MapID -> DungeonID, Difficult, QuestLink and, for a quest map that only
    duplicates the regular map of its difficulty, that map (dungeon gate, 5044)."""
    copies = client_dict.dungeon_map_copies()
    lines = ['map_id\tdungeon_id\tdifficult\tquest_link\tsame_as']
    for map_id, (dungeon, diff, link) in sorted(client_dict.dungeon_maps().items()):
        lines.append(f"{map_id}\t{dungeon}\t{diff}\t{link}\t{copies.get(map_id, '')}")
    out = ASSETS_DIR / 'dungeon_maps.tsv'
    out.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f"Exported {len(lines)-1} dungeon maps to {out.name}")


def export_achievements():
    """All achievements: AchieveID, type, division, goal (0 = none), accumulate."""
    lines = ['achieve_id\ttype\tdivision\tgoal\taccumulate']
    for row in client_dict.achievement_table():
        lines.append('\t'.join(str(v) for v in row))
    out = ASSETS_DIR / 'achievements.tsv'
    out.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f"Exported {len(lines)-1} achievements to {out.name}")


def export_quests(root):
    quest_lines = ['quest_id\texp\tgold\tgp\toffer_group\treward_group\tselect_group']
    mission_lines = ['mission_id\tmission_type\ttarget_id\ttarget_value']
    chain_lines = ['quest_id\tobjective_index\tmission_id']
    group_lines = ['group_id\titem_code\tfield2\tcount']

    for p in sorted(root.glob('quest_*.lua')):
        txt = p.read_text(encoding='utf-8', errors='replace')
        for block in re.split(r'assert\(DictQuest:', txt):
            if block.startswith('LoadQuest'):
                for q_block in re.split(r'\n  \{', block):
                    qid = re.search(r'\bID\s*=\s*"([^"]+)"', q_block)
                    if not qid:
                        continue
                    exp = re.search(r'RewardExp = ([0-9.]+)', q_block)
                    gold = re.search(r'RewardGold = ([0-9.]+)', q_block)
                    gp = re.search(r'RewardGP = ([0-9.]+)', q_block)
                    offer = re.search(r'OfferItemG = "([^"]+)"', q_block)
                    reward_g = re.search(r'RewardItemG = "([^"]+)"', q_block)
                    select_g = re.search(r'RewardSelectG = "([^"]+)"', q_block)
                    quest_lines.append(f"{qid.group(1)}\t{int(float(exp.group(1))) if exp else 0}\t{int(float(gold.group(1))) if gold else 0}\t{int(float(gp.group(1))) if gp else 0}\t{offer.group(1) if offer else ''}\t{reward_g.group(1) if reward_g else ''}\t{select_g.group(1) if select_g else ''}")
                    m_match = re.search(r'MissionID\s*=\s*\{([^}]*)\}', q_block, re.S)
                    mids = re.findall(r'"([^"]+)"', m_match.group(1)) if m_match else []
                    for idx, mid in enumerate(mids):
                        chain_lines.append(f"{qid.group(1)}\t{idx}\t{mid}")
            elif block.startswith('LoadMission'):
                for m_block in re.split(r'\n  \{', block):
                    mid = re.search(r'MissionID\s*=\s*"([^"]+)"', m_block)
                    if not mid:
                        continue
                    mtype = re.search(r'MissionType\s*=\s*"([^"]+)"', m_block)
                    tid = re.search(r'TargetID\s*=\s*"([^"]+)"', m_block)
                    tval = re.search(r'TargetValue\s*=\s*(\d+)', m_block)
                    mission_lines.append(f"{mid.group(1)}\t{mtype.group(1) if mtype else ''}\t{tid.group(1) if tid else ''}\t{tval.group(1) if tval else '1'}")
            elif block.startswith('LoadItemGroup'):
                current_group, unit = None, []
                for line in block.splitlines():
                    if line.startswith('    GroupID = '):
                        current_group = line.split('"')[1]
                        continue
                    if line.startswith('      {'):
                        unit = []
                        continue
                    m = re.match(r'^\s*("[^"]+"|-?\d+),?$', line)
                    if m and current_group is not None:
                        val = m.group(1).strip('"')
                        unit.append(val)
                        continue
                    if line.startswith('      }') and current_group is not None and len(unit) == 3:
                        group_lines.append(f"{current_group}\t{unit[0]}\t{unit[1]}\t{unit[2]}")
                        unit = []

    (ASSETS_DIR / 'quests.tsv').write_text('\n'.join(quest_lines) + '\n', encoding='utf-8')
    (ASSETS_DIR / 'quest_missions.tsv').write_text('\n'.join(mission_lines) + '\n', encoding='utf-8')
    (ASSETS_DIR / 'quest_chains.tsv').write_text('\n'.join(chain_lines) + '\n', encoding='utf-8')
    (ASSETS_DIR / 'quest_item_groups.tsv').write_text('\n'.join(group_lines) + '\n', encoding='utf-8')

    # Export final class-promotion quests (PromotionLv == 0) mapped to promoted class IDs
    from darkblood.games.game_data.quests import _promotion_target_class
    all_q = {}
    for p in sorted(root.glob('quest_*.lua')):
        txt = p.read_text(encoding='utf-8', errors='replace')
        for block in re.split(r'assert\(DictQuest:', txt):
            if not block.startswith('LoadQuest'):
                continue
            for q_block in re.split(r'\n  \{', block)[1:]:
                qid = re.search(r'\bID\s*=\s*"([^"]+)"', q_block)
                if not qid:
                    continue
                plv = re.search(r'PromotionLv\s*=\s*(\d+)', q_block)
                ptype = re.search(r'PromotionType\s*=\s*(\d+)', q_block)
                bcls = re.search(r'DemandBClass\s*=\s*"([^"]+)"', q_block)
                lim = re.search(r'LimitQuest\s*=\s*\{([^}]*)\}', q_block)
                all_q[qid.group(1)] = {
                    'plv': int(plv.group(1)) if plv else None,
                    'ptype': int(ptype.group(1)) if ptype else None,
                    'bcls': bcls.group(1) if bcls else '',
                    'limits': re.findall(r'"([^"]+)"', lim.group(1)) if lim else [],
                }
    promo_lines = ['quest_id\ttarget_class']
    for qid, q in sorted(all_q.items()):
        if q['plv'] != 0 or '1' not in q['bcls']:
            continue
        base_cls = q['bcls'].index('1')
        cur = q
        visited = {qid}
        found_ptype = None
        while cur and cur['limits']:
            prev_id = cur['limits'][0]
            if prev_id in visited or prev_id not in all_q:
                break
            visited.add(prev_id)
            prev = all_q[prev_id]
            if prev['ptype'] is not None:
                found_ptype = prev['ptype']
                break
            cur = prev
        if found_ptype is not None:
            promo_lines.append(f"{qid}\t0x{_promotion_target_class(base_cls, found_ptype):02x}")
    (ASSETS_DIR / 'quest_promotions.tsv').write_text('\n'.join(promo_lines) + '\n', encoding='utf-8')
    print(f"Exported {len(quest_lines)-1} quests, {len(mission_lines)-1} missions, {len(chain_lines)-1} chains, {len(group_lines)-1} item groups, {len(promo_lines)-1} promotions")


def export_tutorial_rewards():
    data = client_dict.tutorial_rewards()
    lines = ['mode\titem_code\tcount']
    for mode, items in sorted(data.items()):
        for item, cnt in items:
            lines.append(f"{mode}\t{item}\t{cnt}")
    out = ASSETS_DIR / 'tutorial_rewards.tsv'
    out.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f"Exported {len(lines)-1} tutorial reward rows to {out.name}")


def export_cash_and_random_boxes():
    items = client_dict.cash_items()
    lines = ['item_id\ttype\tadj']
    for iid, val in sorted(items.items()):
        lines.append(f"{iid}\t{val['type']}\t{val['adj']}")
    (ASSETS_DIR / 'cash_items.tsv').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f"Exported {len(lines)-1} cash items to cash_items.tsv")

    pkgs = client_dict.cash_packages()
    lines = ['group_id\titem_code\tcount']
    for gid, itms in sorted(pkgs.items()):
        for item, count in itms:
            lines.append(f"{gid}\t{item}\t{count}")
    (ASSETS_DIR / 'cash_packages.tsv').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f"Exported {len(lines)-1} cash package rows to cash_packages.tsv")

    states, groups = client_dict.random_boxes()
    (ASSETS_DIR / 'random_boxes.json').write_text(json.dumps({'states': states, 'groups': groups}, indent=2), encoding='utf-8')
    print(f"Exported {len(states)} random box states and {len(groups)} groups to random_boxes.json")


def export_looting():
    mon, items, groups = client_dict.looting()
    (ASSETS_DIR / 'looting.json').write_text(json.dumps({'mon_looting': mon, 'looting_items': items, 'groups': groups}, indent=2), encoding='utf-8')
    print(f"Exported looting tables for {len(mon)} dungeons to looting.json")


def export_dungeon_rewards():
    prizes, dungeons = client_dict.dungeon_rewards()
    (ASSETS_DIR / 'dungeon_rewards.json').write_text(
        json.dumps({'prizes': prizes, 'dungeons': dungeons}, indent=2), encoding='utf-8')
    print(f"Exported {len(prizes)} prize groups for {len(dungeons)} dungeons to dungeon_rewards.json")


def main():
    root = client_dict.data_root()
    print(f"Reading from {root}...")
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    export_starter_equipment()
    export_char_stats()
    export_levelup_ap()
    export_life_water()
    export_item_durabilities()
    export_equip_index()
    export_item_fields()
    export_npcs_and_stores()
    export_monsters()
    export_money_drops()
    export_skills()
    export_map_gates()
    export_quests(root)
    export_dungeon_maps()
    export_achievements()
    export_tutorial_rewards()
    export_cash_and_random_boxes()
    export_looting()
    export_dungeon_rewards()
    print("\nAll assets exported successfully!")


if __name__ == '__main__':
    main()
