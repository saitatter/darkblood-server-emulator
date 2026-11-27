# Recovered client protocol

Updated 2026-11-16 (second session: encrypted handshake through character creation). These findings refer to the client hash in [STATUS.md](STATUS.md). Addresses are x86 VAs, image base `0x00400000`.

Confidence labels: **observed** in a process/capture; **static** from assembly/decompilation; **experimental** for emulator choices not established as original-server behavior.

## Offline Cash Shop purchases

The client sends product IDs in 2712. The emulator resolves each ID to an
item code and quantity from `assets/cash_shop.tsv` or a local server override.
A successful purchase sends 2037 with the granted items and 2714 to finalize
the purchase.
Result 24 reports an unavailable server catalog. Result 442 reports an
unknown product ID. The product list visible in the original client comes
from its own data.

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

`src/darkblood/core/network/proudnet.py` implements this framing. Its 1 MiB frame limit is a local implementation limit.

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
  i32 fast key length in bits (+0x20; 512 used)
  u8 +0x24, u8 +0x25, u8 +0x26, u8 +0x27, u8 +0x2C, u8 +0x2D, u8 +0x2E, i32 +0x28
blob RSA public key            ProudNet scalar length + PKCS#1 DER RSAPublicKey
```

The client checks that the message was consumed exactly. The emulator's values are in `src/darkblood/frontend/server.py:server_settings`; only the key lengths are known to matter.

## 3. Session crypto (static, verified by live decryption)

- RSA: libtomcrypt `rsa_import` (`0x00B98A90`) and `rsa_encrypt_key_ex` (`0x00B991E0`, from `0x00B83CB0`) with padding 2 = OAEP, hash `sha1` (`0x00D79E28`), PRNG `fortuna`. The emulator generates a 1024-bit key on first start (`logs/server_rsa.key`).
- The client draws a random AES session key (settings +0x1C bits) and a fast key (+0x20 bits). Type 6 carries RSA-OAEP(session key) and AES(fast key).
- AES: CRijndael (`0x00B73740` key setup, block 16) in ECB mode (mode 0 of `0x00B74B30`). Envelope before encryption:

```text
plaintext | pad filler (pad bytes) | u32 CRC-32(plaintext) | u8 pad      pad = 16 - (len + 5) % 16
```

  CRC-32 is the standard table at `0x00E45D50` (`0x00B95F60`). The server checks the CRC of every decrypted message; the fast key in type 6 decrypts with a valid CRC, which confirms the reconstruction.
- Fast encryption is mode 2 in the reliable `0x26` and unreliable `0x27`
  envelopes. Key setup `0x00B82D90` sizes the schedule from the negotiated key
  length. Dispatch `0x00B82AE0` accepts 512, 1024 or 2048 bits. Live town
  peer sends failed in mode 2 with the former 128-bit setting. The relay
  supplies 64-byte Fast keys and forwards encrypted peer payloads opaquely.
  The server's own application endpoint still decodes mode 1 (AES).

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

**Request header word (corrected 2026-11-20):** many client bodies start with the 4-byte word `ffffff7f` (2219 = `ffffff7f 00`). Its source is not recovered. An earlier note credited `0x00A1E620`, but that function only initialises the writer state (`0x00B34F70`, copied by `0x00B35060`/`0x00B34F40`) and writes nothing. Senders build the event with `0x00408C60(opcode, -1, -1)`, where the two `-1` are the u64 correlation. Senders that never call `0x00A1E620` and write no fields send an empty body (2131, 2390, 2402, 5045). That matches the captures.

The word's presence is not a property of the sender. In the decompressed captures in `logs/wire.jsonl`, 45 opcodes always carry it and 2036, 2073, 2076, 2078, 2210, 2216, 2346, 2446, 5017, 5040 and 5386 never do, although several of their senders are built like 2219. The same sender produced both forms for 2143 (148 with, 17 without), 2406, 5001 and 5093. So the word depends on runtime state. Testing the hypothesis that it follows a `0x00766AF0` pending-request registration matched only 11 of 47 opcodes. The schemas therefore use `header` when every capture (at least two) has the word, no flag when captures never have it, and `header?` (accepted when present) for mixed or uncaptured opcodes.

Sender writer widths, calibrated on captures (2036 = 8 + 8 + 4 bytes, 2210 = 8 + 8 + 2 + 4 + 4 + 1): `0x00B35100` u8, `0x00B35190` 2 bytes, `0x00B352B0` 4 bytes, `0x00B353D0` 8 bytes, `0x00B35630` bool, `0x00B358D0`/`0x00B35A40` J-wstring, `0x00B34FD0(tag)` container tag. Decompiled senders for the 134 handled request senders listed in `research/opcode_xrefs.tsv` were used to correct the request schemas.

**Container tags:** `0x00B35010` validates a tag byte only for tags 15..26 (`0x0F`..`0x1A`). Observed: `0x0F` map entry, `0x10` vector, `0x13` set-like container, `0x17` map. Struct tag `0x1E` is outside the range and is *not* written. Vectors and maps start with a J-varuint count; fixed arrays (`0x00A48DD0`) are a J-varuint count ≤ capacity followed by elements.

Reader widths: `0x00B35150` u8, `0x00B35680` bool, `0x00B351E0` u16, `0x00B35300` u32, `0x00B35560` 4 bytes, `0x00B35430`/`0x00B356F0` 8 bytes, `0x00B35AB0` J-wstring.

## 5. Application flow (observed in the live client)

Opcode names come from the client's table (`assets/opcodes.tsv`, `tools/codegen/extract_opcodes.py`). Handlers come from the runtime map at `0x00F45250` (lookup `0x0075FD30`), dumped by the shim to `research/client/handler_map.txt`.

| Step | Client request | Server response | Handler / schema | Status |
| --- | --- | --- | --- | --- |
| Connect | — | 2 `eE_ACCEPT_NOT` (empty) | `0x007AE730` → `0x0078A160` sends 5386 | Verified live |
| Login | 5386 `eERC_AUTHENTICATE_STEAM_GAMEUSER_REQ` (SteamID from SteamUser `+8`, ticket from `+0x34`; live `00 88 "DBACC:<account>;" …`) | 5020 `eERC_AUTHENTICATE_GAMEUSER_ACK` (`u32 result, u64 account uid, wstring account, …`) | `0x0096AF60`, body `0x00A519A0`; result 0 → success (`0x00640750`) | Verified live (two accounts) |
| Startup | 2203 `eEGS_COMPUTER_STAT_NOT` | none | hardware report | Logged |
| Startup, title | 2402 `eEGS_DB_LIST_GET_REQ` | 2403 `eEGS_DB_LIST_GET_ACK` | `0x00775340`: u32 result, `0x17` map of {`0x0F`, u32 key, `0x00A496B0`: wstr name, u16, u64, bool ×3} | Verified: Server List "Offline / None" |
| Server Ok | 2001 `eEGS_KNOCK_SQUARELIST_REQ` (i32, u32 server key) | 2002 | `0x00757810`: u32 result; 0 proceeds (`0x00626390`). 2003 queue NOT (`0x00757840`: u16, u16) unused | Verified |
| automatic | 2021 `eEGS_SQUARELIST_REQ` (i32, u32) | 2022 | `0x0077A550`: u32 result, `0x10` vector of {u64 id, wstr name, u32, u32, u32} (`0x00A49700`) | Verified: "Channel 1 · Normal · [Good]" |
| Channel Ok | 5028 `eERC_JOIN_SQUARE_REQ` (i32, u64 square) | 5029 | `0x00757AD0`: u32 result, u64 | Verified |
| after 5029 | — | 5134 `eERC_SQUARE_CHANGE_RELAY_ADDRESS_NOT` | `0x0075AAE0`: no result word; implicit `0x1E` struct = 6 raw bytes (`0x00A48910`) written to the relay buffer at `[owner+0x6C]`: IPv4 bytes in network order + u16 LE port. Handler then calls `JP2PClient::Connect` (`0x00956C80`) | Verified: client connects to `127.0.0.1:9401` |
| automatic | 2008 `eEGS_GET_CHARLIST_REQ` | 2009 | `0x0077CFA0`: u32 result, `0x10` vector of character, `0x10` vector of worn Item records owned by their character (`0x004B94C0`, copied by `0x00538DF0` into the character-select item list; empty = bare class models), u8 slots, u8, bool, `0x17` map (`0x007680E0`), `0x13` (`0x006B9F80`) | Verified: "N SLOT" = first u8 |
| Creation | 2012 `eEGS_CREATE_CHARACTER_REQ` | 2013, followed by 2009 on success | `0x00758070` reads u32 result, character and u8 (→ `0x00F44E58`). The following 2009 uses the same correlation and supplies the worn items for the lobby preview. | Verified live with a new Warrior |
| Ok on character | 2006 `eEGS_SELECT_CHAR_REQ` (i32, u64 char id) | 2007 `eEGS_SELECT_CHAR_ACK` | `0x007AA4B0`: u32 result, struct `0x00A40760` (651 bytes, full stats/visuals/skills), `0x10` vector `0x004B9210` | Verified |
| World layer | 5030 `eERC_JOIN_LAYER_REQ` (i32 prefix, u64 layer ID, bool) | 5031 `eERC_JOIN_LAYER_ACK` | `0x00787A70`: u32 result, i64 square ID, i64 layer ID, empty vector, bool, i64 | Layer change verified |
| Enter map | 2016 `eEGS_ENTER_MAPTOOL_REQ` | 2017 `eEGS_ENTER_MAPTOOL_ACK` | `0x00757D20`: u32 result (0 triggers Scene 5) | Verified |
| Dungeon entrance (walk into town exit) | 2010 → 5001 `_singleplay` → 5043 `eERC_SELECT_DUNGEON_REQ` (i32, J-wstring gate id `Act1_G1`) | 5044 `eERC_SELECT_DUNGEON_ACK` | `0x007702E0`: u32 result, `0x17` history map (dungeon id → J-wstring map id, u8 m_ucDiff = highest cleared difficulty, u8 cleared flag; `0x00A4BC00` allows d when d-1 < m_ucDiff or d-1 == m_ucDiff with the flag), `0x13` set, untagged J-wstring gate id (looked up by `0x006B2C00`, "Invalidation in m_pjGateProp" if unknown), `0x13` set of active quest ids (gate `+0x218`; quest-variant map slots 4+ are offered and auto-selected by `0x006B5930`/`0x006C77E0`/`0x006D1120` only when the JHashString of the map's QuestLink (+0x44) is present). Then app state → dungeon gate (world map table) | Verified live: Gnogue Haram gate map shown |
| Click dungeon on gate map | 5009 `eERC_CHANGE_MAPCODE_REQ` (i32, J-wstring map code `Act1_G1_A10`, bool) | 5010 `eERC_CHANGE_MAPCODE_ACK` | No JUserClient handler; JAppStateDungeonGate vf20 → `0x006D4A00` (app state 8): u32 result, untagged J-wstring map code, bool (meaning unknown; echoed) | Verified live |
| Start game | 5013 `eERC_START_GAME_REQ` (i32, J-wstring map code) | 5014 `eERC_START_GAME_ACK` | `0x007880A0`: u32 result, u16, u32, untagged J-wstring **map code**, 3 × `0x17` map, `0x10` vector (`0x004B94C0`). An empty code crashed: `0x0098E630` returns NULL and `0x00788539` reads `+0x28` | Verified live: Lucid Forest Entrance loaded, monsters spawned, character moves |
| Character deletion | 2014 `eEGS_DELETE_CHARACTER_REQ` (i64 char_uid) | 2015 `eEGS_DELETE_CHARACTER_ACK` | `0x00758370`: i32 result, i64 char_uid, i32 complete_time (0 = instant) | Verified |
| Bag reorder | 2030 `eEGS_SWITCH_BAG_REQ` (u16 from, u16 to) | 2031 `eEGS_SWITCH_BAG_ACK` | `0x00557680`: i32 result, u16 from, u16 to. Reordering persists the bags' UI slot indices (`w2a`), including moves into empty slots. | Verified |
| Inventory drag | 2036 `eEGS_DRAG_ITEM_REQ` (i64 uid, i64 container, i32 slot) | 2037 `eEGS_DRAG_ITEM_ACK` | `0x0077F570`: i32 result, tag `0x10` vector of Item structs | Verified |
| Use item | 2038 `eEGS_USE_ITEM_REQ` (i64 uid, i32 count) | 2039 `eEGS_USE_ITEM_ACK` | `0x0077D4C0`: i32 result, tag `0x10` vector, i32 item_id, i32 use_count | Verified |
| Delete item | 2040 `eEGS_DELETE_ITEM_REQ` (i64 uid, i32 count) | 2041 `eEGS_DELETE_ITEM_ACK` | `0x00557420`: i32 result, i64 uid, i32 del_amount | Verified |
| Equip item | 2042 `eEGS_EQUIP_ITEM_REQ` (i64 uid, i32 slot) | 2043 `eEGS_EQUIP_ITEM_ACK` | `0x007AE940`: i32 result, tag `0x10` vector of items | Verified |
| Quickslot assign | 2044 `eEGS_ASSIGN_QUICKSLOT_REQ` (u8 type, u8 slot, i32 ref_id, i64 ref_uid) | 2045 `eEGS_ASSIGN_QUICKSLOT_ACK` | `0x0078C4A0`: i32 result, echoes slot/ref parameters | Verified |
| Quickslot switch | 2046 `eEGS_SWITCH_QUCIKSLOT_REQ` (ffffff7f prefix, u8 type, u8 from, u8 to) | 2047 `eEGS_SWITCH_QUCIKSLOT_ACK` | `0x0078C790`: i32 result, u8 type, u8 from, u8 to | Verified |
| Learn skill | 2050 `eEGS_LEARN_SKILL_REQ` (u16 skill_index, u8 level) | 2051 `eEGS_LEARN_SKILL_ACK` | `0x0078DBE0`: i32 result, u16 skill_index, u8 level, i32 remain_sp, i64 remain_gold | Verified |
| Learn skill list | 2697 `eEGS_LEARN_SKILL_LIST_REQ` (prefix, tag 0x10 vector: tag 0x0F, u16 sidx, u8 lvl) | 2698 `eEGS_LEARN_SKILL_LIST_ACK` | `0x007A74A0`: i32 result, tag 0x17 map (0x0F, u16 key, u16 sidx, u8 lvl, wstring speech, bool lock, bool unk), i32 remain_sp, i64 remain_gold | Verified |
| Http notice check | 2594 `eEGS_HTTPNOTICE_CHECK_REQ` | 2595 `eEGS_HTTPNOTICE_CHECK_ACK` | `0x005A5110`: i32 result, bool bWatch | Verified |
| Play option update | 2216 `eEGS_PLAY_OPTION_UPDATE_REQ` (i64 char_uid, tag `0x1E` struct) | — | Fire-and-forget; consumed by server | Verified |
| Invite list | 2024 `eEGS_GET_INVITELIST_REQ` | 2025 `eEGS_GET_INVITELIST_ACK` | `0x006A2E10`: i32 result, tag `0x10` empty vector | Verified |
| Finish game / dungeon clear | 5017 `eERC_FINISH_GAME_REQ` (bool is_clear) | 5018 `eERC_FINISH_GAME_ACK` | `0x007ADB60`: u32 result, bool bVictory, wstring strPlayMapID, bool bSamePerson, tag 0x17 mapGuildPersonCnt; if victory: tag 0x17 mapSingleReward (0x0F, i64 uid, 40 raw bytes → JResultDirect `+0x74`: +4 num_total, +8/+0xC rates ×100 shown as "X", +0x10 EXP text, +0x20 extra-box count looped by `0x0071FF0F`, +0x24 extra-box price; +0, +0x14..+0x1C unknown), i32 nPartyRankFirst, i32 nPartyRankFinal, i32 nBoxGrade, i32 nExtraBoxCost, tag 0x10 vecBonusMonster | Verified |
| Dyeing | 2210 `eEGS_USE_DYEING_ITEM_REQ` (`0x00505E30`): i64 dye item uid, i64 target item uid (-1 skin), u16, i32, u32 ARGB color, bool | 2211 `eEGS_USE_DYEING_ITEM_ACK` | coloring page `0x00511E50` → `0x00511B70`: i32 result, 10-byte dye block (`0x00A49BB0`: u16, i32, i32), tag 0x10 Item vector. No reply = client disconnects after the wait Hair (stain Type 2) and skin (Type 3) dyes persist in 2007 details `+0x67`/`+0x71` (player `+0xCC`/`+0xD4`, apply `0x00515B40`) | Verified live 2026-11-20 (persistence headless only) |
| Party invite by nickname | 5092 `eERC_INVITE_USE_NICK_REQ` (`0x007ABAA0`): ffffff7f + J-wstring nickname | 5050 `eERC_INVITE_ACK` | No dedicated ack; the sender waits for none. The server resolves the name and reuses the 5049 path | Headless |
| Frame-rate telemetry | 2204 `eEGS_FRAME_STAT_NOT` (ffffff7f + 5 bytes) | none | Recorded only | Observed |
| Return to square | 5045 `eERC_BACK_TO_SQUARE_REQ` | 5046 `eERC_BACK_TO_SQUARE_ACK` | `0x007897F0`: i32 result, i64 square_uid, i64 layer_net_id, tag `0x10` vector, bool use_waypoint, i64 iCurAr (current AR; 0 reset the town display after a dungeon, also used by 5031) | Verified |
| Dungeon rank reward | 5090 `eERC_CHOICE_REWARD_PARTYRANK_REQ` (i32 prefix, i32 card) | 5091 `eERC_CHOICE_REWARD_PARTYRANK_ACK` | `0x0078D660` reads the i32 result first. The server sends only that field when the claim is unavailable (12) or the bag is full (67). Success adds i64 char_uid, 12 raw bytes (`0x00AC82A0`: u32 item code, u16 unknown, u16 count, u32 unknown), i32 box_type and i32 box_cost. The local player also reads a tag `0x10` Item vector and i64 gold. | Refusals verified in assembly and headless tests |
| Player death | 5093 `eERC_GAMEPLAY_DIE_CHAR_REQ` | 5094 `eERC_GAMEPLAY_DIE_CHAR_ACK` | `0x0078F090`: i32 result, i64 from, i64 to, bool bDie, i32 dmg, i32 cur_hp, i32 max_hp, u16 die_cnt, u16 coins | Verified |
| Daily rebirth coin | 2448 `eEGS_DAILY_REBIRTH_COIN_USE_REQ` | 2449 `eEGS_DAILY_REBIRTH_COIN_USE_ACK` | `0x0079DC70`: i32 result, u16 daily_count, i32 remain_pcbang | Verified |
| Level up notification | — | 5087 `eERC_LEVEL_UP_NOT` | `0x0078CCF0`: tag `0x1E` + tag `0x0D` (count 0) + i64 char_uid + u8 level + i32 hp + i32 mp + bool flag | Verified |
| Exp notification | — | 5086 `eERC_CHANGE_EXP_NOT` | `0x0078D170`: i32 nExpTotal (player `+0x78`) + jGainExp `0x00A49E20` (8 x i32 + J-wstring; a 4-byte float there made every 5086 fail to parse) | Verified |
| Town layer membership | 5030 `eERC_JOIN_LAYER_REQ` (i32 prefix, u64 layer UID) | 5031 `eERC_JOIN_LAYER_ACK` | Layer changes confirmed on two live clients. Position updates use peer messages. | Layer change verified |
| Square presence join | — | 5021 `eERC_USER_JOIN_SQUARE_NOT` | `i64 char_id, i32 square_id, 4 × f32 x/y/z/angle, u8 class, u8 level, wstr name`: broadcast to square occupants | Verified |
| Square presence leave | — | 5022 `eERC_USER_LEAVE_SQUARE_NOT` | `i64 char_id, i32 reason`: broadcast to square occupants upon departure or disconnect | Verified |
| Party invite | 2100 / 5049 `eEGS_PARTY_INVITE_REQ` (i64 target_uid / wstr name) | 2101 / 5050 `eEGS_PARTY_INVITE_ACK` | `0x00758700`: i32 result | Verified |
| Party invite notice | — | 5051 `eERC_INVITE_NOT` | `0x007706E0` → `0x00A4AD10`: bool, host summary, i64 room UID, J-wstring room name, u32 gate, u32 map, u16 difficulty | Static + headless |
| Party join / accept | 2102 / 5054 `eEGS_PARTY_JOIN_REQ` (i32 party_id, i32 host_uid) | 2103 / 5055 `eEGS_PARTY_JOIN_ACK` | i32 result, i32 party_id | Verified |
| Party member joined | — | 5056 `eERC_ACCEPT_INVITE_NOT` | i32 party_id, i64 member_uid, bool is_leader, wstr member_name | Verified |
| Party leave | 2104 `eEGS_PARTY_LEAVE_REQ` (i32 party_id) | 2105 `eEGS_PARTY_LEAVE_ACK` | i32 result; auto-promotes next member if leader departs | Verified |
| Party kick | 2106 `eEGS_PARTY_KICK_REQ` (i64 target_uid, i32 party_id) | 2107 `eEGS_PARTY_KICK_ACK` | i32 result, i64 target_uid; delivers 2105 to kicked member | Verified |

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

Meanings recovered from character select `0x00703EB0` and the delete check `0x006F1DD0`:
`+0x08` level ("Level %d", Text_Level), `+0x09` class (Text_Job; also the max-level lookup), `+0x37` nJoinLayerNetID (Text_Town),
`+0x5D`/`+0x5E` pending deletion + seconds left ("Deleted in %s", RemainTime), `+0x3F` guild UID (-1 none) and `+0x47` guild grade
(4 = master: deletion refused with MB_DeleteCharacter_GuildMaster), `+0x62` f32 rate and `+0x66` i64: "bonus" of rate - 1.0 shown
when `+0x66 > 0`, `+0x74` "Block Status" (UI_3087). Still unknown: `+0x2E`, `+0x49`/`+0x53` (0xA49BB0), `+0x6E`, `+0x72`, `+0x73`.

Location on character select: `0x00704278` resolves the high dword of `u64 +0x37` (nJoinLayerNetID, same encoding as `layer_net_id`: jhash(SquareID) << 32 | layer) through `0x00990030` (DictMap+0x3C) and shows its name in `Text_Town`; an unknown id (the old placeholder 17) shows "default town". Level on character select is read from `+0x09` (`0x00704194`).

Correction to the first handoff: the pushes at `0x007B2C40` (`0x951`, `0x95E`, `0x95F`, `0x963`, `0x965`, `0x967`) are not login or server-list opcodes. The client names them `eEGS_INIT_PROFICIENCY_ACK`, `eEGS_BROKER_CHANGE_REGIST_COUNT`, `eEGS_POST_DAILY_SEND_RECOVER_NOT`, `eEGS_DB_LIST_GET_ACK`, `eEGS_EVENT_DELETE_CHARACTER_ACK`, `eEGS_CHAR_VERIFY_STAT_ACK`.

### Relay connection and world entry (local pass, 2026-11-16)

Handler 2007 ends with `JP2PClient::Connect(0, [owner+0x6C])` at `0x007AAD98`
(`JP2PFactory::Connect` `0x00956A90` creates a new `CNetClient` and calls its
vtable `+0x34`, which reaches `0x00B54B40`). The 6-byte buffer is filled only by
5134. Without 5134 it is zero, `0x00B54B40` throws Proud error 14 ("Unknown
Internet address") and the 30 s selection wait times out. The tracer confirmed the
zero buffer at `0x007AA6C2` and the filled buffer `7F000001 B924` after 5134.

With 5134 sent after 5029 and a second ProudNet listener on 9401 (role `relay`,
same handshake, no welcome), the selection completed and the client rendered the
town: character "Lv.0 Tester", NPC dialogue "Scarlet Harrow" advancing with Space
(screenshots `research/relay1.png`, `relay2.png`, local only). In this run the
client did **not** send 5030/2016/5013; after 2007 it sent 2219, 2131
`eEGS_FRIEND_LIST_REQUEST_REQ`, 2569 (unnamed) and periodic opcode 0. The relay
connection completed the handshake but carried no game events yet. Movement,
NPC interaction beyond the dialogue, and persistence are not verified.

### Dungeon start correction (Cristian, 2026-11-16; static + headless)

In 5014 handler `0x007880A0`, calls at `0x0078822A`, `0x00788231`,
`0x00788238` read u16, u32 and J-wstring. There is no string type tag on the
wire. Three maps follow. At `0x0078836B` the handler checks tag `0x10`, then
calls vector reader `0x004B94C0` at `0x0078837E`. The former serializer wrote
`0B 00` for the string, `17 00` for empty maps, and a trailing zero; these
are invalid empty-container encodings and omit the required vector tag.

Correct default success body (19 bytes):
`00000000 0000 00000000 80 1780 1780 1780 1080`.
This fixes framing only. Zero scalar fields, the empty name and collections
are provisional; required dungeon identifiers and nonempty state still need
recovery. The call to `0x006DBFD0(9)` accesses an app-page object and does not
prove a transition to town. Do not infer gameplay from the ACK alone.

Evidence: matching executable hash in STATUS.md; local mapped image
`research/session.bin`, focused output `research/dungeon-start.c`. Assembly
confirms the reader calls independently of inferred decompiler signatures.
Headless flow checks the complete default body; live acceptance is pending.

### Player visibility across town layers (Cristian, 2026-11-18)

The local capture has live `5030` bodies of `ffffff7f` followed by the
u64 layer ID and a trailing bool. `5031` at `0x00787A70` stores the
confirmed layer at local player `+0xF0` and refreshes the scene. `5027`
at `0x00787790` passes each peer summary and the recipient's current
layer to `0x00967590`. That routine looks up the summary's first i64
as the peer UID and creates a `JUser` entry when needed. `5096` at
`0x0078C990` looks up an existing peer by UID before applying details.
`5039` at `0x00789450` reads a u32 result and i64 peer UID on success,
then calls `0x009662E0` to remove the peer.

The emulator keeps the selected `5028` channel during `2006`. On a
`5030` layer change, it sends the acknowledgment, tells the old layer
to remove the mover, and sends reciprocal `5027` then `5096` announcements
within the destination channel and layer. Two-client headless tests verify
the routing and peer UIDs. Two live clients verified that town positions
travel through the ProudNet peer relay.
Local static evidence is in `research/town-peer-*.c`.

Disconnect, return to character select (`5037`), leave square (`5032`) and
channel changes also announce `5039` to old layer viewers. Removal checks that
the departing session owns the world registration. After `5037`, a new `5028`
chooses a channel and leaves the character list off-world until selection.

### Town party invitation notice (Cristian, 2026-11-18, static + headless)

The `5051` client handler `0x007706E0` requires SquarePlay and sends the payload
to `0x00A4AD10`. The previous two-ID/name payload stopped before the fields
required by this reader. The bool and two structs do not carry a struct tag.

Host summary `0x00A49600` reads i64 square UID, i64 character UID, u32,
J-wstring nickname, u8, u16, u8, two i64, 74 opaque bytes (`0x00A48B40`),
and bool. The UI assigns the first two values to `nSquareUID` and `nCharUID`
at `0x0062BE50` and `0x0062BE63`. The notice uses the registered square and
the inviter's character ID and nickname. Other host and room fields use the
defaults from `0x00473E60` and `0x0049F6C0`, including room UID zero for a town
invite. The server's internal party ID is not a room UID.

`5050` uses the result reader `0x00A1EA20(0)` from `0x00758700`. No `5055`
or `5056` handler was found in the captured global table or the room-page
dispatcher at `0x0059D970`. This is a bounded search. The existing headless
fixtures for those replies do not establish live client behavior.

Evidence is in ignored `research/dungeon-invite-*.c` and x86 instructions
from the same local dump used for the `5014` analysis. The headless tests
check the full notice bytes and the multi-client party workflow. The in-game
dialog remains to be verified.

### Dungeon room join (Cristian, 2026-11-18, static analysis)

- `JAppPageGameRoom::JoinRoomREQ` at `0x0058B430` sends `5003` when the
  room UID is positive. Writer `0x00B353D0` writes the i64 room UID.
  Without a positive room UID, it sends `5054` with two i64 values. The caller
  at `0x0063A80E` identifies them as host square UID and host UID.
  The server accepts this form and the older host-only fixture, both with
  an optional four-byte prefix.
- The game-room dispatcher at `0x0059D970` routes `5004` to `0x00597C30`.
  A nonzero u32 result ends the reply. On success the handler reads untagged
  `jRoomInfo` (`0x00A49380`, shared with `5002`), i64 host UID, a `0x10`
  `vecNetChar`, six-byte relay address, `bFreeItemObtain`, and
  `bIsAllCharSameRate`. The diagnostic string at `0x00CB93C0` names the fields.
- `vecNetChar` is read through `0x00596AA0` → `0x005969B0` → `0x0049EA00`
  → `0x00A533A0`. Each record begins with the `0x00A52630` character details
  used by `2007`, followed by i64, 20 raw bytes (`0x00A48950`), i64,
  eight bytes (`0x00B354D0`), u32, and struct `0x00A4AC80` (two groups of
  six 16-bit fields followed by u32). The `0x1E` checks consume no wire byte.
  The handler looks up its own UID in the list.
- Local evidence is in ignored `research/dungeon-5003-sender.c`,
  `research/dungeon-5004-reader.c`, and `research/dungeon-5004-member.c`.
  Successful room entry still needs the meanings of the nested member fields, room
  membership, and relay routing.

### Dungeon room host handover (2026-11-26, static analysis + headless)

- `JAppPageGameRoom::ChangeHostREQ` (`0x0058D4C0`) sends `5021` only while
  `m_bExistRoom` (+0xAC) is set; the body is one i64 new host UID (writer
  `0x00B353D0`). The server accepts it with or without the request header word.
- The game-room dispatcher routes `5022` to `0x00599630`: u32 result; a nonzero
  result shows its text (`0x00AB29C0`) and stops. Otherwise it reads i64
  `nChangeNewHostUID`, stores it as the room host (`0x00944890`) and announces the
  member's name. The server sends it to every member, and also when the host leaves.
- jNetChar tail (`RoomMember`): `+0x217` is the VIP block read by `0x00A4AC80`
  (`DateTime6` start, `DateTime6` end, i32 grade), the same layout `2711`
  stores at `0x00F24C04`. `SetUser_InParty/InArena/InSiege` copy `+0x207` (i64) to
  `JNetUser +0x100` and `+0x233` (u32) to a protected value at `JNetUser +0x90`
  (`0x009666A5`..`0x009666C9`). Their meanings, and those of `+0x1EB`, `+0x1F3`
  and `+0x20F`, remain open.

### 5014 scalars and RoomMemberInfo stress (2026-11-26, static analysis + headless)

- The 5014 u16 and u32 are read at `0x0078822A`/`0x00788231` into `[esp+0x54]` and
  `[esp+0x58]`. The u16 is the player count: `0x00788588` compares it with 1 and
  plays `Loading_Single.mp3` or `Loading_Party.mp3`. The u32 goes to
  `AppPage(9)+0xB8`; `JAppStateGamePlay::vf04` copies it to `+0x174`, and the 5050
  pickup handler (`0x0078B794`) adds it to a value passed to the CRT seed/random
  imports, so it is a run random seed. `0x008ECAC2` writes a time value there otherwise.
- In state 8 the first map's nested records go to `0x0095A6A0` for every peer
  except the local UID; the assertion `pr2.first == pr2.second` ties each nested key
  to the record's skill index. The second map's value reader chain ends in
  `0x00A52CF0`, the `PetInfo` record.
- `RoomMemberInfo` (`0x00A49600`): the party row filler calls `0x00756F40` with the
  stress gauge and the member. Max stress is property `0x67`, plus `0x68` when
  `0x009B0B90` holds, plus `0x69` when `+0x10 & 2`, plus a bonus when the `+0x8E`
  bool is set. `+0x31` (i16) is the current stress (gauge `stress/max`); at or above
  the max the row text turns grey and `UI_2356` is shown.

### Dungeon start collection readers (Cristian, 2026-11-18, static analysis)

The three outer maps and the trailing vector use these reader chains:

| Field | Client readers | Observed structure or use |
| --- | --- | --- |
| First `0x17` map | `0x004B8B80` → `0x004B2BC0` → `0x004B1F80` | Each pair starts with `0x0F`, then a 64-bit key and a nested `0x17` map through `0x004B1240`. In state 8 the key selects a peer and the client applies the nested skill records to peers other than itself. |
| Second `0x17` map | `0x0064E7D0` → `0x00644440` → `0x00643940` | `0x0F` pair, 64-bit key, structure from `0x00A52CF0`. The `0x1E` check at `0x00642170` consumes no wire byte. The value's role remains open. |
| Third `0x17` map | `0x004B7550` → `0x004B66A0` → `0x004B45F0` | `0x0F` pair, 64-bit key, nested `0x10` vector through `0x004B2C90`. In state 8 the key selects a peer and the vector is passed to `0x00948E80`. |
| Final `0x10` vector | `0x004B94C0` → `0x004B9210` → `0x0049F1E0` → `0x00A53F50` | Standard `Item` records. The handler applies them to the local inventory through `0x00835990` → `0x008354D0`. The `0x1E` check consumes no wire byte. |

The second map's value starts with an array reader `0x00A4B250` (maximum two
elements), followed by i64, u32, u8, u32, u16, J-wstring, a `0x10` vector
through `0x0076E600`, bool, and u16. The field meanings still need confirmation.

`0x007880A0` reads the result first and skips the success fields when it is
nonzero. The emulator sends result 12 (`JERI_INVALID_STATE`) for an empty or malformed 5013 map code.
Valid single-player replies retain the existing map code and empty collections.
The headless test checks both replies. Live verification of the error remains open.

Evidence comes from Ghidra 12.2 focused decompilation and x86 instructions in
`research/session.bin`. The derived PE hashes to
`f5defbc15c68a3c90641b1f02a200a7f3ae64d7e866248db4dd83a3d1f9a3e88`.
The dumps and generated output remain under ignored `research/`.

### Dungeon layer, warflag, monster kill, and drop schemas (2026-11-16; static + headless)

1. **5095 eERC_CHANGE_DUNGEON_LAYER_NOT (sender 0x007900B0):**
   Sent by JAppStateGamePlay::Initialize (0x006C0000.c:10234) via 0x0087D1F0.
   Payload: i32 0x7FFFFFFF + i64 layer_net_id.
   layer_net_id encodes (jhash(map_code) << 32) | layer_id.
   For Lucid Forest Entrance (Act1_G1_A10), jhash('Act1_G1_A10') = 0x32ADCD46, layer is 4.
   The observed payload ffffff7f 04000000 46cdad32 is exactly this.

2. **2422 eEGS_ACTIVE_WARFLAG_REQ (sender 0x0079C300):**
   Sent by 0x0087D170 with active war flag id (i32 0x7FFFFFFF + u32 war_flag_id).
   Observed value 31 (0x1F). No client-side ACK handler is registered in handler_map.txt.

3. **2358 eEGS_GUIDE_BEGINNER_UPDATE_REQ (sender 0x0079A3B0):**
   JUserClient::GuideBeginnerListUpdateREQ: i32 0x7FFFFFFF + vector (tag 0x10) of u32 guide IDs.

4. **5063 eERC_MONSTER_DEAD_REQ (sender 0x0078A690):**
   JUserClient::MonsterDeadREQ: i32 0x7FFFFFFF + u32 monster_id + u32 param.

5. **5064 eERC_DROP_ITEM_NOT (handler 0x0078A870):**
   JUserClient::On_eERC_DROP_ITEM_NOT: u32 source_id + vector (tag 0x10) of 26-byte item drop structs
   (tag 0x1E, u32 drop_uid, u32 item_id, u16 count, u16 drop_type, tag 0x13, 3x float coordinates, u16 flags).

6. **Bag cell display (0x00827D80 / 0x005509F0 / 0x00551310):**
   In the 2007 bag vector (struct 0x00A1EC30):
   - bag_id: must have high dword < 0x80000000 (positive int64) to be considered active by 0x00827D80.
   - code: item hash from DictItem (jhash('Ibaga0004')); must not be -1.
   - +0x28 (b28): item category tab filter (0x00551310: 0 matches any item type). Setting 0xFF prevented matching.
   - +0x29 (b29): cell capacity (0x005509F0: BagSize = 5 for Ibaga0004). Setting 0 displayed zero cells.
   - +0x2A (w2a): UI bag slot index (0..4). UI slot 0 is 0.

### Death, revive and rebirth coins (2026-11-16; static + headless)

- 5093 request (`0x0078EDF0`, no prefix): `u64 own_uid, bool bDie, u32, u32, u32`.
- 5094 ack (`0x0078F090`): `u32 result, i64 char_uid, i64 other, bool bDie, u32, u32, u32, u16`, plus `u16 rebirth_coins` only when `bDie == 0`
  and `char_uid` is the player's own UID. When `bDie` is set and the UID is the player's own, the handler opens the revive page 0x6B.
- 2448 request: `i32 prefix, bool pcbang`. Sent only while player `+0x7E < 3` and `+0x7C < 3`.
- 2449 ack (`0x0079DC70`): `u32 result, u16 -> player +0x7E, u32` (page 0x12).
- 2286 not (`0x007983B0`): `u32 result, u16 -> player +0x7C` (owned coins; a gain shows UI_2653).
- 2007 details `+0x59`/`+0x5B` initialise player `+0x7C`/`+0x7E` (`0x0095A150`).

### Item durability and reserved container 2 (2026-11-16; static)

Item base field names come from `0x006741F0`: `+0` Amount, `+2` UpgStep, `+4` Quality, `+6` RCHold, `+7` Durability (f32).
If durability is <= 0 while the prop's max (`+0xBE`) is > 0, the item is broken (`0x00A49920`), and `0x009D89B0` leaves it out of the stat sum.
`0x008354D0` ignores items whose container is 2, so bag ids must avoid 2 (as well as 1, which is the equipment).

### ACK result codes and client error texts (saita machine, 2026-11-19; static + live)

A nonzero `result` in 2039 (`0x0077D4C0`), 2043 (`0x007AE940`), 2045
(`0x0078C4A0`) and 5068 (`0x0078AD80`) is passed to `0x00AB29C0`.
`0x00AB2980` looks the code up in the std::map at `0x00F4BBBC`
(code → `JERI_*` key, filled by the initializer `0x00AB3450`, inserts up to
`0x00ABBA50`) and the key is resolved through
`Data/Localization_ST/error_st.dat` (UTF-16, `key<TAB>text`) and shown as
system message type `0xD`. Unknown codes show `Invalid value.` (`0x00D58C38`).

- `assets/result_codes.tsv` lists all 497 codes (-2..494, no gaps), with
  English text for 154. Regenerate with `tools/codegen/extract_result_codes.py`.
- Code 1 is `JERI_NO_EXIST_CHAR` ("Unavailable character."). The server had
  sent 1 as a generic failure. Live: a full bag on 2038 showed that text.
- Checks: 206 (`0xCE`) = `JERI_ROUTER_00` "cannot find this character.", and
  421 (`0x1A5`) = `JERI_FRIEND_BLOCK_00` "Currently blocked.", matching
  meanings already used for 2140/2222.
- Inventory: 62 `JERI_INVEN_00` no space for a bag, 63 `JERI_INVEN_01` item
  not found, 67 `JERI_INVEN_05` "Not enough space in inventory.". The server
  now sends 67 for a full bag (2039, 5068) and 63 for a missing item (2039,
  2043). Constants: `src/darkblood/games/network/results.py`.
- 2037 (`0x0077F570`) and 2070 (`0x0077E8E0`) do not call `0x00AB29C0`
  directly. Their failure codes are unchanged and not verified.
- Error-message display for the new codes is not live-verified yet.

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

### Canonical 2007 result prefix (local pass)

Unlike handlers that call `0x00A1EA20(0)`, handler 2007 calls it with 1,
which resets the shared body cursor to zero after peeking the result.
Reader `0x00A40760` then consumes the same leading u32. Do not emit a
second result/field-zero word. The canonical success body starts with
`00 00 00 00 80 80` (result and two empty fixed-array counts). The
previous duplicate word was accidentally tolerated as an overlong zero
J-varuint. Local Tester ACK length is now 636 bytes; other names vary.
The updated body was sent in a live selection exchange, followed by
request 2219 and reply 2220. World entry is still not verified.

A later diagnostic reached `JUserClient::Shutdown` (`0x007869A0`) from
return site `0x007577EF`, in wrapper `0x00757750`, after mailbox handling.
The SteamUser slot-16 stub was called with argument 0 and no new exception
was logged. This is an application shutdown path, not proof that mailbox
parsing failed. The next investigation should identify the UI/error event
that invokes `0x00757750` and capture the shutdown message. Static outputs
are local `research/event-result.c` and `research/dispatch-failure.c`.

## 5. Square Relay Architecture & Relay PIDL

Upon character selection (2006/2007), the client attempts to establish a P2P/relay
connection (`JP2PClient::Connect`, `0x007AAD98` / `0x00956C80`).
If unconfigured, this triggers ProudNet error 14 ("Unknown Internet address") at `0x00B54B40`.

### Square Relay Announcement (Opcode 5134)
- **Opcode**: `5134` (`eERC_SQUARE_CHANGE_RELAY_ADDRESS_NOT`)
- **Handler**: `0x0075AAE0` -> Reader `0x00A48910`
- **Format**: 6 raw bytes: 4-byte IPv4 in network byte order (`127.0.0.1`) + 2-byte little-endian port (`9401`).
- The emulator announces `127.0.0.1:9401` immediately following opcode `5029` (`eERC_JOIN_SQUARE_ACK`).

### Relay PIDL Protocol (Port 9401)
The relay service uses game-defined ProudNet RMI messages rather than standard JEvents:
- **JoinGroup (RMI 1001)**: Client → Server (`0x00956420`/`0x00956500`).
  `u32` group type, two `i64` group identifiers (`0x00977610`), and a trailing
  `i64` character UID. `LeaveGroup` (1002, `0x009565E0`) uses the same
  layout. Live town captures matched the last field to the selected character
  UID on both accounts. The group identifiers were the square and layer UIDs.
  Initial joins sometimes send square UID `-1`, resolved against the game-world
  channel or the default channel when the registration is unavailable.
- **JoinGroupACK (RMI 3001)**: Server → Client (`0x009567A0`).
  - Prefix: ProudNet message type `0x01` + `u16` RMI ID (`3001`).
  - Body: `u32` group HostID + ProudNet scalar byte length + JSerBuffer vector (`0x10`) of member entries (`u64` character UID + `u32` HostID). The pair check at `0x006AFA10` consumes no byte.
- **Peer departure (`0xF61E`)**: Two consecutive 32-bit HostIDs, member then
  group. ProudS2C dispatch entry `0x00B45730` calls vtable slot `+0x30` at
  `0x00B45901`, which resolves to `0x00B573C0`. That routine looks up the first
  value as the remote peer and the second as the group.

The relay keeps a roster per `(group type, first identifier, second identifier)`
and forwards reliable peer frames only within the sender's current group.
Switching groups or disconnecting tells the previous group that a peer left.
A `LeaveGroup` must match both the current group key and character UID.
A join with a different character UID removes the earlier membership before
announcing the replacement. A three-connection headless test covers these
transitions and relay isolation.

The two live relay clients exchange matching `0x32`/ `0x33` control payloads
inside `0x15` / `0x19` reliable relay envelopes. In the disassembly, the
client send path calls `0x00B53310` through vtable slot `+0x30` after encryption and
returns its send status through `0x00B763D3`. Receipt of control messages
establishes reliable peer transport.

With 512-bit Fast keys, both live clients emitted reliable `0x26` mode-2
envelopes via `0x15` and unreliable `0x27` mode-2 envelopes via `0x16`.
The latter decode to a type-2 user message starting with game P2P event
`0x53`. The local decoder verified the Fast CRC on both senders.

- C → S `0x16`: `u8 priority, scalar unique ID, scalar destination count,
  i32 destination HostIDs[count], blob(message)` (writer `0x00B538FB`).
- S → C `0x1A`: `i32 sender HostID, blob(message)` (reader `0x00B5A790`).
  The blob holds one unframed ProudNet message. The client resolves the
  peer using the sender HostID and dispatches the blob through `0x00B5F900`.
  The relay preserves the message and forwards only within the current group.
  Two live clients reached the dispatch at `0x00B5A8B5`, passed the Fast
  CRC check at `0x00B82C2D`, and displayed each other's movement.

The unreliable `0x53` bundle carries the town position revision `0x4D`.
The stock client passes a recipient budget at `0x0087C25E` and clamps
each peer's revision rate to one per 2000 ms at `0x00966C9C`. The
loopback shim replaces that throttle with 100 ms.

The final `i64` of each 5027 player entry (reader destination `+0x41`)
contains the server key in bits 54–58. `0x00944510` copies it to the
peer's `+0x100`, and the overhead name renderer extracts it via
`0x00A614A0`. With key 0 the local server list lookup falls back to
`GAME_434` (“Other server”). The emulator sends the same key as 2403.

## 6. Town & Tutorial Flow (Decompiled & Implemented)

Following character selection and relay attachment, the client interacts with tutorial and town systems:

| Request Opcode | Handler | Response Opcode | Binary Layout & Behavior |
| --- | --- | --- | --- |
| `2131` (`eEGS_FRIEND_LIST_REQUEST_REQ`) | `0x007712E0` | `2132` (`eEGS_FRIEND_LIST_REQUEST_ACK`) | `u32 result` (0) + tag `0x17` map (`\x17\x00` empty map) |
| `2569` | `0x00772160` | `2570` | `u32 result` (0) + tag `0x17` map (`\x17\x00` empty map) |
| `2082` (`eEGS_CLEAR_TUTORIAL_REQ`) | `0x0077EEB0` | `2083` (`eEGS_CLEAR_TUTORIAL_ACK`) | `u32 result` (0) + tag `0x10` Item vector applied by `0x007FEC40` (empty = `10 80`). The client then enters town without a new 2007, so the server sends the whole inventory (worn gear included) plus the rewards. `0x006DBFA0(9)` is a state **getter** (JAppStateTutorial), not a transition; its method `0x006E5CE0` sends 2084, sets SquarePlay `+0x75` and fades into `g_jAS_Tutorial:On_Tutorial_FadeOut()` (`0x006F2EC0`) → `ChangeState(eAS_SquarePlay)`. See §7. |
| `2346` (`eEGS_TUTORIAL_QUEST_START_REQ`) | TalkBox `0x006481E0` | `2347` + `2074` | Request (`0x00799A60`): J-wstring tag + u32 quest id. 2347 is `u32 result` only. The server also sends 2074 to add the quest to the client's active list (hypothesis; see STATUS). |
| `2390` (`eEGS_ROULETTE_MANAGER_INFO_REQ`) | `0x006CC6B0` | `2391` (`eEGS_ROULETTE_MANAGER_INFO_ACK`) | `u32 result` (0) + untagged 21 zero bytes (`0x00A48B80`) |
| `2353` (`eEGS_TUTORIAL_MONSTER_DEAD_NOT`) | Sender `0x00799E60` | None | Notification sent on tutorial mob defeat |
| `2352` (`eEGS_IP_ADDRESS_NOT`) | Sender `0x00930` | None | Notification broadcasting client network IP |

All responses are modeled as Python dataclasses in `src/darkblood/games/network/messages.py` and validated by automated end-to-end tests in `tests/test_headless_flow.py`.

## Protocol map tooling (2026-11-16, saitatter machine)

- `assets/opcodes.tsv`: 1,458 names with no gaps in any block, from the
  client's name map `0x00F49CF8` (`tools/codegen/extract_opcodes.py`). Earlier
  extractions missed every opcode containing a `0x0A` byte (e.g. 2594/2595
  `eEGS_HTTPNOTICE_CHECK_REQ/ACK`, 2712/2713 Steam billing) and 2007.
- `assets/opcode_pairs.tsv`: the client's own request→response map
  `0x00F49CE8` (491 pairs). Cross pairs are real: cheat requests answer with
  the normal ACK, and every regional authenticate request (Steam 5386, CYOU,
  WAYI, ...) answers with 5020.
- `assets/opcode_flags.tsv`: map `0x00F49D04`, values 0/16/17/33/41/64/129;
  meaning not recovered.
- `tools/reverse/opcode_xrefs.py` → `research/opcode_xrefs.tsv`: per opcode, client
  senders (push + event constructor `0x00408C60`/`0x007AEE00`), switch
  dispatchers, and registered handlers (`call 0x0075F080` registrations plus
  the runtime map). 620 of 910 ACK/NOT opcodes have a receiver.
- `tools/codegen/extract_schemas.py` → `research/schemas.txt`: draft read schemas for
  298 registered handlers and 37 dispatcher cases, from the JSerBuffer reader
  calls (type codes 0..10 = i8,u8,i16,u16,i32,u32,i64,u64,f32,f64,bool;
  `0x0B` wstring, `0x0C` string, `0x1B` varint, `0x0E` raw bytes). Validated on
  5046: it reproduces the hand-recovered schema and adds the `vecTargetState`
  element `{i32, bool, bool}`. Tag `0x1E` is implicit on the wire. Loops and
  branches are flattened; confirm before use.

Implemented from these drafts (headless-tested): 5124 → 5125
`eERC_GTARGET_LIST_ACK` (result + empty vector of `{i32,bool,bool}`), 2369 →
2370 `eEGS_BILLING_GET_CURRENT_CASH_ACK` (result + 12 raw bytes, zero).

### Store, Skills & Social Opcodes (2026-11-16)

- `2032 eEGS_CHANGE_BAG_NAME_REQ` (`0x007528B0`) -> `2033 eEGS_CHANGE_BAG_NAME_ACK`: `bag_uid: i64, name: wstring` -> `result: i32, bag_uid: i64, name: wstring`.
- `2117 eEGS_UPDATE_SKILL_LOCKED_REQ` (`0x00790000.c:1390`) -> `2118 eEGS_UPDATE_SKILL_LOCKED_ACK` (`0x00752C70`): `skill_index: i16, locked: bool` -> `result: i32, skill_index: i16, locked: bool`.
- `2145 eEGS_DURABILITY_REPAIR_REQ` (`0x00790000.c:2123`) -> `2146 eEGS_DURABILITY_REPAIR_ACK` (`0x007930D0`): tag 0x17 map -> `result: i32, b'\x17\x80' (empty map), remain_gold: i64`. An unaffordable repair returns `NOT_ENOUGH_AR` (`168`) and leaves the item unchanged.
- `2115 eEGS_ITEM_UPGRADE_REQ` (`0x00790000.c:296`) -> `2116 eEGS_ITEM_UPGRADE_ACK` (`0x007909C0`): `target: i64, catalyst: i64, protect: i64` -> `result: i32` (1 rejection).
- `2086 eEGS_BUY_LIFE_WATER_REQ` (`0x00780000.c:11036`) -> `2087 eEGS_BUY_LIFE_WATER_ACK` (`0x0078FF90`): `flag: bool` -> `result: i32, flag: bool, remain_currency: i64`.
- `2128 eEGS_USE_SPEAKER_ITEM_REQ` (`0x00790000.c:1992`) -> `2129 eEGS_USE_SPEAKER_ITEM_ACK` (`0x0077F320`): `speaker_uid: i64, message: wstring, target_uid: i64` -> `result: i32, speaker_uid: i64, b'\x10\x80'`.
- `5121 eERC_GUILD_CREATE_PROPOSAL_REQ` (`0x00790000.c:2514`) -> `5122 eERC_GUILD_CREATE_PROPOSAL_ACK` (`0x00759750`): `guild_name: wstring` -> `result: i32` (0).
- `2150 eEGS_GUILD_CREATE_REQ` -> `2151 eEGS_GUILD_CREATE_ACK` (`0x00793720`): `guild_name: wstring` -> `result: i32, guild_uid: i64, guild_name: wstring, remain_gold: i64`.
- `2121 eEGS_CONTRACT_UPDATE_REQ` -> `2122 eEGS_CONTRACT_UPDATE_ACK` (`0x00752D80`): `contract_id: i32` -> `result: i32, contract_id: i32`.
- `2143 eEGS_DURABILITY_CHANGE_REQ` (`0x00790000.c:2049`) -> `2144 eEGS_DURABILITY_CHANGE_ACK` (`0x00774AE0`): tag 0x17 map -> `result: i32, b'\x10\x80'`.
- `2133 eEGS_FRIEND_LIST_UPDATE_REQ` (`0x00790000.c:1735`) -> `2134 eEGS_FRIEND_LIST_UPDATE_ACK` (`0x00752E80`): `friend_uid: i64, memo: wstring` -> `result: i32, friend_uid: i64, memo: wstring`.
- `2155 eEGS_GUILD_PERSON_JOIN_REQ` (`0x00790000.c:2837`) -> `2156 eEGS_GUILD_PERSON_JOIN_ACK` (`0x0075A220`): `guild_uid: i64` -> `result: i32` (0).
- `2160 eEGS_GUILD_INVITE_REQ` -> `2161 eEGS_GUILD_INVITE_ACK` (`0x00759870`): `target: wstring` -> `result: i32` (0).
- `2162 eEGS_GUILD_PERSON_LEAVE_REQ` (`0x00790000.c:2761`) -> `2163 eEGS_GUILD_PERSON_LEAVE_ACK` (`0x00759CA0`): empty -> `result: i32` (0).
- `2048 eEGS_CHANGE_BAG_PROPERTY_REQ` (`0x00550000.c:676`) -> `2049 eEGS_CHANGE_BAG_PROPERTY_ACK` (`0x00774040`):
  `nBagUID: i64, ucProperty: u8` -> `result: i32, nBagUID: i64, ucProperty: u8`. Updates bag tab filter `+0x28`.
- `2053 eEGS_MODIFY_SKILL_SPEECH_REQ` (`0x00780000.c:9674`) -> `2054 eEGS_MODIFY_SKILL_SPEECH_ACK` (`0x0078E090`):
  `sKindNameIndex: u16, speech: wstring` -> `result: i32, sKindNameIndex: u16, speech: wstring`. Sets shout text for skill invocation.
- `2055 eEGS_DELETE_SKILL_SPEECH_REQ` (`0x00780000.c:9708`) -> `2056 eEGS_DELETE_SKILL_SPEECH_ACK` (`0x0078E270`):
  `sKindNameIndex: u16` -> `result: i32, sKindNameIndex: u16`. Clears shout text.
- `2067 eEGS_BUY_ITEM_REQ` (`0x00780000.c:10667`) -> `2068 eEGS_BUY_ITEM_ACK` (`0x0077E2F0`):
  `store_id: i32, item_id: i32, count: u16` -> On success: `result: i32 (0), tag 0x1e store record (32 bytes), prefix: i32, gold: i64, tag 0x10 items vector (0x004B94C0), u32, u16, i64, u32`. Deducts gold, adds items to inventory, and saves player state.
- `2069 eEGS_SELL_ITEM_REQ` (`0x00780000.c:10700`) -> `2070 eEGS_SELL_ITEM_ACK` (`0x0077E8E0`):
  `npc_id: i32, item_uid: i64, count: i32` -> On success: `result: i32 (0), tag 0x10 items vector, gold: i64, tag 0x1e repurchase record (Item struct + i32 + i64), tag 0x13 map`. Removes item count, adds gold, and saves player state.
- `2071 eEGS_REPURCHASE_ITEM_REQ` (`0x00780000.c:10735`) -> `2072 eEGS_REPURCHASE_ITEM_ACK` (`0x0077EC30`):
  `item_uid: i64` -> On success: `result: i32 (0), tag 0x10 items vector, gold: i64`.
  The returned equipment keeps the durability, upgrade step and quality it had when sold.
- `2179 eEGS_GUILD_MONEY_IN_REQ` (`0x00790000.c:3031`) -> `2180 eEGS_GUILD_MONEY_IN_ACK` (`0x00794250`):
  `amount: i64` -> `result: i32 (0), remain_gold: i64`. Deposits gold into guild bank and updates player gold.
- `2181 eEGS_GUILD_MONEY_OUT_REQ` (`0x00790000.c:3141`) -> `2182 eEGS_GUILD_MONEY_OUT_ACK` (`0x00794470`):
  `amount: i64` -> `result: i32 (0), remain_gold: i64`. Withdraws gold from guild bank and updates player gold.
- `2183 eEGS_GUILD_LEVEL_UP_REQ` (`0x00790000.c:3250`) -> `2184 eEGS_GUILD_LEVEL_UP_ACK` (`0x00753380`):
  empty / i32 prefix -> `result: i32 (0), new_level: i16`. Increments guild level.
- `2185 eEGS_GUILD_NOTICE_MODIFY_REQ` (`0x00790000.c:3278`) -> `2186 eEGS_GUILD_NOTICE_MODIFY_ACK` (`0x0075A120`):
  `notice: wstring` -> `result: i32 (0)`. Sets guild notice.
- `2188 eEGS_GUILD_NOTICE_DELETE_REQ` (`0x00790000.c:3388`) -> `2189 eEGS_GUILD_NOTICE_DELETE_ACK` (`0x0074B830`):
  empty / i32 prefix -> `result: i32 (0)`. Clears guild notice.
- `2214 eEGS_GUILD_ALL_SKILL_INIT_REQ` -> `2215 eEGS_GUILD_ALL_SKILL_INIT_ACK` (`0x00752D80`):
  empty / i32 prefix -> `result: i32 (0), param: i32 (0)`. Resets guild skills.
- `5087 eERC_LEVEL_UP_NOT` (`0x0078CCF0`) & `5086 eERC_CHANGE_EXP_NOT` (`0x007775F0`):
  Triggered when EXP overflows `UPExp` from `charstat.lua`. Emits level up (new_level, max_hp, max_mp) and 5086 exp details, granting 3 SP per level.
- `2139 eEGS_FRIEND_LIST_ADD_REQ` (`0x00790000.c:1595`) -> `2140 eEGS_FRIEND_LIST_ADD_ACK` (`0x007591A0`):
  `char_name: wstring` -> `result: i32` (0xCE player offline / not found).
- `2135 eEGS_FRIEND_LIST_DELETE_REQ` (`0x00790000.c:1824`) -> `2136 eEGS_FRIEND_LIST_DELETE_ACK` (`0x00759560`):
  `char_uid: i64` -> `result: i32, char_uid: i64`.
- `2221 eEGS_POST_SEND_REQ` (`0x00795D70`) -> `2222 eEGS_POST_SEND_ACK` (`0x00795F40`):
  Sends mail: `result: i32 (0), items: tag 0x10 vector`.
- `2223 eEGS_POST_READ_REQ` (`0x007963C0`) -> `2224 eEGS_POST_READ_ACK` (`0x0075A660`):
  `mail_uid: i64` -> `result: i32 (0), mail_uid: i64`.
- `2225 eEGS_POST_GET_APPEND_ITEM_REQ` (`0x0079664C`) -> `2226 eEGS_POST_GET_APPEND_ITEM_ACK` (`0x0077F8E0`):
  `mail_uid: i64` -> `result: i32 (0), mail_uid: i64, gold: i64, items: tag 0x10 vector`.
- `2236 eEGS_POST_DELETE_REQ` (`0x007964EC`) -> `2237 eEGS_POST_DELETE_ACK` (`0x007715F0`):
  `mail_uids: tag 0x10 vector` -> `result: i32 (0), mail_uids: tag 0x10 vector`.
- `5069 eERC_REQUEST_TRADE_REQ` -> `5070 eERC_REQUEST_TRADE_ACK` (`0x00770E50`):
  `target_uid: i64` -> `result: i32 (0), target_uid: i64, target_name: wstring`.
- `5071 eERC_ACCEPT_REQUEST_TRADE_REQ` -> `5072 eERC_ACCEPT_REQUEST_TRADE_ACK` (`0x007587B0`):
  `source_uid: i64` -> `result: i32 (0), source_uid: i64, target_uid: i64`.
- `5073 eERC_CANCEL_TRADE_REQ` -> `5074 eERC_CANCEL_TRADE_ACK` (`0x0077DE00`):
  empty -> `result: i32 (0), items: tag 0x10 vector`.
- `5075 eERC_INSERT_TRADE_ITEM_REQ` -> `5076 eERC_INSERT_TRADE_ITEM_ACK` (`0x0077D980`):
  `item_uid: i64, slot: i32` -> `result: i32 (0), items: tag 0x10 vector`.
- `5077 eERC_DELETE_TRADE_ITEM_REQ` -> `5078 eERC_DELETE_TRADE_ITEM_ACK` (`0x0077DBB0`):
  `item_uid: i64` -> `result: i32 (0), items: tag 0x10 vector`.
- `5079 eERC_UPDATE_TRADE_AR_REQ` -> `5080 eERC_UPDATE_TRADE_AR_ACK` (`0x00758940`):
  `gold: i64` -> `result: i32 (0), char_uid: i64, gold: i64`.
- `5081 eERC_ACCEPT_TRADE_REQ` -> `5082 eERC_ACCEPT_TRADE_ACK` (`0x0078EB40`):
  empty -> `result: i32 (0), char_uid: i64, accepted: bool`.
- `5083 eERC_FINALLY_ACCEPT_TRADE_REQ` -> `5084 eERC_FINALLY_ACCEPT_TRADE_ACK`:
  empty -> `result: i32 (0)`.
- `5049 eERC_INVITE_REQ` -> `5050 eERC_INVITE_ACK` (`0x00758700`):
  `target_uid: i64` -> `result: i32 (0)`.
- `5054 eERC_ACCEPT_INVITE_REQ` -> `5055 eERC_ACCEPT_INVITE_ACK`:
  `host_square_uid: i64, host_uid: i64` -> `result: i32 (0)`.
  The host-only request remains supported for headless callers.
- `5015 eERC_CHANGE_TEAM_REQ` -> `5016 eERC_CHANGE_TEAM_ACK`:
  `team_id: i32` -> `result: i32 (0), team_id: i32`.
- `5040 eERC_CHAT_REQ` (`0x007AC5E0`) -> `5041 eERC_CHAT_ACK` (`0x007AC890`):
  Tag `0x1E` chat struct (`channel: u8, sender: wstring, target: wstring, message: wstring`).
- `2078 eEGS_QUEST_GIVEUP_REQ` -> `2079 eEGS_QUEST_GIVEUP_ACK` (`0x006223B0`, reader `0x00A559F0`):
  observed request `J-wstring (timestamp text, meaning unknown), u32 quest_id` (same shape as 2073) -> `result: i32 (0)`, tag `0x10` i32 quest-id vector, 18-byte jInfo, tag `0x10` i32 vector, tag `0x10` item vector. Removes quest from active storage. The client looks each id up (`0x00A7B390`) and drops the ack if it is unknown.
  2078 is owned by the quest handler. Stall open uses 2340. Verified live with a 42-byte timestamp and a subsequent 2073 accept for the abandoned quest.
- `2080 eEGS_QUEST_FAIL_REQ` -> `2081 eEGS_QUEST_FAIL_ACK` (`0x006223B0`):
  `quest_id: u32` (request assumed to share the 2078 J-wstring prefix; not yet observed) -> `result: i32 (0), quest_id: u32`. Removes quest from active storage.
- `2254 eEGS_MAGICENCHANT_ENCHANT_REQ` -> `2255 eEGS_MAGICENCHANT_ENCHANT_ACK` (`0x00796DC0`):
  `item_uid: i64, catalyst_uid: i64, scroll_uid: i64` -> `result: i32 (0), items: tag 0x10 vector, gold: i64`.
- `2256 eEGS_MAGICENCHANT_ERASE_OPTION_REQ` -> `2257 eEGS_MAGICENCHANT_ERASE_OPTION_ACK` (`0x00797120`):
  `item_uid: i64` -> `result: i32 (0), items: tag 0x10 vector, gold: i64`.
- `2258 eEGS_MAGICENCHANT_EXPEND_SLOT_REQ` -> `2259 eEGS_MAGICENCHANT_EXPEND_SLOT_ACK` (`0x0077FC60`):
  `item_uid: i64, stone_uid: i64` -> `result: i32 (0), items: tag 0x10 vector`.
- `2284 eEGS_RANDOM_ITEM_UPGRADE_REQ` -> `2285 eEGS_RANDOM_ITEM_UPGRADE_ACK` (`0x0077FED0`):
  `item_uid: i64, stone_uid: i64` -> `result: i32 (0), items: tag 0x10 vector`.
- `2672 eEGS_FIX_ITEM_UPGRADE_REQ` -> `2673 eEGS_FIX_ITEM_UPGRADE_ACK` (`0x00783C40`):
  `item_uid: i64, stone_uid: i64` -> `result: i32 (0), items: tag 0x10 vector`.
- `5065 eERC_PICK_UP_ITEM_REQ` -> `5066 eERC_PICK_UP_ITEM_ACK` & `5068 eERC_PICK_UP_ITEM_RESULT_ACK` (`0x0078AD80`):
  `drop_uid: i64` -> `5066: result: i32 (0)` and `5068: result: i32 (0), picker_uid: i64` + Tag `0x1E` Item struct.
- `5114 eERC_GET_DROP_AR_NOT` (`0x00792700`):
  Emits monster gold drop pickup on screen: `result: i32 (0), gold: i32, drop_id: i32, picker_uid: i64`.
- `5118 eERC_FRIEND_MY_CONNECTION_NOT` (`0x0077A8A0`):
  `char_uid: i64, is_online: bool, param1: i64, param2: i64`.
- `5119 eERC_FRIEND_MY_DISCONNECTION_NOT` (`0x00758FA0`):
  `char_uid: i64, notify: bool`.
- `5096 eERC_UPDATE_CHAR_INFO_NOT` (`0x0078C990`):
  Tag `0x1E` Character Details struct + layer_net_id: real-time visual and stat synchronization.
- `2310 eEGS_CHAR_NICK_CHANGE_REQ` -> `2311 eEGS_CHAR_NICK_CHANGE_ACK` (`0x00780200`):
  `new_name: wstring, item_uid: i64` -> `result: i32 (0), items: tag 0x10 vector, new_name: wstring`.
- `2314 eEGS_GUILD_NAME_CHANGE_REQ` -> `2315 eEGS_GUILD_NAME_CHANGE_ACK` (`0x00780590`):
  `new_name: wstring, item_uid: i64` -> `result: i32 (0), items: tag 0x10 vector, new_name: wstring`.
- `2319 eEGS_KEYBOARD_SET_CUSTOM_KEY_REQ` -> `2320 eEGS_KEYBOARD_SET_CUSTOM_KEY_ACK` (`0x00753960`):
  `keys_blob: bytes` -> `result: i32 (0), keys_blob: wstring`.
- `2338 eEGS_ITEM_SPIRIT_CHANGE_REQ` -> `2339 eEGS_ITEM_SPIRIT_CHANGE_ACK` (`0x00780860`):
  `item_uid: i64, spirit_item_uid: i64` -> `result: i32 (0), spirit_uid: i64, items: tag 0x10 vector`.
- `5351 eERC_REQUEST_TEACHING_REQ` -> `5352 eERC_REQUEST_TEACHING_ACK` (`0x0075C200`):
  `target_uid: i64` -> `result: i32 (0), target_uid: i64, target_name: wstring`.
- `5353 eERC_ACCEPT_REQUEST_TEACHING_REQ` -> `5354 eERC_ACCEPT_REQUEST_TEACHING_ACK` (`0x0075C430`):
  `mentor_uid: i64` -> `result: i32 (0), accepted: bool, mentor_uid: i64, mentor_name: wstring`.
- `5355 eERC_TEACHING_GET_INFO_NOT` (`0x007A5890`):
  Teaching / mentoring status payload (Tag `0x1E` struct).
- `5344 eERC_TREASURE_START_NOT` (`0x007722F0`) & `5345 eERC_TREASURE_END_NOT` (`0x0075BC00`):
  Treasure instance round notifications.
- `5346 eERC_CITADEL_REWARD_NOT` (`0x007833F0`):
  Citadel round settlement: `result: i32 (0), tag 0x17 map, tag 0x10 items vector`.
- `5362 eERC_GOLDGOBLIEN_APPEAR_NOT` (`0x007A6D10`):
  Gold goblin spawns in dungeon: `goblin_id: i32, tag 0x10 items vector`.
- `5363 eERC_GOLDGOBLIEN_ATTACK_REQ` -> `5364 eERC_GOLDGOBLIEN_ATTACK_ACK` (`0x00784A10`):
  `goblin_id: i32, damage: i32` -> `result: i32 (0)`.
- `5365 eERC_GOLDGOBLIEN_DEAD_REQ` -> `5366 eERC_GOLDGOBLIEN_DEAD_ACK` (`0x00784CA0`):
  `goblin_id: i32` -> `result: i32 (0), goblin_id: i32, tag 0x10 items vector`.
- `5367 eERC_GOLDGOBLIEN_DISAPPEAR_NOT`:
  `goblin_id: i32`.
- `2335 eEGS_TITLE_CHANGE_REQ` -> `2336 eEGS_TITLE_CHANGE_ACK` (`0x007751C0`):
  `title_id: i32` -> `result: i32 (0), title_id: i32`.
- `2327 eEGS_ACHIEVE_GET_LIST_REQ` -> `2328 eEGS_ACHIEVE_GET_LIST_ACK` (`0x0079D650`):
  `result: i32`, struct `0x00A3E760` {tag `0x17` map `0x005EC140` (0x0F, u32 division, i64 counter),
  tag `0x17` map `0x00A3DC50` (0x0F, u32 JHashString(AchieveID), entry `0x00A1ED90`: i32 id, bool, i32,
  time64), bool}, tag `0x10` vector of 13-byte completion blocks (`0x0076B0C0` -> `0x00A1E7E0`:
  u32 achievement hash + 9 unrecovered bytes).
- `2444 eEGS_ACHIEVE_UPDATE_REQ` (sender `0x007992D0`): tag `0x10` vector of u32 achievement hashes
  the client completed itself (hidden/group types) -> `2445` (u32 result, `0x0074B830`). Not yet
  observed live.
- `2446 eEGS_ACHIEVE_DIV_UPDATE_REQ` -> `2447` (u32 result): tag `0x17` map (0x0F, u32 division,
  i64 per-run amount), sent after a dungeon run. Type 0 achievements (`achieve.lua`) complete when the
  summed (Accumulate 1) or best single (Accumulate 0) amount reaches GoalAmount.
- `2329 eEGS_ACHIEVE_CHANGE_NOT` (`0x0076C720`):
  3x Tag `0x17` map: real-time achievement progress updates (not sent yet).
- `2330 eEGS_ACHIEVE_COMPLETE_NOT` (`0x0079D240`):
  tag `0x10` vector of `0x00A1ED90` entries (applied to the achievement page), tag `0x10` vector of
  13-byte completion blocks: the handler looks each first u32 up (`0x00AABAB0`) and prints the
  completion message. All 37 `LoadRewardInfo` rewards are titles (RewardType 0); granting them is not
  implemented (the owned-title list is not recovered; the 2007 vector `0x004B1A60` holds i64 values).
- `2362 eEGS_AVATAR_ZAM_INSERT_REQ` -> `2363 eEGS_AVATAR_ZAM_INSERT_ACK` (`0x00782D00`):
  `avatar_item_uid: i64, zam_item_uid: i64` -> `result: i32 (0), items: tag 0x10 vector`.
- `2364 eEGS_AVATAR_ZAM_ERASE_REQ` -> `2365 eEGS_AVATAR_ZAM_ERASE_ACK` (`0x00782F40`):
  `avatar_item_uid: i64` -> `result: i32 (0), items: tag 0x10 vector`.
- `2348 eEGS_TAMEING_MONSTER_INSERT_REQ` -> `2349 eEGS_TAMEING_MONSTER_INSERT_ACK` (`0x00771A00`):
  Tag `0x1E` monster struct -> `result: i32 (0), tag 0x10 vector`.
- `2350 eEGS_TAMEING_MONSTER_DELETE_REQ` -> `2351 eEGS_TAMEING_MONSTER_DELETE_ACK` (`0x00771BB0`):
  `monster_id: i32, slot: i32` -> `result: i32 (0), tag 0x10 vector, deleted_slot: i32`.
- `2280 eEGS_INIT_SKILL_NOT` (`0x00797740`):
  `result: i32 (0), sp: i32, tag 0x17 skill map`.
- `2283 eEGS_PROMOTION_NOT` (`0x00797F00`):
  `result: i32 (0), new_class: u8, sp: i32, tag 0x17 skill map`.
- `2286 eEGS_REBIRTH_COIN_CHANGE_NOT` (`0x007983B0`):
  `result: i32 (0), coins: i16`.
- `2709 eEGS_USE_ARENA_SP_ITEM_REQ` -> `2710 eEGS_USE_ARENA_SP_ITEM_ACK` (`0x007A7CA0`):
  `item_uid: i64` -> `result: i32 (0), consumed_items: tag 0x10 vector, arena_sp: i32`.
- `5165 eERC_ARENA_BACK_TO_SQUARE_REQ` -> `5166 eERC_ARENA_BACK_TO_SQUARE_ACK` (`0x00758550`):
  empty -> `result: i32 (0)`.
- `5256 eERC_SECOND_PASS_CREATE_REQ` -> `5257 eERC_SECOND_PASS_CREATE_ACK` (`0x0075B020`):
  raw PIN blob -> `result: i32 (0)`.
- `5258 eERC_SECOND_PASS_MODIFY_REQ` -> `5259 eERC_SECOND_PASS_MODIFY_ACK` (`0x0075B050`):
  raw PIN blob -> `result: i32 (0)`.
- `5260 eERC_SECOND_PASS_AUTH_REQ` -> `5261 eERC_SECOND_PASS_AUTH_ACK` (`0x0075B080`):
  raw PIN blob -> `result: i32 (0)`.
- `6011 eERT_REQUEST_CHAR_INFO_REQ` -> `6012 eERT_REQUEST_CHAR_INFO_ACK` (`0x00790FA0`):
  `char_uid: i64` -> `result: i32 (0), flag: bool, tag 0x1E summary, 2x tag 0x10 item vectors`.
- `6028 eERT_REQUEST_ITEM_INFO_REQ` -> `6029 eERT_REQUEST_ITEM_INFO_ACK` (`0x00766C20`):
  `item_uid: i64` -> `result: i32 (0), item_uid: i64, tag 0x1E item struct`.
- `2250 eEGS_DIVIDE_ITEM_REQ` -> `2251 eEGS_DIVIDE_ITEM_ACK` (`0x0077F570`):
  `source_item_uid: i64, dest_item_uid: i64, count: i32, slot: i16` -> `result: i32 (0), items: tag 0x10 vector`.
- `2111 eEGS_USE_LEARN_SKILL_ITEM_REQ` -> `2112 eEGS_USE_LEARN_SKILL_ITEM_ACK` (`0x0078BCD0`):
  `item_uid: i64, skill_id: i16` -> `result: i32 (0), skill_id: i16, level: u8, item_code: i32, count: i32, items: tag 0x10 vector, sp: i32`.
- `2092 eEGS_INVENTORY_UPDATED_NOT` (`0x0077F070`):
  Tag `0x10` deleted_items + Tag `0x10` added_items: live bag refresh.
- `2321 eEGS_ITEM_REMAIN_TIME_NOT` (`0x0077AED0`):
  `item_uid: i64, remain_seconds: i64`.
- `2322 eEGS_ITEM_DELETE_NOT` (`0x00774DD0`):
  `item_uid: i64`.
- `2179 eEGS_GUILD_MONEY_IN_REQ` -> `2180 eEGS_GUILD_MONEY_IN_ACK` (`0x00794250`):
  `amount: i64` -> `result: i32 (0), remain_gold: i64`.
- `2181 eEGS_GUILD_MONEY_OUT_REQ` -> `2182 eEGS_GUILD_MONEY_OUT_ACK` (`0x00794470`):
  `amount: i64` -> `result: i32 (0), remain_gold: i64`.
- `2157 eEGS_GUILD_INFO_NOT` (`0x00752FF0`) & `2158 eEGS_GUILD_PERSON_LIST_NOT` (`0x0077ABA0`):
  Guild summary (Tag `0x1E`) and guild roster (Tag `0x10`).
- `2164 eEGS_GUILD_PERSON_GRADE_MODIFY_REQ` -> `2165 eEGS_GUILD_PERSON_GRADE_MODIFY_ACK` (`0x00753170`):
  `member_uid: i64, new_grade: i16` -> `result: i32 (0), member_uid: i64, new_grade: i16`.
- `2183 eEGS_GUILD_LEVEL_UP_REQ` -> `2184 eEGS_GUILD_LEVEL_UP_ACK` (`0x00753380`):
  empty -> `result: i32 (0), new_level: i16`.
- `2185 eEGS_GUILD_NOTICE_MODIFY_REQ` -> `2186 eEGS_GUILD_NOTICE_MODIFY_ACK` (`0x0075A120`):
  `notice: wstring` -> `result: i32 (0)`.
- `2205 eEGS_GUILD_SKILL_NOT` (`0x00779390`):
  `flag: bool, tag 0x10 vector`.
- `2228 eEGS_DEPOT_SAVE_AR_REQ` -> `2229 eEGS_DEPOT_SAVE_AR_ACK` (`0x00795220`):
  `gold: i64` -> `result: i32 (0), tag 0x17 map, new_gold: i64`.
- `2230 eEGS_DEPOT_LOAD_AR_REQ` -> `2231 eEGS_DEPOT_LOAD_AR_ACK` (`0x00795490`):
  `gold: i64` -> `result: i32 (0), tag 0x17 map, new_gold: i64`.
- `2227 eEGS_POST_NEW_ARRIVAL_NOT` (`0x007965B0`):
  empty -> HUD mail notification icon.
- `2234 eEGS_POST_RETURN_REQ` -> `2235 eEGS_POST_RETURN_ACK` (`0x00771470`):
  `mail_id: i64` -> `result: i32 (0), tag 0x10 vector`.
- `2109 eEGS_INSERT_AP_NOT` (`0x00790480`):
  `current_ap: i32, total_ap: i32`.
- `2085 eEGS_CHANGE_DUNGEON_PENALTY_NOT` (`0x0078FA70`):
  `in_dungeon: bool, is_penalty: bool, penalty_level: i16, penalty_id: i32, duration: i32`.
- `2196 eEGS_RANDOMBOX_RESULT_ITEM_NOT` (`0x0075A2E0`):
  `result: i32 (0), item_code: i32, count: i16, is_jackpot: bool`. The emulator now sends this after
  the `2037` inventory delta for successful `DictRandomBox` rolls; `is_jackpot` remains false until its
  client meaning is recovered. Live confirmation of the success UI is pending.

## 7. App states and tutorial exit (static, 2026-11-16, saitatter machine)

App-state enum (registered at `0x00705CD0` as `eAS_* = %d`): 0 SelectChar,
1 Lobby, 2 GamePlay, 3 GameDuel, 4 SquarePlay, 5 MapTool, 6 CharTool, 7 Logo,
8 DungeonGate, 9 Tutorial (the table continues). State objects sit at
`JAppStateMgr+4+idx*8`; RTTI gives the vtables, e.g. `JAppStateTutorial`
`0x00CDDF6C` and `JAppStateSquarePlay` `0x00CE16FC`.

`JAppStateMgr` (`0x006F2E10` request, `0x006F8250` update) commits a requested
state only when the previous state's vtable slot `0x2C` (can leave) and the next
state's slot `0x30` (can enter) both return true. Otherwise, after 5000 ms it
logs `change state fail!, time over` and falls back to `0x006D8C80`, i.e. the
previous state (`+0x5CC`). **This is why "skip tutorial" restarted the
tutorial:** SquarePlay could not be entered, so the client returned to Tutorial.

`JAppStateSquarePlay` can-enter (`0x006FA540`) reads the player object
(`0x0043A180` → `0x00946540`) `+0xF0`, u64 `nJoinLayerNetID`. `-1` fails. The
high dword (`0x00A45380`) must be a square key in `DictMap+0x3C`
(`0x00990030`), otherwise it shows "invalid layer netid" and fails. Squares come
from `DictMap:LoadSquare` (`0x0098FD00`) in `Data/Dict/maplist.lua`; their
`SquareID` strings (`Act1`, `Act2`, `ArenaLobby`, `Act4`) are keyed with
JHashString: DJB2, seed 5381, `h = h*33 + (signed byte)` over the UTF-16LE bytes
(`0x00B3B5A0` → `0x00B3AD70`). `jhash("Act1") = 0x5F98AFAE`.

`0x0095A150` copies the 2007 character details (reader `0x00A52630`) into the
player object. Fields relevant here:

| Details offset | Player offset | Meaning (evidence) |
| --- | --- | --- |
| `+0x5F` u64 | `+0xF0` | `nJoinLayerNetID`, checked by SquarePlay can-enter |
| `+0x9C` bool | `+0x80` | After selection `0x006F88C0` runs `ChangeState(eAS_Tutorial)` when 0 and `ChangeState(eAS_SquarePlay)` otherwise |

The emulator previously sent 0 at `+0x5F`. It now sends
`jhash("Act1") << 32 | 1`; the low dword is a local default whose meaning is not
recovered.

Tutorial exit: `g_jAS_Tutorial:On_Tutorial_Exit()` (`0x006E5C80`) sends 2082
(`0x0078F950`: i32 + bool, observed `ffffff7f 00`). 2083 leads to
`On_Tutorial_FadeOut` (`0x006F2EC0`) and `ChangeState(eAS_SquarePlay)`.

### 5045 → 5046 `eERC_BACK_TO_SQUARE_ACK` (`0x007897F0`)

Field names come from the handler's read-failure message:
`u32 result, u64 nJoinSquareUID, u64 nJoinLayerNetID, tag 0x10 vecTargetState
(0x00773870), bool bUseWaypoint, u64 iCurAr*`. Outside SquarePlay the handler
validates the layer like can-enter, stores it at player `+0xF0`, runs
`g_jAppStateMgr:ChangeState(eAS_SquarePlay)` when `JAppStateMgr+0x5C4 == -1`,
and reconnects the relay. Implemented as `BackToSquareAck`; `vecTargetState`
element layout is unknown and sent empty. The request body is not recovered.

Status: static reconstruction plus headless tests. A live run that confirms the
client enters SquarePlay after skip is still pending.

## 6. Mailbox (Post) System Specification (Opcodes 2219 - 2237)

Binary layout reconstructed from client senders and dispatch handlers:
- `0x007AEF70`: Opcode 2220 (`eEGS_POST_REQUEST_LIST_ACK`)
- `0x00795D70` / `0x00795F40`: Opcode 2221 / 2222 (`eEGS_POST_SEND_REQ` / `ACK`)
- `0x007963C0` / `0x0075A660`: Opcode 2223 / 2224 (`eEGS_POST_READ_REQ` / `ACK`)
- `0x0079664C` / `0x0077F8E0`: Opcode 2225 / 2226 (`eEGS_POST_GET_APPEND_ITEM_REQ` / `ACK`)
- `0x007965B0`: Opcode 2227 (`eEGS_POST_NEW_ARRIVAL_NOT`)
- `0x00A33907` / `0x00771470`: Opcode 2234 / 2235 (`eEGS_POST_RETURN_REQ` / `ACK`)
- `0x007964EC` / `0x007715F0`: Opcode 2236 / 2237 (`eEGS_POST_DELETE_REQ` / `ACK`)

### Mail Header & Payload Struct (Deserializer `0x00A55920`)
Element tag `0x1E` preceding each mail record:
1. `i64 mail_uid` (+0)
2. `u8 post_type` (+8): `0` = normal player mail, `1` = system/admin notice, `2` = returned mail
3. `i64 sender_uid` (+9): character UID of sender
4. `bool is_read` (+0x11): read status flag
5. `bool has_item` (+0x12): attachment flag (items or gold present)
6. `bool can_return` (+0x13): return eligibility (returned mails set to false)
7. `i32 remain_days` (+0x14): remaining days until expiry (default 30)
8. `i64 gold` (+0x18): attached money / AR
9. `i64 send_time` (+0x20): unix timestamp of dispatch
10. `J-wstring sender_name` (+0x28): character name of sender
11. `J-wstring title` (+0x44): subject line
12. `J-wstring content` (+0x60): message body
13. `tag 0x10 vector<Item>` (+0x7C): attached items serialized via standard Item struct `0x00A53F50`

### Post List Request & Ack (2219 → 2220)
- **Request 2219**: `i32 dummy` (observed `ffffff7f 00`).
- **Ack 2220 (`0x007AEF70`)**:
  - `u32 result` (0 = success)
  - `tag 0x17 map<i64, PostEntry>`: Inbox (received mails)
  - `tag 0x17 map<i64, PostEntry>`: Outbox (sent mails)
  - `u32 unread_count`: number of unread mails in inbox
  - `bool notify`: new mail indicator badge in UI

### Post Send Request & Ack (2221 → 2222)
- **Request 2221 (`0x00795D70`)**:
  - `J-wstring recipient`: target character name
  - `J-wstring title`: subject line
  - `tag 0x10 vector<i64>`: UIDs of inventory items attached to the mail
  - `i64 gold`: attached AR
  - `i64 extra`: payment-on-delivery (COD) requested gold
  - `bool is_cod`: COD flag
- **Ack 2222 (`0x00795F40`)**:
  - `i32 result` (0 = success, 0xCE = recipient not found / offline, 1 = insufficient funds)
  - `tag 0x10 vector<Item>`: updated inventory item states
  - `i64 remain_gold`: updated sender gold balance
  - `i16 daily_send_count`: sender's mails sent today
  - `i16 max_daily_send_count`: daily limit (default 30)

### Post Read Request & Ack (2223 → 2224)
- **Request 2223 (`0x007963C0`)**: `i64 mail_uid`.
- **Ack 2224 (`0x0075A660`)**: `i32 result, i64 mail_uid`. Marks mail as read in database.

### Post Claim Attachments (2225 → 2226)
- **Request 2225 (`0x0079664C`)**: `i64 mail_uid`.
- **Ack 2226 (`0x0077F8E0`)**:
  - `i32 result` (0 = success)
  - `i64 mail_uid`
  - `i64 gold`: claimed AR credited to player
  - `tag 0x10 vector<Item>`: claimed items added into player inventory bags.
  Transfers attachments atomically, clears `gold = 0, items = [], has_item = 0` on the mail record.

### Post Return & Delete (2234 → 2235, 2236 → 2237)
- **Return 2234 / 2235 (`0x00771470`)**: `i64 mail_id` -> `i32 result, tag 0x10 vector<i64> returned_mail_uids`. Swaps recipient and sender, sets `post_type = 2`.
- **Delete 2236 / 2237 (`0x007715F0`)**: `tag 0x10 vector<i64>` -> `i32 result, tag 0x10 vector<i64> deleted_mail_uids`. Marks mails as deleted.

---

## 7. Select Character Ack 2007 (`0x00A40760`) Full Field Layout

Decompiled directly from `0x00A40760` (invoked by handler `0x007AA4B0`):
1. `u32 result`: peeked via `0x00A1EA20(1)` then reread at cursor 0.
2. `varuint (max 3)`: custom tag flags.
3. `varuint (max 10)`: custom tag flags.
4. `struct 0x00A52630`: Character World Details (stats, visuals, face, hair, body sliders, join layer netid).
5. `4 x i64 + 2 x u8`: scalar fields (experience counters, world flags).
6. `tag 0x17 map (0x00A40720)`: attribute modifiers map.
7. `tag 0x10 vector (0x00558010)`: equipped and inventory bags (`0x2F` bytes each).
8. `tag 0x10 vector (0x004B9830)`: inventory items (Item struct `0x00A53F50`).
9. `tag 0x10 vector (0x004B2C30)`: quickslots (QuickSlot struct `0x00A49DC0`, 25 bytes).
10. `tag 0x10 vector (0x00A3EEC0)`: secondary quickslots / keybind mappings.
11. `tag 0x17 map (0x004B1240)`: learned skills map (skill_id -> level, lock state, speech text).
12. `tag 0x17 map (0x0076E560)`: skill combos / chain triggers.
13. `tag 0x13 set (0x0076A8C0)`: skill category unlocks.
14. `tag 0x17 map (0x00A3E410)`: passive abilities.
15. `i64 + 2 x i32`: current AP, total AP, combat rank.
16. `tag 0x17 map (0x00A3E450)`: active quests map (ActiveQuest struct `0x00A209B0`).
17. `tag 0x13 set (0x005EE0F0)`: completed quest tags.
18. `18 raw bytes (0x00641E00)`: untagged world navigation & coordinates block.
19. `tag 0x13 set (0x005EE0F0)`: secondary quest completion set.
20. `3 x i64 + 1 x i32 + 2 x i64`: PvP rating, duel statistics, win/loss counters.
21. `tag 0x10 vector (0x004B1A60)`: achievements / title unlocks.
22. `i64 + 2 x bool + f32 + 2 x i64`: movement speeds, mount status, active buffs.
23. `2 x tag 0x17 maps (0x00485220)`: social presence & friendship state.
24. `J-wstring (0x00B35AB0)`: guild title / player motto.
25. `struct 0x0074C1D0 -> 0x00A3E760`: Mailbox state (tag 0x1E):
    - `tag 0x17 map #1`: inbox mail summaries (`map<i32, i64>`)
    - `tag 0x17 map #2`: outbox mail summaries (`map<i32, struct 0x00A1ED90>`)
    - `bool notify`: new mail notification badge.
26. `tag 0x17 map (0x00A3EA00)`: temporary depot / warehouse slots.
27. `2 x i64 + 1 x i32`: extended character counters.
28. `2 x tag 0x10 vectors (0x004DA660)`: pet list & mount list.
29. `i16 + 2 x i64`: daily mail send count and reset timestamps.
30. `tag 0x17 map (0x005F9190)`: cash shop purchased perks map.
31. `tag 0x13 set (0x0076ABA0)`: unlocked emotes / gestures set.
32. `4 x tag 0x10 vectors (0x00A1E8C0, 0x00A3EDD0, 0x00A1EEA0, 0x00A1E900)`: taming monsters, arena presets, league records.
33. `i16 + tag 0x10 vector + tag 0x17 map + i16 + tag 0x17 map`: mentorship links, guild permissions, second password status.
34. `tag 0x10 vector (0x004B9210)`: trailing item updates vector.

