# Session handoff — 2026-11-20 (compressed)

## Dungeon room creation — Cristian, 2026-11-20

- 5001 uses the generated `CreateRoomReq` with an optional request header.
  The x86 sender at `0x0058B060` writes a J-wstring, two i32s, and two i16s.
  The two-client headless test covers both header forms and verifies that a
  truncated request leaves the current room open. Live room creation is pending.

## All message domains schema-generated — saita machine, 2026-11-20 (night)

- **Pipeline**: every module in `games/network/messages/` (15 domains, ~365
  classes) is generated from `schemas/*.jsch` by `tools/gen_messages.py`, as
  MHServerEmu does with `proto/` -> protogen. The format (anonymous `_` fields,
  `h32`, `raw[N]`, `if`/`endif`, `ok_only`, `header`/`header?`, containers) is in
  `schemas/README.md`. `tests/test_generated_messages.py` fails on stale output.
- **Verification**: before/after snapshots of every class (defaults, synthesized
  values, and decoding every captured body in `logs/wire.jsonl`). Live-flow
  replies are byte-identical (explicit checks for 5002/5004/5014/5018/5035/
  5036/5044/5091/5094 and SelectCharacterAck). Captured requests decode to
  the same values. Intended byte changes are listed below. 179 headless tests
  pass; headless tests now fail when the dispatcher logs a rejected request.
  **Not run against the real client this session.**
- **Header word corrected**: `0x00A1E620` does not write `ffffff7f`. That claim
  from the mail commit is fixed in PROTOCOL.md. The word is runtime-dependent,
  and the same sender produced both forms (2143, 2406, 5001, 5093). Schema policy:
  `header` when every capture (>= 2) has it, `header?` when mixed or uncaptured,
  none when never captured with it.
- **Bugs found and fixed**: struct tag `0x1E` emitted in 2220, 2465 and all stall,
  broker and arena structs. Lists sent as a bare length without elements in 2349,
  2351, 2435, 2465, 2481, 5146 and 2309. Unterminated varuint `17 00` in the arena
  team record. Requests that disagreed with their senders: 2053 wstr, 2111
  4-byte id, 2128/2133/2185/5121/5256-5260 J-wstrings, 2164 vector, 2254
  two i64, 2256/2364 extra i32, 2310/2314 i64 first, 5049 i64+bool+i64, 5054
  square+host, 5075 u16 slot, 5077/2228/2230 second i64, 6011/6028 extra fields,
  and empty 2468/2470/2484/5073/5081/5083.
- **Invented opcodes (needs a decision)**: the server's party/presence messages
  use 2100-2107 (client: eEGS_CHEAT_*) and 5021/5022 (client:
  eERC_CHANGE_ROOMHOST_REQ/ACK). The client has no handler for them (nor for
  5055/5056). They are kept as plain structs in `party.jsch` so the handlers and
  tests still work. The real client party flow is 5049-5051, 5054 and 5092.
- **Dispatcher**: a `WireError` from a handler is recorded as `bad-request` and
  no longer closes the connection.
- Next: a live run of login -> town -> dungeon -> mail/stall to confirm the
  generated requests against the real client; then the C# backend.

## Gate, result screen, dyeing, tutorial exit, hotbar — saita machine, 2026-11-20 (late)

Read this first; it corrects two claims in the "Dungeon difficulty" section below.

- **5018 result crash (cause from static analysis plus the client crash log)**:
  `0x0071F9F0` copies the 40-byte mapSingleReward block to JResultDirect `+0x74`. Field `+0x20`
  is the extra-box count: `0x0071FF0F` adds that many "extra_box" UI entries. The previous
  encoder put damage there (5850/14400). The client froze about 80 s after 5018 and logged
  `CRASH`. The fields are recovered in `SingleReward` (messages/dungeon.py). The earlier
  claim that `+0x7C` is a float gauge rate was wrong, because that check belongs to another
  class. The gauges read party member data.
- **5044 gate (static)**: the history value is a J-wstring map id, `u8 m_ucDiff` and a
  `u8` cleared flag. `0x00A4BC00` allows difficulty d when d-1 < m_ucDiff, or when
  d-1 == m_ucDiff with the flag set. `0x006D1120` auto-selects the map whose Difficult
  equals m_ucDiff, one step higher when cleared. Sending 3/1 everywhere therefore made
  "Unique" the default. The server now keeps `char['dungeon_history']`, the highest cleared
  difficulty from 5017 clears. Quest variants are excluded. History entries are sent only
  for cleared dungeons. The trailing i32 set holds **active quest ids**, not map ids. The
  gate hashes each map's `+0x44` (QuestLink) and offers or auto-selects the quest variant
  (e.g. Act1_G1_A16 for Q0002S01 "Violent Monsters") only when it is present.
  `assets/dungeon_maps.tsv` (MapID, DungeonID, Difficult, QuestLink) replaces the wrong
  `quest_play_maps.tsv`. **Not yet confirmed live.**
- **Dyeing (verified live)**: 2210 was unhandled, so the client dropped the connection
  while waiting for 2211. 2210 now leads to 2211 (`0x00511B70`: i32, 10-byte dye block,
  item vector) and the dye is consumed. The 2211 apply (`0x00515B40`) writes hair
  (stain Type 2) and skin (Type 3) dyes to player `+0xCC`/`+0xD4`. 2007 fills those blocks
  from details `+0x67`/`+0x71` (`0x0095A150`), so the server stores `hair_dye`/`skin_dye`
  and resends them. Persistence is covered by a headless test only. Item dyes (weapon, gear,
  pet) are not stored yet. They probably belong in the Item's two `0x00A4B250` arrays.
- **Tutorial skip (verified live)**: `0x0077EEB0` applies the 2083 item vector and enters
  town without a new 2007. The server now resends the whole inventory there, so a new
  knight keeps its armour.
- **Character select**: the second 2009 vector holds worn Item records per character
  (`0x00538DF0`). It was empty, so all models looked bare. Not yet confirmed live.
- **Hotbar**: 2046 carries the ffffff7f prefix. It was decoded as 255/255/255, so dragged
  entries vanished. Not yet confirmed live.
- **5092** invite by nickname (no dedicated ack, answered with 5050) and **2204**
  telemetry (recorded only). No opcode in `logs/wire.jsonl` is unhandled any more.
- Local DB note: Knight1/Knight2 had `tutorial_cleared` reset for the live test. A backup
  copy is in the session scratchpad and is not part of the repo.

- **Later the same session**: 5046/5031 now send `iCurAr` (current AR). The client showed
  0 AR in town after a dungeon. 5086's jGainExp ends with a J-wstring, not a float. Every 5086
  failed to parse, so the EXP bar moved only on level-up. The 5091 reward block starts with the
  item code (`0x00713AB0`); a UID there showed "unknown item". Counter achievements: 2446
  per-run division amounts are summed per character and complete Type 0 entries
  (`assets/achievements.tsv`, keyed by JHashString(AchieveID), confirmed in `0x00A50DA0`).
  2330 announces them and 2328 lists totals and completed entries. 5092 invites by nickname.
  2204 is recorded. `tools/gen_opcode_registry.py` regenerates `docs/OPCODE_REGISTRY.md`. The
  hand-written opcode tables in ROADMAP.md had wrong names and were replaced by a link.
  These fixes are headless-tested only.

- Achievements follow-up: the completion message comes from 2330's second vector (13-byte blocks,
  first u32 = hash), now sent; 2444 (client-detected completions, vector of u32) is accepted and
  validated against all 448 entries in `assets/achievements.tsv`. Rewards are titles only; the
  owned-title list is not recovered, so titles are not granted. Item dyes (weapon/gear) are not
  persisted: the 2211 apply (`0x00515920`) only stores hair/skin on the player; items take the
  ack's item vector, whose two 10-byte dye arrays (`0x00A4B250`) are reached through methods, so the
  array meaning needs a live weapon-dye capture.

Next targets: confirm the gate, character select, hotbar, town AR, EXP bar, chest names and
achievement completion live; then title ownership and item dye arrays. Then look at
fields still sent as zero: item dyes, mapSingleReward `+0x00`/`+0x14..+0x1C`, the first
5044 set, and the 2009 trailing map/set.

## Standalone Server Assets (Elimination of external data_root requirement) — saita machine, 2026-11-20

- Per user request to eliminate `data_root` / external client data dependency:
  Exported all client dictionary tables required by the server into clean, normalized TSV and JSON files in `assets/`:
  - `starter_equipment.tsv` (default class equipment)
  - `char_stats.tsv` (per-class HP, MP, UpExp progression)
  - `levelup_ap.tsv` (level up AP rewards)
  - `item_durabilities.tsv` (equipment max durability)
  - `equip_index.tsv` (item grade, demand level, demand class)
  - `item_fields.tsv` (item BuyPrice, SellPrice, BagSize)
  - `npcs.tsv` & `stores.tsv` (NPC IDs and store inventory lists)
  - `monsters.tsv` (monster HP, Lv, Exp, DropCnt)
  - `money_drops.tsv` (AR gold drop ranges)
  - `skills.tsv` (SP and AR learning demand costs)
  - `map_gates.tsv` (dungeon gate to dungeon IDs)
  - `quests.tsv`, `quest_missions.tsv`, `quest_chains.tsv`, `quest_item_groups.tsv` (quest rewards, chains, objectives, items)
  - `tutorial_rewards.tsv` (complete and skip rewards)
  - `cash_items.tsv`, `cash_packages.tsv`, `random_boxes.json` (cash shop items, packages, random box tables)
  - `looting.json` (dungeon monster drop tables, looting items, groups)
- Created `tools/export_assets.py` to regenerate all asset tables reproducibly from client Lua if ever needed. Total asset size is only ~1.6 MB.
- Updated `src/darkblood/games/game_data/client_dict.py` to read directly from `assets/` by default.
  Added test override support via `_env_override()` so in-memory mock tests in the test suite run flawlessly.
- All 172 unit tests pass standalone with `DARKBLOOD_CLIENT_DATA="C:\does_not_exist"`.

## Dungeon difficulty, end-of-dungeon chest & stats, quest item tracking — saita machine, 2026-11-20

- **Dungeon difficulty switching (Issue 1)**:
  `JAppStateDungeonGate` checks `*(int *)(in_ECX + 0x14)` in its `JDunHistory` map (`0x00A4BC00` `CheckDifficultyEnabled`).
  In Opcode 5044 (`SelectDungeonAck`), the server previously sent an empty map.
  Now populated via `gate_dungeons()` from `maplist.lua` with `(dungeon_id, max_diff=3, state=1)` encoded in the `0x17` map
  as `\x0f + wide_string(dungeon_id) + wide_string(map_code) + struct.pack('<BB', 3, 1)`.
  This unlocks Normal, Hard, Master, and Hero difficulty selection on the dungeon gate UI.
  **Superseded:** 3/1 also made the highest difficulty the default; see the section above.

- **End-of-dungeon chest opening (Issue 2)**:
  In Opcode 5091 (`ChoiceRewardPartyRankAck`, handler `0x0078D660`), when `char_uid == local_player_uid`,
  the client expects `tag 0x10 + vector of Item (0x004B94C0) + i64 new_gold (player +0x70)`.
  Because these trailing fields were previously missing, the client hit a packet read error at line 9410 and aborted,
  never calling `Lua_GetAppPage(0x1b); FUN_00560a20(...)` (which triggers the chest opening animation).
  Updated `ChoiceRewardPartyRankAck` to include the items vector and gold. When picking a card/chest (5090),
  the reward is added to player inventory and cleanly displayed on screen.

- **End-of-dungeon stats calculation (Issue 3)**:
  In Opcode 5018 (`FinishGameAck`, handler `0x007ADB60`), `mapSingleReward` provides 10 dwords (40 bytes) to `JResultDirect +0x74`.
  The 3rd dword (`+0x7c`, offset 8) is checked as a float rate `fVar12 = *(float *)(in_ECX + 0x7c)` in `00720000.c:5112`.
  If `<= 0.0`, line 5124 jumped to `LAB_007274e7`, bypassing all gauge initializations (`gauge_stylish`, `gauge_demolition`, `gauge_damage`)
  and rank score calculations.
  Configured `FinishGameAck` to encode `<iifiiiiiii` with float `1.0f` at offset 8, and populated non-zero combat metrics
  (score, kill_count, max_combo, clear_time, damage_dealt).
  **Wrong, reverted:** `+0x7C` here belongs to another class; this layout crashed the result
  screen (`+0x20` is the extra-box count). See the section above.

- **Quest "Support the Guards!" & Item Objectives (Issue 4)**:
  In `quest_act1.lua`, quest `Q0008S01` has two missions: `QM807` (meet Lloyd, index 0, type 5) and `QM815` (have Backup Order `Iquea0310`, index 1, type 1).
  Previously, `_activate_quest` initialized objective counters to `[]` for all quests except tutorial `0x34c58e7c`, and offer items handed over via 2037
  never evaluated item objectives. Consequently, `QM815` stayed at 0/1, preventing quest completion dialogue when meeting Lloyd.
  Added `quest_mission_counts()` and `quest_item_objectives()` in `client_dict.py`.
  `_activate_quest` now initializes counters according to the quest's mission count.
  Added `check_quest_item_objectives()` to update item objectives and dispatch Opcode 2075 (`QuestUpdateNot`) upon quest acceptance and item pickup.
  Consumed quest items are cleaned up on quest turn-in (2076 -> 2077).
  All 172 unit tests pass.


## Server Cash Shop catalog — saita machine, 2026-11-20

- `2712` resolves product IDs through the bundled `assets/cash_shop.tsv`.
  An operator can supply a complete `data/cash_shop.tsv` override or put
  that file in `DARKBLOOD_DATA`. An invalid catalog returns result 24 with
  diagnostics in the server log.
- Per user request, the public source tree includes the normalized 771-entry
  server catalog. The extracted Lua source and local override stay outside Git.
- All 171 tests passed. Isolated headless replay persisted the four captured
  products (847, 760, 22 and 862) using only the bundled catalog.
  The active diagnostic server was left running while the clients were in use.
- Cash package and random box contents still use the extracted game tables.

## Server compatibility cleanup — saita machine, 2026-11-20

- The user confirmed that the cleanup covers Python server adapters. The
  original client's native `steam_api.dll` hook remains part of local startup.
- The startup registry rejects duplicate opcode owners. Removed the anonymous
  login fallback, implicit character selection, and synthetic stall, arena,
  pet, and town position requests. Character selection and authentication
  are per game connection. All 171 headless tests passed.
- Restarted the server and diagnostic profile. Both original client windows
  authenticated as distinct accounts (`OfflinePlayer` and `Player2`), sent
  character selection, and exchanged traffic through the relay.
- Town presence is indexed by square and layer. The relay reuses the
  serialized roster across recipients of each membership update. Client
  playback profiling and shared dungeon instance ownership remain open.

## Quest abandonment and performance review — saita machine, 2026-11-20

- The live 2078 request on Mage1 carried a 42-byte UTF-16 timestamp and
  quest hash `0x8CD61A6C`. The stall alias's old length heuristic
  misrouted it and sent 2079 “personal shop open ack (uid=2 items=0).”
  2078/2080 now recognize the exact J-wstring plus u32 quest body,
  with one registered dispatcher entry for each opcode. The regression
  uses the full timestamp and preserves the stall alias tests.
  All 173 headless tests passed.
- Restarted the game listener with the fix. Mage1 retried at 00:16:27
  and received a successful 2079 for `0x8CD61A6C`. At 00:17:03 the
  same live client accepted the quest again and received 2074, with a
  fresh active quest record. The server and both clients stayed open.
- Used an isolated loopback benchmark of the relay's real 0x16 → 0x1A
  path. Median latency was 0.26–0.27 ms with capture enabled and
  0.059 ms disabled. Real town client sends remain about 215 ms apart.
  Compare client emission, receive/playback, and event-loop delay
  separately. The local script is `research/benchmark-relay-capture.py`.
- Architecture review pinned NexusForever and MHServerEmu sources. The
  ordered refactor targets and source links are in `docs/ARCHITECTURE.md`.
  Immediate targets are opcode ownership and measured client playback.

## Town update cadence, server labels, and cash shop — saita machine, 2026-11-20

- Both live clients sent event `0x4D` (town position revision inside the
  `0x53` peer bundle) about every 2.1 seconds. The sender at
  `0x0087C1F9` uses the budgeted path in `0x00966B90`, which adds
  2000 ms to the peer's last send timestamp at `0x00966C9C`.
  The loopback shim changes the verified instruction to 100 ms and
  preserves the per-update peer budget.
- `GAME_434` in `ui_st.dat` supplies “Other server.” The overhead name
  renderer uses `0x00A614A0` to extract bits 54–58 of the peer's packed
  ID, copied from the trailing 5027 field by `0x00944510`. The emulator
  now places its configured server-list key (1) in those bits.
- The supplied Downloads capture contained 21 Cash Shop 2712 requests,
  no 2067 NPC buy requests, and 16 finalization ACKs with result 1 and
  zero items. Observed product IDs resolve in the local catalogue.
  Replayed 847, 760, 22 and 862 against an isolated temporary character
  using the installed catalogue. All four returned 0 and filled four
  cells. The historical ACK does not distinguish catalog, inventory, or
  character failure. The new handler returns 24 with a local path in the
  server log when the catalogue is missing/empty, 442 for an unknown
  product, and 67 for a full bag. Result 1 is reserved for a missing
  character. All 173 headless tests passed.
- Rebuilt the x86 shim. Backups are `research/steam_api.live-before-town-update.dll`
  and `research/steam_api.build-before-town-update.dll`.
- Restarted the server and both clients with the changes. The shim logged
  the patch at `0x00966C9C`. Both clients had a median revision interval
  of 215 ms (55 and 50 sampled messages, respectively). A passive capture
  showed `ElfHunter1(Offline)` and `Mage1(Offline)` in the two windows.
  Both live 5027 messages carried key 1. The clients stayed connected.

## Party invitation acceptance — Cristian, 2026-11-20

Acceptance through `2102` or `5054` now requires a pending invite in an
existing party. A successful join consumes the invite. The headless flow
covers both valid accept paths, an absent party, a missing invite, and a
repeat acceptance. Live validation of the `5051` dialog remains open.

## Town peer rendering and movement verified — saita machine, 2026-11-20

- Started the server with the 512-bit Fast correction. Live peer sends
  returned success at both `0x00B762AC` and `0x00B763D3`. The clients sent
  reliable `0x15` frames and unreliable `0x16` messages. Offline decoding
  verified Fast CRCs on both clients' type-2, event-`0x53` payloads.
- Implemented `0x16` → `0x1A` forwarding within the current relay group.
  Writer evidence is `0x00B538FB`, and the receiving reader is
  `0x00B5A790`. The three-connection headless test covers forwarding,
  isolation across layers, and the existing reliable path. All 173 tests pass.
- Restarted the server and both multibox clients with the change. At
  00:03:41–00:03:42 local time Mage1 (UID 2) and ElfHunter1 (UID 3)
  entered town. Both client threads hit `0x00B5A8B5` (dispatch of a relayed
  payload) and `0x00B82C2D` (Fast CRC success). The user confirmed that
  both windows showed the other character and its movement.
- The server and both clients stayed open. The active local breakpoint
  profile traces receive and decrypt. The old send profile is retained as
  `research/client/bp.txt.peer-send-next`. Local evidence includes
  `logs/wire.jsonl`, `research/client/hook_log.txt`, and
  `research/fast-512-before-unreliable-forward.txt`. REA confirmed the
  Fast dispatch in `research/fast-peer-rea.json`
  (evidence `ev_16519ec626a41b065a17cf7b4877c0da92a466feada77f28008df3447ecfb5a3`).
- Next multiplayer milestone: verify the 5051 town party dialog and recover
  the remaining 5004 room member fields for shared dungeon entry.

## Live relay binding replay — saita machine, 2026-11-19

- The updated server accepted both reconnecting clients. The selection ACKs
  returned Mage1 (UID 2) and ElfHunter1 (UID 3). Their subsequent JoinGroup
  requests carried those UIDs, and both rosters mapped them to relay HostIDs
  6 and 7 on the same layer. Both clients received the reciprocal 5027 notices.
- Reliable peer transport carried `0x32` / `0x33` and internal peer RMIs
  `0xFDEA`–`0xFDEC`. No peer user message appeared in the sampled traffic.
  The local decoder `research/live-relay-resume.py` reads from the current
  gamectl session's wire offset and reassembles relay TCP frames.
- At the user's request, stopped the previous multibox processes and launched
  `OfflinePlayer` and `Player2` with the peer-send breakpoint profile in
  `research/client/bp.txt`. The previous profile is backed up as
  `bp.txt.before-peer-send-next`, and the old trace is in
  `research/hook-before-peer-send-relaunch.log`. The new hook log confirms
  the probe addresses were armed. The existing server stayed up.
- Live probes then isolated the failure. Town sends to relay HostIDs 10 and
  11 used mode 2 (`[ebp+0x1C]` at `0x00B762AC`) and returned 0 from
  encryption before routing. Mode 1 sends to the server returned 1.
  In the matching client image, `0x00B82D90` sizes the Fast schedule from
  the negotiated key size, and cipher dispatch `0x00B82AE0` accepts only
  512, 1024 and 2048 bits. The previous server supplied 128 bits. It now
  advertises 512 bits and includes 64-byte Fast keys in peer joins, while
  retaining 128-bit AES. All 173 headless tests passed.

## Relay character binding and peer-send trace — saita machine, 2026-11-19

- Continued from `4845213`. Both multibox clients were connected to the game
  and relay listeners at the start. The initial server later stopped while
  both windows remained open. Started the updated server with
  `python tools/gamectl.py start --server-only`. Checked both the packed
  executable and the analysis fixture against the hashes in `docs/STATUS.md`.
- The live pair used character UIDs 2 and 3 and relay HostIDs 20 and 21.
  The `0x00B761C2`/ `0x00B76229` sample for destination HostID 20 shows a
  non-null session key and a successful reliable encryption counter lookup.
  The town send caller at `0x0095C340` still saw zero. The two processes share
  the hook log, so the capture cannot correlate every send with its internals.
- In `logs/wire.jsonl` around 23:14:13 local time, each client responds to
  the other's `0x32` with a `0x33` carrying the same eight bytes. These are
  inner frames carried in raw `0x15` receives. The server intentionally skips
  separate `message` entries for `0x15`. This establishes that the reliable
  relay can carry control traffic between the two clients. The sampled period
  contained no relayed encrypted user message for town movement.
- The relay now binds each group join to the trailing character UID from RMI
  1001. It also checks that UID on RMI 1002, so a stale leave cannot remove a
  different character using the same connection. This removes the global
  selection FIFO. All reviewed joins and leaves after the local-UID fix
  carried positive values, including captured kind-2 joins. The current pair
  was already mapped correctly, so this is a separate correctness fix.
- All 173 headless tests pass. The three-connection relay test now binds from
  the wire and covers changing character on one TCP connection. The updated
  server listens on both local ports; the new code awaits a two-client replay.
- Next trace: `0x00B762AC` tests the encryption result, `0x00B763D3` stores
  the result returned by routing, and `0x00B53DB3` is the routing failure branch.
  The verified breakpoint profile is saved locally as
  `research/client/bp.txt.peer-send-next` for the next controlled client launch.
  Static outputs are `research/resume-send-routing.c` and
  `research/resume-peer-message.c`. The configured REA CLI retained the
  `0x00B76050` dossier in `research/resume-send-rea.json`
  (evidence `ev_b37f701827abdc6dcf4ffa8f1ddd71e5c0c1e1f37ddf1b1eefec9a1f3cd96e96`).
  Capstone confirmed the instruction boundaries for the next trace.

## Town peer visibility trace — saita machine, 2026-11-19 (live breakpoints)

Peers in town are still invisible. Two live clients, shim `bp.txt` tracer:

- 5027 (`0x00787790` → `0x00967590`) creates the peer `JUser`, but the scene actor
  lookup `0x00866C90` returns 0. Position is not taken from 5027 (`0x00944510`).
- The client never sends town movement to the game server (5030 is always the 13-byte
  layer request in all logs). Town presence and movement are P2P events
  (`JNetMsgHandler::OneET_*`) sent by `JP2PClient::SendTo` (`0x0095C1E0`, caller
  `0x00966970`).
- SendTo looks the peer UID up in the JP2PClient map (`0x0095A9F0`, clients at
  `0xF47A38 + i*0x80`, map head `+0x78`). That map is filled from relay 3001
  JoinGroupACK by `JS2CStub::JoinGroupACK` (`0x0096C220` → `0x00963CE0`, reader
  `0x0090DD90`). The server sent a 0x0F byte per pair that the client does not consume
  (`0x006AFA10` type check), so keys were garbage (live key `0x30F`). Fixed in
  `ef1430e`; after the fix the lookup succeeds.
- After the fix `CNetClientImpl` (vtable `0x00D6EF8C`) slot `+0xC8` (`0x00B55A30`) is
  called with HostID 4, count 1, a 0x38-byte message, and returns 0. Nothing new reaches
  the relay. Open hypotheses: the server must answer ProudNet RMI 0xFA04
  (P2PGroup_MemberJoin_Ack: group HostID, member HostID, event id), or the P2P
  0x32/0x33 exchange that repeats every ~1.7 s never completes. Next: trace inside
  `0x00B55A30` (call via `[this-0xAC]+0x14`) for the failure reason.
- Follow-up: `0x00B55A30` is an adjustor thunk to `0x00B75710` (builds user message type 2,
  calls `Send` `0x00B3FEC0`). SendTo uses the relay NetClient (not the game one) and
  `Send` returns 0 only for the peer HostID. Core per-destination send `0x00B76050`:
  encrypted messages need `GetCryptSessionKey` (vtable +0x54, `0x00B4B1F0`, peer key at
  peer+0xA0, valid flag +0x3E8) and, for reliable sends, NextEncryptCount (+0x44); failures
  log "CStartServerParameter.m_enableP2PEncryptedMessaging=false" / "Failed to Gain
  NextEncryptCount!!". Peer keys come from 0xF619 (`0x00B56830`: AES blob length =
  settings key bits/8, we send 16 bytes for 128 bits). Pending trace (bp.txt is set):
  `0x00B761C2` eax (crypt key), `0x00B76229` eax (encrypt count), error sites
  `0x00B765BB`/`0x00B765D9`/`0x00B76712`. Bring both characters to town and walk.
- Ruled out for town: 5024-5026 (party/duel/arena/siege P2P reports, `0x0094F7D0`) and
  `SetPeerInfo` (`0x0095BB70`, arena/duel/room paths only). There is no UDP socket.
- Tooling: both clients write the same `research/client/hook_log.txt`, so lines from the
  two processes can overwrite each other. `multibox.py start` without `--accounts` once
  picked Player2/Player3 while an old client was exiting. Use
  `--accounts OfflinePlayer Player2`. Original `bp.txt` is in `bp.txt.before-visibility`.

## Live multibox session and result codes — saita machine, 2026-11-19

- Two multibox clients (`OfflinePlayer`/Mage1, `Player2`/ElfHunter1) on the merged
  PRs #5-#10. Observed live: mutual 5027/5096 spawn, 5030 layer split (5039 to the
  peer, relay 0xF61E and a 1-member group), reunion on the same layer, and a
  single 5039 + 5022 departure on 5037. Relay rosters were correct after a server restart.
- Client ACK errors come from the `0x00F4BBBC` code map → `error_st.dat` text.
  `assets/result_codes.tsv` (497 codes) is generated by `tools/extract_result_codes.py`.
  Result 1 is "Unavailable character.": a full bag on 2038 showed it live. The server
  now sends 67 (full bag, 2039/5068) and 63 (missing item, 2039/2043). The 67 message
  is headless-tested only.
- GM `/bags` (chat) gives the character five 20-cell `Ibaga0003` bags. Live: 2007
  grew by 80 bytes after reselecting, and a 7-item cash package (`CPkg1Cash305`) then opened.
- Open observations: relay frames to a peer in another group are still sent by the
  client after 0xF61E (dropped by the relay). Unhandled ProudNet RMIs: 0xFA04 on group
  formation, 0xFA12 every 30 s with the peer HostID, and client 0xFA02 `<hostid> 0x1D`
  after a peer leaves. JoinGroup's last i64 is the character UID; it could replace
  the `pending_relay` FIFO.

## PR integration — saita machine, 2026-11-19

- Reviewed and merged open PRs #5–#10 (CristianVita) into `main` in creation order.
  All were based on `27fce6b`. Doc conflicts were resolved by keeping every section.
- #9 overlapped #5 in the leave/disconnect paths. `remove_session_player()` now
  delegates to the ownership check in `unregister_player(session=...)`, so stale
  cleanup and party retention from #5 still apply. The #5 disconnect regression now
  expects the single 5039 + 5022 departure pair that #9 introduced.
- #10's 28-byte JoinGroup/LeaveGroup argument check matches all 254 relay RMIs in
  the local `logs/wire.jsonl`. The first town join uses scope UID `-1`.
- 170 headless tests pass with Python 3.8. Live verification is still pending for party
  invite dialog (5051), layer visibility (5039/5027), relay groups and the 5014 error reply.

## Relay group isolation — Cristian, 2026-11-19

- The town trace changes the layer UID in `JoinGroup` when walking between
  subareas. The previous relay used one global roster. It now separates groups
  by the identifiers in the request and limits forwarding to the current group.
- Disassembly of `0xF61E` confirmed member HostID followed by group HostID.
  Group moves, explicit leaves, and disconnects now send this notification.
- The headless relay regression covers two layers, membership changes, a stale
  leave, and forwarding isolation. Live visual verification remains open.
  The relay still uses the existing FIFO to associate the first connection
  with a character. See `docs/PROTOCOL.md` for the wire observations.

## Town layer visibility — Cristian, 2026-11-18

- A reported player visibility issue led to comparing live `5030` requests
  with `5031`, `5027`, `5096` and `5039` in Ghidra and x86 assembly.
  The server previously acknowledged layer changes without updating visibility.
- Selection now keeps the chosen channel. Layer changes remove the peer from
  old viewers via `5039` and resend reciprocal spawn data to destination peers.
  Two-client regression coverage and all 165 headless tests pass. The baseline
  socket warnings remain. The visual result still needs two live clients.
- The same PR also covers departure on disconnect, return to character select
  and channel switches. Reopening a channel from character select no longer
  recreates the previous character's world entry before selection.

## Town party invitation notice — Cristian, 2026-11-18

- `5051` now sends the host summary and room fields read by `0x00A4AD10`.
  The host IDs are mapped by the UI at `0x0062BE50` and `0x0062BE63`.
  Town invites use constructor defaults for the room fields. See `docs/PROTOCOL.md`
  for the schema and the ignored `research/dungeon-invite-*.c` outputs.
- `5055/5056` were absent from the checked handler table and room dispatcher.
  Live validation of the invite dialog and shared room entry remains open.

## Room join and invite sender — Cristian, 2026-11-18

- Mapped the `5003` room UID, the outer `5004` reply, and the member record
  reader `0x00A533A0`. The same sender uses `5054` with square UID and host
  UID as a separate path. The server now reads the host from the second
  field. All 164 headless tests passed on the branch based on `main`, with
  the baseline socket warnings. See `docs/PROTOCOL.md` for addresses and evidence.
- Next, identify the nested peer fields and supply shared room membership
  and relay routing. Live room join remains open.

## Dungeon start readers — Cristian, 2026-11-18

- Verified the client hash before examining opcode 5014 in Ghidra and x86
  disassembly. The final collection is an inventory update vector. The first
  and third maps target peers by character ID. The second map's value reader
  is `0x00A52CF0`, with semantics still open. See `docs/PROTOCOL.md` for the
  reader chains and local evidence.
- The server now returns a result-only 5014 error for missing or malformed
  map codes. The valid solo response retains its established wire layout.
  The headless test exercises both paths. Live verification remains open.
- Fix `18430d4` is in PR #6 on `fix/dungeon-start-map`. All 165 headless
  tests passed on that branch. The run reported socket warnings also seen
  on the baseline. The party and reconnect fix is in the separate PR #5.
- Ghidra ran headless on this machine, and REA used the same local fixture
  through MCP. The saved REA evidence is `research/dungeon-5014-rea-evidence.json`.
  Focused decompiler output is in `research/dungeon-5014-*.c`. These files
  stay local under the ignored `research/` directory.
- Co-op entry still needs the room join exchange 5003/5004 and evidence for
  which peer data should populate the maps at the start of a shared room.

## Cristian pause — 2026-11-18 (analysis and test tooling)

- Ghidra 12.2 and the REA CLI and MCP tools are available locally. The static
  fixture `research/unpacked.analysis.exe` and its source dump `research/session.bin`
  are present. The full Ghidra project and decompiled function corpus mentioned
  below belong to the saita setup and were absent from this checkout. The fixture
  is for static analysis only. Keep any Ghidra output under git-ignored `research/`.
- `tools/tail_wire.py` reads the existing `logs/wire.jsonl`, prints the latest
  matching events, and exits. A continuous `--follow` mode for errors and
  unhandled opcodes is a proposal from the collaborator discussion.
- The collaborator also suggested restarting the server during a live test to
  exercise reconnect. A restart disconnects the client. The shim can bring it
  back to the server list, where the player resumes through the lobby.
- The three tooling suggestions (full local Ghidra export, continuous log
  monitoring, and a live restart check) were recorded for later consideration.
  This check inspected local files only. PR #5 contains the party and reconnect
  lifecycle fix described below, with 167 passing tests and live validation pending.

## Cristian resume — 2026-11-18 (party and reconnect lifecycle)

- Workspace `C:/Users/cri99/Projects/darkblood-server-emulator`. PR #3 was closed
  without merging. Started branch `fix/resume-2026-11-18` from fetched `origin/main`
  at `27fce6b`, preserving the previous notes branch and untracked `docs/LOCAL_SETUP.md`.
- Before extending co-op dungeon entry, source review found that `register_player()`
  called `unregister_player()`, which also removed party membership. Rejoining a square
  therefore dissolved the leader's party or removed a member. Registration now replaces
  world presence while keeping the party and rebinding the party member's session.
- Disconnect, leave-layer (5037), and leave-square (5032) now remove presence only when
  the requesting session owns the current registration. A delayed old disconnect or
  leave request preserves a replacement connection. Departure notifications are emitted
  once, upon actual removal. Closing transports reject writes before framing/logging.
- Added three regression tests in `tests/test_world_sessions.py` covering square changes,
  party transport replacement, overlapping reconnect cleanup, stale leave requests and
  leave-then-disconnect notification duplication. Existing multiplayer/party tests also pass.
- Validation on this machine uses `research/venv/Scripts/python.exe`. Baseline 164 tests
  passed with socket warnings. After the fix, all 167 tests pass in about eight seconds
  with no socket warnings in that run. `git diff --check` passes. The sandbox blocked
  asyncio's local socketpair, so socket tests required approved execution outside it.
- Live client verification remains pending. Co-op dungeon synchronization remains the
  next implementation milestone. The 5014 nonempty maps/vector and shared room entry
  still need recovered schemas before implementing multi-player start payloads.

Compressed on 2026-11-17 at the user's request. Earlier entries (2026-11-16 and the first part of 2026-11-17,
~800 lines) are in git history: `git log -p -- docs/SESSION_HANDOFF.md`. Evidence that still matters is
summarized below; detailed protocol notes live in `docs/PROTOCOL.md` and `docs/STATUS.md`.

## Read this first

- Goal: a reproducible offline server for the supplied Dark Blood client. Docs in English; talk to the user in Romanian.
- Pull/rebase `origin main` regularly, run `python -m unittest discover -s tests`, push verified work with
  Conventional Commits. Update this handoff and `ROADMAP.md` before ending a session.
- The user plays live while we work. Restarting `run_server.py` drops their client (the reconnect shim brings it back
  to the server list); say so in the same message or ask first. Do not drive the game UI while the user plays.
- Live packet watch: `logs/wire.jsonl` (server) and `research/client/hook_log.txt` (shim). A small tail script that
  prints client opcodes, server notes, `unhandled-event` and requests without a reply was used all session.

## Wire rules learned the hard way (check every new encoder against these)

1. **Tags outside 0x0F..0x1A are never on the wire.** `0x00B35010(tag)` consumes a byte only for 0x0F..0x1A.
   Struct tag `0x1E` (and `0x0D`) must not be emitted. Fixed so far: 2075, ActiveQuest/2074/2077, 5086, 5087,
   5064/5068 drop structs. **About 15 encoders still emit a literal `0x1e`** (arena, NPC store 2066/2072,
   events, guild, social 2?? summaries) — audit each against its reader.
2. **Most client requests start with the `ffffff7f` prefix** (`0x00408C60(op, -1, -1)` header). Decoders must
   skip it: fixed for 2038, 2040, 2042, 5065 (u32 drop uid), 5093. Drag 2036 has no prefix (live).
3. **The client's own UID is details `+0x1C`** (reader `0x00A52630`, copied by `0x0095A150` to player `+0x10`,
   returned by `0x00946570`). It was sent as 0 while everything else used the character id; now it is the id
   (edff688). Owner checks, user lookups and the revive page all depend on it.
4. **Incremental item records** (2037/2039/2043/rewards/shop) use owner `-1` (`items.UPDATE_OWNER`): per-item apply
   `0x008354D0` drops records whose owner differs from the inventory owner. **Empty cells** are uid -1 / code -1
   (outer ctor `0x004AAB20`); uid 0 / code 0 left ghost copies in the bag. Swaps send the vacating item first.
5. **Item Quality (+4) must be >= 0.** 0xFFFF left the stat tier unset and `0x009D7A50` returned -1.0 per item stat
   (Defense -44, 2 damage). Now 0 (live: Attack 28 -> 87.9, Defense -44 -> 8.4). UpgStep stays 0xFFFF.
6. Max durability is an i16 on the client: send `int(max)` (helmet 18.525 showed 19/18).
7. Many responses are waited for page-locally (not in `handler_map.txt`); check the page's `vf20` dispatcher
   (e.g. Cashshop `0x004DCCC0`, MonsterCard `0x0060B500`) before assuming a reply is ignored.

## Verified live on 2026-11-17

- Tutorial: hog kills (2353) -> 2075 progress, quest completion and exit; counters reset on each 2346.
- Reconnect after a server restart: shim resets the local UID to -1 (b104ead) so channel select sends 2008.
- Equip / unequip / weapon swap / drag display immediately; accessory slots Aclo 7, Anec 8, Aear 9-10, Arin 11-12.
- Death (5093/5094 echoes the request UID) and revive with a rebirth coin; no more crash at `0x0055BF71`.
- Item delete (2040) and use (2038); Steam cash-shop purchases (2712 -> unsolicited 2037 + 2714, free offline).
- Stats after the Quality fix (2406 reports attack/m.attack/defense/m.defense floats).

## Implemented 2026-11-17, headless only (verify live next)

- Monster EXP on 5063 from `monster.lua` (`Exp`, rounded), shared `_grant_exp` with quests (5087/5086 fixed).
- Monster drops (`games/loot.py`): `itemlooting.lua` LoadMonLooting per dungeon (MonID entries only for that
  monster), UsuallyProb scaled by HP/AveMonHP, item from OneItemID / ItemGroup / equipment criteria
  (`<lv><grade>_<Weapon|Armor|Accessory>`, class bit from Demand1Class). 5064 announces drops at the 5063 instance
  id; 5065 pick-up -> 5068 + 2037. Map `Act1_G1_A10` falls back to table `Act1_G1_A1` (assumption).
  Simulation: ~4.4% drop per normal hog, ~4.3 items per `1fpi03U0`.
- Cash packages (Type 36, PACKAGEnnn -> DictItem:LoadPackage) and random boxes (DictRandomBox) open on use;
  bag capacity (`free_bag_slots`, bag `b29`) is enforced for opening, buying and picking up.
- 5017 finish game -> 5018: full victory payload implemented in `dungeon.py` / `messages/dungeon.py` (u32 result, bool bVictory, wstring map_code, bool bSamePerson, tag 0x17 mapGuildPersonCnt, tag 0x17 mapSingleReward with 40-byte stats, 4x i32 ranks/box, tag 0x10 vecBonusMonster). Fixed client dropping out of 0x007ADB60 on truncated read. Dynamic rank calculation (SSS/SS/S/A) based on kills/score and reward statistics payload.
- Blood effect unlocked in options: `m_bAdultUser = True` in welcome 5020 ungrays `Btn_ShowBlood` (JNetUserMgr+0x4C / 0x00577860).
- Quest monster kill tracking: 5063 now resolves active quest objectives via `quest_monster_objectives()` and broadcasts 2075 progress updates.
- Learn skill list (2697 -> 2698): resolved UI freeze in `Lua_OnVirtualLearnSkill` (waiting for 0x0A8A in `0x0094E1F0`). Decoded wire format: 2697 prefix + tag 0x10 vector, 2698 result + tag 0x17 map + remain SP + remain Gold.
- Empty/record-only handlers: 2242->2243, 2446->2447, 2592 (no client handler), 2509, monster cards 2601/2608/2617.
- `GameSession.current_char()` replaces 26 copied character lookups.
- Depot / warehouse: 2228/2229 (DepotSaveArReq/Ack), 2230/2231 (DepotLoadArReq/Ack), 2242/2243 (DepotShareExpireTimeGetReq/Ack), 2461/2462 (DepotSlotExtendReq/Ack) fully wired to character store persistence.
- Codebase modularization: split monolithic `commerce.py` (~940 lines) into dedicated domain mixins: `src/darkblood/games/handlers/skills.py` (`SkillHandlers`), `src/darkblood/games/handlers/inventory.py` (`InventoryHandlers`), and streamlined `commerce.py` (`CommerceHandlers`).
- Shared `strip_prefix(data, prefix=b'\xff\xff\xff\x7f')` in `jser.py` adopted across all handler decoders.
- Audited and eliminated invalid literal `b'\x1e'` from encoders across all domain messages where client `0x00B35010` returns immediately without consuming wire bytes.
- The live character's bag was upgraded once to Ibaga0003 (20 slots) in `data/darkblood.db` (backup in scratchpad).
- **Pets, Mounts & Monster Taming Subsystem**: Opcodes 2348-2351 (Taming), 2434-2438 (Mount summon/dismiss/speed), 2464-2474 (Pet summon/dismiss/feed/rename/level) with SQLite persistence (`mounts`, `pets` tables) and automated flow tests (`test_pets_flow.py`).
- **PvP Arena, Duels, Teams & League Season Rankings**: Opcodes 5100-5113 (Duels), 5145-5154 & 2306/2307 (Arena rooms), 5269-5275 (Arena teams), 2550-2553 & 2475-2478 (League season rankings), 2709/2710 (Arena SP items) with dedicated tests (`test_arena_flow.py`).
- **Mailbox System (Post Office)**: Opcodes 2219-2227, 2234-2237 (list, read, send with attached gold and items, claim append items, delete, return, new arrival notice) with full persistence and tests (`test_mail_flow.py`).
- **Character Struct `0x00A40760` (Opcode 2007) Field Mapping**: All 34 sequential chunks mapped and documented, including mailbox substructure at `0x0074C1D0` -> `0x00A3E760`.
- **Master Opcode Registry**: Created `docs/OPCODE_REGISTRY.md` detailing 501 tracked opcodes, 298 client handler virtual addresses, 140 implemented server handlers, wire formats and packet semantics.
- **GameSession Pure Composition Refactoring**: Eliminated multiple inheritance mixins from `GameSession`. Replaced with central `PacketDispatcher` (`self.dispatcher`) and 11 domain service instances (`self.frontend`, `self.social`, `self.mail`, `self.square`, `self.commerce`, `self.inventory`, `self.skills`, `self.quests`, `self.dungeon`, `self.arena`, `self.pets`) inheriting from `BaseDomainService`. Two-way dynamic delegation preserves 100% backward compatibility for all existing tests and callers.
- **Personal Shop (Player Stalls in town) & Broker Marketplace (P7)**:
  - Personal stalls: Opcodes 2340/2341 (Start/Open, alias 2078/2079), 2342/2343 (Close, alias 2088/2089), 5242/5243 (Buy Stall Item, alias 2080/2081), 2090/2091 (Change Title), 6021/6022 (Get Products), and town broadcasts (5250, 5254, 5255). Atomic gold deduction/credit, inventory item transfer, and SQLite persistence managed by `PersonalShopManager`.
  - Broker Marketplace / Auction House: Opcodes 2262/2263 (List), 2264/2265 (MyList), 2266/2267 (Register Item), 2268/2269 (Buy Item), 2270/2271 (Cancel Listing), 2272/2273 (Price History) managed by `BrokerManager`. Verified by `tests/test_stall_flow.py`.
- Test suite expanded to **164 automated tests** passing 100% (0 failures, 0 errors).

## Open items (priority order)

1. **Co-op Dungeons Instance Synchronization (P6)**: Synchronized party dungeon entry and instance state across party members.
2. **Live verification of Depot / Warehouse, Mailbox, Pets, Stalls, and Party**: In-game client verification of storage, mail send/receive with attachments, pet summoning, personal stalls, and party invites.
3. **C# / .NET 8 Server Scaffolding (P10)**: Initialize `DarkBloodServer.sln` matching MHServerEmu architecture.

## Environment notes (saita machine)

- Workspace `C:\Users\saita\Desktop\repos\darkblood-server-emulator`; client copy `research/client/`
  (Data is a junction — never delete through it). Client data dictionaries: `..\darkblood-client-data\lua_src\data\dict`.
- Shim: `client_hook\build.bat` (vcvars inside; the `vswhere` warning is harmless). Copy `client_hook\steam_api.dll`
  to `research\client\` only while the client is closed. `research/client/bp.txt` arms the INT3 tracer
  (`<VA> [max=N] [expr ...]`; output lines `[BP <VA> #n ...]` in hook_log). Reading game memory from outside is
  denied (OpenProcess error 5) — use the tracer.
- Decompile with `tools\decomp.ps1 OUT.c 0xADDR...`; `research/decompiled/*.c` is a function corpus with names.
- Editing tip: Python heredocs that contain `\x..`/`\n` escapes inside triple-quoted strings were mangled several
  times this session; prefer the Edit tool for code containing byte literals.
