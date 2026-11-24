"""Typed JSerBuffer wire serialization (WireMessage + JSerBufferWriter).

Message and struct dataclasses declare their wire layout directly through type
annotations (i8, u8, i16, u16, i32, u32, h32, i64, u64, f32, f64, bool, wstr,
wstrz, wrest, ipv4, rest, Raw[N], Vector[T], Set[T], Map[K, V], Array[T],
Pairs[T], etc.). Codecs are compiled once per class so encode()/decode() infer
everything from the field types without manual struct.pack format strings.
"""
from __future__ import annotations

import struct
import sys
from dataclasses import dataclass, fields as dc_fields

from darkblood.core.serialization.jser import (
    JSerBufferReader,
    REQUEST_HEADER,
    REQUEST_HEADER_BYTES,
    varuint,
    wide_string,
)


# ------------------------------------------------------------------ writer

class JSerBufferWriter:
    """Symmetric counterpart to JSerBufferReader for building JSerBuffer payloads."""

    __slots__ = ('_buf',)

    def __init__(self):
        self._buf = bytearray()

    def to_bytes(self) -> bytes:
        return bytes(self._buf)

    def write_bytes(self, data: bytes) -> None:
        self._buf.extend(data)

    def write_varuint(self, value: int) -> None:
        self._buf.extend(varuint(value))

    def write_bool(self, value: bool) -> None:
        self._buf.extend(struct.pack('<?', bool(value)))

    def write_i8(self, value: int) -> None:
        self._buf.extend(struct.pack('<b', value))

    def write_u8(self, value: int) -> None:
        self._buf.extend(struct.pack('<B', value))

    def write_i16(self, value: int) -> None:
        self._buf.extend(struct.pack('<h', value))

    def write_u16(self, value: int) -> None:
        self._buf.extend(struct.pack('<H', value))

    def write_i32(self, value: int) -> None:
        self._buf.extend(struct.pack('<i', value))

    def write_u32(self, value: int) -> None:
        self._buf.extend(struct.pack('<I', value))

    def write_h32(self, value: int) -> None:
        self._buf.extend(struct.pack('<I', value & 0xFFFFFFFF))

    def write_i64(self, value: int) -> None:
        self._buf.extend(struct.pack('<q', value))

    def write_u64(self, value: int) -> None:
        self._buf.extend(struct.pack('<Q', value))

    def write_f32(self, value: float) -> None:
        self._buf.extend(struct.pack('<f', value))

    def write_f64(self, value: float) -> None:
        self._buf.extend(struct.pack('<d', value))

    def write_wstring(self, text: str) -> None:
        self._buf.extend(wide_string(text))

    def write_wstring_z(self, text: str) -> None:
        self._buf.extend(text.encode('utf-16le'))
        self._buf.extend(b'\x00\x00')

    def write_wrest(self, text: str) -> None:
        self._buf.extend(text.encode('utf-16le'))

    def write_ipv4(self, addr: str) -> None:
        self._buf.extend(bytes(int(o) for o in addr.split('.')))

    def write_raw(self, data: bytes, size: int) -> None:
        self._buf.extend(bytes(data).ljust(size, b'\x00')[:size])

    def write_rest(self, data: bytes) -> None:
        self._buf.extend(bytes(data))

    def write_empty_container(self, tag) -> None:
        if tag is not None:
            self._buf.append(tag)
        self._buf.append(0x80)


# ------------------------------------------------------------------ codecs

class WireCodec:
    """Base type descriptor usable both as a Python type annotation and a codec."""

    readable: bool = True

    def write(self, w: JSerBufferWriter, value) -> None:
        raise NotImplementedError

    def read(self, r: JSerBufferReader):
        raise NotImplementedError


class _ScalarCodec(WireCodec):
    def __init__(self, name: str, fmt: str, write_fn, read_fn, mask: int = 0):
        self.name = name
        self.fmt = fmt
        self._write_fn = write_fn
        self._read_fn = read_fn
        self._mask = mask

    def write(self, w: JSerBufferWriter, value) -> None:
        self._write_fn(w, value)

    def read(self, r: JSerBufferReader):
        return self._read_fn(r)

    def __repr__(self):
        return self.name


class _SimpleCodec(WireCodec):
    def __init__(self, name: str, write_fn, read_fn):
        self.name = name
        self._write_fn = write_fn
        self._read_fn = read_fn

    def write(self, w: JSerBufferWriter, value) -> None:
        self._write_fn(w, value)

    def read(self, r: JSerBufferReader):
        return self._read_fn(r)

    def __repr__(self):
        return self.name


class _RawFactory:
    def __getitem__(self, size: int) -> WireCodec:
        return _SimpleCodec(
            f'Raw[{size}]',
            lambda w, v, n=size: w.write_raw(v, n),
            lambda r, n=size: r.read_bytes(n),
        )


class _StructCodec(WireCodec):
    def __init__(self, cls, encode_method: str = 'encode', readable: bool = True):
        self.cls = cls
        self.encode_method = encode_method
        self.readable = readable

    def write(self, w: JSerBufferWriter, value) -> None:
        w.write_bytes(getattr(value, self.encode_method)())

    def read(self, r: JSerBufferReader):
        return self.cls.read(r)


class _SeqCodec(WireCodec):
    def __init__(self, kind: str, tag, item_codec: WireCodec, sort: bool = False):
        self.kind = kind
        self.tag = tag
        self.item = item_codec
        self.sort = sort
        self.readable = item_codec.readable and kind != 'pairs'

    def write(self, w: JSerBufferWriter, value) -> None:
        seq = sorted(value) if self.sort else value
        if self.tag is not None:
            w.write_u8(self.tag)
        w.write_varuint(len(seq))
        item = self.item
        for elem in seq:
            item.write(w, elem)

    def read(self, r: JSerBufferReader):
        if self.tag is not None:
            r.expect_tag(self.tag)
        return r.read_vector(self.item.read)


class _MapCodec(WireCodec):
    def __init__(self, key_codec: WireCodec, val_codec: WireCodec):
        self.key = key_codec
        self.val = val_codec
        self.readable = key_codec.readable and val_codec.readable

    def write(self, w: JSerBufferWriter, value) -> None:
        w.write_u8(0x17)
        w.write_varuint(len(value))
        k_codec, v_codec = self.key, self.val
        for k, v in sorted(value.items()):
            w.write_u8(0x0F)
            k_codec.write(w, k)
            v_codec.write(w, v)

    def read(self, r: JSerBufferReader):
        return r.read_tagged_map(self.key.read, self.val.read)


class _EmptyContainerCodec(WireCodec):
    def __init__(self, name: str, tag):
        self.name = name
        self.tag = tag

    def write(self, w: JSerBufferWriter, value=None) -> None:
        w.write_empty_container(self.tag)

    def read(self, r: JSerBufferReader):
        r.read_empty_container(self.tag)
        return None


class _SeqFactory:
    def __init__(self, kind: str, tag, sort: bool = False):
        self._kind = kind
        self._tag = tag
        self._sort = sort

    def __getitem__(self, item_type) -> WireCodec:
        return _SeqCodec(self._kind, self._tag, resolve_codec(item_type), sort=self._sort)


class _MapFactory:
    def __getitem__(self, args) -> WireCodec:
        k_type, v_type = args
        return _MapCodec(resolve_codec(k_type), resolve_codec(v_type))


class _ExternFactory:
    def __getitem__(self, args) -> WireCodec:
        if isinstance(args, tuple):
            cls, encode_method = args[0], args[1]
            readable = args[2] if len(args) > 2 else hasattr(cls, 'read')
            return _StructCodec(cls, encode_method=encode_method, readable=readable)
        return _StructCodec(args, readable=hasattr(args, 'read'))


# Public wire types (usable directly as dataclass field annotations)
i8 = _ScalarCodec('i8', 'b', JSerBufferWriter.write_i8, JSerBufferReader.read_i8)
u8 = _ScalarCodec('u8', 'B', JSerBufferWriter.write_u8, JSerBufferReader.read_u8)
i16 = _ScalarCodec('i16', 'h', JSerBufferWriter.write_i16, JSerBufferReader.read_i16)
u16 = _ScalarCodec('u16', 'H', JSerBufferWriter.write_u16, JSerBufferReader.read_u16)
i32 = _ScalarCodec('i32', 'i', JSerBufferWriter.write_i32, JSerBufferReader.read_i32)
u32 = _ScalarCodec('u32', 'I', JSerBufferWriter.write_u32, JSerBufferReader.read_u32)
h32 = _ScalarCodec('h32', 'I', JSerBufferWriter.write_h32, JSerBufferReader.read_u32)
i64 = _ScalarCodec('i64', 'q', JSerBufferWriter.write_i64, JSerBufferReader.read_i64)
u64 = _ScalarCodec('u64', 'Q', JSerBufferWriter.write_u64, JSerBufferReader.read_u64)
f32 = _ScalarCodec('f32', 'f', JSerBufferWriter.write_f32, JSerBufferReader.read_f32)
f64 = _ScalarCodec('f64', 'd', JSerBufferWriter.write_f64, JSerBufferReader.read_f64)
boolean = _ScalarCodec('bool', '?', JSerBufferWriter.write_bool, JSerBufferReader.read_bool)

wstr = _SimpleCodec('wstr', JSerBufferWriter.write_wstring, JSerBufferReader.read_wstring)
wstrz = _SimpleCodec('wstrz', JSerBufferWriter.write_wstring_z, JSerBufferReader.read_wstring_z)
wrest = _SimpleCodec(
    'wrest',
    JSerBufferWriter.write_wrest,
    lambda r: r.read_rest().decode('utf-16le', errors='replace').rstrip('\x00'),
)
ipv4 = _SimpleCodec(
    'ipv4',
    JSerBufferWriter.write_ipv4,
    lambda r: '.'.join(str(o) for o in r.read_bytes(4)),
)
rest = _SimpleCodec('rest', JSerBufferWriter.write_rest, JSerBufferReader.read_rest)

Raw = _RawFactory()
Vector = _SeqFactory('vector', 0x10)
Set = _SeqFactory('set', 0x13, sort=True)
Array = _SeqFactory('array', None)
Pairs = _SeqFactory('pairs', 0x17)
Map = _MapFactory()
Extern = _ExternFactory()

EmptyVector = _EmptyContainerCodec('vector<?>', 0x10)
EmptySet = _EmptyContainerCodec('set<?>', 0x13)
EmptyMap = _EmptyContainerCodec('map<?>', 0x17)
EmptyArray = _EmptyContainerCodec('array<?>', None)


def resolve_codec(annotation) -> WireCodec:
    """Resolve a Python type annotation into a WireCodec."""
    if isinstance(annotation, WireCodec):
        return annotation
    if annotation is bool:
        return boolean
    if isinstance(annotation, type) and hasattr(annotation, 'encode'):
        return _StructCodec(annotation, readable=hasattr(annotation, 'read'))
    raise TypeError(f'Unsupported wire type annotation: {annotation!r}')


# ------------------------------------------------------------------ layout steps

@dataclass(frozen=True)
class FieldStep:
    name: str
    codec: WireCodec
    cond: str = ''
    optional_header: bool = False


@dataclass(frozen=True)
class ConstStep:
    codec: WireCodec
    value: object = None
    cond: str = ''


@dataclass(frozen=True)
class LitStep:
    data: bytes
    cond: str = ''


@dataclass(frozen=True)
class ComputedStep:
    codec: WireCodec
    fn: object
    cond: str = ''


def Const(wire_type, value=None, cond: str = '') -> ConstStep:
    return ConstStep(resolve_codec(wire_type), value, cond)


def Lit(data: bytes, cond: str = '') -> LitStep:
    return LitStep(data, cond)


def Computed(wire_type, fn, cond: str = '') -> ComputedStep:
    """Encode-only wire step whose value is computed from the instance (`fn(self)`)."""
    return ComputedStep(resolve_codec(wire_type), fn, cond)


def _cond_holds(cond: str, getter) -> bool:
    if not cond:
        return True
    if cond.startswith('!'):
        return not getter(cond[1:])
    return bool(getter(cond))


def _resolve_annotations(cls):
    """Resolve cls.__annotations__ (including PEP 563 string annotations) without typing._type_check."""
    ns = sys.modules[cls.__module__].__dict__
    out = {}
    for name, ann in cls.__dict__.get('__annotations__', {}).items():
        if name == 'OPCODE' or name.startswith('_WIRE_'):
            continue
        out[name] = eval(ann, ns) if isinstance(ann, str) else ann
    return out


def _compile_plan(cls):
    """Compile the wire step list for a WireMessage subclass once on first use."""
    hints = _resolve_annotations(cls)
    raw_layout = cls.__dict__.get('_WIRE_LAYOUT')
    header_mode = cls.__dict__.get('_WIRE_HEADER', '')
    steps = []

    if raw_layout is not None:
        # Explicit layout tuple containing field names, (name, cond), Const(...), Lit(...), Computed(...)
        for item in raw_layout:
            if isinstance(item, (ConstStep, LitStep, ComputedStep)):
                steps.append(item)
            elif isinstance(item, tuple):
                fname, cond = item
                steps.append(FieldStep(fname, resolve_codec(hints[fname]), cond=cond,
                                       optional_header=(fname == 'header' and header_mode == 'header?')))
            else:
                steps.append(FieldStep(item, resolve_codec(hints[item]),
                                       optional_header=(item == 'header' and header_mode == 'header?')))
    else:
        for f in dc_fields(cls):
            if f.name in hints:
                steps.append(FieldStep(
                    f.name, resolve_codec(hints[f.name]),
                    optional_header=(f.name == 'header' and header_mode == 'header?'),
                ))

    plan = tuple(steps)
    cls._WIRE_PLAN = plan
    cls._WIRE_READABLE = (
        all(s.codec.readable for s in plan if isinstance(s, FieldStep))
        and not any(isinstance(s, ComputedStep) for s in plan)
    )
    return plan


class WireMessage:
    """Base class for typed JSerBuffer messages and structs.

    Subclasses simply declare dataclass fields annotated with wire types
    (i32, u16, h32, wstr, Vector[Item], ...). encode(), read(), and decode()
    are inferred automatically from those field types.
    """

    _WIRE_HEADER: str = ''
    _WIRE_OK_INDEX = None
    _WIRE_LAYOUT = None
    _WIRE_PLAN = None
    _WIRE_READABLE: bool = True

    def encode(self) -> bytes:
        cls = type(self)
        plan = cls.__dict__.get('_WIRE_PLAN')
        if plan is None:
            plan = _compile_plan(cls)
        if not plan:
            return b''
        w = JSerBufferWriter()
        ok_index = cls.__dict__.get('_WIRE_OK_INDEX')
        for idx, step in enumerate(plan):
            if step.cond and not _cond_holds(step.cond, lambda n: getattr(self, n)):
                pass
            elif isinstance(step, FieldStep):
                step.codec.write(w, getattr(self, step.name))
            elif isinstance(step, ConstStep):
                step.codec.write(w, step.value)
            elif isinstance(step, ComputedStep):
                step.codec.write(w, step.fn(self))
            else:
                w.write_bytes(step.data)
            if ok_index is not None and idx == ok_index - 1 and self.result != 0:
                return w.to_bytes()
        return w.to_bytes()

    @classmethod
    def read(cls, r: JSerBufferReader):
        plan = cls.__dict__.get('_WIRE_PLAN')
        if plan is None:
            plan = _compile_plan(cls)
        if not cls._WIRE_READABLE:
            raise TypeError(f'{cls.__name__} contains non-readable extern fields')
        kw = {}
        ok_index = cls.__dict__.get('_WIRE_OK_INDEX')
        for idx, step in enumerate(plan):
            if step.cond and not _cond_holds(step.cond, kw.__getitem__):
                pass
            elif isinstance(step, FieldStep):
                if step.optional_header:
                    kw[step.name] = r.read_i32() if r.peek(4) == REQUEST_HEADER_BYTES else REQUEST_HEADER
                else:
                    kw[step.name] = step.codec.read(r)
            elif isinstance(step, ConstStep):
                step.codec.read(r)
            else:
                r.expect_bytes(step.data)
            if ok_index is not None and idx == ok_index - 1 and kw['result'] != 0:
                return cls(**kw)
        return cls(**kw)

    @classmethod
    def decode(cls, data: bytes):
        return cls.read(JSerBufferReader(data))


__all__ = [
    'Array', 'Computed', 'Const', 'EmptyArray', 'EmptyMap', 'EmptySet', 'EmptyVector',
    'Extern', 'JSerBufferWriter', 'Lit', 'Map', 'Pairs', 'Raw', 'Set',
    'Vector', 'WireCodec', 'WireMessage', 'boolean', 'f32', 'f64', 'h32',
    'i16', 'i32', 'i64', 'i8', 'ipv4', 'rest', 'u16', 'u32', 'u64', 'u8',
    'wrest', 'wstr', 'wstrz',
]
