# Recovered client protocol

Updated 2026-11-16 (second session: encrypted handshake through character creation). These findings refer to the client hash in [STATUS.md](STATUS.md). Addresses are x86 VAs, image base `0x00400000`.

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

`server/proudnet.py` implements this framing. Its 1 MiB frame limit is a local implementation limit.

## 2. Handshake (observed, complete for TCP)

| Direction | Payload | Notes |
| --- | --- | --- |
| C → S | `30 0F 00 00 40` | Initial report, writer `0x00B5B910` |
| S → C | `05` + bool + ServerSettings + blob(RSA public key) | Handler `0x00B5C8D0` |
| C → S | `06` + blob(RSA-OAEP(session key)) + blob(AES(fast key)) | Built at `0x00B5CD2E` |
| S → C | `07` | Session key accepted; handler `0x00B5CF80` emits type 8 |
| C → S | `08` + blob(user data) + GUID + u32 | Connection request |
| S → C | `0B` + u32 host ID + GUID + blob + wstr address + u16 port | Handler `0x00B5ED30` |
| S → C | `02` + JEvent 5020 | Application welcome; plaintext user messages are accepted |

Type 5 body (fixed-width little-endian fields, read through `0x00B70740`):

```text
u8   bool (stored at client+0x1660)
ServerSettings (reader 0x00B70DE0, defaults 0x00B82850, copied to client+0x638):
  u8  fallback method          i32 server message max length (0x10000)
  i32 client message max len   i32 default timeout ms (60000)
  u8  direct-P2P start cond.   i32 over-send threshold
  u8  Nagle                    i32 AES key length in bits (+0x1C; 128 used)
  i32 fast key length in bits (+0x20; must be > 0, the random generator fails on 0)
  u8 +0x24, u8 +0x25, u8 +0x26, u8 +0x27, u8 +0x2C, u8 +0x2D, u8 +0x2E, i32 +0x28
blob RSA public key            ProudNet scalar length + PKCS#1 DER RSAPublicKey
```

The client checks that the message was consumed exactly. The emulator's values are in `server/bootstrap_server.py:server_settings`; only the key lengths are known to matter.

## 3. Session crypto (static, verified by live decryption)

- RSA: libtomcrypt `rsa_import` (`0x00B98A90`) and `rsa_encrypt_key_ex` (`0x00B991E0`, from `0x00B83CB0`) with padding 2 = OAEP, hash `sha1` (`0x00D79E28`), PRNG `fortuna`. The emulator generates a 1024-bit key on first start (`logs/server_rsa.key`).
- The client draws a random AES session key (settings +0x1C bits) and a fast key (+0x20 bits). Type 6 carries RSA-OAEP(session key) and AES(fast key).
- AES: CRijndael (`0x00B73740` key setup, block 16) in ECB mode (mode 0 of `0x00B74B30`). Envelope before encryption:

```text
plaintext | pad filler (pad bytes) | u32 CRC-32(plaintext) | u8 pad      pad = 16 - (len + 5) % 16
```

  CRC-32 is the standard table at `0x00E45D50` (`0x00B95F60`). The server checks the CRC of every decrypted message; the fast key in type 6 decrypts with a valid CRC, which confirms the reconstruction.
- Fast encryption (type `0x27`, key setup `0x00B82D90`, RC4-like) is not used by observed traffic and is not implemented.

### Encrypted messages (type 0x26)

Game requests use RmiContext `0x00F2C410` with encryption mode 1. Without a session key `0x00B76050` aborted the send at `0x00B76515`, which was the first session's blocker.

```text
u8 0x26 | u8 encryption mode (1) | scalar length | AES envelope
decrypted: u16 encryption counter (reliable sends, writer 0x00955E30) | inner ProudNet message (02 + JEvent)
```

Server → client messages are currently sent unencrypted (`02` + JEvent) and are accepted.

### Control messages

| Type | Information |
| --- | --- |
| `0x01` | RMI. Observed IDs `0xFA01` (8+4 bytes) and `0xFA13`; not handled |
| `0x1C` | Ping: u64 client timer + u32; reply `0x1E` + echoed timer + server time (reader `0x00B5F220`) |
| `0x1D` | Periodic, about every 0.59 s; emulator replies `0x1F` (exploratory) |
| `0x28` | Compressed envelope before redispatch; static only |

## 4. JSerBuffer and JEvent

JSerBuffer varints use little-endian seven-bit groups, but **setting bit 7 terminates the value**: zero = `80`, 100 = `E4`, 128 = `00 81`. Reader `0x00B357F0`, writer `0x00B357A0`. Application wide strings use this length in **bytes**, followed by UTF-16LE. ProudNet wide strings use a scalar count of UTF-16 code units.

JEvent (`0x00A1EB90`, `0x00B35E50`):

```text
u32 opcode
u64 session value            # 1 after welcome; echoed by the server
J-varuint body_length
if body_length != 0:
    u8 flag                  # 0 in server messages; client 2203 sets 1 with a plain body
    body bytes
```

Handlers such as `0x0077CFA0` reject an ACK whose u64 differs from the client's stored value, so the emulator echoes the request's value. Client decompression exists in `0x00B36110`.

**Body cursor:** `0x00A1EA20(peek)` reads the leading u32 result; with `peek = 0` the shared cursor stays after it, and readers created by `0x00A1E6A0` continue from there.

**Container tags:** `0x00B35010` validates a tag byte only for tags 15..26 (`0x0F`..`0x1A`). Observed: `0x0F` map entry, `0x10` vector, `0x13` set-like container, `0x17` map. Struct tag `0x1E` is outside the range and is *not* written. Vectors and maps start with a J-varuint count; fixed arrays (`0x00A48DD0`) are a J-varuint count ≤ capacity followed by elements.

Reader widths: `0x00B35150` u8, `0x00B35680` bool, `0x00B351E0` u16, `0x00B35300` u32, `0x00B35560` 4 bytes, `0x00B35430`/`0x00B356F0` 8 bytes, `0x00B35AB0` J-wstring.

## 5. Application flow (observed in the live client)

Opcode names come from the client's table (`server/data/opcodes.tsv`, `tools/extract_opcodes.py`). Handlers come from the runtime map at `0x00F45250` (lookup `0x0075FD30`), dumped by the shim to `research/client/handler_map.txt`.

| Step | Client request | Server response | Handler / schema | Status |
| --- | --- | --- | --- | --- |
| Connect | — | 5020 `eERC_AUTHENTICATE_GAMEUSER_ACK` | `0x0096AF60`, body `0x00A519A0`; result 0 → success (`0x00640750`) | Verified |
| Startup | 2203 `eEGS_COMPUTER_STAT_NOT` | none | hardware report | Logged |
| Startup, title | 2402 `eEGS_DB_LIST_GET_REQ` | 2403 `eEGS_DB_LIST_GET_ACK` | `0x00775340`: u32 result, `0x17` map of {`0x0F`, u32 key, `0x00A496B0`: wstr name, u16, u64, bool ×3} | Verified: Server List "Offline / None" |
| Server Ok | 2001 `eEGS_KNOCK_SQUARELIST_REQ` (i32, u32 server key) | 2002 | `0x00757810`: u32 result; 0 proceeds (`0x00626390`). 2003 queue NOT (`0x00757840`: u16, u16) unused | Verified |
| automatic | 2021 `eEGS_SQUARELIST_REQ` (i32, u32) | 2022 | `0x0077A550`: u32 result, `0x10` vector of {u64 id, wstr name, u32, u32, u32} (`0x00A49700`) | Verified: "Channel 1 · Normal · [Good]" |
| Channel Ok | 5028 `eERC_JOIN_SQUARE_REQ` (i32, u64 square) | 5029 | `0x00757AD0`: u32 result, u64 | Verified |
| automatic | 2008 `eEGS_GET_CHARLIST_REQ` | 2009 | `0x0077CFA0`: u32 result, `0x10` vector of character, `0x10` vector (`0x004B94C0`), u8 slots, u8, bool, `0x17` map (`0x007680E0`), `0x13` (`0x006B9F80`) | Verified: "N SLOT" = first u8 |
| Creation | 2012 `eEGS_CREATE_CHARACTER_REQ` | 2013 | `0x00758070`: u32 result, character, u8 (→ `0x00F44E58`) | Verified: character appears |
| Ok on character | 2006 `eEGS_SELECT_CHAR_REQ` (i32, u64 char id) | 2007 `eEGS_SELECT_CHAR_ACK` | `0x007AA4B0`: u32 result, struct `0x00A40760` (651 bytes, full stats/visuals/skills), `0x10` vector `0x004B9210` | Verified |
| World layer | 5030 `eERC_JOIN_LAYER_REQ` (i32, u64 layer id) | 5031 `eERC_JOIN_LAYER_ACK` | `0x00787A70`: u32 result, u64 layer_id, u64 instance_id, u8 tag (0 = absent) | Verified |
| Enter map | 2016 `eEGS_ENTER_MAPTOOL_REQ` | 2017 `eEGS_ENTER_MAPTOOL_ACK` | `0x00757D20`: u32 result (0 triggers Scene 5) | Verified |
| Start game | 5013 `eERC_START_GAME_REQ` | 5014 `eERC_START_GAME_ACK` | `0x007880A0`/`0x00788199`: u32 result, u16, u32, wstr, 3 × `0x17` map, tag 0 (triggers Scene 9: town) | Verified |

Create request (observed): `i32 0x7FFFFFFF, u8 class, wstr name, u32 face, u32 hair, 5 × u8 body sliders (head, arms, chest, torso, legs), u8`.

Character struct (reader `0x00A4AB30`, constructor `0x00737BD0`):

```text
array<u8, <=5> +0x32 body sliders (J-varuint count + bytes)
u64 +0x00 id     u8 +0x08 class     u8 +0x09 index (12 crashed the client)
wstr +0x0A name
u32 +0x26 face   u32 +0x2A hair     u32 +0x2E      u64 +0x37
{u16,u32,u32} +0x49    {u16,u32,u32} +0x53       (0x00A49BB0)
bool +0x5D  u32 +0x5E  u64 +0x3F  u16 +0x47  4 bytes +0x62  u64 +0x66  u32 +0x6E  bool +0x72 +0x73 +0x74
```

Level and location on character select ("Level 0", "default town") did not change when any of these u16/u32/u64 fields were set; they come from another source (probably the second vector or the map in 2009).

Correction to the first handoff: the pushes at `0x007B2C40` (`0x951`, `0x95E`, `0x95F`, `0x963`, `0x965`, `0x967`) are not login or server-list opcodes. The client names them `eEGS_INIT_PROFICIENCY_ACK`, `eEGS_BROKER_CHANGE_REGIST_COUNT`, `eEGS_POST_DAILY_SEND_RECOVER_NOT`, `eEGS_DB_LIST_GET_ACK`, `eEGS_EVENT_DELETE_CHARACTER_ACK`, `eEGS_CHAR_VERIFY_STAT_ACK`.

## 6. Instrumentation and continuation addresses

| Address / slot | Role |
| --- | --- |
| `0x00A5D880` / slot `0x00D4FA90` | OnJoinServerComplete (shim traces it and dumps the handler map) |
| `0x00A5EFA0` / slot `0x00D4FA8C` | OnReceiveUserMessage |
| `0x00787310` | Application-event dispatcher; `0x0075FD30` handler lookup |
| `0x007874A0` | `JUserClient::SendREQ`; vtable `+0xC8` → `0x00B55A30` → `0x00B75710` |
| `0x00B76050` | Send options; `[ctx+0x1C]` encryption mode; `0x00B76515` = no session key |
| `0x0044CE00` / `0x004449B0` | Main loop / frame tick (Sleep frame limiter) |
| `0x00749EE0` | Startup: waits 5020, sends 2402, waits 2403 |
| `0x00640750` | Title-scene login-result handling (results 0, 9, 0xB, 0x1EA) |

All patches and addresses are specific to the analysed hash.

## Local serializer correction (2026-11-16)

Ghidra 12.2 analysis of a mapped image from the matching client confirms that
`0x00B35010` returns success without consuming bytes for tags outside
`0x0F..0x1A`. In particular, struct tag `0x1E` must not be emitted in
`Character.encode_world_details` or `SelectCharacterAck.encode`. Explicit
struct tags shifted subsequent fields in the previous serializers. Container
tags remain present. Static output is retained locally in
`research/select-fields.c` and `research/select-character.c`.

Local live validation reached character selection (2008/2009), but Enter did
not emit request 2006 during that run. Acceptance of the corrected 2007 and
world entry remain unverified on this machine.

### World-details trailer correction (local live verification)

The end of reader `0x00A52630` consumes `bool +1C9`, `u8 +1CA`,
`u16 +1CB`, `bool +1CD`, `bool +1CE`, then a J-wstring. The serializer
previously omitted the u8. After adding it, a local 2006/2007 exchange
reached return site `0x00A52BBF` with reader success byte 1 and cursor
`0x15D` (349), matching the 10-byte record prefix plus 339-byte
world-details payload for the local Tester character. This verifies the
world-details substructure, not the complete 2007 record or world entry.
The client still stays at character selection; remaining fields of reader
`0x00A40760` need tracing. Local diagnostics: `research/raw-read.c`,
`research/select-fields.c`, and the latest client hook log (not published).

### Selection defaults and mailbox continuation (local pass)

Complete 2007 parsing was observed at `0x007AA5B5` and `0x007AA629`
with AL=1; execution reached success-path site `0x007AA6D7`. The prior
selection failure therefore occurred after parsing. Assembly at
`0x007AAA00`/`0x007AAA37` and constructor `0x00485810` identify world
details offsets +A6/+AA as signed lookup inputs initialized to -1. Sending
zero invokes `0x00A90540`; absence of a matching entry takes the failure
branch. Preserve the client defaults `0xFFFFFFFF` for the empty state.
Their domain meaning is not yet established.

With those defaults the local client emitted 2219
`eEGS_POST_REQUEST_LIST_REQ` (body `ffffff7f00`). ACK 2220 handler
`0x007AEF70` reads u32 result, two 0x17 maps, u32 count, bool notification.
The server now encodes an empty mailbox and echoes correlation. This ACK
was checked structurally, but has not yet been accepted in a live client
test. The observed client run exited with access violation C0000005 at
8EC5997B after requesting 2219; this does not establish a cause or a stable
code address. The mapped crash image and hook log remain local. World
entry remains unverified on this machine.
