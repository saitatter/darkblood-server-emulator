# Session handoff — 2026-11-22

## Random box result toast and subclass skill report — saita machine, 2026-11-22

- User reports that random boxes award their item (including a Max HP changing gem) while the client also displays "Please try again." The current `2038` handler sends a successful `2039` consume ACK and `2037` inventory delta but did not send the separate `2196 RandomboxResultItemNot` success notification.
- Added `2196` after the `2037` delta for successful random-box rolls, using the rolled item hash/count and the current default `is_jackpot = false`. The `2039` handler at `0x0077D4C0` routes nonzero result values through the localized error lookup; `2196` has its own success handler at `0x0075A2E0`. Analysis used `tools/decomp.ps1` on the derived static fixture only. Live confirmation is pending.
- User also reports that promotion does not grant new skills selected when choosing a subclass. The promotion Lua dialog selects the subclass branch; the `2076` completion body contains quest ID and reward index, with no skill IDs. Client `0x00797F00` applies the server's `2283` learned-skill map after resetting the tree. Current server behavior sends an empty map and refunds AP. Do not guess an auto-learn list; confirm the exact subclass and expected skill names, then trace the relevant selection path.
- Headless suite: 221/221 tests pass, including a check that `2196` reports the rolled item's signed hash and count after `2037`. The client was not launched; perform one bounded live box check and resolve the subclass skill expectation once the user identifies the class and skills.

## Dungeon rank calculation (`5017/5018`) & card reward table (`5090/5091`, Issue #15 item 8) — saita machine, 2026-11-22

- **Dungeon end rank always SSS (`5017 FinishGameReq` -> `5018 FinishGameAck`, `src/darkblood/games/handlers/dungeon/combat.py`)**:
  - Decompiled `JUserClient::FinishGameByHostREQ` (`0x007AD380`, assert `0x00D00E08`: `bVictory << mapPartyScoreList << mapPartyDPS << nTotalMosterHP << vecUnderling << nInner`).
  - Previously `handle_finish_game` misread the second map (`mapPartyDPS`, typically 200–300+) as a `0..100` rank percentage and mapped `>= 98` to `SSS` (6), forcing every clear to `SSS`.
  - Now parses `mapPartyScoreList` and `nTotalMosterHP` and applies the exact `dungeonrank.lua` (`DictMap:LoadDungeonRank`) thresholds (`D=0.0, C=0.1, B=0.225, A=0.375, S=0.625, SS=0.75, SSS=0.9`) plus `DictDungeonReward:LoadDungeonReward` `BoxGrade` (`D/C/B->0, A->1, S->2, SS->3, SSS->4`).
  - Recovered `SingleReward +0x14` (`bonus_exp`, shown in `bonusexplist` row 0 by `0x00711A30`) and `+0x18` (`final_total_exp`, written to `num_total` after the bonus animation by `0x00711910`; previously sent as `0`, causing final EXP to turn into `0`). Now computes rank clear bonus EXP from `DictDungeonReward:LoadDungeonReward` (`Exp_Reward` 6.5%–20%), grants it via `grant_exp`, and populates both fields.
- **End-of-dungeon card rewards always meat (`5090 -> 5091`, Issue #15 item 8)**:
  - Exported `DictMap:LoadItemPrize` (218 prize groups) and `DictMap:LoadRewardItemGroup` (34 dungeons, N/S/R/U difficulty weights) from `dungeonreward.lua` into `assets/dungeon_rewards.json` via `tools/export_assets.py` and `game_data/world.py::dungeon_rewards()`.
  - Implemented `loot.roll_dungeon_reward(map_code, char_class)` resolving explicit item groups (potions, reinforcing stones, materials) and level/grade/class equipment groups (`Weapon`/`Armor`/`Accessory` across Normal/Superior/Rare/Unique/Mythic) from `equip_index.tsv`, replacing the hardcoded `'Ihppa0001'` (Piece of Raw Meat) in `handle_choice_reward_party_rank`.
- **Removed custom server chat slash commands (`handlers/social/chat.py`, `docs/GM_COMMANDS.md`)**:
  - Removed custom `/gold`, `/levelup`, `/sp`, `/item`, and `/bags` interception from `handle_chat` (`5040`) now that the native client GM console (`Left Ctrl + Left Shift + C` or `%<command>` in chat) covers all 123 commands.
- **Random Box crash/disconnect (`src/darkblood/games/game_data/items.py`, Issue #15 items 2, 3, 7)**:
  - `random_boxes()` assumed each grade entry in `assets/random_boxes.json` was a dict (`g['prob'], g['groups']`), whereas `export_assets.py` exports 2-element lists `[prob, groups]`. Using any random box (Gem Random Box, Mage Rune Box, Card Booster Pack, etc.) raised `TypeError: list indices must be integers or slices, not str` inside `handle_use_item` (`2038`), immediately disconnecting the client. Fixed `random_boxes()` to unpack both `[prob, groups]` lists and dicts.
- **Book of AP `2109 InsertApNot` field order (`schemas/skills.jsch`, `0x00790480`)**:
  - `On_eEGS_INSERT_AP_NOT` (`0x00790480`) reads `total_ap` (`player+0x88`) first and `current_ap` (`player+0x8C`, remaining AP) second, printing `first - old_total_ap` in chat. Previously the two fields were swapped in `schemas/skills.jsch`, causing Book of AP (`Ispaa0001`) to print a negative delta in chat and display `remaining AP` / `total AP` inverted in the skill window. Swapped to `total_ap`, `current_ap`.
- **Verification**: 221/221 headless tests pass (`test_dungeon_rank_uses_score_ratio_and_card_rewards_roll_from_table`), `gen_messages.py --check`, `gen_progress.py --check`, and `gen_opcode_registry.py --check` pass. Live client retest pending.

## Class promotion quests & `2283 PromotionNot` (Issue #16) — saita machine, 2026-11-22

- **Client analysis (`0x00797F00` `On_eEGS_PROMOTION_NOT`, `0x0080BA60`, `0x00AC7130`)**:
  - Recovered `2283 PromotionNot` assert `0x00CFBE70` (`ucJob >> iMarginAp >> mapLearnSkill`) and mapped its trailing map in `schemas/system.jsch` as `map<u16,LearnedSkill> skills` (reader `0x004ACB80`).
  - Verified `0x00797F00` updates `player+0x64` and `unit+0x29` to `ucJob`, calls `0x0080BA60(1, iMarginAp, &mapLearnSkill)` to reset/apply learned skills and refresh the Skill Tree UI, and prints `GAME_241` ("Class has been changed") + `UI_1060` ("A skill has been initialized (AP : %d -> %d)").
  - Verified promoted subclass IDs from `0x00AC7130` and `skilltree.lua` `Demand1Class`: `0x10..0x16` and `0x50..0x56` (low nibble = base class `0..6`). Notably, in `quest_promotion.lua` and `quest_event.lua`, Hunter (`2`) and WHunter (`6`) have `PromotionType = 0` -> Trickster (`0x52`/`0x56`) and `PromotionType = 1` -> Shooter (`0x12`/`0x16`), whereas the other 5 base classes map `0 -> 0x10|base` and `1 -> 0x50|base`.
- **Server & assets (`assets/quest_promotions.tsv`, `tools/export_assets.py`, `game_data/quests.py`, `handlers/quests.py`)**:
  - Exported all 22 final class-promotion quests (`PromotionLv = 0`, 14 standard `QMA*` + 8 jumping `Q12*` quests) to `assets/quest_promotions.tsv` and added `quest_promotion_class()` / `quest_promotion_classes()`.
  - Updated `handle_quest_complete` (`2076`) to promote `char['char_class']`, reset `skills`/`locked_skills`/`skill_show_cooltime`, refund `sp` to `total_ap(char)`, persist via `save_char()`, and send `2283 PromotionNot`.
  - Added all 14 promoted subclass values to `CharacterClass` (`entities/character.py`) and masked `char_class & 0x0F` in `char_level_stat()` (`game_data/progression.py`), `_criteria_item()` (`loot.py`), and friend search (`handlers/social/friends.py`).
- **Verification**: 220/220 headless tests pass (`test_class_promotion_quest_promotes_character_and_sends_2283` in `tests/test_quest_flow.py`), `gen_messages.py --check`, `gen_progress.py --check`, and `gen_opcode_registry.py --check` pass. Live client retest pending.

## Project-wide audit refactors, performance & hygiene — saita machine, 2026-11-21

- **Performance & Persistence (`src/darkblood/core/network/crypto.py`, `player_management/store.py`, `frontend/server.py`, `frontend/relay.py`)**:
  - Precomputed GF(2^8) lookup tables (`_MUL2`..`_MUL14`) and fused ShiftRows/SubBytes in pure-Python `AES` (verified against FIPS-197 Appendix B KAT). Full headless suite runtime dropped from ~8.0s to ~3.0s.
  - Switched `SqliteCharacterStore` to a persistent connection (WAL + `busy_timeout=5000`, `close()` / context manager / `weakref.finalize`), added indexed `get_by_id()` / `get_by_name()` and atomic `save_chars()`, and replaced linear `all_characters()` scans in `social/` and `mail.py` plus single-character `store().save()` calls across handlers and `GameSession.tick_timers()` with `save_char()`.
  - Moved `BootstrapServer.record()` JSON serialization and disk writes off the asyncio loop onto a bounded daemon queue (`maxsize=4096`, `record_drops` counter, flushed on `close_log()`).
  - Added relay backpressure guard (`MAX_RELAY_WRITE_BUFFER = 256 KiB`) in `RelayGroups.forward()` for unreliable `0x16 -> 0x1A` traffic.
- **Architecture & Layering (`handlers/social/`, `handlers/dungeon/`, `handlers/commerce/`, `core/network/proudnet.py`)**:
  - Split mega-handlers into responsibility-focused mixin packages matching `handlers/inventory/`: `handlers/social/` (`friends.py`, `chat.py`, `party.py`, `guild.py`), `handlers/dungeon/` (`rooms.py`, `combat.py`, `events.py`), and `handlers/commerce/` (`stores.py`, `cash_shop.py`, `trade.py`, `stalls.py`).
  - Eliminated downward-layering violations: moved `RELAY_PORT`/`relay_address` and `SQUARE_UID_*`/`square_uid` to `core/network/proudnet.py`, injected `square_resolver` into `RelayGroups`, and injected `timer_refresher` into `SqliteCharacterStore` from `GameSession.store()`.
  - Stopped broadcasting invented `5021`/`5022` on town join/leave (preventing `5022` collision with real `eERC_CHANGE_ROOMHOST_ACK`); town presence uses `5027`/`5096` and `5039` (`LeaveLayerNot`).
- **Client Hook & CI/Tests (`client_hook/patches/network_redirect.c`, `tools/gen_opcode_registry.py`, `.github/workflows/ci.yml`)**:
  - Replaced non-thread-safe `inet_ntoa()` in `RedirectSockAddr` with direct byte formatting (`FormatIpv4`); rebuilt `steam_api.dll` cleanly with MSVC x86.
  - Added `--check` to `tools/gen_opcode_registry.py`, added `gen_progress.py --check` to CI, added `*.log` to `.gitignore`, and updated `docs/ARCHITECTURE.md` and `ROADMAP.md`.
  - Added `tests/test_architecture.py` (layering rules, FIPS-197 AES KAT, indexed lookups / `save_chars`) and `tests/test_fuzz_and_load.py` (varuint/scalar/frame fuzzing, pre-auth packet resilience, and 10 simultaneous headless clients).

## Live 2-client social, party, inspect & stress fixes — saita machine, 2026-11-21

- **Chat & Whisper (`5040 ChatReq` / `5041 ChatAck`, `schemas/social.jsch`, `src/darkblood/games/handlers/social.py`)**:
  - Removed the bogus extra `u8 _ = 0x0A` byte before `0x00A52BD0` (`bool` + 2 vectors) in `5041 ChatAck`, which shifted every `5041` by +1 byte and caused `0x007AC890` to drop all chat/whisper messages.
  - Swapped `target` (`+0x01`) and `sender` (`+0x1D`) in both `5040 ChatReq` and `5041 ChatAck` per `0x00544310` (`+0x1D` is sender, `+0x01` is target), fixing missing sender names in normal chat and reversed `"Whisper to"` on recipients.
  - Mapped `server_key = 31` (`+0x76`, checked by `0x007AC890`) and `sender_square_uid = 0x07C0000000000001` (`+0x7A`, checked by `0x00544310`), removing the `"(Other server)"` suffix on whispers. **Live-confirmed.**
- **GameOption defaults in `2007 SelectCharacterAck` (`src/darkblood/games/entities/character.py`)**:
  - `Character.encode_world_details()` previously sent 24 zero bytes at `+0x84` (`0x00A488F0`), which `0x00470D10` copied into `0x00F2DA28 +0xBE..+0xD5`, disabling `+0xBE` (`AllowPartyInvite`), `+0xCB` (`AllowTrade/Guild`), and `+0xCC` (`AllowWhisper`). Replaced with client constructor `0x0045FD50` defaults (`1,1,1,1,1,0,1,1,0,0,1,1,1,1,1, 0.5f, 0.5f, 0`). **Live-confirmed**: party invites now appear on the target client.
- **Party Invite, Promotion & Inspect (`5050`, `5051`, `5054`, `5022`, `6011/6012`)**:
  - `5050 PartyInviteAck` (`0x00758700`) has no `result == 0` guard and unconditionally prints `FUN_00ab29c0(result)` (`"This is an unknown message"` for `0`); now sent only on errors (`res != 0`). **Live-confirmed.**
  - `5051 PartyInviteNot`: packed `inviter_square_uid` with `square_uid(...)`, mapped `+0x31` as `i16 inviter_stress = 0` (was `0xFFFF` = `-1`, showing `"-1/330"`).
  - `5054 PartyAcceptInviteReq`: when the host has no `DungeonRoom` yet, auto-creates a party room (`5002` + `5004` + `5035`). `PartyManager` now dissolves stale 1-member solo parties from unaccepted outgoing invites so Community tab invites succeed.
  - `5005 LeaveRoomReq` (`src/darkblood/games/handlers/dungeon.py`): when the party leader leaves with remaining members, keeps the room alive, promotes `peers[0]` to `room.host`, and sends `5022 eERC_CHANGE_ROOMHOST_ACK` (`0x00599630`: `i32 result`, `i64 nChangeNewHostUID`).
  - `6011/6018 -> 6012 RequestCharInfoAck` (`0x00790FA0`): recovered full struct (`result`, `bool is_other`, `Character`, `vector<Item>`, 2 vectors, `0x00A50B80` PvP stats, trailing vector) and wired real character + equipped items.
- **Friend Memo & Online Flag (`2132`, `2133/2134`)**:
  - Fixed `2134 FriendListUpdateAck` (`0x00752E80`) to encode `comment` as J-wstring (`wstr`) instead of `wstrz`, persisted `friend_memos` per character, and mapped `FriendEntry.memo` (`+0x2E`) and `FriendEntry.is_online` (`+0x52`, from `Lua_OnUpdateFriendList` `0x00500000.c:2026`).
- **Stress (Fatigue) System (`src/darkblood/games/progression.py`, `character.py`, `dungeon.py`, `square.py`, `frontend.py`, `gm.py`)**:
  - Fixed `Character.encode_world_details()` `+0x4D/+0x7C/+0x7E/+0x80` (`<IQIhhhh`: `total_ap`, `stress`, `stress_week`, `stress_pcb`, `daily_post_send`; previously `u6e` was in `+0x4D` and `total_ap` overflowed into `+0x7C stress`).
  - Implemented dungeon stress consumption (`+2` on `5013 StartGameReq` and each newly visited room on `5095 ChangeDungeonLayerNot`, clamped to `0..330`), passive town/offline recovery (`1` per minute on `2006`, `5030`, `5045`), daily midnight reset, persistent GM cheat `2130`, and `2023 StressChangedNot` broadcasts.
- **Verification**: 200/200 headless tests pass (`test_stress_consumption_and_recovery` added), `gen_messages.py --check` and `gen_progress.py --check` pass. Live check of stress, 6012 View Info, 5022 host promotion, and 2134 memo pending.

## Native GM Console & Cheats sweep — saita machine, 2026-11-21

- **GM Mode Option (`src/darkblood/core/options.py`, `src/darkblood/games/handlers/frontend.py`)**:
  - Added `[server] gm_mode` option (default `True`), setting `nAuthLevel = 1` in `5020 WelcomeNot` so the client's native GM console (`JAppPageCheat`, `0x004EF790`) is unlocked out of the box.
- **GM Cheat Opcodes (`schemas/gm.jsch`, `src/darkblood/games/handlers/gm.py`, `src/darkblood/games/session.py`)**:
  - Recovered and implemented all live `eEGS_CHEAT_*` / `eERC_CHEAT_*` opcodes (`2057–2064`, `2088/2089`, `2093`, `2096/2097`, `2099`, `2101`, `2103`, `2105`, `2107/2108`, `2123–2125`, `2130`, `2137/2138`, `2141/2142`, `2170/2171`, `2194/2195`, `2197–2200`, `2212/2213`, `2232/2233`, `2238/2239`, `2488–2491`, `2512`, `2514`, `2522`, `2624/2625`, `2627`, `2660/2661`, `2687–2692`, `5117`, `5129`, `5252`, `5262/5263`), with server-side effects for level-up, AR/AP/coins, itemcall, clearbag, upgrade, quality, promotion, stress, quests, guild, pet, card, explore, broker, and achievements.
- **GM Command Documentation (`docs/GM_COMMANDS.md`)**:
  - Extracted and documented all **123 native GM console commands** from `JAppPageCheat` (`0x00CA0000..0x00CA3200`) and `cheat_st.dat` (syntax, parameters, and wire opcodes), plus the server's chat slash commands.
- **Verification**: 199/199 headless tests pass (`tests/test_gm_flow.py`), `gen_messages.py --check` and `gen_progress.py --check` pass.

## Arena room, square, team, random matching & league charstat sweep — saita machine, 2026-11-21

- **Arena (`schemas/arena.jsch`, `src/darkblood/games/handlers/arena.py`)**: recovered and implemented 34 Arena opcodes from `JAppPageArena` (`0x004C6110`), `JAppPageArenaLeague` (`0x0049D180`), and `JAppStateArenaSquare` (`0x006A9F70`):
  - Arena Square & Layers: `5140 ArenaLeaveSquareAck`, `5141 ArenaLeaveLayerNot`, `5142/5143 ArenaJoinLayer`, `5144 ArenaJoinLayerNot`.
  - Arena Room lifecycle: `5150 ArenaLeaveRoomNot`, `5163/5164 ArenaBanishUser`, `5168/5169 ArenaChangeRoomHost`, `5172/5173 ArenaStartGame`, `5182/5183 ArenaReadyGame`, `5226 ArenaSelectSubCharAck`, `5265/5266 ArenaChangeRoomCharInfo`, `5267/5268 ArenaChangeSlotCharInfo`.
  - Arena Teams & Random Matching: `2472 ArenaRandomMatchingUserCntNot`, `5202/5203 ArenaRandomMatchingRequest`, `5220 ArenaRandomMatchingInitAck`, `5276 ArenaTeamLeaveNot`, `5282/5283 ArenaTeamBanish`, `5286/5287 ArenaTeamChangeHost`, `5301/5302 ArenaChangeTeamInfo`.
  - League Season CharStats: `2556/2557 LeagueSeasonArenaCharStatUpdate`, `2561/2562 LeagueSeasonArenaCharStatInit`.
- **Verification**: 196/196 headless tests pass (`test_extended_arena_room_team_and_league_opcodes`), `gen_messages.py --check` and `gen_progress.py --check` pass.

## Monster Card, Roulette, Cronos, Explore & Clear Rank sweep — saita machine, 2026-11-21

- **Monster Card (`schemas/pets.jsch`, `src/darkblood/games/handlers/pets.py`)**: recovered all 23 Monster Card & Card Lotto opcodes from `JAppPageMonsterCard` (`0x0060B500`), including `MonsterCardInfo` (`0x00A52DB0`) and `MonsterCardLottoEntry` (`0x00A51C20`), and wired `2604`, `2606`, `2610`, `2613`, `2615`, `2633`, `2636`, `2638`. Pets reached **72/74 (97%)**.
- **Commerce (`schemas/commerce.jsch`, `src/darkblood/games/handlers/commerce.py`)**: recovered and wired Roulette (`2386-2389`, `0x0063FB10`), Storage Share (`2530/2531`, `0x00655350`), `2463 DepotSlotExtendExpireNot`, and Cash Paint (`2622/2623`, `0x005E6BA0`). Commerce reached **56/59 (95%)**.
- **Dungeon (`schemas/dungeon.jsch`, `src/darkblood/games/handlers/dungeon.py`)**: recovered and wired Cronos attendance (`2289-2300`, `0x004EE850`), Explore (`2651-2657`, `2662/2663`, `0x00546490`), and Clear Rank (`2539/2540`, `5228/5229`, `0x0051B740`, `DungeonClearRankInfo` `0x00A51AC0`).
- **Verification**: 195/195 headless tests pass (`test_monster_card_roulette_cronos_explore_clear_rank`), `gen_messages.py --check` and `gen_progress.py --check` pass.

## Lobby, Dungeon & Arena live opcode sweep — saita machine, 2026-11-21

- **Lobby (`schemas/lobby.jsch`, `src/darkblood/games/handlers/frontend.py`)**: recovered and implemented `2323/2324 CharNickChangeByIntegrate`, `2404/2405 EventDeleteCharacter`, `2441/2442 CharSlotExtend`, `5128 ImpliedJoinLayerReq` (delegates to `handle_join_layer`), plus schema definitions for `5033 LeaveSquareAck`, `5038 LeaveLayerAck`, `5039 LeaveLayerNot`.
- **Dungeon (`schemas/dungeon.jsch`, `src/darkblood/games/handlers/dungeon.py`)**: recovered and implemented `5052/5053 AgainSelectDungeon` (also confirming `setMinCitadelHistory` in gate replies), `5236/5237 TrainingJoinRoom`, `5238/5239 TrainingLeaveRoom`, `5240/5241 MonsterRegen`, `5342/5343 TreasureFind`, plus 18 live dungeon/buff/daily-count notices (`2110`, `2288`, `2301`, `2318`, `2418`, `2419`, `2421`, `2443`, `2517-2521`, `2585`, `2641`, `2704`, `5136`, `5222`, `5326`).
- **Arena (`schemas/arena.jsch`, `src/darkblood/games/handlers/arena.py`)**: recovered and implemented GBB Rock-Paper-Scissors minigame (`2715-2720`) plus `2537/2538 LeagueSeasonChar/GuildAwardNot` and `5135 ArenaSquareChangeRelayAddressNot`.
- **Verification**: 194/194 headless tests pass (`test_extended_lobby_dungeon_and_arena_opcodes`), `gen_messages.py --check` and `gen_progress.py --check` pass. Total progress crossed 50% overall (646/1098 opcodes = 59%, 87% fields). Live client retest pending.

## Fishing, System, Inventory, Stalls, Commerce & Pets sweep — saita machine, 2026-11-21

- **Fishing (`schemas/fishing.jsch`, `src/darkblood/games/handlers/square.py`)**: recovered and implemented all 9 fishing opcodes (`2523/2524 FishingStart`, `2525/2526 FishingStop`, `2527 FishingResultNot`, `2528 FishingFailedNot`, `2529 FishingProficiencyNot`, `2541 FishingLicenseChangeNot`, `2542 FishingLicenseExpireNot`). Fishing jumped from 0% to **100% (9/9 opcodes, 100% fields)**.
- **System (`schemas/system.jsch`)**: recovered all 4 remaining system notices (`2020 CloseConnectionNot`, `2023 StressChangedNot`, `2582 ChangeMainSpiritNot`, `2626 IndulgenceNot`), bringing System to **100% (36/36 opcodes)**.
- **Inventory (`tools/gen_progress.py`)**: marked internal router opcodes `6005-6008` (`eERT_USER_LOGIN/LOGOUT`) as `UNUSED_IN_CLIENT` (no client senders/handlers), bringing Inventory to **100% (90/90 opcodes)**.
- **Stalls (`schemas/stalls.jsch`, `src/darkblood/games/handlers/commerce.py`)**: recovered and implemented `2398 BrokerChangeRegistCountNot`, `2586/2587 SaleByBulkOption` (`map<i16, bool>`), and `2588/2589 SaleByBulkRegist` (`vector<i32>`).
- **Commerce (`schemas/commerce.jsch`, `src/darkblood/games/handlers/commerce.py`)**: recovered and implemented `2243 DepotShareExpireTimeGetAck`, `2400 DepotShareExpireTimeAddNot`, `2401 DepotSizeIncreaseNot`, `2416/2417 BeautyShopCare` (`BeautyShopInfo` `0x00A49EF0`/`0x00A49F30`), `2590/2591 SellItemAll`, `2711 VipServiceInfoNot` (`0x00A4AC80`), `2721/2722 SteamBuyPackage`, `5085 CancelAcceptTradeNot`, `6010 TradeResultNot`.
- **Pets (`schemas/pets.jsch`, `src/darkblood/games/handlers/pets.py`)**: recovered and implemented all 18 live missing pet/riding opcodes (`2436 RidingChangeListNot`, `2479 PetConsumeSatietyNot`, `2482/2483 PetEatCash`, `2492-2495 PetCashFoodEquip/Unequip`, `2498/2499 PetExtendDepot`, `2500/2501 PetSwitchStorage`, `2502 PetDepotExtendExpireNot`, `2516 PetDyeingNot`, `2646/2647 RidingExpireUpdate`, `5323 PetLevelUpNot`, `5324 PetChangeExpNot`).
- **Verification**: 193/193 headless tests pass (`test_extended_fishing_commerce_stalls_and_pets`), `gen_messages.py --check` and `gen_progress.py --check` pass. Live client retest pending.

## Mail, Social, Party & Guild domain sweep — saita machine, 2026-11-21

- **Mail (`schemas/mail.jsch`, `src/darkblood/games/handlers/mail.py`, `src/darkblood/player_management/store.py`)**:
  - Recovered and implemented all 5 remaining mail opcodes from `unpacked.analysis.exe`: `2248/2249 PostGetAppendAr` (`0x00796700` / `0x007967E0`, asserts `nPostUID >> nCurrentAr`, updates player `+0x70`), `2252/2253 PostSave` (`0x007969D0` / `0x0075A780`, extends mail `remain_days=90`), and `2399 PostDailySendRecoverNot` (`0x0079A880`, writes `player+0x32C`/`+0x32E`).
  - Mail reached **100% (18/18 opcodes, 54/54 fields)**.
- **Social (`schemas/social.jsch`, `src/darkblood/games/handlers/social.py`)**:
  - Recovered and implemented all live missing social opcodes: `2120 AlarmUpdateAck` (`0x00771150`), `2354/2355 ChatNotify` (`0x004E6D30` / `0x00A1EDD0`), `2565-2568` & `2571-2572 FriendBlockList` (`Add`/`Delete`/`Update`, `FriendBlockEntry` `0x00A4A1A0`, persisted per character in `blocked_friends`), `2693/2694 WatchEventSeen`, `5007/5008 BanishUser` (`0x005975D0` / `0x005999A0`, room host kicks member and broadcasts `5008`), and `6018 RequestCharInfoByNickReq` (`0x00790E10` -> `6012`).
  - Social jumped from 35% (26/53) to **60% (40/53 opcodes, 80% fields)**.
- **Party / Teaching / Guide (`schemas/party.jsch`, `src/darkblood/games/handlers/social.py`)**:
  - Recovered and implemented 18 opcodes: `2356/2357 GuideWaitlistUpdate`, `2359 GuideBeginnerUpdateAck`, `2360/2361 GuideDonelistUpdate`, `2648/2649 TeachingStressReward`, `2650 TeachingGetHistoryNot` (`TeachingHistoryEntry` `0x00A4AF60`), `2658/2659 TeachingGraduationReward`, `5130/5131 SummonAcknowledge`, `5356/5357 TeachingSummonAccept`, `6030/6031 TeachingDelete`, `6032/6033 TeachingSummonRequest`.
  - Party jumped from 23% (7/26) to **88% (25/26 opcodes, 91% fields)**.
- **Guild (`schemas/guild.jsch`, `src/darkblood/games/handlers/social.py`)**:
  - Recovered and implemented 51 opcodes + `GuildSkillEntry` (`0x00A48890`, also resolving `2205 GuildSkillNot`'s unmapped vector): `2159 GuildHistoryNot`, `2166-2169` & `2172 GuildFallout`, `2173/2174 GuildGradeDelegation`, `2175/2176` & `6017 GuildPersonExpulsion`, `2187 GuildViewedNoticeNot`, `2190-2193 GuildDismissal`, `2206-2209` & `5127 GuildSkill`, `2218` & `6019 RefuseGuildInvite`, `5123 GuildCreateCompleteNot`, `6015/6016 GuildInvite` (live-forwarded from `2160`), `2674/2675 GuildPersonIntroduction`, `2677 GuildMissionNot`, `2678-2683 GuildBroker`, `2684-2686 GuildSupply`, `2426/2427 GuildPersonArenaGradeModify`, `2450-2456 GuildSiege` (`Officer` / `TeamIdx` / `UpdateSiegeInfo`), `2599/2600` & `2631` & `2676 Citadel`.
  - Guild jumped from 28% (30/98) to **81% (81/98 opcodes, 98% fields)**.
- **Verification**: 192/192 headless tests pass (`test_mail_claim_ar_and_save`, `test_extended_social_party_guild_opcodes`), `gen_messages.py --check` and `gen_progress.py --check` pass. Live client retest pending.

## Storage / Depot & NPC Shop Buy Crash fixes — saita machine, 2026-11-21

- **NPC Shop Buy Crash (`2067 -> 2068`, `schemas/commerce.jsch`, `src/darkblood/games/handlers/commerce.py`)**:
  - Recovered `On_eEGS_BUY_ITEM_ACK` (`0x0077E2F0`, assert `0x00CF5D40`): `jModifyGoods >> nNPCID >> nCurAr >> vecItem >> nItemID >> sItemNum >> nCurPvPPoint >> nCurLeaguePoint`.
  - Previously `nItemID` (`u32_2`) was sent as `0`, causing `FUN_009e5440(0)` to return NULL and crash on dereference (`*puVar6`).
  - `on_2067` now checks free bag space (`results.INVEN_FULL = 67`) before deducting AR, populates `store_record` (`StoreRecord`), `npc_id`, `gold`, `items`, `item_id = jhash(item_code)`, `item_num = count`, `pvp_point`, and `league_point`.
- **Storage / Depot (`2007`, `2036/2037`, `2228/2229`, `2230/2231`, `2461/2462`)**:
  - Recovered `SelectCharacterAck` (`2007`) map `0x00A40720` -> `0x00A40590` -> `0x00A40380` (`DepotInfo`) and `0x00A1EBF0` (`DepotSlotInfo`), loaded into `JDepotMgr` (`0x00942EE0`). Previously sent empty (`17 80`), leaving `Page_Storage` on its XML placeholder (`"3,000,000 Ar"`) with all 3 slot groups locked.
  - `build_select_char_ack` now populates `depots` for all characters on the account, each with 2 `DepotSlotInfo` entries (required by `0x00936990` which indexes `slots[0..1]` without bounds checking; group 1 = slots `0..19` is always unlocked).
  - Recovered `0x009411A0` (`2037 DragItemAck` depot apply): items with `container == 2` (`DEPOT_CONTAINER`) are stored in `JDepotMgr` keyed by `item.owner == depot_char_uid`. `JAppPageStorage::OnDragItem` (`0x00650D00`) sends `2036 DragItemReq` with `to_container = pjDepot->m_nCharUID`. Updated `handle_drag_item` (`items.py`) to move/swap items between bags and depots and emit `owner = depot_char_uid` for `container == 2`.
  - Fixed `2228 DepotSaveArReq` (`0x007950A0`) and `2230 DepotLoadArReq` (`0x00795160`) field order (`depot_uid` first, `gold` second) and populated `map<i64,i64> depot_ar` (`mapCurDepotAr`, `0x00765610 -> 0x0074D640`) in `2229`/`2231` ACKs alongside remaining player gold (`nCurAr`). Updated `2461 -> 2462` (`handle_depot_slot_extend`) to return non-zero remaining seconds (`30 * 86400`).
  - **Handler decorator migration**: migrated all remaining 11 modules (`session.py`, `frontend.py`, `square.py`, `arena.py`, `quests.py`, `mail.py`, `skills.py`, `pets.py`, `commerce.py`, `dungeon.py`, `social.py`) from `on_XXXX` methods/aliases to `@packet_handler(...)` + descriptive `handle_*` names (216/216 registered handlers, 0 `on_*` remaining) and regenerated `docs/OPCODE_REGISTRY.md`.
  - **Skills domain sweep (`schemas/skills.jsch`, `src/darkblood/games/handlers/skills.py`)**: recovered all 9 live missing skills opcodes (`2152 SkillUpdateShowCoolTimeReq`, `2302/2303 ReadjustQuality`, `2384/2385 InitProficiency`, `2577 DualSkillExpireNot`, `2578 DualSkillActiveNot`, `2579/2580 DualSkillChangeIndex`) plus both previously unmapped fields (`LearnedSkill.show_cooltime` from `0x00952BD0`, `2280 InitSkillNot.skills` `map<u16,LearnedSkill>`). Moved `QuickSlot` struct to `schemas/skills.jsch` to avoid circular imports with `lobby.py`. Skills progress jumped from 54% (14/25) to 88% (23/25; only `2052` and `2153` remain, neither having handlers in this client build).
  - **Quests domain sweep (`schemas/quests.jsch`, `src/darkblood/games/handlers/quests.py`)**: recovered and implemented all live missing quests/NPC Kairo/Seal opcodes (`2090/2091 QuestDiscard`, `2098 QuestAlimiChangeNot` quest tracker persistence, `2126/2127 GetQuestTag`, `2177/2178 ActKairo`, `2496/2497 NpcMakingKairo`, `2728/2729 NpcSealItem`, `5382/5383 QuestItemDrop`), added schema definitions for already-handled opcodes (`2073`, `2076`, `2082`, `2094`, `2113/2114`, `2344/2345`, `2346`, `2353`, `2445`, `2447`), and mapped 19 of 20 unmapped fields (`QuestSpecialInfo` `0x00A48A90`, `KairoResult` `0x00A55AD0`, `vector<Item>`, and `2077.skills` `map<u16,LearnedSkill>`). Quests progress jumped from 25% (19/43, 57% fields) to 83% (36/43, 99% fields).
  - Verification: 190/190 headless tests pass, `gen_messages.py --check` and `gen_progress.py --check` pass. Live client retest pending.

## Live 2-client co-op dungeon bugfixes — saita machine, 2026-11-21

- **Party Rank & User Rank (`schemas/dungeon.jsch`, `src/darkblood/games/handlers/dungeon.py`)**:
  - Recovered `SingleReward +0x24` from `0x0071F9F0` / `0x00720000:530` (`Lua_OnChecked_5`): it is the per-player individual `rank` (`0=D, 1=C, 2=B, 3=A, 4=S, 5=SS, 6=SSS`), not `extra_box_price`. Previously it was always `0` (`D`) while `FinishGameAck.rank_first/rank_final` sent `1` (`C`), making Party Rank always 1 grade higher than User Rank.
  - `on_5017` now decodes the optional `5017 FinishGameReq` score and rank-point maps, computes each member's `SingleReward.rank` on the `0..6` scale, and sets `rank_first = rank_final = round(avg(member_ranks))` (matching `user_rank` identically in solo runs).
- **Random Looting bag-full fallback (`src/darkblood/games/handlers/dungeon.py`)**:
  - In `on_5065` when `room.loot_mode == 0` (Random Looting), filter party members with free bag slots before `random.choice` so one member having a full bag no longer blocks other members from looting drops.
- **Party dungeon end timer / back to square (`src/darkblood/games/handlers/square.py`)**:
  - In a party dungeon, only the host sends `5045 BackToSquareReq` when the result timer expires or the gate is closed. `handle_back_to_square` now also sends `5046 BackToSquareAck` (with each member's own square/layer/gold) to every other member in the room while keeping the party intact.
- **Durability loss & repair (`schemas/inventory.jsch`, `src/darkblood/games/handlers/commerce.py`, `src/darkblood/games/handlers/inventory/crafting.py`)**:
  - Decoded `map<i64,f32>` in `2143 DurabilityChangeReq`, `2145 DurabilityRepairReq`, and `2154 DurabilityRepairByItemReq` (plus `i64 repair_item_uid`).
  - `on_2143` persists updated item durability (clamped to `[0, max_dur]`) and reports broken (`<= 0`) item UIDs in `2144 DurabilityChangeAck`.
  - `handle_durability_repair` (`2145 -> 2146`) restores items to max durability, charges AR proportional to missing durability, persists changes, and returns `repaired_items` + `remain_gold`. `handle_durability_repair_by_item` (`2154 -> 2146`) restores durability without AR cost and consumes 1 repair kit item.

## Typed wire serialization & project audit refactors — saita machine, 2026-11-21

- **Typed wire serialization (`src/darkblood/core/serialization/wire.py`, `tools/gen_messages.py`)**:
  - Added `WireMessage` + `JSerBufferWriter` and nominal wire types (`i8..u64`, `h32`, `f32`, `f64`, `bool`, `wstr`, `wstrz`, `wrest`, `ipv4`, `rest`, `Raw[N]`, `Vector[T]`, `Set[T]`, `Map[K, V]`, `Array[T]`, `Pairs[T]`, `Extern[...]`, `Const`, `Lit`, `Computed`).
  - Updated `PythonBackend` in `tools/gen_messages.py` to emit declarative typed `WireMessage` dataclasses with a single `from darkblood.core.serialization.wire import *` line and **0** `struct.pack`/`struct.unpack` calls across all 15 `messages/*.py` modules (verified 0 diffs against a 434-class byte-for-byte snapshot).
  - Migrated `Item`, `Bag` (`entities/items.py`) and `ActiveQuest` (`missions/quests.py`) onto declarative `WireMessage` layouts.
  - Split `handlers/inventory.py` into `handlers/inventory/` (`bags.py`, `items.py`, `crafting.py`, `depot.py`, `__init__.py`) using `self.reply()` and `self.save_char()`.
- **Server & persistence cleanups**:
  - Removed duplicate zlib decompression in `src/darkblood/games/session.py` (`jser.parse_event` already handles it).
  - Added `BaseDomainService.reply()` and `send_msg()` helpers in `src/darkblood/games/handlers/base.py`.
  - Enabled SQLite WAL mode (`PRAGMA journal_mode=WAL`, `synchronous=NORMAL`), removed the duplicate `CREATE TABLE mailbox` block, and added single-character `SqliteCharacterStore.save_char(account, char_id)` in `src/darkblood/player_management/store.py`.
  - Switched `BootstrapServer.record()` in `src/darkblood/frontend/server.py` to a persistent line-buffered log handle (`close_log()` on shutdown).
- **Client hook isolation (`client_hook/patches/network_redirect.c`)**:
  - Added `WSAConnect` inline hook alongside `connect` (sharing `RedirectSockAddr` and the verified `8B FF 55 8B EC` prologue check); rebuilt and deployed `research/client/steam_api.dll`.
- **Verification**: 190/190 headless tests pass (`tests/test_wire_typing.py` added), `gen_messages.py --check` and `gen_progress.py --check` pass.

## Inventory domain sweep (31 opcodes + 6 unmapped fields) — saita machine, 2026-11-21

- Recovered 6 previously unmapped fields in `schemas/inventory.jsch` from client readers/asserts:
  - `ItemDropEntry`: `u16 quality` (`+8`, `0x008842C0` -> `0x009E5560`) and `set<i64> owner_uids` (`+0xE`, `0x006B9200` / `0x00A4C7A0` loot rights).
  - `2146 DurabilityRepairAck` (`0x007930D0`): `map<i64,f32> repaired_items` (`0x00763A50` -> `0x0074D5B0`).
  - `2144 DurabilityChangeAck` (`0x00774AE0`): `vector<i64> changed_item_uids` (`0x004AFD30`).
  - `2364 AvatarZamEraseReq` (`0x007A47F0`): `h32 zam_item_id` (assert `nTargetItemUID << nZamItemID`).
  - `2092 InventoryUpdatedNot` (`0x0077F070`): `vector<AddedItemNotice> added_notices` (`0x0076E900` -> `0x00AC82A0`, 12 bytes) and `vector<Item> items` (`0x004B9210`).
- Recovered schemas for all 31 live missing inventory opcodes from `unpacked.analysis.exe` (the remaining 8 in `opcodes.tsv` — `2034/2035`, `2382/2383`, `2705..2708` — have no senders or handlers in this client build):
  - Bags & notices: `2029 CloseBagAck`, `2593 BagChangeSellEnableAck`, `2287 NotEnoughInvenSpaceNot`, `2620 MarkItemActiveNot`, `2621 MarkTabActiveNot`, `2703 DecreaseUsageLimitNot`.
  - Requests & ACKs (wired in `src/darkblood/games/handlers/inventory.py` + `on_2028` now replies with `2029`): `2147/2148 SealItem`, `2154 DurabilityRepairByItemReq`, `2408/2409 AvatarZamMerge`, `2428/2429 UseSelectedSkillChangeItem`, `2432/2433 AvatarMerge`, `2543/2544 AvatarChanger`, `2545/2546 ItemDecompose`, `2547/2548 RandomOptionChange`, `2573/2574 UseItemLeaguePointAdd`, `2583/2584 RareAvatarChangeLook`, `2597/2598 AvatarZamSeparate`, `2629/2630 ItemClassSmelting`, `2701/2702 MarkOptionChange`.
- Regenerated `messages/inventory.py`, `README.md`, `docs/UNMAPPED_FIELDS.md`, and `docs/OPCODE_REGISTRY.md`. All 186 headless tests pass (`test_extended_inventory_opcodes_and_recovered_fields`). Live client check pending.

## Custom launcher and modular client hook — saita machine, 2026-11-21

- **Modular client hook (`client_hook/`)**: split `steam_api_hook.c` into shared core (`common.h`/`common.c`, Steam API exports + VEH dispatcher in `steam_api_hook.c`) and one file per patch/hook under `client_hook/patches/`:
  - `network_redirect.c`: IPv4 `connect()` redirect reading `[network] host`, `port`, and `relay_port` from `darkblood_options.ini` (resolves hostnames, falls back to `127.0.0.1`, maps port `9400 -> port` and `9401 -> relay_port`).
  - `borderless_fullscreen.c` (`[client] borderless_fullscreen`, default 1, still honours `exclusive_fullscreen.txt`).
  - `auto_reconnect.c` (`[client] auto_reconnect`, default 1; includes the two post-reconnect VEH recovery sites).
  - `peer_update_interval.c` (`[client] peer_update_interval`, default 1; `0x00966C9C` 2000 ms -> 100 ms).
  - `skip_logos.c` (`[client] skip_logos`, default 0).
  - `skip_tutorial_always.c` (`[client] skip_tutorial_always`, default 0).
  - `diagnostic_hooks.c` (`[client] diagnostic_hooks`, default 1; `TraceWelcome`, `TraceJoin`/`handler_map.txt`, `TraceUserMessage`, C++ selection throw log).
  - `debug_tools.c` (`[client] debug_tools`, default 1; `bp.txt` INT3 tracer and `sample.txt` thread sampler).
- Built and verified with MSVC x86 (`client_hook/build.bat`, all 57 Steam exports intact) and deployed to `research/client/steam_api.dll`. Live client launch check pending.
- **Custom launcher (`tools/launcher.py`, `Launch_DarkBlood.bat`, `src/darkblood/core/options.py`)**:
  - Configures server IP/host, game port, relay port (`[network]`), account and client count (`[launcher]`), and toggles all client/server patches grouped by Improvements, Hacks, Server Behaviour, and Diagnostics (showing each patch's source file).
  - Includes TCP connection probe, local server start/stop button, one-click hook DLL rebuild & deploy, and direct 1–4 client launch (with multibox mutex release).
  - Bifrost-inspired dark UI with two tabs (`NEWS & SERVER` and `PATCHES & HACKS`), scrollable repository commit news feed (local `git log` with GitHub API fallback and clickable commit links), always-visible bottom `PLAY` bar, and runtime extraction of the `DarkBlood.exe` client icon (`RT_GROUP_ICON`) for both the window taskbar and header banner.
  - `tools/patcher.py` now delegates to `tools/launcher.py`. `steam_api_hook.c` also reads `[launcher] account` when `DARKBLOOD_ACCOUNT` is unset.
  - 185 headless tests pass (`tests/test_options.py` expanded for network/launcher round-trip, validation, and patch metadata).

## Docs cleanup and progress CI — saita machine, 2026-11-20 (late)

- ROADMAP.md now lists only open work; implemented items and the per-feature logs in STATUS.md and this file
  were removed (Git history keeps them). The README names the supported client (SHA-256 `a82ae3d7...`).
- `tools/gen_progress.py` builds the README "Progress by system" table (opcode coverage x named-field share per `schemas/*.jsch`
  domain) and `docs/UNMAPPED_FIELDS.md`. CI regenerates both on every push to `main` and commits them as
  `docs(readme): update per-domain progress [skip ci]`. Since 2026-11-21 `main` is protected by the
  ruleset "main protection" (PR with 1 approval, no force push, no deletion; bypass: admins and deploy
  keys); the classic branch protection was removed. GitHub Actions cannot be a bypass actor on a
  personal repo, so the job pushes with the write deploy key `ci-progress` (secret `PROGRESS_DEPLOY_KEY`).
- Next targets: see ROADMAP.md "Open work" (town movement desync, shared dungeon instances) and the largest
  unmapped groups (lobby 72, dungeon 43, social 24).
## Live two-client playtest — saita machine, 2026-11-20 (evening)

Data reset at the start (`data/darkblood.db` removed; backup in the session
scratchpad). Two multibox clients (`OfflinePlayer`/Knight1, `Player2`/Warrior1),
user testing by hand, server log monitored. 181 headless tests pass.

Fixed this session (live-confirmed only where stated):
- **5094 revive position**: the client's read assert names the fields
  `nFromCharUID >> nToCharUID >> bDie >> nLayerID >> nX >> nY >>
  sCurPartyRebirthLimit`; the request assert is `GamePlayDieCharREQ(netID, bDie,
  m_nLayerID, (int)pos.x, (int)pos.y)`. The server sent HP values as nX/nY. Now
  echoed. Live check pending.
- **Town layer (`nJoinLayerNetID` low dword)**: it is the town layer (zone).
  `0x008EC230` (SquarePlay entry) reads it via `0x005DDD10` (returns the low
  dword) and picks the start-point dood of that layer (`0x008B59F0`), or the
  layer waypoint after GamePlay (`0x0098BE00`); state 9 (Tutorial) uses the
  start point. The server always sent 1. Act1 layers seen in 5030: 0, 2, 5, 7.
  Default is now 0 (assumed main town, unconfirmed: the user expects to spawn
  next to the first quest giver after the tutorial), 5030 stores the layer,
  2007/5046 send it. Live check pending.
- **Peer layer in 5096**: details `+0x5F` carried the stored default layer, so
  after a 5030 the peer's JUser reported another layer. Now the presence layer.
- **Floor gold**: the 5064 entry count (amount, `0x004C8CA0`) was always 1; the
  AR is now rolled at drop time and awarded unchanged by 5114.
- **Relay group leave**: the departing member now also gets 0xF61E for every
  remaining peer before its own. Hypothesis (stale P2P entry and keys after a
  layer change); live result not isolated.
- **Room finder 2010 -> 2011**: was always empty. Element = jRoomInfo
  (`0x00580B40` -> `0x00A49380`). Layout: id, name, i16 max users (+0x2C),
  i16 current users (+0x2E), i32 state (+0x30: 1/2 -> status layer 2, 8 -> 1,
  else "FULL"), i64 host, i64 ?, i32 gate, i32 map, i16 diff. The row prints
  UI_625 with +0x2E / +0x2C. The last 2011 field is shown plus one (last page
  index). 5001 skips the 0x7FFFFFFF prefix. **Live-confirmed**: the room
  appeared in the other client's Find party list (before the layout fix).
- **"(Offline)"/"(Other server)" name suffix**: `0x007E9896` adds "(server)"
  unless `0x0087DBB0` finds equal keys (bits 54-58, `0x00A614A0`) in the
  peer's and the own JUser `+0x100`. That field is a **square UID**: the peer's
  comes from the last field of its 5027 entry (`0x00944510`); the own one is
  all ones until the first layer change (live breakpoint at `0x0087DBF8`, key
  31) and then the `nJoinSquareUID` of 5031, which `0x00787A70` writes to
  `+0x100` (live: it became 1, and peers showed "(Other server)"). The server
  now sends square UIDs as `0x1F << 54 | square` in 5027, 5031 and 5046, and
  the relay masks bits 54+ when grouping by square. The 2007 struct `+0x207`
  field is not involved (two attempts there were reverted). Live check pending.
- **Peer spawn timing**: live, a 5027 sent 1 ms after 2006 was never shown, one
  at +0.9 s (after 2219, before the relay JoinGroup) was shown, and one after
  5124 (+10 s, after JoinGroup) was not shown. A player is now `loading` from
  2006 and is announced both ways at 2131 (~2 s after 2006, just before
  JoinGroup); 5124 is a fallback. **Live-confirmed**: both players saw each
  other after this change.

Open, observed live:
- **Town movement desync and latency** (next target). Positions drift, worst
  with click-to-move on the world map (no 5030 involved). Each client sends a
  relay `0x16` every ~216 ms (shim patch `peer_update_interval`, 2000 -> 100 ms
  at `0x00966C9C`), plus ~35 reliable `0x15` per minute; the relay drops
  nothing and forwards at once. Plan: the server generates the P2P AES/Fast keys
  (0xF619), so add a diagnostic relay decoder that logs the inner message type
  per sender (position revision 0x4D in the 0x53 bundle vs move commands), then
  compare a map click with what the peer renders.
- 5060 eERC_ROOM_MEM_INFO_REQ (Find party member view) and 5088
  eERC_CHANGE_ITEM_OBTAIN_REQ (party looting mode button) are unhandled.
- The IME button next to the name in character creation is a Korean/English
  input toggle (`g_jAP_CreateChar:OnToggleIME()`), not a name check; names are
  validated by 2012 (result codes 14-17).
- Tooling: `multibox.py tile` has no borderless mode by choice; fullscreen is
  already borderless through the shim (`exclusive_fullscreen.txt` opts out).

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

## Party invite target field — 2026-11-21
- Live: 5049 body is `[header][i64 target square UID = key31|square id][bool][i64 target char id]`.
  The server used the first i64 (square UID, masked to the square id 1) as the target, so a
  Knight1 -> Warrior1 invite targeted char 1 and failed with result 1 ("Unavailable
  character", `JERI_NO_EXIST_CHAR`). `PartyInviteReq` now decodes the last i64 as `target_uid`.
- Decline: no refuse opcode for party exists in `assets/opcodes.tsv` (only duel 5112 and guild
  2218/6019) and no packet reached the server after clicking it. The popup handler 0x007706E0
  was not traced further. Pending invitations are therefore never cleared on decline.

## Party name edit, looting buttons, popup findings — 2026-11-21
- 5011 (party name edit) was unhandled and the client froze waiting for 5012 (u32 result +
  RoomInfo, handler 0x00584160). Now answered; only the room host may rename.
- 5088 looting buttons (one bool) were unhandled. 5089 ack is one bool (handler 0x00588B50) and is
  also sent to the other members. What true/false mean (random vs free) is unverified; the value is
  stored in `DungeonRoom.loot_mode` only, there is no drop-distribution logic yet.
- **Follow-up (same day, live report)**: Party info OK did not propagate and the looting
  checkbox snapped back. 5011 is a whole jRoomInfo (caller 0x0063BB53: max users from control 2,
  gate/map/diff, which the host's client writes into its own room first); live bodies showed the
  map changing (0xCD450996 -> 0xCD4509D8) and diff 0. The server now stores max users (clamped to
  members..4), gate, map and diff, and sends 5012 to every member. The 5012 handler copies only
  max users (+0x2C) and the title into the member's room (0x0058432D), and the room dispatcher
  0x0059D970 handles only 5002/5004/5006/5008/5012/5022/5035/5036/5048/5089, so no recovered
  message updates the dungeon for members already in the room (later joiners get it via 5004).
  Looting: the checkbox handler 0x0054F86C sends 1 when the box was unchecked; 5089 stores
  (v != 1) at +0xB4 and 0x0054F910 checks control 4 when +0xB4 == 1, so the echo unchecked it.
  The ack now sends the inverse and only the host may change it. Headless-tested; live pending.
- **Reconnect crash (live 2026-11-21)**: after a server restart, the client that still saw the
  other player crashed at 0x0076F98D right after `ChangeState(eAS_Lobby)`. 0x007850F0 walks the
  user manager's category-4 map (manager +0x9C, getter 0x00965A80) and calls 0x0076F900 for every
  non-local JUser; the stale peer's model lookup returns NULL. The shim now removes remote users
  with the client's own 5039 path (0x009662E0, i64 uid) before resetting the local UID
  (`ForgetRemoteUsers`). The other client had already died at 0x0059C161 in an earlier run; the
  `[RECOVER]` world-map skip for that site is committed with it. Built, not yet live-tested.
- **Max users always 4 (open)**: the user picked 2 and 3 and 5011 still carried 4. The caller reads
  control 2 with 0x00AF54C0 = selected item's `_combo_value` (0x00AD6710); the fill loop at
  0x0063BD5C labels items 2..4 via code outside the dump (0x600F7E10). `research/client/bp.txt`
  now traces the index (0x00AF54C8) and the value (0x0063BA77) for the next live check.
- **Invite accept (static, 2026-11-21)**: `JAppPageRequestList::OnBtn_Party_Accept` (0x0063A600). On the
  room host (0x00966EA0) it calls `AcceptJoinRoomREQ(nSquareUID, nCharUID)` = 5049, which answers a 5048
  join request with an invite. On the invitee it refuses with `JERI_ALREADY_JOIN_CHAR` while GameRoom
  +0xAC is set, else `JoinRoomREQ(nInviteRoomUID, nHostSquareUID, nHostCharUID)` (0x0058B430): 5003 for
  a room UID > 0, otherwise 5054. nInviteRoomUID is 5051 +0x90, which the server sent as 0. 5051 now
  carries the inviter's room (UID, name, gate, map, diff), and 5054 joins the host's room through the 5003
  path (5004 + 5035) instead of the invented PartyManager reply (5055/5056 have no client handler).
  The 5051 handler only runs in `eAS_Square`. Live 2026-11-21: after the 5051, no 5054 reached the server;
  the client-side reason is not established yet.
- **Quest dungeons**: 86 maps have a QuestLink. 34 are copies of the regular map at their Difficult (same
  file, monsters and stats; only MapID, PlayOrder, QuestLink and Money differ, e.g. Act1_G1_A16 = A10);
  `assets/dungeon_maps.tsv` column `same_as` names that map. Their clear counts as the regular map in the
  5044 history. The other 52 have their own content (own `.map`, HP/stats, PartyMember, level: Act1_G1_A15 is
  level 35-37 though Difficult 2) and do not advance difficulty. The gate (0x006D1120) keeps slots 0-3 for the
  difficulties (+0xA0) and 4-29 for quest maps (+0xB0) and auto-selects a quest slot whose QuestLink hash is
  in the 5044 quest set, so the client shows quest maps as their own choice. The copy quests' missions are
  kills (type 0), quest items (type 1, Iquea*), type 3 = clear that exact quest MapID, type 2/5. Room map hashes (5001/5011) are DungeonID hashes (Act1_G1_A1 =
  0xCD450996), not MapIDs.
- **Live trace 2026-11-21 (bp.txt)**: (1) Capacity works: an earlier run stored `max 2`; this run the combo
  (0x00AF54C8) was on index 2 = "4", preselected as `max - 2`. (2) Loot: 5089 starts with
  `0x00A1EA20(0)`, which reads an **i32 result** (returns -1 when the read fails, error path otherwise),
  so the bool-only ack never reached 0x0054F910. 5089 is now `i32 result, bool`. A second trace showed the control flips itself before 0x0054F86C reads it, so an inverse ack made every click send 1; the ack now echoes the mode. Check other handlers
  that start with 0x00A1EA20(0) for the same missing result. (3) Join request: the host's Accept ran
  the host branch (0x0063A695 eax=1) and sent 5049; the requester got 5051 but its
  `OnBtn_Party_Accept` never ran. A 5049 for a pending 5047 requester now joins it directly (5004 on
  the 5047 correlation, 5035 to the room); whether the requester's client accepts that 5004 outside
  the GameRoom page is unverified.
- **Find user (2024 -> 2025)**: the request is low/high level, page, job (7 = eCK_Max), layer, square;
  2025 is `i32 result, vector<RoomMemberInfo>`. The server sent an empty list; now online players.
- **Live 2026-11-21 (later)**: Find user, join request and the looting button work. 5045 (back to square)
  left the room, so a leader closing the dungeon gate sent 5036 for the host and the member saw "all
  members left the party"; 5045 now ends only the `_singleplay` room. The looting mode is stored in
  `DungeonRoom.loot_mode` only: drops (5064/5114) are still per player, as dungeons are not shared yet.
  The leader's dungeon gate took 10+ s of black screen; the server answered 5043 at once and nothing was
  pending, so the wait is client-side. Both clients send 5024 (`P2P_DIRECT_CONNECT_RESULT_NOT`: bool +
  peer char id) after joining a room; it is unhandled. `sample.txt` now takes the sampling interval in
  ms (shim) to profile that wait.
- **Party gate barrier (sampler, 2026-11-21)**: after 5044 the leader's main thread sat 15 s in
  `0x005C6D40(2, 15000)`, called by `0x006C7920` (state Enter, loading page 0x31): it sends P2P 0x5F
  (`0x005C51A0` -> `0x00954810(0x5F, own uid)`) and polls `0x005C4FB0(2)` until every other user with
  flag 2, `+0x2C0 == -1`, `+0x2BA == 0` has `+0x138` set, which the P2P handler `0x009695F0` does on a
  peer's 0x5F (`0x005C4E40(uid)`). Only the leader entered the gate, so it always timed out. 5044's
  handler (`0x007702E0`, global) changes the state itself, so the server now sends 5044 to every
  room member when the host opens the gate, and forwards the host's 5010. Not yet confirmed live;
  Leaving the gate (5045) is still per player. Shared dungeon step 1: the host's 5013 also sends its 5014
  (same map) to the room members in the gate. Live: both clients loaded the map and stayed linked through
  the room relay group (kind 2); the member fought (2143). Only the host's client sent 5063 kills, 5017 and
  5095, so EXP, drops and the result reached only the host. Step 2: the room shares the run (`room.started`,
  same map code): every member gets each kill's EXP/score/quest kills (deduplicated by monster id +
  instance), drops are rolled once into a room pool and 5064 goes to all, the first picker wins (5068 to
  all; 5114 result 0 to the picker and nonzero to the others, because `0x00792700` adds the AR to the local
  player only for result 0, after removing the drop), and the host's 5017 sends 5018 with every member's
  reward entry to all. Looting modes: `0x00584460` prints UI_1468 "Random looting" for +0xB4 != 0 and
  UI_1467 "Free for all" otherwise, so 5088/5089 mode 0 = random, 1 = free for all (fresh page default).
  Random: a pickup goes to a random run member (item or AR). 5004 `bFreeItemObtain` now carries the mode.
  Chat: 5040 was only echoed; 5041 now reaches the square (channel 1), the named player (2 = whisper) or
  the party room (other channels, values not recovered; `chat-route` records them).
  The quest-item check after a pickup never ran (`hasattr` on the wrong object); fixed.
- **Reconnect from town, two clients (open)**: with the 0x0076F98D and 0x0059C161 recoveries both
  clients get past the lobby and character select, then stop on a modal error box ("오류") from
  `JAppStateSquarePlay::LoadMap` (0x006F9920, MessageBox call 0x006F9C00): the local user's square UID
  (`0x00946540` +0xF0) -> square (`0x00984D20`) -> map (`0x00990030`, name +0x20) -> `0x008EC9E0` returns
  false. The world-map lookup `0x008BE570` returning NULL earlier points the same way: map state from
  the lost session is not reset. The 2026-11-17 reconnect (one client, world) did not hit this.
  Until it is fixed, restart the clients instead of reconnecting after a server restart.
- Party decline = `Lua_OnBtn_Refuse` -> `JAppPageRequestList::RemoveElt` (local only, no packet).
- Open: accepting a party invite showed "this is an unknown message" and the client sent 5060/5047
  with room UID 1 (not 5054); 5051 room UID fields still need decoding.
- Shim logs are per account now (`hook_log.<account>.txt`) to debug the relogin client exit.
