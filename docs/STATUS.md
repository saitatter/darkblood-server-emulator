# Research status and handoff

## Random box toast and subclass skill report - 2026-11-22

- User reported that random boxes grant the rolled inventory item but also display "Please try again." Static decompilation of the hash-verified client's analysis fixture shows `2039 UseItemAck` handles nonzero results through the localized result table, while `2196 RandomboxResultItemNot` is a separate successful-roll notification. The emulator sent the `2039` success and `2037` inventory update but omitted `2196`.
- Added a `2196` notification after the inventory update for successful `DictRandomBox` rolls, carrying the rolled item hash and count. This is a source-level fix based on client static analysis; live confirmation is pending. The derived `research/unpacked.analysis.exe` fixture was decompiled only and was not launched.
- User also reported missing new skills after choosing a subclass. The promotion dialog data selects a subclass and branches into its questline; the `2076` completion request carries only quest ID and reward selection. `2283` applies the server-provided learned-skill map after a skill reset. The server currently sends an empty map and refunds AP. The exact skills expected from the selected profession remain unclear, so no guessed learned-skill grants were added pending the user's class/skill details.
- Headless suite: 221/221 tests pass, including the random-box `2196` result assertion. Live client confirmation is pending.

> Older per-feature logs (2026-11-15 to 11-20) were removed once the work was implemented and summarized in the README,
> `docs/OPCODE_REGISTRY.md` and `ROADMAP.md`; they remain in Git history. This file keeps recent evidence and the RE notes still in use.

## Live two-client playtest — 2026-11-20 (evening)

- Room finder (2010 -> 2011) lists open rooms; jRoomInfo layout recovered
  (max/current users, state, gate, map, difficulty). Verified live that the
  room appears.
- Town peers are announced both ways at 2131 (after the town load starts,
  before the relay JoinGroup). Verified live: both players see each other.
- Peers carry server key 31 (own JUser `+0x100` read live as all ones), which
  should remove the "(Offline)" name suffix.
- Revive (5094) echoes nLayerID/nX/nY; town layer is the low dword of
  nJoinLayerNetID (default 0, persisted from 5030); 5096 carries the current
  layer; floor gold shows the rolled amount; relay leaves notify the departing
  member of every peer. Live checks pending.
- Open: town movement desync/latency, worst with world-map click-to-move.
  Positions arrive every ~216 ms through the relay with no drops. Next: decode
  relayed P2P messages with the server-generated keys.
- 181 headless tests pass.

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

- Existing XML in `extracted_sample/` is malformed and must not be treated as plaintext. JPK extraction itself is
  verified (`docs/JPK_FORMAT.md`, `tests/test_jpk.py`); `docs/CRYPTO_KEYS.md` records the cipher.
- The supplied `DarkbloodKR.ini` is not plaintext INI; its packaging/obfuscation is unresolved.
- The Steam shim implements few interface slots (see ROADMAP, P5) and redirects IPv4 `connect` only.
- Server → client messages are unencrypted (the client accepts them); `0x1D -> 0x1F` is exploratory.
- Unmapped wire fields: `docs/UNMAPPED_FIELDS.md` (generated). Open features: `ROADMAP.md`.

## Public repository preparation

The user subsequently requested a public repository named `darkblood-server-emulator`. A clean `main` branch was prepared containing only source and documentation. The original two-commit history remains locally on `master`, because it includes extracted game resources. Those resources remain on disk and are ignored on `main`. Only `main` should be pushed; do not publish all branches or mirror the local repository.
