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

## Follow-ups

- [ ] Find the code that uses the `mon.changyou.com` string and whether it runs; block it in the shim if so.
- [ ] Extend the network hook to `WSAConnect`/`ConnectEx`/IPv6 so an offline session cannot reach these hosts.
- [ ] Mine `game_protocol.py`/`party_protocol.py`/`scene_protocol.js` for layouts of our unmapped fields
  (lobby, dungeon, social), verifying each against the client reader.
