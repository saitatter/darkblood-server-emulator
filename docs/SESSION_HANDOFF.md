# Session handoff ? 2026-11-16 (Cristian machine)

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

Last owned client/server test processes were stopped. Verify fresh status before
starting; never reuse recorded PIDs. sample.txt enables bounded 5s sampling;
bp.txt has diagnostic breakpoints. Inspect these before another test.
Windows Task Scheduler task DarkBlood-RepoSync-10min fetches every 10 minutes;
clean, non-divergent main can pull/rebase/push. No automatic commits or force push.
Script/log: research/automation/sync.ps1 and sync.log. Runs while user logged in.
This task only syncs Git; it does not run autonomous game investigations.
A historical stash preserves the pre-model local tag patch; already ported and
published. Do not reapply it blindly. docs/LOCAL_SETUP.md remains local/untracked.
