# Server architecture

The server is a Python package, `src/darkblood`, laid out like
[MHServerEmu](https://github.com/Crypto137/MHServerEmu) so that it can be
ported to C#/.NET later. Each top-level subpackage maps to one future C#
project; folder names inside follow MHServerEmu's (`Network`, `Entities`,
`Missions`, `GameData`...). Python stays on the standard library (3.8+).

```
run_server.py                    entry point from the repo root (python run_server.py)
assets/                          normalized tables the server ships (opcodes, items, quests,
                                 maps, achievements, cash shop...); tools/export_assets.py
                                 regenerates them from an extracted client
src/darkblood/
  __main__.py                    python -m darkblood (src/ on sys.path)  -> C#: DarkBlood (host)
  core/                                                                   -> C#: DarkBlood.Core
    hashing.py                   JHashString (client 0x00B3B5A0)
    options.py                   server options
    network/proudnet.py          ProudNet framing, scalars, control messages
    network/crypto.py            RSA-OAEP / AES and the ProudNet envelope
    serialization/jser.py        JSerBuffer varuints, J-wstrings, JEvent envelope
  frontend/                                                               -> C#: DarkBlood.Frontend
    server.py                    TCP listeners, handshake, key exchange, wire log
    relay.py                     square/room relay address + relay PIDL (JoinGroup)
  player_management/                                                      -> C#: DarkBlood.PlayerManagement
    characters.py                create-request parser, default inventory, equipment rules
    store.py                     SQLite character store (data/darkblood.db)
  games/                                                                  -> C#: DarkBlood.Games
    session.py                   GameSession and the startup DISPATCHER
    dispatcher.py                opcode -> handler registry (rejects duplicate owners)
    config.py                    local server list, channels, slot count
    world.py                     town presence by (square, layer), parties
    progression.py               levels and AP
    achievements.py              counter achievements from 2446 reports
    loot.py, stalls.py           drop rolls, personal shops
    handlers/                    one domain service per file:
      frontend social square commerce inventory skills quests dungeon arena pets mail
    network/messages/            one dataclass per message, by domain (encode/decode)
    network/results.py           client result codes
    entities/character.py        Character + lobby/world-detail encodings
    entities/items.py            Item (0x00A53F50), Bag (0x00A1EC30)
    missions/quests.py           ActiveQuest (2007 map 0x00A3E450)
    game_data/client_dict.py     readers for assets/ (or an extracted client override)
    game_data/cash_shop.py       purchase catalog
tests/                           headless end-to-end tests (no game window)
tools/                           gamectl, MCP server, headless client, asset export,
                                 opcode registry generator, RE helpers
```

## Rules

- Dependencies point downward: `core` imports nothing from the package;
  `games` may use `core`; `frontend` hosts `games.session`; handlers never
  import `session` (shared helpers live next to the handlers that own them).
- New opcode: add the message dataclass to the matching
  `games/network/messages/<domain>.py` (docstring starts with `Opcode N:` and
  names the client reader addresses), then an `on_<opcode>` method in the
  matching `games/handlers/*.py` service, then a headless test. Regenerate
  `docs/OPCODE_REGISTRY.md` with `python tools/gen_opcode_registry.py`.
- Domain rules that are not wire handling (progression, achievements, loot)
  live in plain modules under `games/` so handlers stay thin.
- Extracted client data (`../darkblood-client-data`) stays private. The
  server ships normalized tables in `assets/`; `tools/export_assets.py`
  regenerates them.

## Porting notes

`GameSession` mixins map to partial classes or handler classes registered by
opcode. Dataclass `encode()` methods map to serializers on message types; the
JSer helpers in `core/serialization/jser.py` are the only wire primitives the
game layer needs.

## Performance and ownership review

Town movement uses a client-generated `0x4D` revision inside a peer
payload. The current clients emit revisions about every 215 ms with the
100 ms shim throttle. In an isolated Windows loopback run of the real
relay path with two headless connections, the median send-to-receive time
was 0.26–0.27 ms with synchronous wire capture and 0.059 ms with capture
disabled. The 95th percentiles were 0.42–0.43 ms and 0.07–0.11 ms
respectively (two runs of 280 measured messages per mode, sequential
sends). This measures the two-peer forwarding path without contention
or client rendering.

1. **Town playback.** Timestamp the client eligibility check
   (`0x008464E0`), revision enqueue (`0x0087C25E`), and receiver apply
   before changing another timer. Measure sender and receiver intervals
   during continuous movement and after direction changes. Any
   interpolation should target the client consumer of actual peer
   revisions.
2. **Opcode ownership.** The startup registry validates unique ownership
   and dispatches every request through a uniform async signature. The
   game connection owns its authenticated account and selected character.
   Quest, stall, arena, and pet requests use their client opcodes.
3. **Lobby and instance lifecycle.** World presence is indexed by
   `(square, layer)` for town fan-out. The next step is to let each dungeon
   instance own its membership, room state, and lifecycle commands. Resolve session
   identity at the boundary, then enqueue typed joins and departures
   for the owner. NexusForever's `MapManager` drains pending admissions
   before updating maps, and its entity command handler forwards to the
   controlled entity's movement manager. MHServerEmu drains network input
   ahead of fixed-step simulation and uses per-connection area of
   interest. Use these boundaries first for shared rooms and despawn
   ordering. Town can keep its existing peer protocol.
   [NexusForever MapManager](https://github.com/NexusForever/NexusForever/blob/43004fc8bdd8769342cd59783315f6dd484b1394/Source/NexusForever.Game/Map/MapManager.cs)
   [NexusForever movement entry](https://github.com/NexusForever/NexusForever/blob/43004fc8bdd8769342cd59783315f6dd484b1394/Source/NexusForever.WorldServer/Network/Message/Handler/Entity/ClientEntityCommandHandler.cs)
   [MHServerEmu update loop](https://github.com/Crypto137/MHServerEmu/blob/1a309e526a74b2066ea6705e7ca4e17c4ba32489/src/MHServerEmu.Games/Game.cs#L207)
   [MHServerEmu AreaOfInterest](https://github.com/Crypto137/MHServerEmu/blob/1a309e526a74b2066ea6705e7ca4e17c4ba32489/src/MHServerEmu.Games/Network/AreaOfInterest.cs#L97)
4. **Relay and persistence under load.** Track event-loop delay, outgoing
   buffer size, fan-out and database flush time. Move optional packet
   capture off the hot path with a bounded queue and drop counter,
   preserving gameplay messages and diagnostic ordering. Relay roster
   updates are serialized once per join. Replace whole-cache saves with
   explicit dirty records, preserving atomic trade or inventory changes
   across characters. Keep these changes independently measurable.
