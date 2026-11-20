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
}
RESERVED = {'r', 'b', 'data', 'cls', 'self', 'OPCODE'}
IDENT = re.compile(r'[A-Za-z_][A-Za-z0-9_]*$')


class SchemaError(Exception):
    pass


# ---------------------------------------------------------------- model

@dataclass
class Type:
    kind: str                     # scalar | wstr | rest | vector | map | struct | extern
    name: str = ''                # scalar name or struct/extern name
    args: List['Type'] = field(default_factory=list)

    def __str__(self):
        if self.kind == 'vector':
            return 'vector<%s>' % self.args[0]
        if self.kind == 'map':
            return 'map<%s,%s>' % (self.args[0], self.args[1])
        return self.name or self.kind


@dataclass
class Field:
    type: Type
    name: str
    default: Optional[str] = None
    comment: str = ''


@dataclass
class Struct:
    name: str
    fields: List[Field] = field(default_factory=list)
    doc: List[str] = field(default_factory=list)
    opcode: Optional[int] = None  # set for messages
    client_name: str = ''
    direction: str = ''           # request | reply
    ok_only: bool = False
    bare: bool = False

    @property
    def is_message(self):
        return self.opcode is not None


@dataclass
class Extern:
    name: str
    module: str
    readable: bool


@dataclass
class Schema:
    path: Path
    domain: str = ''
    doc: str = ''
    externs: Dict[str, Extern] = field(default_factory=dict)
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

    def fail(self, message):
        raise SchemaError('%s: %s' % (self.where, message))

    def parse_type(self, text):
        m = re.match(r'(vector|map)<(.*)>$', text)
        if m:
            args = [self.parse_type(a) for a in split_type_args(m.group(2))]
            if len(args) != (1 if m.group(1) == 'vector' else 2):
                self.fail('wrong number of type arguments in %s' % text)
            if m.group(1) == 'map' and args[0].kind not in ('scalar', 'wstr'):
                self.fail('map keys must be scalars or wstr')
            return Type(m.group(1), args=args)
        if text in SCALARS:
            return Type('scalar', text)
        if text in ('wstr', 'rest'):
            return Type(text)
        if text in self.schema.externs:
            return Type('extern', text)
        if any(s.name == text and not s.is_message for s in self.schema.structs):
            return Type('struct', text)
        self.fail('unknown type %r (structs must be defined before use)' % text)

    def parse_field(self, line, owner):
        code, _, comment = line.partition('#')
        m = re.match(r'(\S+)\s+([A-Za-z_]\w*)\s*(?:=\s*(\S+))?\s*$', code.strip())
        if not m:
            self.fail('cannot parse field: %r' % line)
        ftype = self.parse_type(m.group(1))
        name = m.group(2)
        if name in RESERVED or name in ('header', 'result'):
            self.fail('reserved field name %r' % name)
        if any(f.name == name for f in owner.fields):
            self.fail('duplicate field %r' % name)
        if owner.fields and owner.fields[-1].type.kind == 'rest':
            self.fail('rest must be the last field')
        if ftype.kind == 'rest' and not owner.is_message:
            self.fail('rest is only allowed in messages')
        default = m.group(3)
        if default is not None and ftype.kind != 'scalar':
            self.fail('defaults are only allowed on scalars')
        if default is not None:
            default = {'true': 'True', 'false': 'False'}.get(default, default)
        owner.fields.append(Field(ftype, name, default, comment.strip()))

    def parse(self):
        current = None
        text = self.schema.path.read_text(encoding='utf-8')
        for number, raw in enumerate(text.splitlines(), 1):
            self.where = '%s:%d' % (self.schema.path.name, number)
            line = raw.strip()
            if not line or (line.startswith('#') and not line.startswith('##')):
                continue
            if current is not None:
                if line == 'end':
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
                m = re.match(r'extern\s+(\w+)\s+from\s+([\w.]+)(\s+readable)?$', line)
                if not m:
                    self.fail('expected: extern NAME from MODULE [readable]')
                self.schema.externs[m.group(1)] = Extern(m.group(1), m.group(2), bool(m.group(3)))
            elif words[0] == 'struct' and len(words) == 2:
                current = Struct(words[1])
            elif words[0] == 'message' and len(words) >= 4:
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
        name, direction, flags = words[2], words[3], set(words[4:])
        if direction not in ('request', 'reply'):
            self.fail('direction must be request or reply')
        unknown = flags - {'ok_only', 'bare'}
        if unknown:
            self.fail('unknown flags %s' % sorted(unknown))
        if opcode not in self.names:
            self.fail('opcode %d is not in assets/opcodes.tsv' % opcode)
        client = self.names[opcode]
        if (direction == 'request') != client.endswith('_REQ'):
            self.fail('%s does not look like a %s' % (client, direction))
        if 'ok_only' in flags and direction != 'reply':
            self.fail('ok_only applies to replies')
        if any(s.opcode == opcode for s in self.schema.structs):
            self.fail('opcode %d defined twice' % opcode)
        return Struct(name, opcode=opcode, client_name=client, direction=direction,
                      ok_only='ok_only' in flags, bare='bare' in flags)

    def finish(self, struct):
        if struct.bare and struct.fields:
            self.fail('bare messages carry no fields')
        self.schema.structs.append(struct)


def load_schemas():
    names = client_names()
    schemas = [Parser(p, names).parse() for p in sorted(SCHEMA_DIR.glob('*.jsch'))]
    seen = {}
    for schema in schemas:
        for s in schema.structs:
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
    def readable(self, t):
        if t.kind == 'extern':
            return self.schema.externs[t.name].readable
        if t.kind == 'struct':
            return all(self.readable(f.type) for f in self.structs[t.name].fields)
        return all(self.readable(a) for a in t.args)

    def py_type(self, t):
        if t.kind == 'scalar':
            return SCALARS[t.name][1]
        if t.kind == 'wstr':
            return 'str'
        if t.kind == 'rest':
            return 'bytes'
        if t.kind == 'vector':
            return 'list[%s]' % self.py_type(t.args[0])
        if t.kind == 'map':
            return 'dict[%s, %s]' % (self.py_type(t.args[0]), self.py_type(t.args[1]))
        return t.name

    def default(self, f):
        t = f.type
        if t.kind == 'scalar':
            if f.default is not None:
                return f.default
            return {'bool': 'False', 'float': '0.0'}.get(SCALARS[t.name][1], '0')
        if t.kind == 'wstr':
            return "''"
        if t.kind == 'rest':
            return "b''"
        factory = {'vector': 'list', 'map': 'dict'}.get(t.kind, t.name)
        return 'field(default_factory=%s)' % factory

    def enc(self, t, expr, depth=0):
        """Expression producing the wire bytes of value `expr`."""
        if t.kind == 'scalar':
            return "struct.pack('<%s', %s)" % (SCALARS[t.name][0], expr)
        if t.kind == 'wstr':
            return 'wide_string(%s)' % expr
        if t.kind == 'rest':
            return 'bytes(%s)' % expr
        if t.kind in ('struct', 'extern'):
            return '%s.encode()' % expr
        e = 'e%d' % depth
        if t.kind == 'vector':
            item = t.args[0]
            if item.kind == 'scalar':
                body = "struct.pack('<%%d%s' %% len(%s), *%s)" % (SCALARS[item.name][0], expr, expr)
            else:
                body = "b''.join(%s for %s in %s)" % (self.enc(item, e, depth + 1), e, expr)
            return "b'\\x10' + varuint(len(%s)) + %s" % (expr, body)
        k, v = 'k%d' % depth, 'v%d' % depth
        pair = "b'\\x0f' + %s + %s" % (self.enc(t.args[0], k, depth + 1), self.enc(t.args[1], v, depth + 1))
        return "b'\\x17' + varuint(len(%s)) + b''.join(%s for %s, %s in %s.items())" % (expr, pair, k, v, expr)

    def dec(self, t, reader='r', depth=0):
        """Expression reading one value of type `t` from `reader`."""
        if t.kind == 'scalar':
            return '%s.%s()' % (reader, SCALARS[t.name][2])
        if t.kind == 'wstr':
            return '%s.read_wstring()' % reader
        if t.kind == 'rest':
            return '%s.read_rest()' % reader
        if t.kind in ('struct', 'extern'):
            return '%s.read(%s)' % (t.name, reader)
        inner = 'r%d' % (depth + 1)
        if t.kind == 'vector':
            return '%s.read_tagged_vector(lambda %s: %s)' % (reader, inner, self.dec(t.args[0], inner, depth + 1))
        return '%s.read_tagged_map(lambda %s: %s, lambda %s: %s)' % (
            reader, inner, self.dec(t.args[0], inner, depth + 1), inner, self.dec(t.args[1], inner, depth + 1))

    # -- emitters
    def encode_lines(self, fields, ok_only):
        """Statements appending each field to bytearray `b`; consecutive scalars share one pack."""
        lines, run = [], []

        def flush():
            if run:
                fmt = ''.join(SCALARS[f.type.name][0] for f in run)
                args = ', '.join('self.%s' % f.name for f in run)
                lines.append("b += struct.pack('<%s', %s)" % (fmt, args))
                run.clear()

        for index, f in enumerate(fields):
            if f.type.kind == 'scalar':
                run.append(f)
            else:
                flush()
                lines.append('b += %s' % self.enc(f.type, 'self.%s' % f.name))
            if ok_only and index == 0:
                flush()
                lines.append('if self.result != 0:')
                lines.append('    return bytes(b)')
        flush()
        return lines

    def emit_struct(self, s):
        out = ['', '', '@dataclass', 'class %s:' % s.name]
        doc = list(s.doc)
        if s.is_message:
            doc.insert(0, 'Opcode %d: %s (%s).' % (s.opcode, s.client_name, s.direction))
            if s.doc:
                doc.insert(1, '')
        out += self.docstring(doc)
        fields = list(s.fields)
        if s.is_message:
            out.append('    OPCODE: ClassVar[int] = %d' % s.opcode)
            if not s.bare:
                if s.direction == 'request':
                    head = Field(Type('scalar', 'i32'), 'header', 'REQUEST_HEADER')
                else:
                    head = Field(Type('scalar', 'i32'), 'result', '0')
                fields.insert(0, head)
        for f in fields:
            line = '    %s: %s = %s' % (f.name, self.py_type(f.type), self.default(f))
            if f.comment:
                line += '  # ' + f.comment
            out.append(line)
        out += ['', '    def encode(self) -> bytes:']
        if not fields:
            out.append("        return b''")
        else:
            out.append('        b = bytearray()')
            out += ['        ' + line for line in self.encode_lines(fields, s.ok_only)]
            out.append('        return bytes(b)')
        if self.readable(Type('struct', s.name)) if not s.is_message else all(self.readable(f.type) for f in fields):
            out += self.emit_read(s, fields)
        return out

    def emit_read(self, s, fields):
        out = ['']
        if s.is_message:
            out += ['    @classmethod', "    def decode(cls, data: bytes) -> '%s':" % s.name]
            if fields:
                out.append('        r = JSerBufferReader(data)')
        else:
            out += ['    @classmethod', "    def read(cls, r: JSerBufferReader) -> '%s':" % s.name]
        for index, f in enumerate(fields):
            out.append('        %s = %s' % (f.name, self.dec(f.type)))
            if s.ok_only and index == 0:
                out.append('        if result != 0:')
                out.append('            return cls(result=result)')
        args = ', '.join('%s=%s' % (f.name, f.name) for f in fields)
        out.append('        return cls(%s)' % args)
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
        jser = ['JSerBufferReader', 'REQUEST_HEADER', 'varuint', 'wide_string']
        jser = [n for n in jser if re.search(r'\b%s\b' % n, text)]
        head = [
            '# Generated by tools/gen_messages.py from %s. DO NOT EDIT.' % rel,
            '"""%s"""' % (schema.doc or schema.domain),
            'from __future__ import annotations',
            '',
        ]
        if 'struct.' in text:
            head.append('import struct')
        head.append('from dataclasses import dataclass%s' % (', field' if 'field(' in text else ''))
        head.append('from typing import ClassVar')
        head.append('')
        if jser:
            head.append('from darkblood.core.serialization.jser import %s' % ', '.join(jser))
        for ext in schema.externs.values():
            head.append('from %s import %s' % (ext.module, ext.name))
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
