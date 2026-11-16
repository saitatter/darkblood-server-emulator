# Session handoff — 2026-11-16 (Cristian machine)

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
4. Unequip: Resolved and verified in tests. `0x008354D0` skips container 2 because container 2 is managed by `0x009411A0` (inventory bag slot index updater). When moving or unequipping an item to an empty slot, Dark Blood requires a two-cell wire diff: the moved item in its new container/slot AND an empty item placeholder (`uid=0, code='', container=old_c, slot=old_s`) for the vacated slot. Without the empty record, the client never calls `0x0082F5F0` to detach the old gear mesh or clear the paperdoll slot. Additionally, right-click unequip in `on_2042` was implemented to find the first free bag slot and return both the unequipped item and the cleared equipment slot.
   the server swapped them back into the equipment. The bag is now id 3 (no migration; the data was reset).

Open: confirm all four live; find the revive-button request; check whether `2143` values are f32 before persisting durability.

## Update — 2026-11-16 ~22:45 (1v1 Town Duels, Arena Matchmaking, Multi-Client World Presence & SQLite Backend)

1. 1v1 PvP Town Duels & Arena Matchmaking (Opcodes 5097 - 5113, 2304 - 2309, 5138, 5269 - 5275, 2550 - 2553):
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
2. Multi-Client World Presence & Mutual Spawns (`GameWorldManager` & Opcode 5096 `UpdateCharInfoNot`):
   - Implemented singleton `GameWorldManager` in `src/darkblood/games/world.py`:
     - Tracks active players across town square channels and instanced sub-districts.
     - Automated mutual player spawning via Opcode 5096 (`eERC_UPDATE_CHAR_INFO_NOT` / struct `0x00A52630` `FUN_00a52630`).
     - Broadcaster delivers visual models of existing town inhabitants to newcomers and announces newcomer 3D appearances to existing occupants.
     - Automatic cleanup on disconnect via `Session.run` finally block and `GameSession.on_disconnect`.
   - Verified with dual-client live interaction in `tests/test_world_flow.py`.
3. SQLite Primary Backend Integration (`data/darkblood.db`):
   - Switched `GameSession.store()` runtime character store from JSON to `SqliteCharacterStore`.
   - Added in-memory character caching with atomic `save()` synchronization.
   - Added automated migration on first run if database is empty and `characters.json` exists.
   - Linked `tools/dashboard.py` directly to `SqliteCharacterStore`.
4. Test Suite Verification:
   - **114/114 tests passing cleanly** across all unit and headless flow test suites in ~1.71s.

## Update — 2026-11-16 ~22:00 (Modular Messages, GM Web Dashboard & Semantic Handlers Architecture)

1. Modular Domain Package Architecture (`src/darkblood/games/network/messages/`):
   - Successfully deconstructed monolithic `messages.py` (110 KB, 247 dataclasses) into clean domain packages matching client architecture:
     - `lobby.py`, `inventory.py`, `skills.py`, `commerce.py`, `quests.py`, `dungeon.py`, `social.py`, `guild.py`, `events.py`, `system.py`.
   - Maintained 100% backward compatibility via `__init__.py` re-exports (`from darkblood.games.network.messages import *`).
2. Standalone GM & Server Web Dashboard (`tools/dashboard.py`):
   - Zero-dependency web dashboard on `http://127.0.0.1:9494`.
   - Real-time socket health probes for Game Server (9400) and Relay Server (9401) with millisecond latency measurement.
   - Interactive character explorer and editor: view character data from `data/characters.json` / SQLite, modify levels (1-60), clear tutorial flags, and delete characters.
   - Opcode reference directory: instant search and domain filtering for all 1,400+ Dark Blood opcodes.
3. Semantic Handler Architecture:
   - Replaced raw opcode identifiers with descriptive semantic method names (`handle_buy_item`, `handle_clear_tutorial`, `handle_select_character`, etc.).
   - Attached backward-compatible `on_<opcode>` aliases and detailed reverse-engineering docstrings with memory offsets and wire structures.
4. Granular Unit Testing:
   - Expanded bundled multi-opcode tests in `tests/test_wire_messages.py` into distinct, granular unit tests.
   - **105/105 tests passing cleanly** across all 11 test modules in ~1.36s.

## Update — 2026-11-16 ~21:30 (Guild Banking, Level Up, Item Splitting & Storage Depot)

1. Guild Banking, Grade & Level-Up System (Opcodes 2157 - 2158, 2164 - 2165, 2179 - 2186, 2205):
   - Reverse engineered `0x00752FF0` (`GuildInfoNot`), `0x0077ABA0` (`GuildPersonListNot`), `0x00794250` (`GuildMoneyInAck`), `0x00794470` (`GuildMoneyOutAck`), `0x00753170` (`GuildPersonGradeModifyAck`), `0x00753380` (`GuildLevelUpAck`), `0x0075A120` (`GuildNoticeModifyAck`), and `0x00779390` (`GuildSkillNot`).
   - Wire serialization: `GuildMoneyInReq/Ack` (i64 amount -> u32 result, i64 remain_gold), `GuildMoneyOutReq/Ack`, `GuildPersonGradeModifyReq/Ack` (i64 member_uid, i16 new_grade), `GuildLevelUpReq/Ack` (i16 new_level), `GuildNoticeModifyReq/Ack` (wstring notice), and `GuildSkillNot` (bool flag, Tag 0x10 skills vector).
   - Wired domain handlers `on_2179`, `on_2181`, `on_2164`, `on_2183`, `on_2185` in `social.py`.
   - Verified in `tests/test_social_flow.py` and `tests/test_wire_messages.py`.
2. Personal Storage Depot & Mail Return (Opcodes 2227 - 2231, 2234 - 2235):
   - Reverse engineered `0x00795220` (`DepotSaveArAck`), `0x00795490` (`DepotLoadArAck`), `0x007965B0` (`PostNewArrivalNot`), and `0x00771470` (`PostReturnAck`).
   - Wire serialization: `DepotSaveArReq/Ack` (i64 gold -> u32 result, Tag 0x17 map, i64 new_storage_gold), `DepotLoadArReq/Ack`, `PostNewArrivalNot` (empty notification), and `PostReturnReq/Ack` (i64 mail_id -> u32 result, Tag 0x10 vector).
   - Wired domain handlers `on_2228`, `on_2230` in `commerce.py` and `on_2234` in `social.py`.
   - Verified in `tests/test_inventory_flow.py`, `tests/test_social_flow.py`, and `tests/test_wire_messages.py`.
3. Item Stack Splitting, Skill Books & Inventory Refresh (Opcodes 2092, 2111 - 2112, 2250 - 2251, 2321 - 2322):
   - Reverse engineered `0x0077F570` (`DivideItemAck`), `0x0078BCD0` (`UseLearnSkillItemAck`), `0x0077F070` (`InventoryUpdatedNot`), `0x0077AED0` (`ItemRemainTimeNot`), and `0x00774DD0` (`ItemDeleteNot`).
   - Wire serialization: `DivideItemReq/Ack` (i64 source_uid, i64 dest_uid, i32 count, i16 slot -> u32 result, Tag 0x10 items), `UseLearnSkillItemReq/Ack` (i64 item_uid, i16 skill_id -> u32 result, i16 skill_id, u8 level, i32 item_code, i32 count, Tag 0x10 items, i32 sp), and `InventoryUpdatedNot` (Tag 0x10 deleted + Tag 0x10 added).
   - Wired domain handlers `on_2250` and `on_2111` in `commerce.py`.
   - Verified in `tests/test_inventory_flow.py` and `tests/test_wire_messages.py`.
4. Combat AP, Dungeon Penalty & Random Box (Opcodes 2085, 2109, 2196):
   - Reverse engineered `0x0078FA70` (`ChangeDungeonPenaltyNot`), `0x00790480` (`InsertApNot`), and `0x0075A2E0` (`RandomboxResultItemNot`).
   - Wire serialization: `InsertApNot` (i32 current_ap, i32 total_ap), `ChangeDungeonPenaltyNot` (bool in_dungeon, bool is_penalty, i16 level, i32 id, i32 duration), and `RandomboxResultItemNot` (u32 result, i32 item_code, i16 count, bool is_jackpot).
   - Verified in `tests/test_wire_messages.py`.
5. Test Suite:
   - 72/72 unit and flow tests passing cleanly across all 11 test modules in ~1.33s.


## Update — 2026-11-16 ~21:15 (Titles, Achievements, Avatar Zam Socketing, Security & Inspection)

1. Titles & Achievements System (Opcodes 2327 - 2336):
   - Reverse engineered `0x007751C0` (`TitleChangeAck`), `0x0079D650` (`AchieveGetListAck`), `0x0076C720` (`AchieveChangeNot`), and `0x0079D240` (`AchieveCompleteNot`).
   - Wire serialization: `TitleChangeReq/Ack` (i32 title_id -> i32 result, i32 title_id), `AchieveGetListReq/Ack` (Tag 0x1E + Tag 0x17 + Tag 0x17 + Tag 0x0A + Tag 0x10), `AchieveChangeNot` (3x Tag 0x17 maps), and `AchieveCompleteNot` (2x Tag 0x10 vectors).
   - Wired domain handlers `on_2335` and `on_2327` in `social.py`.
   - Verified in `tests/test_social_flow.py` and `tests/test_wire_messages.py`.
2. Avatar Gem / Zam Socketing System (Opcodes 2362 - 2365):
   - Reverse engineered `0x00782D00` (`AvatarZamInsertAck`) and `0x00782F40` (`AvatarZamEraseAck`).
   - Wire serialization: `AvatarZamInsertReq/Ack` (i64 avatar_uid, i64 zam_uid -> i32 result, Tag 0x10 items) and `AvatarZamEraseReq/Ack` (i64 avatar_uid -> i32 result, Tag 0x10 items).
   - Wired domain handlers `on_2362` and `on_2364` in `commerce.py`.
   - Verified in `tests/test_inventory_flow.py` and `tests/test_wire_messages.py`.
3. Class Promotion, Skill Reset & Rebirth Coins (Opcodes 2280, 2283, 2286):
   - Reverse engineered `0x00797740` (`InitSkillNot`), `0x00797F00` (`PromotionNot`), and `0x007983B0` (`RebirthCoinChangeNot`).
   - Wire serialization: `InitSkillNot` (u32 result, i32 sp, Tag 0x17 skills map), `PromotionNot` (u32 result, u8 new_class, i32 sp, Tag 0x17 skills map), and `RebirthCoinChangeNot` (u32 result, i16 coins).
   - Verified in `tests/test_wire_messages.py`.
4. Arena SP Item & Arena Return (Opcodes 2709 - 2710, 5165 - 5166):
   - Reverse engineered `0x007A7CA0` (`UseArenaSpItemAck`) and `0x00758550` (`ArenaBackToSquareAck`).
   - Wire serialization: `UseArenaSpItemReq/Ack` (i64 item_uid -> u32 result, Tag 0x10 items, i32 arena_sp) and `ArenaBackToSquareReq/Ack`.
   - Wired domain handler `on_2709` in `commerce.py` and `on_5165` in `social.py`.
   - Verified in `tests/test_inventory_flow.py` and `tests/test_social_flow.py`.
5. Second Password / Security PIN (Opcodes 5256 - 5261):
   - Reverse engineered `0x0075B020` (`SecondPassCreateAck`), `0x0075B050` (`SecondPassModifyAck`), and `0x0075B080` (`SecondPassAuthAck`).
   - Wire serialization: `SecondPassCreateReq/Ack`, `SecondPassModifyReq/Ack`, `SecondPassAuthReq/Ack`.
   - Wired domain handlers `on_5256`, `on_5258`, and `on_5260` in `social.py`.
   - Verified in `tests/test_social_flow.py` and `tests/test_wire_messages.py`.
6. Remote Player & Item Inspection (Opcodes 6011 - 6012, 6028 - 6029):
   - Reverse engineered `0x00790FA0` (`RequestCharInfoAck`) and `0x00766C20` (`RequestItemInfoAck`).
   - Wire serialization: `RequestCharInfoReq/Ack` (i64 char_uid -> u32 result, bool flag, Tag 0x1E summary, 2x Tag 0x10 item vectors) and `RequestItemInfoReq/Ack` (i64 item_uid -> u32 result, i64 item_uid, Tag 0x1E item struct).
   - Wired domain handlers `on_6011` and `on_6028` in `social.py`.
   - Verified in `tests/test_social_flow.py` and `tests/test_wire_messages.py`.
7. Test Suite:
   - 69/69 unit and flow tests passing cleanly across all 11 test modules in ~1.40s.


## Update — 2026-11-16 ~21:00 (Mentoring, Teaching & Gold Goblin Encounter Events)

1. Mentoring & Teaching System (Opcodes 5351 - 5357):
   - Reverse engineered `0x0075C200` (`RequestTeachingAck`), `0x0075C430` (`AcceptRequestTeachingAck`), and `0x007A5890` (`TeachingGetInfoNot`).
   - Wire serialization: `RequestTeachingReq/Ack` (i64 target_uid, wstring target_name), `AcceptRequestTeachingReq/Ack` (bool accepted, i64 mentor_uid, wstring mentor_name), and `TeachingGetInfoNot` (Tag 0x1E struct).
   - Wired domain handlers `on_5351` and `on_5353` in `social.py`.
   - Verified in `tests/test_social_flow.py` and `tests/test_wire_messages.py`.
2. Gold Goblin Encounter Events (Opcodes 5362 - 5367):
   - Reverse engineered `0x007A6D10` (`GoldGoblinAppearNot`), `0x00784A10` (`GoldGoblinAttackAck`), and `0x00784CA0` (`GoldGoblinDeadAck`).
   - Wire serialization: `GoldGoblinAppearNot` (i32 goblin_id, tag 0x10 items), `GoldGoblinAttackReq/Ack`, `GoldGoblinDeadReq/Ack`, and `GoldGoblinDisappearNot`.
   - Wired domain handlers `on_5363` (attack goblin) and `on_5365` (kill goblin and reward items) in `dungeon.py`.
   - Verified in `tests/test_dungeon_flow.py` and `tests/test_wire_messages.py`.
3. Citadel & Treasure Notifications (Opcodes 5344 - 5346):
   - Reverse engineered `0x007722F0` (`TreasureStartNot`), `0x0075BC00` (`TreasureEndNot`), and `0x007833F0` (`CitadelRewardNot`).
   - Wire serialization: `TreasureStartNot`, `TreasureEndNot`, and `CitadelRewardNot` (Tag 0x17 map + Tag 0x10 items vector).
   - Verified in `tests/test_wire_messages.py`.
4. Test Suite:
   - 64/64 unit and flow tests passing cleanly across all 11 test modules in ~1.48s.

## Update — 2026-11-16 ~20:45 (Character & Guild Renaming, Custom Keybindings & Spirit Weapons)

1. Character & Guild Renaming (Opcodes 2310 - 2315):
   - Reverse engineered `0x00780200` (`CharNickChangeAck`) and `0x00780590` (`GuildNameChangeAck`).
   - Wire serialization: `CharNickChangeReq/Ack` (wstring new_name, i64 item_uid -> i32 result, tag 0x10 items, wstring new_name) and `GuildNameChangeReq/Ack`.
   - Wired domain handlers `on_2310` (character nickname change with character store persistence) and `on_2314` (guild name change) in `social.py`.
   - Verified in `tests/test_social_flow.py` and `tests/test_wire_messages.py`.
2. Custom Keymapping & Keybindings (Opcodes 2319 - 2320):
   - Reverse engineered `0x00753960` (`KeyboardSetCustomKeyAck`).
   - Wire serialization: `KeyboardSetCustomKeyReq/Ack` (arbitrary raw keyboard mapping blob).
   - Wired domain handler `on_2319` in `social.py` persisting custom key bindings on character record.
   - Verified in `tests/test_social_flow.py` and `tests/test_wire_messages.py`.
3. Spirit Weapon System (Opcodes 2338 - 2339):
   - Reverse engineered `0x00780860` (`ItemSpiritChangeAck`).
   - Wire serialization: `ItemSpiritChangeReq/Ack` (i64 item_uid, i64 spirit_item_uid -> i32 result, i64 spirit_uid, tag 0x10 items).
   - Wired domain handler `on_2338` in `commerce.py`.
   - Verified in `tests/test_inventory_flow.py` and `tests/test_wire_messages.py`.
4. Test Suite:
   - 62/62 unit and flow tests passing cleanly across all 11 test modules in ~1.94s.

## Update — 2026-11-16 ~20:30 (SQLite Storage Backend, Item Enchanting, Upgrades & Loot Pickup)

1. SQLite Character Store & JSON Migration (Milestone P9):
   - Designed `ICharacterStore` interface and implemented `SqliteCharacterStore` in `src/darkblood/player_management/store.py` backed by `data/darkblood.db`.
   - Supports atomic transactions, relational indexes on `name` (case-insensitive) and `account`, and full character JSON blob storage.
   - Implemented bidirectional migration utilities `import_from_json(json_path)` and `export_to_json(json_path)`.
   - Verified in `tests/test_character_store.py`: CRUD operations, case-insensitive duplicate name rejection, and bidirectional JSON <-> SQLite migration.
2. Magic Enchanting & Item Upgrades (Opcodes 2254 - 2259, 2284 - 2285, 2672 - 2673):
   - Reverse engineered `0x00796DC0` (`MagicEnchantEnchantAck`), `0x00797120` (`MagicEnchantEraseOptionAck`), `0x0077FC60` (`MagicEnchantExpendSlotAck`), `0x0077FED0` (`RandomItemUpgradeAck`), and `0x00783C40` (`FixItemUpgradeAck`).
   - Implemented wire serialization and domain handlers `on_2254`, `on_2256`, `on_2258`, `on_2284`, and `on_2672` in `commerce.py`.
   - Verified in `tests/test_inventory_flow.py` and `tests/test_wire_messages.py`.
3. Item Drop, Pickup & Real-Time Presence (Opcodes 5065 - 5068, 5114, 5118 - 5119, 5096):
   - Reverse engineered `0x0078AD80` (`PickUpItemResultAck`), `0x00792700` (`GetDropArNot`), `0x0077A8A0` (`FriendMyConnectionNot`), `0x00758FA0` (`FriendMyDisconnectionNot`), and `0x0078C990` (`UpdateCharInfoNot`).
   - Implemented wire serialization and domain handlers `on_5065` (Pick up item) emitting 5066 and 5068 in `dungeon.py`.
   - Verified in `tests/test_dungeon_flow.py` and `tests/test_wire_messages.py`.
4. Test Suite:
   - 61/61 unit and flow tests passing cleanly across all 11 test modules in ~1.38s.

## Update — 2026-11-16 ~20:10 (Mailbox, P2P Trade, Party Invites, GM Console Commands & Quest State)

1. Mailbox System (Opcodes 2221 - 2237):
   - Reverse engineered `0x00795D70` (`PostSendReq`), `0x00795F40` (`PostSendAck`), `0x007963C0` (`PostReadReq`), `0x0075A660` (`PostReadAck`), `0x0079664C` (`PostGetAppendItemReq`), `0x0077F8E0` (`PostGetAppendItemAck`), `0x007964EC` (`PostDeleteReq`), and `0x007715F0` (`PostDeleteAck`).
   - Implemented wire serialization and domain handlers `on_2221`, `on_2223`, `on_2225`, and `on_2236` in `social.py`.
   - Verified send, read, claim item/gold, and delete in `tests/test_social_flow.py` and `tests/test_wire_messages.py`.
2. P2P Direct Trade (Opcodes 5069 - 5084):
   - Reverse engineered `0x00770E50` (`RequestTradeAck`), `0x007587B0` (`AcceptRequestTradeAck`), `0x0077DE00` (`CancelTradeAck`), `0x0077D980` (`InsertTradeItemAck`), `0x0077DBB0` (`DeleteTradeItemAck`), `0x00758940` (`UpdateTradeArAck`), and `0x0078EB40` (`AcceptTradeAck`).
   - Implemented wire serialization and domain handlers `on_5069`, `on_5071`, `on_5073`, `on_5075`, `on_5077`, `on_5079`, `on_5081`, and `on_5083` in `commerce.py`.
   - Verified trade lifecycle in `tests/test_inventory_flow.py` and `tests/test_wire_messages.py`.
3. Party & Team System (Opcodes 5049 - 5055, 5015 - 5016):
   - Reverse engineered `0x00758700` (`PartyInviteAck`), party acceptance (`PartyAcceptInviteAck`), and team changes (`ChangeTeamAck`).
   - Implemented wire serialization and domain handlers `on_5049`, `on_5054`, and `on_5015` in `dungeon.py`.
   - Verified in `tests/test_dungeon_flow.py` and `tests/test_wire_messages.py`.
4. Chat & In-Game GM Console Commands (Opcodes 5040 - 5041):
   - Reverse engineered `0x007AC5E0` (`ChatReq`) and `0x007AC890` (`ChatAck`) using Tag `0x1E` message struct.
   - Handled GM console commands `/gold <amount>`, `/levelup [n]`, `/sp <amount>`, and `/item <code> [count]` directly from chat bar.
   - Verified normal chat and all GM commands in `tests/test_social_flow.py`.
5. Quest Giveup & Fail Handling (Opcodes 2078 - 2081):
   - Reverse engineered `0x006223B0` (`QuestGiveupAck` / `QuestFailAck`).
   - Implemented wire serialization and domain handlers `on_2078` and `on_2080` in `quests.py`, removing active quests from character storage.
   - Verified in `tests/test_quest_flow.py` and `tests/test_wire_messages.py`.
6. Test Suite:
   - 54/54 unit and flow tests passing cleanly across all 11 test modules.


## Update — 2026-11-16 ~19:50 (Level-Up Progression, Store Economy & Guild Banking)

1. Level-Up & SP Progression on EXP Overflow:
   - Added `char_level_stats()` and `char_level_stat(char_class, level)` in `darkblood.games.game_data.client_dict`, parsing `UPExp`, `HealthPoint`, and `ManaPoint` from `charstat.lua` across all 7 character classes (`Warrior`, `Knight`, `Hunter`, `Mage`, `Thief`, `Fighter`, `WHunter`) with fallback formula.
   - Wired level-up loop into `on_2076` in `quests.py`: when EXP overflows `UPExp`, increments level, adds 3 SP per level, updates max HP and MP, and emits `5087 eERC_LEVEL_UP_NOT` and `5086 eERC_CHANGE_EXP_NOT`.
   - Verified in `tests/test_quest_flow.py` (character level increases to 2, SP is 3, remaining EXP is carried over).
2. Store Economy Transactions & Inventory Persistence:
   - Reverse engineered `0x0077E2F0` (`BuyItemAck`), `0x0077E8E0` (`SellItemAck`), and `0x0077EC30` (`RepurchaseItemAck`).
   - Wired `on_2067` (Buy): looks up item in store catalogs, deducts gold, generates and inserts item via `add_reward_items`, and persists state.
   - Wired `on_2069` (Sell): removes item count, adds earned gold, and persists state.
   - Wired `on_2071` (Repurchase): sends balance confirmation.
   - Verified in `tests/test_inventory_flow.py` and `tests/test_wire_messages.py`.
3. Guild Economy, Progression & Skill Reset Opcodes:
   - `2179 eEGS_GUILD_MONEY_IN_REQ` & `2180 eEGS_GUILD_MONEY_IN_ACK` (`0x00794250`): `<q` -> `<iq`. Deposits gold into guild bank and updates player balance.
   - `2181 eEGS_GUILD_MONEY_OUT_REQ` & `2182 eEGS_GUILD_MONEY_OUT_ACK` (`0x00794470`): `<q` -> `<iq`. Withdraws gold from guild bank and updates player balance.
   - `2183 eEGS_GUILD_LEVEL_UP_REQ` & `2184 eEGS_GUILD_LEVEL_UP_ACK` (`0x00753380`): empty -> `<ih`. Increments guild level.
   - `2185 eEGS_GUILD_NOTICE_MODIFY_REQ` & `2186 eEGS_GUILD_NOTICE_MODIFY_ACK` (`0x0075A120`): wide string -> `<i`. Updates guild notice.
   - `2188 eEGS_GUILD_NOTICE_DELETE_REQ` & `2189 eEGS_GUILD_NOTICE_DELETE_ACK` (`0x0074B830`): empty -> `<i`. Clears guild notice.
   - `2214 eEGS_GUILD_ALL_SKILL_INIT_REQ` & `2215 eEGS_GUILD_ALL_SKILL_INIT_ACK` (`0x00752D80`): empty -> `<ii`. Resets guild skills.
4. Test Suite:
   - 48/48 unit and flow tests passing across 11 test modules.
5. Roadmap Overhaul:
   - Updated `ROADMAP.md` with full milestones P0 through P9, complete categorized opcode roadmap (Combat, Dungeons, Inventory, Commerce, Quests, Guilds, Social, Post, Arena/PvP), live client graphics verification checklist, headless test matrix, modular refactoring roadmap, and future GM/Admin & Web dashboard tools.

## Update — 2026-11-16 ~19:30 (Milestone P1: Transport & Serialization Hardening, Roadmap Update)

1. Completed P1 Objectives:
   - Dedicated test suite `tests/test_transport.py` (11 tests) verifying ProudNet signed scalar boundaries (1, 2, 4, 8 bytes), invalid scalar widths, regression fixture for client first frame (`13 57 01 05 30 0F 00 00 40`), fragmented TCP delivery, coalesced TCP frames, and frame limits.
   - Implemented `JSerBufferReader` in `darkblood.core.serialization.jser` with bounds checking for all primitive integers, floats, UTF-16LE wide strings, and vectors.
   - Handled zlib compressed event payload unpacking with 4-byte uncompressed size header.
2. Updated `ROADMAP.md` checking off verified progress in P0, P1, P2, P3, P4, and P5.
3. Test suite expanded to 47 tests across 11 test categories, running in under 1.0 second.

## Update — 2026-11-16 ~19:15 (Guilds, Megaphone, Repairs, Upgrades, Bag Renaming, Contracts & Memos)

Decompiled client handlers/senders and added full support:
1. `2032 eEGS_CHANGE_BAG_NAME_REQ` -> `2033 eEGS_CHANGE_BAG_NAME_ACK` (`0x007528B0`): `<q` + wide string -> `<iq` + wide string. Persists custom bag tab names.
2. `2117 eEGS_UPDATE_SKILL_LOCKED_REQ` -> `2118 eEGS_UPDATE_SKILL_LOCKED_ACK` (`0x00752C70`): `<h?` -> `<ih?`. Persists locked skill set.
3. `2145 eEGS_DURABILITY_REPAIR_REQ` -> `2146 eEGS_DURABILITY_REPAIR_ACK` (`0x007930D0`): tag 0x17 map -> `<i` + `b'\x17\x80'` + `<q`. Updates gold and completes repairs.
4. `2115 eEGS_ITEM_UPGRADE_REQ` -> `2116 eEGS_ITEM_UPGRADE_ACK` (`0x007909C0`): `<qqq` -> `<i` (result=1 rejection).
5. `2086 eEGS_BUY_LIFE_WATER_REQ` -> `2087 eEGS_BUY_LIFE_WATER_ACK` (`0x0078FF90`): `<?` -> `<i?q`.
6. `2128 eEGS_USE_SPEAKER_ITEM_REQ` -> `2129 eEGS_USE_SPEAKER_ITEM_ACK` (`0x0077F320`): `<q` + wide string + `<q` -> `<iq` + `b'\x10\x80'`.
7. `5121 eERC_GUILD_CREATE_PROPOSAL_REQ` -> `5122 eERC_GUILD_CREATE_PROPOSAL_ACK` (`0x00759750`): wide string -> `<i`.
8. `2150 eEGS_GUILD_CREATE_REQ` -> `2151 eEGS_GUILD_CREATE_ACK` (`0x00793720`): wide string -> `<iq` + wide string + `<q`.
9. `2121 eEGS_CONTRACT_UPDATE_REQ` -> `2122 eEGS_CONTRACT_UPDATE_ACK` (`0x00752D80`): `<i` -> `<ii`.
10. `2143 eEGS_DURABILITY_CHANGE_REQ` -> `2144 eEGS_DURABILITY_CHANGE_ACK` (`0x00774AE0`): tag 0x17 map -> `<i` + `b'\x10\x80'`.
11. `2133 eEGS_FRIEND_LIST_UPDATE_REQ` -> `2134 eEGS_FRIEND_LIST_UPDATE_ACK` (`0x00752E80`): `<q` + wide string -> `<iq` + wide string.
12. `2155 eEGS_GUILD_PERSON_JOIN_REQ` -> `2156 eEGS_GUILD_PERSON_JOIN_ACK` (`0x0075A220`): `<q` -> `<i`.
13. `2160 eEGS_GUILD_INVITE_REQ` -> `2161 eEGS_GUILD_INVITE_ACK` (`0x00759870`): wide string -> `<i`.
14. `2162 eEGS_GUILD_PERSON_LEAVE_REQ` -> `2163 eEGS_GUILD_PERSON_LEAVE_ACK` (`0x00759CA0`): empty -> `<i`.

36/36 headless tests pass cleanly across all categories.

## Update — 2026-11-16 ~18:50 (Diagnostic Tooling, GitHub Issue Templates, Store & Social Opcodes)

1. Diagnostic Export Tool & Issue Templates:
   - Added `.github/ISSUE_TEMPLATE/bug_report.yml`, `.github/ISSUE_TEMPLATE/opcode_investigation.yml`, and `config.yml`.
   - Added `tools/export_diagnostics.py` producing `darkblood_diagnostics_<timestamp>.zip` containing OS, Git commit hash, client executable SHA256, recent wire logs, characters database, and opcode maps.
2. Store, Bag Property, Skill Shout & Friend List Opcodes Implemented:
   - `2048 eEGS_CHANGE_BAG_PROPERTY_REQ` -> `2049 eEGS_CHANGE_BAG_PROPERTY_ACK`: `<qB` -> `<iqB` updating tab filter `b28`.
   - `2053 eEGS_MODIFY_SKILL_SPEECH_REQ` -> `2054 eEGS_MODIFY_SKILL_SPEECH_ACK`: `<H` + wide string -> `<iH` + wide string. Persists to character `skill_speeches`.
   - `2055 eEGS_DELETE_SKILL_SPEECH_REQ` -> `2056 eEGS_DELETE_SKILL_SPEECH_ACK`: `<H` -> `<iH`. Deletes skill shout.
   - `2067 eEGS_BUY_ITEM_REQ` -> `2068 eEGS_BUY_ITEM_ACK`: `<iiH` -> `<i` (result=1 rejection).
   - `2069 eEGS_SELL_ITEM_REQ` -> `2070 eEGS_SELL_ITEM_ACK`: `<iqi` -> `<i` (result=1 rejection).
   - `2071 eEGS_REPURCHASE_ITEM_REQ` -> `2072 eEGS_REPURCHASE_ITEM_ACK`: `<q` -> `<i` (result=1 rejection).
   - `2139 eEGS_FRIEND_LIST_ADD_REQ` -> `2140 eEGS_FRIEND_LIST_ADD_ACK`: wide string -> `<i` (0xCE player offline).
   - `2135 eEGS_FRIEND_LIST_DELETE_REQ` -> `2136 eEGS_FRIEND_LIST_DELETE_ACK`: `<q` -> `<iq` (result=0, char_uid).
3. Test suite updated with 4 new tests covering all new messages and full end-to-end flows in `test_inventory_flow.py` and `test_social_flow.py`. 35/35 tests pass.

## Update — 2026-11-16 ~18:30 (Modular test suite refactoring into granular categories)

Decomposed monolithic `test_headless_flow.py` into dedicated, modular test suites:
1. `tests/test_wire_messages.py` (13 tests): Pure unit tests for opcode dataclass encode/decode (2014/2015, 2040/2041, 2030/2031, 2046/2047, 2050/2051, 2594/2595, 2024/2025, 5086, 5087, 5095, 2422, 2358, 5063, 5064, item count at +0).
2. `tests/test_character_store.py` (4 tests): Unit tests for `CharacterStore` CRUD, case-insensitive duplicate check, deletion, inventory & bag initialization.
3. `tests/test_hashing.py` (2 tests): Unit tests for djb2 `jhash` matching client `0x00B3AD70`.
4. `tests/test_lobby_flow.py` (2 tests): Server & channel lists, character creation & deletion, selection.
5. `tests/test_inventory_flow.py` (1 test): Item drag, use, discard, bag & quickslots, skill learn.
6. `tests/test_dungeon_flow.py` (1 test): Dungeon gates, layer transition, combat, death & rebirth coin, rank rewards, back to square.
7. `tests/test_quest_flow.py` (3 tests): Quest completion persistence, client dictionary rewards, active quest tracking in selection.
8. `tests/test_social_flow.py` (1 test): Post list, friends, invite list, web notices, NPC dialogue.
9. `tests/test_relay_flow.py` (1 test): Relay server connection and handshake isolation.
10. `tests/test_jpk.py` (5 tests): Archive structure, cipher inverse, rebuild verification.

Total 31/31 unit and integration tests passing cleanly.

## Update — 2026-11-16 ~18:15 (Skill training, character deletion, item discard, bag & quickslot switching, notices)

Decompiled client handlers/senders and added full support:
1. `2014 eEGS_DELETE_CHARACTER_REQ` (0x00780000.c:6618: i64 char_uid) -> `2015 eEGS_DELETE_CHARACTER_ACK` (0x00758370: i32 result + i64 char_uid + i32 complete_time=0). Added `CharacterStore.delete()` and handled in `on_2014`.
2. `2040 eEGS_DELETE_ITEM_REQ` (0x00550000.c:769: i64 item_uid + i32 amount) -> `2041 eEGS_DELETE_ITEM_ACK` (0x00557420: i32 result + i64 item_uid + i32 del_amount). Decrements or removes items from inventory and persists. Handled in `on_2040`.
3. `2030 eEGS_SWITCH_BAG_REQ` (0x00550000.c:626: u16 from_index + u16 to_index) -> `2031 eEGS_SWITCH_BAG_ACK` (0x00557680: i32 result + u16 from + u16 to). Swaps bags and persists. Handled in `on_2030`.
4. `2046 eEGS_SWITCH_QUCIKSLOT_REQ` (0x00780000.c:8591: u8 slot_type + u8 from_slot + u8 to_slot) -> `2047 eEGS_SWITCH_QUCIKSLOT_ACK` (0x0078C790: i32 result + u8 type + u8 from + u8 to). Handled in `on_2046`.
5. `2050 eEGS_LEARN_SKILL_REQ` (0x00780000.c:9504: u16 sKindNameIndex + u8 ucLevel) -> `2051 eEGS_LEARN_SKILL_ACK` (0x0078DBE0: i32 result + u16 sKindNameIndex + u8 ucLevel + i32 nRemainSP + i64 nRemainGold). Persists learned skills on character. Handled in `on_2050`.
6. `2594 eEGS_HTTPNOTICE_CHECK_REQ` -> `2595 eEGS_HTTPNOTICE_CHECK_ACK` (0x005A5110: i32 result + bool bWatch=False). Handled in `on_2594`.
7. `2216 eEGS_PLAY_OPTION_UPDATE_REQ` (0x00790000.c:3729: i64 char_uid + tag 0x1E struct). Fire-and-forget, handled in `on_2216`.
8. `2024 eEGS_GET_INVITELIST_REQ` (0x007A0000.c:7840) -> `2025 eEGS_GET_INVITELIST_ACK` (0x006A2E10: i32 result + tag 0x10 empty vector). Handled in `on_2024`.
9. `5087 eERC_LEVEL_UP_NOT` (0x0078CCF0): tag 0x1E + tag 0x0D (varuint 0) + i64 char_uid + u8 level + i32 hp + i32 mp + bool flag.
10. `5086 eERC_CHANGE_EXP_NOT` (0x0078D170): i32 nExpTotal + tag 0x1E jGainExp (8 x i32 + 1 x f32).
11. Updated `Item` model with `count: int = 1`, correctly packed at +0 offset.

17/17 headless tests pass.

## Update — 2026-11-16 ~17:45 (Dungeon clear reward, back-to-square, use item, equip & quickslot schemas implemented)

Decompiled client handlers/senders and added full support:
1. `5045 eERC_BACK_TO_SQUARE_REQ` (0x007A0000.c:8367) -> `5046 eERC_BACK_TO_SQUARE_ACK` (0x007897F0): returns character to town square with valid layer net ID. Handled in `on_5045`.
2. `5090 eERC_CHOICE_REWARD_PARTYRANK_REQ` (0x00780000.c:9280: i32 prefix + i32 card_index) -> `5091 eERC_CHOICE_REWARD_PARTYRANK_ACK` (0x0078D660: i32 result + i64 char_uid + tag `0x1E` 12-byte item reward + i32 box_type + i32 box_cost). Handled in `on_5090`.
3. `2038 eEGS_USE_ITEM_REQ` (0x00780000.c:8159: i64 item_uid + i32 use_count) -> `2039 eEGS_USE_ITEM_ACK` (0x0077D4C0: i32 result + tag `0x10` vector of updated items + i32 item_id + i32 use_count). Updates item count, persists, and notifies client. Handled in `on_2038`.
4. `2042 eEGS_EQUIP_ITEM_REQ` (0x00800000.c:500: i64 item_uid + i32 equip_slot) -> `2043 eEGS_EQUIP_ITEM_ACK` (0x007AE940: i32 result + tag `0x10` vector of equipped/unequipped Item structs). Swaps previous equipment to bag and equips new gear. Handled in `on_2042`.
5. `2044 eEGS_ASSIGN_QUICKSLOT_REQ` (0x00780000.c:8513: u8 ucType + u8 ucSlotNum + i32 nRefID + i64 nRefUID) -> `2045 eEGS_ASSIGN_QUICKSLOT_ACK` (0x0078C4A0: i32 result + echoes slot/ref data). Persists quickslots on character. Handled in `on_2044`.

16/16 headless tests pass.


Live play in Lucid Forest (`Act1_G1_A10`) confirmed active gameplay loop:
- Player interacted with new bag cells: emitted `2036 eEGS_DRAG_ITEM_REQ` (moving item 7 to container 2 slot 0) and `2028 eEGS_CLOSE_BAG_REQ` (closing container 2).
- Player engaged dungeon monsters, took fatal damage, and emitted `5093 eERC_GAMEPLAY_DIE_CHAR_REQ`.
- Rebirth modal triggered and player requested revival: `2448 eEGS_DAILY_REBIRTH_COIN_USE_REQ`.
- Periodic stat heartbeat observed: `2406 eEGS_CHAR_VERIFY_STAT_REQ`.

Decompiled client routines and implemented wire schemas:
1. `2036 eEGS_DRAG_ITEM_REQ` (0x00790000.c:4212): i64 item_uid + i64 to_container + i32 to_slot. Handled in `on_2036`: swaps or moves items, saves to store, and returns `2037 eEGS_DRAG_ITEM_ACK` (0x0077F570: i32 result + tag `0x10` vector of updated Item structs).
2. `2028 eEGS_CLOSE_BAG_REQ` (0x00550000.c:1773): i32 prefix + i64 bag_id. Client registers no ACK. Handled in `on_2028`.
3. `2406 eEGS_CHAR_VERIFY_STAT_REQ` -> `2407 eEGS_CHAR_VERIFY_STAT_ACK` (0x0074B830): i32 result 0. Handled in `on_2406`.
4. `5093 eERC_GAMEPLAY_DIE_CHAR_REQ` (0x00780000.c:10409): i64 from_char_uid + bool bDie + i32 damage + i32 cur_hp + i32 max_hp. Handled in `on_5093`: replies with `5094 eERC_GAMEPLAY_DIE_CHAR_ACK` (0x0078F090: i32 result + i64 from_uid + i64 to_uid + bool bDie + i32 damage + i32 cur_hp + i32 max_hp + u16 die_count + u16 sRebirthCoin=5).
5. `2448 eEGS_DAILY_REBIRTH_COIN_USE_REQ`: i32 prefix + u8 coin_type. Handled in `on_2448`: replies with `2449 eEGS_DAILY_REBIRTH_COIN_USE_ACK` (0x0079DC70: i32 result + u16 sDailyRecvCnt + i32 nPCBangCoinRemain=5) to revive the player via client function `0x00559310`.

16/16 headless tests pass.


Decompiled senders/handlers and recovered wire formats for dungeon & inventory flow:
1. 5095 eERC_CHANGE_DUNGEON_LAYER_NOT (0x007900B0): i32 0x7FFFFFFF + i64 layer_net_id
   where layer_net_id = (jhash(map_code) << 32) | layer_id. For Lucid Forest Entrance
   (Act1_G1_A10), jhash is 0x32ADCD46 and layer is 4 (wire: ffffff7f0400000046cdad32).
   Sent by JAppStateGamePlay::Initialize (0x006C0000.c:10234 via 0x0087D1F0). Handled in on_5095.
2. 2422 eEGS_ACTIVE_WARFLAG_REQ (0x0079C300): i32 0x7FFFFFFF + u32 war_flag_id (31).
   Client registers no 2423 ACK. Handled in on_2422.
3. 2358 eEGS_GUIDE_BEGINNER_UPDATE_REQ (0x0079A3B0): i32 0x7FFFFFFF + vector<u32> guide_ids.
   Handled in on_2358.
4. 5063 eERC_MONSTER_DEAD_REQ (0x0078A690): u32 monster_id + u32 param.
5. 5064 eERC_DROP_ITEM_NOT (0x0078A870): u32 source_id + vector (0x10) of 26-byte item drop
   structs (drop_uid, item_id, count, drop_type, 3x float coords, flags).
6. Bag cell display (0x00827D80, 0x005509F0, 0x00551310): In struct 0x00A1EC30:
   - bag_id must be a positive int64 (high dword < 0x80000000) for 0x00827D80 to accept it.
   - code must not be -1 (jhash('Ibaga0004')).
   - +0x28 (b28) is item tab filter (0 accepts any item type; 0xFF was blocking display).
   - +0x29 (b29) is cell capacity (BagSize = 5 for Ibaga0004; 0 displayed zero cells).
   - +0x2A (w2a) is UI slot index (0..4).
   Updated ensure_inventory with container 2 (Ibaga0004, 5 cells, UI slot 0).
16/16 headless tests pass.

## Update — 2026-11-16 ~13:50 (Cristian machine, dungeon render reproduced)

User clarified the earlier movement/attacks were their manual input, so do not
investigate spontaneous tutorial input. They authorized a new test. Pulled main
at e410c89, stopped the old owned server (client had already exited), ran the
13 passing headless tests, and started a fresh session with gamectl. Existing
Mage `lindic` (id 2) now has tutorial_cleared=true, persisted by the previous
manual session. Both characters remain present.

Locally verified: direct town entry; click movement; transitions Northern
Elwood Forest -> Elwood Center -> Elwood Village -> Western Forked Road ->
Entrance to Gnogue Haram. Then 2010/2011, 5001/5002 `_singleplay`,
5043/5044 `Act1_G1`, 5009/5010 `Act1_G1_A10`, 5013/5014: Lucid Forest
Entrance rendered successfully with the Mage and no logged exception/crash.
5095 (ffffff7f0400000046cdad32) remains unhandled. No monster was visible
in the initial viewport. Do not claim local dungeon movement/combat yet:
click movement, automated right arrow and X did not produce a visible action.
Requested a manual right-arrow/X test to distinguish input delivery from an
incomplete game state. UI automation is stopped pending that answer; leave
the client/server running for the manual check (owned processes are tracked in
logs/session.json, verify before stopping). Computer Use native pipe was
unavailable earlier in this conversation; gamectl is the fallback.

Screenshots (local): `research/test2-dungeon.png`,
`research/test2-dungeon-move.png`, `research/test2-action.png`;
latest traversal `research/test2-ui.png`. Wire log session starts at byte
2027398 (~13:41); new server runs e410c89. Next: manual control result,
then combat/drop/clear flow or input delivery debugging as supported by evidence.
## Update — 2026-11-16 ~16:00 (saita machine, MHServerEmu-style layout)

At the user's request the server moved from `server/` into the package
`src/darkblood` (see docs/ARCHITECTURE.md) ahead of a later C# port:
`core` (proudnet, crypto, jser, hashing), `frontend` (listeners, relay),
`player_management` (characters), `games` (session dispatcher, handler
mixins per domain, messages, entities, missions, game_data). Code was moved
verbatim (git mv where whole files moved); behaviour is unchanged: 15/15
headless tests and a live lobby/selection/relay run pass. Start with
`python run_server.py`; opcode tables are in `assets/`; the speculative
prototype is in `legacy/`. Collaborators with local edits to
server/game_wire.py or server/models.py must re-apply them in the new files.

## Update — 2026-11-16 ~15:00 (saita machine, quests/rewards/equipment)

See STATUS.md top. Fixed: active quest lost after relog, rewards ignored,
naked characters. Existing records get `bags`/`items` on next selection
(characters.ensure_inventory). Inventory window opens via the leftmost HUD
menu icon (click 0.468,0.955); the `i` key via gamectl did not work.
Open: bag cell display (try bag +0x28/+0x29 and the inventory page code from
Lua_UnequipBag 0x00552A90 / 0x00827D80), level-up, 5095, 2422, 2358.
User proposed an MHServerEmu-like layout ahead of a later C# port (not done).

## Update — 2026-11-16 ~13:30 (saita machine, dungeon entry live)

Dungeon entry works live (see STATUS.md top). Test route: gamectl
start / enter-lobby / select-character, click (0.66,0.80) x4, click (0.05,0.62)
x8 (follow the green arrows west into Gnogue Haram), wait for the gate map,
click Lucid Forest at (0.723,0.60). Added 5043->5044 and 5009->5010; 5014 now
echoes the map code. Next: 5095, 2422, monster kill flow, drops, dungeon
clear/return to town. Thief1 is naked (no inventory/equipment implemented).
2358 GUIDE_BEGINNER_UPDATE still unhandled. Session processes were stopped.

## Update — 2026-11-16 ~12:00 (Cristian live test)

The user authorized exclusive game control. Started the updated local server
and client using gamectl; selected existing Mage `lindic` (id 2), preserving
both existing characters. Live-verified on this machine: 2006/2007 selection,
relay handshake/JoinGroupACK, mailbox/friends/block-list replies, and the Mage
tutorial rendered at Library/Laboratory of Magician's Top. Client remained
connected and emitted 2353 monster-death notifications; no C++ exception or
access violation was logged. This is tutorial behavior, not dungeon entry.

Esc displayed the End tutorial dialog, but the attempted OK click and Enter
did not produce 2082. Character movement/attacks continued between inputs.
Asked whether the user was also controlling the game, and stopped further UI
input pending clarification. Do not assume skip succeeded. The skill's native
Computer Use pipe was unavailable; gamectl was the fallback. Its combined
physical/PostMessage input may need investigation if the user confirms no input.

Server/client are LEFT RUNNING (`logs/session.json` tracks owned processes;
verify current PIDs before touching them). Local captures: `research/resume-ui.png`
(latest tutorial combat), `research/resume-start.png`; wire/hook logs contain
the run from ~11:54. Additional static output `research/dungeon-flow.c` confirms
0x6E5C80 selects 0x78F950 (2082 sender) or 0x7AC380 based on app-page +0xC4;
the latter branch's behavior was not recovered. Next: settle exclusive control,
verify tutorial exit, reach town, then exercise room creation/start.

## Update — 2026-11-16 (Cristian resume, dungeon start serializer)

Pulled/rebased `origin main`: already at `cbcc82e`. Upstream already implements
2010/2011 room lists, 5001/5002 room creation, store dict loading, persistent
quest completion/history, and 2344/2345 waypoints. Do not reimplement these.
The older endpoint blocker below is historical and resolved.

Rebuilt and deployed the current Steam shim on this machine (the previous DLL
was from 03:01 and lacked newer fixes). Client executable SHA-256 still matches
the documented `a82ae3...c931`. No game process was running during deployment.

Fixed the old 5014 START_GAME_ACK serializer after focused Ghidra decompilation
and x86 assembly confirmation: untagged J-wstring, three maps, mandatory final
vector; all empty lengths terminate with 0x80. See PROTOCOL.md's dungeon start
correction. Full headless suite passes (13 tests). No live dungeon acceptance
claimed; field defaults remain provisional. Local evidence:
`research/dungeon-start.c`, `research/dungeon-start.log`, `research/session.bin`.

Exclusive game UI control was requested in this conversation; no answer yet.
No client launched or UI input sent. Next: live-test create room and start game,
then recover actual dungeon/map identifiers and the next observed requests.
Do not treat corrected framing as verified dungeon entry.

## Update — 2026-11-16 ~07:00 (sixth session, town gameplay live)

Live-verified with "Thief1": town entry, movement, map changes (5030 → 5031
now uses the 5046 layout; the old u8 0 made the client resend 5030 forever),
empty NPC store window (2065 → 2066), quest accepted and shown in the journal
(2073 → 2074, quest ids = jhash('Q0001S01')), quest completed without
rewards (2076 → 2077) and the next quest Q0002S01 started. Compressed client
events are inflated only when a zlib stream follows (2001/2203 set the flag
with plain bodies). Protector stubs resolved from an elevated live dump
(research/stub_names.tsv, 708 targets) and applied in Ghidra.

Open next: dungeon entry — 2010 GET_ROOMINFOLIST (→ 2011, handler
0x77A1F0), 5001 CREATE_ROOM "singleplay" (→ 5002, dispatcher 0x59D970), then
join room / P2P / monsters. Also: 2358 GUIDE_BEGINNER_UPDATE (→ 2359, receiver
not found), 2594/2595, 2216/2217, quest persistence and rewards, store items
from storelist.lua, skip with a fresh character (not yet retested).

## Update — 2026-11-16 06:12 (sixth session, live results)

Tutorial fix live-verified: "Thief1" entered SquarePlay. New shim with offline
ISteamUserStats fixed the follow-up crash at 0x0092CF06; ~2 min in town
without exceptions. Next: answer 5124, 2594, 2216, 2369, 2712, 2024 (schemas
not yet recovered), verify movement, test skip with a fresh character, and
dump protector stubs from an elevated prompt (the game requires admin).
Full Ghidra project: research/ghidra-full, pseudocode research/decompiled.

## Update — saitatter machine, 2026-11-16 ~06:00 (sixth session)

User report: "skip tutorial" restarted the tutorial. Cause found statically
(PROTOCOL.md §7): SquarePlay can-enter `0x006FA540` rejected
`nJoinLayerNetID` (2007 details `+0x5F` → player `+0xF0`) because we sent 0;
`JAppStateMgr` then timed out (5 s) and returned to Tutorial. Fix: details
`+0x5F = jhash("Act1") << 32 | 1`; 5046 `BACK_TO_SQUARE_ACK` now complete.
Headless tests: 11/11 pass. **Not yet live-tested**: the user's own client
(started 05:08) and server PID 43592 were still running, so nothing was
stopped. Next live test: restart the server with this code, select a
character (tutorial cleared or not), skip, and record the next requests the
town sends; also check for the "invalid layer netid" message box.

JPK correction: header byte `0x226` = encrypted flag; cipher covers whole
blobs of every entry. New tools: `tools/build_client_data.py` (private
workspace `../darkblood-client-data`, separate local Git repo — never push it
publicly), `tools/jpk_pack.py` (byte-identical rebuild, entry replacement),
`tools/luac51_dump.py` (Lua 5.1 constant listings). `research/all_extracted`
was produced with the old rule and is partly still encrypted.

## Update — saitatter machine, 2026-11-16 03:55

The "Unknown Internet address" blocker below is RESOLVED. The endpoint was the
square relay address filled by 5134 (`0x0075AAE0`), not the 18-byte `0x00A48A90`
block. The server sends 5134 = 127.0.0.1:9401 after 5029, and `run_bootstrap.py`
runs a handshake-only relay listener on 9401 with Relay PIDL JoinGroup/JoinGroupACK.
Town loaded and the NPC dialogue advanced with Space.
All subsequent opcodes (2131 friend list, 2569, 2082 clear tutorial -> 2083 town
transition, 2346 quest start -> 2347, 2390 roulette -> 2391, and notifications
2352/2353) have been decompiled, modeled with high-level dataclasses in
`server/models.py`, implemented in `server/game_wire.py`, and verified with
automated headless tests in `tests/test_headless_flow.py` (3/3 passing in ~0.6s).
Direct3D 9 multi-adapter fallback hook has been compiled into `client_hook/steam_api.dll`
and deployed to `research/client/steam_api.dll`. Server is running in background.

## Read this first

Goal: a reproducible, open-source local Dark Blood server. Offline gameplay is
NOT verified. Older status tables claiming world transitions are not a local
reproduction. Continue from the evidence below, rather than repeating setup.
Documentation stays in English; user communication is Romanian.

## User preferences and authorization

- Work autonomously on integration, reverse engineering, fixes and tests.
- Use local Ghidra and REA. Preserve collaborator changes and user data.
- Pull/rebase origin main every 10 minutes and push coherent verified work.
- Before ending a session, update roadmap/status/protocol/research notes and
  this handoff, then commit/push. User requested persistent written memory.
- Do not control the game simultaneously with the user. The user manually
  created a second character and opened a Delete character dialog during tests.
  Preserve both characters. Ask for an exclusive test window before UI input.
- User has little usage remaining and intends to resume tomorrow.

## Local environment (different from original author's saita paths)

Repo: C:/Users/cri99/Projects/darkblood-server-emulator
Original: research/supplied-client/Dark Blood/DarkBlood.exe
Test copy: research/client/DarkBlood.exe; Data is a junction to original assets.
Client SHA256: a82ae3d71b596418c1f3593cb63d3f9746318d452143c2e88f6ebbaff339c931
Archive: research/Dark Blood.7z, downloaded/decrypted from user-supplied MEGA.
Ghidra: C:/Users/cri99/Tools/ghidra_12.2_PUBLIC
JAVA_HOME: C:/Program Files/Eclipse Adoptium/jdk-25.0.5.8-hotspot
REA MCP 6.9.0 is connected and Ghidra decompilation has worked.
Python: research/venv/Scripts/python.exe (Python 3.10, pefile/capstone/py7zr).
Bare python is a Microsoft Store alias. py -3.10 and py -3.14 also exist.
MSVC: VS 2022 Community x86; client_hook/build.bat works.
PowerShell script execution is disabled; invoke Ghidra analyzeHeadless.bat
 directly instead of changing system execution policy. FocusedDecompile.java
accepts output path and VA seeds; use disposable projects and -noanalysis.
Computer Use sky native pipe was unavailable. gamectl is the tested fallback.
Its focus/screenshot can hang while the game main thread waits; bound tests.

## Work already published

b4af5cd: remove explicit 0x1E struct tags (client consumes only 0x0F..0x1A).
b0b16d7: add missing u8 at world-details +1CA (bool,u8,u16,bool,bool trailer).
a201b77: preserve -1 at details +A6/+AA; add empty mailbox 2219/2220 response.
59fa4f1: SteamUser slot 16 one-argument offline stub; former three-slot vtable
 caused an invalid indirect call at 0x786B28. Compiled ret 4 and live stub hit.
311ec56: remove duplicate 2007 result word. A1EA20(1) peeks/reset cursor;
 A40760 rereads the same result. Tester ACK is 636 bytes, not 640/651.
5d537ce: bounded first-chance C++ exception diagnostics after opcode 2007.
The diagnostic DLL has been deployed to research/client for the last test.
Four collaborator commits introducing models/world handlers were integrated.
No open PRs were found at the last check; the user uses PR to mean git pull.

## Latest concrete blocker (most important)

The final bounded test caught E06D7363 after selecting Tester:
- RTTI at throw info 0x00EE60CC identifies Proud::Exception (and std::exception).
- Candidate stack returns: 0x00B71DD4, 0x00B5533F, 0x00B7135A.
- Assembly at 0x00B55315 pushes error 14; B727E0(14) maps to English
  "Unknown Internet address." at 0x00D74140 (other languages also present).
- Function 0x00B54B40 validates connection parameters: address conversion must
  succeed and port must not be 0 or -1. This is the next investigation target.
- Many 2007 fields are still zero/defaults, including candidate endpoint blocks.
  Do NOT guess the endpoint layout or patch out the exception/timeout.
- Wrapper 0x00641E00 invokes reader 0x00A48A90 (not yet decompiled) for a
  candidate 18-byte nested block in the record. Recover it next; trace the
  actual connection parameters back to 2007 before changing the serializer.

Timeout mechanism: scene code 0x006F8960 sends 2006 and waits for 2007 at
0x006F8992 -> 0x0094E1F0. After 30000ms it calls 0x00757750(0), then
JUserClient::Shutdown 0x007869A0. Dispatcher 0x00787310 normally calls
0x009443A0 at 0x0078747F after handler return to complete the wait. The
exception is a plausible reason handler completion is skipped; verify causality.
Do not describe network heartbeats or successful deserialization as world entry.

## Local evidence to reuse

research/session.bin: mapped image; research/unpacked.analysis.exe: STATIC ONLY
fixture, never launch it. Original packed executable gives zeros at parser VAs.
research/client/hook_log.txt: last test's CXX record and candidate stack words.
research/proud-error.c: message mapping; research/next-address.c: B54B40.
research/last-selection-throw.c; research/endpoint-schema.c (641E00 wrapper).
research/main-wait.c; research/dispatch-wait.c; research/ack-wait-end.c.
research/select-character.c; research/select-fields.c; research/detail-defaults.c.
research/client/crash_image.bin: older crash image, NOT the last C++ object.
Focused decompiler signatures/stack labels are unreliable; confirm with capstone.
All game binaries, dumps, captures, generated DLLs and research remain ignored.

## Next session checklist

1. Pull/rebase main, inspect newer collaborator work, read relevant AGENTS/skills.
2. Recover A48A90 and actual endpoint argument layout used by B54B40.
3. Locate endpoint fields in 2007 and derive valid loopback endpoint encoding
   from the client; verify correct listener/connection route before testing.
4. Agree exclusive UI control, restart with built diagnostic shim, bounded test.
   Preserve data/characters.json; for isolation set DARKBLOOD_DATA in the SAME
   process environment that launches the server (it does not persist across tools).
5. Verify handler completes, wait is released, next requests and visible scene.
6. Commit tested fixes with evidence limitations; update this handoff at shutdown.

## Cleanup and background sync

Cristian resume update (2026-11-16): the user reported a recurring brief
PowerShell window. The sync task was a likely cause (10-minute interactive
PowerShell launches, despite `-WindowStyle Hidden`). Its action now uses local
`research/venv/Scripts/pythonw.exe` with `research/automation/sync_hidden.pyw`;
the wrapper invokes the unchanged sync script with `CREATE_NO_WINDOW` and
redirected standard streams. Original task XML is backed up locally at
`research/automation/task-before-hidden-launcher.xml`. The schedule is preserved.

Last owned client/server test processes were stopped. Verify fresh status before
starting; never reuse recorded PIDs. sample.txt enables bounded 5s sampling;
bp.txt has diagnostic breakpoints. Inspect these before another test.
Windows Task Scheduler task DarkBlood-RepoSync-10min fetches every 10 minutes;
clean, non-divergent main can pull/rebase/push. No automatic commits or force push.
Script/log: research/automation/sync.ps1 and sync.log. Runs while user logged in.
This task only syncs Git; it does not run autonomous game investigations.
A historical stash preserves the pre-model local tag patch; already ported and
published. Do not reapply it blindly. docs/LOCAL_SETUP.md remains local/untracked.
