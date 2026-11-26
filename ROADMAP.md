# Roadmap — Dark Blood Offline Server Emulator

Updated **November 20, 2026**. Target client: `DarkBlood.exe`, SHA-256 `a82ae3d7…c931` (see the README).

Final objective: launch without the original services, establish a local session, persist character and world
state, enter maps and dungeons, and provide offline single-player and LAN multiplayer gameplay.

This file lists **what is still open**. Finished work is recorded in `docs/STATUS.md` (evidence log), per-opcode
state in [`docs/OPCODE_REGISTRY.md`](docs/OPCODE_REGISTRY.md), and the per-domain field coverage in the README
progress table and [`docs/UNMAPPED_FIELDS.md`](docs/UNMAPPED_FIELDS.md).

---

## Milestones

| Milestone | Scope | Status | Remaining |
|---|---|---|---|
| **P0 Enter the World** | Handshake, auth, lobby, selection, town | Done | — |
| **P1 Transport & Serialization** | ProudNet framing, JSerBuffer, crypto | Done | Server→client encryption, `0x1D` ACK, UDP (below) |
| **P2 Lobby & Account** | Character list/create/delete, SQLite store | Done | Multiple accounts |
| **P3 Gameplay & Economy** | Combat, dungeons, drops, store, level-up | Mostly done | Monster AI/damage, live checks of the 11-20 work |
| **P4 Assets & Config** | JPK unpacker, normalized `assets/` tables | Mostly done | Skill formulas, `DarkbloodKR.ini` flags |
| **P5 Stability & Launcher** | Steam shim, `gamectl`, MCP, dashboard | Mostly done | Full network isolation, test-client staging, release build |
| **P6 Multiplayer & Relay** | Relay, town presence, party, rooms | In progress | Movement desync, shared dungeon instances |
| **P7 Commerce & Post** | Trade, mail, stalls, broker, depot | Done | Live verification |
| **P8 Guild & Arena** | Guild bank/skills, duels, arenas, ranks | Mostly done | Guild war and siege |
| **P9 Architecture** | Schema-generated messages, opcode registry | Mostly done | Items below |
| **P10 C# / .NET 8 port** | MHServerEmu-style server | Planned | Everything |

---

## Open work

### Protocol and transport (P1)
- [ ] Investigate the `0x1D` control message and its official ACK (current `0x1F` reply is exploratory).
- [ ] Optional server→client encryption (symmetric AES) when the client enables it.
- [ ] Evaluate a UDP route for fast position sync (`JP2PClient` type `0x27`).
- [ ] Recover the source of the `ffffff7f` request header word (runtime dependent; see PROTOCOL.md).

### Account and lobby (P2)
- [ ] Multiple accounts and profile switching.

### Gameplay (P3)
- [x] Attendance calendar (CRONOS 2289-2300), native GM cheat opcodes, fishing (9/9), guild domain sweep.
- [x] Constructor defaults in the 2007 details (24-byte options block) and non-zero `nAuthLevel` in 5020 (`gm_mode`).
- [ ] Live-check the random-box success notification (`2196`) and confirm the expected learned-skill map after subclass promotion.
- [ ] Monster AI aggro and damage calculation from the client property tables.
- [ ] Live checks for the 11-20/21 work: gate history and quest variants, EXP bar, town AR, chest names,
  counter achievements, revive layer, floor gold, stress, 6012 View Info, 5022 host promotion, 2134 memo.
- [ ] Zero-filled fields in the result (5018) and gate (5044) messages, achievement rewards and group
  achievements (`2331`/`2332`, Type 2/3), item dyes (see `docs/UNMAPPED_FIELDS.md`).

### Assets and configuration (P4)
- [ ] Parse skill damage formulas and cooldowns (`Data/Dict/skilllist.lua`).
- [ ] Investigate `DarkbloodKR.ini` flags and client customization toggles.
- [ ] Optional: fix the shipped English UI text in `Data/localization_st/ui_st.dat` (UTF-16, `ID<TAB>text`), on a
  separate copy only, never through the `research/client/Data` junction. Known mistranslations: `UI_504` "Item"
  heads the channel list's Category column; `UI_1213` "Character" heads the server list's count column.
  Deferred by the user (2026-11-16).

### Stability and tooling (P5)
- [ ] Verify complete network isolation: hook `ConnectEx`, IPv6 and UDP (`connect` and `WSAConnect` IPv4 are hooked).
- [x] Automatic test-client staging (`stage_client_folder()` in `tools/launcher/launcher.py` — copies EXE, backs up `steam_api.dll`, creates `Data` junction, deploys hook).
- [x] Release build producing a portable launcher zip (`tools/launcher/build_release.py` + `.github/workflows/release.yml` with prebuilt x86 `steam_api.dll` + GitHub Releases auto-updater in `tools/launcher/updater.py`).
- [ ] Find whether the client's `mon.changyou.com` monitoring ping (MAC, IP, disk serial) can run and block it
  (`docs/CLIENT_LEADS.md`).
- [ ] Steam shim: SteamUser has three slots and SteamFriends one; other interfaces return placeholder `1`.

### Multiplayer (P6)
- [ ] Town send throttle (`0x87C0D0` limit 8/2 selects a 2000 ms per-peer branch) and remote-position drift handling
  (`peer+0x108`, path request `0x810CA0`): see `docs/CLIENT_LEADS.md` lead 1.
- [ ] Town movement desync/latency (worst with world-map click-to-move): decode relayed P2P messages with the
  server-generated keys and compare against the peer view.
- [x] Answer 5060 (room member info) and 5088 (party looting mode).
- [ ] Validate the corrected 5051 invitation notice in the client dialog.
- [ ] Profile client revision eligibility and playback separately from relay forwarding; per-instance command
  ownership for shared room work.
- [ ] **Shared dungeon instances**:
  - Party members enter the same instance; complete the 5004 member fields and shared room/relay routing.
  - Live-check the manual host handover (5021 -> 5022, headless-verified 2026-11-26) in the party room UI.
  - Live-check party 5014 (`player_count`, shared `rand_seed`, `peer_skills`, headless-verified 2026-11-26); the pet map's key and consumer remain open.
  - Synchronize monster health, damage numbers and boss cinematics.
  - Shared party rank and card reward selection at dungeon finish.

### Guild (P8)
- [ ] Guild war declaration and castle siege (gate destruction, flag capture).
- [ ] Mount summoning (`ridecall`) and pet items (`PetCall`) live checks.

### Architecture (P9)
- [ ] Decide what to do with the invented party opcodes (2100-2107), which the client names as cheat messages and does
  not handle. (The invented 5021/5022 square notices were removed on 2026-11-26; those opcodes are the room-host pair.)
- [ ] C# backend for `tools/codegen/gen_messages.py` that emits the same schemas as C# classes.
- [ ] Reduce the unmapped fields shown in the README progress table (the number that matters most for fidelity).

### C# / .NET 8 port (P10, MHServerEmu layout)
- [ ] Solution scaffolding: `DarkBlood.Core` (binary primitives, JSerBuffer, crypto), `DarkBlood.Network`
  (ProudNet framing, sessions), `DarkBlood.Database` (SQLite), `DarkBlood.GameServer` (dispatcher and domain services).
- [ ] ProudNet RSA + AES key exchange and framing in C#; JSerBuffer varuint and wide strings.
- [ ] Attribute-based routing (`[PacketHandler(Opcode.…)]`), the 2007 character payload builder, asset loaders.
- [ ] xUnit replicas of the headless tests, then a live client against the C# server.

---

## Verification

Headless suite: `python -m unittest discover -s tests -v` (drives the server with `tools/automation/headless_client.py`; real
handshake and encryption, no window). CI runs it on every push (`.github/workflows/ci.yml`).

Live checklist (use `tools/automation/gamectl.py enter-lobby`; launch the client only to confirm it parses a changed response):
- [ ] Store: buying decrements gold and adds the bag icon; selling removes it.
- [ ] Equipment window shows worn gear; dragging a weapon to a slot updates the mesh.
- [ ] Skill window: spending SP raises the skill and enables it on the hotbar.
- [ ] Dungeon entry loads the map and spawns monsters with health bars.
- [ ] Combat: hit sound, floating damage numbers, death animation.
- [ ] Level-up fanfare when the EXP bar fills.
- [ ] Card reward UI after a clear; return to town by portal. One card claim per character per clear is verified headlessly.

Still to write:
- [x] Fuzz JSerBuffer varuints and scalar widths; out-of-order packets (gameplay before auth); truncated-frame floods (`tests/test_fuzz_and_load.py`).
- [x] 10 simultaneous headless clients (login, select, town presence & chat) with broadcast delivery checks (`tests/test_fuzz_and_load.py`).

---

## Future tools
- [ ] Packet inspector in the GM dashboard (`tools/launcher/dashboard.py` already shows telemetry and edits characters).
- [ ] Asset modding toolkit: browse, modify and repack JPK archives; quest-string localization.
