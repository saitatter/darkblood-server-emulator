"""Prepare a scratch character database for live tests (never the real data/ folder).

Start the server on it with `gamectl.py start --data-dir DIR` (or the MCP game_start
data_dir argument). Create characters before starting the server: it caches the store.

Usage:
    python tools/automation/test_data.py DIR --name LifeTester --level 15 \
        --skill 9007=1 --item ILurN1=5 --gold 100000 --layer Act1:4
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REAL_DATA = (ROOT / 'data').resolve()

_CREATE = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
spec = json.loads(sys.argv[2])
from darkblood.games.session import GameSession
from darkblood.games.entities.character import layer_net_id
from darkblood.player_management.characters import add_reward_items
store = GameSession.store()
char = store.create(spec['account'], {'name': spec['name'], 'char_class': spec['char_class']})
if char is None:
    sys.exit('name already taken: %s' % spec['name'])
char.update(level=spec['level'], gold=spec['gold'], tutorial_cleared=True)
if spec.get('layer'):
    square, layer = spec['layer']
    char['join_layer_net_id'] = layer_net_id(square, layer)
char.setdefault('skills', {}).update({str(k): int(v) for k, v in spec['skills'].items()})
life = [int(k) for k in spec['skills'] if int(k) in (9007, 9008)]
if life:
    char['learned_proficiencies'] = sorted({0 if k == 9007 else 1 for k in life})
add_reward_items(char, [(code, int(n)) for code, n in spec['items']])
store.save_char(spec['account'], char['id'])
print(json.dumps({'id': char['id'], 'name': char['name'], 'account': spec['account'],
                  'level': char['level'], 'db': str(store.path),
                  'items': [(i['code'], i.get('count', 1)) for i in char['items']]}))
'''


def create_character(data_dir, name, account='OfflinePlayer', char_class=1, level=1, gold=0,
                     skills=None, items=None, layer=None):
    """Create one character in the store at `data_dir`; returns its summary."""
    data_dir = Path(data_dir).resolve()
    if data_dir == REAL_DATA:
        raise ValueError('refusing to write test characters into the real data/ folder')
    data_dir.mkdir(parents=True, exist_ok=True)
    spec = dict(name=name, account=account, char_class=int(char_class), level=int(level), gold=int(gold),
                skills=skills or {}, items=items or [], layer=layer)
    env = dict(os.environ, DARKBLOOD_DATA=str(data_dir))
    proc = subprocess.run([sys.executable, '-c', _CREATE, str(ROOT / 'src'), json.dumps(spec)],
                          cwd=str(ROOT), env=env, capture_output=True, text=True)
    if proc.returncode:
        raise RuntimeError((proc.stderr or proc.stdout).strip())
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _pair(text, sep='='):
    key, _, value = text.partition(sep)
    return key, value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('data_dir')
    parser.add_argument('--name', required=True)
    parser.add_argument('--account', default='OfflinePlayer')
    parser.add_argument('--char-class', type=int, default=1)
    parser.add_argument('--level', type=int, default=1)
    parser.add_argument('--gold', type=int, default=0)
    parser.add_argument('--skill', action='append', default=[], help='skill_index=level')
    parser.add_argument('--item', action='append', default=[], help='ItemID=count')
    parser.add_argument('--layer', help='Square:layer for the spawn layer, e.g. Act1:4')
    args = parser.parse_args(argv)
    layer = None
    if args.layer:
        square, idx = _pair(args.layer, ':')
        layer = (square, int(idx))
    print(json.dumps(create_character(
        args.data_dir, args.name, args.account, args.char_class, args.level, args.gold,
        skills=dict(_pair(s) for s in args.skill),
        items=[(code, int(n or 1)) for code, n in (_pair(i) for i in args.item)],
        layer=layer), indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
