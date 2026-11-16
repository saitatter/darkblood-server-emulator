# Research status and handoff

Updated **November 16, 2026** (second session). Offline gameplay is not available yet; the client now reaches character creation and selection against the local server.

## Verified in the second session

1. The send blocker was encryption: game requests use ProudNet strong encryption (RmiContext `0x00F2C410`, mode 1) and `0x00B76050` aborted at `0x00B76515` because the shortened handshake never established a session key.
2. The emulator now performs the real key exchange (type 5 → 6 → 7): RSA-1024 OAEP-SHA1 for the session key, AES-128 ECB with a CRC-32 envelope for messages. The fast key in type 6 and every client message decrypt with a valid CRC.
3. The client's opcode → name table (1,191 entries) and runtime handler map (298 entries) were recovered; see `server/data/opcodes.tsv` and [PROTOCOL.md](PROTOCOL.md#5-application-flow-observed-in-the-live-client).
4. Observed flow with parser-accepted responses: welcome 5020 → DB list 2402/2403 (title Server List shows "Offline / None") → knock 2001/2002 → square list 2021/2022 (Channel List shows "Channel 1 · Normal · [Good]") → join square 5028/5029 → character list 2008/2009 (character select, "4 SLOT") → create 2012/2013 (character "Tester" appears, Warrior).
5. Characters persist in `data/characters.json` (ignored by Git) and are listed again after a client restart.
6. The intro cinematics are skipped by clicking once loading is complete; `gamectl skip-intro` clicks until the Server List opens.
7. The client runs in exclusive fullscreen; GDI capture works once the window is focused. DXUT's Alt+Enter toggles windowed mode.

Screenshots of each stage are kept locally in `research/` (`shot8.png` server list, `g7.png` channel list, `g10.png` empty character select, `g11.png` creation, `g13.png` created character).

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
