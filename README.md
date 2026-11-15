# Dark Blood Online — offline emulator in development

This project aims to run the supplied Dark Blood client against a local server. **Offline gameplay is not working yet.**

Verified progress from the November 15, 2026 investigation:

- The client starts with the Steam shim and opens the game window.
- Its TCP connection to the original port `9400` is redirected to `127.0.0.1:9400`.
- The experimental ProudNet handshake is accepted: `OnJoinServerComplete result=0`.
- The client receives and deserializes application message `5020 / 0x139C`.
- Initialization advances to waiting for message `2403 / 0x0963`. Server selection, characters, and entering a map are not implemented or verified.

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
| `server/run_bootstrap.py` | Entry point used for live-client experiments on port 9400 |
| `server/proudnet.py` | ProudNet framing observed in the client |
| `server/game_wire.py` | JEvent serialization and experimental welcome message |
| `server/bootstrap_server.py` | Local handshake and wire logging |
| `tools/capture_server.py` | Passive loopback TCP recorder |
| `tools/debug_client.c` | Bounded launches, thread inspection, and image dumps |
| `tools/image_to_pe.py` | Memory dump to static-analysis PE; output is not a playable client |
| `tools/FocusedDecompile.java` | Focused Ghidra decompilation at requested addresses |
| `tools/jpk_extractor.py` | Earlier archive extractor; decryption needs verification |

`server/server.py`, `auth_server.py`, `lobby_server.py`, and `packet.py` belong to the earlier speculative prototype. Its `<uint16 length, uint16 opcode>` framing and `0x1001/0x2001` opcodes **have not been confirmed in the client**.

## Reproduce the current milestone on this machine

Requires Windows, Python 3.8+, and MSVC x86. The game client and assets are not included in this repository.

Original client: `C:\Users\saita\Downloads\Dark Blood\Dark Blood`. The existing test copy is `research/client/`; its `Data` directory is a junction to the original assets. See [STATUS.md](docs/STATUS.md) to prepare a fresh test copy.

From the repository root, with the game closed:

```powershell
Push-Location client_hook
.\build.bat
Pop-Location
Copy-Item client_hook\steam_api.dll research\client\steam_api.dll
```

Check the compiler output: the inherited build script still needs reliable failure propagation. Do not continue after a failed build using a stale DLL.

First terminal:

```powershell
python server\run_bootstrap.py
```

Second terminal:

```powershell
$env:__COMPAT_LAYER = 'RunAsInvoker'
$lab = Join-Path $pwd 'research\client'
Start-Process -FilePath "$lab\DarkBlood.exe" -WorkingDirectory $lab
```

`RunAsInvoker` avoids the manifest's elevation request during these tests. Logs are written to `research/client/hook_log.txt` and `logs/wire.jsonl`. The expected result is the initialization progress above, not gameplay.

## Current limitations

The local handshake uses a plaintext route accepted by this client. ProudNet encrypted negotiation `5/6`, UDP/P2P, and the complete game protocol are not implemented. The shim contains build-specific addresses and incomplete Steam interfaces; later calls can still crash. The asset decryption key is unverified.

`research/`, `logs/`, compiled DLLs, and memory dumps are ignored by Git. The documentation preserves the information needed to resume without those local artifacts.
