# Roadmap — Dark Blood Offline Server Emulator

Updated **November 17, 2026**.

Final objective: launch without the original services, establish a local session, persist character and world state, enter maps/dungeons, and provide full offline singleplayer and LAN multiplayer gameplay.

---

## Current Milestones Overview

| Milestone | Scope | Status | Notes |
|---|---|---|---|
| **P0: Enter the World** | Handshake, Auth, Lobby, Selection, Town entry | **Verified** | Town rendered, character visible, movement confirmed |
| **P1: Transport & Serialization** | ProudNet framing, JSerBuffer, crypto, compression | **Verified** | Full regression test suite (`test_transport.py`), 11 tests |
| **P2: Lobby & Account** | Character list, create, delete, versioned persistence | **Verified** | Name validation, persistent SQLite store, default gear |
| **P3: Gameplay & Economy** | Combat, dungeons, drops, store, level-up, guild | **Verified (~95%)** | Live 11-17: tutorial, equip/swap, stats, death/revive, cash shop, depot, pets, mounts, loot |
| **P4: Assets & Config** | JPK unpacker, LUA tables, dictionaries | **In Progress (~80%)** | Validated decoder, store/quest/stat/cash/monster tables parsed |
| **P5: Stability & Launcher** | Steam shim, process supervisor, gamectl, MCP | **In Progress (~85%)** | Clean headless test runner, process cleanup, GM web dashboard |
| **P6: Multiplayer & Relay Sync** | P2P client relay, party instances, town broadcast | **In Progress (~85%)** | Spatial movement sync (5030/5031), join/leave (5021/5022), party subsystem (2100-2107, 5049-5056) verified; co-op dungeon instances next |
| **P7: Commerce & Post System** | P2P trade, personal shops, mail/attachments, depot | **Verified (~95%)** | P2P trade, full mailbox with attachments, depot AR/slots, player stalls & broker marketplace live |
| **P8: Guild Warfare & Arena PvP** | Guild wars, sieges, arena rooms, ladder matchmaking | **In Progress (~90%)** | Guild banking/notice/skills live; duels, arena rooms, teams, league rankings live; siege warfare next |
| **P9: Refactoring & Architecture** | Modular messages, GM dashboard, opcode registry | **Verified (100%)** | 164 tests; pure composition `PacketDispatcher` & `BaseDomainService`; opcode registry (501 entries) |
| **P10: C# / .NET 8 Server Port** | High-performance C# server (MHServerEmu alignment) | **Planned** | Composition architecture, ProudNet wire layer, entity model, domain services |

---

## Detailed Milestone Progress

### P0 — Enter the World
- [x] Explain why 2402 was never sent (missing session key; strong encryption mode 1).
- [x] Implement ProudNet RSA/AES key exchange and decrypt type 0x26.
- [x] Recover and answer 2403, 2002, 2022, 5029, 2009, 2013.
- [x] Recover struct `0x00A40760` and vector `0x004B9210` for opcode 2007 (handler `0x007AA4B0`); implement the response.
- [x] Observe client requests after 2007 and connect `JP2PClient` via relay 5134.
- [x] Identify level, class, and location fields shown on character selection screen.
- [x] Live town entry verified with rendered graphics and controllable character.

### P1 — Reproducible Transport and Serialization
- [x] Test ProudNet signed scalar boundaries (1, 2, 4, 8 bytes), invalid widths, truncation, and frame limits (`tests/test_transport.py`).
- [x] Add regression fixture for first captured frame (`13 57 01 05 30 0F 00 00 40`).
- [x] Implement bounded `JSerBufferReader` supporting varuints, strings, wide strings, and vectors (`core.serialization.jser`).
- [x] Implement zlib payload compression with 4-byte uncompressed size prefix.
- [x] Distinguish ProudNet control messages (0x05, 0x06, 0x07, 0x08, 0x0B), RMIs, and application events (0x02).
- [ ] Investigate `0x1D` control message and determine official ACK semantics (current `0x1F` reply is experimental).
- [ ] Implement optional server-to-client encryption (symmetric AES) if enabled by client settings.
- [ ] Evaluate UDP route for fast position synchronization (`JP2PClient` type 0x27).

### P2 — Initialization, Authentication, and Lobby
- [x] Recover bootstrap, server/channel list, and authentication operations from the application dispatcher.
- [x] Implement local account session states (`OfflinePlayer`) and credentials handling.
- [x] Implement character listing, creation, and deletion with case-insensitive name validation.
- [x] Implement versioned local character persistence (`data/characters.json`).
- [x] Decode adult flag in opcode 5020 (`m_bAdultUser = True` unlocks blood effect in client options).
- [ ] Add multiple account support and profile switching.

### P3 — Map Entry, Dungeons, Combat & Economy
- [x] Recover lobby-to-square/zone transfers, map IDs, and relay handshake (port 9401).
- [x] Implement spawn coordinates, player movement, and heartbeat responses.
- [x] Implement dungeon lifecycle: gate selection (5043/5044), map code resolution (5009/5010), and dungeon start (5013/5014).
- [x] Implement dungeon layers (5095 `CHANGE_DUNGEON_LAYER_NOT`) and active warflags (2422).
- [x] Player death (5093/5094, echoes the client UID) and rebirth-coin revive — live 2026-11-17.
- [x] Monster kill EXP (5063 -> 5086 from `monster.lua`) and drops (`games/loot.py`, 5064, pick-up 5065 -> 5068 + 2037) — headless only.
- [x] Implement dungeon completion: card reward choice (5090/5091) and return to town (5045/5046).
- [x] 5017 finish game -> 5018 clear result (reward map still empty).
- [x] Implement level-up & SP progression on EXP overflow using `Data/Dict/charstat.lua` tables with 5087 (`LevelUpNot`) and 5086 (`ChangeExpNot`).
- [x] Implement shop transactions: buy item (2067/2068), sell item (2069/2070), and repurchase (2071/2072) with gold & inventory persistence.
- [x] Inventory operations live 2026-11-17: drag (2036/2037), equip/unequip/swap (2042/2043), use (2038/2039), delete (2040/2041). Fixes: request prefix, owner -1, empty cells uid/code -1, equipment slot validation, bag capacity.
- [x] Item stats: Quality 0 (was 0xFFFF -> every item stat -1.0), integer max durability.
- [x] Depot / warehouse: gold storage save/load (2228-2231 `DEPOT_SAVE_AR`/`DEPOT_LOAD_AR`) and container slot expansion (2461/2462 `DEPOT_SLOT_EXTEND`).
- [x] Implement skill management: learn skill (2050/2051), lock skill (2117/2118), and custom speech shout (2053/2054, 2055/2056).
- [x] Implement guild economy: money deposit (2179/2180), money withdraw (2181/2182), level up (2183/2184), notice modify/delete (2185/2186, 2188/2189), and skill init (2214/2215).
- [ ] Implement monster AI aggro and damage calculation algorithms from client property tables.
- [ ] Implement item enhancement/refining system (2115/2116 `ITEM_UPGRADE_REQ/ACK`) with success/break rates.
- [x] Cash shop offline: Steam purchase 2712 -> 2037 + 2714; packages (PACKAGEnnn) and random boxes open on use.
- [x] Mounts (`ridecall`, 2434-2438), pets (`PetCall`, 2464-2474), monster taming (2348-2351), CashWG/CashAG/Zam boxes.

### Wire-correctness audit (from the 2026-11-17 session)
- [x] Remove literal `0x1E`/`0x0D` struct tags where the reader uses `0x00B35010` (2075, 2074/2077, 5086, 5087, 5064, 5068).
- [ ] Audit the ~15 encoders that still emit `0x1e` (arena, NPC store 2066/2072, events, guild, social).
- [x] Client UID: details `+0x1C` now carries the character id.
- [ ] Shared `strip_prefix()` for the `ffffff7f` request header (~30 ad-hoc checks).

### P4 — Assets and Configuration
- [x] Reverse engineer JPK archive format: 0x226 header flag, custom inverse cipher, and directory headers.
- [x] Implement byte-identical JPK repacker and CLI extraction tools (`tools/jpk_tool.py`).
- [x] Parse `Data/Dict/questlist.lua` for quest objectives, dialogue, and gold/EXP/item rewards.
- [x] Parse `Data/Dict/storelist.lua` for NPC shop inventories and stock limits.
- [x] Parse `Data/Dict/charstat.lua` for per-class base stats, HP/MP curves, and level-up requirements.
- [x] Parse `Data/Dict/maplist.lua` for square definitions, dungeon layers, and spawn coordinates.
- [x] Parse `monster.lua` (Exp, Lv, HP, DropCnt) and `itemlooting.lua` (MonLooting, LootingItem, groups), `item_cash.lua` (products, packages, random boxes).
- [ ] Parse skill damage formulas and cooldown definitions (`Data/Dict/skilllist.lua`).
- [ ] Investigate `DarkbloodKR.ini` configuration flags and client customization toggles.
- [ ] Optional: fix the shipped English UI text in `Data/localization_st/ui_st.dat` (UTF-16, `ID<TAB>text` lines), on a separate
  copy of the archive only, never through the `research/client/Data` junction to the original install. Known
  mistranslations: `UI_504` "Item" heads the channel list's Category column (`page_selectchannel.xml`); `UI_1213`
  "Character" (singular) heads the server list's character count column (`page_selectserver.xml`). Deferred by the user (2026-11-16).

### P5 — Stability, Launcher & Tooling
- [x] Replace dummy Steam placeholders with robust proxy implementations (`SteamUser`, `SteamFriends`, `SteamUserStats`).
- [x] Fix compilation issues under MSVC with independent build environment detection (`build_shim.bat`).
- [x] Implement supervisor CLI (`tools/gamectl.py`) with client hash verification and clean process isolation.
- [x] Implement MCP automation server (`tools/mcp_server.py`) for AI agent control and live telemetry.
- [x] Add GitHub Issue templates (`bug_report.yml`, `opcode_investigation.yml`) and diagnostic exporter (`tools/export_diagnostics.py`).
- [ ] Implement automatic test-client staging (clean copy of game folder without touching original install).
- [ ] Verify complete network isolation: hook `WSAConnect`, `ConnectEx`, IPv6 sockets, and UDP ports.
- [ ] Automated release build pipeline producing single-binary / portable launcher zip.

---

## New Milestones

### P6 — Multiplayer, Party & P2P Relay Synchronization
- [x] **Multi-client Square Synchronization**:
  - Broadcast player position, rotation, and animation state to nearby players in the same square/layer (`5030/5031 eERC_USER_MOVE_NOT`).
  - Handle player join notification (`5021 eERC_USER_JOIN_SQUARE_NOT`) and player leave notification (`5022 eERC_USER_LEAVE_SQUARE_NOT`).
  - Chat broadcasting: normal chat, whisper, party chat, guild chat, and world megaphone (2128/2129).
- [x] **Party System**:
  - Party creation and invite (`2100 eEGS_PARTY_INVITE_REQ` / `2101 eEGS_PARTY_INVITE_ACK`, `5049/5050 eERC_INVITE_REQ/ACK`, `5051 eERC_INVITE_NOT`).
  - Party join, leave, and kick (`2102/2103 eEGS_PARTY_JOIN`, `5054/5055 eERC_ACCEPT_INVITE`, `5056 ACCEPT_INVITE_NOT`, `2104/2105 LEAVE`, `2106/2107 KICK`).
  - Master delegation and leader promotion upon departure.
  - Square re-registration preserves party membership and updates the member session.
    Stale disconnect/leave requests preserve replacement sessions (167 tests pass
    locally on Cristian's machine, 2026-11-18, live verification pending).
- [ ] **Co-op Dungeon Instances**:
  - Synchronize party dungeon entry so all party members enter the same dungeon instance.
  - Synchronize monster health, damage numbers, and boss cinematic triggers across party members.
  - Shared party rank calculation and card reward selection at dungeon finish.

### P7 — Complete Economy, Trade & Mail System
- [x] **Player-to-Player Direct Trade**:
  - Trade request and invitation (`5069 eERC_REQUEST_TRADE_REQ` / `5070 ACK` `0x00770E50`, `5071/5072 ACCEPT_REQUEST_TRADE` `0x007587B0`).
  - Trade window synchronization: adding items (`5075/5076 INSERT_TRADE_ITEM` `0x0077D980`), deleting items (`5077/5078` `0x0077DBB0`), updating AR currency (`5079/5080` `0x00758940`), locking and dual confirmation (`5081/5082 ACCEPT_TRADE` `0x0078EB40`, `5083/5084 FINALLY_ACCEPT_TRADE`, `6010 TRADE_RESULT_NOT` `0x0077E090`).
  - Transaction atomicity: swap items and gold between characters with inventory capacity verification.
- [x] **Mailbox System (Post Office)**:
  - Mail listing (`2219 eEGS_POST_REQUEST_LIST_REQ` / `2220 ACK` `0x007AEF70`).
  - Read mail, claim attached gold/items (`2223/2224 eEGS_POST_READ_REQ/ACK` `0x0075A660`, `2225/2226 eEGS_POST_GET_APPEND_ITEM_REQ/ACK` `0x0077F8E0`).
  - Send mail with gold and item attachments to offline/online characters (`2221/2222 eEGS_POST_SEND_REQ/ACK` `0x00795F40`).
  - Mail expiration, return to sender, and deletion (`2236/2237 eEGS_POST_DELETE_REQ/ACK` `0x007715F0`).
- [x] **Personal Shop (Player Stalls)**:
  - Opening personal stall in town (`2340/2341 eEGS_PERSONALSHOP_START` `0x00601AA0`, alias `2078/2079`).
  - Setting stall title, price per item (`StallItem`), and browsing products (`6021/6022 eERT_PERSONALSHOP_GET_PRODUCTS` `0x006029D6`).
  - Purchasing items directly from player stalls (`5242/5243 eERC_PERSONALSHOP_BUYITEM` `0x006022AC`, alias `2080/2081`) with atomic gold and inventory transfers.
  - Renaming stall title (`2090/2091`) and closing stalls (`2342/2343`, alias `2088/2089`) with town broadcasts (`5250`, `5254`, `5255`).
- [x] **Auction House / Market (Broker Subsystem)**:
  - Search and browse marketplace listings with pagination (`2262/2263 eEGS_BROKER_LIST` `0x005ADAC0`).
  - Query personal listings (`2264/2265 eEGS_BROKER_MYLIST` `0x005ADFF0`).
  - Register items for instant marketplace buyout with deposit (`2266/2267 eEGS_BROKER_REGIST_ITEM` `0x005AFBAC`).
  - Buy marketplace items atomically (`2268/2269 eEGS_BROKER_BUY_ITEM` `0x005B005C`).
  - Cancel marketplace listings (`2270/2271 eEGS_BROKER_CANCEL`).
  - Market price history and valuation statistics (`2272/2273 eEGS_BROKER_PRICE`).

### P8 — Guild Warfare, Sieges, Social Expansion & Arena PvP
- [x] **Titles & Achievements System**:
  - Title change request and update (`2335/2336 eEGS_TITLE_CHANGE_REQ/ACK` `0x007751C0`).
  - Achievement list request (`2327/2328 eEGS_ACHIEVE_GET_LIST_REQ/ACK` `0x0079D650`).
  - Real-time achievement progression updates (`2329 eEGS_ACHIEVE_CHANGE_NOT` `0x0076C720`, `2330 eEGS_ACHIEVE_COMPLETE_NOT` `0x0079D240`).
- [x] **Avatar Gem / Zam Socketing & Monster Taming**:
  - Avatar gem insert and socketing (`2362/2363 eEGS_AVATAR_ZAM_INSERT_REQ/ACK` `0x00782D00`).
  - Avatar gem removal and extraction (`2364/2365 eEGS_AVATAR_ZAM_ERASE_REQ/ACK` `0x00782F40`).
  - Monster taming capture and release (`2348/2349 eEGS_TAMEING_MONSTER_INSERT_REQ/ACK` `0x00771A00`, `2350/2351 eEGS_TAMEING_MONSTER_DELETE_REQ/ACK` `0x00771BB0`).
- [x] **Class Promotion, Skill Reset & Security**:
  - Skill point reset notification (`2280 eEGS_INIT_SKILL_NOT` `0x00797740`).
  - Class advancement and promotion (`2283 eEGS_PROMOTION_NOT` `0x00797F00`).
  - Rebirth coin balance sync (`2286 eEGS_REBIRTH_COIN_CHANGE_NOT` `0x007983B0`).
  - Second password / PIN management (`5256/5257 CREATE` `0x0075B020`, `5258/5259 MODIFY` `0x0075B050`, `5260/5261 AUTH` `0x0075B080`).
- [x] **Remote Player & Item Inspection**:
  - Character gear and avatar inspection (`6011/6012 eERT_REQUEST_CHAR_INFO_REQ/ACK` `0x00790FA0`).
  - Remote item tooltip inspection (`6028/6029 eERT_REQUEST_ITEM_INFO_REQ/ACK` `0x00766C20`).
- [x] **Guild Management Expansion**:
  - Member grade and permissions management (`2164/2165 eEGS_GUILD_PERSON_GRADE_MODIFY_REQ/ACK` `0x00753170`).
  - Guild bank and economy (`2179/2180 eEGS_GUILD_MONEY_IN_REQ/ACK` `0x00794250`, `2181/2182 eEGS_GUILD_MONEY_OUT_REQ/ACK` `0x00794470`).
  - Guild info and roster broadcast (`2157 eEGS_GUILD_INFO_NOT` `0x00752FF0`, `2158 eEGS_GUILD_PERSON_LIST_NOT` `0x0077ABA0`).
  - Guild level-up perks and notices (`2183/2184 eEGS_GUILD_LEVEL_UP_REQ/ACK` `0x00753380`, `2185/2186 eEGS_GUILD_NOTICE_MODIFY_REQ/ACK` `0x0075A120`).
  - Guild skill tree sync (`2205 eEGS_GUILD_SKILL_NOT` `0x00779390`, `2207 eEGS_GUILD_LEARN_SKILL_ACK`, `2209 eEGS_GUILD_SKILL_CHANGE_USE_STATE_ACK`).
- [x] **Storage Depot, Item Splitting & Combat Feedback**:
  - Personal depot AR gold storage (`2228/2229 eEGS_DEPOT_SAVE_AR_REQ/ACK` `0x00795220`, `2230/2231 eEGS_DEPOT_LOAD_AR_REQ/ACK` `0x00795490`).
  - Mail arrival notice (`2227 eEGS_POST_NEW_ARRIVAL_NOT` `0x007965B0`) and mail return (`2234/2235 eEGS_POST_RETURN_REQ/ACK` `0x00771470`).
  - Item stack splitting (`2250/2251 eEGS_DIVIDE_ITEM_REQ/ACK` `0x0077F570`).
  - Skill book consumption (`2111/2112 eEGS_USE_LEARN_SKILL_ITEM_REQ/ACK` `0x0078BCD0`).
  - Item duration & deletion sync (`2321 eEGS_ITEM_REMAIN_TIME_NOT` `0x0077AED0`, `2322 eEGS_ITEM_DELETE_NOT` `0x00774DD0`).
  - Real-time inventory refresh (`2092 eEGS_INVENTORY_UPDATED_NOT` `0x0077F070`).
  - AP gain, dungeon penalty & random box feedback (`2109 eEGS_INSERT_AP_NOT` `0x00790480`, `2085 eEGS_CHANGE_DUNGEON_PENALTY_NOT` `0x0078FA70`, `2196 eEGS_RANDOMBOX_RESULT_ITEM_NOT` `0x0075A2E0`).
- [x] **PvP Duels & Arena**:
  - 1v1 duel challenge in town / square (`5100/5101 eERC_DUEL_REQUEST` `0x006C0A10`, `5097/5098 eERC_DUEL_START` `0x006CBE60`, `5099 eERC_DUEL_START_NOT` `0x006CCDF0`, `5105/5106 eERC_DUEL_RESULT` `0x006CC6B0`, `5108 eERC_DUEL_GIVEUP_NOT`, `5112/5113 eERC_DUEL_REFUSE` `0x006B4120`).
  - Arena channels, rooms and matchmaking (`2304/2305 eEGS_ARENA_SQUARELIST` `0x004B67F0`, `2306/2307 eEGS_ARENA_GET_ROOMLIST` `0x004B96D0`, `2308/2309 eEGS_ARENA_GET_INVITELIST` `0x004B4680`, `5138 eERC_ARENA_JOIN_SQUARE_ACK`).
  - Arena teams management (`5269/5270 eERC_ARENA_TEAM_CREATE` `0x0049BEF0`, `5271/5272 eERC_ARENA_TEAM_JOIN` `0x0049C4B0`, `5274/5275 eERC_ARENA_TEAM_LEAVE` `0x00490100`).
  - Arena rankings & ladder leaderboards (`2550/2551 eEGS_LEAGUE_SEASON_ARENA_GET_RANK` `0x00499DC0`, `2552/2553 eEGS_LEAGUE_SEASON_ARENA_GET_MY_RANK` `0x00492A10`).
  - Arena SP item consumption (`2709/2710 eEGS_USE_ARENA_SP_ITEM_REQ/ACK` `0x007A7CA0`) and square return (`5165/5166 eERC_ARENA_BACK_TO_SQUARE_ACK` `0x00758550`).
  - Verified by dedicated unit & headless flow tests (`test_arena_flow.py`).
- [ ] **Guild War & Castle Siege**:
  - War declaration between guilds.
  - Scheduled siege warfare instances with gate destruction and flag capture objectives.

### P9 — Architecture Refactoring & C# Migration Preparation
- [x] **Modularize Message Schemas**:
  - Split monolithic `src/darkblood/games/network/messages.py` into 13 domain-specific modules:
    - `darkblood.games.network.messages.lobby`
    - `darkblood.games.network.messages.inventory`
    - `darkblood.games.network.messages.skills`
    - `darkblood.games.network.messages.commerce`
    - `darkblood.games.network.messages.quests`
    - `darkblood.games.network.messages.dungeon`
    - `darkblood.games.network.messages.social`
    - `darkblood.games.network.messages.guild`
    - `darkblood.games.network.messages.events`
    - `darkblood.games.network.messages.system`
    - `darkblood.games.network.messages.arena`
    - `darkblood.games.network.messages.mail`
    - `darkblood.games.network.messages.pets`
  - Re-exported all dataclasses in `messages/__init__.py` with 100% backward compatibility.
- [x] **Standalone GM & Server Web Dashboard**:
  - Built `tools/dashboard.py` (port 9494) providing live telemetry for port 9400 & 9401.
  - Interactive web UI for character inspection, level/stat modification, and opcode reference browser.
  - Integrated `SqliteCharacterStore` with dashboard.
- [x] **Semantic Handler Architecture & Docstrings**:
  - Replaced raw opcode identifiers with semantic method names (`handle_*`) across all handler domains.
  - Added opcode backward-compatibility aliases and rich reverse-engineering docstrings.
- [x] **Granular Unit Testing**:
  - Expanded test suite to **150 automated tests** covering wire codecs, flows, database persistence, and edge cases.
- [x] **Database & Storage Abstraction**:
  - Introduce `ICharacterStore` interface with abstract async methods.
  - Implement SQLite backend (`data/darkblood.db`) for high reliability and SQL querying (`src/darkblood/player_management/store.py`).
  - Implement export/import tool between JSON and SQLite (`import_from_json`, `export_to_json`).
  - Switched `GameSession.store()` runtime store to `SqliteCharacterStore` with auto-migration from `characters.json` and ACID commit guarantees.
- [x] **Domain Entity Decoupling & Multi-client World Management**:
  - Introduced `GameWorldManager` managing player presence, square instances, and mutual character spawns via Opcode 5096 (`UpdateCharInfoNot`).
  - Automated mutual spawning between players entering square channels (`test_world_flow.py`).
- [x] **Master Opcode Registry**:
  - Created `docs/OPCODE_REGISTRY.md` compiling 501 tracked opcodes, reverse-engineered client virtual addresses (298 found), implemented server handlers (140), directions, and wire notes.
- [x] **C# Architectural Blueprint & Packet Dispatcher**:
  - Documented complete composition transition in `docs/ARCHITECTURE_REFACTOR_CSHARP.md`.
  - Created prototype `PacketDispatcher` (`src/darkblood/games/dispatcher.py`) and `BaseDomainService` (`src/darkblood/games/handlers/base.py`).
- [x] **Server Session Composition Transition**:
  - Migrated `GameSession` from 11 multiple inheritance mixins (`FrontendHandlers`, `SocialHandlers`, `MailHandlers`, `SquareHandlers`, `CommerceHandlers`, `InventoryHandlers`, `SkillHandlers`, `QuestHandlers`, `DungeonHandlers`, `ArenaHandlers`, `PetHandlers`) to pure composition using `PacketDispatcher` (`self.dispatcher`).
  - All domain services inherit from `BaseDomainService(session)` and register their handlers cleanly.
  - Full backward compatibility and two-way dynamic delegation maintained; 164 automated unit & flow tests passing 100%.

### P10 — C# / .NET 8 Server Port (MHServerEmu Architecture)
- [ ] **Solution & Project Scaffolding**:
  - Create `DarkBloodServer.sln` targeting .NET 8:
    - `DarkBlood.Core`: Binary primitives, endianness helpers, JSerBuffer reader/writer, cryptographic handshakes.
    - `DarkBlood.Network`: ProudNet framing, packet serialization, session lifecycle, encryption pipelines.
    - `DarkBlood.Database`: Entity Framework Core / SQLite entities, repositories, database migration tools.
    - `DarkBlood.GameServer`: PacketDispatcher, session controller, domain services (Lobby, Inventory, Skills, Combat, Quests, Social, Mail, Guild, Arena, Pets).
- [ ] **Network Protocol & Handshake Parity**:
  - Implement ProudNet RSA 1024 + AES-128-CBC key exchange and packet framing in C#.
  - Implement JSerBuffer varuint & wide-string serialization matching Python implementation and client binary layout.
- [ ] **Domain Services & Handlers**:
  - Port attribute-based packet routing: `[PacketHandler(Opcode.eEGS_CHAR_LIST_REQ)]`.
  - Port character selection payload builder matching struct `0x00A40760` (all 34 sequential chunks).
  - Port game asset loaders for `.lua` dictionaries (`storelist.lua`, `questlist.lua`, `charstat.lua`, `monster.lua`, `itemlooting.lua`).
- [ ] **End-to-End Verification**:
  - Replicate integration tests in xUnit.
  - Connect live game client to C# server: verify authentication, character select, town movement, inventory manipulation, dungeon combat, and SQLite persistence.

---

## Subsystem Opcode Reference & Implementation Status

Below is the structured roadmap of client opcodes, categorized by gameplay subsystem.

### 1. Authentication, Lobby & Account (Opcodes 2001 - 2023, 2402 - 2405, 5020, 5028)
| Opcode Pair | Name | Status | Function / Handler |
|---|---|---|---|
| 5020 | `eERC_WELCOME_NOT` | **Implemented** | Initial session handshake & client settings |
| 2402 / 2403 | `eEGS_DB_LIST_REQ / ACK` | **Implemented** | Server list dialog (`0x00783CD0`) |
| 2001 / 2002 | `eEGS_CHANNEL_LIST_REQ / ACK` | **Implemented** | Channel selection list (`0x00783F40`) |
| 2021 / 2022 | `eEGS_AUTHENTICATE_REQ / ACK` | **Implemented** | User account authentication (`0x007841C0`) |
| 5028 / 5029 | `eERC_VERSION_REQ / ACK` | **Implemented** | Client version check (`0x00784400`) |
| 5134 | `eERC_SQUARE_RELAY_ANNOUNCE` | **Implemented** | Relay server endpoint (127.0.0.1:9401) |
| 2008 / 2009 | `eEGS_CHAR_LIST_REQ / ACK` | **Implemented** | Character selection list (`0x00784860`) |
| 2012 / 2013 | `eEGS_CREATE_CHARACTER_REQ / ACK` | **Implemented** | Character creation (`0x00784AC0`) |
| 2014 / 2015 | `eEGS_DELETE_CHARACTER_REQ / ACK` | **Implemented** | Character deletion (`0x00758370`) |
| 2006 / 2007 | `eEGS_SELECT_CHAR_REQ / ACK` | **Implemented** | Character select & world entry payload (`0x007AA4B0`) |
| 2016 / 2017 | `eEGS_CHANGE_CHAR_SLOT_REQ / ACK` | Planned | Reordering characters in selection menu |

### 2. Inventory, Items & Bag Management (Opcodes 2028 - 2049, 2115 - 2118, 2143 - 2146)
| Opcode Pair | Name | Status | Function / Handler |
|---|---|---|---|
| 2028 | `eEGS_CLOSE_BAG_REQ` | **Implemented** | Fire-and-forget bag window closed |
| 2030 / 2031 | `eEGS_SWITCH_BAG_REQ / ACK` | **Implemented** | Bag container slot swap (`0x00557680`) |
| 2032 / 2033 | `eEGS_CHANGE_BAG_NAME_REQ / ACK` | **Implemented** | Rename bag tab (`0x007528B0`) |
| 2036 / 2037 | `eEGS_DRAG_ITEM_REQ / ACK` | **Implemented** | Drag item across inventory slots (`0x0077DF60`) |
| 2038 / 2039 | `eEGS_USE_ITEM_REQ / ACK` | **Implemented** | Consume potion / food / buff (`0x0077D4C0`) |
| 2040 / 2041 | `eEGS_DELETE_ITEM_REQ / ACK` | **Implemented** | Discard item from inventory (`0x00557420`) |
| 2042 / 2043 | `eEGS_EQUIP_ITEM_REQ / ACK` | **Implemented** | Equip weapon / armor / accessory (`0x007AE940`) |
| 2044 / 2045 | `eEGS_ASSIGN_QUICKSLOT_REQ / ACK` | **Implemented** | Map item/skill to quickslot (`0x0078C4A0`) |
| 2046 / 2047 | `eEGS_SWITCH_QUICKSLOT_REQ / ACK` | **Implemented** | Reorder quickslot buttons (`0x0078C790`) |
| 2048 / 2049 | `eEGS_CHANGE_BAG_PROPERTY_REQ / ACK` | **Implemented** | Bag category filter settings (`0x00774040`) |
| 2115 / 2116 | `eEGS_ITEM_UPGRADE_REQ / ACK` | **Implemented** | Equipment reinforcement & upgrading (`0x007909C0`) |
| 2117 / 2118 | `eEGS_UPDATE_SKILL_LOCKED_REQ / ACK` | **Implemented** | Lock skill from accidental use (`0x00752C70`) |
| 2143 / 2144 | `eEGS_DURABILITY_CHANGE_REQ / ACK` | **Implemented** | Item durability wear update (`0x00774AE0`) |
| 2145 / 2146 | `eEGS_DURABILITY_REPAIR_REQ / ACK` | **Implemented** | Blacksmith durability repair (`0x007930D0`) |
| 2050 / 2051 | `eEGS_LEARN_SKILL_REQ / ACK` | **Implemented** | Skill tree progression & level (`0x0078DB90`) |
| 2053 / 2054 | `eEGS_MODIFY_SKILL_SPEECH_REQ / ACK` | **Implemented** | Custom skill shout text (`0x0078E090`) |
| 2055 / 2056 | `eEGS_DELETE_SKILL_SPEECH_REQ / ACK` | **Implemented** | Clear skill shout text (`0x0078E270`) |
| 2108 / 2109 | `eEGS_ITEM_DISASSEMBLE_REQ / ACK` | Planned | Salvage items into crafting materials |
| 2110 / 2111 | `eEGS_ITEM_SOCKET_INSERT_REQ / ACK` | Planned | Insert jewel / gem into socket |
| 2112 / 2113 | `eEGS_ITEM_SOCKET_REMOVE_REQ / ACK` | Planned | Extract jewel from socket |

### 3. Economy, Stores & Trade (Opcodes 2065 - 2087, 5069 - 5084)
| Opcode Pair | Name | Status | Function / Handler |
|---|---|---|---|
| 2065 / 2066 | `eEGS_GET_STORE_INFO_REQ / ACK` | **Implemented** | Fetch NPC store item list (`0x007842C0`) |
| 2067 / 2068 | `eEGS_BUY_ITEM_REQ / ACK` | **Implemented** | Buy items from store with gold (`0x0077E2F0`) |
| 2069 / 2070 | `eEGS_SELL_ITEM_REQ / ACK` | **Implemented** | Sell items to vendor for gold (`0x0077E8E0`) |
| 2071 / 2072 | `eEGS_REPURCHASE_ITEM_REQ / ACK` | **Implemented** | Repurchase sold items tab (`0x0077EC30`) |
| 2086 / 2087 | `eEGS_BUY_LIFE_WATER_REQ / ACK` | **Implemented** | Purchase life water resurrection item (`0x0078FF90`) |
| 5069 / 5070 | `eERC_REQUEST_TRADE_REQ / ACK` | **Implemented** | Direct player trade invite (`0x00770E50`) |
| 5071 / 5072 | `eERC_ACCEPT_REQUEST_TRADE_REQ / ACK` | **Implemented** | Accept trade invitation (`0x007587B0`) |
| 5073 / 5074 | `eERC_CANCEL_TRADE_REQ / ACK` | **Implemented** | Cancel active trade session (`0x0077DE00`) |
| 5075 / 5076 | `eERC_INSERT_TRADE_ITEM_REQ / ACK` | **Implemented** | Stage item into trade slot (`0x0077D980`) |
| 5077 / 5078 | `eERC_DELETE_TRADE_ITEM_REQ / ACK` | **Implemented** | Unstage item from trade slot (`0x0077DBB0`) |
| 5079 / 5080 | `eERC_UPDATE_TRADE_AR_REQ / ACK` | **Implemented** | Update gold offered in trade (`0x00758940`) |
| 5081 / 5082 | `eERC_ACCEPT_TRADE_REQ / ACK` | **Implemented** | Lock and accept trade terms (`0x0078EB40`) |
| 5083 / 5084 | `eERC_FINALLY_ACCEPT_TRADE_REQ / ACK` | **Implemented** | Final trade transaction execution |
| 2254 / 2255 | `eEGS_MAGICENCHANT_ENCHANT_REQ / ACK` | **Implemented** | Magic enchanting application (`0x00796DC0`) |
| 2256 / 2257 | `eEGS_MAGICENCHANT_ERASE_OPTION_REQ/ACK`| **Implemented** | Erase magical option from gear (`0x00797120`)|
| 2258 / 2259 | `eEGS_MAGICENCHANT_EXPEND_SLOT_REQ/ACK`| **Implemented** | Expand item socket slot (`0x0077FC60`) |
| 2284 / 2285 | `eEGS_RANDOM_ITEM_UPGRADE_REQ / ACK` | **Implemented** | Random item stat upgrade (`0x0077FED0`) |
| 2672 / 2673 | `eEGS_FIX_ITEM_UPGRADE_REQ / ACK` | **Implemented** | Fixed item stat upgrade (`0x00783C40`) |
| 2338 / 2339 | `eEGS_ITEM_SPIRIT_CHANGE_REQ / ACK` | **Implemented** | Spirit weapon stat transformation (`0x00780860`)|
| 2078 / 2079 | `eEGS_PERSONALSHOP_OPEN_REQ / ACK` | Planned | Open personal shop stall in town |
| 2080 / 2081 | `eEGS_PERSONALSHOP_BUY_REQ / ACK` | Planned | Purchase from player's personal stall |

### 4. Quests, Tutorial & Dialogue (Opcodes 2073 - 2095, 2346 - 2358, 2410)
| Opcode Pair | Name | Status | Function / Handler |
|---|---|---|---|
| 2073 / 2074 | `eEGS_QUEST_ACCEPT_REQ / ACK` | **Implemented** | Start quest (`0x0076BA00`) |
| 2076 / 2077 | `eEGS_QUEST_COMPLETE_REQ / ACK` | **Implemented** | Turn in quest, gold/EXP/items (`0x00656870`) |
| 2082 / 2083 | `eEGS_CLEAR_TUTORIAL_REQ / ACK` | **Implemented** | Complete tutorial, enter Act 1 (`0x006E5CE0`) |
| 2084 / 2085 | `eEGS_CHECK_TUTORIAL_REQ / ACK` | **Implemented** | Tutorial status query |
| 2094 / 2095 | `eEGS_NPC_FIRST_MEET_REQ / ACK` | **Implemented** | NPC introductory dialogue (`0x00762E40`) |
| 2346 / 2347 | `eEGS_TUTORIAL_QUEST_START_REQ / ACK` | **Implemented** | Tutorial quest chain init (`0x006481E0`) |
| 2358 | `eEGS_GUIDE_BEGINNER_UPDATE_REQ` | **Implemented** | Beginner guide tooltip completion (`0x0079A3B0`) |
| 2410 | `eEGS_QUEST_HISTORY_REFRESH_NOT` | **Implemented** | Restores completed quest log (`0x0076C1E0`) |
| 2078 / 2079 | `eEGS_QUEST_GIVEUP_REQ / ACK` | **Implemented** | Abandon active quest (`0x006223B0`) |
| 2080 / 2081 | `eEGS_QUEST_FAIL_REQ / ACK` | **Implemented** | Quest fail status handling (`0x006223B0`) |

### 5. Dungeon, Monsters & Combat (Opcodes 5001 - 5095, 2422, 2448)
| Opcode Pair | Name | Status | Function / Handler |
|---|---|---|---|
| 5001 / 5002 | `eERC_CREATE_ROOM_REQ / ACK` | **Implemented** | Create dungeon instance room (`0x00788320`) |
| 5009 / 5010 | `eERC_CHANGE_MAPCODE_REQ / ACK` | **Implemented** | Select dungeon stage map code (`0x006D4A00`) |
| 5013 / 5014 | `eERC_START_GAME_REQ / ACK` | **Implemented** | Launch dungeon session (`0x00788640`) |
| 5015 / 5016 | `eERC_CHANGE_TEAM_REQ / ACK` | **Implemented** | Switch team in multiplayer match |
| 5030 / 5031 | `eERC_USER_MOVE_NOT` | **Implemented** | Position and movement synchronization |
| 5043 / 5044 | `eERC_CHANGE_DUNGEON_GATE_REQ / ACK`| **Implemented** | Dungeon gate selection (`0x007894F0`) |
| 5045 / 5046 | `eERC_BACK_TO_SQUARE_REQ / ACK` | **Implemented** | Leave dungeon, return to town (`0x007897F0`) |
| 5049 / 5050 | `eERC_INVITE_REQ / ACK` | **Implemented** | Party invitation (`0x00758700`) |
| 5054 / 5055 | `eERC_ACCEPT_INVITE_REQ / ACK` | **Implemented** | Accept party invitation |
| 5063 | `eERC_MONSTER_DEAD_REQ` | **Implemented** | Monster killed event (`0x0078A690`) |
| 5064 | `eERC_DROP_ITEM_NOT` | **Implemented** | Monster loot dropped on ground (`0x00784D10`) |
| 5086 | `eERC_CHANGE_EXP_NOT` | **Implemented** | EXP bar update notification (`0x007775F0`) |
| 5087 | `eERC_LEVEL_UP_NOT` | **Implemented** | Level-up animation and stat boost (`0x0078CCF0`) |
| 5090 / 5091 | `eERC_CHOICE_REWARD_PARTYRANK_REQ/ACK`| **Implemented** | End-of-dungeon reward card pick (`0x0078D660`)|
| 5093 / 5094 | `eERC_CHAR_DEAD_NOT / ACK` | **Implemented** | Player character death event (`0x0078D9C0`) |
| 5095 | `eERC_CHANGE_DUNGEON_LAYER_NOT` | **Implemented** | Enter next dungeon layer/sub-area (`0x007900B0`)|
| 2422 | `eEGS_ACTIVE_WARFLAG_REQ` | **Implemented** | Active war flag state update (`0x0079C300`) |
| 2448 / 2449 | `eEGS_REBIRTH_COIN_REVIVE_REQ / ACK`| **Implemented** | Revive in dungeon using coin (`0x00795450`) |
| 5065 / 5066 | `eERC_PICK_UP_ITEM_REQ / ACK` | **Implemented** | Pick up dropped loot from ground (`0x0078AD80`)|
| 5068 | `eERC_PICK_UP_ITEM_RESULT_ACK` | **Implemented** | Broadcast item picked up by player (`0x0078AD80`)|
| 5114 | `eERC_GET_DROP_AR_NOT` | **Implemented** | Gold dropped by monster picked up (`0x00792700`)|
| 5096 | `eERC_UPDATE_CHAR_INFO_NOT` | **Implemented** | Real-time gear and visual sync (`0x0078C990`) |
| 5344 / 5345 | `eERC_TREASURE_START / END_NOT` | **Implemented** | Treasure dungeon instance rounds (`0x007722F0`) |
| 5346 | `eERC_CITADEL_REWARD_NOT` | **Implemented** | Citadel instance stage rewards (`0x007833F0`) |
| 5362 | `eERC_GOLDGOBLIEN_APPEAR_NOT` | **Implemented** | Gold Goblin dungeon encounter (`0x007A6D10`) |
| 5363 / 5364 | `eERC_GOLDGOBLIEN_ATTACK_REQ/ACK` | **Implemented** | Attack Gold Goblin (`0x00784A10`) |
| 5365 / 5366 | `eERC_GOLDGOBLIEN_DEAD_REQ/ACK` | **Implemented** | Defeat Gold Goblin and claim loot (`0x00784CA0`)|
| 5060 / 5061 | `eERC_MONSTER_SPAWN_NOT` | Planned | Dynamic monster wave spawn |

### 6. Social, Friends, Guilds & Post (Opcodes 2128 - 2237, 2569 - 2595, 5040 - 5041)
| Opcode Pair | Name | Status | Function / Handler |
|---|---|---|---|
| 5040 / 5041 | `eERC_CHAT_REQ / ACK` | **Implemented** | Chat & GM console commands (`0x007AC890`) |
| 2128 / 2129 | `eEGS_USE_SPEAKER_ITEM_REQ / ACK` | **Implemented** | Megaphone world shout message (`0x0077F320`) |
| 2131 / 2132 | `eEGS_FRIEND_LIST_REQ / ACK` | **Implemented** | Request friends list (`0x00752110`) |
| 2133 / 2134 | `eEGS_FRIEND_LIST_UPDATE_REQ / ACK` | **Implemented** | Update friend memo (`0x00752E80`) |
| 2135 / 2136 | `eEGS_FRIEND_LIST_DELETE_REQ / ACK` | **Implemented** | Remove friend from list (`0x00759560`) |
| 2139 / 2140 | `eEGS_FRIEND_LIST_ADD_REQ / ACK` | **Implemented** | Send friend request (`0x007591A0`) |
| 5118 | `eERC_FRIEND_MY_CONNECTION_NOT` | **Implemented** | Friend came online notification (`0x0077A8A0`)|
| 5119 | `eERC_FRIEND_MY_DISCONNECTION_NOT` | **Implemented** | Friend went offline notification (`0x00758FA0`)|
| 5121 / 5122 | `eERC_GUILD_CREATE_PROPOSAL_REQ/ACK`| **Implemented** | Guild name availability check (`0x00759750`) |
| 2150 / 2151 | `eEGS_GUILD_CREATE_REQ / ACK` | **Implemented** | Register new guild (`0x00793720`) |
| 2155 / 2156 | `eEGS_GUILD_PERSON_JOIN_REQ / ACK` | **Implemented** | Accept guild member join (`0x0075A220`) |
| 2160 / 2161 | `eEGS_GUILD_INVITE_REQ / ACK` | **Implemented** | Invite character to guild (`0x00759870`) |
| 2162 / 2163 | `eEGS_GUILD_PERSON_LEAVE_REQ / ACK` | **Implemented** | Leave current guild (`0x00759CA0`) |
| 2179 / 2180 | `eEGS_GUILD_MONEY_IN_REQ / ACK` | **Implemented** | Deposit gold into guild bank (`0x00794250`) |
| 2181 / 2182 | `eEGS_GUILD_MONEY_OUT_REQ / ACK` | **Implemented** | Withdraw gold from guild bank (`0x00794470`) |
| 2183 / 2184 | `eEGS_GUILD_LEVEL_UP_REQ / ACK` | **Implemented** | Upgrade guild level (`0x00753380`) |
| 2185 / 2186 | `eEGS_GUILD_NOTICE_MODIFY_REQ / ACK` | **Implemented** | Set guild announcement (`0x0075A120`) |
| 2188 / 2189 | `eEGS_GUILD_NOTICE_DELETE_REQ / ACK` | **Implemented** | Delete guild announcement (`0x0074B830`) |
| 2214 / 2215 | `eEGS_GUILD_ALL_SKILL_INIT_REQ / ACK` | **Implemented** | Reset guild skill tree (`0x00752D80`) |
| 2219 / 2220 | `eEGS_POST_LIST_REQ / ACK` | **Implemented** | Open mailbox mail list (`0x00753BE0`) |
| 2221 / 2222 | `eEGS_POST_SEND_REQ / ACK` | **Implemented** | Compose and send mail (`0x00795F40`) |
| 2223 / 2224 | `eEGS_POST_READ_REQ / ACK` | **Implemented** | Read mail content (`0x0075A660`) |
| 2225 / 2226 | `eEGS_POST_GET_APPEND_ITEM_REQ / ACK` | **Implemented** | Claim attached items and gold (`0x0077F8E0`) |
| 2227 | `eEGS_POST_NEW_ARRIVAL_NOT` | **Implemented** | Notification when new letter arrives (`0x007965B0`) |
| 2234 / 2235 | `eEGS_POST_RETURN_REQ / ACK` | **Implemented** | Return letter with items to sender (`0x00771470`) |
| 2236 / 2237 | `eEGS_POST_DELETE_REQ / ACK` | **Implemented** | Batch delete letters (`0x007715F0`) |
| 2228 / 2229 | `eEGS_DEPOT_SAVE_AR_REQ / ACK` | **Implemented** | Deposit gold into personal warehouse (`0x00795220`) |
| 2230 / 2231 | `eEGS_DEPOT_LOAD_AR_REQ / ACK` | **Implemented** | Withdraw gold from personal warehouse (`0x00795490`) |
| 2461 / 2462 | `eEGS_DEPOT_SLOT_EXTEND_REQ / ACK` | **Implemented** | Expand depot storage tab slots (`0x007A3E20`) |
| 2310 / 2311 | `eEGS_CHAR_NICK_CHANGE_REQ / ACK` | **Implemented** | Character rename scroll (`0x00780200`) |
| 2314 / 2315 | `eEGS_GUILD_NAME_CHANGE_REQ / ACK` | **Implemented** | Guild rename scroll (`0x00780590`) |
| 2319 / 2320 | `eEGS_KEYBOARD_SET_CUSTOM_KEY_REQ/ACK` | **Implemented** | Custom keybindings mapping (`0x00753960`) |
| 2569 / 2570 | `eEGS_ATTENDANCE_CHECK_REQ / ACK` | **Implemented** | Daily attendance reward check |
| 2594 / 2595 | `eEGS_HTTPNOTICE_CHECK_REQ / ACK` | **Implemented** | Web event notice check (`0x005A5110`) |

### 7. Pets, Mounts & Monster Taming (Opcodes 2348 - 2351, 2434 - 2438, 2464 - 2474)
| Opcode Pair | Name | Status | Function / Handler |
|---|---|---|---|
| 2348 / 2349 | `eEGS_TAMEING_MONSTER_INSERT_REQ / ACK` | **Implemented** | Capture/tame monster (`0x00771A00`) |
| 2350 / 2351 | `eEGS_TAMEING_MONSTER_DELETE_REQ / ACK` | **Implemented** | Release tamed monster (`0x00771BB0`) |
| 2434 / 2435 | `eEGS_RIDING_CALL_REQ / ACK` | **Implemented** | Summon mount (`0x007A3820`) |
| 2436 / 2437 | `eEGS_RIDING_DISMISS_REQ / ACK` | **Implemented** | Dismiss mount (`0x007A3B10`) |
| 2438 | `eEGS_RIDING_SPEED_SYNC` | **Implemented** | Mount movement speed synchronization (`0x007A3DA0`) |
| 2464 / 2465 | `eEGS_PET_CALL_REQ / ACK` | **Implemented** | Summon pet (`0x007A4100`) |
| 2466 / 2467 | `eEGS_PET_DISMISS_REQ / ACK` | **Implemented** | Dismiss pet (`0x007A4390`) |
| 2468 / 2469 | `eEGS_PET_INFO_REQ / ACK` | **Implemented** | Query pet status and stats (`0x007A4620`) |
| 2470 / 2471 | `eEGS_PET_FEED_REQ / ACK` | **Implemented** | Feed pet to replenish satiety (`0x007A4950`) |
| 2472 / 2473 | `eEGS_PET_NAME_CHANGE_REQ / ACK` | **Implemented** | Rename pet scroll (`0x007A4C80`) |
| 2474 | `eEGS_PET_LEVEL_UP_NOT` | **Implemented** | Pet level-up event notification (`0x007A4F10`) |

### 8. PvP Arena, Duels & League Ladders (Opcodes 2304 - 2309, 2446 - 2457, 2475 - 2478, 2550 - 2553, 5097 - 5113, 5138 - 5166, 5269 - 5275)
| Opcode Pair | Name | Status | Function / Handler |
|---|---|---|---|
| 5097 / 5098 | `eERC_DUEL_START_REQ / ACK` | **Implemented** | Start 1v1 duel (`0x006CBE60`) |
| 5099 | `eERC_DUEL_START_NOT` | **Implemented** | Broadcast duel start in town (`0x006CCDF0`) |
| 5100 / 5101 | `eERC_DUEL_REQUEST / ACK` | **Implemented** | Challenge player to duel (`0x006C0A10`) |
| 5105 / 5106 | `eERC_DUEL_RESULT / ACK` | **Implemented** | Duel match result (`0x006CC6B0`) |
| 5108 | `eERC_DUEL_GIVEUP_NOT` | **Implemented** | Duel forfeit / surrender (`0x006CC8E0`) |
| 5112 / 5113 | `eERC_DUEL_REFUSE / ACK` | **Implemented** | Decline duel request (`0x006B4120`) |
| 2304 / 2305 | `eEGS_ARENA_SQUARELIST_REQ / ACK` | **Implemented** | List arena channels (`0x004B67F0`) |
| 2306 / 2307 | `eEGS_ARENA_GET_ROOMLIST_REQ / ACK` | **Implemented** | List active arena rooms (`0x004B96D0`) |
| 2308 / 2309 | `eEGS_ARENA_GET_INVITELIST_REQ / ACK`| **Implemented** | List arena invitations (`0x004B4680`) |
| 5138 | `eERC_ARENA_JOIN_SQUARE_ACK` | **Implemented** | Enter arena lobby square (`0x007584A0`) |
| 5145 / 5146 | `eERC_ARENA_JOIN_ROOM_REQ / ACK` | **Implemented** | Join arena match room (`0x004B4CD0`) |
| 5148 / 5149 | `eERC_ARENA_LEAVE_ROOM_REQ / ACK` | **Implemented** | Leave arena match room (`0x004B5030`) |
| 5153 / 5154 | `eERC_ARENA_CREATE_ROOM_REQ / ACK` | **Implemented** | Create new arena room (`0x004B58E0`) |
| 5165 / 5166 | `eERC_ARENA_BACK_TO_SQUARE_ACK` | **Implemented** | Return from arena to town square (`0x00758550`) |
| 5269 / 5270 | `eERC_ARENA_TEAM_CREATE_REQ / ACK` | **Implemented** | Create arena team (`0x0049BEF0`) |
| 5271 / 5272 | `eERC_ARENA_TEAM_JOIN_REQ / ACK` | **Implemented** | Join arena team (`0x0049C4B0`) |
| 5274 / 5275 | `eERC_ARENA_TEAM_LEAVE_REQ / ACK` | **Implemented** | Leave arena team (`0x00490100`) |
| 2550 / 2551 | `eEGS_LEAGUE_SEASON_ARENA_GET_RANK_REQ/ACK` | **Implemented** | Arena season ladder rankings (`0x00499DC0`) |
| 2552 / 2553 | `eEGS_LEAGUE_SEASON_ARENA_GET_MY_RANK_REQ/ACK`| **Implemented** | Player's arena rank and score (`0x00492A10`) |
| 2709 / 2710 | `eEGS_USE_ARENA_SP_ITEM_REQ / ACK` | **Implemented** | Consume arena SP item (`0x007A7CA0`) |

---

## Rigorous Verification & Testing Strategy

### 1. Headless Continuous Integration Matrix
All emulator functions must execute headless through `python -m unittest discover -s tests -v` (150 tests):
- `test_character_store.py`: CRUD, case-insensitive duplicate prevention, inventory initialization, SQLite repository.
- `test_transport.py`: Scalar boundaries, fragmented/coalesced TCP frames, varuint limits, zlib compression.
- `test_wire_messages.py`: Unit encode/decode matching disassembled client schemas for all opcodes.
- `test_lobby_flow.py`: Full login, server list, channel list, character list, creation, deletion, selection.
- `test_inventory_flow.py`: Drag, equip, consume, bag switch, bag rename, quickslots, skill learn, buy, sell, repurchase.
- `test_dungeon_flow.py`: Gate select, map code, dungeon start, layer switch, combat, dead/revive, card rewards, back to square.
- `test_quest_flow.py`: Quest acceptance, reward calculation, level-up progression, SP boost, active tracker restore.
- `test_social_flow.py`: Friends, guild creation, guild bank deposit/withdraw, guild level up, notice edit/delete, skills reset.
- `test_mail_flow.py`: Mailbox lifecycle, multiple item & gold attachments, read, claim, delete, return.
- `test_pets_flow.py`: Mount summon/dismiss/speed, pet summon/feed/rename/level, monster taming capture/release.
- `test_arena_flow.py`: Arena rooms, join/leave, team creation/switching, league season ladder rankings, duels.
- `test_world_flow.py`: Spatial grid management, multi-client square presence, Opcode 5096 mutual character visual updates.
- `test_cash_shop_flow.py`: Offline Steam Cash Shop purchase (2712/2714), package unboxing, random boxes.
- `test_relay_flow.py`: Relay server PIDL handshake, group join isolation.
- `test_jpk.py`: Archive unpacking, byte-identical repack, key cipher verification.
- `test_hashing.py`: Client DJB2 hashing parity.

### 2. Live Client Graphics & UI Verification Matrix
Manual and automated client execution checklist (`tools/gamectl.py enter-lobby` / `live test`):
- [x] Initial splash screen, intro video skip, server selection popup.
- [x] Channel selection dialog and ping display.
- [x] Character creation: Warrior, Knight, Hunter, Mage, Thief, Fighter, WHunter models display with starting gear.
- [x] Character selection: 3D character preview, level display, location display.
- [x] Town entry: Act 1 town 3D geometry renders, character controllable via WASD/arrow keys.
- [x] NPC Dialogue: talk box appears, advances dialogue with Space key.
- [x] Store Window: talking to shop NPC opens store UI with item tabs.
- [ ] Store Transactions: buying potion decrements gold UI, adds item icon in bag cell; selling removes icon and updates gold UI.
- [ ] Equipment Window: pressing 'I'/'E' shows worn gear; dragging weapon to slot equips with character mesh update.
- [ ] Skill Window: pressing 'K' shows skill tree; spending SP increases skill level and enables skill on hotbar.
- [ ] Dungeon Entry: walking into dungeon gate loads dungeon map (`Act1_G1_A10`), spawns monsters with health bars.
- [ ] Combat Animation: attacking monster plays hit sound, displays floating damage numbers, triggers monster death animation.
- [ ] Level-Up Fanfare: EXP bar reaches 100%, plays level-up visual fanfare, displays "Level Up!" text, increments character level display.
- [ ] Card Reward UI: completing dungeon displays 4 face-down cards, clicking a card flips it and grants selected reward item.
- [ ] Return to Town: portal returns player back to town square seamlessly.

### 3. Boundary, Network Fuzzing & Malformed Packet Tests
- Fuzz JSerBuffer with malformed varuint terminal bits (missing terminal bit 7, oversized streams).
- Fuzz scalar reader with invalid width bytes (0, 3, 5, 255).
- Send out-of-order packets (e.g. gameplay packet before authentication) to verify graceful disconnection rather than server crash.
- Flood TCP stream with truncated frames to ensure memory buffers do not leak or grow unbounded.

### 4. Multi-Client Concurrency Tests
- Simulate 10 simultaneous headless clients performing login, character select, and town movements in parallel.
- Verify thread safety of character data storage (`data/characters.json` or SQLite).
- Assert that broadcast events (e.g. megaphone 2128 or town movement 5030) are delivered to all connected clients without deadlocks.

---

## Architecture Refactoring & Clean Code Plan

### 1. Splitting `messages.py` into Domain Packages
Currently, `src/darkblood/games/network/messages.py` exceeds 2000 lines of code. It will be refactored into:
- `src/darkblood/games/network/messages/`
  - `__init__.py` (re-exports for backwards compatibility)
  - `base.py` (common dataclass utilities, tag constants, `ItemDropEntry`)
  - `lobby.py` (GameServer, Channel, Character, CreateChar, DeleteChar, SelectChar)
  - `commerce.py` (StoreInfo, BuyItem, SellItem, Repurchase, ItemUpgrade, LifeWater, Bags)
  - `combat.py` (MonsterDead, DropItem, CharDead, RebirthCoin, LevelUp, ChangeExp)
  - `dungeon.py` (Room, DungeonGate, MapCode, StartGame, DungeonLayer, WarFlag, CardReward, BackToSquare)
  - `social.py` (FriendList, Mail, Speaker, Attendance, HttpNotice)
  - `guild.py` (GuildCreate, GuildJoin, GuildLeave, GuildMoney, GuildLevel, GuildNotice, GuildSkill)

### 2. Asynchronous Storage Layer Abstraction
- Replace direct JSON file writes with an abstract storage repository:
  ```python
  class ICharacterRepository(ABC):
      async def get_character(self, account: str, char_id: int) -> Optional[Character]: ...
      async def save_character(self, account: str, character: Character) -> None: ...
      async def delete_character(self, account: str, char_id: int) -> bool: ...
      async def list_characters(self, account: str) -> List[Character]: ...
  ```
- Implement two backends:
  - `JsonCharacterRepository`: backward-compatible file storage.
  - `SqliteCharacterRepository`: production ACID-compliant local database.

### 3. Server Core & Session Decoupling
- Separate raw socket IO handling from game business logic.
- Extract `GameWorld`:
  - Keeps track of spatial grid partitioning for player movement broadcasting.
  - Manages active dungeon instances and instance cleanup on exit.

---

## Future Improvements & Quality-of-Life Tools

1. **Integrated Web Dashboard & Live Packet Inspector**:
   - Lightweight built-in local web dashboard on `http://127.0.0.1:9405`.
   - Real-time display of connected clients, active maps, character stats, and live decoded event logs.
   - Interactive character editor: edit level, gold, add items, reset quests.

2. **In-Game GM Commands & Console**:
   - Chat commands executed by typing in town or dungeon chat:
     - `/gold <amount>`: adds gold immediately.
     - `/levelup <levels>`: increments character level and awards SP.
     - `/item <item_code> <count>`: grants items directly into inventory.
     - `/teleport <map_code>`: moves character to specified map/square.
     - `/clearquest <quest_id>`: sets quest as completed.
     - `/spawn <monster_id>`: spawns monster at current coordinates.

3. **Asset Pipeline & Modding Toolkit**:
   - Automated GUI / CLI tool to browse, unpack, modify, and repack client JPK archives.
   - Translation / localization support: extract and replace client dialogue strings in `questlist.lua`.

4. **Port to C# / .NET 8 (MHServerEmu Architecture)**:
   - Once all opcode schemas and game formulas are stabilized in Python, port cleanly to high-performance C# server architecture matching MHServerEmu.
