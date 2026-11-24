# Session handoff — 2026-11-24

> Older per-session logs (2026-11-16 through 2026-11-21) were pruned to keep this handoff concise; they remain in Git history and their results are reflected in `README.md`, `docs/STATUS.md`, `docs/OPCODE_REGISTRY.md`, and `ROADMAP.md`.

## Recent verified changes (2026-11-22 – 2026-11-24)

- **Codebase refactoring & modularization (2026-11-24)**:
  - Removed duplicate handler definitions (`DungeonRoom` across `dungeon/*`, `store_record` / `MONSTER_CARD_ACKS` across `commerce/*`) and cleaned up 300+ unused top-level imports across `src/darkblood/`.
  - Unified shared GM mutations in `src/darkblood/games/gm_commands.py` (used by both `handlers/gm.py` and `gm_bridge.py`, decomposing `execute_gm_command` into a dispatch table and fixing Rune Slate unlock drift on `lv 30+` via the launcher GM bridge).
  - Replaced all remaining whole-store `store.save()` calls in `dungeon/combat.py` and `games/stalls.py` with targeted `save_char()` / atomic `save_chars()` and indexed `get_by_id()` lookups; added regression guardrails in `tests/test_architecture.py`.
  - Modularized `dungeon/combat.py` into `dungeon/{entry,combat,rewards}.py`, split `handlers/pets.py` into `handlers/pets/{pets,mounts,cards}.py`, extracted `PartyManager` into `src/darkblood/games/party.py` (re-exported from `world.py`), decomposed `handle_drag_item` / `handle_use_item` in `handlers/inventory/items.py`, and extracted non-UI launcher logic into `tools/launcher_app/{theme,changelog,client_ops,widgets}.py`.
  - Uniformized 141 typed `self.transport.send_event(event(...))` calls across 15 handler modules onto `BaseDomainService.reply()` / `self.send_msg()`.
- **Fortress/Special dungeon entry limits & required entry items (Issue #22 — live-verified)**:
  - Extracted all 16 special/Citadel map entry rules (`EnterItemID`, `EnterItemAmount`, `EnterLimit`, `ClearLimit`, `is_citadel`) from `maplist.lua` into `assets/dungeon_entry_rules.json` (`dungeon_entry_rule()` in `src/darkblood/games/game_data/world.py`).
  - Mapped `daily_dun_enter_counts` (`+0x3D1` -> `0x009646F0`), `daily_dun_clear_counts` (`+0x3DD` -> `0x00964A00`), and `citadel_play_count` (`+0x3E9` -> `player +0x304`, `UI_3408`) in `2007 SelectCharacterAck` (`schemas/lobby.jsch`, `src/darkblood/games/handlers/frontend.py`).
  - Added `refresh_dungeon_entry_limits()` in `src/darkblood/games/progression.py` (Monday weekly reset to 3 Citadel challenges, +1 daily charge up to 7, daily reset of `daily_dun_enter_counts`).
  - Enforced & consumed Citadel play count (`2631 CitadelPlayCountUpdateNot`), daily enter limits (`2318 DailyDunEnterCountUpdateNot`), and required entry items (`2037 DragItemAck`) in `handle_start_game` (`5013 -> 5014`), rejecting missing items with `5136 FailDungeonEnterItemNot` + `5014(result=138)` and limit exhaustion with `5222 FailDungeonEnterLimitNot` + `5014(result=139)` (matching `0x007880A0` silent range `0x8A..0x8B`).
- **Dual Skill Activation Order (`2038 -> 2039 + 2578 DualSkillActiveNot`, `2007`, PR #24 / Issue #15 item 6)**:
  - Mapped all 3 `Type = 54` Dual Skill items (`IDSk1Cash269` 30d, `IDSk20S159` 10d, `IDSk20R434` 30d) in `src/darkblood/games/handlers/inventory/items.py`: using an item persists `dual_skill_expire` and sends `2578 DualSkillActiveNot` (`extend_time` in remaining seconds, multiplied by 1000 in `0x00945C60`).
  - Mapped `+0x18A` (`dual_skill_index`) and `+0x194` (`dual_skill_remain_sec`) in `Character.encode_world_details` (`0x00A52630`, `2007 SelectCharacterAck`) so active Dual Skill persists across relogging.
- **Launcher & GM Bridge (`tools/launcher.py`, `tools/updater.py`, `tools/build_release.py`, `src/darkblood/games/gm_bridge.py`)**:
  - Restricted launcher updates strictly to published GitHub Releases (`releases_only=True`, no fallback to unreleased `main` commits) and fixed release changelog scoping via GitHub `/compare/{prev_tag}...{cur_tag}`.
  - Eliminated Windows light-theme flash on tab/page switches via `tkraise()` and off-screen atomic `ScrollFrame.swap_inner()`.
  - Hid `Build & Deploy Hook` in frozen release builds, added `--icon assets/darkblood.ico` to `DarkBloodLauncher.exe`, defaulted `skip_logos` and `skip_tutorial_always` to `True`, and added `ensure_hook_deployed()` on Play.
  - Added searchable `GM COMMANDS` tab (shown only when `gm_mode` is enabled) backed by localhost-only GM bridge (`127.0.0.1:9402`) for live execution of server-backed GM commands.
- **Waypoints (`2344 -> 2345`, `5030 -> 5031`, `2007`, PR #24 — live-verified)**:
  - Recovered `WaypointData` (`0x00A49700`: `u64 layer_net_id`, `wstr name`, `h32 waypoint_id`, `i32 x`, `i32 y`) from `0x0064AE00`, `0x0064FC60` (`UpdateList`), and `0x00654D80` (`OnTeleportOK`), and `DictSquarePortal::GetCost` (`0x00A688E0`: `int(int(base_cost) * level_ratio + 0.5)`).
  - Extracted all 11 town waypoints (layer IDs, `@LayerName_*` localization keys, `act*_0*` IDs, and `(x, y)` coordinates) from `act1.map`, `act2.map`, `act4.map` and portal cost/level-ratio tables from `waypoint.lua` into `assets/waypoints.json`, loaded via `waypoint_info()` / `portal_cost()` in `src/darkblood/games/game_data/world.py`.
  - `handle_waypoint_insert` (`2344 -> 2345`) now sends real `@LayerName_*` names, `jhash(waypoint_id)`, and destination `(x, y)`; `handle_join_layer` (`5030 -> 5031`) deducts `portal_cost` from `char['gold']` when `use_waypoint=True` and returns the updated `cur_ar`.
  - Mapped `map<u64, WaypointData> waypoints` (`0x00A3EA00 -> 0x00A3E490 -> 0x00A1F4E0`) in `2007 SelectCharacterAck` (`schemas/lobby.jsch`, `src/darkblood/games/handlers/frontend.py`) so unlocked waypoints persist across relogging.
- **Batch skill learning freeze/crash (`2697 -> 2698`, PR #24 / Issue #15 item 1 — live-verified)**:
  - Live wire capture showed that large `2697 LearnSkillListReq` batches (zlib-compressed by the client) decode **without** the `0x7FFFFFFF` 4-byte prefix (`10 8a 0f ff 00 04 ...`), while `schemas/skills.jsch` declared `header` (unconditional 4-byte strip), causing `bad-request 2697` and leaving the client frozen waiting for `2698`.
  - Changed `2697` to `header?` and fixed `_charge_skills` (`src/darkblood/games/handlers/skills.py`) to advance a running per-skill level map instead of double/triple-charging SP/AR when `2697` includes multiple sequential level steps for the same skill.
- **Pet Egg hatching (`2464 -> 2465 PetCreateAck`, PR #24 / Issue #15 item 4 — live-verified)**:
  - Recovered `PetInfo` (`0x00A52CF0`, ctor `0x005014D0`) and `2465 PetCreateAck` (`0x0079E620`, assert `0x00CFD628`: `vecItem >> nItemID >> jNewPetInfo`).
  - Previously `PetCreateAck` sent 52 zero bytes (`raw[52]`), causing `0x00A52CF0` to fail deserialization and abort without consuming the egg or creating the pet.
  - `handle_pet_create` now consumes 1 Pet Egg item (emitting a zero-count tombstone in `vecItem` and `jhash(egg_code)` as `item_id`) and sends a valid `PetInfo` (`PetCall001`), triggering inventory/quickslot/pet UI refresh and opening page `0x7C`.
- **Quickslot refresh on item deletion (`2040 -> 2041`, PR #24 — live-verified)**:
  - Client `0x00557420` (`2041 DeleteItemAck`) only refreshes UI `0` (Inventory) and omits UI `7` (Quickslot).
  - `handle_delete_item` (`src/darkblood/games/handlers/inventory/items.py`) now follows successful `2041` replies with an unsolicited empty `2037 DragItemAck(result=0, items=[])` (`0x0077F570` refreshes `[0, 7, 2, 0xc, 0xe]`) and clears UID-bound quickslots (`type == 0, ref_uid == req.item_uid`) on full deletion via `2045 AssignQuickslotAck(ref_id=-1, ref_uid=-1)`.
- **Random box popup & Card Booster Pack (`2196`, `item_randombox.lua`, PR #24 / Issue #15 items 2, 3, 7 — live-verified)**:
  - Static analysis of `0x0075A2E0` (assert `0x00CF0A30`: `nItemID >> sAmount >> bSelect`) and `0x00614030` (`JAppPageRandomBox::ShowResult`) showed `bSelect == False` skips updating `Page_RandomBox`, leaving `GAME_432` (`"Please try again."`). `handle_use_item` now sends `RandomboxResultItemNot(..., is_jackpot=True)` (`bSelect=True`).
  - Updated `cash_items()`, `cash_packages()`, and `random_boxes()` (`src/darkblood/games/game_data/items.py`) to scan `item_randombox.lua` and `item_disposable.lua` (all sections) and re-exported `assets/cash_items.tsv` (1,026 items), `assets/cash_packages.tsv` (2,216 rows), and `assets/random_boxes.json` (440 states, 319 groups — fixing Card Booster Pack `IRanCashEtc260` -> `RboxEEtc150R628`).
- **GM command documentation & ID catalogs (PR #24)**:
  - Reorganized `docs/GM_COMMANDS.md` with parameters, examples, GM shortcuts, and generated ID catalogs under `docs/gm_ids/` (`tools/gen_gm_reference.py`).
- **Standalone PyInstaller launcher release (`DarkBloodLauncher.exe`)**:
  - Removed legacy `.bat` wrappers; `tools/launcher.py` supports `--server`, `--check`, and `DARKBLOOD_WINDOW_RECT` 2×2 tiling for 1–4 clients; `tools/updater.py` supports Windows locked-exe self-update; `tools/build_release.py` and `.github/workflows/release.yml` build the standalone ZIP.
- **Starter armor preview after creation (`2013 -> 2009`, live-verified)**:
  - Sending `2009` roster after successful `2013` displays starter armor immediately in the lobby.
- **Dungeon rank calculation (`5017/5018`), card rewards (`5090/5091`), & class promotion (`2283`)**:
  - `5017` computes rank from `mapPartyScoreList / nTotalMosterHP` via `dungeonrank.lua` thresholds; `5091` rolls from `assets/dungeon_rewards.json` (limited to one claim per clear; full bag leaves claim available); repeat `5017` returns saved `5018`.
  - Class promotion quests (`assets/quest_promotions.tsv`) promote `char_class`, refund AP, and send `2283 PromotionNot`.
- **4-client multibox (`tools/multibox.py`, `tools/mcp_server.py`)**:
  - Generalized to 1–4 clients with `auto`/`grid`/`row` tiling and `--with-server`.

## Verification status

- **Headless suite**: **238/238** tests pass (`python -m unittest discover -s tests -v`), plus `gen_messages.py --check`, `gen_progress.py --check`, and `gen_opcode_registry.py --check`.

## Open targets / next investigations

- **Issue #15 remaining items**:
  5. Life Skills screen not updating visually after learning.
  6. Dual Skill item live verification (code & headless test complete; verify in-game).
- **Subclass promotion skills**: Confirm exact subclass and expected auto-learned skills before changing `2283 PromotionNot`'s empty learned-skill map.
- **Roadmap priorities (`ROADMAP.md`)**: Shared co-op dungeon instances, town movement desync, remaining unmapped fields (`docs/UNMAPPED_FIELDS.md`).
