# Dark Blood Online — Native GM Console & Cheat Commands

Complete reference for the native in-game GM console (`JAppPageCheat`, `0x004EF790`), its parameters, examples, and ID catalogs.

## How to Enable & Use

1. **Enable GM Mode**: set `[server] gm_mode = 1` in `research/client/darkblood_options.ini` (enabled by default; also toggleable in `tools/launcher/launcher.py` under **Patches & Hacks -> Server Behaviour -> GM console & cheat commands**).
   - When enabled, the server sends `nAuthLevel = 1` in the `5020` welcome packet (`src/darkblood/games/handlers/frontend.py`), unlocking the client's built-in GM features.
2. **Open the GM Console or Run Commands**:
   - Press **`Left Ctrl + Left Shift + C`** in-game (`0x00451A87`: `DIK_LCONTROL` + `DIK_LSHIFT` + `DIK_C`) to toggle the visual `Page_Cheat` console window (`eAP_Cheat = 0x37`).
   - Or run any command below directly from normal chat (`Enter`) using the **`%`** prefix (e.g. `%lv 20`, `%ar 100000`, `%itemcall IbagU160 1`; `0x00547574` -> `0x00547B38`).
3. **Client-side vs Server-backed**: client-side commands (e.g. `notdie`, `maxatk`, `speed`, `freecamera`, `moncall`, `dunclear`) take effect immediately in the client; server-backed commands send `eEGS_CHEAT_*` / `eERC_CHEAT_*` opcodes handled by `src/darkblood/games/handlers/gm.py`.

## ID Reference Catalogs

Regenerated from extracted client data via `python tools/codegen/gen_gm_reference.py`:

| Catalog | Contents | Used By Commands |
| :--- | :--- | :--- |
| [Item IDs (Bags, Consumables, Cash, Boxes, Avatars, Materials & Misc)](gm_ids/items.md) | 4,534 items (incl. 11 inventory bags, 53 crafting materials) | `itemcall`, `itemdrop` |
| [Equipment Item IDs (Lv 1–57)](gm_ids/items_equipment.md) | Weapons, armor & accessories by level tier | `itemcall`, `itemdrop` |
| [Monster IDs](gm_ids/monsters.md) | 3,749 monsters with level & grade | `moncall`, `summon`, `aiatk`, `aifool`, `aicaution`, `ainormal`, `questdropinfo`, `buff`, `passivebuff` |
| [Skill IDs](gm_ids/skills.md) | 509 skills with numeric `NameIndex` | `skill`, `petevolution` |
| [Quest IDs](gm_ids/quests.md) | All Act 1–4, Promotion & Event quests | `questenable`, `missionclear` |
| [Buff & Effect IDs](gm_ids/buffs.md) | Buff and status effect IDs | `buff`, `passivebuff` |
| [NPC IDs](gm_ids/npcs.md) | Town & dungeon NPCs | `questnpc` |
| [Mount & Pet IDs](gm_ids/mounts_and_pets.md) | 27 mounts (`ridecall*`) & pets | `riding` |

## GM Keyboard & Mouse Shortcuts

Active whenever GM Mode (`nAuthLevel >= 1`) is enabled:

- **`Left Ctrl + Left Shift + C`**: Toggle GM Console (`Page_Cheat`).
- **`Ctrl + E`**: Open Event Scene Viewer.
- **`Ctrl + Alt + Left Click` on World Map (`M`)**: Teleport directly to clicked location.
- **`Ctrl + Click` on Random Box**: Skip opening animation.
- **`Ctrl + Click` on Reinforce button**: Skip reinforcement animation.
- **`Alt + Click` on Reinforce button**: 100% reinforcement success rate.

---

## Native GM Console Commands (123 commands)

> **Parameter notation**: `<required>` = required argument, `[optional]` = optional argument. Separate arguments with spaces (e.g. `%itemcall IbagU160 1`).

### Character, Stats & Economy

| Command | Description | Parameters | Example |
| :--- | :--- | :--- | :--- |
| `lv` | Change character level | `<level>` (`1`–`60`) | `%lv 20` |
| `ar` | Add Ar (gold) | `<amount>` | `%ar 500000` |
| `ap` | Add Ability Points (SP/AP) | `<amount>` | `%ap 50` |
| `coin` | Add rebirth coins | `<count>` | `%coin 10` |
| `cash` | Charge cash balance | — | `%cash` |
| `stress` | Set fatigue/stress values | `<daily> [pcbang] [weekly]` (`0`–`330`) | `%stress 0` |
| `attack` | Override physical/magic attack | `<value \| off>` | `%attack 9999` / `%attack off` |
| `defence` | Override physical defense | `<value>` | `%defence 5000` |
| `mdefence` | Override magical defense | `<value>` | `%mdefence 5000` |
| `critical` | Override critical chance | `<0..100>` | `%critical 100` |
| `speed` | Change movement speed multiplier | `<rate>` (e.g. `1.5`, `2.0`) | `%speed 2.0` |
| `atkspeed` | Change attack speed | `[rate]` | `%atkspeed 2.0` |
| `notdie` | Enable god mode (cannot die) | — | `%notdie` |
| `candie` | Disable god mode | — | `%candie` |
| `maxatk` | Enable max attack damage | — | `%maxatk` |
| `notmaxatk` | Reset max attack damage | — | `%notmaxatk` |
| `maxhpmp` | Restore HP and MP to 100% | — | `%maxhpmp` |
| `halfhpmp` | Set HP and MP to 50% | — | `%halfhpmp` |
| `die` | Suicide (kill own character) | — | `%die` |
| `burst` | Set burst gauge value | `<value>` | `%burst 100` |
| `transform` | Toggle transformation state | `<on \| off>` | `%transform on` |
| `chakra` | Create chakra | `<chakra_id>` (`0`–`3`) | `%chakra 0` |
| `enemy` | Switch to opposing team | — | `%enemy` |
| `friend` | Switch to ally team | — | `%friend` |
| `statcheckon` | Enable server stat check | — | `%statcheckon` |
| `statcheckoff` | Disable server stat check | — | `%statcheckoff` |

### Items, Inventory & Storage

| Command | Description | Parameters | Example / ID Catalog |
| :--- | :--- | :--- | :--- |
| `itemcall` | Spawn item directly into inventory | `<item_id> [count=1] [expire_min]` | `%itemcall IbagU160 1` — [Items](gm_ids/items.md) · [Equipment](gm_ids/items_equipment.md) |
| `itemdrop` | Drop item on the ground | `<item_id> [count=1]` | `%itemdrop Ihppa0000 5` — [Items](gm_ids/items.md) · [Equipment](gm_ids/items_equipment.md) |
| `clearbag` | Empty entire inventory | — | `%clearbag` |
| `allpick` | Pick up all dropped items on the floor | — | `%allpick` |
| `upgrade` | Set reinforce level of equipped weapon | `<level>` | `%upgrade 12` |
| `forceupgrade` | Force reinforce equipped weapon or armor | `<weapon \| cloth> <level>` (`1+`) | `%forceupgrade weapon 10` |
| `quality` | Adjust quality of item in slot 0 of basic bag | `<quality_value>` | `%quality 100` |
| `durability` | Set durability of all worn equipment | `<value>` | `%durability 100` |
| `incdepot` | Expand storage (depot) by 20 slots | — | `%incdepot` |
| `sharedepot` | Enable shared account storage | `<days>` | `%sharedepot 30` |
| `alldrop` | Force monsters to drop 1 item per drop group | — | `%alldrop` |
| `forcedrop` | Run drop logic for all monsters (incl. spawned) | — | `%forcedrop` |
| `viewdrop` | Log monster drop probabilities | — | `%viewdrop` |
| `mapdrop` | Set treasure map drop difficulty | `<easy \| hard>` | `%mapdrop hard` |

### Skills & Buffs

| Command | Description | Parameters | Example / ID Catalog |
| :--- | :--- | :--- | :--- |
| `allskill` | Learn all skills at min or max level | `<max \| min>` | `%allskill max` |
| `skill` | Set a specific skill's level | `<skill_number> <level>` | `%skill 5 10` — [Skill IDs](gm_ids/skills.md) |
| `skillinit` | Reset skill tree and refund AP | — | `%skillinit` |
| `infiniteskill` | Ignore skill cooldowns | — | `%infiniteskill` |
| `finiteskill` | Re-enable skill cooldowns | — | `%finiteskill` |
| `buff` | Apply active buff to self or monster | `<buff_id> [monster_id]` | `%buff 306A001` — [Buff IDs](gm_ids/buffs.md) · [Monsters](gm_ids/monsters.md) |
| `passivebuff` | Apply passive buff to self or monster | `<buff_id> [monster_id]` | `%passivebuff 45B111` — [Buff IDs](gm_ids/buffs.md) · [Monsters](gm_ids/monsters.md) |
| `proficiency` | Set living/gathering proficiency EXP | `<exp_index> <value>` | `%proficiency 0 1000` |
| `proficiencyinit` | Reset living/gathering proficiency EXP | `<exp_index>` | `%proficiencyinit 0` |
| `partychaintest` | Allow solo testing of party chain skills | `<on \| off>` | `%partychaintest on` |

### Dungeons, Monsters & Combat

| Command | Description | Parameters | Example / ID Catalog |
| :--- | :--- | :--- | :--- |
| `moncall` | Spawn monsters in current room | `<monster_id> [count=1]` | `%moncall 1npi01n0 3` — [Monster IDs](gm_ids/monsters.md) |
| `summon` | Summon a monster | `<monster_id>` | `%summon 1npi01n0` — [Monster IDs](gm_ids/monsters.md) |
| `aiatk` | Lock monster AI to a specific attack index | `<monster_id> <attack_num>` | [Monster IDs](gm_ids/monsters.md) |
| `aifool` | Disable monster AI actions | `<monster_id>` | [Monster IDs](gm_ids/monsters.md) |
| `aicaution` | Restrict monster AI to boundary only | `<monster_id>` | [Monster IDs](gm_ids/monsters.md) |
| `ainormal` | Reset monster AI to normal | `<monster_id>` | [Monster IDs](gm_ids/monsters.md) |
| `aipainatk` | Force monster counter-attack after N hits | `<hit_count>` | `%aipainatk 3` |
| `notdiemon` | Make monster(s) unkillable | `[monster_num]` | `%notdiemon` |
| `candiemon` | Make monster(s) killable again | `[monster_num]` | `%candiemon` |
| `dunclear` | Instant dungeon clear | — | `%dunclear` |
| `layerclear` | Instant current room/layer clear | — | `%layerclear` |
| `clear` | Kill all monsters on screen | — | `%clear` |
| `dungeonmaster` | Unlock all dungeons up to Unique difficulty | — | `%dungeonmaster` |
| `dungeonenterinit` | Reset daily instance entry counts | — | `%dungeonenterinit` |
| `ignorewarflag` | Ignore battle/war flags | — | `%ignorewarflag` |
| `notignorewarflag` | Re-enable battle/war flags | — | `%notignorewarflag` |
| `warflagcheckon` | Enable server war flag check | — | `%warflagcheckon` |
| `warflagcheckoff` | Disable server war flag check | — | `%warflagcheckoff` |
| `minimapclear` | Reveal full dungeon minimap (Second Sight) | — | `%minimapclear` |
| `minimapnotclear` | Hide unvisited minimap rooms | — | `%minimapnotclear` |
| `showscore` | Toggle dungeon score display | — | `%showscore` |

### Quests

| Command | Description | Parameters | Example / ID Catalog |
| :--- | :--- | :--- | :--- |
| `questenable` | Check availability of a quest | `<quest_id \| subtitle>` | `%questenable Q0001S01` — [Quest IDs](gm_ids/quests.md) |
| `questinfo` | Show details of current quest | — | `%questinfo` |
| `questhistory` | List completed quest history | — | `%questhistory` |
| `questnpc` | List quests offered by an NPC | `<npc_id>` | `%questnpc 0rst01n0` — [NPC IDs](gm_ids/npcs.md) |
| `questcancel` | Reset quest completion history | — | `%questcancel` |
| `questclear` | Force-complete active quest | — | `%questclear` |
| `dquestclear` | Reset daily quests | — | `%dquestclear` |
| `questlist` | Output all registered quests | — | `%questlist` |
| `queststart` | Activate selected quest | — | `%queststart` |
| `questdropinfo` | View quest drop table for a monster | `<monster_id>` | `%questdropinfo 1npi01n0` — [Monster IDs](gm_ids/monsters.md) |
| `missionclear` | Force-complete a quest mission objective | `<quest_id> <mission_idx>` (`0`-based) | `%missionclear Q0001S01 0` — [Quest IDs](gm_ids/quests.md) |

### Mounts, Pets & Social / Guild / Arena

| Command | Description | Parameters | Example / ID Catalog |
| :--- | :--- | :--- | :--- |
| `riding` | Test mount / dismount | `<mount_id \| off>` | `%riding ridecall10` / `%riding off` — [Mount IDs](gm_ids/mounts_and_pets.md) |
| `petlv` | Change active pet level | `[level]` | `%petlv 20` |
| `petsatiety` | Change active pet energy/satiety | `<satiety> [cash_flag]` | `%petsatiety 100 0` |
| `petevolution` | Evolve active pet | `<evolution_idx> [skill_idx]` | `%petevolution 1 0` — [Skill IDs](gm_ids/skills.md) |
| `createguild` | Create a guild | `<guild_name>` | `%createguild MyGuild` |
| `guildlv` | Change guild level | `<1..7>` | `%guildlv 7` |
| `guildpoint` | Add/set guild points | `<points>` | `%guildpoint 10000` |
| `falloutstart` | Start guild dissolution (master only) | — | `%falloutstart` |
| `falloutend` | Force-finish guild dissolution | — | `%falloutend` |
| `dismissalend` | Force-finish guild resignation | — | `%dismissalend` |
| `guildskillinit` | Reset all learned guild skills | — | `%guildskillinit` |
| `arenatime` | Adjust duel/arena timer | `<seconds>` | `%arenatime 60` |
| `arenagrade` | Set arena level and EXP percent | `<level> <exp_percent>` | `%arenagrade 10 50` |
| `arenapoint` | Add arena/duel points | `<points>` | `%arenapoint 5000` |
| `usercall` | Summon another player (town only) | `<char_name>` | `%usercall Player2` |
| `movetouser` | Teleport to another player (town only) | `<char_name>` | `%movetouser Player2` |
| `kick` | Kick a player | `<char_name>` | `%kick Player2` |
| `bombmail` | Send multiple test mails | `<char_name> <count>` | `%bombmail Player2 5` |
| `pstoretime` | Extend personal store duration | — | `%pstoretime` |
| `pstoreinit` | Reset personal store timer | — | `%pstoreinit` |

### World, Camera, Visuals & Diagnostics

| Command | Description | Parameters | Example |
| :--- | :--- | :--- | :--- |
| `move` | Teleport to doodad/coordinates | `<doodad_id> <x> <y>` | `%move 0 100 100` |
| `notice` | Broadcast chat window notice | `<message>` | `%notice Server restarting` |
| `mainnotice` | Broadcast top-screen banner notice | `<message>` | `%mainnotice Welcome!` |
| `freecamera` | Toggle free camera | `<on \| off>` | `%freecamera on` |
| `showme` | Make player visible to others | — | `%showme` |
| `hideme` | Hide player from others | — | `%hideme` |
| `champ` | Change head/champion effect | `<slot_id> <head_group_id> <effect_idx>` | `%champ 0 1 1` |
| `mesheffect` | Attach mesh visual effect | `<effect_id> <bone>` | — |
| `evs` | Play an event cutscene file | `<file_path>` | — |
| `evsview` | Enable event scenes | — | `%evsview` |
| `notevsview` | Disable event scenes | — | `%notevsview` |
| `actshow` | Play Act start or completion cutscene | `<start \| complete>` | `%actshow start` |
| `credit` | Play credits for an Act | `<act_num>` (`1+`) | `%credit 1` |
| `pcroomui` | Toggle virtual PC Bang UI | — | `%pcroomui` |
| `guideinit` | Reset beginner guide state | — | `%guideinit` |
| `achievedump` | Toggle/clear achievement performance dump | `<toggle \| clear>` | `%achievedump toggle` |
| `spiritlog` | Show spirit weapon calculation in chat | — | `%spiritlog` |
| `reverse` | Reverse character rendering | `<on \| off>` | `%reverse on` |
| `sysinfo` | Display system info overlay | — | `%sysinfo` |
| `fps` | Display FPS overlay | — | `%fps` |
| `buildtime` | Display client build timestamp | — | `%buildtime` |
