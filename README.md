# Dark Blood Online — offline emulator in development

This project aims to run the supplied Dark Blood client against a local server. **Offline gameplay is not working yet**, but the client now gets through login to character creation on the local server.

Verified progress (November 16, 2026):

- The client starts with the Steam shim; its TCP connection to port `9400` is redirected to `127.0.0.1:9400`.
- The real ProudNet key exchange runs locally (RSA-OAEP + AES); encrypted client requests are decrypted and checked.
- Title screen → **Server List** ("Offline") → **Channel List** ("Channel 1") → **character select** → **character creation**. Created characters persist in `data/darkblood.db` (SQLite).
- Next step: the select-character response (opcode 2007) that loads the game world.

## Documentation

- [AGENTS.md](AGENTS.md): instructions for the next agent.
- [ROADMAP.md](ROADMAP.md): priorities, blockers, and acceptance criteria.
- [Research status](docs/STATUS.md): findings, local evidence, tools, and reproduction.
- [Recovered protocol](docs/PROTOCOL.md): framing, handshake, serialization, and function addresses.
- [Client analysis](docs/REVERSE_ENGINEERING.md): protection, unpacking, and hooks.

## Components

| Component | Purpose / status |
| --- | --- |
| `client_hook/steam_api_hook.c` | Experimental x86 shim: Steam exports, minimal User/Friends interfaces, TCP redirect, diagnostics |
| `run_server.py` | Local server entry point (127.0.0.1:9400 game, 9401 relay) |
| `src/darkblood/` | Server package, MHServerEmu-like layout: see [ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| `src/darkblood/core/` | ProudNet framing and crypto, JSerBuffer/JEvent serialization |
| `src/darkblood/frontend/` | Listeners, handshake/key exchange, relay, wire logging |
| `src/darkblood/games/` | Game session, handlers per domain, messages, entities, client data readers |
| `src/darkblood/player_management/` | Character persistence (`data/darkblood.db`, SQLite) |
| `assets/opcodes.tsv` | Opcode names extracted from the client |
| `tools/gamectl.py` | CLI/library: start/stop session, screenshots, input, intro skip, decoded events |
| `tools/mcp_server.py` | MCP stdio server exposing `gamectl` (registered in `.mcp.json`) |
| `tools/decomp.ps1` | One-command focused Ghidra decompilation |
| `tools/capture_server.py` | Passive loopback TCP recorder |
| `tools/debug_client.c` | Bounded launches, thread inspection, and image dumps |
| `tools/image_to_pe.py` | Memory dump to static-analysis PE; output is not a playable client |
| `tools/FocusedDecompile.java` | Focused Ghidra decompilation at requested addresses |
| `tools/jpk_extractor.py` | Earlier archive extractor; decryption needs verification |

## Run it on this machine

Requires Windows, Python 3.8+, and MSVC x86. The game client and assets are not included in this repository. The test copy is `research/client/` (its `Data` is a junction to the original assets; see [STATUS.md](docs/STATUS.md) to prepare one).

Build and deploy the shim with the game closed:

```powershell
client_hookuild.bat
Copy-Item client_hook\steam_api.dll research\client\steam_api.dll
```

Then:

```powershell
python tools\gamectl.py start          # server + client
python tools\gamectl.py enter-lobby    # skip intro, pick server and channel
python tools\gamectl.py events         # decoded protocol log
python tools\gamectl.py stop
```

Or play manually: `python run_server.py`, then launch `research\client\DarkBlood.exe` with `$env:__COMPAT_LAYER = 'RunAsInvoker'`. Click once the intro is loaded to skip it, press Enter on the server and channel lists, and use Create on character select.

### MCP server

`.mcp.json` registers `tools/mcp_server.py` as the `darkblood` MCP server, so MCP clients such as Claude Code opened in this repository can call `game_start`, `game_enter_lobby`, `game_screenshot`, `game_click`, `game_keys`, `game_type`, `game_events`, `game_wait_event`, `game_hook_log` and `game_stop`.

## Current limitations

UDP/P2P, fast encryption (type 0x27), and the game protocol after character creation are not implemented. Several character fields have unknown meaning. The shim contains build-specific addresses and incomplete Steam interfaces; later calls can still crash. The asset decryption key is unverified.

`research/`, `logs/`, compiled DLLs, and memory dumps are ignored by Git. The documentation preserves the information needed to resume without those local artifacts.
