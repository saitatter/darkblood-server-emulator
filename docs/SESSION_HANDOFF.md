# Session handoff — 2026-11-17 (compressed)

Compressed on 2026-11-17 at the user's request. Earlier entries (2026-11-16 and the first part of 2026-11-17,
~800 lines) are in git history: `git log -p -- docs/SESSION_HANDOFF.md`. Evidence that still matters is
summarized below; detailed protocol notes live in `docs/PROTOCOL.md` and `docs/STATUS.md`.

## Read this first

- Goal: a reproducible offline server for the supplied Dark Blood client. Docs in English; talk to the user in Romanian.
- Pull/rebase `origin main` regularly, run `python -m unittest discover -s tests`, push verified work with
  Conventional Commits. Update this handoff and `ROADMAP.md` before ending a session.
- The user plays live while we work. Restarting `run_server.py` drops their client (the reconnect shim brings it back
  to the server list); say so in the same message or ask first. Do not drive the game UI while the user plays.
- Live packet watch: `logs/wire.jsonl` (server) and `research/client/hook_log.txt` (shim). A small tail script that
  prints client opcodes, server notes, `unhandled-event` and requests without a reply was used all session.

## Wire rules learned the hard way (check every new encoder against these)

1. **Tags outside 0x0F..0x1A are never on the wire.** `0x00B35010(tag)` consumes a byte only for 0x0F..0x1A.
   Struct tag `0x1E` (and `0x0D`) must not be emitted. Fixed so far: 2075, ActiveQuest/2074/2077, 5086, 5087,
   5064/5068 drop structs. **About 15 encoders still emit a literal `0x1e`** (arena, NPC store 2066/2072,
   events, guild, social 2?? summaries) — audit each against its reader.
2. **Most client requests start with the `ffffff7f` prefix** (`0x00408C60(op, -1, -1)` header). Decoders must
   skip it: fixed for 2038, 2040, 2042, 5065 (u32 drop uid), 5093. Drag 2036 has no prefix (live).
3. **The client's own UID is details `+0x1C`** (reader `0x00A52630`, copied by `0x0095A150` to player `+0x10`,
   returned by `0x00946570`). It was sent as 0 while everything else used the character id; now it is the id
   (edff688). Owner checks, user lookups and the revive page all depend on it.
4. **Incremental item records** (2037/2039/2043/rewards/shop) use owner `-1` (`items.UPDATE_OWNER`): per-item apply
   `0x008354D0` drops records whose owner differs from the inventory owner. **Empty cells** are uid -1 / code -1
   (outer ctor `0x004AAB20`); uid 0 / code 0 left ghost copies in the bag. Swaps send the vacating item first.
5. **Item Quality (+4) must be >= 0.** 0xFFFF left the stat tier unset and `0x009D7A50` returned -1.0 per item stat
   (Defense -44, 2 damage). Now 0 (live: Attack 28 -> 87.9, Defense -44 -> 8.4). UpgStep stays 0xFFFF.
6. Max durability is an i16 on the client: send `int(max)` (helmet 18.525 showed 19/18).
7. Many responses are waited for page-locally (not in `handler_map.txt`); check the page's `vf20` dispatcher
   (e.g. Cashshop `0x004DCCC0`, MonsterCard `0x0060B500`) before assuming a reply is ignored.

## Verified live on 2026-11-17

- Tutorial: hog kills (2353) -> 2075 progress, quest completion and exit; counters reset on each 2346.
- Reconnect after a server restart: shim resets the local UID to -1 (b104ead) so channel select sends 2008.
- Equip / unequip / weapon swap / drag display immediately; accessory slots Aclo 7, Anec 8, Aear 9-10, Arin 11-12.
- Death (5093/5094 echoes the request UID) and revive with a rebirth coin; no more crash at `0x0055BF71`.
- Item delete (2040) and use (2038); Steam cash-shop purchases (2712 -> unsolicited 2037 + 2714, free offline).
- Stats after the Quality fix (2406 reports attack/m.attack/defense/m.defense floats).

## Implemented 2026-11-17, headless only (verify live next)

- Monster EXP on 5063 from `monster.lua` (`Exp`, rounded), shared `_grant_exp` with quests (5087/5086 fixed).
- Monster drops (`games/loot.py`): `itemlooting.lua` LoadMonLooting per dungeon (MonID entries only for that
  monster), UsuallyProb scaled by HP/AveMonHP, item from OneItemID / ItemGroup / equipment criteria
  (`<lv><grade>_<Weapon|Armor|Accessory>`, class bit from Demand1Class). 5064 announces drops at the 5063 instance
  id; 5065 pick-up -> 5068 + 2037. Map `Act1_G1_A10` falls back to table `Act1_G1_A1` (assumption).
  Simulation: ~4.4% drop per normal hog, ~4.3 items per `1fpi03U0`.
- Cash packages (Type 36, PACKAGEnnn -> DictItem:LoadPackage) and random boxes (DictRandomBox) open on use;
  bag capacity (`free_bag_slots`, bag `b29`) is enforced for opening, buying and picking up.
- 5017 finish game -> 5018 (u32, bool clear, wstring, bool, empty 0x17 map): no reward data yet.
- Empty/record-only handlers: 2242->2243, 2446->2447, 2592 (no client handler), 2509, monster cards 2601/2608/2617.
- `GameSession.current_char()` replaces 26 copied character lookups.
- The live character's bag was upgraded once to Ibaga0003 (20 slots) in `data/darkblood.db` (backup in scratchpad).

## Open items (priority order)

1. **Depot / warehouse**: not implemented. Cash items Ikee*Cash (Type 7, warehouse rental) and lSto1Cash18
   (Type 29, remote warehouse) are consumed without effect. Recover the depot container convention (bag entries in
   2007), handlers 2229/2231 (AR save/load), 2401 size increase, 2461/2462 slot extend.
2. **Crash at `0x00650DB4`** (FUN_00650D00 from `Lua_OnUseBtnDown_Inven` / `Lua_OnBtn_Drop`): `0x00938C70(-1,-1)`
   (manager `0x0054AF50`, lookup by the current UID) returned NULL. Expected to be fixed by the UID fix; retest.
3. Audit the remaining literal `0x1e` encoders (rule 1).
4. 5018 rewards (0x17 map `0x005EAAC0`), gold/AR drops (5114), upgrade probabilities in drops.
5. Mounts (`ridecall`), pets (`PetCall`), CashWG/CashAG/Zam boxes are consumed without effect.
6. 5030 layer id is parsed as i64 at +4; live body suggests u32 at +8.
7. Duplicate-prone decoders: a shared `strip_prefix()` for the ffffff7f header would remove ~30 ad-hoc checks.

## Environment notes (saita machine)

- Workspace `C:\Users\saita\Desktop\repos\darkblood-server-emulator`; client copy `research/client/`
  (Data is a junction — never delete through it). Client data dictionaries: `..\darkblood-client-data\lua_src\data\dict`.
- Shim: `client_hook\build.bat` (vcvars inside; the `vswhere` warning is harmless). Copy `client_hook\steam_api.dll`
  to `research\client\` only while the client is closed. `research/client/bp.txt` arms the INT3 tracer
  (`<VA> [max=N] [expr ...]`; output lines `[BP <VA> #n ...]` in hook_log). Reading game memory from outside is
  denied (OpenProcess error 5) — use the tracer.
- Decompile with `tools\decomp.ps1 OUT.c 0xADDR...`; `research/decompiled/*.c` is a function corpus with names.
- Editing tip: Python heredocs that contain `\x..`/`\n` escapes inside triple-quoted strings were mangled several
  times this session; prefer the Edit tool for code containing byte literals.
