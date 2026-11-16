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
        char['items'] = [dict(code=code, uid=next_item_uid(char), container=EQUIP_CONTAINER, slot=i)
                         for i, code in enumerate(gear)]
        changed = True

    return changed


def next_item_uid(char):
    """Per-character item UID counter (UIDs only need to be unique per owner here)."""
    uid = int(char.get('next_item_uid', 1))
    char['next_item_uid'] = uid + 1
    return uid


def add_reward_items(char, items):
    """Store reward items in the first non-equipment bag, next free slots.

    Returns the stored item records. Without an equipped bag the items go to
    container -1 (client default bag 0x00828600(-1)); their display in the
    inventory window is NOT verified yet.
    """
    bags = [b['bag_id'] for b in char.get('bags', []) if b.get('bag_id') != EQUIP_CONTAINER]
    container = bags[0] if bags else -1
    used = {i['slot'] for i in char.get('items', []) if i.get('container') == container}
    from darkblood.games.game_data.client_dict import item_max_durability
    stored = []
    for code, count in items:
        count = max(1, int(count))
        # Equipment (has a Durability entry) takes one slot per piece; other
        # items are stored as one stack (Item +0 Amount). Stack limits are not
        # recovered.
        stacks = [1] * count if item_max_durability(code) is not None else [count]
        for amount in stacks:
            slot = next(s for s in range(256) if s not in used)
            used.add(slot)
            record = dict(code=code, uid=next_item_uid(char), container=container, slot=slot)
            if amount > 1:
                record['count'] = amount
            char.setdefault('items', []).append(record)
            stored.append(record)
    return stored
