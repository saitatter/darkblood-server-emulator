# Research status and handoff

Documentation handoff: **November 16, 2026**, covering the investigation performed on November 15, Europe/Bucharest. Experimental work is paused at the user's request. Offline gameplay is not available yet.

## Verified findings

1. The initial Steam shim lacked exports required during dynamic import resolution. The earlier setup exited before normal Steam calls; termination hooks concealed this by sleeping forever.
2. Completing the export surface and disabling global termination hooks allowed calls to `SteamAPI_RestartAppIfNecessary(267790)` and `SteamAPI_Init`.
3. Returning pointer `1` from Steam interface getters caused invalid accesses. The observed crash at `0x0092C322` dereferenced `SteamUser()`'s result.
4. Minimal SteamUser/SteamFriends interfaces let the client open its game window. SteamUser supplies handle, BLoggedOn, and SteamID; SteamFriends supplies persona name `OfflinePlayer`.
5. This client attempted TCP connection to `54.173.235.121:9400`. This is an observed endpoint in the supplied copy, not a claim about a currently operating service. The new hook redirects to loopback while preserving the port.
6. The passive local recorder received `13 57 01 05 30 0F 00 00 40` as the initial frame.
7. The experimental plaintext ProudNet route was accepted. Instrumentation confirmed `OnJoinServerComplete result=0`.
8. Application event `5020 / 0x139C`, wrapped in ProudNet user message type `2`, reached `OnReceiveUserMessage`: 114 bytes in the current experiment.
9. The welcome parser finished with `reader_ok=1` and body cursor `100`. The trace `Welcome decoded=1766913` includes undefined upper bits of a boolean return in AL; the meaningful result is its low byte `1`.
10. The main-thread stack in `research/decode.log` advanced to waiting for `0x0963 / 2403` at `0x0074A0C7`. Earlier traces showed the previous wait for `0x139C / 5020` at `0x0074A04F`.

The visible client remained at its splash/initialization screen. Server selection, completed login, character creation, map entry, movement, and combat have not been demonstrated.

## Immediate blocker

`0x0079A970` constructs application request `0x0962 / 2402`, then passes it through `0x007874A0` to ProudNet `SendUserMessage`. A corresponding application user message has not appeared in the TCP capture, although the main thread advances to waiting for response `0x0963`.

Recovered static route:

```text
0x0079A970   constructs request 0x0962
0x007874A0   serializes JEvent and invokes ProudNet interface +0xC8
0x00B55A30   thunk: adjusts this by -0xAC
0x00B75710   prepares ProudNet user message type 2
0x00B3FEC0   initial guard and routing
0x00B76050   send options / encryption branches
0x00B53310   destination / transport routing
```

`0x00B53310` checks an object pointer at `+0x1570` and a value at `+0x1500`. Observe their actual values and the executed branch before assigning meanings. Skipping the complete ProudNet negotiation might omit necessary initialization, but that is a hypothesis, not an established cause.

## Artifact identities

| Artifact | SHA-256 |
| --- | --- |
| Original `DarkBlood.exe` | `a82ae3d71b596418c1f3593cb63d3f9746318d452143c2e88f6ebbaaff339c931` |
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

Verified environment: Windows x64, Python 3.8, MSVC 2022 x86, Ghidra 12.1.4, JDK 21.0.9, and REA CLI 6.7.0. Python modules `pefile` and `capstone` are available. The bootstrap server uses only the standard library. `cryptography`, `Crypto`, `frida`, and `unicorn` were absent.

### Prepare a fresh test copy

Run from the repository root. This refuses an existing destination to preserve earlier experiments:

```powershell
$source = 'C:\Users\saita\Downloads\Dark Blood\Dark Blood'
$lab = Join-Path $pwd 'research\client'
if (Test-Path -LiteralPath $lab) { throw 'Test copy already exists; inspect it before making changes.' }
New-Item -ItemType Directory -Path $lab -Force | Out-Null
Get-ChildItem -LiteralPath $source -File | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $lab
}
New-Item -ItemType Junction -Path (Join-Path $lab 'Data') -Target (Join-Path $source 'Data')
```

Large assets are shared through the junction. Avoid recursive operations that traverse it. Preserve the supplied original `steam_api.dll.bak`. Do not replace the original EXE with a memory dump or analysis fixture.

See the [README](../README.md) for shim compilation and manual launch. Do not run the passive recorder and bootstrap on the same port simultaneously.

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
- The bootstrap does not fully validate type-8 connection requests or implement application behavior after welcome.
- `0x1D → 0x1F` is exploratory. The `0x1E` timing parser is recovered; complete control-message semantics are not.
- No dedicated automatic protocol test suite has been added. Native builds and bounded live-client experiments succeeded through the milestones above; these are not gameplay end-to-end tests.

## Workspace state at pause

At the research pause, no commit had been created and no destructive Git operations had been performed. Research artifacts, wire logs, and generated binaries are ignored.

The bootstrap server started during this session was stopped. No test client, debugger, or Ghidra process remained at inspection. The earlier `server/server.py` process, already present at the start, was left running. Verify processes and ports before resuming; historical PIDs must never be used without checking current ownership.

## Public repository preparation

The user subsequently requested a public repository named `darkblood-server-emulator`. A clean `main` branch was prepared containing only source and documentation. The original two-commit history remains locally on `master`, because it includes extracted game resources. Those resources remain on disk and are ignored on `main`. Only `main` should be pushed; do not publish all branches or mirror the local repository.
