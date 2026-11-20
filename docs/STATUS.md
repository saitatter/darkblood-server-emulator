# Research status and handoff

## Gate history, result screen, dyeing and tutorial exit — 2026-11-20

- 5018: the 40-byte mapSingleReward block is recovered (`SingleReward`). `+0x20` is
  the extra-box count looped by `0x0071FF0F`. Sending damage there froze and crashed
  the result screen.
- 5044: the history entries hold the highest cleared difficulty per dungeon, now
  persisted per character. The trailing set holds active quest ids, which unlock the
  quest variants of a dungeon (map QuestLink).
- 2210/2211 dyeing is verified live. Hair and skin dyes persist through 2007 details
  `+0x67`/`+0x71`.
- 2083 resends the inventory: the tutorial skip enters town without a new 2007.
  Verified live.
- 2009 sends worn items for the character-select models. 2046 skips the request prefix.
- 5092 nickname invite; 2204 telemetry is recorded.
- 5046/5031 send the current AR (iCurAr). 5086 ends jGainExp with a J-wstring, so the EXP bar
  updates. The 5091 reward block starts with the item code.
- Counter achievements (2446 to 2330/2328) track per-character division totals.
  All 176 headless tests pass.

## Party invitation acceptance — Cristian, 2026-11-20

The server requires a pending invitation for `2102` and `5054` and consumes it
on acceptance. Host and party IDs resolve through separate lookups. Valid joins,
missing invitations, and repeated acceptance are covered headlessly.

## Standalone Server Assets and Client Data Elimination — 2026-11-20

The server no longer requires external client Lua dictionaries (`darkblood-client-data` or `$DARKBLOOD_CLIENT_DATA`).
All required game tables have been extracted into normalized TSV and JSON files under `assets/` (~1.6 MB total):
- Default starter equipment (`assets/starter_equipment.tsv`)
- Character stats and progression (`assets/char_stats.tsv`)
- Level up AP rewards (`assets/levelup_ap.tsv`)
- Equipment durability and grade/demand specifications (`assets/item_durabilities.tsv`, `assets/equip_index.tsv`, `assets/item_fields.tsv`)
- NPC and store vendor catalogs (`assets/npcs.tsv`, `assets/stores.tsv`)
- Monster combat and drop parameters (`assets/monsters.tsv`, `assets/money_drops.tsv`)
- Skill SP and AR demand tables (`assets/skills.tsv`)
- Dungeon map gates (`assets/map_gates.tsv`)
- Quests, mission objectives, chains, and item groups (`assets/quests.tsv`, `assets/quest_missions.tsv`, `assets/quest_chains.tsv`, `assets/quest_item_groups.tsv`)
- Tutorial rewards (`assets/tutorial_rewards.tsv`)
- Cash shop item properties, packages, and random box state probabilities (`assets/cash_items.tsv`, `assets/cash_packages.tsv`, `assets/random_boxes.json`)
- Dungeon monster drop tables (`assets/looting.json`)

All 172 unit tests pass completely standalone without any external client data directory.

## Server Cash Shop catalog — 2026-11-20

The purchase handler loads product IDs, item codes, and quantities from the
bundled `assets/cash_shop.tsv` or an operator-supplied override. The bundled
catalog contains 771 entries. The optional import tool creates an override
without overwriting operator edits. Cash package and random box contents
still come from the extracted game tables.
The 171 headless tests passed. A separate replay granted and persisted
products 847, 760, 22 and 862 with no extracted game data available.

## Opcode ownership and town presence — 2026-11-20

The startup registry rejects duplicate opcode registrations and calls domain
handlers through a uniform async signature. Removed the pre-ticket login
fallback, global character selection, and synthetic stall, arena, pet,
and position routes. Town presence is indexed by square and layer, and the
relay serializes the member roster once per join. All 171 headless tests pass.

## Quest abandonment and relay latency — 2026-11-20

The live 2078 request was routed to the stall alias because its timestamp
made it longer than the old heuristic allowed. Mage1 abandoned and then
accepted the same quest in a live replay after the original routing fix.
An isolated two-peer relay benchmark measured a 0.43 ms worst-run p95
with capture enabled. The town client emits revisions about every 215 ms.
See `docs/ARCHITECTURE.md` for the benchmark limits and refactor priorities.

## Town update cadence, player labels, and cash shop — 2026-11-20

Town position revisions arrived around every 2.1 seconds before the shim
change. The x86 patch lowers the client throttle to 100 ms; both live
clients then had a 215 ms median revision interval. Opcode 5027 now carries
the configured server key, and both nameplates show “Offline.”

The submitted Cash Shop log shows result 1 for zero granted items. The
current local data grants the captured products in a headless replay, and
the server now distinguishes missing catalog data, unknown products,
and insufficient inventory space. See the session handoff for the capture
and test results.

## Town peer rendering and movement — saita machine, 2026-11-20

Mage1 and ElfHunter1 rendered and moved in each other's clients, confirmed
by the live tester. Both client traces reached the `0x1A` payload dispatch
and passed the Fast CRC check. The relay sends `0x1A` for `0x16` requests
within each group. All 173 headless tests pass, including reliable and
unreliable forwarding isolation. Shared dungeon entry remains open.

## Town peer sends — saita machine, 2026-11-19

Two connected clients exchanged ProudNet `0x32`/ `0x33` control messages inside
reliable relay frames. A peer send reached key and reliable-counter lookup
successfully, but the game send caller still saw zero and the captured relay
stream had no encrypted peer movement payload. Town characters remain
invisible to one another. The next trace distinguishes payload encryption
from the subsequent transport send.

JoinGroup now uses the character UID in its payload, removing the dependency
on game selection order. The same connection can change characters, and a
leave for the former character preserves its replacement. All 173 headless
tests passed. A live reconnect verified both character UIDs in the shared
roster and reciprocal 5027 notices.

The next client trace captured town sends failing inside mode 2 encryption
at `0x00B762AC` and `0x00B763FD`. The Fast cipher only dispatches key
schedules of 512, 1024 or 2048 bits at `0x00B82AE0`. The emulator advertised
128 bits and now supplies 512-bit Fast keys in both settings and member joins.
Live verification showed mode 2 return success at `0x00B762AC` for both
peers. The prior server forwarded reliable `0x15` traffic but dropped the
newly observed `0x16` movement envelopes. The relay now forwards those as
`0x1A` per the client reader at `0x00B5A790`. All 173 headless tests pass,
including forwarding and isolation across two layers.

## Relay group isolation — Cristian, 2026-11-19

Town joins now use the observed square and layer identifiers for relay
membership. A moved or disconnected peer is removed with `0xF61E`.
Reliable forwarding stays within the sender's group. Headless coverage uses
three local relay connections. Live player visibility remains open.

## Town layer visibility routing — Cristian, 2026-11-18

Preserved the selected channel and used live `5030` layer IDs for peer
visibility. Added `5039` removal for old layer viewers and reannouncements
in the destination layer. See `docs/PROTOCOL.md`. All 165 headless tests pass.
Live rendering and relay position synchronization remain open.
The departure path now sends `5039` on disconnect, explicit leave, and channel
change. Returning to character select keeps the old character off-world when
the connection chooses another channel.

## Town party invitation notice — Cristian, 2026-11-18

Ghidra and x86 disassembly confirmed the 5051 host summary and room fields.
The server sends the corrected shape for town invitations. The wire fixture
and multi-client headless party flow cover it. Live dialog verification is open.

## Dungeon room join and invite sender — Cristian, 2026-11-18

Mapped the 5003 request, 5004 outer reply and member record from the local
client. The 5054 handler now uses the host UID that follows the square UID.
The full headless suite passes (164 tests). Live entry into a shared room
and the meanings of the remaining member fields are still open.

## Dungeon start ACK readers — Cristian, 2026-11-18

Ghidra and x86 disassembly identify the 5014 inventory vector and the three
outer map reader chains. Two maps apply data to peers by character ID. See
`docs/PROTOCOL.md` for addresses and limits. Invalid 5013 map strings now get a
result-only error. Co-op entry and live validation of the error remain open.

## Party retention and overlapping reconnect cleanup — Cristian, 2026-11-18

Source review found that square re-registration removed party membership and that an
older connection's cleanup could unregister a replacement session. Registration now
keeps the party and updates its transport. Disconnect and 5037/5032 removal check
session ownership and broadcast departure only after removal. Closing transports
reject writes. Three regression tests and the full suite pass locally (167 tests).
Live verification is pending. Co-op dungeon entry remains open.

## Subsystem Expansion & Master Opcode Registry — saita machine, 2026-11-17 (headless verified; 155 tests passing)

Major subsystems implemented, integrated, and verified with 155 automated tests:
- **Multiplayer Movement & Spatial Broadcasting (Milestone P6)**:
  - Wire messages `UserMoveNot` (Opcodes 5030 / 5031), `UserJoinSquareNot` (Opcode 5021), and `UserLeaveSquareNot` (Opcode 5022).
  - Spatial position updates (x, y, z, angle, move_state) decoded and tracked on `WorldPlayer` in `GameWorldManager`.
  - Movement notifications broadcast to connected occupants in the same square/layer.
  - Presence notifications broadcast to peers on square join, leave (5032/5037), and connection disconnect.
- **Party Management Subsystem (Milestone P6)**:
  - Implemented `PartyManager` singleton (`src/darkblood/games/world.py`) and wire messages (`src/darkblood/games/network/messages/party.py`).
  - Opcodes 2100-2101 & 5049-5050 (Invite request/ack, client handler `0x00758700`), Opcode 5051 (`PartyInviteNot`, handler `0x007706E0`).
  - Opcodes 2102-2103 & 5054-5055 (Join / accept request/ack), Opcode 5056 (`PartyAcceptInviteNot`).
  - Opcodes 2104-2105 (Leave request/ack with automatic host leader re-election).
  - Opcodes 2106-2107 (Party kick with leader permission checks and kick notice delivery).
  - Fully verified across multi-client sessions in `tests/test_party_flow.py`.
- **Pets, Mounts & Monster Taming Subsystem**:
  - Implemented `PetHandlers` (`src/darkblood/games/handlers/pets.py`) and wire messages (`src/darkblood/games/network/messages/pets.py`).
  - Opcodes 2348-2351 (Taming), 2434-2438 (Mount summon/dismiss/speed), 2464-2474 (Pet summon/dismiss/feed/rename/level).
  - SQLite tables `mounts` and `pets` in `data/darkblood.db`. End-to-end verified in `tests/test_pets_flow.py`.
- **PvP Arena, Duels, Teams & League Season Rankings**:
  - Implemented `ArenaHandlers` (`src/darkblood/games/handlers/arena.py`) and wire messages (`src/darkblood/games/network/messages/arena.py`).
  - Opcodes 5100-5113 (Duels), 5145-5154 & 2306/2307 (Arena rooms), 5269-5275 (Arena teams), 2550-2553 & 2475-2478 (League season rankings), 2709/2710 (Arena SP items).
  - Verified in `tests/test_arena_flow.py`.
- **Mailbox System with Attachments**:
  - Implemented `MailHandlers` (`src/darkblood/games/handlers/mail.py`) and wire messages (`src/darkblood/games/network/messages/mail.py`).
  - Opcodes 2219-2227, 2234-2237 (Mail listing, send with attached gold and items, read, claim items into inventory, delete, return, new arrival notice).
  - Verified in `tests/test_mail_flow.py`.
- **Character Struct `0x00A40760` (Opcode 2007) Field Mapping**:
  - All 34 sequential chunks mapped and documented, including mailbox substructure at `0x0074C1D0` -> `0x00A3E760`.
- **Master Opcode Registry**:
  - Created `docs/OPCODE_REGISTRY.md`: 501 tracked opcodes, 298 client handler virtual addresses, 140 implemented server handlers, wire formats and packet semantics.
- **C# Architectural Refactoring & Packet Dispatcher**:
  - Blueprint in `docs/ARCHITECTURE_REFACTOR_CSHARP.md` detailing migration from Python multiple inheritance mixins to composition.
  - Implemented prototype `PacketDispatcher` (`src/darkblood/games/dispatcher.py`) and `BaseDomainService` (`src/darkblood/games/handlers/base.py`).

## Live play-test fixes — saita machine, 2026-11-17 (static + headless; live retest pending unless noted)

Player reports from a live session, with the cause found in the wire log or client code:

- Give up quest: 2078 is `J-wstring (timestamp text) + u32 quest id`. The id was read from offset 0; the ack (reader `0x00A559F0`) carried an unknown id and the client dropped it.
- Character select "default town": `0x00704278` resolves the high dword of lobby `u64 +0x37` (nJoinLayerNetID) through `0x00990030`. Placeholder 17 → unknown → "default town".
- Skills lost on relog: 2007 map `0x4B1240` (struct `+0x2D3`) uses the 2698 element reader `0x4ACB80`; now filled from the stored skills.
- Bag equip (live verified: "Coarse Bag" appeared): 2026 = prefix + i64 bag item uid; 2027 (`0x00557860`) = `u32 result` + Bag struct (`0x00A1EC30`), bag id = item uid, capacity = item dict `BagSize`.
- Shop "Not enough products": store record (32 raw bytes, `0x00A489D0`) is `+0 hash, +4 AR price, +8 / +0xC other-currency prices (player +0x268 / +0x27C), +0x18 i16 stock (0 → flag 8, JERI_STOREMAXNUM_00), +0x1A i16 (-1: max = item stack)`. Flags `0x0059A280`, disable `0x0059A5DC`.
- Rewards "no space": reward placement only used the first bag and ignored its capacity; it now walks every bag's free cells.
- Level 4 vs 5: `CLASS_SECTION_MAP` was 1-based while CharacterClass is 0-based, so Warrior used the fallback EXP formula (HUD showed `EXP 316 / 1536` at server level 5). The live character was recomputed from total EXP.
- Lloyd quest (Q0008S01): 2113 eEGS_QUEST_UPDATE_MISSION_REQ (prefix + J-wstring mission id, `QM807`) was unhandled. Switch `0x00659F00` → 2114 handler `0x006481E0` reads only `u32 result`; progress goes through 2075.
- Dungeon clear froze: 5018 looked up `char['char_uid']` (absent), so `mapSingleReward` was empty; it now uses the character id (player UID, details `+0x1C`).
- Quickslots: 2007 vector `0x4B2C30` (struct `+0x2B3`, loaded by `0x00966080` at `0x007AA8A6`), element `0x00A49DC0` = `u8 type, u8 slot, i32 refID, i64 refUID, bool, i64, u16 0xFFFF`. Storage was keyed by slot only, so the item bar overwrote the skill bar.

Multibox (static + headless; two live windows not tried yet): `python tools/multibox.py start -n 2` launches clients against the running
server and tiles them on the primary monitor (`tile`, `status`, `stop`). All windows log in as the same local account, so give each window
its own character. The selected character is now kept per game connection (`GameSession.char_id`); the relay connection takes the oldest
pending selection on its first JoinGroup (`state.pending_relay`). Whether the client allows a second instance is not verified.

Accounts (live-verified with two windows): the client logs in only after the server sends 2 `eE_ACCEPT_NOT`; it then sends 5386 with its
SteamID and Steam auth ticket. The shim takes the account from `DARKBLOOD_ACCOUNT` (default `OfflinePlayer`), uses it as persona name
and SteamID low dword, and returns the ticket `DBACC:<account>;` from SteamUser slot 13 (`GetAuthSessionTicket`, previously NULL). The
server registers unknown names on first login (`accounts` table; OfflinePlayer = uid 1) and keeps characters per account. Without a 5386
within 3 s it falls back to the default account. The client also has an unused NA-dev ID/password form on the server-select page
(`MainLoginPage`, `TryLogin` `0x0063EB00` → the same 5386 sender; `OnRegister` is the shared stub `0x00464750`). The single-instance
mutex is "DarkBlood Online" (`0x00472579`); `tools/multibox.py` closes it in running clients and sets one account per window.

Options (`tools/patcher.py` GUI → `research/client/darkblood_options.ini`; static, patch bytes verified in a live client's memory):
- Tutorial skip rule: `JAppStateTutorial` Esc (`0x006FBC50`) opens MB_Tutorial_Exit only when user-manager `+0x65` (`+0x66` for class 5)
  is 0. `0x006F8A10` sets these from the 2009 character list (`class & 0xF` of each entry +0x09): 0 only if the list already held a
  character of that group, so a new account's first character cannot skip (seen live with a Player2 Elf Hunter). Option
  `skip_tutorial_always` patches `sete bl` at `0x006FBCEE` to `mov bl,1`.
- Logos: `JAppStateLogo` plays a clip queue (`+0x8C..+0x90`); `0x006F3950` ends the state (`0x006F2E10(1)`) when it is empty. Option
  `skip_logos` turns `je` at `0x006F39AB` into `jmp`. Whether a separate intro movie follows is not checked yet.
- `adult_content` (server) drives `m_bAdultUser` in the welcome.

Friends (static + headless): 2139 is `ffffff7f + J-wstring name` (live). 2140 (`0x007591A0`) = `u32 result` (0xCE not found) + friend
struct `0x00A49450` (`i64 uid, wstring name, u8, u8, i64 location (-1 = offline, counted by 0x00926800), wstring, i64, bool`); 2132 map
entries are `0x0F, i64 uid, struct`. Friends are stored per character and resolved across accounts.

Players do not see each other yet (live, two accounts in the same square). JoinGroupACK (3001) lists only the local character, while
`0x0096BC60` expects a P2P link to every other member; ProudNet P2P group membership and relayed P2P messages are not emulated. 5096 spawn
notices on the game connection do not make the other player appear.

Open: inventory shows "Ar : 0" although 2007 details `+0x45` carries the gold; drag-unequip to an empty cell looked wrong live (2036 acked, then a 2042 re-equipped); dungeon gate list content (2010/5043) still to inspect with the player; learning skills does not charge SP/AR.

## Default equipment slots — saita machine, 2026-11-16 ~22:30 (static + headless; live retest pending)

Report: the new Warrior looked wrong, and the tutorial sword did not show. `ensure_inventory` stored the default items in slots 0..7 in list order.
The slots have fixed meanings (`0x0070A8C0` maps slot to widget): 0 Weapon_1 (right), 1 Weapon_2 (left), 2 Armor, 3 Glove, 4 FootWear, 5 Belt,
6 Shoulder, 7 Cloak, 8 Necklace, 9-10 EarRing, 11-12 Ring, 13 Helmet. The Thief/Fighter lists happened to put armour first. The Warrior list put its belt
into the weapon slot and its sword into Belt. The slot now comes from the item: Abod 2, Aglo 3, Asho 4, Abel 5 (pants, BODY_B), Ader 6 (shoulder),
Ahel 13, confirmed by each item's PartFilePath/DropImgFilePath. Weapons take the right hand, then the left; a shield/book takes the left hand.
A third weapon (Knight: Wmack) goes to the bag. The two existing characters were fixed once in `data/darkblood.db` (no migration code).
Hotbar: the Fighter's first entry sent 2044 for skills 410/411 (the client assigns them itself). The Warrior session sent none. Quickslots are stored but not yet sent back in 2007.

## Borderless fullscreen — saita machine, 2026-11-16 ~21:55 (device level verified; visual check pending)

The game's "Full Screen" setting ("Window Mode" unchecked; JHoundOption +0x7C, RecreateDevice passes `bWindow = !+0x7C`) now runs
borderless. The shim replaces only `IDirect3D9::CreateDevice` (vtable slot 16, found through a throw-away IDirect3D9; no code patch in d3d9.dll;
the old inline Direct3DCreate9 hook was removed in 634b1e8 because it broke launch) and `IDirect3DDevice9::Reset` (slot 16 of the device vtable).
For an exclusive fullscreen request it sets `Windowed=TRUE`, sets the back buffer to the monitor size, and makes the window `WS_POPUP` covering its monitor.
Windowed mode is unchanged. `exclusive_fullscreen.txt` next to the exe disables the conversion.
Live log: the saved option requested `Windowed=0 2560x1440`, which became a windowed popup 2560x1440; the window style was `0x94000000`.
Follow-up: the 2474x1392 rect was the game shrinking the window to the work area (1440 minus the 48 px taskbar, same aspect ratio).
A window subclass now pins the window to the monitor rect (WM_WINDOWPOSCHANGING) and keeps WS_POPUP (WM_STYLECHANGING) while borderless is active.
A windowed request at another size turns borderless off. Live: rect 0,0,2560,1440, style 0x94000000.
The live check was stopped early because the test window opened under the user's foreground apps on the primary monitor.

## Return to the server list after a disconnect — saita machine, 2026-11-16 ~21:45 (live-verified)

Before this change, losing the server closed the client. `JUserClient::vf0c` (`0x007869A0`) sets `0x00F45204 = 1`,
sets byte 0 of the `0x00F36544` object to 1 (an input lock checked by `0x006E2400`), and opens `MB_DisconnectFromServer`.
That box's OnOK in `page_msgbox.xml` runs `g_jLobby:ExitGame()` (`Lua_ExitGame` `0x007381E0`).
The shim (`client_hook/steam_api_hook.c`) now hooks:
- `Lua_ExitGame` (prologue `6A 00 6A 00 6A 02`): while `0x00F45204 == 1` it clears both flags and releases the old
  NetClient through `0x00A5CF50`. The old instance never connects again, and the global "connected" bytes `0x00F29AE8..EA` stay at 1.
  It clears login flags +9/+10 of the `0x00F2EE90` singleton, because the welcome sets +9 (`0x0096B20B`) and Login refuses while it is set.
  Then it runs `JLobbyCommon::Login` (`0x00749EE0`, thiscall on `0x00456CE0`, arg = the id recorded at startup)
  and `FadeOut("g_jAppStateMgr:ChangeState(eAS_Lobby)", 0)` (as `Lua_GoBackToLobby` `0x006E25E0` does).
- `JLobbyCommon::Login` (prologue `6A FF 68 09 C4 BF 00`): records the startup login id (live: 13 characters).
- If Login gets no welcome (the server is still down), the box opens again (`0x00AF57A0`), and the next Ok retries.
  Entering the Lobby without a session left the server list stuck after Knock (2001 was acked, but 2021 was never sent), so that path is avoided.
Live: tested from character select and from the world (Northern Elwood). With the server down, Ok reopened the box. After the server restarted,
Ok led to Server List -> Channel List (2001/2021) -> 5028/2008 -> character select -> 2006 back into the world.
Any other ExitGame call still exits normally. The relay reconnects on its own (9401 connect observed).
Note: another agent (agy.exe) ran its own `run_server.py` on this machine during the test. Check for running servers before testing live.

## Log review: quickslots, tutorial completion, level-up class — saita machine, 2026-11-16 ~21:10

Source: wire log of the 20:56-21:05 session (new character, tutorial). Static + headless; live retest pending.
- The repeated connect/disconnect pairs every 4 s are `tools/dashboard.py` health probes (auto-refresh). They are harmless.
- 2044 quickslot: the live body is `ffffff7f` + u8 type + u8 slot + u32 ref + u64 ref_uid (18 bytes). The decoder read from
  offset 0, so it stored and echoed type/slot 255. Fixed.
- Tutorial never finished (the same pattern appears in the 05:00 session): the map trigger JBehaviorQuestStart (`0x0089B020`) sends 2346
  for `Q0882S01` (`0x34C58E7C`). Its missions are QM788/QM789 (targets 71/72, x2 each), and the closing NPC is `0mok01n2` (`0xEAEC51BD`, met at 21:04:12).
  The talk `SQ0882S01c1` runs `CompleteQuest('Q0882S01'); On_Tutorial_Exit(true)`. The 2347 reader (TalkBox `0x006481E0`) only checks the
  result, and only 2074 (`0x00659790` -> `0x00A60960`) adds a quest to the client's active list. The server now stores the quest and also
  sends 2074 after 2347. This is a hypothesis: confirm that the NPC offers the closing talk and that 2076 + 2082 follow.
- 2082 bool is read as "completed" (Exit(true) from the closing talk; the skip button sends 0). 2083 now carries the tutorialreward.lua
  items: CompleteLoad on completion, SkipLoad on skip, once per character. Reward potions are stored as one stack (Item Amount);
  equipment still takes one slot per piece.
- The quest-complete level-up read `char['class']`, but the key is `char_class`, so every class used the Warrior's level thresholds. Fixed.

## Legacy and migration code removed, data reset — saita machine, 2026-11-16

At the user's request, there is no legacy or migration code before the first release:
- Removed `legacy/speculative_prototype/`, the JSON stores (`CharacterStore`, `JsonCharacterStore`), the
  JSON auto-import/export of `SqliteCharacterStore`, and the inventory backfill/migration in `ensure_inventory`
  and in the select/drag/use/equip handlers. `ensure_inventory` now only initialises new characters at creation.
- `data/darkblood.db` and `data/characters.json` were deleted. The server starts with an empty SQLite database.
- 112 headless tests pass.

## Dungeon damage, revive, daily coins, unequip — saita machine, 2026-11-16 (static + headless; live retest pending)

Player report: very low damage to the first-dungeon boss; revive, daily rebirth coins and unequip did not work.
Evidence is the wire log of the 20:24-20:38 session plus static reconstruction. None of the fixes has been retested live yet.

1. Low damage: Item base +0x07 is f32 `Durability` (field names from the Lua item builder `0x006741F0`:
   +0 Amount, +2 UpgStep, +4 Quality, +6 RCHold, +7 Durability). The emulator sent 0.0 for every item. `0x00A49920`
   marks an item broken when prop +0xBE (max durability) > 0 and durability <= 0, and `0x009D89B0` skips broken
   items when it sums equipment stats, so the weapon and armour gave no stats. The live `2143` durability report listed 0 for all 8 items.
   Items now send the max `Durability` from `item_equip*.lua` (`client_dict.item_max_durability`), or 100.0 when the item is unknown.
   UpgStep/Quality still send the constructor's 0xFFFF; their effect on stats is not checked.
   Player +0x110..+0x118 (five u16, from details +0xBA..+0xC2) are bonus stat points added to the charstat base (`JUnit_Stat` vf38 `0x00845070`, 2110 handler `0x007743A0`). They are still sent as 0, which is correct for a new character.
2. Revive: 5094 (`0x0078F090`, checked in the assembly) reads, after the u32 result, `i64 char_uid, i64 other, bool bDie, u32, u32, u32, u16`,
   plus `u16 coins` only when bDie == 0 and char_uid == own UID. When bDie is set and the UID is the player's own, the handler opens page 0x6B (`0x008FC100(1)`).
   The old ack put an attacker UID first, so the client never matched its own UID. The request (`0x0078EDF0`) is
   `u64 uid, bool, 3 x u32` with no prefix; live uid = 0, because details +0x1C is 0. The ack now echoes that UID.
   A revive (bDie = 0) spends a stored coin. Which request the revive button sends has not been observed yet.
3. Daily coins: 2448 is a claim, not a revive. Its sender refuses locally when player +0x7E (coins received) or +0x7C (coins owned) is >= 3.
   2449 = `u32 result, u16 -> +0x7E, u32` (PC-bang value). The owned coins change only through 2286 (`u32 result, u16 -> +0x7C`), which the
   emulator never sent. Details +0x59/+0x5B (copied by `0x0095A150` to +0x7C/+0x7E) were 0. The emulator now stores `rebirth_coins`
   (default 3) and `daily_rebirth_recv` (reset daily) and sends 2449 + 2286.
4. Unequip: `0x008354D0` returns without storing any item whose container is 2. The inventory bag used id 2, so items dragged
   into it were dropped by the client. Live: uid 7 was unequipped to bag 2 slot 0, and the client then picked slot 0 again for uid 4;
   the server swapped them back into the equipment. The bag is now id 3 (no migration; the data was reset).

Open: confirm all four live; find the revive-button request; check whether `2143` values are f32 before persisting durability.

## 1v1 Town Duels, Arena Matchmaking, Multi-Client World Presence & SQLite Backend — 2026-11-16 ~22:45

* **1v1 PvP Town Duels & Arena Matchmaking (Opcodes 5097 - 5113, 2304 - 2309, 5138, 5269 - 5275, 2550 - 2553)**:
  - Reverse engineered binary packet schemas from client dispatchers in `research/schemas.txt`:
    - `0x006C0A10`: `DuelRequestAck` (5101) - challenge request with opponent info.
    - `0x006CBE60` / `0x006CCDF0`: `DuelStartAck` (5098) & `DuelStartNot` (5099) - begins duel session with 36-byte state struct.
    - `0x006CC6B0`: `DuelResultAck` (5106) - confirms victory/defeat banner.
    - `0x006B4120`: `DuelRefuseAck` (5113) - notifies challenger of decline.
    - `0x004B67F0` / `0x004B96D0` / `0x004B4680`: `ArenaSquareListAck` (2305), `ArenaGetRoomListAck` (2307), `ArenaGetInviteListAck` (2309).
    - `0x0049BEF0` / `0x0049C4B0` / `0x00490100`: `ArenaTeamCreateAck` (5270), `ArenaTeamJoinAck` (5272), `ArenaTeamLeaveAck` (5275).
    - `0x00499DC0` / `0x00492A10`: `LeagueSeasonArenaGetRankAck` (2551), `LeagueSeasonArenaGetMyRankAck` (2553).
  - Implemented `ArenaHandlers` in `src/darkblood/games/handlers/arena.py` with 12 semantic handler methods and opcode aliases.
  - Added wire dataclasses in `src/darkblood/games/network/messages/arena.py`.
  - Verified with comprehensive lifecycle scenario in `tests/test_arena_flow.py`.
* **Multi-Client World Presence & Mutual Spawns (`GameWorldManager` & Opcode 5096 `UpdateCharInfoNot`)**:
  - Implemented singleton `GameWorldManager` in `src/darkblood/games/world.py`:
    - Tracks active players across town square channels and instanced sub-districts.
    - Automated mutual player spawning via Opcode 5096 (`eERC_UPDATE_CHAR_INFO_NOT` / struct `0x00A52630` `FUN_00a52630`).
    - Broadcaster delivers visual models of existing town inhabitants to newcomers and announces newcomer 3D appearances to existing occupants.
    - Automatic cleanup on disconnect via `Session.run` finally block and `GameSession.on_disconnect`.
  - Verified with dual-client live interaction in `tests/test_world_flow.py`.
* **SQLite Primary Backend Integration (`data/darkblood.db`)**:
  - Switched `GameSession.store()` runtime character store from JSON to `SqliteCharacterStore`.
  - Added in-memory character caching with atomic `save()` synchronization.
  - Added automated migration on first run if database is empty and `characters.json` exists.
  - Linked `tools/dashboard.py` directly to `SqliteCharacterStore`.
* **Test Suite Verification**:
  - **114/114 tests passing cleanly** across all unit and headless flow test suites in ~1.71s.

* **Modular Domain Package Architecture (`src/darkblood/games/network/messages/`)**:
  - Deconstructed monolithic `messages.py` (110 KB, 247 dataclasses) into clean symmetric domain modules:
    - `lobby.py`: Server list, square channels, character select, delete, relay address, back to square.
    - `inventory.py`: Bag management, equip, use, drop, repair, upgrade, enchant, zam sockets, spirit weapon, stack splitting, expiration.
    - `skills.py`: Skill learning, quickslots, lock status, speech bubbles, skill book consumption, AP gain.
    - `commerce.py`: NPC merchants (buy, sell, repurchase), player-to-player trade, personal storage depot currency save/load.
    - `quests.py`: Quest start, progress, rewards, tutorial quests, abandon, fail, beginner guide.
    - `dungeon.py`: Party room creation, dungeon selection, map codes, layer changes, combat lifecycle, rebirth coins, loot drops.
    - `social.py`: Friend list, chat channels, party invitations, team change, mailbox (send, read, claim, return, delete), inspection.
    - `guild.py`: Guild creation, invite, join, leave, banking in/out, level up, notices, grade delegation, guild skills.
    - `events.py`: Mentoring / teaching, gold goblin attack/dead/disappear, citadel reward, treasure hunt, roulette, pet taming.
    - `system.py`: HTTP notices, play options, custom keybindings, name changing, stat verification, second password PIN, titles, achievements.
  - Re-exported all dataclasses in `messages/__init__.py` providing 100% backward compatibility for all existing code.
* **Standalone GM & Server Web Dashboard (`tools/dashboard.py`)**:
  - Zero-dependency web tool running on `http://127.0.0.1:9494`.
  - Real-time live TCP socket probes for Game Server (9400) and Relay Server (9401) with response latency measurements.
  - Interactive Character Explorer: lists accounts, character levels, classes, items, and quests. Allows GM level editing, tutorial reset, and deletion.
  - Searchable Opcode Browser: index of all 1,400+ opcodes with hex representation, domain prefix filtering, and implementation status.
* **Semantic Handler Architecture**:
  - Replaced raw opcode method names with descriptive semantic functions (`handle_buy_item`, `handle_select_character`, `handle_clear_tutorial`, etc.).
  - Added backward-compatible `on_<opcode>` aliases and rich reverse-engineering docstrings with client handler addresses and packet layout.
* **Granular Unit Tests**:
  - Expanded and unbundled multi-opcode tests in `tests/test_wire_messages.py` into dedicated individual unit tests.
  - **105/105 tests passing cleanly** across all test suites in ~1.36s.

## Guild Banking, Level Up, Item Splitting & Storage Depot — 2026-11-16 ~21:30

* **Guild Banking, Grade & Level-Up System (Opcodes 2157 - 2158, 2164 - 2165, 2179 - 2186, 2205)**:
  - Reverse engineered `0x00752FF0` (`GuildInfoNot`), `0x0077ABA0` (`GuildPersonListNot`), `0x00794250` (`GuildMoneyInAck`), `0x00794470` (`GuildMoneyOutAck`), `0x00753170` (`GuildPersonGradeModifyAck`), `0x00753380` (`GuildLevelUpAck`), `0x0075A120` (`GuildNoticeModifyAck`), and `0x00779390` (`GuildSkillNot`).
  - Wire serialization: `GuildMoneyInReq/Ack` (i64 amount -> u32 result, i64 remain_gold), `GuildMoneyOutReq/Ack`, `GuildPersonGradeModifyReq/Ack` (i64 member_uid, i16 new_grade), `GuildLevelUpReq/Ack` (i16 new_level), `GuildNoticeModifyReq/Ack` (wstring notice), and `GuildSkillNot` (bool flag, Tag 0x10 skills vector).
  - Wired domain handlers `on_2179`, `on_2181`, `on_2164`, `on_2183`, `on_2185` in `social.py`.
  - Verified in `tests/test_social_flow.py` and `tests/test_wire_messages.py`.
* **Personal Storage Depot & Mail Return (Opcodes 2227 - 2231, 2234 - 2235)**:
  - Reverse engineered `0x00795220` (`DepotSaveArAck`), `0x00795490` (`DepotLoadArAck`), `0x007965B0` (`PostNewArrivalNot`), and `0x00771470` (`PostReturnAck`).
  - Wire serialization: `DepotSaveArReq/Ack` (i64 gold -> u32 result, Tag 0x17 map, i64 new_storage_gold), `DepotLoadArReq/Ack`, `PostNewArrivalNot` (empty notification), and `PostReturnReq/Ack` (i64 mail_id -> u32 result, Tag 0x10 vector).
  - Wired domain handlers `on_2228`, `on_2230` in `commerce.py` and `on_2234` in `social.py`.
  - Verified in `tests/test_inventory_flow.py`, `tests/test_social_flow.py`, and `tests/test_wire_messages.py`.
* **Item Stack Splitting, Skill Books & Inventory Refresh (Opcodes 2092, 2111 - 2112, 2250 - 2251, 2321 - 2322)**:
  - Reverse engineered `0x0077F570` (`DivideItemAck`), `0x0078BCD0` (`UseLearnSkillItemAck`), `0x0077F070` (`InventoryUpdatedNot`), `0x0077AED0` (`ItemRemainTimeNot`), and `0x00774DD0` (`ItemDeleteNot`).
  - Wire serialization: `DivideItemReq/Ack` (i64 source_uid, i64 dest_uid, i32 count, i16 slot -> u32 result, Tag 0x10 items), `UseLearnSkillItemReq/Ack` (i64 item_uid, i16 skill_id -> u32 result, i16 skill_id, u8 level, i32 item_code, i32 count, Tag 0x10 items, i32 sp), and `InventoryUpdatedNot` (Tag 0x10 deleted + Tag 0x10 added).
  - Wired domain handlers `on_2250` and `on_2111` in `commerce.py`.
  - Verified in `tests/test_inventory_flow.py` and `tests/test_wire_messages.py`.
* **Combat AP, Dungeon Penalty & Random Box (Opcodes 2085, 2109, 2196)**:
  - Reverse engineered `0x0078FA70` (`ChangeDungeonPenaltyNot`), `0x00790480` (`InsertApNot`), and `0x0075A2E0` (`RandomboxResultItemNot`).
  - Wire serialization: `InsertApNot` (i32 current_ap, i32 total_ap), `ChangeDungeonPenaltyNot` (bool in_dungeon, bool is_penalty, i16 level, i32 id, i32 duration), and `RandomboxResultItemNot` (u32 result, i32 item_code, i16 count, bool is_jackpot).
  - Verified in `tests/test_wire_messages.py`.
* **72/72 unit and flow tests passing cleanly** across all test modules in ~1.33s.


## Titles, Achievements, Avatar Zam Socketing, Security & Inspection — 2026-11-16 ~21:15

* **Titles & Achievements System (Opcodes 2327 - 2336)**:
  - Reverse engineered `0x007751C0` (`TitleChangeAck`), `0x0079D650` (`AchieveGetListAck`), `0x0076C720` (`AchieveChangeNot`), and `0x0079D240` (`AchieveCompleteNot`).
  - Wire serialization: `TitleChangeReq/Ack` (i32 title_id -> i32 result, i32 title_id), `AchieveGetListReq/Ack` (Tag 0x1E + Tag 0x17 + Tag 0x17 + Tag 0x0A + Tag 0x10), `AchieveChangeNot` (3x Tag 0x17 maps), and `AchieveCompleteNot` (2x Tag 0x10 vectors).
  - Wired domain handlers `on_2335` and `on_2327` in `social.py`.
  - Verified in `tests/test_social_flow.py` and `tests/test_wire_messages.py`.
* **Avatar Gem / Zam Socketing System (Opcodes 2362 - 2365)**:
  - Reverse engineered `0x00782D00` (`AvatarZamInsertAck`) and `0x00782F40` (`AvatarZamEraseAck`).
  - Wire serialization: `AvatarZamInsertReq/Ack` (i64 avatar_uid, i64 zam_uid -> i32 result, Tag 0x10 items) and `AvatarZamEraseReq/Ack` (i64 avatar_uid -> i32 result, Tag 0x10 items).
  - Wired domain handlers `on_2362` and `on_2364` in `commerce.py`.
  - Verified in `tests/test_inventory_flow.py` and `tests/test_wire_messages.py`.
* **Class Promotion, Skill Reset & Rebirth Coins (Opcodes 2280, 2283, 2286)**:
  - Reverse engineered `0x00797740` (`InitSkillNot`), `0x00797F00` (`PromotionNot`), and `0x007983B0` (`RebirthCoinChangeNot`).
  - Wire serialization: `InitSkillNot` (u32 result, i32 sp, Tag 0x17 skills map), `PromotionNot` (u32 result, u8 new_class, i32 sp, Tag 0x17 skills map), and `RebirthCoinChangeNot` (u32 result, i16 coins).
  - Verified in `tests/test_wire_messages.py`.
* **Arena SP Item & Arena Return (Opcodes 2709 - 2710, 5165 - 5166)**:
  - Reverse engineered `0x007A7CA0` (`UseArenaSpItemAck`) and `0x00758550` (`ArenaBackToSquareAck`).
  - Wire serialization: `UseArenaSpItemReq/Ack` (i64 item_uid -> u32 result, Tag 0x10 items, i32 arena_sp) and `ArenaBackToSquareReq/Ack`.
  - Wired domain handler `on_2709` in `commerce.py` and `on_5165` in `social.py`.
  - Verified in `tests/test_inventory_flow.py` and `tests/test_social_flow.py`.
* **Second Password / Security PIN (Opcodes 5256 - 5261)**:
  - Reverse engineered `0x0075B020` (`SecondPassCreateAck`), `0x0075B050` (`SecondPassModifyAck`), and `0x0075B080` (`SecondPassAuthAck`).
  - Wire serialization: `SecondPassCreateReq/Ack`, `SecondPassModifyReq/Ack`, `SecondPassAuthReq/Ack`.
  - Wired domain handlers `on_5256`, `on_5258`, and `on_5260` in `social.py`.
  - Verified in `tests/test_social_flow.py` and `tests/test_wire_messages.py`.
* **Remote Player & Item Inspection (Opcodes 6011 - 6012, 6028 - 6029)**:
  - Reverse engineered `0x00790FA0` (`RequestCharInfoAck`) and `0x00766C20` (`RequestItemInfoAck`).
  - Wire serialization: `RequestCharInfoReq/Ack` (i64 char_uid -> u32 result, bool flag, Tag 0x1E summary, 2x Tag 0x10 item vectors) and `RequestItemInfoReq/Ack` (i64 item_uid -> u32 result, i64 item_uid, Tag 0x1E item struct).
  - Wired domain handlers `on_6011` and `on_6028` in `social.py`.
  - Verified in `tests/test_social_flow.py` and `tests/test_wire_messages.py`.
* **69/69 unit and flow tests passing cleanly** across all test modules in ~1.40s.


## Mentoring, Teaching & Gold Goblin Encounter Events — 2026-11-16 ~21:00

* **Mentoring & Teaching System (Opcodes 5351 - 5357)**:
  - Reverse engineered `0x0075C200` (`RequestTeachingAck`), `0x0075C430` (`AcceptRequestTeachingAck`), and `0x007A5890` (`TeachingGetInfoNot`).
  - Wire serialization: `RequestTeachingReq/Ack` (i64 target_uid, wstring target_name), `AcceptRequestTeachingReq/Ack` (bool accepted, i64 mentor_uid, wstring mentor_name), and `TeachingGetInfoNot` (Tag 0x1E struct).
  - Wired domain handlers `on_5351` and `on_5353` in `social.py`.
  - Verified in `tests/test_social_flow.py` and `tests/test_wire_messages.py`.
* **Gold Goblin Encounter Events (Opcodes 5362 - 5367)**:
  - Reverse engineered `0x007A6D10` (`GoldGoblinAppearNot`), `0x00784A10` (`GoldGoblinAttackAck`), and `0x00784CA0` (`GoldGoblinDeadAck`).
  - Wire serialization: `GoldGoblinAppearNot` (i32 goblin_id, tag 0x10 items), `GoldGoblinAttackReq/Ack`, `GoldGoblinDeadReq/Ack`, and `GoldGoblinDisappearNot`.
  - Wired domain handlers `on_5363` (attack goblin) and `on_5365` (kill goblin and reward items) in `dungeon.py`.
  - Verified in `tests/test_dungeon_flow.py` and `tests/test_wire_messages.py`.
* **Citadel & Treasure Notifications (Opcodes 5344 - 5346)**:
  - Reverse engineered `0x007722F0` (`TreasureStartNot`), `0x0075BC00` (`TreasureEndNot`), and `0x007833F0` (`CitadelRewardNot`).
  - Wire serialization: `TreasureStartNot`, `TreasureEndNot`, and `CitadelRewardNot` (Tag 0x17 map + Tag 0x10 items vector).
  - Verified in `tests/test_wire_messages.py`.
* **64/64 unit and flow tests passing cleanly** across all test modules in ~1.48s.

## Character & Guild Renaming, Custom Keybindings & Spirit Weapons — 2026-11-16 ~20:45

* **Character & Guild Renaming (Opcodes 2310 - 2315)**:
  - Reverse engineered `0x00780200` (`CharNickChangeAck`) and `0x00780590` (`GuildNameChangeAck`).
  - Wire serialization: `CharNickChangeReq/Ack` (wstring new_name, i64 item_uid -> i32 result, tag 0x10 items, wstring new_name) and `GuildNameChangeReq/Ack`.
  - Wired domain handlers `on_2310` (character nickname change with character store persistence) and `on_2314` (guild name change) in `social.py`.
  - Verified in `tests/test_social_flow.py` and `tests/test_wire_messages.py`.
* **Custom Keymapping & Keybindings (Opcodes 2319 - 2320)**:
  - Reverse engineered `0x00753960` (`KeyboardSetCustomKeyAck`).
  - Wire serialization: `KeyboardSetCustomKeyReq/Ack` (arbitrary raw keyboard mapping blob).
  - Wired domain handler `on_2319` in `social.py` persisting custom key bindings on character record.
  - Verified in `tests/test_social_flow.py` and `tests/test_wire_messages.py`.
* **Spirit Weapon System (Opcodes 2338 - 2339)**:
  - Reverse engineered `0x00780860` (`ItemSpiritChangeAck`).
  - Wire serialization: `ItemSpiritChangeReq/Ack` (i64 item_uid, i64 spirit_item_uid -> i32 result, i64 spirit_uid, tag 0x10 items).
  - Wired domain handler `on_2338` in `commerce.py`.
  - Verified in `tests/test_inventory_flow.py` and `tests/test_wire_messages.py`.
* **62/62 unit and flow tests passing cleanly** across all test modules in ~1.94s.

## SQLite Storage Backend, Item Enchanting, Upgrades & Loot Pickup — 2026-11-16 ~20:30

* **SQLite Character Store & JSON Migration (Milestone P9)**:
  - Designed `ICharacterStore` interface and implemented `SqliteCharacterStore` in `src/darkblood/player_management/store.py` backed by `data/darkblood.db`.
  - Supports atomic transactions, relational indexes on `name` (case-insensitive) and `account`, and full character JSON blob storage.
  - Implemented bidirectional migration utilities `import_from_json(json_path)` and `export_to_json(json_path)`.
  - Verified in `tests/test_character_store.py`: CRUD operations, case-insensitive duplicate name rejection, and bidirectional JSON <-> SQLite migration.
* **Magic Enchanting & Item Upgrades (Opcodes 2254 - 2259, 2284 - 2285, 2672 - 2673)**:
  - Reverse engineered `0x00796DC0` (`MagicEnchantEnchantAck`), `0x00797120` (`MagicEnchantEraseOptionAck`), `0x0077FC60` (`MagicEnchantExpendSlotAck`), `0x0077FED0` (`RandomItemUpgradeAck`), and `0x00783C40` (`FixItemUpgradeAck`).
  - Implemented wire serialization and domain handlers `on_2254`, `on_2256`, `on_2258`, `on_2284`, and `on_2672` in `commerce.py`.
  - Verified in `tests/test_inventory_flow.py` and `tests/test_wire_messages.py`.
* **Item Drop, Pickup & Real-Time Presence (Opcodes 5065 - 5068, 5114, 5118 - 5119, 5096)**:
  - Reverse engineered `0x0078AD80` (`PickUpItemResultAck`), `0x00792700` (`GetDropArNot`), `0x0077A8A0` (`FriendMyConnectionNot`), `0x00758FA0` (`FriendMyDisconnectionNot`), and `0x0078C990` (`UpdateCharInfoNot`).
  - Implemented wire serialization and domain handlers `on_5065` (Pick up item) emitting 5066 and 5068 in `dungeon.py`.
  - Verified in `tests/test_dungeon_flow.py` and `tests/test_wire_messages.py`.
* **61/61 unit and flow tests passing cleanly** across all test modules in ~1.38s.

## Mailbox, P2P Trade, Party Invites, GM Console Commands & Quest State — 2026-11-16 ~20:10

* **Mailbox System (Opcodes 2221 - 2237)**:
  - Reverse engineered `0x00795D70` (`PostSendReq`), `0x00795F40` (`PostSendAck`), `0x007963C0` (`PostReadReq`), `0x0075A660` (`PostReadAck`), `0x0079664C` (`PostGetAppendItemReq`), `0x0077F8E0` (`PostGetAppendItemAck`), `0x007964EC` (`PostDeleteReq`), and `0x007715F0` (`PostDeleteAck`).
  - Implemented wire serialization and domain handlers `on_2221`, `on_2223`, `on_2225`, and `on_2236` in `social.py`.
  - Added support for reading mail, claiming attached items and gold, and batch deleting letters.
* **P2P Direct Trade Lifecycle (Opcodes 5069 - 5084)**:
  - Reverse engineered `0x00770E50` (`RequestTradeAck`), `0x007587B0` (`AcceptRequestTradeAck`), `0x0077DE00` (`CancelTradeAck`), `0x0077D980` (`InsertTradeItemAck`), `0x0077DBB0` (`DeleteTradeItemAck`), `0x00758940` (`UpdateTradeArAck`), and `0x0078EB40` (`AcceptTradeAck`).
  - Implemented wire serialization and domain handlers `on_5069`, `on_5071`, `on_5073`, `on_5075`, `on_5077`, `on_5079`, `on_5081`, and `on_5083` in `commerce.py`.
  - Supports trading invitations, gold staging, item staging/unstaging, mutual trade acceptance, and trade cancellations.
* **Party & Team Management (Opcodes 5049 - 5055, 5015 - 5016)**:
  - Reverse engineered `0x00758700` (`PartyInviteAck`), party acceptance (`PartyAcceptInviteAck`), and team changes (`ChangeTeamAck`).
  - Implemented wire serialization and domain handlers `on_5049`, `on_5054`, and `on_5015` in `dungeon.py`.
* **Chat & In-Game GM Console Commands (Opcodes 5040 - 5041)**:
  - Reverse engineered `0x007AC5E0` (`ChatReq`) and `0x007AC890` (`ChatAck`) using Tag `0x1E` message struct.
  - Implemented wire serialization and domain handler `on_5040` in `social.py` supporting regular chat broadcasting and in-game GM commands:
    - `/gold <amount>`: Instantly adds gold to character balance and syncs character state.
    - `/levelup [n]`: Levels up character by `n` levels, grants 3 SP per level, calculates HP/MP, emits `5087 eERC_LEVEL_UP_NOT`, and replies in chat.
    - `/sp <amount>`: Grants bonus skill points for testing skill trees.
    - `/item <item_code> [count]`: Grants items directly into character bags via `add_reward_items`.
* **Quest Giveup & Fail Handling (Opcodes 2078 - 2081)**:
  - Reverse engineered `0x006223B0` (`QuestGiveupAck` / `QuestFailAck`).
  - Implemented wire serialization and domain handlers `on_2078` and `on_2080` in `quests.py`, removing active quests from character storage and sending confirmation ACKs.
* **54/54 unit and flow tests passing cleanly** across all 11 test modules.


## Level-Up Progression, Store Economy & Guild Banking — 2026-11-16 ~19:50

* **Level-Up & SP Progression on EXP Overflow**:
  - Implemented `char_level_stats()` and `char_level_stat(char_class, level)` in `src/darkblood/games/game_data/client_dict.py`, parsing `UPExp`, `HealthPoint`, and `ManaPoint` from `Data/Dict/charstat.lua` across all 7 character classes (`Warrior`, `Knight`, `Hunter`, `Mage`, `Thief`, `Fighter`, `WHunter`) with fallback geometric scaling.
  - Wired level-up evaluation loop into quest reward completion (`on_2076` in `quests.py`). When EXP overflows `UPExp`, increments character level, grants 3 SP per level, updates max HP and MP, emits `5087 eERC_LEVEL_UP_NOT` and `5086 eERC_CHANGE_EXP_NOT`, and persists character state.
  - Verified progression in `tests/test_quest_flow.py` (character levels from 1 -> 2, accumulates 3 SP, and carries remaining EXP).
* **Store Economy Transactions & Inventory Persistence**:
  - Reverse engineered `0x0077E2F0` (`On_eEGS_BUY_ITEM_ACK`), `0x0077E8E0` (`On_eEGS_SELL_ITEM_ACK`), and `0x0077EC30` (`On_eEGS_REPURCHASE_ITEM_ACK`).
  - Implemented wire encoding for `BuyItemAck` (tag 0x1E store record, i32, i64 player gold, tag 0x10 item vector, i32, i16, i64, i32), `SellItemAck` (tag 0x10 item vector, i64 player gold, tag 0x1E repurchase item struct, tag 0x13 map), and `RepurchaseItemAck` (tag 0x10 item vector, i64 player gold).
  - Wired `on_2067` (Buy Item): matches `item_id` hash against store item catalog, deducts gold, generates and adds item to player inventory via `add_reward_items`, and persists balance.
  - Wired `on_2069` (Sell Item): decrements/removes sold item from player bags, awards gold, and saves character state.
  - Wired `on_2071` (Repurchase Item): returns player gold balance.
* **Guild Economy, Progression & Skill Reset Opcodes**:
  - `2179 eEGS_GUILD_MONEY_IN_REQ` & `2180 eEGS_GUILD_MONEY_IN_ACK` (`0x00794250`): `<q` (deposit amount) -> `<iq` (result=0, remaining gold), updating player gold and guild bank.
  - `2181 eEGS_GUILD_MONEY_OUT_REQ` & `2182 eEGS_GUILD_MONEY_OUT_ACK` (`0x00794470`): `<q` (withdraw amount) -> `<iq` (result=0, remaining gold), updating player gold and guild bank.
  - `2183 eEGS_GUILD_LEVEL_UP_REQ` & `2184 eEGS_GUILD_LEVEL_UP_ACK` (`0x00753380`): empty -> `<ih` (result=0, new_level), incrementing guild level.
  - `2185 eEGS_GUILD_NOTICE_MODIFY_REQ` & `2186 eEGS_GUILD_NOTICE_MODIFY_ACK` (`0x0075A120`): wide string notice -> `<i` (result=0).
  - `2188 eEGS_GUILD_NOTICE_DELETE_REQ` & `2189 eEGS_GUILD_NOTICE_DELETE_ACK` (`0x0074B830`): empty -> `<i` (result=0).
  - `2214 eEGS_GUILD_ALL_SKILL_INIT_REQ` & `2215 eEGS_GUILD_ALL_SKILL_INIT_ACK` (`0x00752D80`): empty -> `<ii` (result=0, param=0).
* 48/48 unit and flow tests pass cleanly across all 11 test modules.

## Milestone P1: Reproducible Transport & Serialization Hardening — 2026-11-16 ~19:30

* Transport & Serialization Test Suite (`tests/test_transport.py`, 11 comprehensive tests):
  - ProudNet signed scalar boundaries across widths 1, 2, 4, 8 bytes and overflow checks beyond 64-bit signed ranges.
  - Verification of invalid scalar width handling (e.g. widths 0, 3, 5, 255) raising `ProtocolError`.
  - Regression fixture for the exact observed first client frame `13 57 01 05 30 0F 00 00 40` (type 0x30, parameter `0x4000000F`).
  - Fragmented TCP frames (streaming 1 byte at a time through `pop_frame`) and coalesced TCP frames (multiple ProudNet frames in a single chunk).
  - JSerBuffer inverted terminal bit varuints (bit 7 set: 0 -> `\x80`, 128 -> `\x00\x81`), truncation bounds, and length limit enforcement.
  - Implemented `JSerBufferReader` class in `darkblood.core.serialization.jser` supporting bounds-checked reads for all primitive types, UTF-16LE wide strings, UTF-8 strings, and dynamic vector parsing.
  - Hardened `parse_event` and `event` for zlib compression with 4-byte uncompressed size prefix matching client behavior.
* Updated `ROADMAP.md` milestone progress across P0, P1, P2, P3, P4, and P5.
* 47/47 unit and flow tests pass cleanly across all 11 test modules.

## Guilds, Megaphone, Repairs, Upgrades, Bag Renaming, Contracts & Memos — 2026-11-16 ~19:15

* Decompiled and implemented wire schemas, domain handlers, and tests for 13 additional opcodes:
  - `2032 eEGS_CHANGE_BAG_NAME_REQ` & `2033 eEGS_CHANGE_BAG_NAME_ACK`: `<q` (bag_uid) + wide string -> `<iq` + wide string, persisting custom bag tab labels on character. Handled in `on_2032`.
  - `2117 eEGS_UPDATE_SKILL_LOCKED_REQ` & `2118 eEGS_UPDATE_SKILL_LOCKED_ACK`: `<h?` (sKindNameIndex, bLocked) -> `<ih?` (result, sKindNameIndex, bLocked), persisting locked skill set on character. Handled in `on_2117`.
  - `2145 eEGS_DURABILITY_REPAIR_REQ` & `2146 eEGS_DURABILITY_REPAIR_ACK`: tag 0x17 map -> `<i` (result=0) + `b'\x17\x80'` (empty tag 0x17 map) + `<q` (remain_gold), updating player gold and completing gear durability repairs. Handled in `on_2145`.
  - `2115 eEGS_ITEM_UPGRADE_REQ` & `2116 eEGS_ITEM_UPGRADE_ACK`: `<qqq` (target_item_uid, catalyst_uid, protect_uid) -> `<i` (result=1 rejection until upgrade recipes are wired). Handled in `on_2115`.
  - `2086 eEGS_BUY_LIFE_WATER_REQ` & `2087 eEGS_BUY_LIFE_WATER_ACK`: `<?` (flag) -> `<i?q` (result, flag, remain_currency). Handled in `on_2086`.
  - `2128 eEGS_USE_SPEAKER_ITEM_REQ` & `2129 eEGS_USE_SPEAKER_ITEM_ACK`: `<q` (speaker_uid) + wide string (megaphone message) + `<q` (target_uid) -> `<iq` + `b'\x10\x80'` (empty updated item vector). Handled in `on_2128`.
  - `5121 eERC_GUILD_CREATE_PROPOSAL_REQ` & `5122 eERC_GUILD_CREATE_PROPOSAL_ACK`: wide string (guild_name) -> `<i` (result=0). Handled in `on_5121`.
  - `2150 eEGS_GUILD_CREATE_REQ` & `2151 eEGS_GUILD_CREATE_ACK`: wide string (guild_name) -> `<iq` (result=0, guild_uid) + wide string (guild_name) + `<q` (remain_gold). Handled in `on_2150`.
  - `2121 eEGS_CONTRACT_UPDATE_REQ` & `2122 eEGS_CONTRACT_UPDATE_ACK`: `<i` (contract_id) -> `<ii` (result, contract_id). Handled in `on_2121`.
  - `2143 eEGS_DURABILITY_CHANGE_REQ` & `2144 eEGS_DURABILITY_CHANGE_ACK`: tag 0x17 map -> `<i` + `b'\x10\x80'` (empty item vector). Handled in `on_2143`.
  - `2133 eEGS_FRIEND_LIST_UPDATE_REQ` & `2134 eEGS_FRIEND_LIST_UPDATE_ACK`: `<q` (friend_uid) + wide string (memo) -> `<iq` + wide string (memo). Handled in `on_2133`.
  - `2155 eEGS_GUILD_PERSON_JOIN_REQ` & `2156 eEGS_GUILD_PERSON_JOIN_ACK`: `<q` (guild_uid) -> `<i` (result=0). Handled in `on_2155`.
  - `2160 eEGS_GUILD_INVITE_REQ` & `2161 eEGS_GUILD_INVITE_ACK`: wide string (char_name) -> `<i` (result=0). Handled in `on_2160`.
  - `2162 eEGS_GUILD_PERSON_LEAVE_REQ` & `2163 eEGS_GUILD_PERSON_LEAVE_ACK`: empty -> `<i` (result=0). Handled in `on_2162`.
* 36/36 headless tests pass cleanly across all categories.

## Diagnostic Export Tooling & GitHub Issue Templates — 2026-11-16 ~18:50

* Added GitHub Issue Templates under `.github/ISSUE_TEMPLATE/`:
  - `bug_report.yml`: GitHub Issue form for player bug reports, gameplay areas, unhandled opcodes, executable hashes, and diagnostic bundles.
  - `opcode_investigation.yml`: Reverse engineering form for opcode number/name, handler address, hex payload, decompiled C snippet, and diagnostic bundle.
  - `config.yml`: Helpful links to local documentation.
* Implemented `tools/export_diagnostics.py`:
  - Automatically gathers OS info, Git commit hash, client executable SHA-256 (`DarkBlood.exe`), recent entries from `wire.jsonl`, `data/characters.json`, `research/client/handler_map.txt`, and `assets/opcodes.tsv`.
  - Packages diagnostics into a zip file `darkblood_diagnostics_<timestamp>.zip` for easy issue submission.
* Decompiled and implemented wire schemas, domain handlers, and tests for 8 additional opcodes:
  - `2048 eEGS_CHANGE_BAG_PROPERTY_REQ` & `2049 eEGS_CHANGE_BAG_PROPERTY_ACK`: `<qB` (nBagUID, ucProperty) -> `<iqB` (result, nBagUID, ucProperty) updating tab filter `b28` on bag. Handled in `on_2048`.
  - `2053 eEGS_MODIFY_SKILL_SPEECH_REQ` & `2054 eEGS_MODIFY_SKILL_SPEECH_ACK`: `<H` (sKindNameIndex) + wide string -> `<iH` + wide string, persisting custom skill shout text on character. Handled in `on_2053`.
  - `2055 eEGS_DELETE_SKILL_SPEECH_REQ` & `2056 eEGS_DELETE_SKILL_SPEECH_ACK`: `<H` (sKindNameIndex) -> `<iH` (result, sKindNameIndex) removing shout text. Handled in `on_2055`.
  - `2067 eEGS_BUY_ITEM_REQ` & `2068 eEGS_BUY_ITEM_ACK`: `<iiH` (store_id, item_id, count) -> `<i` (result=1 rejection until store inventory is populated). Handled in `on_2067`.
  - `2069 eEGS_SELL_ITEM_REQ` & `2070 eEGS_SELL_ITEM_ACK`: `<iqi` (npc_id, item_uid, count) -> `<i` (result=1 rejection). Handled in `on_2069`.
  - `2071 eEGS_REPURCHASE_ITEM_REQ` & `2072 eEGS_REPURCHASE_ITEM_ACK`: `<q` (item_uid) -> `<i` (result=1 rejection). Handled in `on_2071`.
  - `2139 eEGS_FRIEND_LIST_ADD_REQ` & `2140 eEGS_FRIEND_LIST_ADD_ACK`: wide string -> `<i` (0xCE player offline / not found). Handled in `on_2139`.
  - `2135 eEGS_FRIEND_LIST_DELETE_REQ` & `2136 eEGS_FRIEND_LIST_DELETE_ACK`: `<q` (char_uid) -> `<iq` (result=0, char_uid). Handled in `on_2135`.
* 35/35 headless tests pass cleanly across all categories.

## Modular Test Suite Refactoring — 2026-11-16 ~18:30

* Refactored monolithic `test_headless_flow.py` into 10 granular, modular test modules:
  - `test_character_store.py`: CharacterStore creation, duplicate check, deletion, inventory.
  - `test_wire_messages.py`: Unit encoding/decoding for all opcode dataclasses.
  - `test_hashing.py`: JHash algorithm verification against client DJB2.
  - `test_lobby_flow.py`: Lobby handshake, server/channel/character listing, creation/deletion/selection.
  - `test_inventory_flow.py`: Drag, use, discard, bags, quickslots, skill learning.
  - `test_dungeon_flow.py`: Gates, layers, monster combat, death/revival, cards, town return.
  - `test_quest_flow.py`: Quest acceptance, completion, client dict rewards, tracking restore.
  - `test_social_flow.py`: Mailbox, friends, invite lists, web notices, NPC dialogue.
  - `test_relay_flow.py`: Relay server isolation.
  - `test_jpk.py`: JPK archive and crypto.
* 31/31 tests pass cleanly across all categories.

## Skills, Character deletion, Item management, Bag & Quickslots — 2026-11-16 ~18:15

* 2014 eEGS_DELETE_CHARACTER_REQ & 2015 eEGS_DELETE_CHARACTER_ACK: Wire schema i64 char_uid -> i32 result + i64 char_uid + i32 complete_time=0. CharacterStore.delete() persists account character removals.
* 2040 eEGS_DELETE_ITEM_REQ & 2041 eEGS_DELETE_ITEM_ACK: i64 item_uid + i32 amount -> i32 result + i64 item_uid + i32 del_amount. Inventory item deletion and stack decrementing persisted to store.
* 2030 eEGS_SWITCH_BAG_REQ & 2031 eEGS_SWITCH_BAG_ACK: u16 from + u16 to -> i32 result + u16 from + u16 to. Bag reordering persisted.
* 2046 eEGS_SWITCH_QUCIKSLOT_REQ & 2047 eEGS_SWITCH_QUCIKSLOT_ACK: u8 type + u8 from + u8 to -> i32 result + echoes slot payload.
* 2050 eEGS_LEARN_SKILL_REQ & 2051 eEGS_LEARN_SKILL_ACK: u16 sKindNameIndex + u8 ucLevel -> i32 result + u16 index + u8 level + i32 remain_sp + i64 remain_gold. Character skill points and learned levels persisted.
* 2594 eEGS_HTTPNOTICE_CHECK_REQ & 2595 eEGS_HTTPNOTICE_CHECK_ACK: i32 result + bool bWatch=False.
* 2216 eEGS_PLAY_OPTION_UPDATE_REQ: i64 char_uid + tag 0x1E struct recorded and consumed.
* 2024 eEGS_GET_INVITELIST_REQ & 2025 eEGS_GET_INVITELIST_ACK: i32 result + tag 0x10 empty user vector.
* 5087 eERC_LEVEL_UP_NOT & 5086 eERC_CHANGE_EXP_NOT: wire structures mapped from 0x0078CCF0 / 0x0078D170.
* Item entity updated with item count/amount at +0 offset.
* 17/17 headless tests pass.

## Dungeon schemas & Bag cell display resolved — 2026-11-16 ~17:15

* 5095 eERC_CHANGE_DUNGEON_LAYER_NOT: payload decoded as i32 0x7FFFFFFF + i64 layer_net_id = (jhash(map_code) << 32) | layer_id. For Lucid Forest Entrance (Act1_G1_A10), jhash is 0x32ADCD46 and layer is 4 (fffff7f 04000000 46cdad32). Sent by JAppStateGamePlay::Initialize (0x006C0000.c:10234 via 0x0087D1F0 -> 0x007900B0). Handled in on_5095.
* 2422 eEGS_ACTIVE_WARFLAG_REQ: decoded as i32 0x7FFFFFFF + u32 war_flag_id (31). Sent by 0x0087D170 via 0x0079C300. Client registers no 2423 ACK. Handled in on_2422.
* 2358 eEGS_GUIDE_BEGINNER_UPDATE_REQ: guide vector (i32 0x7FFFFFFF + tag 0x10 vector<u32>). Handled in on_2358.
* 5063 eERC_MONSTER_DEAD_REQ & 5064 eERC_DROP_ITEM_NOT: JUserClient::MonsterDeadREQ (0x0078A690) sends u32 monster_id + u32 param. On_eERC_DROP_ITEM_NOT (0x0078A870) maps 26-byte item drop structs (drop_uid, item_id, count, drop_type, 3x float coords, flags).
* Bag cell display: Field semantics recovered from 0x00827D80, 0x005509F0, 0x00551310. Bag id must have high dword < 0x80000000; +0x28 is item category tab (0 accepts all items; 0xFF blocked matching), +0x29 is cell capacity (BagSize = 5 for Ibaga0004; 0 displayed zero cells), +0x2A is UI slot (0). Container 2 added to ensure_inventory.
* 16/16 headless tests pass.

## Dungeon render reproduced — Cristian machine, 2026-11-16 ~13:50

Fresh e410c89 server; 13/13 headless tests pass. Existing Mage `lindic` entered
town directly with tutorial completion persisted. Movement and map transitions
through Elwood Center/Village/Western Forked Road were observed locally.
Room creation, gate selection, map-code change and start-game replies loaded
Lucid Forest Entrance without a logged crash. Initial viewport had no monsters;
automated arrow/X input did not visibly act. Manual control check pending;
local dungeon movement/combat is not yet established. 5095 remains unhandled.
See SESSION_HANDOFF.md for captures and the live session.
## Quests, rewards, equipment — saita machine, 2026-11-16 ~15:00

Live-verified with Thief1:
* Active quests survive relog: 2007 struct 0x00A40760 map at +0x31F
  (reader 0x00A3E450 -> 0x00A209B0) is the same map 2074 fills through
  0x00A60960. Entry: tag 0x0F, u32 quest id, i64 UID, i64 start time, u32
  quest id, bool tracked, u32[<=5] mission counters. The tracker showed
  "Violent Monsters - Berserk Hogs defeated 0/1" after relog.
* Details u62 is EXP (HUD "EXP 13 / 144" = charstat UPExp of level 1) and
  u66 is gold (inventory "Ar: 21 Ar"). 2077 jAck mapped (models.QuestCompleteAck):
  +0x1E new gold total, +0x26 item vector, +0x42 EXP, +0x46 GP. Rewards come
  from DictQuest (RewardExp/Gold/GP, RewardItemG, RewardSelectG + request index).
* Items: struct 0x00A53F50 fully mapped (two 0x00A4B250 arrays precede the
  u16 fields -- missing them broke 2007 parsing). Container 1 = worn; the
  default equipment list renders on the character. 2007 bag vector +0x293
  (0x00A1EC30, 0x2F bytes): i64 id, u32 bag item code, wstr, u8, u8, u16 UI
  slot index (+0x2A), 3 bools. An Ibaga0004 bag appeared in UI slot 0 but its
  cells and a potion stored in it did not; that display path is the next step.

## Dungeon entry live — saita machine, 2026-11-16 ~13:30

Thief1 walked from town (Western Forked Road) into the Gnogue Haram entrance:
2010 → 5001 `_singleplay` → 5043 `Act1_G1` → new 5044 → gate map shown;
clicking Lucid Forest sent 5009 `Act1_G1_A10` → new 5010 → 5013 → 5014.
5014's J-wstring is the map code (empty crashed at `0x00788539`: NULL+0x28 from
`0x0098E630`). With the code echoed, "Lucid Forest Entrance" loaded with hog
monsters, combo counter and movement; no exception in ~1 minute. Next requests:
5095 `eERC_CHANGE_DUNGEON_LAYER_NOT` (`ffffff7f 04000000 46cdad32`) and 2422
`eEGS_ACTIVE_WARFLAG_REQ` (`ffffff7f 1f000000`), both unhandled. Kills, drops,
dungeon clear and return to town are not yet verified. 13/13 headless tests pass.

## Latest resume verification — Cristian, 2026-11-16

Local live test (~11:54–12:00): existing Mage `lindic` selected successfully
and rendered its tutorial. Relay JoinGroupACK and mailbox/friend replies were
exercised; 2353 monster-death notifications arrived and no crash was logged.
Attempted tutorial exit did not emit 2082. Further UI input was stopped because
movement/attacks continued between commands; user-control clarification pending.
Town/skip/dungeon acceptance remains unverified in this local run.

`origin main` was already current at `cbcc82e`; upstream includes room list and
creation responses, store dict loading, quest persistence/history and waypoints.
Rebuilt/deployed the latest shim locally and verified the client executable hash.
All 13 headless tests pass, including the corrected 5014 start-game response.
Static and assembly evidence confirms its empty string has no type tag and its
last container is a mandatory vector. Live dungeon entry remains unverified;
see PROTOCOL.md's dungeon start correction and SESSION_HANDOFF.md.

Updated **November 16, 2026** (second session). Offline gameplay is not available yet; the client now reaches character creation and selection against the local server.

## Tutorial skip and client data (saitatter machine, 2026-11-16, sixth session)

1. **Skip-tutorial loop explained (static).** The 2083 path requests
   `ChangeState(eAS_SquarePlay)`. `JAppStateSquarePlay` can-enter (`0x006FA540`)
   requires player `+0xF0` (`nJoinLayerNetID`, copied from 2007 details `+0x5F`
   by `0x0095A150`) to carry a loaded SquareID hash in its high dword. We sent 0,
   so after 5 s `JAppStateMgr` fell back to the previous state: the tutorial
   restarted. The emulator now sends `jhash("Act1") << 32 | 1` (DJB2 over
   UTF-16LE, `0x00B3AD70`; `Act1` from `maplist.lua` `DictMap:LoadSquare`).
   Details `+0x9C` is confirmed as the flag that picks Tutorial vs SquarePlay
   after selection (`0x006F88C0`). 5046 `BACK_TO_SQUARE_ACK` schema recovered.
   See PROTOCOL.md §7. **Live-verified 06:08:** "Thief1" (tutorial cleared)
   entered SquarePlay. Entering then crashed at `0x0092CF06`:
   `JSteamMgr::FindLeaderboards` (`0x0092CE00`, called at `0x007004E5`) used the
   placeholder `SteamUserStats()` pointer 1. The shim now provides an offline
   ISteamUserStats (v011 slot order); with it the client ran ~2 minutes in town
   without exceptions until closed by the user. Unanswered town requests seen:
   5124 `eERC_GTARGET_LIST_REQ`, 2594 (no name in opcodes.tsv), 2216
   `eEGS_PLAY_OPTION_UPDATE_REQ` (zlib body), 2369
   `eEGS_BILLING_GET_CURRENT_CASH_REQ`, 2712, 2024. 5124 and 2594 are sent
   fire-and-forget from SquarePlay (`0x006F9AB9`, `0x007002BD`).
2. **JPK encryption rule corrected.** Header byte `0x226` marks an encrypted
   archive and the cipher covers every entry blob, not only XML/Lua. Older
   extractions of encrypted archives (e.g. `research/all_extracted`) contain
   still-encrypted textures/effects and 5,209 failed `.j` entries. With the
   corrected reader 36,648 entries extract (6 placeholder failures). `tools/jpk_pack.py` rebuilds
   archives byte-identically and can replace edited entries (client loading of
   an edited archive not yet tested).
3. **Private client-data workspace.** `tools/build_client_data.py` extracts all
   archives into `../darkblood-client-data` (separate local Git repository, not
   for publication) with a manifest and `tools/luac51_dump.py` listings of all
   86 Lua 5.1 dict chunks.

## World entry reproduced (saitatter machine, 2026-11-16, 03:23)

The Proud error 14 blocker is resolved. 2007's handler connects `JP2PClient`
(`0x00956C80`) to a relay endpoint that only 5134 `eERC_SQUARE_CHANGE_RELAY_ADDRESS_NOT`
fills. The server now sends 5134 (127.0.0.1:9401) after 5029 and
`run_bootstrap.py` also listens on 9401 as a handshake-only relay. After selecting
"Tester", the town loaded with the character and an NPC dialogue, and Space
advanced the dialogue. Movement and further gameplay are not verified. Unhandled
next requests: 2131, 2569, opcode 0. See PROTOCOL.md §5.

## Latest local handoff ? 2026-11-16

[SESSION_HANDOFF.md](SESSION_HANDOFF.md) records the current machine setup and
resume instructions. Local world entry is **not verified**. The last test captured
a Proud::Exception with error 14, "Unknown Internet address", at a connection
validation path in 0x00B54B40. Earlier world-transition claims below are historical
collaborator notes and must not be treated as a reproduction on this machine.
The next target is endpoint reader 0x00A48A90 and the 2007 connection fields.
All owned final-test processes were stopped; generated artifacts remain local.

## Verified in the second session

1. The send blocker was encryption: game requests use ProudNet strong encryption (RmiContext `0x00F2C410`, mode 1) and `0x00B76050` aborted at `0x00B76515` because the shortened handshake never established a session key.
2. The emulator now performs the real key exchange (type 5 → 6 → 7): RSA-1024 OAEP-SHA1 for the session key, AES-128 ECB with a CRC-32 envelope for messages. The fast key in type 6 and every client message decrypt with a valid CRC.
3. The client's opcode → name table (1,191 entries) and runtime handler map (298 entries) were recovered; see `server/data/opcodes.tsv` and [PROTOCOL.md](PROTOCOL.md#5-application-flow-observed-in-the-live-client).
4. Observed flow with parser-accepted responses: welcome 5020 → DB list 2402/2403 (title Server List shows "Offline / None") → knock 2001/2002 → square list 2021/2022 (Channel List shows "Channel 1 · Normal · [Good]") → join square 5028/5029 → character list 2008/2009 (character select, "4 SLOT") → create 2012/2013 (character "Tester" appears, Warrior).
5. Characters persist in `data/characters.json` (ignored by Git) and are listed again after a client restart.
6. The intro cinematics are skipped by clicking once loading is complete; `gamectl skip-intro` clicks until the Server List opens.
7. The client runs in exclusive fullscreen; GDI capture works once the window is focused. DXUT's Alt+Enter toggles windowed mode.

Screenshots of each stage are kept locally in `research/` (`shot8.png` server list, `g7.png` channel list, `g10.png` empty character select, `g11.png` creation, `g13.png` created character).

## Fifth session findings & breakthroughs (2026-11-16)

1. **Asset Cryptography Fully Broken & Verified (`docs/CRYPTO_KEYS.md`):**
   - Reverse engineered JPK asset decryption function in `DarkBlood.exe` at `0x00411F90`.
   - Algorithm: subtract-1 then 73-byte polyalphabetic repeating XOR: `plain[i] = ((cipher[i] - 1) & 0xFF) ^ key[i % 73]`.
   - Secret key recovered from VA `0x00C4A848`: `305D006B-8D74-458f-BB80-CA243100F0DA-11406C9F-8393-42e8-9037-077D988CCF80`.
   - Verified on live client assets: `Common_0.jpk` extracts clean plaintext (`configure.txt`, `action.lua`, `macro.lua`), `Dict_*.jpk` extracts clean Lua 5.1 bytecode (`\x1bLuaQ`) compiled by `lua_tinker`. Updated `tools/jpk_extractor.py`.
2. **NPC Dialogue & Quest Progression (Opcode 2094 → 2095):**
   - Client sends `eEGS_NPC_FIRST_MEET_REQ` (2094) upon encountering NPCs or after beating tutorial monsters.
   - Decompiled handler `0x00752B60` (`eEGS_NPC_FIRST_MEET_ACK`, opcode 2095): expects `struct.pack('<II', 0, npc_id)`.
   - Handler registers `npc_id` as met in NPC Manager `0x00F2D0C0` via `FUN_00405150(npc_id, 1)` and `FUN_009d2a50(npc_id, 1)`, unlocking post-battle dialogue and quest advance.
3. **Character Creation Byte-Order & Lobby Deserialization:**
   - Reader `0x00A4AB30` expects Byte 8 = Level and Byte 9 = Character Class.
   - Fixed field inversion in `Character.encode_lobby_entry()` (previously swapped, causing Thief to render as "Warrior Level 4").
   - Fresh characters initialize with `level=1` and `tutorial_cleared=False`.
4. **Tutorial Progression & Skip Analysis:**
   - Opcode `2082` (`eEGS_CLEAR_TUTORIAL_REQ`) -> `2083` (`eEGS_CLEAR_TUTORIAL_ACK`). Handler `0x0077EEB0` reads reward vector and calls `0x006E5CE0`.
   - `0x006E5CE0` emits `2084` (`eEGS_CLEAR_OPENING_NOT`), sets `[Scene 4 + 0x75] = 1`, and calls Lua `g_jAS_Tutorial:On_Tutorial_FadeOut()`.
   - Discovered `DictTutorialReward:CompleteLoad` and `DictTutorialReward:SkipLoad` in `data\dict\tutorialreward.lua` with starting reward items (`Aneca0001`, `Ihppa0000`, `Imppa0000`).
5. **Multi-Agent Conventional Commits Rule:**
   - Updated `AGENTS.md` and `CONTRIBUTING.md` mandating Semantic Commit Conventions (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`).

## Fourth session findings & achievements (2026-11-16)

1. **Square Relay Server & JoinGroup Protocol:**
   - Identified ProudNet error 14 resolution: `5134` (`eERC_SQUARE_CHANGE_RELAY_ADDRESS_NOT`) announces relay server at `127.0.0.1:9401`.
   - Reverse engineered Relay PIDL RMI 1001 (`JoinGroup`) and implemented RMI 3001 (`JoinGroupACK`) with group host ID `0x10000` and member assignment.
2. **Decompiled Tutorial & Town Opcode Suite:**
   - Opcode `2131` -> `2132` (`eEGS_FRIEND_LIST_REQUEST_ACK`, handler `0x007712E0`): `struct.pack('<I', 0) + b'\x17\x00'`.
   - Opcode `2569` -> `2570` (handler `0x00772160`): `struct.pack('<I', 0) + b'\x17\x00'`.
   - Opcode `2082` -> `2083` (`eEGS_CLEAR_TUTORIAL_ACK`, handler `0x0077EEB0`): `struct.pack('<I', 0) + b'\x10\x00'`. Triggers `0x006DBFA0(9)` to transition to Town Scene.
   - Opcode `2346` -> `2347` (`eEGS_TUTORIAL_QUEST_START_ACK`, handler `0x006481E0`): `struct.pack('<I', 0)`.
   - Opcode `2390` -> `2391` (`eEGS_ROULETTE_MANAGER_INFO_ACK`, handler `0x006CC6B0`): `struct.pack('<I', 0) + (b'\x00' * 21)`.
   - Opcode `2353` (`eEGS_TUTORIAL_MONSTER_DEAD_NOT`) & `2352` (`eEGS_IP_ADDRESS_NOT`): client notifications mapped and recognized.
3. **High-Level Domain Models (`server/models.py`):**
   - Implemented dataclasses for `JoinSquareAck`, `RelayAddressNot`, `PostListAck`, `FriendListAck`, `GuildOrAttendanceAck`, `ClearTutorialAck`, `TutorialQuestStartAck`, `RouletteManagerInfoAck`, and `RelayJoinGroupAck`.
   - Refactored `server/game_wire.py` to use domain models directly, maintaining human-readable code.
4. **Direct3D 9 Multi-Adapter Hook (`client_hook/steam_api_hook.c`):**
   - Intercepted `Direct3DCreate9` and `IDirect3D9::CreateDevice`.
   - Added automatic adapter fallback for headless/virtual display systems (Parsec Adapter 0 fallback to Adapter 1 or Reference Rasterizer `d3dref9.dll`).
5. **Headless Test Suite (`tests/test_headless_flow.py`):**
   - Added automated headless tests for character selection, relay handshake, and all town/tutorial opcodes.
   - 100% test pass rate in 0.6s without opening game windows.

## Third session findings & achievements (2026-11-16)

1. **Character Selection (2006 → 2007):** Recovered the complete 651-byte binary schema for `eEGS_SELECT_CHAR_ACK` (`0x007AA4B0` / reader `0x00A40760`). Modeled with high-level dataclasses in `server/models.py` (`GameServer`, `ChannelSquare`, `CharacterClass`, `CharacterVisuals`, `Character`, `SelectCharacterAck`).
2. **ProudNet RMI Ping/Pong Protocol (0xFA01 → 0xFA02):** Reverse engineered client ping handler at `0x00B47ED0` in `normal.bin`. Client sends RMI ping type 1 (`0x01`, ID `0xFA01`). Implemented immediate `0xFA02` pong response echoing timestamp and sequence in `server/bootstrap_server.py`.
3. **World Transition Opcode Pipeline:**
   - **5030 → 5031 (`eERC_JOIN_LAYER`):** Handler `0x00787A70` (`u32 result`, `u64 layer_id`, `u64 instance_id`, `u8 tag`).
   - **2016 → 2017 (`eEGS_ENTER_MAPTOOL`):** Handler `0x00757D20` (`u32 result` = 0 triggers Scene 5).
   - **5013 → 5014 (`eERC_START_GAME`):** Handler `0x007880A0`/`0x00788199` (`u32 result`, `u16`, `u32`, `wstr`, 3 × `0x17` map, `u8 tag` = 0 triggers Scene 9 / Town).
4. **Multi-Desktop Windows Sandbox Automation:**
   - Discovered that the Windows agent sandbox creates isolated virtual desktops on `WinSta0` (`exebox-...`).
   - Enhanced `tools/gamectl.py` to traverse all desktops via `EnumDesktopsW` and `EnumDesktopWindows`, attaching via `SetThreadDesktop`.
   - Enhanced input delivery using `AttachThreadInput`, `BringWindowToTop`, `SetForegroundWindow`, and dual `mouse_event`/`keybd_event` + `PostMessageW` routing.
5. **Collaborator Setup & Recurring Sync:**
   - Granted repository collaborator status to `CristianVita` (`cri999sti@gmail.com`) and `mauvalefotos@gmail.com`.
   - Branch protection enabled on `main` (`allow_force_pushes: false`, required PR reviews: 1, `enforce_admins: false` allowing owner `saitatter` administrative privileges).
   - Contributors submit changes via feature branches and Pull Requests (PRs); force pushes are blocked.
   - Updated [CONTRIBUTING.md](../CONTRIBUTING.md) and [AGENTS.md](../AGENTS.md) mandating Semantic Commit Conventions and the 10-minute sync cycle.

## Immediate blocker

The world load sequence triggers Scene 9 (Town). Next step is to observe and implement the in-world entity synchronization and movement notifications (`eERC_UPDATE_CHAR_INFO_NOT` 5096, `eERC_MOVE_NOT`, etc.) to achieve full interactive free-roam in town.

## First session findings (2026-11-15)

1. The initial Steam shim lacked exports required during dynamic import resolution; termination hooks concealed this.
2. Completing the export surface and disabling termination hooks allowed `SteamAPI_RestartAppIfNecessary(267790)` and `SteamAPI_Init`.
3. Returning pointer `1` from Steam interface getters caused invalid accesses (crash at `0x0092C322`); minimal SteamUser/SteamFriends interfaces fixed startup.
4. The client connects to `54.173.235.121:9400`; the shim redirects IPv4 `connect` to loopback, preserving the port.
5. The plaintext route to `OnJoinServerComplete result=0` and the decoded 5020 welcome were reached; the encrypted route above replaces it.

## Artifact identities

| Artifact | SHA-256 |
| --- | --- |
| Original `DarkBlood.exe` | `a82ae3d71b596418c1f3593cb63d3f9746318d452143c2e88f6ebbaff339c931` |
| `research/normal.bin` | `7909a808a15a0caa8355fca5630b2497c66100e61d43a2aaf00b30a06519c894` |
| `research/client/crash_image.bin` | `fdac37cd829cdea136f85e604d6386f9407dfe3f6e6a20e2d742c3efeb0b6ff4` |
| `research/unpacked.analysis.exe` | `a05dde1ddfb5aafb0878452fb47d6dbcf4637885be5674bd8a3baeaa150756ba` |
| `research/client/steam_api.dll.bak` | `fd16fba7a64afdcfcad2a935337432400c8c528e3f210a6672254f75d39bad7e` |
| Initial hook source, `research/steam_api_hook.before.c` | `98eb8e87513e5732dde7f393b4aecb71c9aef97c8e614af44b5a9c34377652c1` |

The version label `1.6.5#0` comes from the earlier notes and needs independent verification. Use the hash as the compatibility anchor for hardcoded addresses.

The original EXE is PE32 x86, image base `0x00400000`, and 5,509,120 bytes on disk. Captured images are `0xDA0000` bytes. Dumps taken at different stages have different contents: mutable state, DLL/heap addresses, and diagnostic patches.

`unpacked.analysis.exe` was derived from `crash_image.bin`, not `normal.bin`. Its converter maps the image into one `.image` section, removes loader directories, and sets an artificial entry seed. It is a static-analysis fixture, not a runnable unpacked client.

## Local evidence inventory

`research/` and `logs/` are ignored by Git and may be absent on another machine.

| File / group | Contents |
| --- | --- |
| `research/wire.jsonl` | First passive capture: connection and initial frame |
| `logs/wire.jsonl` | Multiple live sessions: connect/recv/message/send/disconnect, peer, timestamp, hex |
| `research/client/hook_log.txt` | Latest session: Steam, redirect, successful connection, application event, welcome decode |
| `research/decode.log`, `decode.bin` | Welcome parser instrumentation and next wait for 2403 |
| `research/join.log`, `join.bin` | Connection callback confirmation |
| `research/normal.log`, `normal.bin` | Normal launch and mapped-image dump containing unpacked code |
| `research/debug.log`, `loaded.bin` | Initial debugger experiments; behavior differs from a normal launch |
| `research/steam_init.evidence.json` | REA/Ghidra Evidence for artificial seed `0x92C2E0` |
| `research/unpacked.rea.json` | Snapshot of queried REA observations, not a complete persistent Ghidra project |
| `research/focused.log` | Latest focused Ghidra run; overwritten by subsequent runs |
| `research/bootstrap*.log`, `network.log`, `interfaces.log`, `pong.log`, `welcome.log`, `greeting.log` | Intermediate experiments; some logs are empty |

Focused decompilation outputs:

| Area | Local files under `research/` |
| --- | --- |
| ProudNet handshake and fields | `handshake.c`, `connected.c`, `fields.c`, `strings.c`, `network-functions.c`, `focused.c` |
| Control and sending | `control.c`, `fallback.c`, `send.c`, `proud-send.c`, `route.c`, `tcp-route.c` |
| JEvent and startup | `game-wire.c`, `serializer.c`, `startup.c`, `startup-wait.c`, `welcome.c`, `welcome-fields.c`, `welcome-map.c` |

The cropped splash screenshot is preserved locally as `research/splash-local.png`. It is not evidence of gameplay.

## Tools and reproduction

Verified environment: Windows x64, Python 3.8, MSVC 2022 x86, Ghidra 12.1.4, JDK 21.0.9, REA CLI 6.7.0. The server and tools use only the Python standard library.

### Headless tests (no game window)

```powershell
python -m unittest discover -s tests -v          # server end-to-end, ~1 s
python tools\headless_client.py --port 9400 --select 1   # against a running server
```

`tools/headless_client.py` performs the client side of the handshake (RSA-OAEP-SHA1
session key, AES envelopes, type 0x26 mode 1 with the u16 counter) and replays the
observed lobby requests. It checks the server, not the real client's parsers.

### Driving the game

`tools/gamectl.py` (CLI) and `tools/mcp_server.py` (MCP stdio server, registered in `.mcp.json`) start/stop the server and client, take screenshots, send keys/clicks, skip the intro, walk to character select, and decode the wire log with opcode names:

```powershell
python tools\gamectl.py start
python tools\gamectl.py enter-lobby        # intro -> server -> channel -> character select
python tools\gamectl.py screenshot research\shot.png
python tools\gamectl.py events
python tools\gamectl.py stop
```

`gamectl` stops only processes it started (`logs/session.json`) and refuses to start if port 9400 is busy.

### Shim diagnostics

- `research/client/bp.txt`: in-process INT3 tracer. Lines are `<hex VA> [max=N] [expr ...]`, with `reg+off` (dword), `reg+off.N` (bytes) and `@reg+off+off2` (dereference). It logs registers and restores the byte, single-steps and re-arms. No debugger is attached.
- `research/client/sample.txt` (presence): logs the main thread's EIP and code return addresses every 5 s.
- `handler_map.txt` is written at OnJoinServerComplete (columns: raw words; key = 2nd, handler = 4th).

### Focused decompilation

```powershell
.	ools\decomp.ps1 research\out.c 0x7aa4b0 0xa40760
```

### Passive capture

```powershell
python tools\capture_server.py --port 9400 --output research\wire.jsonl
```

### Bounded launch and dump

```powershell
.\tools\build_debugger.bat
$env:__COMPAT_LAYER = 'RunAsInvoker'
$env:DB_NO_DEBUG = '1'
.\research\debug_client.exe "$pwd\research\client\DarkBlood.exe" "$pwd\research\client" research\session.bin 15000 > research\session.log
```

With `DB_NO_DEBUG` present, the helper launches normally, waits, enumerates modules/threads/windows, captures the image, and terminates its own child. Without that variable it uses Windows Debug API; the packer behaved differently in that mode. A child that exits before inspection may produce no dump. Currently unreadable pages are zero-filled without a separate coverage manifest; interpret missing data carefully.

### Ghidra / REA

The connected REA server lacked Ghidra/JDK environment configuration. CLI analysis worked using command-local environment variables:

```powershell
$env:GHIDRA_INSTALL_DIR = 'C:\Users\saita\tools\ghidra_12.1.4_PUBLIC'
$env:JAVA_HOME = 'C:\Users\saita\.jdks\ms-21.0.9'
$env:REA_JAVA_COMMAND = 'C:\Users\saita\.jdks\ms-21.0.9\bin\java.exe'
rea providers --format json
```

No global MCP configuration was changed. Full REA auto-analysis took several minutes on the large fixture. Its snapshot stores queried observations, not every future answer without further analysis.

For a new fixture, use a confirmed function boundary:

```powershell
python tools\image_to_pe.py research\session.bin research\session.analysis.exe --entry 0x92c2c0
```

Focused analysis example:

```powershell
New-Item -ItemType Directory research\ghidra-focused -Force | Out-Null
& "$env:GHIDRA_INSTALL_DIR\support\analyzeHeadless.bat" `
  "$pwd\research\ghidra-focused" DarkBlood `
  -import "$pwd\research\unpacked.analysis.exe" -noanalysis `
  -scriptPath "$pwd\tools" `
  -postScript FocusedDecompile.java "$pwd\research\next.c" 0xb53310 0xb75710 `
  -deleteProject
```

This example analyzes the historical fixture. Do not overwrite its identity if retaining the link to existing evidence. The focused script is fast but has limited analysis: verify signatures, stack variables, and function boundaries against assembly.

The original REA seed `0x92C2E0` begins inside the Steam-related function. Its confirmed start is `0x92C2C0`. The artificial `entry` in that Evidence is not the original program entry point.

## Outstanding code and asset issues

- Existing XML in `extracted_sample/` is malformed, for example `"!xol vkNukon=...` instead of valid XML. The key in `CRYPTO_KEYS.md` is inherited and unverified; the old README contained a different value. Recover and validate the algorithm/key again.
- The supplied `DarkbloodKR.ini` is not plaintext INI. Its packaging/obfuscation remains unresolved.
- The Steam shim has incomplete export semantics and invalid interfaces not yet exercised by startup.
- Termination-hook definitions remain as dead WIP code; they are not installed.
- The server does not validate type-8 connection requests. Application handlers exist only for the flow up to character creation.
- Server → client messages are sent unencrypted; the client accepts them, but the original server may have encrypted them.
- `0x1D → 0x1F` is exploratory. The `0x1E` timing parser is recovered; complete control-message semantics are not.
- No dedicated automatic protocol test suite has been added. Native builds and bounded live-client experiments succeeded through the milestones above; these are not gameplay end-to-end tests.

## Workspace state at pause

Second session: changes are uncommitted on `main` (no commit was requested). The test client and server started by `gamectl` were stopped. The pre-existing `server/server.py` process (ports 10001/10002) was left untouched. Verify processes and ports before resuming.

## Public repository preparation

The user subsequently requested a public repository named `darkblood-server-emulator`. A clean `main` branch was prepared containing only source and documentation. The original two-commit history remains locally on `master`, because it includes extracted game resources. Those resources remain on disk and are ignored on `main`. Only `main` should be pushed; do not publish all branches or mirror the local repository.
