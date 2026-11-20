# Dark Blood Online — Offline Server Emulator

A Python-based offline server emulator and reverse-engineering project for **Dark Blood Online**.

The project allows playing the original client offline via a local server (`127.0.0.1:9400` game, `127.0.0.1:9401` relay) backed by SQLite persistence, real ProudNet encryption, Lua game data integration, and automated headless testing.

---

## Current Status & Implemented Features

### 1. Connection & Protocol Security
* **ProudNet Transport & Cryptography**: Authentic RSA-OAEP + AES key exchange, packet framing, scalar/varint handling, and TCP stream reassembly.
* **Client Hook & Auto-Reconnect**: Lightweight x86 Steam API shim (`client_hook/steam_api_hook.c`) redirecting IPv4 connections to loopback, providing borderless fullscreen, and supporting seamless reconnect to the server list upon server restart.

### 2. Lobby & Character Management
* **Server & Channel Lists**: Interactive server and channel selection with live character counts.
* **Character Creation & Selection**: Full character creation for all classes (Warrior, Knight, Thief, Hunter, Mage, Fighter) persisting in SQLite (`data/darkblood.db`).
* **Game World Loading (Opcode 2007)**: Full character state serialization (attributes, stats, equipment slots, bag inventories, quickslots, active quests, locked skills).
* **Adult Blood Effect**: Unlocked and ungrayed in options menu (`m_bAdultUser = True` in welcome 5020).

### 3. World & Town Gameplay
* **Town Play**: Town square loading (Northern Elwood, etc.), local character movement, and chat broadcasts.
* **Multi-Client World Presence**: Two live clients can see each other and synchronize movement in the same town layer through the local TCP relay.
* **Channel & Layer Transitions**: Switching between channels and field layers cleanly.

### 4. Dungeons, Combat & Quests
* **Dungeon Lifecycle**: Tutorial (with skip), Act 1 dungeons, layer transitions and combat loops.
* **Dungeon Gate (5044)**: Per-character clear history unlocks difficulties in order (Normal first), and active quests unlock their quest variant of a dungeon.
* **Monster Combat & EXP**: Monster death (`5063`) grants EXP from `monster.lua`, drives level-up (`5087`) and updates the EXP bar (`5086`).
* **Loot**: Drop tables from `itemlooting.lua`, drop announcement (`5064`), item and AR pickup (`5065`/`5068`/`5114`).
* **Quest Progress Tracking**: Kill and item objectives advance active quests with HUD updates (`2075`).
* **Dungeon Result Screen (5017 / 5018)**: Clear payload with party rank, box grade and the recovered 40-byte reward block; reward chest pick (`5090`/`5091`).
* **Player Death & Revive (5093 / 5094)**: Revive UI and rebirth coins.
* **Achievements**: Counter achievements progress from the client's division reports (`2446`), complete with `2330` and list in `2328`.

### 5. Inventory & Equipment
* **Item Management**: Drag-and-drop (`2036`/`2037`), stack division (`2250`), item use (`2038`), deletion (`2040`), equip and weapon swap (`2042`), quickslots (`2044`/`2046`).
* **Appearance**: Worn gear on character-select models (`2009`), hair and skin dyeing (`2210`/`2211`) persisted through login.
* **Crafting & Upgrades**: Durability repairs (`2145`), Avatar Zam socket insertion/removal (`2362`/`2364`), item upgrades (`2115`), and spirit weapons (`2338`).
* **Depot**: Gold deposits and withdrawals (`2228`–`2231`), shared depot expiry (`2242`), slot expansion (`2461`).

### 6. Skills & Combat Abilities
* **Skill Learning**: Single skill learning (`2050`) and full skill tree batch learning (`2697`/`2698`).
* **Skill State**: Skill lock/unlock toggles (`2117`/`2118`), skill speech macros (`2053`/`2055`), and skill book consumption (`2111`).

### 7. Commerce, Cash Shop & Social
* **NPC Stores & Buyback**: Store info catalogs (`2065`), item purchases with gold verification (`2067`), item selling (`2069`), and buyback (`2071`).
* **Offline Steam Cash Shop**: In-game cash shop purchases (`2712` -> unsolicited `2037` items + `2714`), cash packages (Type 36) and random boxes opening into bag slots.
* **Player-to-Player Trade**: Request, accept, item placement, gold stakes, lock, and completion (`5069`–`5084`).
* **Social & Guilds**: Friend list management, online presence notifications, memos, guild creation, guild bank deposits/withdrawals, guild level-up, and duel requests.

---

## Architecture & Codebase

The server is a Python package laid out like MHServerEmu so it can be ported to C# later:

```
src/darkblood/
├── core/               # ProudNet framing, crypto, JSerBuffer serialization, JHashString
├── frontend/           # Listeners: game (9400) and relay (9401)
├── player_management/  # Character creation rules and the SQLite store
└── games/
    ├── session.py      # GameSession and the startup opcode dispatcher
    ├── handlers/       # One service per domain: frontend, square, social, commerce,
    │                   # inventory, skills, quests, dungeon, arena, pets, mail
    ├── network/        # messages/<domain>.py dataclasses, result codes
    ├── entities/       # Character and Item wire structs
    ├── game_data/      # Readers for the normalized tables in assets/
    └── world.py, progression.py, achievements.py, loot.py, stalls.py
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the rules and the porting plan, and
[docs/OPCODE_REGISTRY.md](docs/OPCODE_REGISTRY.md) (generated) for every opcode's status.

---

## Automated Test Suite

The emulator includes **176 headless integration and unit tests** for network handshakes and protocol flows without launching graphics windows:

```bash
python -m unittest discover -s tests -v
```

* Tests cover: lobby handshake, character creation, SQLite storage, world entrance, monster EXP, dungeon gate history and result screen, inventory, depot and dyeing, quest progression, achievements, party invites, cash shop, arena duels, and wire serialization.

---

## Running Locally

### Prerequisites
* Windows OS
* Python 3.8+ (with `pefile` and `capstone`)
* MSVC x86 build tools (Visual Studio Community 2022)

### Cash Shop catalog

The repo ships the default purchase catalog at `assets/cash_shop.tsv`.
To replace it on your server, put a complete catalog in `data/cash_shop.tsv`
(or `$DARKBLOOD_DATA/cash_shop.tsv` when the server data directory is configured).
Use UTF-8 tab-separated columns `product_id`, `item_code`, and `quantity` and
match the product IDs sent by the client. Restart the server after editing a
loaded catalog. Offline purchases are free.

To populate a new catalog from an existing local extraction, run
`python tools/import_cash_shop.py`. The importer searches
`lua_src/data/dict/item_cash.lua` under `DARKBLOOD_CLIENT_DATA` or the adjacent
`darkblood-client-data` directory. It also accepts an explicit `--source` path
and creates a local override without overwriting an existing catalog.

Purchases use the TSV at runtime. Package and random box contents come from
`assets/cash_packages.tsv` and `assets/random_boxes.json`. Players connecting
to the server need no Cash Shop configuration.

### Game data

The server runs from the normalized tables in `assets/` and needs no extracted
client data. `python tools/export_assets.py` regenerates them from an extracted
client (`DARKBLOOD_CLIENT_DATA` or the adjacent `darkblood-client-data`).

### 1. Build & Deploy Client Hook
Build the x86 redirect hook with the game client closed:

```powershell
client_hook\build.bat
Copy-Item client_hook\steam_api.dll research\client\steam_api.dll
```

### 2. Start the Server
Run the local server from the repository root:

```powershell
python run_server.py
```
*Port `9400` handles game traffic; port `9401` handles relay traffic.*

### 3. Launch Client
Launch the working client in `research\client\`:

```powershell
$env:__COMPAT_LAYER = 'RunAsInvoker'
.\research\client\DarkBlood.exe
```

### 4. CLI & MCP Automation (`gamectl`)
Manage server and game automation with `tools/gamectl.py`:

```powershell
python tools\gamectl.py start          # Start server + client
python tools\gamectl.py enter-lobby    # Skip intro, pick server and channel
python tools\gamectl.py events         # Tail decoded protocol events
python tools\gamectl.py stop           # Stop processes
```

*An MCP stdio server is available via `.mcp.json` (`tools/mcp_server.py`) exposing automated gameplay, screenshot, and inspection tools.*

---

## Documentation

* [Session Handoff](docs/SESSION_HANDOFF.md): Latest findings, active tasks, and verified breakthroughs.
* [Research Status](docs/STATUS.md): Reverse-engineering notes, evidence logs, and memory offsets.
* [Recovered Protocol](docs/PROTOCOL.md): Wire framing, opcode tables, and client handler addresses.
* [Opcode Registry](docs/OPCODE_REGISTRY.md): Generated per-opcode status (`python tools/gen_opcode_registry.py`).
* [Architecture](docs/ARCHITECTURE.md): Package layout, rules, and porting notes.
* [Roadmap](ROADMAP.md): Milestones, priority items, and development trajectory.
* [Agent Guidelines](AGENTS.md): Working instructions, commit conventions, and synchronization rules.

---

## Current Roadmap & Next Steps

* **Shared dungeon instances**: Party rooms owned by one instance with synchronized membership.
* **Remaining zero-filled fields**: Item dyes, the unrecovered parts of the result and gate messages, and achievement rewards and group achievements (`2331`/`2332`, Type 2/3).
* **Mounts & Pets**: Mount summoning (`ridecall`) and pet items (`PetCall`).

See [ROADMAP.md](ROADMAP.md) for milestones.

---

## License

Copyright (C) 2026 the Dark Blood server emulator contributors.

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU Affero General Public License as published by the Free
Software Foundation, either version 3 of the License, or (at your option) any
later version. It is distributed WITHOUT ANY WARRANTY; see [LICENSE](LICENSE)
for the full text. If you run a modified version as a network service, the
AGPL requires you to offer its users the corresponding source code.

The license covers this repository's source and documentation only. The Dark
Blood client, its game data and any extracted assets are not part of this
project and are not covered by it.
