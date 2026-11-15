# Roadmap — Dark Blood offline

Documentation handoff: **November 16, 2026**, covering the November 15 investigation. Experimental work is paused at the user's request.

Final objective: launch without the original services, establish a local session, persist a character, enter a map, and verify offline gameplay.

## Current milestones

| Milestone | Status |
| --- | --- |
| Client startup / minimal Steam support | Verified through the current initialization stage |
| Unpacked code for analysis | Captured locally |
| IPv4 TCP redirect to localhost:9400 | Verified |
| Local plaintext ProudNet handshake | Accepted by the client |
| Connection callback | `result=0`, observed |
| Application message 5020 | Deserialized; body cursor reaches 100 bytes |
| Next message 2403 | Awaited; response not implemented |
| Login / server list / characters / map | Not implemented or not verified |
| Gameplay and persistence | Not implemented |

## P0 — Resolve the immediate blocker

- [ ] Trace ProudNet `SendUserMessage` and OnError/OnWarning callbacks without changing their results.
- [ ] Explain why application request `2402 / 0x0962`, constructed by `0x0079A970`, does not appear in the TCP capture after welcome.
- [ ] Follow `0x007874A0 → vtable +0xC8 → 0x00B55A30 → 0x00B75710 → 0x00B3FEC0 → 0x00B76050 → 0x00B53310`.
- [ ] Inspect the object pointer at `+0x1570`, the value at `+0x1500`, transport state, and destination in `0x00B53310`. Establish pointer semantics through its constructor and uses.
- [ ] Determine which initialization the shortened handshake skips: ServerSettings, UDP/TCP state, session keys, or send limits.
- [ ] Recover the parser and meaning of awaited message `2403 / 0x0963`, then implement confirmed fields.

Acceptance: capture the relevant client request, deliver a parser-accepted response, and observe initialization advancing past `0x0963` without forcing a client-side result.

Local starting points: `research/tcp-route.c`, `route.c`, `proud-send.c`, `send.c`, `welcome.c`, and `startup-wait.c`. Addresses are also preserved in [PROTOCOL.md](docs/PROTOCOL.md), since `research/` is not tracked.

## P1 — Reproducible transport and serialization

- [ ] Test ProudNet signed scalar boundaries, invalid widths, truncation, fragmented/coalesced TCP frames, and invalid sizes.
- [ ] Add a regression fixture for `13 57 01 05 30 0F 00 00 40`.
- [ ] Implement a bounded JSerBuffer/JEvent reader: inverted terminal bit, UTF-16, empty bodies, and compression. The current module primarily implements writers.
- [ ] Distinguish ProudNet control messages, RMIs, and application events in logs.
- [ ] Preserve small capture fixtures without personal information.
- [ ] Identify `0x1D`; its current `0x1F` response is experimental.
- [ ] Establish whether the local connection can remain plaintext or requires negotiation `5/6`.
- [ ] If required, recover ServerSettings, RSA key representation, session keys, and encrypted/compressed envelopes.
- [ ] Establish a verified TCP-only route before implementing full UDP/P2P.

Acceptance: repeated clean client launches follow the same documented sequence without arbitrary delays or guessed packets.

## P2 — Initialization, authentication, and lobby

- [ ] Identify the semantics of every field in message 5020; current values are test defaults.
- [ ] Recover bootstrap, server/channel list, and authentication operations from the application dispatcher.
- [ ] Implement a local account and explicit session states.
- [ ] Recover addresses and ports for subsequent connections.
- [ ] Implement character listing, creation, and selection using the client's actual parsers.
- [ ] Add simple, versioned local persistence with an explicit reset operation.

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
- [ ] Add a launcher with client hash verification, test-copy preparation, startup/shutdown, and restoration.
- [ ] Investigate WSAConnect/ConnectEx/IPv6/UDP and additional outbound connections.
- [ ] Separate or archive the speculative Auth/Lobby prototype.
- [ ] Test from a clean checkout and clean local state without the original services.

Final acceptance: installation, launch, gameplay, saving, and shutdown are reproducible, documented, and verified.
