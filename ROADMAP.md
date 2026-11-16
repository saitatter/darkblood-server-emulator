# Roadmap — Dark Blood offline

Updated **November 16, 2026** (second session).

Final objective: launch without the original services, establish a local session, persist a character, enter a map, and verify offline gameplay.

## Latest local verification ? Cristian, 2026-11-16

See [session handoff](docs/SESSION_HANDOFF.md). Selection ACK parsing and mailbox
continuation were reproduced, but world entry is not verified. The concrete
blocker is Proud::Exception 14 (Unknown Internet address) during connection
validation at 0x00B54B40, followed by the 30-second selection wait timeout.

- [x] Correct implicit struct tags, trailer u8, absent lookup sentinels and result prefix.
- [x] Add empty mailbox ACK 2220 and handle the exercised SteamUser slot 16.
- [x] Capture the post-selection C++ exception without swallowing it.
- [x] Trace the endpoint: 2007 connects `JP2PClient` to the relay buffer filled by 5134 (`0x0075AAE0`), not by `0x00A48A90`.
- [x] Send 5134 (127.0.0.1:9401) after 5029 and run a relay listener; selection wait completes.
- [x] Town rendered with the character and an NPC dialogue that advances with Space (saitatter machine).
- [x] Answer 2131 friend list and 2569; recover the relay server's application protocol (PIDL JoinGroup/JoinGroupACK).
- [x] Answer 2082 clear tutorial -> 2083 (triggers Scene 9 Town), 2346 tutorial quest start -> 2347, 2390 roulette -> 2391.
- [x] Headless/automated tests: protocol-level client replay without the graphics window (`tests/test_headless_flow.py`).
- [x] Explain the skip-tutorial loop: SquarePlay can-enter rejected `nJoinLayerNetID = 0`; send `jhash("Act1") << 32 | 1` (static + headless).
- [x] Live: tutorial-cleared character enters SquarePlay; offline ISteamUserStats fixes the town-entry crash.
- [ ] Live-verify skip with a fresh character; answer 5124, 2594, 2216, 2369, 2712, 2024.
- [x] Correct JPK decryption (header flag `0x226`, whole blob); byte-identical repacker; private client-data workspace.
- [ ] Load one edited JPK entry in the client (crc field semantics unknown).
- [x] Live: movement, map change (5030/5031), NPC store window (2066), quest accept/complete (2074/2077).
- [x] Headless: 2010/2011 room list and 5001/5002 create room (singleplay).
- [x] Correct 5014 start-game string/container framing from the client reader (static + headless).
- [x] Live dungeon entry (single play): 5043/5044 gate, 5009/5010 map code, 5013/5014 start; Lucid Forest (`Act1_G1_A10`) loads with monsters.
- [x] Dungeon schemas: 5095 CHANGE_DUNGEON_LAYER_NOT, 2422 ACTIVE_WARFLAG_REQ, 2358 GUIDE_BEGINNER_UPDATE, 5063 MONSTER_DEAD_REQ, 5064 DROP_ITEM_NOT mapped; kills/rewards/clear next.
- [x] Active quests restored at selection (2007 map 0xA3E450); quest gold/EXP rewards from DictQuest (live: EXP bar, Ar gold).
- [x] Default equipment worn from DictItem:LoadDefaultEquipItem (2007 bag/item vectors; live).
- [x] Bag cells: recovered +0x28 tab filter, +0x29 capacity, +0x2A UI slot, bag_id high dword from client (0x00827D80, 0x005509F0, 0x00551310); container 2 added.
- [x] Inventory & combat schemas: 2036/2037 drag item (slot swapping & persistence), 2028 close bag, 2406/2407 stat verify, 5093/5094 death notification, 2448/2449 rebirth coin revive.
- [ ] Level-up on EXP overflow (charstat.lua UPExp), mission counters, package items (CPkg...).
- [ ] Verify NPC interaction and persistence across sessions before claiming gameplay.

## Current milestones

| Milestone | Status |
| --- | --- |
| Client startup / minimal Steam support | Verified |
| IPv4 TCP redirect to localhost:9400 | Verified |
| ProudNet handshake with real key exchange (5/6/7) | Verified; client messages decrypt with valid CRC |
| Welcome 5020, DB list 2403 | Verified |
| Title → Server List → Channel List | Verified on screen |
| Character list / creation (persisted) | Verified on screen; several fields unknown |
| Select character → enter map (2006/2007 + relay 5134) | Town rendered; movement not yet verified |
| Movement, combat, persistence of progress | Not started |
| Control tooling (`gamectl`, MCP server) | Implemented |

## P0 — Enter the world

- [x] Explain why 2402 was never sent (missing session key; strong encryption mode 1).
- [x] Implement ProudNet RSA/AES key exchange and decrypt type 0x26.
- [x] Recover and answer 2403, 2002, 2022, 5029, 2009, 2013.
- [ ] Recover struct `0x00A40760` and vector `0x004B9210` for opcode 2007 (handler `0x007AA4B0`); implement the response.
- [ ] Observe the client's next requests after 2007 (map loading, possibly a new connection or square/room join) and answer them.
- [ ] Identify level/location fields shown on character select.

Acceptance: the selected character loads into a map and is visible and controllable.

## P1 — Reproducible transport and serialization

- [ ] Test ProudNet signed scalar boundaries, invalid widths, truncation, fragmented/coalesced TCP frames, and invalid sizes.
- [ ] Add a regression fixture for `13 57 01 05 30 0F 00 00 40`.
- [ ] Implement a bounded JSerBuffer/JEvent reader: inverted terminal bit, UTF-16, empty bodies, and compression. The current module primarily implements writers.
- [ ] Distinguish ProudNet control messages, RMIs, and application events in logs.
- [ ] Preserve small capture fixtures without personal information.
- [ ] Identify `0x1D`; its current `0x1F` response is experimental.
- [x] Negotiation 5/6 is required for game requests; ServerSettings, RSA and AES envelopes recovered.
- [ ] Decide whether server → client messages should be encrypted.
- [ ] Establish a verified TCP-only route before implementing full UDP/P2P.

Acceptance: repeated clean client launches follow the same documented sequence without arbitrary delays or guessed packets.

## P2 — Initialization, authentication, and lobby

- [ ] Identify the semantics of every field in message 5020; current values are test defaults.
- [ ] Recover bootstrap, server/channel list, and authentication operations from the application dispatcher.
- [ ] Implement a local account and explicit session states.
- [ ] Recover addresses and ports for subsequent connections.
- [x] Implement character listing and creation using the client's parsers (selection pending).
- [x] Simple versioned local persistence (`data/characters.json`); reset = delete the file.

Acceptance: the client displays a local server/channel, creates and selects a character, and retains it after restart.

## P3 — Map entry and minimum gameplay

- [ ] Recover lobby-to-square/zone transfers and real map IDs.
- [ ] Implement spawn, coordinates, movement, and heartbeats.
- [ ] Implement the minimum inventory/equipment state required by the client.
- [ ] Recover combat synchronization, monsters, and dungeon transitions.
- [ ] Implement damage, death/revival, loot, and persistent progress.
- [ ] Verify actual movement and a combat cycle in the client.

Acceptance: a character enters a map, moves, and completes a minimum gameplay loop with saved state.

## P4 — Assets and configuration

- [ ] Repair and validate JPK decryption; existing extracted XML is malformed.
- [ ] Validate the key/algorithm against multiple parseable files rather than a guessed XML header.
- [ ] Recover the actual algorithm from the client and distinguish encryption/compression layers.
- [ ] Investigate `DarkbloodKR.ini`, server configuration, and map/class/item tables.
- [ ] Harden the extractor against EOF, invalid varints, sizes/offsets, path traversal, and decompression errors.
- [ ] Extract needed assets selectively after validating the decoder.

## P5 — Stability and launcher

- [ ] Replace Steam pointer `1` placeholders with correct interfaces for exercised methods; verify x86 ABI and struct returns.
- [ ] Implement callbacks/tickets required by the observed local flow.
- [ ] Remove dead termination-hook code and make diagnostics optional.
- [ ] Fix builds: MSVC detection, working-directory independence, failure propagation, and stale-DLL prevention.
- [x] Session control with hash verification and owned-process shutdown (`tools/gamectl.py`, MCP `tools/mcp_server.py`).
- [ ] Test-copy preparation and shim build/deploy in the launcher.
- [ ] Investigate WSAConnect/ConnectEx/IPv6/UDP and additional outbound connections.
- [x] Separate or archive the speculative Auth/Lobby prototype (`legacy/speculative_prototype/`).
- [ ] Test from a clean checkout and clean local state without the original services.

Final acceptance: installation, launch, gameplay, saving, and shutdown are reproducible, documented, and verified.
