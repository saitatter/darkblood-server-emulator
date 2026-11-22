"""Monster drops from itemlooting.lua (DictItemDrop), rolled on 5063.

Simplified model of the client tables (the server-side rules are not in the
client): for each LoadMonLooting entry of the current dungeon, roll
RotateCount times with probability UsuallyProb, scaled by monster HP /
AveMonHP when AdjustProbByMonHP is set. A hit picks one item from the
LoadLootingItem entry: its OneItemID, a random entry of its ItemGroup
groups, or (criteria entries) an item_equip*.lua item of the requested
ItemType (0 weapon, 1 armour, 2 accessory), Grade and DemandLv range usable
by the player's class (BaseClass -2). Upgrade probabilities, rare/sneaky
weights and DropEventRevise are ignored.
"""
import random
import re

from darkblood.games.game_data import client_dict
from darkblood.player_management.characters import ACCESSORY_SLOTS, ARMOR_SLOTS

DROP_RATE = 1.0  # global multiplier for the table probabilities


def dungeon_tables(map_code):
    """Loot entries for a map code: exact DungeonID, else the _A1 variant (assumption)."""
    mon, _, _ = client_dict.looting()
    if map_code in mon:
        return mon[map_code]
    return mon.get(re.sub(r'_A\d+$', '_A1', map_code), [])


def _criteria_item(looting_id, char_class):
    m = re.match(r'(\d+)([NSRUM])_(Weapon|Armor|Accessory)$', looting_id)
    if not m:
        return None
    lo = int(m.group(1))
    hi = lo + 4
    grade = 'NSRUM'.index(m.group(2))
    kind = m.group(3)

    def fits(code):
        if kind == 'Weapon':
            return code.startswith('W')
        if kind == 'Armor':
            return code[:4] in ARMOR_SLOTS
        return code[:4] in ACCESSORY_SLOTS

    base_class = int(char_class) & 0x0F
    pool = [code for code, g, lv, cls in client_dict.equip_index()
            if g == grade and lo <= lv <= hi and fits(code)
            and (len(cls) <= base_class or cls[base_class] == '1')]
    return random.choice(pool) if pool else None


def pick_item(looting_id, char_class):
    _, items, groups = client_dict.looting()
    one, group_ids = items.get(looting_id, ('', []))
    if one:
        return one
    pool = [i for g in group_ids for i in groups.get(g, [])]
    if pool:
        return random.choice(pool)
    return _criteria_item(looting_id, char_class)


def roll_drops(map_code, monster, char_class):
    """[ItemID] dropped by one kill of `monster` (client_dict.monsters entry)."""
    drops = []
    for entry in dungeon_tables(map_code):
        if entry['mon_id'] and entry['mon_id'] != monster.get('id'):
            continue  # per-monster table entry (bosses, named monsters)
        prob = entry['prob'] * DROP_RATE
        if entry['adjust_hp'] and entry['ave_hp'] > 0 and monster.get('hp'):
            prob *= monster['hp'] / entry['ave_hp']
        for _ in range(max(1, entry['rotate'])):
            if random.random() < prob:
                item = pick_item(entry['looting_id'], char_class)
                if item:
                    drops.append(item)
    return drops


def _equip_for_prize(kind, level, grade, char_class):
    """Pick a random equipment item matching (kind, level..level+4, grade, base_class)."""
    if kind not in ('Weapon', 'Armor', 'Accessory'):
        return None
    base_class = int(char_class) & 0x0F

    def fits(code):
        if kind == 'Weapon':
            return code.startswith('W')
        if kind == 'Armor':
            return code[:4] in ARMOR_SLOTS
        return code[:4] in ACCESSORY_SLOTS

    equip = client_dict.equip_index()
    for lo, hi in ((level, level + 4), (max(1, level - 5), level + 5)):
        pool = [code for code, g, lv, cls in equip
                if g == grade and lo <= lv <= hi and fits(code)
                and (len(cls) <= base_class or cls[base_class] == '1')]
        if pool:
            return random.choice(pool)
    return None


def roll_dungeon_reward(map_code, char_class):
    """Roll (item_code, count) for a dungeon clear reward card (5090 -> 5091) from dungeonreward.lua."""
    prizes, dungeons = client_dict.dungeon_rewards()
    info = client_dict.dungeon_maps().get(map_code)
    dungeon_id = info[0] if info else ''
    diff = min(3, max(0, int(info[1]))) if info else 0

    entries = dungeons.get(dungeon_id)
    if not entries and map_code:
        # Fallback: strip trailing _A## / _B## map index if map_code wasn't in dungeon_maps
        base = re.sub(r'([A-Z]\d)\d+$', r'\1', map_code)
        entries = dungeons.get(base) or dungeons.get(map_code)
    if not entries:
        return 'Ihppa0001', 1

    # Filter to entries whose prize group can actually resolve an item
    weighted = []
    for pcode, probs in entries:
        w = probs[diff] if diff < len(probs) else (probs[0] if probs else 0.0)
        if w > 0 and pcode in prizes:
            weighted.append((pcode, w))
    if not weighted:
        weighted = [(pcode, 1.0) for pcode, _ in entries if pcode in prizes]

    # Try up to 6 weighted rolls (skipping empty groups such as Avatar_Group_* when unindexed)
    for _ in range(6):
        total_w = sum(w for _, w in weighted)
        if total_w <= 0:
            break
        pick = random.random() * total_w
        acc = 0.0
        chosen = weighted[-1][0]
        for pcode, w in weighted:
            acc += w
            if pick <= acc:
                chosen = pcode
                break
        prize = prizes.get(chosen, {})
        if prize.get('items'):
            code, cnt = random.choice(prize['items'])
            return code, max(1, int(cnt))
        item = _equip_for_prize(prize.get('kind', ''), int(prize.get('level', 1)),
                                int(prize.get('grade', 0)), char_class)
        if item:
            return item, 1

    # Deterministic fallback to any explicit item group in this dungeon
    for pcode, _ in weighted:
        items = prizes.get(pcode, {}).get('items')
        if items:
            code, cnt = random.choice(items)
            return code, max(1, int(cnt))
    return 'Ihppa0001', 1
