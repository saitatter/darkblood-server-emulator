# Message schemas

`schemas/*.jsch` describe every wire message the server encodes or decodes.
`tools/gen_messages.py` turns each file into
`src/darkblood/games/network/messages/<domain>.py`. All 15 domain modules are
generated and start with `DO NOT EDIT`; only `messages/__init__.py` is written by
hand. To change a message, edit the schema and run:

```
python tools/gen_messages.py           # regenerate
python tools/gen_messages.py --check   # fail when a module is stale (also a unit test)
```

This mirrors MHServerEmu, which keeps the `.proto` files it extracted from its
client in `proto/` and generates C# with protogen. Dark Blood uses JSerBuffer,
not protobuf, so it ships no schemas. These files are written by hand from the
recovered readers and writers. Only the opcode names come from the client
(`assets/opcodes.tsv`): the generator checks each opcode against that table,
which is how the invented party opcodes in `party.jsch` were found. A C# backend
for the port can be added to the generator; the schemas stay as they are.

## Format

```
# line comment
domain mail Module docstring text.
extern Item from darkblood.games.entities.items [readable] [encode=METHOD]
import layer_net_id from darkblood.games.entities.character

struct PostEntry
  ## docstring line
  i64 uid                    # field comment, kept in the generated code
  bool can_return = true     # default
  u8 _ = 1                   # anonymous constant: always sent, not in the API
  vector<Item> items
end

message 2220 PostListAck ok_only
  u32 result
  map<i64,PostEntry> inbox
end
```

### Messages

`message OPCODE Name [header|header?] [ok_only] [bare]`

- The opcode must exist in `assets/opcodes.tsv`. The generated class gets
  `OPCODE` and a docstring `Opcode N: <client name> (request|reply).`
- `header`: the body starts with the 4-byte word `ffffff7f` and decoding requires
  it. `header?`: the word is accepted when present. Neither may be used on an
  `_ACK`. The generated field is `header` (default `REQUEST_HEADER`); encoders
  always write it. See PROTOCOL.md, "Request header word", for how to choose.
- `ok_only`: a reply with a non-zero `result` (first field) stops after it. A line
  `ok_only` inside the body moves the cut after the preceding fields instead.
- `bare`: an empty body.
- `struct Name ... end` declares a nested type with `encode`, `read(reader)` and
  `decode(bytes)`. Structs without an opcode are also used for layouts that the
  server uses on opcodes the client names differently (see `party.jsch`).

### Fields

`TYPE name [= DEFAULT]  # comment`

| Type | Wire form | Python |
|---|---|---|
| `i8 u8 i16 u16 i32 u32 i64 u64 f32 f64 bool` | little-endian | int / float / bool |
| `h32` | 4 bytes; accepts signed or unsigned (JHashString) | int |
| `wstr` | J-varuint byte length + UTF-16LE (odd lengths are rejected) | str |
| `wstrz` | UTF-16LE + `0000` terminator, no length (earlier server forms) | str |
| `wrest` | remaining bytes as UTF-16LE (earlier raw forms; last field) | str |
| `ipv4` | 4 bytes, network order | dotted str |
| `raw[N]` | N bytes, padded or cut | bytes |
| `rest` | remaining bytes (last field) | bytes |
| `vector<T>` | tag `0x10`, J-varuint count, elements | list |
| `set<T>` | tag `0x13`, count, elements sorted | list |
| `map<K,V>` | tag `0x17`, count, `0x0F` + key + value per pair, sorted by key | dict |
| `array<T>` | J-varuint count, elements (untagged fixed array) | list |
| `pairs<T>` | tag `0x17`, count, extern elements that write `0x0F`, key and value | list |
| `vector<?> set<?> map<?> array<?>` | empty container whose element layout is unknown (anonymous only) | — |
| struct / extern name | the type's encoder; no tag byte | object |

- `lit HEX` writes literal bytes and checks them when decoding.
- Name `_` makes an anonymous field: sent as its default (or zero), skipped when
  decoding, not in the class. Use it for fields whose meaning is not recovered.
- Defaults: numbers, `true`/`false`, `'text'`, or a factory such as `Bag()` or
  `Item('', 0)`.
- `if NAME` / `if not NAME` ... `endif` makes the enclosed fields depend on an
  earlier scalar field (5094 rebirth coins, 5018 clear rewards). No nesting.
- No struct tag is written: `0x00B35010` consumes nothing for tag `0x1E`.
- Decoding is strict: a short or malformed body raises `WireError`. The
  dispatcher records it as `bad-request`, logs a warning and keeps the
  connection; headless tests fail on that warning.
- Externs must provide `encode()` (or the method named by `encode=`). With
  `readable` they must also provide `read(reader)`. Messages that contain a
  non-readable type get no `decode`.
