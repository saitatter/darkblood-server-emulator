#!/usr/bin/env python3
"""Generate the per-domain progress bars and the unmapped-field list.

Source of truth: schemas/*.jsch. Every field named `_` is sent as its default
because the client reader that consumes it has not been mapped to a meaning, so
the share of named fields measures how much of the implemented wire is understood.

Coverage counts the client-facing opcodes (eEGS_, eERC_, eERT_ in
assets/opcodes.tsv) that have a schema message or a server handler. Each opcode
is assigned to a domain: its schema's domain when it has one, otherwise by the
keyword rules in DOMAIN_RULES. GM cheats, anti-cheat, login/billing back ends
and similar opcodes (OUT_OF_SCOPE) are not counted. Overall = coverage x field
mapping, so unimplemented or schema-less opcodes lower the percentage.

Writes:
  docs/UNMAPPED_FIELDS.md   full list, grouped by domain
  README.md                 the block between <!-- PROGRESS:START --> and <!-- PROGRESS:END -->

    python tools/gen_progress.py           # rewrite both files
    python tools/gen_progress.py --check   # exit 1 when they are stale
"""
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCHEMAS = ROOT / 'schemas'
README = ROOT / 'README.md'
UNMAPPED = ROOT / 'docs' / 'UNMAPPED_FIELDS.md'
START, END = '<!-- PROGRESS:START -->', '<!-- PROGRESS:END -->'
BAR = 20

OUT_OF_SCOPE = re.compile(r'^(CHEAT|AUTHENTICATE|NPROTECT|XTRAP|AUTOCHECK|LOG_|USER_LOG|DB_|COMPUTER|FRAME_STAT|WARFLAG_HACK)')
DOMAIN_RULES = [(domain, re.compile(rx)) for domain, rx in [
    ('arena', r'^(ARENA|LEAGUE|DUEL|GBB|MINIGAME)'),
    ('guild', r'^(GUILD|SIEGE|CITADEL|CIDADEL|REFUSE_GUILD|CURRENT_GUILD|ACTIVE_WARFLAG|STRESS_CHANGE_WARFLAG)'),
    ('mail', r'^POST'),
    ('pets', r'^(PET|RIDING|TAMEING|MONSTERCARD)'),
    ('stalls', r'^(PERSONALSHOP|BROKER|SALEBYBULK)'),
    ('party', r'^(INVITE|ACCEPT_INVITE|ROOM_MEM|REQUEST_JOIN_ROOM|TEACHING|GUIDE|SUMMON|ACKNOWLEDGE_TELEPORT)'),
    ('quests', r'^(QUEST|TUTORIAL|CLEAR_TUTORIAL|NPC|WAYPOINT_|ACHIEVE|TITLE|ACT_KAIRO)'),
    ('skills', r'^(LEARN|SKILL|DUALSKILL|INIT_SKILL|INIT_PROF|MODIFY_SKILL|READJUST|ASSIGN|SWITCH_QU)'),
    ('commerce', r'^(BUY|SELL|REPURCHASE|BILLING|STEAM|ACTOZ|CASH|STORE|TRADE|ACCEPT_REQUEST_TRADE|CANCEL_TRADE|'
                 r'INSERT_TRADE|DELETE_TRADE|FINALLY|DEPOT|STORAGE|BEAUTYSHOP|ROULETTE|VIP)'),
    ('social', r'^(FRIEND|CHAT|BANISH|ALARM|CONTRACT|HTTPNOTICE|WATCH|REQUEST_)'),
    ('dungeon', r'^(CLEAR_|EXPLORE|DUNGEON|STORYDUNGEON|TRAINING|MONSTER_|TREASURE|DAILY|FAIL|GOLDGOBLIEN|'
                r'START_GAME|FINISH_GAME|BACK_TO|AGAIN|CHOICE|GAMEPLAY|RELAY_|SELECT_DUNGEON|CREATE_ROOM|JOIN_ROOM|'
                r'CHANGE_ROOM|WAYPOINTCHARLAYER|DROP_ITEM|PICK|LEVEL_UP|REBIRTH|INCREASING|CRONOS|SERVERBUFF|KEEP|'
                r'QUESTITEM|GET_ROOMINFO|LEAVE_ROOM)'),
    ('inventory', r'^(USE|ITEM|AVATAR|MAGICENCHANT|SMELTING|MARK|SEAL|RANDOM|FIX|DURABILITY|DRAG|EQUIP|OPEN_BAG|'
                  r'CLOSE_BAG|SWITCH_BAG|CHANGE_BAG|CHANGE_ITEM|BAG|REPLACE|DIVIDE|INVENTORY|NOT_ENOUGH|INSERT_AP|'
                  r'DECREASE|RAREAVATAR|DELETE_ITEM|DELETE_ALL)'),
    ('lobby', r'^(KNOCK|SELECT_CHAR|GET_CHAR|GET_INVITE|CREATE_CHAR|DELETE_CHAR|UNDELETE|CHARSLOT|CHAR_|SQUARELIST|'
              r'SQUARE|JOIN_SQUARE|LEAVE_SQUARE|ENTER|LEAVE_MAPTOOL|UPDATE_KNOCK|PLAY|KEYBOARD|SECOND|IMPLIED)'),
]]

HEADER = re.compile(r'^(message|struct)\s+(\d+\s+)?(\w+)')
FIELD = re.compile(r'^\s+(raw\[\d+\]|\w+(?:<[^>\s]*>)?)\s+(\w+)\s*(?:=\s*[^#]*?)?\s*(?:#\s*(.*))?$')
SKIP = {'ok_only', 'if', 'endif', 'lit', 'end'}


def parse(path):
    """Return (message opcodes, field count, unmapped rows (owner, line, type, note))."""
    messages, fields, unmapped = set(), 0, []
    owner = None
    for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        header = HEADER.match(line)
        if header:
            kind, opcode, name = header.groups()
            owner = (opcode.strip() + ' ' if opcode else '') + name
            if kind == 'message':
                messages.add(int(opcode))
            continue
        if owner is None or not line.startswith('  ') or line.lstrip().startswith('#'):
            continue
        match = FIELD.match(line)
        if not match or match.group(1) in SKIP:
            continue
        ftype, fname, note = match.groups()
        fields += 1
        if fname == '_':
            unmapped.append((owner, number, ftype, (note or '').strip()))
    return messages, fields, unmapped


def bar(done, total):
    filled = round(BAR * done / total) if total else BAR
    return '█' * filled + '░' * (BAR - filled)


def client_opcodes():
    names = {}
    for line in (ROOT / 'assets' / 'opcodes.tsv').read_text(encoding='utf-8').splitlines():
        parts = line.split('	')
        if len(parts) >= 2 and parts[0].isdigit():
            match = re.match(r'eE(?:GS|RC|RT)_(.*)', parts[1])
            if match and not OUT_OF_SCOPE.match(match.group(1)):
                names[int(parts[0])] = match.group(1)
    return names


def keyword_domain(name):
    for domain, rule in DOMAIN_RULES:
        if rule.match(name):
            return domain
    return 'system'


def server_handlers():
    sys.path.insert(0, str(ROOT / 'src'))
    from darkblood.games import session  # registers every controller
    return set(session.DISPATCHER._handlers)


def collect():
    parsed = {}
    for path in sorted(SCHEMAS.glob('*.jsch')):
        parsed[path] = parse(path)
    names, handled = client_opcodes(), server_handlers()
    schema_domain = {op: path.stem for path, (messages, _f, _u) in parsed.items() for op in messages}
    scope = {d: [0, 0] for d in (p.stem for p in parsed)}  # [implemented, total]
    for op, name in names.items():
        domain = schema_domain.get(op) or keyword_domain(name)
        scope[domain][1] += 1
        if op in schema_domain or op in handled:
            scope[domain][0] += 1
    rows = []
    for path, (messages, fields, unmapped) in parsed.items():
        rows.append({'domain': path.stem, 'file': path.name, 'messages': messages,
                     'fields': fields, 'unmapped': unmapped, 'named': fields - len(unmapped),
                     'impl': scope[path.stem][0], 'total': scope[path.stem][1]})
    return rows


def overall(row):
    return (row['impl'] / row['total'] if row['total'] else 1) * (row['named'] / row['fields'] if row['fields'] else 1)


def table_row(label, impl, total, named, fields):
    cov = impl / total if total else 1
    fmap = named / fields if fields else 1
    return '| {l} | {i}/{t} ({c:.0f}%) | {n}/{f} ({m:.0f}%) | `{b}` {o:.0f}% |'.format(
        l=label, i=impl, t=total, c=100 * cov, n=named, f=fields, m=100 * fmap,
        b=bar(cov * fmap * 1000, 1000), o=100 * cov * fmap)


def render_readme(rows):
    lines = ['_Generated by `tools/gen_progress.py` on every push to main; do not edit by hand._', '',
             '**Opcodes** are the client-facing requests and notices (`eEGS_`, `eERC_`, `eERT_`) that have a schema '
             'message or a server handler, out of all the client defines for that system. **Fields** are the share '
             'of fields in implemented messages whose meaning is recovered; unmapped ones (`_` in '
             '`schemas/*.jsch`) are sent as zero or defaults. **Overall** = opcodes x fields, so unimplemented '
             'opcodes and unmapped fields both lower it. GM cheats, anti-cheat and login/billing back ends are not '
             'counted, and opcodes without a schema are assigned to a system by name, so the split is approximate.', '',
             '| System | Opcodes | Fields | Overall |', '| :--- | ---: | ---: | :--- |']
    tot = [0, 0, 0, 0]
    for row in sorted(rows, key=lambda r: -overall(r)):
        lines.append(table_row(row['domain'], row['impl'], row['total'], row['named'], row['fields']))
        for i, key in enumerate(('impl', 'total', 'named', 'fields')):
            tot[i] += row[key]
    lines.append(table_row('**Total**', *tot))
    lines += ['', 'Every unmapped field, with the reader-address note recorded next to it, is in '
              '[docs/UNMAPPED_FIELDS.md](docs/UNMAPPED_FIELDS.md).', '',
              '<details><summary>Messages and structs that still contain unmapped fields</summary>', '']
    for row in rows:
        if not row['unmapped']:
            continue
        by_owner = {}
        for owner, _, ftype, _note in row['unmapped']:
            by_owner.setdefault(owner, []).append(ftype)
        lines.append('**%s** (%d)' % (row['domain'], len(row['unmapped'])))
        lines.append('')
        lines.append(', '.join('`%s` ×%d' % (o, len(t)) if len(t) > 1 else '`%s`' % o
                               for o, t in by_owner.items()))
        lines.append('')
    lines.append('</details>')
    return '\n'.join(lines)


def render_unmapped(rows):
    out = ['# Unmapped fields', '',
           '> Generated by `tools/gen_progress.py`; do not edit by hand. Each row is a field the server sends',
           '> as zero or a default because its meaning is not recovered. Fix it by recovering the client',
           '> reader/writer, naming the field in `schemas/<domain>.jsch`, and regenerating.', '']
    for row in rows:
        if not row['unmapped']:
            continue
        out += ['## %s (%d of %d fields)' % (row['domain'], len(row['unmapped']), row['fields']), '',
                '| Message / struct | Type | Line | Note |', '| :--- | :--- | ---: | :--- |']
        for owner, number, ftype, note in row['unmapped']:
            out.append('| `%s` | `%s` | %s:%d | %s |' % (owner, ftype, row['file'], number, note.replace('|', '\\|')))
        out.append('')
    return '\n'.join(out)


def main():
    rows = collect()
    text = README.read_text(encoding='utf-8')
    if START not in text or END not in text:
        sys.exit('README.md lacks the %s / %s markers' % (START, END))
    head, rest = text.split(START, 1)
    tail = rest.split(END, 1)[1]
    new_readme = head + START + '\n' + render_readme(rows) + '\n' + END + tail
    new_unmapped = render_unmapped(rows) + '\n'
    if '--check' in sys.argv:
        stale = (new_readme != text or not UNMAPPED.is_file()
                 or UNMAPPED.read_text(encoding='utf-8') != new_unmapped)
        if stale:
            sys.exit('progress is stale: run python tools/gen_progress.py')
        return
    for path, content in ((README, new_readme), (UNMAPPED, new_unmapped)):
        with open(str(path), 'w', encoding='utf-8', newline='\n') as handle:
            handle.write(content)
    print('Wrote README progress block and docs/UNMAPPED_FIELDS.md')


if __name__ == '__main__':
    main()
