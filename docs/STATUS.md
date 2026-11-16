# Research status and handoff

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
   - Granted direct write/push access on `main` to `CristianVita` (`cri999sti@gmail.com`).
   - Created [CONTRIBUTING.md](../CONTRIBUTING.md) and established a mandatory 10-minute sync rule for all agents.

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
