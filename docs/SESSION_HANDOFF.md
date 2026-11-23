# Session handoff — 2026-11-23

> Older per-session logs (2026-11-16 through 2026-11-21) were pruned to keep this handoff concise; they remain in Git history and their results are reflected in `README.md`, `docs/STATUS.md`, `docs/OPCODE_REGISTRY.md`, and `ROADMAP.md`.

## Recent verified changes (2026-11-22 – 2026-11-23)

- **Waypoints (`2344 -> 2345 WaypointInsertAck`, `5030 -> 5031`, PR #24 — headless verified, live check pending)**:
  - Recovered `WaypointData` (`0x00A49700`: `u64 layer_net_id`, `wstr name`, `h32 waypoint_id`, `i32 x`, `i32 y`) from `0x0064AE00`, `0x0064FC60` (`UpdateList`), and `0x00654D80` (`OnTeleportOK`).
  - Previously `2345` sent `ChannelSquare` (`u64 1`), so `UpdateList` called `DictMap::FindSquare(high_dword(1))` = `NULL` and discarded every waypoint. `handle_waypoint_insert` now sends `WaypointData(layer_net_id=layer, ...)` and persists `char['waypoints']`, and `handle_join_layer` (`5030 -> 5031`) echoes `use_waypoint`.
- **Pet Egg hatching (`2464 -> 2465 PetCreateAck`, PR #24 / Issue #15 item 4 — headless verified, live check pending)**:
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

- **Headless suite**: **226/226** tests pass (`python -m unittest discover -s tests -v`), plus `gen_messages.py --check`, `gen_progress.py --check`, and `gen_opcode_registry.py --check`.

## Open targets / next investigations

- **Issue #15 remaining items**:
  1. Game crash when putting many points into a skill.
  4. Pet Egg does nothing when used.
  5. Life Skills screen not updating visually after learning.
  6. Dual Skill item not reflected in Skill screen.
- **Subclass promotion skills**: Confirm exact subclass and expected auto-learned skills before changing `2283 PromotionNot`'s empty learned-skill map.
- **Roadmap priorities (`ROADMAP.md`)**: Shared co-op dungeon instances, town movement desync, remaining unmapped fields (`docs/UNMAPPED_FIELDS.md`).
