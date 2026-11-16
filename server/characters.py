"""Local character storage and the client's character struct.

Struct reader 0xA4AB30 (constructor 0x737BD0); offsets are in the client
object. Field names are only given where the value was observed in a request
or on screen; the rest are named by offset and sent as zero.
"""
import json
import os
import struct
import threading
from pathlib import Path

from game_wire import WireError, read_varuint, varuint, wide_string
from models import Character, CharacterClass, CharacterVisuals

DATA = Path(os.environ.get('DARKBLOOD_DATA', Path(__file__).resolve().parent.parent / 'data'))


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


class CharacterStore:
    def __init__(self, path=None):
        self.path = Path(path or DATA / 'characters.json')
        self.lock = threading.Lock()
        try:
            self.data = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            self.data = {'version': 1, 'next_id': 1, 'accounts': {}}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.data, indent=2), encoding='utf-8')
        os.replace(tmp, self.path)

    def characters(self, account):
        return self.data['accounts'].get(account, [])

    def get(self, account, char_id):
        for c in self.characters(account):
            if c['id'] == char_id:
                return c
        return None

    def create(self, account, request):
        with self.lock:
            chars = self.data['accounts'].setdefault(account, [])
            if any(c['name'].lower() == request['name'].lower()
                   for acc in self.data['accounts'].values() for c in acc):
                return None
            char = dict(request, id=self.data['next_id'], level=1, tutorial_cleared=False)
            self.data['next_id'] += 1
            ensure_inventory(char)
            chars.append(char)
            self.save()
            return char


EQUIP_CONTAINER = 1  # item container treated as worn by the client (0x008354D0)


def ensure_inventory(char):
    """Give a character the equipment/bag state the 2007 reply needs.

    Characters created before inventory support have no 'bags'/'items'; they
    receive the client's default equipment for their job
    (DictItem:LoadDefaultEquipItem), worn in container 1. Live-verified: the
    selected character renders with it. Returns True if the record changed.
    """
    if 'bags' in char and 'items' in char:
        return False
    from client_dict import default_equipment
    job = int(char.get('char_class', 0))
    # Package items ("CPkg...") in the list are not wearable; they are left
    # out until the bag/cell display is recovered.
    gear = [code for code in default_equipment().get(job, []) if not code.startswith('C')]
    char.setdefault('bags', [{'bag_id': EQUIP_CONTAINER}])
    char.setdefault('items', [dict(code=code, uid=next_item_uid(char), container=EQUIP_CONTAINER, slot=i)
                              for i, code in enumerate(gear)])
    return True


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
    stored = []
    for code, count in items:
        for _ in range(max(1, int(count))):
            slot = next(s for s in range(256) if s not in used)
            used.add(slot)
            record = dict(code=code, uid=next_item_uid(char), container=container, slot=slot)
            char.setdefault('items', []).append(record)
            stored.append(record)
    return stored
