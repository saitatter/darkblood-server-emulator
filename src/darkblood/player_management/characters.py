"""Local character storage and the client's character struct.

Struct reader 0xA4AB30 (constructor 0x737BD0); offsets are in the client
object. Field names are only given where the value was observed in a request
or on screen; the rest are named by offset and sent as zero.
"""
import os
import struct
from pathlib import Path
from darkblood import REPO_ROOT
from darkblood.core.serialization.jser import WireError, read_varuint
from darkblood.games.entities.character import Character


DATA = Path(os.environ.get('DARKBLOOD_DATA', REPO_ROOT / 'data'))


def read_wide(data, offset):
    size, offset = read_varuint(data, offset)
    if size % 2 or offset + size > len(data):
        raise WireError('Bad wide string')
    return data[offset:offset + size].decode('utf-16le'), offset + size


def parse_create_request(body):
    """eEGS_CREATE_CHARACTER_REQ (2012), observed layout:
    i32 (0x7FFFFFFF), u8 class, wstr name, u32 face, u32 hair,
    5 x u8 body sliders (head, arms, chest, torso, legs), u8."""
    if len(body) < 6:
        raise WireError('Truncated create request')
    char_class = body[4]
    name, offset = read_wide(body, 5)
    if offset + 14 > len(body):
        raise WireError('Truncated create request tail')
    face, hair = struct.unpack_from('<II', body, offset)
    sliders = list(body[offset + 8:offset + 13])
    trailing = body[offset + 13]
    return dict(char_class=char_class, name=name, face=face, hair=hair, body=sliders, extra=trailing)


def encode_character(char):
    """Serialize for reader 0xA4AB30 using Character model."""
    if isinstance(char, Character):
        return char.encode_lobby_entry()
    return Character.from_dict(char).encode_lobby_entry()


EQUIP_CONTAINER = 1  # item container treated as worn by the client (0x008354D0)
# Container value 2 is reserved: 0x008354D0 drops every item whose container
# is 2 without storing it, so bag ids must avoid it.
INVENTORY_BAG_CONTAINER = 3
DEFAULT_BAG_CODE = 'Ibaga0004'
DEFAULT_BAG_CAPACITY = 5


def ensure_inventory(char):
    """Give a new character its default equipment and first bag.

    Equipment is the client's default set for the job
    (DictItem:LoadDefaultEquipItem), worn in container 1. Container 3 is an
    initial 5-cell Ibaga0004 bag in UI slot 0. Returns True if the record changed.
    """
    changed = False
    from darkblood.games.game_data.client_dict import default_equipment
    job = int(char.get('char_class', 0))

    if 'bags' not in char:
        char['bags'] = [
            {'bag_id': EQUIP_CONTAINER, 'b28': 0xFF, 'w2a': 0xFFFF},
            {'bag_id': INVENTORY_BAG_CONTAINER, 'code': DEFAULT_BAG_CODE,
             'b28': 0, 'b29': DEFAULT_BAG_CAPACITY, 'w2a': 0},
        ]
        changed = True

    if 'items' not in char:
        gear = [code for code in default_equipment().get(job, []) if not code.startswith('C')]
        char['items'] = []
        equipped = set()
        for code in gear:
            slot = equip_slot_for(code, equipped)
            record = dict(code=code, uid=next_item_uid(char))
            if slot is None:
                record.update(container=INVENTORY_BAG_CONTAINER,
                              slot=len([i for i in char['items'] if i['container'] == INVENTORY_BAG_CONTAINER]))
            else:
                equipped.add(slot)
                record.update(container=EQUIP_CONTAINER, slot=slot)
            char['items'].append(record)
        changed = True

    return changed


# Equipment container slots, from 0x0070A8C0 (slot -> character-window
# widget): 0 Slot_Weapon_1 (right hand), 1 Slot_Weapon_2 (left hand), 2 Armor,
# 3 Glove, 4 FootWear, 5 Belt, 6 Shoulder, 7 Cloak, 8 NeckLace, 9/10 EarRing,
# 11/12 Ring, 13 Helmet. Armour parts by item-id prefix, confirmed by each
# item's PartFilePath/DropImgFilePath (BODY_A, GLOVE, BOOTS, BODY_B = pants,
# SHOULDER, HELMET).
ARMOR_SLOTS = {'Abod': 2, 'Aglo': 3, 'Asho': 4, 'Abel': 5, 'Ader': 6, 'Ahel': 13}
# Accessories by prefix, from each item's DropImgFilePath in item_equip*.lua
# (Cloak_*, Necklace_*, Earring_*, Ring_*).
ACCESSORY_SLOTS = {'Aclo': (7,), 'Anec': (8,), 'Aear': (9, 10), 'Arin': (11, 12)}
# Avatar (costume) parts live in the same equipment container. Slot ->
# widget map from the character window builder (0x009E3A50 calls): 14
# HairStyle, 15 FaceType, 16 Armor_Avatar, 17 Helmet_Avatar, 18 Glove_Avatar,
# 19 FootWear_Avatar, 20 Belt_Avatar, 21 Shoulder_Avatar, 22 Cloak_Avatar,
# 23-30 rune slots. Costume ids are C + part (CbodW1N808 ... CderW1N814), also
# Cmag + part for the magic variants (CmagbodCash5).
AVATAR_SLOTS = {'bod': 16, 'hel': 17, 'glo': 18, 'sho': 19, 'bel': 20, 'der': 21, 'clo': 22}


def avatar_slot(code):
    if not code.startswith('C'):
        return None
    part = code[4:7] if code.startswith('Cmag') else code[1:4]
    return AVATAR_SLOTS.get(part)
WEAPON_RIGHT, WEAPON_LEFT = 0, 1
OFFHAND_PREFIXES = ('Ashi', 'Abok', 'Wshu', 'WTof')  # shield (Knight), book (Mage), shuriken (Thief), tonfa (Fighter)


def equip_slot_for(code, taken):
    """Equipment slot for a default item, or None if it belongs in a bag.

    Main weapons take the right hand (Slot 0). Shields (Ashi), books (Abok),
    and true dual-wield offhands (Thief shuriken Wshu, Fighter tonfa WTof)
    take the left hand (Slot 1). Single-weapon classes (Warrior, Hunter, etc.)
    never occupy Slot 1; alternate weapons (e.g. Warrior axe Waxew0000) go to the bag.
    """
    slot = ARMOR_SLOTS.get(code[:4])
    if slot is None and code.startswith(OFFHAND_PREFIXES):
        slot = WEAPON_LEFT
    elif slot is None and code.startswith('W'):
        slot = WEAPON_RIGHT
    if slot is None or slot in taken:
        return None
    return slot


def fits_equip_slot(code, slot):
    """Whether an item may sit in equipment slot `slot`.

    Armour with a known prefix only fits its own slot; accessories their
    slot(s); weapons fit the hands (offhand items the left hand, others the
    right). Unknown A* prefixes fit nowhere.
    """
    part = ARMOR_SLOTS.get(code[:4])
    if part is not None:
        return slot == part
    avatar = avatar_slot(code)
    if avatar is not None:
        return slot == avatar
    if code[:4] in ACCESSORY_SLOTS:
        return slot in ACCESSORY_SLOTS[code[:4]]
    if code.startswith(OFFHAND_PREFIXES):
        return slot == WEAPON_LEFT
    if code.startswith('W'):
        return slot == WEAPON_RIGHT
    return False


def next_item_uid(char):
    """Per-character item UID counter (UIDs only need to be unique per owner here)."""
    uid = int(char.get('next_item_uid', 1))
    char['next_item_uid'] = uid + 1
    return uid


def slots_needed(items):
    """Bag cells add_reward_items would use for [(code, count)]."""
    from darkblood.games.game_data.client_dict import item_max_durability
    return sum(max(1, int(n)) if item_max_durability(code) is not None else 1 for code, n in items)


def _inventory_bags(char):
    """Non-equipment bags in UI slot order (w2a 0..4)."""
    bags = [b for b in char.get('bags', []) if b.get('bag_id') != EQUIP_CONTAINER]
    return sorted(bags, key=lambda b: int(b.get('w2a', 0xFFFF)))


def free_cells(char):
    """[(container, slot)] free cells over every equipped bag, in UI order.

    A bag's capacity is its entry's b29 (BagSize, e.g. 5 for Ibaga0004).
    """
    used = {(i.get('container'), i.get('slot')) for i in char.get('items', [])}
    return [(b['bag_id'], s) for b in _inventory_bags(char)
            for s in range(int(b.get('b29', DEFAULT_BAG_CAPACITY)))
            if (b['bag_id'], s) not in used]


TEST_BAG_CODE = 'Ibaga0003'  # BagSize 20 in item_disposable.lua
UI_BAG_SLOTS = 5               # bag bar slots w2a 0..4 (0x00557860)


def grant_test_bags(char, code=TEST_BAG_CODE, size=20):
    """Testing aid (GM /bags): every UI bag slot holds a `size`-cell bag.

    Existing bags smaller than `size` become `code`; free UI slots get a new
    bag. Bag ids avoid the equipment container 1, the reserved container 2
    and ids already in use. Returns the number of bags added or enlarged.
    The client reads bags from 2007, so the character must be selected again.
    """
    bags = char.setdefault('bags', [])
    changed = 0
    for bag in _inventory_bags(char):
        if int(bag.get('b29', DEFAULT_BAG_CAPACITY)) < size:
            bag.update(code=code, b29=size)
            changed += 1
    used_ids = {b['bag_id'] for b in bags} | {EQUIP_CONTAINER, 2}
    used_slots = {int(b.get('w2a', 0xFFFF)) for b in _inventory_bags(char)}
    for slot in range(UI_BAG_SLOTS):
        if slot in used_slots:
            continue
        bag_id = next_item_uid(char)
        while bag_id in used_ids:
            bag_id = next_item_uid(char)
        used_ids.add(bag_id)
        bags.append({'bag_id': bag_id, 'code': code, 'b28': 0, 'b29': size, 'w2a': slot})
        changed += 1
    return changed


def free_bag_slots(char):
    """Free cells over all equipped bags. None when there is no bag."""
    if not _inventory_bags(char):
        return None
    return len(free_cells(char))


def add_reward_items(char, items):
    """Store reward items in the free cells of the equipped bags, in UI order.

    Returns the stored item records. Callers check free_bag_slots first; if
    the bags are still full, the remaining items go past the last bag's
    capacity (not shown by the client). Without an equipped bag the items go
    to container -1 (client default bag 0x00828600(-1)); their display in the
    inventory window is NOT verified yet.
    """
    bags = _inventory_bags(char)
    cells = free_cells(char)
    last = bags[-1]['bag_id'] if bags else -1
    used = {i['slot'] for i in char.get('items', []) if i.get('container') == last}
    from darkblood.games.game_data.client_dict import item_max_durability
    stored = []
    for code, count in items:
        count = max(1, int(count))
        # Equipment (has a Durability entry) takes one slot per piece; other
        # items are stored as one stack (Item +0 Amount). Stack limits are not
        # recovered.
        stacks = [1] * count if item_max_durability(code) is not None else [count]
        for amount in stacks:
            if cells:
                container, slot = cells.pop(0)
            else:
                container = last
                slot = next(s for s in range(256) if s not in used)
            if container == last:
                used.add(slot)
            record = dict(code=code, uid=next_item_uid(char), container=container, slot=slot)
            if amount > 1:
                record['count'] = amount
            char.setdefault('items', []).append(record)
            stored.append(record)
    return stored
