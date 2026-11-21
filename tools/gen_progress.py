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
ARCH_START, ARCH_END = '<!-- ARCHITECTURE:START -->', '<!-- ARCHITECTURE:END -->'
BAR = 20

# Anti-cheat, hardware telemetry, and real-money billing backends are out of scope.
OUT_OF_SCOPE_GROUPS = (
    ('anti-cheat & telemetry', re.compile(r'^(NPROTECT|XTRAP|AUTOCHECK|LOG_|COMPUTER|FRAME_STAT|WARFLAG_HACK)')),
    ('billing & monetization', re.compile(r'^(BILLING|ACTOZ)')),
)
OUT_OF_SCOPE = re.compile(
    r'^(NPROTECT|XTRAP|AUTOCHECK|LOG_|COMPUTER|FRAME_STAT|WARFLAG_HACK|BILLING|ACTOZ)'
)
# Opcodes present in the client's enum string table (assets/opcodes.tsv) that have been
# verified against unpacked.analysis.exe + handler_map.txt to have no sender or handler
# in this client build (a82ae3d7...): replaced or removed features, or fire-and-forget ACKs.
UNUSED_IN_CLIENT = frozenset({
    # inventory (12): no senders or handlers in build (6005-6008 are internal router login/logout)
    2034, 2035, 2382, 2383, 2705, 2706, 2707, 2708, 6005, 6006, 6007, 6008,
    # skills (2): 2052 replaced by 2111/2112; 2153 unused (2152 is fire-and-forget)
    2052, 2153,
    # quests (7): old achieve reward/stat & title list opcodes replaced by 2330/2444/2446
    2331, 2332, 2333, 2334, 2337, 2380, 2381,
})
DOMAIN_RULES = [(domain, re.compile(rx)) for domain, rx in [
    ('gm', r'^CHEAT'),
    ('fishing', r'^FISHING'),
    ('arena', r'^(ARENA|LEAGUE|DUEL|GBB|MINIGAME)'),
    ('guild', r'^(GUILD|SIEGE|CITADEL|CIDADEL|REFUSE_GUILD|CURRENT_GUILD|ACTIVE_WARFLAG|STRESS_CHANGE_WARFLAG|UPDATE_CITADEL)'),
    ('mail', r'^POST'),
    ('pets', r'^(PET|RIDING|TAMEING|MONSTERCARD)'),
    ('stalls', r'^(PERSONALSHOP|BROKER|SALEBYBULK)'),
    ('party', r'^(INVITE|ACCEPT_INVITE|ROOM_MEM|REQUEST_JOIN_ROOM|TEACHING|GUIDE|SUMMON|ACKNOWLEDGE_TELEPORT)'),
    ('quests', r'^(QUEST|GET_QUEST|TUTORIAL|CLEAR_TUTORIAL|NPC|WAYPOINT_|ACHIEVE|TITLE|ACT_KAIRO)'),
    ('skills', r'^(LEARN|SKILL|DUALSKILL|INIT_SKILL|INIT_PROF|MODIFY_SKILL|READJUST|ASSIGN|SWITCH_QU)'),
    ('commerce', r'^(BUY|SELL|REPURCHASE|STEAM|CASH|STORE|GET_STORE|TRADE|ACCEPT_REQUEST_TRADE|CANCEL_TRADE|CANCEL_ACCEPT_TRADE|'
                 r'INSERT_TRADE|DELETE_TRADE|FINALLY|DEPOT|STORAGE|BEAUTYSHOP|ROULETTE|VIP)'),
    ('social', r'^(FRIEND|CHAT|BANISH|ALARM|CONTRACT|HTTPNOTICE|WATCH|REQUEST_|ACKNOWLEDGE_LOCATION)'),
    ('dungeon', r'^(CLEAR_|EXPLORE|DUNGEON|STORYDUNGEON|TRAINING|MONSTER_|TREASURE|DAILY|FAIL|GOLDGOBLIEN|'
                r'START_GAME|FINISH_GAME|BACK_TO|AGAIN|CHOICE|GAMEPLAY|RELAY_|SELECT_DUNGEON|CREATE_ROOM|JOIN_ROOM|'
                r'CHANGE_ROOM|CHANGE_MAPCODE|WAYPOINTCHARLAYER|DROP_ITEM|PICK|LEVEL_UP|REBIRTH|INCREASING|CRONOS|'
                r'SERVERBUFF|UPDATE_SERVERBUFF|KEEP|QUESTITEM|GET_ROOMINFO|LEAVE_ROOM)'),
    ('inventory', r'^(USE|ITEM|AVATAR|MAGICENCHANT|SMELTING|MARK|SEAL|RANDOM|FIX|DURABILITY|DRAG|EQUIP|OPEN_BAG|'
                  r'CLOSE_BAG|SWITCH_BAG|CHANGE_BAG|CHANGE_ITEM|BAG|REPLACE|DIVIDE|INVENTORY|NOT_ENOUGH|INSERT_AP|'
                  r'DECREASE|RAREAVATAR|DELETE_ITEM|DELETE_ALL)'),
    ('lobby', r'^(AUTHENTICATE|USER_LOG|DB_LIST|KNOCK|SELECT_CHAR|GET_CHAR|GET_INVITE|CREATE_CHAR|DELETE_CHAR|'
              r'EVENT_DELETE_CHAR|UNDELETE|CHARSLOT|CHAR_|ADD_CHAR|SQUARELIST|SQUARE|JOIN_SQUARE|LEAVE_SQUARE|'
              r'JOIN_LAYER|LEAVE_LAYER|P2P_|GTARGET|CHANGE_GTARGET|ENTER|LEAVE_MAPTOOL|UPDATE_KNOCK|PLAY|'
              r'KEYBOARD|SECOND|IMPLIED)'),
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
            op = int(parts[0])
            if op in UNUSED_IN_CLIENT:
                continue
            match = re.match(r'eE(?:GS|RC|RT)_(.*)', parts[1])
            if match and not OUT_OF_SCOPE.match(match.group(1)):
                names[op] = match.group(1)
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


def excluded_counts():
    counts = {label: 0 for label, _ in OUT_OF_SCOPE_GROUPS}
    counts['unused in client'] = 0
    for line in (ROOT / 'assets' / 'opcodes.tsv').read_text(encoding='utf-8').splitlines():
        parts = line.split('\t')
        if len(parts) >= 2 and parts[0].isdigit():
            match = re.match(r'eE(?:GS|RC|RT)_(.*)', parts[1])
            if not match:
                continue
            if int(parts[0]) in UNUSED_IN_CLIENT:
                counts['unused in client'] += 1
                continue
            body = match.group(1)
            for label, rx in OUT_OF_SCOPE_GROUPS:
                if rx.match(body):
                    counts[label] += 1
                    break
    return counts


def collect():
    parsed = {}
    for path in sorted(SCHEMAS.glob('*.jsch')):
        parsed[path] = parse(path)
    names, handled = client_opcodes(), server_handlers()
    schema_domain = {op: path.stem for path, (messages, _f, _u) in parsed.items() for op in messages}
    all_domains = list(dict.fromkeys([p.stem for p in parsed] + [d for d, _ in DOMAIN_RULES]))
    scope = {d: [0, 0] for d in all_domains}  # [implemented, total]
    for op, name in names.items():
        domain = schema_domain.get(op) or keyword_domain(name)
        scope[domain][1] += 1
        if op in schema_domain or op in handled:
            scope[domain][0] += 1
    by_domain = {p.stem: (p, data) for p, data in parsed.items()}
    rows = []
    for domain in all_domains:
        if scope[domain][1] == 0 and domain not in by_domain:
            continue
        if domain in by_domain:
            path, (messages, fields, unmapped) = by_domain[domain]
            fname = path.name
        else:
            messages, fields, unmapped, fname = set(), 0, [], ''
        rows.append({'domain': domain, 'file': fname, 'messages': messages,
                     'fields': fields, 'unmapped': unmapped, 'named': fields - len(unmapped),
                     'impl': scope[domain][0], 'total': scope[domain][1]})
    return rows


def overall(row):
    cov = row['impl'] / row['total'] if row['total'] else 1
    fmap = row['named'] / row['fields'] if row['fields'] else 1
    return cov * fmap


def table_row(label, impl, total, named, fields):
    cov = impl / total if total else 1
    fmap = named / fields if fields else 1
    fields_col = '%d/%d (%.0f%%)' % (named, fields, 100 * fmap) if fields else '—'
    missing = total - impl
    return '| {l} | {i}/{t} ({c:.0f}%) | {miss} | {fc} | `{b}` {o:.0f}% |'.format(
        l=label, i=impl, t=total, c=100 * cov, miss=missing, fc=fields_col,
        b=bar(cov * fmap * 1000, 1000), o=100 * cov * fmap)


def render_readme(rows):
    excl = excluded_counts()
    excl_summary = ', '.join('%d %s' % (n, label) for label, n in excl.items() if n)
    lines = ['_Generated by `tools/gen_progress.py` on every push to main; do not edit by hand._', '',
             '**Opcodes** are client-facing requests, replies, and notices (`eEGS_`, `eERC_`, `eERT_`) that have a '
             'schema message or server handler — including login/auth (`lobby`) and GM commands (`gm`). '
             '**Missing** is the number of remaining opcodes in that system. **Fields** is the share of fields in '
             'implemented messages whose meaning is recovered (`_` in `schemas/*.jsch` are unmapped). '
             '**Overall** = opcodes × fields. Out of scope (excluded): %s.' % excl_summary, '',
             '| System | Opcodes | Missing | Fields | Overall |', '| :--- | ---: | ---: | ---: | :--- |']
    tot = [0, 0, 0, 0]
    for row in sorted(rows, key=lambda r: (-overall(r), -r['impl'], r['domain'])):
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


def _first_doc(path):
    """Extract the first line of a Python docstring or C top-of-file comment."""
    try:
        text = path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return ''
    if path.suffix == '.py':
        m = re.match(r'\s*(?:#[^\n]*\n\s*)*(?:from\s+__future__[^\n]*\n\s*)*(?:"""|\'\'\')(.+?)(?:"""|\'\'\')', text, re.S)
        if m:
            first = m.group(1).strip().splitlines()[0].strip().rstrip('.')
            return first[:72] + ('…' if len(first) > 72 else '')
    elif path.suffix in ('.c', '.h'):
        m = re.match(r'\s*/\*\s*(.+?)\s*(?:\n|\*/)', text)
        if m:
            first = m.group(1).strip().lstrip('*').strip()
            return first[:72] + ('…' if len(first) > 72 else '')
    return ''


def _tree_lines(root_dir, prefix='', max_depth=3, depth=0, collapse=None):
    collapse = collapse or {}
    entries = sorted(
        (p for p in root_dir.iterdir()
         if not p.name.startswith('.') and p.name != '__pycache__'
         and p.suffix not in ('.obj', '.dll', '.lib', '.exp', '.pyc')),
        key=lambda p: (not p.is_dir(), p.name.lower()),
    )
    out = []
    for idx, p in enumerate(entries):
        last = (idx == len(entries) - 1)
        branch = '└── ' if last else '├── '
        rel = p.relative_to(ROOT).as_posix()
        if p.is_dir():
            if rel in collapse:
                note = collapse[rel](p)
                out.append(f'{prefix}{branch}{p.name}/  # {note}')
            else:
                doc = _first_doc(p / '__init__.py') if (p / '__init__.py').is_file() else ''
                suffix = f'  # {doc}' if doc else ''
                out.append(f'{prefix}{branch}{p.name}/{suffix}')
                if depth + 1 < max_depth:
                    ext = '    ' if last else '│   '
                    out.extend(_tree_lines(p, prefix + ext, max_depth, depth + 1, collapse))
        else:
            if p.name == '__init__.py':
                continue
            doc = _first_doc(p)
            suffix = f'  # {doc}' if doc else ''
            out.append(f'{prefix}{branch}{p.name}{suffix}')
    return out


def render_architecture():
    collapse = {
        'src/darkblood/games/network/messages': lambda p: (
            f'{len(list(p.glob("*.py"))) - 1} schema-generated typed WireMessage modules'
        ),
        'client_hook/patches': lambda p: (
            f'{len(list(p.glob("*.c")))} modular patches: '
            + ', '.join(sorted(f.stem for f in p.glob('*.c')))
        ),
    }
    schema_count = len(list(SCHEMAS.glob('*.jsch')))
    lines = [
        '_Generated by `tools/gen_progress.py` on every push to main; do not edit by hand._',
        '',
        'The server is a Python package laid out like MHServerEmu so it can be ported to C# later:',
        '',
        '```text',
        'src/darkblood/',
        *_tree_lines(ROOT / 'src' / 'darkblood', max_depth=4, collapse=collapse),
        '',
        'client_hook/',
        *_tree_lines(ROOT / 'client_hook', max_depth=2, collapse=collapse),
        '',
        f'schemas/  # {schema_count} JSerBuffer wire schema domains (*.jsch -> tools/gen_messages.py)',
        'tools/    # launcher.py, gamectl.py, multibox.py, mcp_server.py, headless_client.py, gen_*.py',
        '```',
    ]
    return '\n'.join(lines)


def main():
    rows = collect()
    text = README.read_text(encoding='utf-8')
    if START not in text or END not in text:
        sys.exit('README.md lacks the %s / %s markers' % (START, END))
    head, rest = text.split(START, 1)
    tail = rest.split(END, 1)[1]
    new_readme = head + START + '\n' + render_readme(rows) + '\n' + END + tail
    if ARCH_START in new_readme and ARCH_END in new_readme:
        ahead, arest = new_readme.split(ARCH_START, 1)
        atail = arest.split(ARCH_END, 1)[1]
        new_readme = ahead + ARCH_START + '\n' + render_architecture() + '\n' + ARCH_END + atail
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
    print('Wrote README progress/architecture blocks and docs/UNMAPPED_FIELDS.md')


if __name__ == '__main__':
    main()
