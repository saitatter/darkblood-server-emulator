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
            char = dict(request, id=self.data['next_id'])
            self.data['next_id'] += 1
            chars.append(char)
            self.save()
            return char
