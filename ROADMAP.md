# Roadmap — Dark Blood Offline Server Emulator

Updated **November 20, 2026**.

Final objective: launch without the original services, establish a local session, persist character and world state, enter maps/dungeons, and provide full offline singleplayer and LAN multiplayer gameplay.

---

## Current Milestones Overview

| Milestone | Scope | Status | Notes |
|---|---|---|---|
| **P0: Enter the World** | Handshake, Auth, Lobby, Selection, Town entry | **Verified** | Town rendered, character visible, movement confirmed |
| **P1: Transport & Serialization** | ProudNet framing, JSerBuffer, crypto, compression | **Verified** | Full regression test suite (`test_transport.py`), 11 tests |
| **P2: Lobby & Account** | Character list, create, delete, versioned persistence | **Verified** | Name validation, persistent SQLite store, default gear |
| **P3: Gameplay & Economy** | Combat, dungeons, drops, store, level-up, guild | **Verified (~95%)** | Live 11-17: tutorial, equip/swap, stats, death/revive, cash shop, depot, pets, mounts, loot. 11-20: result screen, dyeing, tutorial-exit gear; gate history/quest variants, EXP bar, town AR, chest names and counter achievements await live checks |
| **P4: Assets & Config** | JPK unpacker, Lua tables, dictionaries | **In Progress (~80%)** | Validated decoder, bundled Cash Shop purchase catalog, store/quest/stat/monster tables parsed |
| **P5: Stability & Launcher** | Steam shim, process supervisor, gamectl, MCP | **In Progress (~85%)** | Clean headless test runner, process cleanup, GM web dashboard |
| **P6: Multiplayer & Relay Sync** | P2P client relay, party instances, town broadcast | **In Progress** | Town peer rendering and movement verified with two live clients. Shared dungeon instances remain open. |
| **P7: Commerce & Post System** | P2P trade, personal shops, mail/attachments, depot | **Verified (~95%)** | P2P trade, full mailbox with attachments, depot AR/slots, player stalls & broker marketplace live |
| **P8: Guild Warfare & Arena PvP** | Guild wars, sieges, arena rooms, ladder matchmaking | **In Progress (~90%)** | Guild banking/notice/skills live; duels, arena rooms, teams, league rankings live; siege warfare next |
| **P9: Refactoring & Architecture** | Modular messages, GM dashboard, opcode ownership, world lifecycle | **In Progress** | Startup-validated opcode registry, generated opcode registry doc, per-connection identity, indexed town presence, shared party-invite path. 176 headless tests pass. Shared instance ownership remains open. |
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
  - Two live clients displayed each other's characters and movement.
    `5030/5031` changes the layer, and town positions use the peer transport.
  - Handle player join notification (`5021 eERC_USER_JOIN_SQUARE_NOT`) and player leave notification (`5022 eERC_USER_LEAVE_SQUARE_NOT`).
  - Live clients crossed between layers and exchanged reliable relay control
    frames. The relay now binds group membership to the request's character
    UID. Both client bindings were checked after a live reconnect. The
    same-connection character replacement is covered headlessly.
  - Chat broadcasting: normal chat, whisper, party chat, guild chat, and world megaphone (2128/2129).
  - Live clients send town updates with 512-bit ProudNet Fast keys.
    The relay forwards `0x16` updates as `0x1A` within the group.
  - The two-client rerun measured a 215 ms median town revision interval
    with the shim and showed the correct “Offline” server name.
  - Profile client revision eligibility and playback separately from relay
    forwarding. Use per-instance command ownership for shared room work.
- [x] **Party System**:
  - Party creation and invite (`2100 eEGS_PARTY_INVITE_REQ` / `2101 eEGS_PARTY_INVITE_ACK`, `5049/5050 eERC_INVITE_REQ/ACK`, `5051 eERC_INVITE_NOT`).
  - Party join, leave, and kick (`2102/2103 eEGS_PARTY_JOIN`, `5054/5055 eERC_ACCEPT_INVITE`, `5056 ACCEPT_INVITE_NOT`, `2104/2105 LEAVE`, `2106/2107 KICK`).
  - Master delegation and leader promotion upon departure.
  - Validate the corrected 5051 invitation notice in the client dialog.
  - Square re-registration preserves party membership and updates the member session.
    Stale disconnect/leave requests preserve replacement sessions (167 tests pass
    locally on Cristian's machine, 2026-11-18, live verification pending).
- [ ] **Co-op Dungeon Instances**:
  - Synchronize party dungeon entry so all party members enter the same dungeon instance.
  - Complete the 5004 member fields and shared room and relay routing. The 5003
    request and outer 5004 reply are mapped in `docs/PROTOCOL.md`.
  - Verify how clients populate 5014's peer maps.
    The three map readers and the local inventory vector are documented in `docs/PROTOCOL.md`.
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
- [ ] **Schema-generated messages** (`schemas/*.jsch` → `tools/gen_messages.py`, see `schemas/README.md`):
  - [x] Generator with a Python backend, opcode validation against `assets/opcodes.tsv`, a `--check` unit test, and the `mail` domain converted (2026-11-20).
  - [ ] Convert the remaining domains one at a time, checking the request header and struct tags against the client senders and readers.
  - [ ] Add a C# backend for P10 that emits the same schemas as C# message classes.
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

## Opcode Reference

Per-opcode status lives in [`docs/OPCODE_REGISTRY.md`](docs/OPCODE_REGISTRY.md), generated by
`python tools/gen_opcode_registry.py` from the client's own opcode table, the shim's handler
map and the server dispatcher. The hand-written tables that used to be here had drifted from
the client enum names (for example 2108 listed as item disassembly; the client calls it
`eEGS_CHEAT_DELETE_ALL_INVEN_ITEM_ACK`) and were removed.

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
