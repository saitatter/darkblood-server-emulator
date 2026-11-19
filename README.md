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
* **Dungeon Lifecycle**: Tutorial dungeon entry, Act 1 dungeons, zone transitions, and combat loops.
* **Monster Combat & EXP**: Monster death (`5063`) grants authentic EXP from client dictionary (`monster.lua`) and drives level-up progression.
* **Dynamic Lua Loot Drops**: Integrated drop tables (`itemlooting.lua`) rolling monster drops scaled by HP ratios and player class requirements; drop announcement (`5064`) and pickup (`5065`/`5068`).
* **Quest Progress Tracking**: Monster kills automatically advance active quest objectives (`quest_monster_objectives`) with real-time HUD updates (`2075`).
* **Dungeon Victory & Clear Screen (5017 / 5018)**: Complete victory payload (`0x007ADB60`) with dynamic party rank calculation (**SSS, SS, S, A**) based on score and kill count, reward box grades, and 40-byte player clear statistics payload.
* **Player Death & Revive (5093 / 5094)**: Character death opens the revive UI; resurrection consumes rebirth coins and restores HP.

### 5. Inventory & Equipment
* **Item Management**: Drag-and-drop (`2036`/`2037`), stack division (`2250`), item use (`2038`), item deletion (`2040`), and weapon swapping (`2042`).
* **Equipment Verification**: Slot-to-widget mapping (Weapon 1/2, Armor, Gloves, Boots, Belt, Shoulders, Cloak, Accessories, Helmet).
* **Crafting & Upgrades**: Durability repairs (`2145`), Avatar Zam socket insertion/removal (`2362`/`2364`), item upgrades (`2115`), and spirit weapons (`2338`).
* **Depot / Warehouse (Bancă)**: Gold deposits (`2228`/`2229`), gold withdrawals (`2230`/`2231`), shared depot expiry query (`2242`/`2243`), and depot slot expansions (`2461`/`2462`).

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

The emulator follows a clean domain-driven architecture inspired by MHServerEmu:

```
src/darkblood/
├── core/                       # ProudNet protocol, framing, cryptography, serialization
│   ├── hashing.py              # DJB2 hashing (jhash)
│   ├── proudnet/               # ProudNet transport, packet framing, handshake
│   └── serialization/          # JSerBuffer, JEvent varints, strip_prefix
├── frontend/                   # Network listeners (port 9400 game, 9401 relay)
│   ├── server.py               # BootstrapServer, Session connection lifecycle
│   └── relay.py                # Relay server listener
├── player_management/          # Character & account persistence
│   ├── characters.py           # Equipment rules, slot verification, rewards
│   └── store.py                # SQLite CharacterStore backend
└── games/                      # Game logic domain
    ├── session.py              # GameSession routing and event loop
    ├── game_data/              # Client dictionary readers (monsters, quests, items, loot)
    ├── network/messages/       # Typed dataclass wire encoders and decoders
    └── handlers/               # Modular domain mixins:
        ├── arena.py            # Arena & duel matches
        ├── commerce.py         # NPC shops, Steam billing, trade
        ├── dungeon.py          # Dungeon instance, combat, monster dead, clear ack
        ├── events.py           # World events, Gold Goblin
        ├── guild.py            # Guild administration, skills, bank
        ├── inventory.py        # Item drag/use/equip, bags, crafting, depot
        ├── lobby.py            # Server/channel list, character creation/select
        ├── quests.py           # Quest lifecycle & rewards
        ├── skills.py           # Skill tree learning & management
        ├── social.py           # Friends, party, chat, notifications
        ├── square.py           # Town square presence & broadcast
        └── system.py           # System settings, alarms, second password
```

---

## Automated Test Suite

The emulator includes **173 headless integration and unit tests** for network handshakes and protocol flows without launching graphics windows:

```bash
python -m unittest discover -s tests -v
```

* Tests cover: lobby handshake, character creation, SQLite storage, world entrance, monster EXP, dungeon victory rank calculation, inventory & depot flows, quest progression, cash shop, arena duels, and wire serialization.

---

## Running Locally

### Prerequisites
* Windows OS
* Python 3.8+ (with `pefile` and `capstone`)
* MSVC x86 build tools (Visual Studio Community 2022)

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
* [Roadmap](ROADMAP.md): Milestones, priority items, and development trajectory.
* [Agent Guidelines](AGENTS.md): Working instructions, commit conventions, and synchronization rules.

---

## Current Roadmap & Next Steps

* **P2P / UDP synchronization**: Multi-player dungeon synchronization.
* **Mounts & Pets**: Activating mount summoning (`ridecall`) and pet items (`PetCall`).
* **Party Dungeon Matchmaking**: Synchronizing dungeon parties across multiple client connections.
