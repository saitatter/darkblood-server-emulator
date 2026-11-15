# Working instructions

## Start here

Read `README.md`, `docs/STATUS.md`, `docs/PROTOCOL.md`, and `ROADMAP.md` before resuming implementation. Documentation handoff: 2026-11-16, covering the 2026-11-15 investigation. The user requested a pause for documentation; wait for their instruction before resuming game experiments.

Write and maintain all project documentation in English, as explicitly requested by the user.

## Public repository layout

`main` is the clean source-only publication branch. The earlier history remains on local `master` and includes extracted game assets. Do not push `master`, use `git push --all`, or mirror the repository. Extracted assets remain on disk but are ignored on `main`.

Goal: make the supplied Dark Blood client playable with a local offline server. This is incomplete. Current milestone: accepted local transport and decoded application welcome; the main thread next waits for application event `2403 (0x0963)`.

## Machine and repository

- Workspace: `C:\Users\saita\Desktop\repos\darkblood-server-emulator`.
- Supplied client: `C:\Users\saita\Downloads\Dark Blood\Dark Blood`.
- Working client: `research/client/`, whose `Data` is a junction to the original game's resources.
- Ghidra: `C:\Users\saita\tools\ghidra_12.1.4_PUBLIC`.
- JDK: `C:\Users\saita\.jdks\ms-21.0.9`.
- Python on PATH: 3.8; `pefile` and `capstone` available. `cryptography`, `Crypto`, `frida`, and `unicorn` absent at handoff.
- MSVC x86: `C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars32.bat`.
- Installed REA CLI: `rea`, observed version `6.7.0`.

Use the `reverse-engineer-anything` skill for shipped binary analysis. Do not spawn agents unless the user or an applicable skill explicitly asks for delegation.

## Evidence discipline

- Check the client SHA-256 in `docs/STATUS.md` before using build-specific addresses.
- Addresses are x86 VAs, image base `0x00400000`. Memory-image offset = VA minus base; original PE file offsets have different mappings.
- The on-disk EXE is packed. Game code was recovered through a normal launch and mapped-image dump. Debugging from process creation triggered a protection error; normal launch worked.
- `research/unpacked.analysis.exe` is a derived static-analysis fixture with modified PE headers, removed loader directories, and an artificial entry seed. Never launch it as a playable client.
- The REA query seeded at `0x92C2E0` starts inside a function; the correct boundary used in focused analysis is `0x92C2C0`. That artificial `entry` is not the original entry point.
- `FocusedDecompile.java` uses no full auto-analysis, limited callee discovery, and inferred stack-purge metadata. Signatures, stack variables, and function boundaries can be wrong. Confirm key claims with assembly and runtime observations.
- Distinguish observed behavior, static reconstruction, and hypotheses. A decoded greeting is not login or gameplay.

## Implementation route

- Current server: `python server/run_bootstrap.py` from the repo root, binding `127.0.0.1:9400`.
- `server/server.py` is the earlier speculative Auth/Lobby prototype on ports 10001/10002. Its framing/opcodes are not recovered facts.
- ProudNet scalars and JSerBuffer varints are different: width-prefixed signed integers versus seven-bit groups terminating when bit 7 is **set**.
- Game events travel in ProudNet user messages (observed type `2`). Type `1` is RMI traffic; captured `0xFA01` does not establish a game login request.
- Recover parser schemas before adding login/character/map responses. Do not invent opcode tables.
- Welcome defaults are accepted by the serializer; most field meanings remain unknown.

## Experiments and client modifications

- Use `research/client/` for new DLLs/settings. Preserve the supplied EXE and `steam_api.dll.bak`.
- Preserve all uncommitted changes. User/Gemini hook changes existed at session start; exact source backup: `research/steam_api_hook.before.c`, ignored by Git.
- Never recursively delete/move through the `Data` junction. Verify resolved paths and junction targets first.
- Do not reinstall the old ExitProcess/NtTerminateProcess hooks. Their dead definitions remain in the WIP source but are not called. `Sleep(INFINITE)` hides failures.
- Install the network hook after unpacking, in `SteamAPI_Init`. Only relocate the verified prologue `8B FF 55 8B EC`; an arbitrary five-byte copy is unsafe.
- Preserve destination ports and copy sockaddr inputs before redirecting. Do not send experiments to the original remote service.
- Current redirect covers IPv4 `connect` only. WSAConnect, ConnectEx, IPv6, and UDP are not covered; this is not complete offline isolation.
- Diagnostic vtable/callsite hooks check expected targets before patching and should only trace behavior.
- Bound test duration and stop only owned processes. The new bootstrap was stopped for the pause. The pre-existing `server/server.py` process was left alone (PID 44712 then; never reuse a recorded PID without verification).

## Known gaps

- SteamUser implements only three initial slots; SteamFriends only the first slot. Other interfaces still return invalid placeholder `1`, and many export signatures/callbacks are incomplete.
- Transport skips encrypted negotiation `5/6`. Control reply `0x1D -> 0x1F` is exploratory, not a recovered production mapping.
- No automatic test suite yet. Native builds and bounded live-client tests were performed.
- `docs/CRYPTO_KEYS.md` is provisional. Existing extracted XML is malformed; do not treat it as plaintext or mass-extract using an unverified key.
- Keep game binaries, dumps, generated DLLs, captures, and unrelated user files out of Git. Keep reproducible source and concise evidence notes.

Update status/protocol/roadmap when milestones are actually verified. Gameplay requires observed character/map control and persistent state, not a splash screen.
