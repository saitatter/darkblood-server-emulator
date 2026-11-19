# Session handoff — 2026-11-17 (compressed)

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
