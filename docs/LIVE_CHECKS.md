# Pending live checks

Single list of behaviour that is implemented and headless-tested but **not yet
confirmed in the real client**. Run the headless suite first
(`python -m unittest discover -s tests -v`); launch the client only for these
checks. Drive it with `tools/automation/gamectl.py` / `tools/automation/multibox.py`
(or the `darkblood` MCP server).

Before a multibox session: keep both game windows unobstructed. `gamectl` clicks
move the real cursor, so a window covered by another application receives clicks
meant for the game (a 2026-11-26 attempt was stopped for this reason).

When a check passes, move it to `docs/STATUS.md` with the date and remove it here.
When it fails, note what the client did and keep it here.

## Dungeon rooms and party runs (two clients)

| # | Check | Steps | Expected | Since |
|---|---|---|---|---|
| D1 | Manual host handover `5021 -> 5022` | Two clients in the same party room; the host uses the room's change-host action on the other member. | Both windows show the new host; the new host can change room settings and start; the old host cannot. No error popup. | 2026-11-26 |
| D2 | Automatic host promotion on leave (`5022`) | Host leaves the room (`5005`). | The remaining member becomes host without an error popup. | 2026-11-21 |
| D3 | Party `5014` loading screen | Host starts a run with two members. | Both clients play `Loading_Party.mp3` (solo runs keep `Loading_Single.mp3`). | 2026-11-26 |
| D4 | Party `5014` peer skills | During the party run, each player uses a skill. | The peer's skill animations/effects render (peer skill records applied by `0x0095A6A0`). No crash. | 2026-11-26 |
| D5 | Party `5014` shared seed | Party run with floor drops; both players pick items up. | No desync or error on pickup results (`5050`); seed is shared via `AppPage(9)+0xB8`. | 2026-11-26 |
| D6 | Party row stress gauge (`5061`/`5048`/`2025`) | Give one character stress (dungeon runs or GM `2130`); the other opens Find party → room row / join request / Find user. | The stress gauge shows `stress/max`; at max the row is grey with `UI_2356`. | 2026-11-26 |
| D7 | `5051` invitation dialog | Host invites a town player. | Invitation dialog shows inviter name, class, level and stress; Accept joins the room. | — |
| D8 | Shared dungeon run end to end | Two clients enter, kill, finish (`5017 -> 5018`). | Both see the result screen with an entry per member; card rewards claimable once per member. | 2026-11-21 |

## Dungeon progress and rewards (one client)

| # | Check | Steps | Expected | Since |
|---|---|---|---|---|
| R1 | Daily clear count `2443` | Clear `Act4_G2_R13` (entry item `IticR5040` x2). | No error; the gate/dungeon UI shows the clear count if the client displays it. Count resets the next day. | 2026-11-26 |
| R2 | Full-inventory chest mail (`5091` result 294) | Fill the inventory, clear a dungeon and open a chest. Try claiming the attachment, then free a slot and retry. | The chest opens, `UI_3329` appears, and mail arrives (`2227`). The attachment stays in the inbox while the bag is full and moves into the freed slot on retry. | 2026-11-26 |
| R3 | Pet EXP on kills (`5324`/`5323`) | Summon a pet and kill monsters. | Pet EXP bar rises; pet level-up notice at the threshold. | 2026-11-26 |
| R4 | 11-20/21 work | Gate history and quest variants, EXP bar, town AR, chest names, counter achievements, revive layer, floor gold, stress, `6012` View Info, `2134` memo. | Each behaves as described in `docs/STATUS.md` (2026-11-20/21 sections). | 2026-11-21 |
| R5 | Explore join (`5359`) | Enter the Forest of Oblivion. | Page opens; check whether `total_max_stress = 0` is acceptable or the stress UI needs a value. | 2026-11-26 |

## Other domains

| # | Check | Expected | Since |
|---|---|---|---|
| O1 | Random-box success notice (`2196`) | Opening a random box shows the success notice. | — |
| O2 | Subclass promotion (`2283`) learned-skill map | Promotion grants the expected auto-learned skills (map currently empty). | 2026-11-24 |
| O3 | Life Skills screen (issue #15 item 5) | Screen opens with the expected data. | 2026-11-24 |
| O4 | Dual Skill item (issue #15 item 6) | Using the item enables the dual skill. | 2026-11-24 |
| O5 | Mount summoning (`ridecall`) and pet items (`PetCall`) | Mount appears; pet summons. | — |
| O6 | Party retention across reconnect | Reconnecting keeps the party; the old connection's cleanup does not remove the new session. | 2026-11-18 |
| O7 | Town revive / layer / floor gold / relay leave notices | As listed in `docs/STATUS.md` (multiplayer section). | — |
| O8 | Commerce and post (P7) | Trade, mail, stalls, broker, depot flows work end to end. | — |

## Wire fixes and newly filled fields (2026-11-26)

| # | Check | Expected |
|---|---|---|
| W1 | Login (`2007`) with completed achievements | The achievement window shows them right after login, before any `2328` request. |
| W2 | Pet evolution (`2485`) | AR display shows the player's real AR afterwards (the field was sent as a pet UID before). |
| W3 | Tame monster insert/delete (`2349`/`2351`) | The tamed list window shows the stored list. The two-i32 entry split is a guess: check the monster names/slots. |
| W4 | Personal shop open/buy (`2341`/`5243`) | Shop title shows correctly; the shop lists items and expiry (layout corrected: address, `vector<u32>`, trailing 4 bytes). |
| W5 | Pet feeding (`2481`) | Satiety updates; no inventory refresh issue (the vector is now `vector<Item>`, sent empty). |
| W6 | Item link / remote item info (`6028 -> 6029`) | Clicking another player's item shows its tooltip (full Item record); an unknown item shows `JERI_INVEN_01`. Confirms that `nItemInfoID` is the item UID's low 32 bits (assumption). |
| W7 | Gold goblin kill (`5366`) | Drop position uses the float `fX`/`fY` (earlier i16 layout was 4 bytes short). |
| W8 | Trade / teaching requests (`5070`/`5352`) | The dialog shows the real target name, level and class. |
| W9 | Arena relay change (`5135`) | 6-byte address (was 24 bytes); no read error. |
| W10 | Duel start (`5098`) | Duel begins without a read error; both players' skills/levels are applied (layout was missing seven fields). |
| W11 | Arena room join (`5146`) and invite list (`2309`) | Join succeeds (relay address now sent); the invite list shows candidates and the page number. |
| W12 | League ranking (`2551`/`2472`) | Ranking pages and the season start date display. |

## Basic client checklist (from ROADMAP)

- [ ] Store: buying decrements gold and adds the bag icon; selling removes it.
- [ ] Equipment window shows worn gear; dragging a weapon to a slot updates the mesh.
- [ ] Skill window: spending SP raises the skill and enables it on the hotbar.
- [ ] Dungeon entry loads the map and spawns monsters with health bars.
- [ ] Combat: hit sound, floating damage numbers, death animation.
- [ ] Level-up fanfare when the EXP bar fills.
- [ ] Card reward UI after a clear; return to town by portal.
