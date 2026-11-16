# Session handoff ? 2026-11-16 (Cristian machine)

## Update — 2026-11-16 ~13:50 (Cristian machine, dungeon render reproduced)

User clarified the earlier movement/attacks were their manual input, so do not
investigate spontaneous tutorial input. They authorized a new test. Pulled main
at e410c89, stopped the old owned server (client had already exited), ran the
13 passing headless tests, and started a fresh session with gamectl. Existing
Mage `lindic` (id 2) now has tutorial_cleared=true, persisted by the previous
manual session. Both characters remain present.

Locally verified: direct town entry; click movement; transitions Northern
Elwood Forest -> Elwood Center -> Elwood Village -> Western Forked Road ->
Entrance to Gnogue Haram. Then 2010/2011, 5001/5002 `_singleplay`,
5043/5044 `Act1_G1`, 5009/5010 `Act1_G1_A10`, 5013/5014: Lucid Forest
Entrance rendered successfully with the Mage and no logged exception/crash.
5095 (ffffff7f0400000046cdad32) remains unhandled. No monster was visible
in the initial viewport. Do not claim local dungeon movement/combat yet:
click movement, automated right arrow and X did not produce a visible action.
Requested a manual right-arrow/X test to distinguish input delivery from an
incomplete game state. UI automation is stopped pending that answer; leave
the client/server running for the manual check (owned processes are tracked in
logs/session.json, verify before stopping). Computer Use native pipe was
unavailable earlier in this conversation; gamectl is the fallback.

Screenshots (local): `research/test2-dungeon.png`,
`research/test2-dungeon-move.png`, `research/test2-action.png`;
latest traversal `research/test2-ui.png`. Wire log session starts at byte
2027398 (~13:41); new server runs e410c89. Next: manual control result,
then combat/drop/clear flow or input delivery debugging as supported by evidence.
## Update — 2026-11-16 ~16:00 (saita machine, MHServerEmu-style layout)

At the user's request the server moved from `server/` into the package
`src/darkblood` (see docs/ARCHITECTURE.md) ahead of a later C# port:
`core` (proudnet, crypto, jser, hashing), `frontend` (listeners, relay),
`player_management` (characters), `games` (session dispatcher, handler
mixins per domain, messages, entities, missions, game_data). Code was moved
verbatim (git mv where whole files moved); behaviour is unchanged: 15/15
headless tests and a live lobby/selection/relay run pass. Start with
`python run_server.py`; opcode tables are in `assets/`; the speculative
prototype is in `legacy/`. Collaborators with local edits to
server/game_wire.py or server/models.py must re-apply them in the new files.

## Update — 2026-11-16 ~15:00 (saita machine, quests/rewards/equipment)

See STATUS.md top. Fixed: active quest lost after relog, rewards ignored,
naked characters. Existing records get `bags`/`items` on next selection
(characters.ensure_inventory). Inventory window opens via the leftmost HUD
menu icon (click 0.468,0.955); the `i` key via gamectl did not work.
Open: bag cell display (try bag +0x28/+0x29 and the inventory page code from
Lua_UnequipBag 0x00552A90 / 0x00827D80), level-up, 5095, 2422, 2358.
User proposed an MHServerEmu-like layout ahead of a later C# port (not done).

## Update — 2026-11-16 ~13:30 (saita machine, dungeon entry live)

Dungeon entry works live (see STATUS.md top). Test route: gamectl
start / enter-lobby / select-character, click (0.66,0.80) x4, click (0.05,0.62)
x8 (follow the green arrows west into Gnogue Haram), wait for the gate map,
click Lucid Forest at (0.723,0.60). Added 5043->5044 and 5009->5010; 5014 now
echoes the map code. Next: 5095, 2422, monster kill flow, drops, dungeon
clear/return to town. Thief1 is naked (no inventory/equipment implemented).
2358 GUIDE_BEGINNER_UPDATE still unhandled. Session processes were stopped.

## Update — 2026-11-16 ~12:00 (Cristian live test)

The user authorized exclusive game control. Started the updated local server
and client using gamectl; selected existing Mage `lindic` (id 2), preserving
both existing characters. Live-verified on this machine: 2006/2007 selection,
relay handshake/JoinGroupACK, mailbox/friends/block-list replies, and the Mage
tutorial rendered at Library/Laboratory of Magician's Top. Client remained
connected and emitted 2353 monster-death notifications; no C++ exception or
access violation was logged. This is tutorial behavior, not dungeon entry.

Esc displayed the End tutorial dialog, but the attempted OK click and Enter
did not produce 2082. Character movement/attacks continued between inputs.
Asked whether the user was also controlling the game, and stopped further UI
input pending clarification. Do not assume skip succeeded. The skill's native
Computer Use pipe was unavailable; gamectl was the fallback. Its combined
physical/PostMessage input may need investigation if the user confirms no input.

Server/client are LEFT RUNNING (`logs/session.json` tracks owned processes;
verify current PIDs before touching them). Local captures: `research/resume-ui.png`
(latest tutorial combat), `research/resume-start.png`; wire/hook logs contain
the run from ~11:54. Additional static output `research/dungeon-flow.c` confirms
0x6E5C80 selects 0x78F950 (2082 sender) or 0x7AC380 based on app-page +0xC4;
the latter branch's behavior was not recovered. Next: settle exclusive control,
verify tutorial exit, reach town, then exercise room creation/start.

## Update — 2026-11-16 (Cristian resume, dungeon start serializer)

Pulled/rebased `origin main`: already at `cbcc82e`. Upstream already implements
2010/2011 room lists, 5001/5002 room creation, store dict loading, persistent
quest completion/history, and 2344/2345 waypoints. Do not reimplement these.
The older endpoint blocker below is historical and resolved.

Rebuilt and deployed the current Steam shim on this machine (the previous DLL
was from 03:01 and lacked newer fixes). Client executable SHA-256 still matches
the documented `a82ae3...c931`. No game process was running during deployment.

Fixed the old 5014 START_GAME_ACK serializer after focused Ghidra decompilation
and x86 assembly confirmation: untagged J-wstring, three maps, mandatory final
vector; all empty lengths terminate with 0x80. See PROTOCOL.md's dungeon start
correction. Full headless suite passes (13 tests). No live dungeon acceptance
claimed; field defaults remain provisional. Local evidence:
`research/dungeon-start.c`, `research/dungeon-start.log`, `research/session.bin`.

Exclusive game UI control was requested in this conversation; no answer yet.
No client launched or UI input sent. Next: live-test create room and start game,
then recover actual dungeon/map identifiers and the next observed requests.
Do not treat corrected framing as verified dungeon entry.

## Update — 2026-11-16 ~07:00 (sixth session, town gameplay live)

Live-verified with "Thief1": town entry, movement, map changes (5030 → 5031
now uses the 5046 layout; the old u8 0 made the client resend 5030 forever),
empty NPC store window (2065 → 2066), quest accepted and shown in the journal
(2073 → 2074, quest ids = jhash('Q0001S01')), quest completed without
rewards (2076 → 2077) and the next quest Q0002S01 started. Compressed client
events are inflated only when a zlib stream follows (2001/2203 set the flag
with plain bodies). Protector stubs resolved from an elevated live dump
(research/stub_names.tsv, 708 targets) and applied in Ghidra.

Open next: dungeon entry — 2010 GET_ROOMINFOLIST (→ 2011, handler
0x77A1F0), 5001 CREATE_ROOM "singleplay" (→ 5002, dispatcher 0x59D970), then
join room / P2P / monsters. Also: 2358 GUIDE_BEGINNER_UPDATE (→ 2359, receiver
not found), 2594/2595, 2216/2217, quest persistence and rewards, store items
from storelist.lua, skip with a fresh character (not yet retested).

## Update — 2026-11-16 06:12 (sixth session, live results)

Tutorial fix live-verified: "Thief1" entered SquarePlay. New shim with offline
ISteamUserStats fixed the follow-up crash at 0x0092CF06; ~2 min in town
without exceptions. Next: answer 5124, 2594, 2216, 2369, 2712, 2024 (schemas
not yet recovered), verify movement, test skip with a fresh character, and
dump protector stubs from an elevated prompt (the game requires admin).
Full Ghidra project: research/ghidra-full, pseudocode research/decompiled.

## Update — saitatter machine, 2026-11-16 ~06:00 (sixth session)

User report: "skip tutorial" restarted the tutorial. Cause found statically
(PROTOCOL.md §7): SquarePlay can-enter `0x006FA540` rejected
`nJoinLayerNetID` (2007 details `+0x5F` → player `+0xF0`) because we sent 0;
`JAppStateMgr` then timed out (5 s) and returned to Tutorial. Fix: details
`+0x5F = jhash("Act1") << 32 | 1`; 5046 `BACK_TO_SQUARE_ACK` now complete.
Headless tests: 11/11 pass. **Not yet live-tested**: the user's own client
(started 05:08) and server PID 43592 were still running, so nothing was
stopped. Next live test: restart the server with this code, select a
character (tutorial cleared or not), skip, and record the next requests the
town sends; also check for the "invalid layer netid" message box.

JPK correction: header byte `0x226` = encrypted flag; cipher covers whole
blobs of every entry. New tools: `tools/build_client_data.py` (private
workspace `../darkblood-client-data`, separate local Git repo — never push it
publicly), `tools/jpk_pack.py` (byte-identical rebuild, entry replacement),
`tools/luac51_dump.py` (Lua 5.1 constant listings). `research/all_extracted`
was produced with the old rule and is partly still encrypted.

## Update — saitatter machine, 2026-11-16 03:55

The "Unknown Internet address" blocker below is RESOLVED. The endpoint was the
square relay address filled by 5134 (`0x0075AAE0`), not the 18-byte `0x00A48A90`
block. The server sends 5134 = 127.0.0.1:9401 after 5029, and `run_bootstrap.py`
runs a handshake-only relay listener on 9401 with Relay PIDL JoinGroup/JoinGroupACK.
Town loaded and the NPC dialogue advanced with Space.
All subsequent opcodes (2131 friend list, 2569, 2082 clear tutorial -> 2083 town
transition, 2346 quest start -> 2347, 2390 roulette -> 2391, and notifications
2352/2353) have been decompiled, modeled with high-level dataclasses in
`server/models.py`, implemented in `server/game_wire.py`, and verified with
automated headless tests in `tests/test_headless_flow.py` (3/3 passing in ~0.6s).
Direct3D 9 multi-adapter fallback hook has been compiled into `client_hook/steam_api.dll`
and deployed to `research/client/steam_api.dll`. Server is running in background.

## Read this first

Goal: a reproducible, open-source local Dark Blood server. Offline gameplay is
NOT verified. Older status tables claiming world transitions are not a local
reproduction. Continue from the evidence below, rather than repeating setup.
Documentation stays in English; user communication is Romanian.

## User preferences and authorization

- Work autonomously on integration, reverse engineering, fixes and tests.
- Use local Ghidra and REA. Preserve collaborator changes and user data.
- Pull/rebase origin main every 10 minutes and push coherent verified work.
- Before ending a session, update roadmap/status/protocol/research notes and
  this handoff, then commit/push. User requested persistent written memory.
- Do not control the game simultaneously with the user. The user manually
  created a second character and opened a Delete character dialog during tests.
  Preserve both characters. Ask for an exclusive test window before UI input.
- User has little usage remaining and intends to resume tomorrow.

## Local environment (different from original author's saita paths)

Repo: C:/Users/cri99/Projects/darkblood-server-emulator
Original: research/supplied-client/Dark Blood/DarkBlood.exe
Test copy: research/client/DarkBlood.exe; Data is a junction to original assets.
Client SHA256: a82ae3d71b596418c1f3593cb63d3f9746318d452143c2e88f6ebbaff339c931
Archive: research/Dark Blood.7z, downloaded/decrypted from user-supplied MEGA.
Ghidra: C:/Users/cri99/Tools/ghidra_12.2_PUBLIC
JAVA_HOME: C:/Program Files/Eclipse Adoptium/jdk-25.0.5.8-hotspot
REA MCP 6.9.0 is connected and Ghidra decompilation has worked.
Python: research/venv/Scripts/python.exe (Python 3.10, pefile/capstone/py7zr).
Bare python is a Microsoft Store alias. py -3.10 and py -3.14 also exist.
MSVC: VS 2022 Community x86; client_hook/build.bat works.
PowerShell script execution is disabled; invoke Ghidra analyzeHeadless.bat
 directly instead of changing system execution policy. FocusedDecompile.java
accepts output path and VA seeds; use disposable projects and -noanalysis.
Computer Use sky native pipe was unavailable. gamectl is the tested fallback.
Its focus/screenshot can hang while the game main thread waits; bound tests.

## Work already published

b4af5cd: remove explicit 0x1E struct tags (client consumes only 0x0F..0x1A).
b0b16d7: add missing u8 at world-details +1CA (bool,u8,u16,bool,bool trailer).
a201b77: preserve -1 at details +A6/+AA; add empty mailbox 2219/2220 response.
59fa4f1: SteamUser slot 16 one-argument offline stub; former three-slot vtable
 caused an invalid indirect call at 0x786B28. Compiled ret 4 and live stub hit.
311ec56: remove duplicate 2007 result word. A1EA20(1) peeks/reset cursor;
 A40760 rereads the same result. Tester ACK is 636 bytes, not 640/651.
5d537ce: bounded first-chance C++ exception diagnostics after opcode 2007.
The diagnostic DLL has been deployed to research/client for the last test.
Four collaborator commits introducing models/world handlers were integrated.
No open PRs were found at the last check; the user uses PR to mean git pull.

## Latest concrete blocker (most important)

The final bounded test caught E06D7363 after selecting Tester:
- RTTI at throw info 0x00EE60CC identifies Proud::Exception (and std::exception).
- Candidate stack returns: 0x00B71DD4, 0x00B5533F, 0x00B7135A.
- Assembly at 0x00B55315 pushes error 14; B727E0(14) maps to English
  "Unknown Internet address." at 0x00D74140 (other languages also present).
- Function 0x00B54B40 validates connection parameters: address conversion must
  succeed and port must not be 0 or -1. This is the next investigation target.
- Many 2007 fields are still zero/defaults, including candidate endpoint blocks.
  Do NOT guess the endpoint layout or patch out the exception/timeout.
- Wrapper 0x00641E00 invokes reader 0x00A48A90 (not yet decompiled) for a
  candidate 18-byte nested block in the record. Recover it next; trace the
  actual connection parameters back to 2007 before changing the serializer.

Timeout mechanism: scene code 0x006F8960 sends 2006 and waits for 2007 at
0x006F8992 -> 0x0094E1F0. After 30000ms it calls 0x00757750(0), then
JUserClient::Shutdown 0x007869A0. Dispatcher 0x00787310 normally calls
0x009443A0 at 0x0078747F after handler return to complete the wait. The
exception is a plausible reason handler completion is skipped; verify causality.
Do not describe network heartbeats or successful deserialization as world entry.

## Local evidence to reuse

research/session.bin: mapped image; research/unpacked.analysis.exe: STATIC ONLY
fixture, never launch it. Original packed executable gives zeros at parser VAs.
research/client/hook_log.txt: last test's CXX record and candidate stack words.
research/proud-error.c: message mapping; research/next-address.c: B54B40.
research/last-selection-throw.c; research/endpoint-schema.c (641E00 wrapper).
research/main-wait.c; research/dispatch-wait.c; research/ack-wait-end.c.
research/select-character.c; research/select-fields.c; research/detail-defaults.c.
research/client/crash_image.bin: older crash image, NOT the last C++ object.
Focused decompiler signatures/stack labels are unreliable; confirm with capstone.
All game binaries, dumps, captures, generated DLLs and research remain ignored.

## Next session checklist

1. Pull/rebase main, inspect newer collaborator work, read relevant AGENTS/skills.
2. Recover A48A90 and actual endpoint argument layout used by B54B40.
3. Locate endpoint fields in 2007 and derive valid loopback endpoint encoding
   from the client; verify correct listener/connection route before testing.
4. Agree exclusive UI control, restart with built diagnostic shim, bounded test.
   Preserve data/characters.json; for isolation set DARKBLOOD_DATA in the SAME
   process environment that launches the server (it does not persist across tools).
5. Verify handler completes, wait is released, next requests and visible scene.
6. Commit tested fixes with evidence limitations; update this handoff at shutdown.

## Cleanup and background sync

Cristian resume update (2026-11-16): the user reported a recurring brief
PowerShell window. The sync task was a likely cause (10-minute interactive
PowerShell launches, despite `-WindowStyle Hidden`). Its action now uses local
`research/venv/Scripts/pythonw.exe` with `research/automation/sync_hidden.pyw`;
the wrapper invokes the unchanged sync script with `CREATE_NO_WINDOW` and
redirected standard streams. Original task XML is backed up locally at
`research/automation/task-before-hidden-launcher.xml`. The schedule is preserved.

Last owned client/server test processes were stopped. Verify fresh status before
starting; never reuse recorded PIDs. sample.txt enables bounded 5s sampling;
bp.txt has diagnostic breakpoints. Inspect these before another test.
Windows Task Scheduler task DarkBlood-RepoSync-10min fetches every 10 minutes;
clean, non-divergent main can pull/rebase/push. No automatic commits or force push.
Script/log: research/automation/sync.ps1 and sync.log. Runs while user logged in.
This task only syncs Git; it does not run autonomous game investigations.
A historical stash preserves the pre-model local tag patch; already ported and
published. Do not reapply it blindly. docs/LOCAL_SETUP.md remains local/untracked.
