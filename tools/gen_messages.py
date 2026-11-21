#!/usr/bin/env python3
"""Generate wire message classes from schemas/*.jsch.

The schema files are the source of truth for message layouts, in the way
MHServerEmu keeps .proto files and generates C# from them. Dark Blood has no
embedded schemas (JSerBuffer is not protobuf), so the .jsch files are written
by hand from the recovered client readers and writers; the opcode names come
from the client's own table in assets/opcodes.tsv.

Only a Python backend exists today. The parser produces a plain model
(Schema/Struct/Field), so a C# backend for the port can be added next to
PythonBackend without touching the schemas.

    python tools/gen_messages.py           # rewrite generated modules
    python tools/gen_messages.py --check   # exit 1 if any module is stale

Format: see schemas/README.md.
"""
import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = ROOT / 'schemas'
OUTPUT_DIR = ROOT / 'src' / 'darkblood' / 'games' / 'network' / 'messages'
OPCODES = ROOT / 'assets' / 'opcodes.tsv'

# name -> (struct format char, python type, reader method)
SCALARS = {
    'i8': ('b', 'int', 'read_i8'), 'u8': ('B', 'int', 'read_u8'),
    'i16': ('h', 'int', 'read_i16'), 'u16': ('H', 'int', 'read_u16'),
    'i32': ('i', 'int', 'read_i32'), 'u32': ('I', 'int', 'read_u32'),
    'i64': ('q', 'int', 'read_i64'), 'u64': ('Q', 'int', 'read_u64'),
    'f32': ('f', 'float', 'read_f32'), 'f64': ('d', 'float', 'read_f64'),
    'bool': ('?', 'bool', 'read_bool'),
    'h32': ('I', 'int', 'read_u32'),  # 32-bit JHashString: signed or unsigned input
}
TAGS = {'vector': 0x10, 'set': 0x13, 'map': 0x17, 'pairs': 0x17}
RESERVED = {'r', 'b', 'data', 'cls', 'self', 'OPCODE'}
IDENT = re.compile(r'[A-Za-z_][A-Za-z0-9_]*$')
ANON = '_'


class SchemaError(Exception):
    pass


# ---------------------------------------------------------------- model

@dataclass
class Type:
    kind: str           # scalar wstr ipv4 raw rest vector set map pairs array empty struct extern
    name: str = ''      # scalar/struct/extern name, or container kind for `empty`
    args: List['Type'] = field(default_factory=list)
    size: int = 0       # raw[N]

    def __str__(self):
        if self.kind in ('vector', 'set', 'array', 'pairs'):
            return '%s<%s>' % (self.kind, self.args[0])
        if self.kind == 'map':
            return 'map<%s,%s>' % (self.args[0], self.args[1])
        if self.kind == 'empty':
            return '%s<?>' % self.name
        if self.kind == 'raw':
            return 'raw[%d]' % self.size
        return self.name or self.kind


@dataclass
class Field:
    type: Type
    name: str           # ANON for constant fields
    default: Optional[str] = None
    comment: str = ''
    literal: bytes = b''  # kind == 'lit'
    cond: str = ''        # 'name' or '!name': present only when that earlier field is true/false

    @property
    def anonymous(self):
        return self.name == ANON


@dataclass
class Struct:
    name: str
    fields: List[Field] = field(default_factory=list)
    doc: List[str] = field(default_factory=list)
    opcode: Optional[int] = None  # set for messages
    client_name: str = ''
    direction: str = ''           # request | reply
    header: str = ''              # '' | 'header' | 'header?'
    ok_index: Optional[int] = None  # fields after this many are sent only when result == 0
    bare: bool = False

    @property
    def is_message(self):
        return self.opcode is not None


@dataclass
class Extern:
    name: str
    module: str
    readable: bool = False
    encode: str = 'encode'


@dataclass
class Schema:
    path: Path
    domain: str = ''
    doc: str = ''
    externs: Dict[str, Extern] = field(default_factory=dict)
    imports: Dict[str, str] = field(default_factory=dict)  # plain python names
    structs: List[Struct] = field(default_factory=list)


# ---------------------------------------------------------------- parser

def client_names():
    names = {}
    for line in OPCODES.read_text(encoding='utf-8').splitlines():
        parts = line.split('\t')
        if len(parts) >= 2 and parts[0].isdigit():
            names[int(parts[0])] = parts[1]
    return names


def split_type_args(text):
    depth, start, parts = 0, 0, []
    for i, ch in enumerate(text):
        if ch == '<':
            depth += 1
        elif ch == '>':
            depth -= 1
        elif ch == ',' and depth == 0:
            parts.append(text[start:i].strip())
            start = i + 1
    parts.append(text[start:].strip())
    return parts


class Parser:
    def __init__(self, path, names):
        self.schema = Schema(path)
        self.names = names
        self.where = ''
        self.cond = ''

    def fail(self, message):
        raise SchemaError('%s: %s' % (self.where, message))

    def parse_type(self, text):
        m = re.match(r'(vector|set|map|pairs|array)<(.*)>$', text)
        if m:
            kind, inner = m.groups()
            if inner == '?':
                if kind not in ('vector', 'set', 'map', 'array'):
                    self.fail('only vector/set/map/array may have an unknown element type')
                return Type('empty', kind)
            args = [self.parse_type(a) for a in split_type_args(inner)]
            if len(args) != (2 if kind == 'map' else 1):
                self.fail('wrong number of type arguments in %s' % text)
            if kind in ('map', 'set') and args[0].kind not in ('scalar', 'wstr'):
                self.fail('%s keys must be scalars or wstr' % kind)
            if kind == 'pairs' and args[0].kind != 'extern':
                self.fail('pairs<T> needs an extern type whose encoder writes 0x0F, key and value')
            return Type(kind, args=args)
        m = re.match(r'raw\[(\d+)\]$', text)
        if m:
            return Type('raw', size=int(m.group(1)))
        if text in SCALARS:
            return Type('scalar', text)
        if text in ('wstr', 'wstrz', 'wrest', 'rest', 'ipv4'):
            return Type(text)
        if text in self.schema.externs:
            return Type('extern', text)
        if any(s.name == text and not s.is_message for s in self.schema.structs):
            return Type('struct', text)
        self.fail('unknown type %r (structs must be defined before use)' % text)

    def parse_default(self, text, ftype):
        m = re.match(r'(\w+)\((.*)\)$', text)
        if m:
            fn = m.group(1)
            if (fn not in self.schema.imports and fn not in self.schema.externs
                    and not any(s.name == fn for s in self.schema.structs)):
                self.fail('default factory %s is not imported' % fn)
            return text
        if ftype.kind in ('wstr', 'wstrz', 'wrest', 'ipv4'):
            if not re.match(r"'[^'\\]*'$", text):
                self.fail('string defaults use single quotes')
            return text
        if ftype.kind != 'scalar':
            self.fail('defaults are only allowed on scalars, strings and factories')
        if text in ('true', 'false'):
            return 'True' if text == 'true' else 'False'
        if not re.match(r'-?(0x[0-9A-Fa-f]+|\d+(\.\d+)?)$', text):
            self.fail('bad default %r' % text)
        return text

    def parse_field(self, line, owner):
        code, _, comment = line.partition('#')
        code, comment = code.strip(), comment.strip()
        if owner.fields and owner.fields[-1].type.kind in ('rest', 'wrest'):
            self.fail('rest must be the last field')
        m = re.match(r'lit\s+([0-9A-Fa-f ]+)$', code)
        if m:
            raw = bytes.fromhex(m.group(1).replace(' ', ''))
            owner.fields.append(Field(Type('lit'), ANON, comment=comment, literal=raw, cond=self.cond))
            return
        m = re.match(r'(\S+)\s+([A-Za-z_]\w*)\s*(?:=\s*(.+?))?$', code)
        if not m:
            self.fail('cannot parse field: %r' % line)
        ftype = self.parse_type(m.group(1))
        name = m.group(2)
        default = self.parse_default(m.group(3), ftype) if m.group(3) else None
        if name != ANON:
            if name in RESERVED or name == 'header':
                self.fail('reserved field name %r' % name)
            if any(f.name == name for f in owner.fields):
                self.fail('duplicate field %r' % name)
        else:
            if ftype.kind in ('vector', 'set', 'map', 'pairs', 'array', 'struct', 'extern', 'rest', 'wrest'):
                self.fail('anonymous fields must be scalars, strings, raw bytes or vector<?>')
            if default and default.endswith(')'):
                self.fail('anonymous fields take constant defaults')
        if ftype.kind == 'empty' and name != ANON:
            self.fail('%s must be anonymous (_)' % ftype)
        if ftype.kind in ('rest', 'wrest') and not owner.is_message:
            self.fail('rest is only allowed in messages')
        owner.fields.append(Field(ftype, name, default, comment, cond=self.cond))

    def parse(self):
        current = None
        text = self.schema.path.read_text(encoding='utf-8')
        for number, raw in enumerate(text.splitlines(), 1):
            self.where = '%s:%d' % (self.schema.path.name, number)
            line = raw.strip()
            if not line or (line.startswith('#') and not line.startswith('##')):
                continue
            if current is not None:
                m = re.match(r'if\s+(not\s+)?(\w+)$', line)
                if line == 'ok_only':
                    if current.ok_index is not None or not current.fields or self.cond:
                        self.fail('ok_only marker needs preceding fields, appears once, outside if blocks')
                    current.ok_index = len(current.fields)
                elif m:
                    if self.cond:
                        self.fail('if blocks do not nest')
                    target = next((f for f in current.fields if f.name == m.group(2)), None)
                    if target is None or target.type.kind != 'scalar':
                        self.fail('if needs an earlier scalar field, got %r' % m.group(2))
                    self.cond = ('!' if m.group(1) else '') + m.group(2)
                elif line == 'endif':
                    if not self.cond:
                        self.fail('endif without if')
                    self.cond = ''
                elif line == 'end':
                    if self.cond:
                        self.fail('missing endif')
                    self.finish(current)
                    current = None
                elif line.startswith('##'):
                    current.doc.append(line[2:].strip())
                else:
                    self.parse_field(line, current)
                continue
            words = line.split()
            if words[0] == 'domain':
                self.schema.domain = words[1]
                self.schema.doc = ' '.join(words[2:])
            elif words[0] == 'extern':
                m = re.match(r'extern\s+(\w+)\s+from\s+([\w.]+)((?:\s+\S+)*)$', line)
                if not m:
                    self.fail('expected: extern NAME from MODULE [readable] [encode=METHOD]')
                ext = Extern(m.group(1), m.group(2))
                for opt in m.group(3).split():
                    if opt == 'readable':
                        ext.readable = True
                    elif opt.startswith('encode='):
                        ext.encode = opt[len('encode='):]
                    else:
                        self.fail('unknown extern option %r' % opt)
                self.schema.externs[ext.name] = ext
            elif words[0] == 'import':
                m = re.match(r'import\s+(\w+)\s+from\s+([\w.]+)$', line)
                if not m:
                    self.fail('expected: import NAME from MODULE')
                self.schema.imports[m.group(1)] = m.group(2)
            elif words[0] == 'struct' and len(words) == 2:
                current = Struct(words[1])
            elif words[0] == 'message' and len(words) >= 3:
                current = self.message_header(words)
            else:
                self.fail('unexpected line: %r' % line)
            if current is not None:
                if not IDENT.match(current.name):
                    self.fail('bad name %r' % current.name)
                if any(s.name == current.name for s in self.schema.structs):
                    self.fail('duplicate name %r' % current.name)
        if current is not None:
            self.fail('missing end for %s' % current.name)
        if not self.schema.domain:
            raise SchemaError('%s: missing domain line' % self.schema.path.name)
        return self.schema

    def message_header(self, words):
        opcode = int(words[1])
        name, flags = words[2], set(words[3:])
        unknown = flags - {'ok_only', 'bare', 'header', 'header?'}
        if unknown:
            self.fail('unknown flags %s' % sorted(unknown))
        if opcode not in self.names:
            self.fail('opcode %d is not in assets/opcodes.tsv' % opcode)
        client = self.names[opcode]
        direction = 'request' if client.endswith('_REQ') else 'reply'
        header = 'header?' if 'header?' in flags else ('header' if 'header' in flags else '')
        if header and client.endswith('_ACK'):
            self.fail('%s is a server reply; only client-sent messages carry the header word' % client)
        if any(s.opcode == opcode for s in self.schema.structs):
            self.fail('opcode %d defined twice' % opcode)
        return Struct(name, opcode=opcode, client_name=client, direction=direction, header=header,
                      ok_index=1 if 'ok_only' in flags else None, bare='bare' in flags)

    def finish(self, struct):
        if struct.bare and (struct.fields or struct.header):
            self.fail('bare messages carry no header and no fields')
        if struct.ok_index is not None and (not struct.fields or struct.fields[0].name != 'result'
                               or struct.fields[0].type.kind != 'scalar'):
            self.fail('ok_only needs a scalar first field named result')
        self.schema.structs.append(struct)


def load_schemas():
    names = client_names()
    schemas = [Parser(p, names).parse() for p in sorted(SCHEMA_DIR.glob('*.jsch'))]
    seen, classes = {}, {}
    for schema in schemas:
        for s in schema.structs:
            if s.name in classes:
                raise SchemaError('%s defined in both %s and %s' % (s.name, classes[s.name], schema.path.name))
            classes[s.name] = schema.path.name
            if s.is_message:
                if s.opcode in seen:
                    raise SchemaError('opcode %d in both %s and %s' % (s.opcode, seen[s.opcode], schema.path.name))
                seen[s.opcode] = schema.path.name
    return schemas


# ---------------------------------------------------------------- python backend

class PythonBackend:
    def __init__(self, schema):
        self.schema = schema
        self.structs = {s.name: s for s in schema.structs}

    def output_path(self):
        return OUTPUT_DIR / ('%s.py' % self.schema.domain)

    # -- type helpers
    def wire_type(self, t):
        if t.kind == 'scalar':
            return 'bool' if t.name == 'bool' else t.name
        if t.kind in ('wstr', 'wstrz', 'wrest', 'ipv4', 'rest'):
            return t.kind
        if t.kind == 'raw':
            return 'Raw[%d]' % t.size
        if t.kind == 'empty':
            return {'vector': 'EmptyVector', 'set': 'EmptySet',
                    'map': 'EmptyMap', 'array': 'EmptyArray'}[t.name]
        if t.kind in ('vector', 'set', 'array', 'pairs'):
            cls = {'vector': 'Vector', 'set': 'Set', 'array': 'Array', 'pairs': 'Pairs'}[t.kind]
            return '%s[%s]' % (cls, self.wire_type(t.args[0]))
        if t.kind == 'map':
            return 'Map[%s, %s]' % (self.wire_type(t.args[0]), self.wire_type(t.args[1]))
        if t.kind == 'extern':
            ext = self.schema.externs[t.name]
            if ext.encode != 'encode':
                return "Extern[%s, '%s', %s]" % (t.name, ext.encode, ext.readable)
            if not ext.readable:
                return "Extern[%s, 'encode', False]" % t.name
            return t.name
        return t.name

    def default(self, f):
        t = f.type
        if f.default is not None:
            m = re.match(r'(\w+)\((.*)\)$', f.default)
            if m:
                if m.group(2):
                    return 'field(default_factory=lambda: %s)' % f.default
                return 'field(default_factory=%s)' % m.group(1)
            return f.default
        if t.kind == 'scalar':
            return {'bool': 'False', 'float': '0.0'}.get(SCALARS[t.name][1], '0')
        if t.kind in ('wstr', 'wstrz', 'wrest'):
            return "''"
        if t.kind == 'ipv4':
            return "'0.0.0.0'"
        if t.kind == 'rest':
            return "b''"
        if t.kind == 'raw':
            return 'bytes(%d)' % t.size
        factory = {'vector': 'list', 'set': 'list', 'array': 'list', 'pairs': 'list', 'map': 'dict'}.get(t.kind, t.name)
        return 'field(default_factory=%s)' % factory

    def const_value(self, f):
        if f.type.kind == 'empty':
            return None
        if f.default is not None:
            return f.default
        return self.default(f)

    # -- emitters
    def emit_struct(self, s):
        out = ['', '', '@dataclass', 'class %s(WireMessage):' % s.name]
        doc = list(s.doc)
        if s.is_message:
            doc.insert(0, 'Opcode %d: %s (%s).' % (s.opcode, s.client_name, s.direction))
            if s.doc:
                doc.insert(1, '')
        out += self.docstring(doc)
        fields = list(s.fields)
        if s.is_message:
            out.append('    OPCODE: ClassVar[int] = %d' % s.opcode)
        if s.header:
            out.append("    _WIRE_HEADER: ClassVar[str] = '%s'" % s.header)
            fields.insert(0, Field(Type('scalar', 'i32'), 'header', 'REQUEST_HEADER'))
        if s.ok_index is not None:
            out.append('    _WIRE_OK_INDEX: ClassVar[int] = %d' % s.ok_index)

        needs_layout = any(f.anonymous or f.type.kind == 'lit' or f.cond for f in fields)
        for f in fields:
            if f.anonymous or f.type.kind == 'lit':
                continue
            line = '    %s: %s = %s' % (f.name, self.wire_type(f.type), self.default(f))
            if f.comment:
                line += '  # ' + f.comment
            out.append(line)

        if needs_layout:
            out.append('    _WIRE_LAYOUT: ClassVar[tuple] = (')
            for f in fields:
                cond_arg = ", cond='%s'" % f.cond if f.cond else ''
                if f.type.kind == 'lit':
                    out.append('        Lit(%r%s),' % (f.literal, cond_arg))
                elif f.anonymous:
                    val = self.const_value(f)
                    if val is None:
                        out.append('        Const(%s%s),' % (self.wire_type(f.type), cond_arg))
                    else:
                        out.append('        Const(%s, %s%s),' % (self.wire_type(f.type), val, cond_arg))
                elif f.cond:
                    out.append("        ('%s', '%s')," % (f.name, f.cond))
                else:
                    out.append("        '%s'," % f.name)
            out.append('    )')
        elif not fields and not s.is_message:
            out.append('    pass')
        return out

    @staticmethod
    def docstring(lines):
        if not lines:
            return []
        if len(lines) == 1:
            return ['    """%s"""' % lines[0]]
        return ['    """%s' % lines[0]] + [('    ' + l) if l else '' for l in lines[1:]] + ['    """']

    def render(self):
        schema = self.schema
        rel = schema.path.relative_to(ROOT).as_posix()
        body = []
        for s in schema.structs:
            body += self.emit_struct(s)
        text = '\n'.join(body)
        head = [
            '# Generated by tools/gen_messages.py from %s. DO NOT EDIT.' % rel,
            '"""%s"""' % (schema.doc or schema.domain),
            'from __future__ import annotations',
            '',
            'from dataclasses import dataclass%s' % (', field' if 'field(' in text else ''),
        ]
        if 'ClassVar' in text:
            head.append('from typing import ClassVar')
        head.append('')
        if 'REQUEST_HEADER' in text:
            head.append('from darkblood.core.serialization.jser import REQUEST_HEADER')
        head.append('from darkblood.core.serialization.wire import *  # noqa: F403')
        modules = {}
        for ext in schema.externs.values():
            modules.setdefault(ext.module, []).append(ext.name)
        for name, module in schema.imports.items():
            modules.setdefault(module, []).append(name)
        for module in sorted(modules):
            head.append('from %s import %s' % (module, ', '.join(sorted(modules[module]))))
        names = [s.name for s in schema.structs]
        head += ['', '__all__ = [', *("    '%s'," % n for n in names), ']']
        return '\n'.join(head) + '\n' + text + '\n'


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--check', action='store_true', help='fail if a generated module is out of date')
    args = ap.parse_args()
    try:
        schemas = load_schemas()
    except SchemaError as exc:
        print('schema error: %s' % exc, file=sys.stderr)
        return 2
    stale = []
    for schema in schemas:
        backend = PythonBackend(schema)
        path, text = backend.output_path(), backend.render()
        # Compare without line endings: core.autocrlf checkouts turn LF into CRLF.
        current = path.read_bytes().decode('utf-8').replace('\r\n', '\n') if path.is_file() else None
        if current == text:
            continue
        if args.check:
            stale.append(path)
        else:
            path.write_bytes(text.encode('utf-8'))
            print('wrote %s' % path.relative_to(ROOT))
    for path in stale:
        print('stale: %s (run python tools/gen_messages.py)' % path.relative_to(ROOT), file=sys.stderr)
    return 1 if stale else 0


if __name__ == '__main__':
    sys.exit(main())
