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
