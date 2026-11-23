# Working instructions

## Start here

Read `docs/SESSION_HANDOFF.md` first for the latest local setup, user preferences,
verified findings and next investigation target. Update that handoff before ending
each session, along with roadmap/status and relevant evidence notes, then submit
the updates through a pull request.


Read `README.md`, `docs/STATUS.md`, `docs/PROTOCOL.md`, and `ROADMAP.md` before resuming implementation.

Write and maintain all project documentation in English, as explicitly requested by the user.

## Public repository layout

`main` is the clean source-only publication branch. The earlier history remains on local `master` and includes extracted game assets. Do not push `master`, use `git push --all`, or mirror the repository. Extracted assets remain on disk but are ignored on `main`.

Goal: make the supplied Dark Blood client playable with a local offline server. Town play, dungeons, quests, inventory, economy and two-client town presence work; shared dungeon instances and many zero-filled fields remain. The current milestone and next targets are in `docs/SESSION_HANDOFF.md`.

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

- Current server: `python run_server.py` from the repo root, binding `127.0.0.1:9400` (game) and `9401` (relay).
- Code layout follows MHServerEmu for a later C# port: `src/darkblood/{core,frontend,player_management,games}`; read `docs/ARCHITECTURE.md` before adding handlers (new opcode = message dataclass + `on_<opcode>` in the domain mixin + headless test).
- Drive live tests with `tools/gamectl.py` (or the `darkblood` MCP server): it verifies the client hash, refuses a busy port, and stops only processes it started. Use `enter-lobby` to reach character select.
- Decompile with `tools/decomp.ps1 OUT.c 0xADDR...`; dump behaviour with the shim's `bp.txt` tracer and `sample.txt` sampler (see STATUS.md).
- Opcode names: `assets/opcodes.tsv`. Handler addresses: `research/client/handler_map.txt` (written by the shim on connect).
- No legacy or data-migration code until the first release: the speculative prototype and the JSON character store were removed on 2026-11-16. Change the stored format freely and reset `data/` instead of migrating.
- ProudNet scalars and JSerBuffer varints are different: width-prefixed signed integers versus seven-bit groups terminating when bit 7 is **set**.
- Game events travel in ProudNet user messages (observed type `2`). Type `1` is RMI traffic; captured `0xFA01` does not establish a game login request.
- Recover parser schemas before adding responses. Do not invent opcode tables; use the client's own table. Fields without a recovered meaning are sent as zero/defaults and marked as such in code.
- Welcome defaults are accepted by the serializer; most field meanings remain unknown.
- Character field `+0x09` is an index: value 12 crashed the client.

## Experiments and client modifications

- Use `research/client/` for new DLLs/settings. Preserve the supplied EXE and `steam_api.dll.bak`.
- Preserve all uncommitted changes. User/Gemini hook changes existed at session start; exact source backup: `research/steam_api_hook.before.c`, ignored by Git.
- Never recursively delete/move through the `Data` junction. Verify resolved paths and junction targets first.
- Do not reinstall the old ExitProcess/NtTerminateProcess hooks. Their dead definitions remain in the WIP source but are not called. `Sleep(INFINITE)` hides failures.
- Install the network hook after unpacking, in `SteamAPI_Init`. Only relocate the verified prologue `8B FF 55 8B EC`; an arbitrary five-byte copy is unsafe.
- Preserve destination ports and copy sockaddr inputs before redirecting. Do not send experiments to the original remote service.
- Current redirect covers IPv4 `connect` only. WSAConnect, ConnectEx, IPv6, and UDP are not covered; this is not complete offline isolation.
- Diagnostic vtable/callsite hooks check expected targets before patching and should only trace behavior.
- Bound test duration and stop only owned processes. The new bootstrap was stopped for the pause. Never reuse a recorded PID without verification.

## Mandatory Agent Collaboration & Synchronization Rule

Until the server emulator implementation is complete:
- **10-Minute Git Sync Cycle**: During active work, check for remote changes every **10 minutes** with `git fetch origin` and integrate upstream changes into the working branch. Push verified changes to that branch and open or update a pull request targeting `main`.
- **Semantic Commit Name Convention**: All git commits MUST strictly use the Semantic Commit / Conventional Commits format (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`, etc.) with an optional scope and a clear imperative description (e.g. `fix(lobby): swap character level and class byte order in lobby entry`, `feat(wire): add opcode 2082 clear tutorial handler`, `docs(agents): mandate semantic commit convention`).
- **Contributors & Branch Protection**: Recognized project contributors include repository owner `saitatter`, `CristianVita` (`cri999sti@gmail.com`), and `mauvalefotos@gmail.com`. Branch protection is active on `main`: force pushes (`git push --force`) are strictly prohibited for contributors. Contributors must contribute via feature branches and Pull Requests (PRs), with only the owner (`saitatter`) holding direct administrative override privileges.
- **Never Overwrite or Lose Progress**: Always rebase cleanly, verify tests with `gamectl`, and never perform destructive resets. Keep documentation in English and keep all evidence updated.

## Known gaps

- SteamUser implements only three initial slots; SteamFriends only the first slot. Other interfaces still return invalid placeholder `1`, and many export signatures/callbacks are incomplete.
- Server → client messages are unencrypted; fast encryption (0x27) and UDP are not implemented. Control reply `0x1D -> 0x1F` is exploratory.
- Headless tests: `python -m unittest discover -s tests -v` drives the server with `tools/headless_client.py` (real handshake, encrypted events, no game window). Run them first; launch the client only to verify that it parses a changed response. The user asked to avoid opening the graphics window for every test.
- `docs/CRYPTO_KEYS.md` is provisional. Existing extracted XML is malformed; do not treat it as plaintext or mass-extract using an unverified key.
- Keep game binaries, dumps, generated DLLs, captures, and unrelated user files out of Git. Keep reproducible source and concise evidence notes.

Update status/protocol/roadmap when milestones are actually verified. Gameplay requires observed character/map control and persistent state, not a splash screen.
