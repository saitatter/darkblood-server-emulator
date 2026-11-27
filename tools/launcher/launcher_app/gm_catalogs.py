"""Lazy-loaded searchable GM ID catalogs and command parameter parser for the launcher."""
from dataclasses import dataclass, field
from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Dict, List, Optional, Tuple

from launcher_app.theme import ROOT

GM_IDS_DIR = ROOT / 'docs' / 'gm_ids'
GM_PINS_PATH = ROOT / 'data' / 'gm_pins.json'

CATALOG_LABELS = {
    'item': 'Item',
    'monster': 'Monster',
    'skill': 'Skill',
    'quest': 'Quest',
    'buff': 'Buff',
    'npc': 'NPC',
    'mount': 'Mount',
}

PARAM_TO_CATALOG = {
    'item_id': 'item',
    'monster_id': 'monster',
    'skill_number': 'skill',
    'skill_idx': 'skill',
    'quest_id': 'quest',
    'buff_id': 'buff',
    'npc_id': 'npc',
    'mount_id': 'mount',
}

EQUIPMENT_GROUP = 'Equipment'
EQUIPMENT_KINDS = ('Weapons', 'Armor', 'Shields', 'Accessories')
_ACCESSORY_PREFIXES = ('Aear', 'Anec', 'Arin')


def equipment_kind(item_id: str) -> str:
    """Slot group of an equipment ID (W* weapons; A* armor, Ashi shields, Aear/Anec/Arin accessories)."""
    if item_id.startswith('W'):
        return 'Weapons'
    if item_id.startswith('Ashi'):
        return 'Shields'
    if item_id.startswith(_ACCESSORY_PREFIXES):
        return 'Accessories'
    if item_id.startswith('A'):
        return 'Armor'
    return ''


_ROW_RE = re.compile(r'^\|\s*`([^`]+)`\s*\|\s*(.+?)\s*\|$')
_PARAM_TOKEN_RE = re.compile(r'(<[^>]+>|\[[^\]]+\])')


@dataclass(frozen=True)
class CatalogEntry:
    id: str
    name: str
    extra: str = ''
    search_key: str = ''
    category: str = ''  # the `## section` the entry came from, e.g. 'Equipment (Lv 1–15)'
    kind: str = ''      # equipment slot group from the ID prefix: Weapons, Armor, Shields, Accessories

    def display(self) -> str:
        if self.extra:
            return f'{self.id:<18}  {self.name}  ({self.extra})'
        return f'{self.id:<18}  {self.name}'

    def short_label(self) -> str:
        if self.name:
            return f'{self.id} — {self.name}'
        return self.id


@dataclass
class ParamSpec:
    name: str
    required: bool = True
    default: str = ''
    catalog: Optional[str] = None
    choices: List[str] = field(default_factory=list)


def _clean_cell(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == '`' and text[-1] == '`':
        text = text[1:-1]
    return text.strip()


def _parse_markdown_table(
    path: Path,
    *,
    name_col: int = 1,
    extra_cols: Tuple[int, ...] = (),
    only_section: Optional[str] = None,
    include_section: bool = False,
) -> List[CatalogEntry]:
    if not path.is_file():
        return []
    entries: List[CatalogEntry] = []
    seen = set()
    section = ''
    in_section = only_section is None
    for raw in path.read_text(encoding='utf-8', errors='replace').splitlines():
        line = raw.strip()
        if line.startswith('## '):
            section = re.sub(r'\s*\(\d+\)\s*$', '', line[3:].strip())
            if only_section is not None:
                in_section = section.lower().startswith(only_section.lower())
            continue
        if not in_section or not line.startswith('|'):
            continue
        m = _ROW_RE.match(line)
        if not m:
            continue
        item_id = m.group(1).strip()
        if not item_id or item_id in seen:
            continue
        cols = [_clean_cell(c) for c in m.group(2).split('|')]
        # cols[0] is the second table column (index 1 in full row)
        name_idx = name_col - 1
        name = cols[name_idx] if 0 <= name_idx < len(cols) else ''
        if name in ('—', '-'):
            name = ''
        extras = []
        if include_section and section:
            extras.append(section)
        for ci in extra_cols:
            c_idx = ci - 1
            if 0 <= c_idx < len(cols):
                val = cols[c_idx]
                if val and val not in ('—', '-'):
                    extras.append(val)
        kind = equipment_kind(item_id) if section.startswith(EQUIPMENT_GROUP) else ''
        if kind:
            extras.insert(1 if include_section and section else 0, kind)
        extra = ', '.join(extras)
        seen.add(item_id)
        entries.append(CatalogEntry(
            id=item_id,
            name=name,
            extra=extra,
            search_key=f'{item_id} {name} {extra}'.lower(),
            category=section,
            kind=kind,
        ))
    return entries


@lru_cache(maxsize=16)
def load_catalog(catalog_name: str, ids_dir: Path = GM_IDS_DIR) -> Tuple[CatalogEntry, ...]:
    """Load and cache all entries for a GM ID catalog."""
    if catalog_name == 'item':
        items = _parse_markdown_table(
            ids_dir / 'items.md', name_col=1, extra_cols=(2,), include_section=True,
        )
        equip = _parse_markdown_table(
            ids_dir / 'items_equipment.md', name_col=1, extra_cols=(2,), include_section=True,
        )
        seen = {e.id for e in items}
        merged = list(items) + [e for e in equip if e.id not in seen]
        return tuple(merged)
    if catalog_name == 'monster':
        return tuple(_parse_markdown_table(
            ids_dir / 'monsters.md', name_col=1, extra_cols=(2, 3),
        ))
    if catalog_name == 'skill':
        return tuple(_parse_markdown_table(
            ids_dir / 'skills.md', name_col=2, extra_cols=(1, 3),
        ))
    if catalog_name == 'quest':
        return tuple(_parse_markdown_table(
            ids_dir / 'quests.md', name_col=1, extra_cols=(2,), include_section=True,
        ))
    if catalog_name == 'buff':
        return tuple(_parse_markdown_table(
            ids_dir / 'buffs.md', name_col=1, extra_cols=(2,),
        ))
    if catalog_name == 'npc':
        return tuple(_parse_markdown_table(
            ids_dir / 'npcs.md', name_col=1,
        ))
    if catalog_name == 'mount':
        return tuple(_parse_markdown_table(
            ids_dir / 'mounts_and_pets.md', name_col=2, only_section='Mounts',
        ))
    return ()


@lru_cache(maxsize=16)
def _catalog_index(catalog_name: str, ids_dir: Path = GM_IDS_DIR) -> Dict[str, CatalogEntry]:
    return {e.id.lower(): e for e in load_catalog(catalog_name, ids_dir)}


def lookup_entry(catalog_name: str, item_id: str, ids_dir: Path = GM_IDS_DIR) -> Optional[CatalogEntry]:
    if not item_id:
        return None
    return _catalog_index(catalog_name, ids_dir).get(item_id.strip().lower())


def _split_section(section: str) -> Tuple[str, str]:
    """'Equipment (Lv 1–15)' -> ('Equipment', 'Lv 1–15'); other sections have no sub-part."""
    m = re.match(r'^(.*?)\s*\((.+)\)$', section)
    if m and m.group(1) == EQUIPMENT_GROUP:
        return m.group(1), m.group(2)
    return section, ''


def catalog_categories(catalog_name: str, ids_dir: Path = GM_IDS_DIR) -> List[Tuple[str, object]]:
    """Category menu tree for a catalog, in catalog order.

    Each node is (label, filter) or (label, [child nodes]); filters are
    'section:<name>', 'group:<name>' or 'kind:<name>' strings for search_catalog.
    Catalogs with fewer than two sections return an empty list.
    """
    groups: Dict[str, List[str]] = {}
    for e in load_catalog(catalog_name, ids_dir):
        if not e.category:
            continue
        group, _sub = _split_section(e.category)
        subs = groups.setdefault(group, [])
        if e.category not in subs:
            subs.append(e.category)
    if len(groups) < 2 and not any(len(v) > 1 for v in groups.values()):
        return []
    tree: List[Tuple[str, object]] = []
    for group, sections in groups.items():
        if len(sections) == 1 and _split_section(sections[0])[1] == '':
            tree.append((group.replace(' (Quick Reference)', ''), f'section:{sections[0]}'))
            continue
        children: List[Tuple[str, object]] = [(f'All {group.lower()}', f'group:{group}')]
        children += [(_split_section(sec)[1] or sec, f'section:{sec}') for sec in sections]
        if group == EQUIPMENT_GROUP:
            children.append(('', None))  # separator
            children += [(kind, f'kind:{kind}') for kind in EQUIPMENT_KINDS]
        tree.append((group, children))
    return tree


def category_label(category: Optional[str]) -> str:
    """Short text for a filter string ('section:Equipment (Lv 1–15)' -> 'Equipment (Lv 1–15)')."""
    if not category:
        return 'All'
    return category.split(':', 1)[1].replace(' (Quick Reference)', '')


def _in_category(entry: CatalogEntry, category: Optional[str]) -> bool:
    if not category:
        return True
    key, _, value = category.partition(':')
    if key == 'section':
        return entry.category == value
    if key == 'group':
        return _split_section(entry.category)[0] == value
    if key == 'kind':
        return entry.kind == value
    return True


def search_catalog(
    catalog_name: str,
    query: str,
    limit: int = 120,
    ids_dir: Path = GM_IDS_DIR,
    category: Optional[str] = None,
) -> Tuple[List[CatalogEntry], int]:
    """Filter catalog entries by multi-token substring match on ID, name and extra info.

    `category` is a filter from catalog_categories (None = everything).
    Returns (top_matches, total_match_count).
    """
    entries = load_catalog(catalog_name, ids_dir)
    if category:
        entries = tuple(e for e in entries if _in_category(e, category))
    q = (query or '').strip().lower()
    if not q:
        return list(entries[:limit]), len(entries)
    tokens = q.split()
    exact_id = []
    prefix_id = []
    name_starts = []
    other = []
    for e in entries:
        if not all(t in e.search_key for t in tokens):
            continue
        id_l = e.id.lower()
        if id_l == q:
            exact_id.append(e)
        elif id_l.startswith(tokens[0]):
            prefix_id.append(e)
        elif e.name.lower().startswith(tokens[0]):
            name_starts.append(e)
        else:
            other.append(e)
    all_matches = exact_id + prefix_id + name_starts + other
    return all_matches[:limit], len(all_matches)


def parse_command_params(params_str: str) -> List[ParamSpec]:
    """Parse GM_COMMANDS.md parameter syntax into structured ParamSpec entries.

    Examples:
        '<item_id> [count=1] [expire_min]'
        '<buff_id> [monster_id]'
        '<mount_id | off>'
        '<weapon | cloth> <level>'
    """
    if not params_str or params_str.strip() in ('—', '-'):
        return []
    specs: List[ParamSpec] = []
    for token in _PARAM_TOKEN_RE.findall(params_str):
        required = token.startswith('<')
        inner = token[1:-1].strip()
        if not inner:
            continue
        parts = [p.strip() for p in inner.split('|') if p.strip()]
        if len(parts) > 1:
            # Either '<mount_id | off>' (catalog + literal choices) or '<weapon | cloth>' (pure enum)
            catalog = None
            base_name = parts[0]
            choices = []
            for p in parts:
                key = p.split('=', 1)[0].strip().lower()
                if key in PARAM_TO_CATALOG and catalog is None:
                    catalog = PARAM_TO_CATALOG[key]
                    base_name = key
                elif not any(ch in p for ch in (' ', '.')):
                    choices.append(p)
            if catalog is not None:
                specs.append(ParamSpec(name=base_name, required=required, catalog=catalog, choices=choices))
            elif all(re.match(r'^[a-zA-Z0-9_-]+$', p) for p in parts):
                # Pure enum like '<weapon | cloth>' or '<on | off>' (exclude '<value | off>' where 'value' is numeric)
                if parts[0].lower() in ('value', 'quest_id'):
                    specs.append(ParamSpec(
                        name=parts[0].lower(),
                        required=required,
                        catalog=PARAM_TO_CATALOG.get(parts[0].lower()),
                        choices=parts[1:] if parts[0].lower() == 'value' else [],
                    ))
                else:
                    specs.append(ParamSpec(name=inner, required=required, default=parts[0], choices=parts))
            else:
                specs.append(ParamSpec(name=parts[0], required=required))
        else:
            if '=' in inner:
                pname, default = inner.split('=', 1)
                pname, default = pname.strip(), default.strip()
            else:
                pname, default = inner, ''
            key = pname.lower()
            specs.append(ParamSpec(
                name=pname,
                required=required,
                default=default,
                catalog=PARAM_TO_CATALOG.get(key),
            ))
    return specs


def suggest_pin_label(command: str, ids_dir: Path = GM_IDS_DIR) -> str:
    """Build a friendly default label for a pinned GM command (resolving known IDs)."""
    cmd = (command or '').strip()
    if cmd.startswith('%'):
        cmd = cmd[1:].strip()
    parts = cmd.split()
    if not parts:
        return ''
    name = parts[0].lower()
    if len(parts) >= 2:
        arg1 = parts[1]
        cat_for_cmd = {
            'itemcall': 'item',
            'itemdrop': 'item',
            'moncall': 'monster',
            'summon': 'monster',
            'skill': 'skill',
            'buff': 'buff',
            'passivebuff': 'buff',
            'questenable': 'quest',
            'missionclear': 'quest',
            'questnpc': 'npc',
            'riding': 'mount',
        }.get(name)
        if cat_for_cmd:
            entry = lookup_entry(cat_for_cmd, arg1, ids_dir=ids_dir)
            if entry and entry.name:
                if name in ('itemcall', 'itemdrop') and len(parts) >= 3 and parts[2].isdigit() and int(parts[2]) > 1:
                    return f'{entry.name} x{parts[2]}'
                return entry.name
    return cmd


def _clean_gm_command(command) -> str:
    return str(command or '').strip().lstrip('%').strip()


def normalize_gm_pin(item) -> Optional[Dict[str, object]]:
    """Return ``{'label', 'commands'}`` for a pin/macro dict, or None when it has no commands."""
    if not isinstance(item, dict):
        return None
    raw = item.get('commands')
    if not isinstance(raw, list):
        return None
    commands = [c for c in (_clean_gm_command(x) for x in raw) if c]
    if not commands:
        return None
    label = str(item.get('label') or '').strip() or commands[0]
    return {'label': label, 'commands': commands}


def load_gm_pins(path: Path = GM_PINS_PATH) -> List[Dict[str, object]]:
    """Load pinned GM macros (label + ordered command list) from data/gm_pins.json."""
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    if not isinstance(raw, list):
        return []
    return [p for p in (normalize_gm_pin(x) for x in raw) if p]


def save_gm_pins(pins: List[Dict[str, object]], path: Path = GM_PINS_PATH) -> None:
    """Persist pinned GM macros to data/gm_pins.json (pins without commands are dropped)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = [p for p in (normalize_gm_pin(x) for x in pins) if p]
    path.write_text(json.dumps(clean, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def move_item(items: list, index: int, delta: int) -> int:
    """Move ``items[index]`` by ``delta`` positions in place; return its new index."""
    if not 0 <= index < len(items):
        return index
    new = max(0, min(len(items) - 1, index + delta))
    if new != index:
        items.insert(new, items.pop(index))
    return new
