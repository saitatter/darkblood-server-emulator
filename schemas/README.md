# Message schemas

`schemas/*.jsch` describe wire messages. `tools/gen_messages.py` turns each
file into `src/darkblood/games/network/messages/<domain>.py`. The generated
modules start with `DO NOT EDIT`. To change one, edit the schema and run:

```
python tools/gen_messages.py           # regenerate
python tools/gen_messages.py --check   # fail when a module is stale (also a unit test)
```

This mirrors MHServerEmu, which keeps the `.proto` files it extracted from its
client in `proto/` and generates C# with protogen. Dark Blood uses JSerBuffer,
not protobuf, so it ships no schemas. These files are written by hand from the
recovered readers and writers. Only the opcode names come from the client
(`assets/opcodes.tsv`), and the generator checks each opcode against that
table. A C# backend for the port can be added to the generator. The schemas
stay as they are.

Converted so far: `mail`. Other domains are still hand-written dataclasses.

## Format

```
# line comment
domain mail Module docstring text.
extern Item from darkblood.games.entities.items [readable]

struct PostEntry
  ## docstring line
  i64 uid                    # field comment, kept in the generated code
  bool can_return = true     # scalar default
  vector<Item> items
end

message 2220 PostListAck reply ok_only
  map<i64,PostEntry> inbox
end
```

- `message OPCODE Name request|reply [ok_only] [bare]`. The direction must
  match the client name: requests end in `_REQ`.
- Every body starts with the i32 header word (see PROTOCOL.md, "Request header
  word"). It is implicit. Requests get a `header` field that defaults to
  `REQUEST_HEADER` (`0x7FFFFFFF`), and replies get `result`.
- `ok_only`: a reply with a non-zero result carries only the result word.
- `bare`: no header word and no fields (an empty body).
- Types: `i8 u8 i16 u16 i32 u32 i64 u64 f32 f64 bool` (little-endian),
  `wstr` (J-varuint byte length + UTF-16LE), `vector<T>` (tag `0x10`, count,
  elements), `map<K,V>` (tag `0x17`, count, then `0x0F` + key + value per
  pair), struct and extern names. `rest` captures the remaining bytes and
  must be the last field. Use it for trailing data that is not decoded yet.
- No struct tag is written. `0x00B35010` consumes nothing for `0x1E`.
- Decoding is strict. A short body raises `WireError`, and trailing bytes are
  ignored unless a `rest` field takes them.
- An extern type must provide `encode()`. With `readable` it must also
  provide `read(reader)`. Messages that contain a non-readable type get no
  `decode`.
- Mark fields whose meaning is unknown in their comment. Send them as zero or
  default values.
