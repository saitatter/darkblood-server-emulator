"""Generate GM command ID reference catalogs under docs/gm_ids/ from extracted client data.

Usage:
    python tools/codegen/gen_gm_reference.py [--source PATH]

Reads Lua dictionaries under <client_data>/lua_src/data/dict/ and UTF-16LE string
tables under <client_data>/files/data/localization_st/ to emit searchable Markdown
ID -> Name tables linked from docs/GM_COMMANDS.md.
"""
import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / 'docs' / 'gm_ids'

FIELD_STR_RE = re.compile(r'^ {4,6}(\w+) = "(.*)",?$')
FIELD_NUM_RE = re.compile(r'^ {4,6}(\w+) = (-?\d+(?:\.\d+)?),?$')


def resolve_client_data(explicit=None) -> Path:
    if explicit:
        return Path(explicit)
    env = os.environ.get('DARKBLOOD_CLIENT_DATA')
    if env:
        return Path(env)
    return ROOT.parent / 'darkblood-client-data'


def load_strings(loc_dir: Path) -> dict:
    strings = {}
    if not loc_dir.is_dir():
        return strings
    for path in sorted(loc_dir.glob('*_st.dat')):
        raw = path.read_bytes()
        text = raw.decode('utf-16le', errors='replace').lstrip('\ufeff')
        for line in text.splitlines():
            if '\t' not in line:
                continue
            key, val = line.split('\t', 1)
            key = key.strip()
            val = val.strip()
            if key and val:
                strings[key] = val
    return strings


def iter_section_entries(lua_path: Path, section_name: str):
    """Yield {field: value} dicts for top-level table entries inside assert(section_name({ ... }))."""
    if not lua_path.is_file():
        return
    in_section = False
    in_entry = False
    cur = {}
    depth = 0
    for line in lua_path.read_text(encoding='utf-8', errors='replace').splitlines():
        stripped = line.strip()
        if not in_section:
            if f'{section_name}({{' in line:
                # An empty table on one line (`LoadItem({})`) has no entries;
                # entering it would swallow the next section's entries.
                in_section = f'{section_name}({{}})' not in line
                depth = 1
            continue
        if stripped.startswith('})'):
            if cur:
                yield cur
                cur = {}
            in_section = False
            in_entry = False
            continue
        if line == '  {':
            cur = {}
            in_entry = True
            depth = 2
            continue
        if line in ('  },', '  }'):
            if in_entry and cur:
                yield cur
            cur = {}
            in_entry = False
            depth = 1
            continue
        if not in_entry:
            continue
        # Only capture top-level fields of the entry (4 spaces indent)
        if line.startswith('    ') and not line.startswith('     '):
            m = FIELD_STR_RE.match(line)
            if m:
                cur[m.group(1)] = m.group(2)
            else:
                m = FIELD_NUM_RE.match(line)
                if m:
                    cur[m.group(1)] = m.group(2)


def clean_md(text: str) -> str:
    if not text:
        return ''
    text = text.replace('\r', ' ').replace('\n', ' ').replace('\\n', ' ')
    text = re.sub(r'@C[0-9a-fA-F]{6}|@CR', '', text)
    text = text.replace('|', '\\|')
    return ' '.join(text.split())


def write_md(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='\n') as f:
        f.write(content)
    print(f'wrote {path.relative_to(ROOT)}')


def generate_items(dict_dir: Path, strings: dict):
    non_equip_files = [
        ('item_disposable.lua', 'Consumables & Bags'),
        ('item_randombox.lua', 'Random Boxes'),
        ('item_cash.lua', 'Cash Shop & Gems'),
        ('item_avatar.lua', 'Avatars'),
        ('item_beauty.lua', 'Beauty & Dyes'),
        ('item_reinforcingstone.lua', 'Reinforcing Stones'),
        ('item_magicstone.lua', 'Magic Stones'),
        ('monstercard.lua', 'Monster Cards'),
        ('item_quest.lua', 'Quest Items'),
        ('item_moneysetting.lua', 'Currency Items'),
        ('making.lua', 'Crafting Materials'),
        ('fishing.lua', 'Fishing (Fish, Bait & Permits)'),
        ('arena.lua', 'Arena Items'),
        ('mark.lua', 'Skill Runes'),
    ]
    equip_files = [
        ('item_equip1_15lv.lua', 'Equipment (Lv 1–15)'),
        ('item_equip20_27lv.lua', 'Equipment (Lv 20–27)'),
        ('item_equip30_37lv.lua', 'Equipment (Lv 30–37)'),
        ('item_equip40_47lv.lua', 'Equipment (Lv 40–47)'),
        ('item_equip50_57lv.lua', 'Equipment (Lv 50–57)'),
    ]

    def collect(files):
        sections = []
        bags = []
        seen = set()
        for fname, title in files:
            rows = []
            for e in iter_section_entries(dict_dir / fname, 'DictItem:LoadItem'):
                code = e.get('ItemID')
                if not code or code in seen:
                    continue
                seen.add(code)
                name_key = e.get('Name', '')
                name = (
                    strings.get(name_key)
                    or strings.get(f'Item_{code}')
                    or strings.get(f'Name_{code}')
                    or ''
                )
                lv = e.get('DemandLv', '')
                bag_size = int(e['BagSize']) if e.get('BagSize', '').isdigit() else 0
                row = (code, clean_md(name), lv, bag_size)
                rows.append(row)
                if bag_size > 0:
                    bags.append(row)
            rows.sort(key=lambda r: r[0])
            sections.append((title, rows))
        bags.sort(key=lambda r: (-r[3], r[0]))
        return bags, sections

    bags, non_equip_sections = collect(non_equip_files)
    _, equip_sections = collect(equip_files)

    # 1. docs/gm_ids/items.md (Bags + all non-equipment items)
    total_non_equip = sum(len(r) for _, r in non_equip_sections)
    lines = [
        '# GM Reference — Item IDs (Bags, Consumables, Cash, Boxes, Avatars & Misc)',
        '',
        'Generated by `tools/codegen/gen_gm_reference.py`. Used with **`%itemcall <ItemID> <Count>`** and **`%itemdrop <ItemID> <Count>`**.',
        'For Lv 1–57 weapons, armor and accessories, see [Equipment Item IDs](items_equipment.md).',
        '',
        f'Total non-equipment items: **{total_non_equip}** (including **{len(bags)}** inventory bags).',
        '',
        '## Inventory Bags (Quick Reference)',
        '',
        'Example: `%itemcall IbagU160 1` (then right-click the bag in inventory to equip it).',
        '',
        '| Item ID | Name | Slots (`BagSize`) |',
        '| :--- | :--- | ---: |',
    ]
    for code, name, _, bag_size in bags:
        lines.append(f'| `{code}` | {name or "—"} | {bag_size} |')
    lines.append('')

    for title, rows in non_equip_sections:
        lines.append(f'## {title} ({len(rows)})')
        lines.append('')
        lines.append('| Item ID | Name | Req Lv |')
        lines.append('| :--- | :--- | ---: |')
        for code, name, lv, _ in rows:
            lines.append(f'| `{code}` | {name or "—"} | {lv or "—"} |')
        lines.append('')

    write_md(OUT_DIR / 'items.md', '\n'.join(lines))

    # 2. docs/gm_ids/items_equipment.md
    total_equip = sum(len(r) for _, r in equip_sections)
    elines = [
        '# GM Reference — Equipment Item IDs (Lv 1–57)',
        '',
        'Generated by `tools/codegen/gen_gm_reference.py`. Used with **`%itemcall <ItemID> <Count>`** and **`%itemdrop <ItemID> <Count>`**.',
        'For bags, potions, random boxes, gems, avatars and quest items, see [Item IDs](items.md).',
        '',
        f'Total equipment items: **{total_equip}**.',
        '',
    ]
    for title, rows in equip_sections:
        elines.append(f'## {title} ({len(rows)})')
        elines.append('')
        elines.append('| Item ID | Name | Req Lv |')
        elines.append('| :--- | :--- | ---: |')
        for code, name, lv, _ in rows:
            elines.append(f'| `{code}` | {name or "—"} | {lv or "—"} |')
        elines.append('')

    write_md(OUT_DIR / 'items_equipment.md', '\n'.join(elines))


def generate_monsters(dict_dir: Path, strings: dict):
    rows = []
    seen = set()
    for e in iter_section_entries(dict_dir / 'monster.lua', 'DictMonster:LoadAbility'):
        code = e.get('ID')
        if not code or code in seen:
            continue
        seen.add(code)
        name_key = e.get('Name', '')
        name = strings.get(name_key) or strings.get(f'AMon_{code}') or ''
        lv = e.get('Lv', '')
        grade = e.get('Grade', '')
        rows.append((code, clean_md(name), lv, grade))
    rows.sort(key=lambda r: r[0])

    lines = [
        '# GM Reference — Monster IDs',
        '',
        'Generated by `tools/codegen/gen_gm_reference.py`. Used with **`%moncall <MonsterID> <Count>`**, **`%summon <MonsterID>`**, **`%questdropinfo <MonsterID>`**, and AI/buff commands.',
        '',
        f'Total monsters: **{len(rows)}**.',
        '',
        '| Monster ID | Name | Level | Grade |',
        '| :--- | :--- | ---: | :---: |',
    ]
    for code, name, lv, grade in rows:
        lines.append(f'| `{code}` | {name or "—"} | {lv or "—"} | {grade or "—"} |')
    lines.append('')
    write_md(OUT_DIR / 'monsters.md', '\n'.join(lines))


def generate_skills(dict_dir: Path, strings: dict):
    by_idx = {}
    for e in iter_section_entries(dict_dir / 'skill.lua', 'DictSkill:LoadSkill'):
        idx_raw = e.get('NameIndex')
        if idx_raw is None:
            continue
        try:
            idx = int(idx_raw)
        except ValueError:
            continue
        if idx in by_idx:
            continue
        code = e.get('ID', '')
        name_key = e.get('Name', '')
        name = strings.get(name_key) or ''
        lv = e.get('DemandLv', '')
        stype = e.get('Type', '')
        by_idx[idx] = (idx, code, clean_md(name), lv, stype)

    rows = sorted(by_idx.values(), key=lambda r: r[0])
    lines = [
        '# GM Reference — Skill IDs',
        '',
        'Generated by `tools/codegen/gen_gm_reference.py`. Used with **`%skill <SkillNumber> <Level>`**.',
        '',
        f'Total distinct skills: **{len(rows)}**.',
        '',
        '| Skill Number (`NameIndex`) | Internal ID | Name | Req Lv | Type |',
        '| ---: | :--- | :--- | ---: | :---: |',
    ]
    for idx, code, name, lv, stype in rows:
        lines.append(f'| `{idx}` | `{code}` | {name or "—"} | {lv or "—"} | {stype or "—"} |')
    lines.append('')
    write_md(OUT_DIR / 'skills.md', '\n'.join(lines))


def generate_quests(dict_dir: Path, strings: dict):
    quest_files = [
        ('quest_act1.lua', 'Act 1'),
        ('quest_act2.lua', 'Act 2'),
        ('quest_act3.lua', 'Act 3'),
        ('quest_act4.lua', 'Act 4'),
        ('quest_promotion.lua', 'Class Promotion'),
        ('quest_event.lua', 'Events & Miscellaneous'),
    ]
    sections = []
    seen = set()
    for fname, title in quest_files:
        rows = []
        for e in iter_section_entries(dict_dir / fname, 'DictQuest:LoadQuest'):
            qid = e.get('ID')
            if not qid or qid in seen:
                continue
            seen.add(qid)
            main_t = strings.get(e.get('MainTitle', '')) or strings.get(f'QTitleM_{qid}') or ''
            sub_t = strings.get(e.get('SubTitle', '')) or strings.get(f'QTitleS_{qid}') or ''
            full = clean_md(f'{main_t} — {sub_t}' if (main_t and sub_t and main_t != sub_t) else (main_t or sub_t))
            lv = e.get('ProperLv', '')
            rows.append((qid, full, lv))
        rows.sort(key=lambda r: r[0])
        sections.append((title, rows))

    total = sum(len(r) for _, r in sections)
    lines = [
        '# GM Reference — Quest IDs',
        '',
        'Generated by `tools/codegen/gen_gm_reference.py`. Used with **`%questenable <QuestID>`** and **`%missionclear <QuestID> <MissionIndex>`**.',
        '',
        f'Total quests: **{total}**.',
        '',
    ]
    for title, rows in sections:
        lines.append(f'## {title} ({len(rows)})')
        lines.append('')
        lines.append('| Quest ID | Title | Level |')
        lines.append('| :--- | :--- | ---: |')
        for qid, title_text, lv in rows:
            lines.append(f'| `{qid}` | {title_text or "—"} | {lv or "—"} |')
        lines.append('')
    write_md(OUT_DIR / 'quests.md', '\n'.join(lines))


def generate_buffs(dict_dir: Path, strings: dict):
    rows = []
    seen = set()
    for e in iter_section_entries(dict_dir / 'effect.lua', 'DictEffect:LoadEffect'):
        eid = e.get('EffectID')
        if not eid or eid in seen:
            continue
        seen.add(eid)
        name_key = e.get('EffectName', '')
        name = strings.get(name_key) or strings.get(f'EffName_{eid}') or ''
        tip = strings.get(f'EffectTip_{eid}') or strings.get(f'Effect_{eid}') or ''
        rows.append((eid, clean_md(name), clean_md(tip)))
    rows.sort(key=lambda r: r[0])

    lines = [
        '# GM Reference — Buff & Effect IDs',
        '',
        'Generated by `tools/codegen/gen_gm_reference.py`. Used with **`%buff <BuffID> [Target]`** and **`%passivebuff <BuffID> [Target]`**.',
        '',
        f'Total effects: **{len(rows)}**.',
        '',
        '| Buff / Effect ID | Name | Description |',
        '| :--- | :--- | :--- |',
    ]
    for eid, name, tip in rows:
        lines.append(f'| `{eid}` | {name or "—"} | {tip or "—"} |')
    lines.append('')
    write_md(OUT_DIR / 'buffs.md', '\n'.join(lines))


def generate_npcs(dict_dir: Path, strings: dict):
    rows = []
    seen = set()
    for e in iter_section_entries(dict_dir / 'npc.lua', 'DictMonster:LoadNpcAbility'):
        nid = e.get('ID')
        if not nid or nid in seen:
            continue
        seen.add(nid)
        name_key = e.get('Name', '')
        name = strings.get(name_key) or strings.get(f'NpcName_{nid}') or ''
        rows.append((nid, clean_md(name)))
    rows.sort(key=lambda r: r[0])

    lines = [
        '# GM Reference — NPC IDs',
        '',
        'Generated by `tools/codegen/gen_gm_reference.py`. Used with **`%questnpc <NpcID>`**.',
        '',
        f'Total NPCs: **{len(rows)}**.',
        '',
        '| NPC ID | Name |',
        '| :--- | :--- |',
    ]
    for nid, name in rows:
        lines.append(f'| `{nid}` | {name or "—"} |')
    lines.append('')
    write_md(OUT_DIR / 'npcs.md', '\n'.join(lines))


def generate_mounts_and_pets(dict_dir: Path, strings: dict):
    mounts = []
    for e in iter_section_entries(dict_dir / 'riding.lua', 'DictRiding:LoadRiding'):
        rid = e.get('ID')
        vid = e.get('VehicleID', '')
        if not rid:
            continue
        name = strings.get(f'V_name_{vid}') or strings.get(f'Name_{rid}') or ''
        mounts.append((rid, vid, clean_md(name)))
    mounts.sort(key=lambda r: r[0])

    pet_unit_names = {}
    for e in iter_section_entries(dict_dir / 'pet.lua', 'DictMonster:LoadAbility'):
        uid = e.get('ID')
        nk = e.get('Name', '')
        if uid and nk:
            pet_unit_names[uid] = strings.get(nk) or ''

    pets = []
    for e in iter_section_entries(dict_dir / 'pet.lua', 'DictPet:LoadPet'):
        pid = e.get('ID')
        uid = e.get('UnitID', '')
        if not pid:
            continue
        name = pet_unit_names.get(uid) or strings.get(f'NpcName_{uid}') or strings.get(f'Name_{pid}') or ''
        pets.append((pid, uid, clean_md(name)))
    pets.sort(key=lambda r: r[0])

    lines = [
        '# GM Reference — Mount (Riding) & Pet IDs',
        '',
        'Generated by `tools/codegen/gen_gm_reference.py`. Mount IDs are used with **`%riding <MountID | off>`**.',
        '',
        f'## Mounts ({len(mounts)})',
        '',
        '| Mount ID (`%riding`) | Vehicle ID | Name |',
        '| :--- | :--- | :--- |',
    ]
    for rid, vid, name in mounts:
        lines.append(f'| `{rid}` | `{vid}` | {name or "—"} |')
    lines.extend([
        '',
        f'## Pets ({len(pets)})',
        '',
        '| Pet ID | Unit ID | Name |',
        '| :--- | :--- | :--- |',
    ])
    for pid, uid, name in pets:
        lines.append(f'| `{pid}` | `{uid}` | {name or "—"} |')
    lines.append('')
    write_md(OUT_DIR / 'mounts_and_pets.md', '\n'.join(lines))


def main():
    parser = argparse.ArgumentParser(description='Generate GM ID reference markdown tables under docs/gm_ids/.')
    parser.add_argument('--source', help='Path to extracted darkblood-client-data directory')
    args = parser.parse_args()

    client_data = resolve_client_data(args.source)
    dict_dir = client_data / 'lua_src' / 'data' / 'dict'
    loc_dir = client_data / 'files' / 'data' / 'localization_st'
    if not dict_dir.is_dir():
        print(f'ERROR: client Lua dict directory not found: {dict_dir}', file=sys.stderr)
        return 1

    strings = load_strings(loc_dir)
    print(f'Loaded {len(strings)} localization strings from {loc_dir}')

    generate_items(dict_dir, strings)
    generate_monsters(dict_dir, strings)
    generate_skills(dict_dir, strings)
    generate_quests(dict_dir, strings)
    generate_buffs(dict_dir, strings)
    generate_npcs(dict_dir, strings)
    generate_mounts_and_pets(dict_dir, strings)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
