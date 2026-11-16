# Server architecture

The server is a Python package, `src/darkblood`, laid out like
[MHServerEmu](https://github.com/Crypto137/MHServerEmu) so that it can be
ported to C#/.NET later. Each top-level subpackage maps to one future C#
project; folder names inside follow MHServerEmu's (`Network`, `Entities`,
`Missions`, `GameData`...). Python stays on the standard library (3.8+).

```
run_server.py                    entry point from the repo root (python run_server.py)
assets/                          opcode tables extracted from the client
  opcodes.tsv, opcode_pairs.tsv, opcode_flags.tsv
src/darkblood/
  __main__.py                    python -m darkblood (src/ on sys.path)  -> C#: DarkBlood (host)
  core/                                                                   -> C#: DarkBlood.Core
    hashing.py                   JHashString (client 0x00B3B5A0)
    network/proudnet.py          ProudNet framing, scalars, control messages
    network/crypto.py            RSA-OAEP / AES and the ProudNet envelope
    serialization/jser.py        JSerBuffer varuints, J-wstrings, JEvent envelope
  frontend/                                                               -> C#: DarkBlood.Frontend
    server.py                    TCP listeners, handshake, key exchange, wire log
    relay.py                     square/room relay address + relay PIDL (JoinGroup)
  player_management/                                                      -> C#: DarkBlood.PlayerManagement
    characters.py                create-request parser, default inventory
    store.py                     SQLite character store (data/darkblood.db)
  games/                                                                  -> C#: DarkBlood.Games
    session.py                   GameSession: JEvent dispatch to on_<opcode>
    state.py                     state shared by game and relay connections
    config.py                    local server list, channels, slot count
    handlers/                    one mixin per domain, combined by GameSession
      frontend.py  social.py  square.py  commerce.py  quests.py  dungeon.py
    network/messages.py          one dataclass per server->client message
    entities/character.py        Character + lobby/world-detail encodings
    entities/items.py            Item (0x00A53F50), Bag (0x00A1EC30)
    missions/quests.py           ActiveQuest (2007 map 0x00A3E450)
    game_data/client_dict.py     readers for the client's Data/Dict tables
tests/                           headless end-to-end tests (no game window)
tools/                           gamectl, headless client, RE helpers
```

## Rules

- Dependencies point downward: `core` imports nothing from the package;
  `games` may use `core`; `frontend` hosts `games.session`; handlers never
  import `session` (shared helpers live next to the handlers that own them).
- New opcode: add the message dataclass to `games/network/messages.py` (with
  the client reader addresses in its docstring), then an `on_<opcode>` method
  in the matching `games/handlers/*.py` mixin, then a headless test.
- New domain: create `games/handlers/<domain>.py` with a mixin class and add it
  to `GameSession`'s bases.
- Client data (`../darkblood-client-data`) is private and never committed;
  `game_data` returns empty results when it is absent.

## Porting notes

`GameSession` mixins map to partial classes or handler classes registered by
opcode. Dataclass `encode()` methods map to serializers on message types; the
JSer helpers in `core/serialization/jser.py` are the only wire primitives the
game layer needs.
