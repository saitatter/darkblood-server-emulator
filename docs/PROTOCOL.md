# Recovered client protocol

Documentation handoff: 2026-11-16, covering the 2026-11-15 investigation. These findings refer to the client hash in [STATUS.md](STATUS.md). Addresses are x86 VAs, image base `0x00400000`.

Confidence labels: **observed** in a process/capture; **static** from assembly/decompilation; **experimental** for emulator choices not established as original-server behavior.

## 1. ProudNet framing

Observed format:

```text
13 57 | scalar_signed(payload_length) | payload
```

A scalar contains a width byte (`1`, `2`, `4`, or `8`) followed by a signed little-endian integer of that width. The writer chooses the smallest signed width that holds the value. Length counts payload bytes, not the complete frame.

First captured frame:

```text
13 57 01 05 30 0F 00 00 40
------ ----- --------------
magic  len=5 payload: type=0x30, u32=0x4000000F
```

| Function | Address | Role |
| --- | --- | --- |
| Frame writer | `0x00B7FBE0` | Writes magic `0x5713`, scalar length, and payload |
| Frame reader | `0x00B7FD80` | Checks magic, length, and body availability |
| Scalar writer | `0x00B95CB0` | Signed representation, widths 1/2/4/8 |
| Scalar reader | `0x00B95D90` | Same widths with sign extension |
| Scalar writer wrapper | `0x00B71050` | Used by CMessage |
| Scalar reader wrapper | `0x00B70A50` | Used by CMessage |
| Client dispatcher | `0x00B5F900` | Switch over message types 1..51 |

`server/proudnet.py` implements this framing. Its 1 MiB frame limit is a local implementation limit, not a demonstrated universal client protocol limit.

## 2. Accepted local sequence

| Direction | Payload | Result / confidence |
| --- | --- | --- |
| C → S | `30 0F 00 00 40` | Observed initial report; writer `0x00B5B910` |
| S → C | `07` | Experimental: handler `0x00B5CF80` emits type 8 |
| C → S | `08 01 00 9D 10 B1 D7 45 61 35 46 A8 CD EC B5 CF 75 E7 99 97 01 03 00` | Observed connection request |
| S → C | `0B` + host ID + GUID + user data + endpoint | Accepted: connection callback returns result 0 |
| S → C | `02` + JEvent 5020 | Delivered to the application and deserialized |

Type 8 is statically reconstructed as: user-data blob with scalar length, raw16 GUID, then a protocol/version u32. The capture contains an empty blob, GUID bytes `9D10B1D745613546A8CDECB5CF75E799`, then `97 01 03 00`. The exact version semantics need confirmation; this value is distinct from the type-0x30 report.

Type `0x0B` is read by `0x00B5ED30`:

```text
u8   type = 0x0B
u32  assigned client host ID
16B  server GUID
blob user data                   # scalar byte length + bytes
wstr observed client address     # scalar UTF-16 code unit count + UTF-16LE
u16  observed client port        # little-endian
```

Local client host IDs start at 2; the game addresses the server as host 1. The emulator's server GUID is a test value. This sequence **skips encrypted negotiation** and is not a complete ProudNet handshake implementation.

## 3. Incomplete negotiation and control

| Type | Recovered information |
| --- | --- |
| `0x01` | RMI; observed little-endian ID `0xFA01`, followed by 8+4 bytes |
| `0x02`, `0x03` | User message; route `0x00B5F6B0` delivers the remaining bytes to the application |
| `0x05` | Handler `0x00B5C8D0`: bool, ServerSettings, public-key blob; initializes crypto and emits type 6 |
| `0x06` | Client would send session-material blobs after type 5; unimplemented |
| `0x07` | Handler `0x00B5CF80`: sends type 8 |
| `0x0B` | Connection success, layout above |
| `0x1C` | Observed ping: u64 client timer + u32 latency value; writer at `0x00B4A225` |
| `0x1D` | Periodic control message without a body, roughly every 0.59 s; semantics unresolved |
| `0x1E` | Handler `0x00B5F220`: two 8-byte values used for latency and clock-offset calculations |
| `0x1F` | Consumed dispatcher branch; this does not establish it as the correct reply to 0x1D |
| `0x26`, `0x27` | Decryption branches before redispatch; static, not tested |
| `0x28` | Compressed envelope before redispatch; static route |

The emulator replies to `0x1C` with `0x1E + echoed timer + local timer`. The `0x1D → 0x1F` reply is exploratory and needs verification.

ServerSettings is read by `0x00B70DE0`, with defaults constructed by `0x00B82850`. It contains length/timeout/options/crypto fields and booleans. Its semantic schema is not sufficiently verified for implementation. RSA key representation and actual ciphers remain unresolved.

## 4. JSerBuffer and JEvent

Application serialization is separate from ProudNet framing.

JSerBuffer varints use little-endian seven-bit groups, but **setting bit 7 terminates the value**. Examples: zero = `80`, 100 = `E4`, 128 = `00 81`. Reader: `0x00B357F0`; writer: `0x00B357A0`.

Application wide strings use this length in **bytes**, followed by UTF-16LE. ProudNet wide strings instead use a scalar and a count of UTF-16 code units.

JEvent, recovered from `0x00A1EB90` and `0x00B35E50`:

```text
u32 opcode
u64 metadata/session field       # complete semantics not established
J-varuint body_length
if body_length != 0:
    u8 compressed_flag
    body bytes
```

The current writer emits only uncompressed bodies. Client decompression exists in `0x00B36110`; server-side decoding is not implemented.

Type checks vary. `0x00A48AF0` is a no-op returning true in this build. However, `0x00B35010` can validate a tag byte for types 15..26 when its type-check flag is active; welcome includes `0x17` before its map. Do not add tags universally to every field.

## 5. Welcome 5020 and the next step

| Function | Address | Role |
| --- | --- | --- |
| Welcome dispatcher | `0x0096D2C0` | Selects the handler for `0x139C` |
| Welcome handler | `0x0096AF60` | Reads result and body, updates application state |
| Result reader | `0x00A1EA20` | Reads u32 from the start of the body |
| Welcome body reader | `0x00A519A0` | Schema used by the experimental implementation |
| Body constructor | `0x00962AB0` | Client-side structure defaults |
| Map reader | `0x0076D5C0` / `0x0076AFD0` | J-varuint element count, then entries |
| Date reader | `0x00A49110` | Six u16 fields |
| Startup sequence | `0x00749EE0` | Waits for 5020, then 2403 |
| Event wait | `0x0094E1F0` | Polling with approximately 30-second timeout |
| Next request constructor | `0x0079A970` | Opcode 2402 / 0x0962: `JUserClient::DBListREQ` |
| Request sender | `0x007874A0` | `JUserClient::SendREQ(jEvt)` |

Structural welcome schema, after its result u32:

```text
u64
J-wide-string
u32, u32
bool, bool, bool
u64
tag 0x17, J-varuint map_count, map entries
u32, u32, u8
J-wide-string
u16 year, month, day, hour, minute, second
u64, u64, u16
```

The current test uses result 0, u64 value 1, text `OfflinePlayer`, an empty map, local date/time, and other fields zero. Its body is 100 bytes and its complete JEvent is 114 bytes. Client instrumentation confirmed complete deserialization.

### Recovered DBListREQ / DBListACK Flow:
* `0x0079A970` is statically identified via embedded developer log strings as `JUserClient::DBListREQ` (`L"Request DB list"`).
* It constructs JEvent opcode `0x0962` (2402) and invokes `0x007874A0` (`JUserClient::SendREQ`).
* `JUserClient::SendREQ` invokes `m_pjClient->SendUserMessage(Proud::HostID_Server)` via vtable slot `+0xC8` (`0x00B55A30`).
* If `SendUserMessage` fails, `0x007874A0` logs `L"Invalidation in m_pjClient->SendUserMessage( Proud::HostID_Server )"` (string VA `0x00CF7B30`) and `0x0079A970` logs `L"Invalidation in SendREQ( jEvt )"` (string VA `0x00CF8458`).
* Immediately after dispatching `DBListREQ`, the client calls `0x0094E1F0` waiting for event `0x0963` (2403, `DBListACK`).
* Opcode map `0x00F49CE8` registers pairs: `0x951` (LoginREQ), `0x95E`/`0x95F` (ServerList/SelectChannel), `0x962`/`0x963` (DBListREQ/DBListACK), `0x965`/`0x967` (CharCreateREQ/ACK).

### Internal Send Checks Identified:
1. `0x00B3FEC0`: Checks `[CNetClient + 0x550]`. If `NULL` or `*[+0x550] == 0`, immediately aborts and returns `0` (FALSE).
2. `0x00B53310`: Routing check. Checks `[CNetClient + 0x1570]` (remote host collection) and `[CNetClient + 0x1500]` (assigned client HostID). If empty, jumps to error cleanup at `0x00B53DB3` and returns `0` (FALSE).

## 6. Instrumentation and continuation addresses

| Address / slot | Role |
| --- | --- |
| `0x0092C2C0` | Function where the old SteamUser mock crashed at +0x62 |
| `0x00A5D880` | OnJoinServerComplete; sets connected flag on result 0 |
| `0x00D4FA90` | Connection callback vtable slot |
| `0x00A5EFA0` | OnReceiveUserMessage; JEvent deserialization |
| `0x00D4FA8C` | User-message vtable slot |
| `0x0096B091` | Welcome-reader callsite instrumented for diagnostics |
| `0x00F29AE8` | Connected flag observed after callback |
| `0x00A5CF30` | Connected-flag getter |
| `0x00787310` | Application-event dispatcher |
| `0x007874A0` | `JUserClient::SendREQ` |
| `0x0079A970` | `JUserClient::DBListREQ` (Opcode 0x0962) |
| `0x0074A0B6` | Wait site for `DBListACK` (Opcode 0x0963) |
| `0x00B55A30` | ProudNet `SendUserMessage` thunk (`sub ecx, 0xAC`) |
| `0x00B75710` | ProudNet user message preparer |
| `0x00B3FEC0` | ProudNet send guard (`[ecx + 0x550]`) |
| `0x00B53310` | ProudNet send transport routing (`[edi + 0x1570]`, `[edi + 0x1500]`) |
| `0x00D6EF8C` | ProudNet client-interface vtable; +0xC8 sends user messages |
| `0x00B57910` | Core constructor initializing multiple vtables |
| `0x00F2C410` | RmiContext used by game sending |

Send route and next probes are in [STATUS.md](STATUS.md) and [ROADMAP.md](../ROADMAP.md). All diagnostic patches are specific to the analyzed hash. Interpret boolean returns in AL; decompilers declaring them as int can expose undefined upper bits.
