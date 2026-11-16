# Dark Blood client reverse engineering

Documentation handoff: 2026-11-16, covering the 2026-11-15 investigation. See [STATUS.md](STATUS.md) for artifact identities and [PROTOCOL.md](PROTOCOL.md) for the recovered wire formats.

## Target

- Supplied game: Dark Blood Online / Project Hound, with build paths referring to JCR Soft's Hound client.
- Steam AppID observed in a client call: `267790`.
- Executable: `DarkBlood.exe`, PE32 x86, image base `0x00400000`.
- Working version label from earlier notes: `1.6.5#0`; not independently revalidated.
- Original SHA-256: `a82ae3d71b596418c1f3593cb63d3f9746318d452143c2e88f6ebbaaff339c931`.
- Embedded PDB path includes `D:\Depot\Hound\Development\B_STEAM_QA\Library\SkClient\Release_Public_Service\DarkBlood Service.pdb`.

## Packing and execution

The disk executable contains packed code and an Oreans protection layer. Runtime strings include Oreans references. Earlier notes identify an aPLib stage; that algorithm identification still needs independent verification and should not be treated as complete unpacker reconstruction.

Original entry VA is `0x0119E000`, with an initial transfer eventually reaching the stub at `0x0119D000`. Original section RVAs include `0x00CE3000` (`snlesxay`), `0x00D9D000`, and `0x00D9E000`. Distinguish RVAs from VAs: add the image base to obtain the corresponding virtual address.

Launching under Windows Debug API from process creation triggered many first-chance privileged/illegal-instruction exceptions and a protection-error dialog. Those exceptions can be part of the packer; blindly skipping them is not a valid unpacking strategy.

Normal execution with `__COMPAT_LAYER=RunAsInvoker` reached unpacked game code. `tools/debug_client.c`, in `DB_NO_DEBUG` mode, was used to read the mapped image and inspect threads. The helper terminates only the child it created after its bounded observation window.

The derived `research/unpacked.analysis.exe` is not playable. It wraps a captured memory image into a simplified PE for static analysis, with loader directories removed and an artificial disassembly seed. Addresses in this fixture correspond to memory VAs; original disk offsets do not.

## Steam shim findings

The supplied folder already contained a replacement `steam_api.dll` and an original `steam_api.dll.bak`. The earlier replacement exported only a subset of the original API. Completing the export surface allowed the packer/import setup to reach normal game initialization.

The original backup has 57 exports. Matching names is not full API compatibility: several mock signatures, callback behaviors, and interfaces remain incomplete.

A crash at `0x0092C322` showed that returning pointer `1` from SteamUser was invalid. Minimal vtables now provide:

- SteamUser slot 0: user handle.
- SteamUser slot 1: BLoggedOn.
- SteamUser slot 2: SteamID, using an x86 hidden output pointer for the struct return.
- SteamFriends slot 0: persona name `OfflinePlayer`.

Other interfaces still contain invalid pointer placeholders. Later authentication, achievements, inventory, or networking calls may require additional methods. Startup success does not validate those APIs.

## Hooking changes

The earlier hook copied arbitrary five-byte API prologues and blocked ExitProcess/NtTerminateProcess using `Sleep(INFINITE)`. It could split instructions and conceal actual failures. Those termination hooks are no longer installed; their dead definitions remain in the WIP source for later cleanup.

The current redirect is installed during `SteamAPI_Init`, after unpacking. Its trampoline helper accepts only the inspected x86 hotpatch prologue `8B FF 55 8B EC`, flushes instruction caches, and refuses other layouts. The redirect copies the sockaddr and preserves the requested port.

Observed original connection: `54.173.235.121:9400`. Experimental destination: `127.0.0.1:9400`.

Coverage is limited to IPv4 `connect`. WSAConnect, ConnectEx, IPv6, and UDP have not been comprehensively redirected. Do not claim complete network isolation.

Build-specific diagnostic patches trace:

- Connection callback via slot `0x00D4FA90`, expected function `0x00A5D880`.
- User messages via slot `0x00D4FA8C`, expected function `0x00A5EFA0`.
- Welcome deserialization at callsite `0x0096B091`, expected target `0x00A519A0`.

Each checks its expected target before mutation. These are observation hooks; they do not force parser or login success.

## Analysis tools and limits

REA's connected server initially reported Ghidra unavailable because its process environment lacked the paths. The installed CLI worked with shell-local `GHIDRA_INSTALL_DIR`, `JAVA_HOME`, and absolute `REA_JAVA_COMMAND`; no global MCP configuration change was needed.

Full Ghidra analysis through REA produced retained Evidence. The initial artificial seed `0x92C2E0` lies inside the Steam-related function whose actual start is `0x92C2C0`; do not interpret the synthetic `entry` as a recovered original entry point.

`tools/FocusedDecompile.java` provides faster targeted analysis using `-noanalysis`, requested function seeds, limited callee discovery, and return-based stack-purge metadata. Its output may contain incorrect signatures, merged function bodies, and inaccurate stack variables. Check important details against assembly and live observations.

### Full named Ghidra project (2026-11-16, saitatter machine)

Reproducible from local evidence (all outputs stay under ignored `research/`):

```sh
python tools/image_to_pe.py research/normal.bin research/normal.analysis.exe --entry 0x92C2C0
python tools/gen_symbols.py research/normal.bin -o research/symbols.tsv
# GHIDRA_HEADLESS_MAXMEM=8G, JAVA_HOME set:
analyzeHeadless research/ghidra-full DarkBlood -import research/normal.analysis.exe -overwrite \
  -scriptPath tools -preScript ApplySymbols.java research/symbols.tsv \
  -postScript ApplySymbols.java research/symbols.tsv
analyzeHeadless research/ghidra-full DarkBlood -process -noanalysis -scriptPath tools \
  -postScript ExportDecompiled.java research/decompiled 30
```

`normal.analysis.exe` (SHA-256 `344442f6...aca67`) wraps `normal.bin`, the
normal-launch dump without diagnostic patches; like `unpacked.analysis.exe` it
is a static fixture, never a runnable client. `gen_symbols.py` recovers 282
opcode handler names (`On_<opcode>`; 59 opcodes are missing from
`opcodes.tsv` and stay `On_opcode_N`), 1,806 lua_tinker binding names
(`Lua_<name>`, the Lua-visible name) and 4,373 RTTI names
(`Class::vftable`, `Class::vfNN` for slots owned by one class). Open the project
in the Ghidra GUI for navigation; `research/decompiled/*.c` and
`functions.tsv` are greppable pseudocode.

First run: auto-analysis 457 s; ApplySymbols named 5,208 functions and 1,184
labels; ExportDecompiled produced 32,219 of 32,225 functions (39 MB).

Handler registrations also occur outside the connect-time map: pattern
`mov eax, handler ... mov edx, opcode ... call 0x0075F080` (138 found by byte
scan). The game runs elevated (`requireAdministrator` in the manifest), so
`tools/dump_stubs.py` must run from an elevated prompt.

Known limit: calls written as `nop; call 0x600xxxxx` go to protector-allocated
stubs outside the image (no DLL is based there), replacing the original
`call [IAT]` thunks. They show as `func_0x600xxxxx` until a live process dump of
that region maps each stub to its CRT/MFC/WinAPI target.

The client contains ProudNet networking and its own JSerBuffer/JEvent serialization. The initial Auth/Lobby prototype did not implement those real formats. The actual accepted sequence and the remaining `2403` initialization wait are documented in [PROTOCOL.md](PROTOCOL.md) and [ROADMAP.md](../ROADMAP.md).

## SteamUser slot 16 crash (local 2026-11-16 verification)

A selection-continuation failure reached `0x007869A0`; its final call at
`0x00786B28` uses vtable offset +0x40 with one stack argument. The import
slot `0x00C48EA8` in the local mapped image resolved to shim `SteamUser`
(export RVA 0x2009 in that build), not an internal game interface. The
three-entry mock vtable had no slot 16, causing an invalid indirect target
(observed C0000005, return address 0x00786B2A).

The shim now reserves 17 entries and supplies a diagnostic offline no-op
for the observed slot 16 call. Its exact Steam method name/semantics remain
unconfirmed; slots 3..15 remain unsupported NULL entries. MSVC object
disassembly confirms one stack argument is removed (`ret 4`). The updated
shim logged slot 16 argument 32 during local execution; the client remained
alive afterward with no new exception in that run. This fixes the observed
invalid call, not the upstream connection/scene failure that reaches this
cleanup path. Full Steam compatibility and playable world entry remain
unverified. Binary outputs and crash images stay local.

## Selection wait timeout and exception diagnostics

Local main-thread samples after selection contain `0x0094E253` and
`0x006F8997`. Decompilation and assembly identify caller `0x006F8960`
requesting character selection then waiting on opcode 0x7D7 (2007) through
`0x0094E1F0`. The latter pumps events until field +0x60 becomes -1 and
invokes `0x00757750(0)` after 30000 ms. This explains a shutdown without
a new access violation. `0x009443A0` completes a matching wait and is
called at dispatcher `0x0078747F`, after the event handler returns.

The next hypothesis is that a C++ exception or another early exit prevents
handler completion; successful parsing does not establish successful handler
completion. A diagnostic in the shim logs up to 16 first-chance C++ throws
after a 2007 message, with at most 24 candidate game-code stack words each.
These are raw stack candidates, not an unwound call trace. It preserves
normal exception handling. The diagnostic build compiles with MSVC x86;
runtime reproduction with this new build is still pending. The working DLL
is not replaced while the user is running the client. Static outputs are
retained locally in `research/main-wait.c`, `research/ack-wait-end.c`,
`research/dispatch-wait.c` and `research/wait-completion.c`.
