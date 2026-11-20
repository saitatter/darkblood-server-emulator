# Client leads

Unverified observations about client `a82ae3d7…c931` that may improve the server. Addresses are x86 VAs. Verify each
against the client reader (or live) before changing a schema, then move the result to `PROTOCOL.md`.

1. **Town movement desync (ROADMAP P6).**
   - The town movement sender `0x87C0D0` passes 8 (or 2) as the limit argument of `0x966B90`, which selects a per-peer
     2000 ms throttle (`peer+0xC0 + 0x7D0`). With `-1` it sends to every ready peer on each `0x95E260` pulse
     (about 200 ms). The limit is a `MOV EDI, imm32` near `0x87C1D2`. Find when the throttle branch is taken.
   - The receiver stores the latest remote position at `peer+0x108/+0x10C` (`0x855F7E`, `0x855F88`). For errors of
     32..1024 it walks the actor there with its own path request (`0x810CA0`), which can stall behind obstacles. This
     matches the world-map click-to-move symptom.
2. **Zero-filled blocks in the 2007 details** (`Character.encode_world_details`). Constructor defaults look like: the
   24-byte block read by `0xA488F0` has bytes 0-4, 6, 7, 10-14 and 23 set to 1 and two floats 1.0 at offsets 15 and
   19 (probably play options, cf. 2216); the five-element vector after it holds five `i64 -1`. We send zeros and an
   empty vector. Try them and watch the options and slot UIs.
3. **Native GM console.** The client has a command console (`0x4EF790`: `ar ap coin itemcall lv allskill clearbag
   stressall upgrade forceupgrade attack maxatk speed ...`) that sends the `eEGS_CHEAT_*` events 2057, 2061,
   2088/2089, 2101, 2103, 2105, 2107, 2130, 2137 and 2414 when the protected GM flag at `JUser+0x58` bit 0 is set.
   5020 probably sets it from `nAuthLevel` (we send 0). Test a non-zero value, then implement the cheat handlers.
4. **Attendance calendar (CRONOS).** Opening the calendar page (vtable `0xC9D1FC`) sends 2289 and 2299 and waits for
   2291 (`UPDATE_DATA_NOT`), retrying up to 3 times; related replies are 2290, 2298 and 2300. We handle none.
5. **Room records.** The second unknown `i64` after the host id in `jRoomInfo` looks like `-1` for server-built rooms
   (we send 0); `state` is 0 in 5002. 5004 carries leader `i64`, a count-checked vector of full character structs,
   a 4-byte IP plus `u16` port and two bools.
6. **Party UIDs.** Peers are addressed with the server key 31 in bits 54-58 (`0x07C0000000000000 | char_id`), as seen
   in a live 5049. Server lookups must mask with `SQUARE_UID_MASK` (fixed for the party handlers, 2026-11-21).
7. **Notice page.** The client opens `http://www.jcrsoft.co.kr/patch_test/Pub/` (push at `0x5A9B34`, opcodes
   `HTTPNOTICE_*`) unless redirected. Serve a local page and rewrite the string in the shim.
8. **Waypoints.** The client prices a waypoint itself (`GetCost` at `0xA688E0`): `floor(baseCost[source][target] *
   levelRatio[level] + 0.5)` over a complete source/target matrix; the server must charge the same.
   `WAYPOINTCHARLAYER_*` (6 opcodes) are unimplemented.
9. **Unimplemented systems.** 9 `FISHING_*`, 44 `GUILD_*` and the `CRONOS_*` opcodes (see `OPCODE_REGISTRY.md`).
   Founding a guild alone clears the party-leader and member-count requirement bits client-side.
10. **UI text.** `Localization_ST_0.jpk` can be replaced as an archive overlay (`tools/jpk_pack.py`), which fits the
    deferred UI-text fix in ROADMAP P4. Font heights live in the JFont descriptors (stride `0x50`, constructors
    `0x411138..0x411604`). Time fields: the client's CRT local-time conversion rejects some valid years.
11. **Telemetry strings in the client.** `http://mon.changyou.com/client.html?gametype=%s&version=%s&param=%d&mac=%s&ip=
    %s&hdserial=%s` (MAC, IP, disk serial), `http://account.changyou.com/fangchenmi/submitlogin.jsp` and
    `http://darbloodzonelist.changyou.com/zonelist.asp`. Whether they are reachable in the Steam build is unknown (no
    `push` of the string address was found in code). The shim redirects IPv4 `connect()` only (no `WSAConnect`,
    `ConnectEx`, IPv6, UDP); `hook_log.txt` of the latest session shows only the redirected game and relay sockets.
