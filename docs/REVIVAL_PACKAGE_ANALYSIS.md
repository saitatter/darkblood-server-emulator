# Analysis of the third-party "revival" client package (2026-11-20)

Subject: a 3.7 GB directory supplied by the user (`Downloads\package`, manifest `client-package.json`, version
`0.1.0-test.8-guildupgrade1`). It is **not** a Korean build. It is a Chinese private-server distribution of the same
Steam client, prepared for a platform called "173game" (`173game-integration.json`). Nothing in it was executed;
everything below comes from static inspection (hashes, `pefile`, string and source reading, `luac51_dump.py`
comparisons). The package is not copied into this repository.

## Verdict in short

| Question | Answer |
| :--- | :--- |
| Different client build? | No. `DarkBlood.exe` is byte-identical to ours (SHA-256 `a82ae3d7…c931`, Steam `1.6.5#0`). `CLIENT_BASELINE.json` pins the same hash. |
| New game functionality in the client? | None in the binary. The extras are server features plus Frida memory patches applied at runtime (below). |
| Extra cash shop items? | None. `DictCash:LoadProductList` has the same **771** product ids as our `assets/cash_shop.tsv`, and `item_cash.lua` is byte-identical to ours. The package only relabels the currency ("点券") and patches the cash UI. |
| Telemetry / spyware? | No evidence of spyware in the package's own code. One telemetry URL exists inside the client itself (see below). |

## What differs from our client (73 files differ, mostly noise)

Compared with `C:\Users\saita\Downloads\Dark Blood\Dark Blood` by SHA-256:

- **MiniMap `.MNP/.RAD`** (about 180 extra files, ~40 changed): generated per-player map caches, not content.
- **Localization**: `Localization_ST_0`, `UI_ST_0`, `Font_ST_0`, `Sound_ST_*`, the three legal documents
  (`TermsofUse`, `OnlinePrivacyPolicy`, `RulesofConduct`) are Simplified Chinese (same table ids, translated text).
  Audio archives are repacked with different sizes. A Noto UI font set ships under `revival/client-fonts`.
- **Game tables** (decoded with `tools/luac51_dump.py --ops`), only three differ:
  - `item_disposable.lua`: two constant operands changed 0 to 1 (override `surplus-22bag-discard`: surplus 22-slot bags
    become discardable).
  - `maplist.lua`: recompiled; 31 extra constants and changed float coordinates (map placement values). The source
    name is stripped from the chunk header.
  - `title.lua`: one extra title.
- **Binary assets** patched by overrides: `UI_6/7.jpk` (VIP three-column UI, chat badge), `Unit_7.jpk` (female splash
  hit-stop). `steam_api.dll` in the package is Valve's genuine DLL (same hash as our `steam_api.dll.bak`).
- `game-template/` otherwise contains the stock client files (BugTrap, Bandisoft video DLLs, JCR `PatchRecovery.exe`,
  `GameGuard.des`, `JFirewall.dll`); all are identical to ours except those listed.

## Server-side features visible in the package (not client features)

From `client-package.json` `contentOverrides` and `revival/`:

- VIP system (badge in chat, gameplay and enhancement display), default fatigue capacity 2x, a local cash-claim flow
  (`steam-local-cash-claim-v1`), fishing policy, waypoint pricing, guild promotion/foundation policy, forest spawns,
  card events, several original-scene scripts (quests 93/119, Flame Soldiers), and a GM client (`steam_gm_client.js`).
- `revival/tools/game_protocol.py`, `party_protocol.py`, `scene_protocol.js`, `character_detail.py` and
  `proudnet_local.py` document wire layouts the authors recovered from the same client. They may help with our
  unmapped fields (`docs/UNMAPPED_FIELDS.md`) but are third-party code of unknown license: use them as evidence leads
  and re-verify against the client, do not copy them (this project is AGPL-3.0).

How the client is modified: a Python launcher starts the original EXE and attaches **Frida** (vendored
`frida-17.19.0`), installing byte-guarded memory hooks (for example the multi-client patch renames the two singleton
mutexes `DarkBlood Recovery` and `DarkBlood Online`). Hooks check the EXE hash and instruction bytes before patching.
Our approach (a `steam_api.dll` shim) is different but equivalent in effect.

## Network behavior of the package

- Configured server: `120.26.7.29` (HTTPS 443, game 10496, relay 10497; `connection.example.json`), validated against
  the pinned self-signed `tools/server-ca.pem` ("DarkBlood Server CA", valid 2026-10-20 to 2027-10-21). Redirects are
  disabled and system proxies are ignored in `platform_ticket_gateway.py`.
- Local only: `127.0.0.1:19496` notice proxy and `127.0.0.1:4196`.
- Credentials: `client_bundle.py` asks for an account and password (`getpass`) or receives a platform ticket on a
  private stdin pipe; tickets use a PKCE-style challenge/verifier and are sent only to the configured server's
  `/revival/v1/steam/login`. Status output filters keys such as password, ticket and token.
- Other behavior worth knowing: the launcher self-elevates through `ShellExecuteEx` with `runas` (the original EXE's
  manifest requires administrator); it ships a full CPython 3.12 runtime whose `python.exe` and DLLs are
  PSF-signed and has no `sitecustomize`/`.pth` hooks; there is no scheduled task, registry autorun, certificate-store
  installation or clipboard/keyboard capture in the launcher scripts that were read.
- Not audited: the 400 files under `revival/` were sampled (all launchers, tools and the protocol modules' headers),
  not read line by line; `launcher/online_update.py` and `DarkBloodLauncher.exe` are referenced but absent;
  the vendored `frida`, `Crypto`, `capstone` and `pefile` trees were not diffed against upstream wheels.
  Treat it as untrusted: run it only in a VM, and do not enter real credentials.

## Telemetry inside the client itself (applies to our client too)

Strings in the unpacked image (`research/unpacked.analysis.exe`) include leftovers from the Chinese publisher build:

- `http://mon.changyou.com/client.html?gametype=%s&version=%s&param=%d&mac=%s&ip=%s&hdserial=%s`: a monitoring ping
  carrying the **MAC address, IP and hard-disk serial**.
- `http://account.changyou.com/fangchenmi/submitlogin.jsp` (Chinese anti-addiction check) and
  `http://darbloodzonelist.changyou.com/zonelist.asp` (server list).
- `http://www.jcrsoft.co.kr/patch_test/Pub/` (JCR SOFT patch server, used by the patcher) and UPnP
  `AddPortMapping`/`DeletePortMapping` SOAP bodies.

Status: these are **observed strings only**. We have not traced whether the monitoring call is reachable in the Steam
build. Runtime evidence so far: the shim redirects every IPv4 `connect()` to loopback and `hook_log.txt` of the
latest session shows only `54.173.235.121:9400` (redirected) and the local relay. HTTP over WinInet would not use
the redirect if it goes through paths the shim does not cover (IPv6, `WSAConnect`, `ConnectEx`, UDP; see ROADMAP P5),
so complete isolation is not yet proven. Next step: trace the xrefs to `0xD25708` with the shim's `bp.txt` tracer
or Ghidra (a quick byte scan found no `push` of that address in code, so the reference may be indirect).

## Improvement leads for this project (all unverified until checked against our client)

Source files are in the package under `revival/`; addresses are Steam x86 VAs. Each lead needs a client-reader or
live check before it enters a schema. Highest value first.

1. **Town movement desync (ROADMAP P6).** `scene_protocol.js` documents two client behaviors:
   - The town movement sender `0x87C0D0` passes 8 (or 2) as the limit argument of `0x966B90`, which selects a
     per-peer **2000 ms throttle** (`peer+0xC0 + 0x7D0`). With `-1` it sends to every ready peer on each `0x95E260`
     pulse (about 200 ms). The package patches the two `MOV EDI` immediates near `0x87C1D2`
     (`bf08000000` / `bf02000000`). Find out when the throttle branch is taken and whether our shim needs the same patch.
   - The receiver stores the latest remote position at `peer+0x108/+0x10C` (`0x855F7E`, `0x855F88`). For errors of
     32..1024 it walks the actor there with its own path request (`0x810CA0`), which can stall behind obstacles
     (the package teleports a stuck actor). This matches our world-map click-to-move symptom.
2. **Zero-filled blocks in the 2007 character details** (`Character.encode_world_details`). The package's fixture
   (`revival/tools/character_detail.py`, `steam_character_detail.py`) sends constructor defaults where we send zeros:
   the 24-byte block read by `0xA488F0` has bytes 0-4, 6, 7, 10-14 and 23 set to 1 and two floats 1.0 at offsets 15
   and 19 (probably the play-options struct, cf. 2216), and the five-element vector after it holds five `i64 -1`
   instead of our empty vector. Try these and watch the options and slot UIs.
3. **Native GM console.** The client has a built-in command console (`0x4EF790`, commands `ar ap coin itemcall lv
   allskill clearbag stressall upgrade forceupgrade attack maxatk speed ...`) that sends the `eEGS_CHEAT_*` events
   2057, 2061, 2088/2089, 2101, 2103, 2105, 2107, 2130, 2137 and 2414 when the protected GM flag at `JUser+0x58`
   bit 0 is set. The package clears that bit after 5020, so the stock 5020 handling sets it, most likely from
   `nAuthLevel` in our welcome (currently 0). Test a non-zero auth level, then implement those cheat handlers
   (none exist yet) instead of custom chat commands.
4. **Attendance calendar (CRONOS).** Opening the calendar page (vtable `0xC9D1FC`) sends 2289 and 2299 and waits for
   2291 (`UPDATE_DATA_NOT`), retrying up to 3 times; related replies are 2290, 2298 and 2300. We handle none of these.
5. **Room records.** The package's `jRoomInfo` reader shows the second unknown `i64` after the host id is `-1` in
   server-built rooms (we send 0) and `state` is 0 in 5002; 5004 carries leader `i64`, a count-checked vector of
   full character structs, a 4-byte IP plus `u16` port and two bools. `revival/scene/party_protocol.py::member`
   walks a member element field by field, which can fill our `vector<?> members` in `party.jsch`.
6. **Notice page.** The client opens `http://www.jcrsoft.co.kr/patch_test/Pub/` (push at `0x5A9B34`, notice opcodes
   `HTTPNOTICE_*`). Unless redirected, that is an outbound request on login. The package serves its own notice on a
   local port; we could serve a local page and rewrite the string in the shim.
7. **Waypoints.** The client prices a waypoint itself (`GetCost` at `0xA688E0`): `floor(baseCost[source][target] *
   levelRatio[level] + 0.5)` over a complete source/target matrix; the server must charge the same. The
   `WAYPOINTCHARLAYER_*` opcodes (6) are unimplemented here.
8. **Fishing and guild.** `revival/server/data-steam/fishing.json` lists fishing lures (`DictItem` type 45) and fishing
   skill rows (`DemandProficiency`, `MaxProficiency`); we implement none of the 9 `FISHING_*` opcodes. The guild policy
   patch shows the client clears the party-leader/member-count requirement bits when founding a guild alone and
   confirms promotion with the selected character; we have 44 unimplemented `GUILD_*` opcodes.
9. **Localization and fonts.** The package ships repacked `Localization_ST_0.jpk`, `UI_ST`/`Font_ST` archives and a
   Noto UI font that the client loads, which supports our deferred UI-text fix as an archive overlay (using
   `tools/jpk_pack.py`). Font sizes are patched at runtime in the JFont descriptors (stride `0x50`, constructors
   `0x411138..0x411604`). Note: the card-event adapter documents that the client's CRT local-time conversion rejects
   some valid years, which matters for any date fields we send.
10. **Transport cross-check.** `steam_transport.py` records application GUID `d7b1109d-6145-4635-a8cd-ecb5cf75e799`,
    version 197015, strong key 16 bytes (RSA-OAEP/SHA1), AES-ECB with CRC32 trailer, and the settings hint layout
    `<BIIIBIBII7BI`. Our server does not check the GUID or version; compare the hint bytes with ours.
11. **Private extension events** `29001..29003` and `29140/29141` are the package's own (GM, calendar); they are not
    part of the client protocol and must not be mistaken for opcodes.

## Follow-ups

- [ ] Find the code that uses the `mon.changyou.com` string and whether it runs; block it in the shim if so.
- [ ] Extend the network hook to `WSAConnect`/`ConnectEx`/IPv6 so an offline session cannot reach these hosts.
- [ ] Work through the leads above, verifying each against the client reader before changing a schema.
