# Dark Blood Online — GM Console & Cheat Commands

Complete reference for the native in-game GM console (`JAppPageCheat`, `0x004EF790`) and server-side chat commands.

## How to Enable & Use

There are **two separate command systems**:

1. **Native GM Console (`JAppPageCheat` — built into the original `DarkBlood.exe` client)**:
   - **Enable**: set `[server] gm_mode = 1` in `research/client/darkblood_options.ini` (enabled by default; also toggleable in `tools/launcher.py` under **Patches & Hacks -> Server Behaviour -> GM console & cheat commands**). When enabled, the server sends `nAuthLevel = 1` in the `5020` welcome packet (`src/darkblood/games/handlers/frontend.py`), unlocking the client's built-in GM features.
   - **How to open / run**:
     - Press **`Left Ctrl + Left Shift + C`** in-game (`0x00451A87`: `DIK_LCONTROL` + `DIK_LSHIFT` + `DIK_C`) to toggle the visual `Page_Cheat` console window.
     - Or run any native GM command directly from normal chat using the **`%`** prefix (e.g. `%lv 20`, `%notdie`, `%maxatk`, `%dunclear`; `0x00547574` -> `0x00547B38`).
   - **What it does**: supports all **123 original client commands** below — including **client-side** cheats that only the game binary can perform (`notdie`, `maxatk`, `speed`, `freecamera`, `moncall`, `dunclear`) and **server-backed** commands that send `eEGS_CHEAT_*` / `eERC_CHEAT_*` opcodes to `src/darkblood/games/handlers/gm.py`.

2. **Server Chat Slash Commands (emulator convenience shortcuts — not part of the original client)**:
   - Typed directly in normal chat (`Enter`) with a **`/`** prefix — intercepted on the server (`5040 ChatReq`), work even when `gm_mode = 0`, and are meant as quick shortcuts for common testing actions:
     - `/gold <amount>` — Add AR (gold) to the current character.
     - `/levelup [levels]` — Level up by N levels (default 1) and broadcast `5087 LevelUpNot`.
     - `/sp <amount>` — Add Skill Points (AP/SP).
     - `/item <code> [count]` — Grant an item by code (e.g. `/item Iwpna0001 1`).
     - `/bags` — Expand all bags to 20 slots.

## Native GM Console Commands (123 commands)

| Command | Description | Parameters / Usage |
| :--- | :--- | :--- |
| `lv` | Change Level | [Level Value] |
| `attack` | Change Attack | [Attack Level] or [Off] |
| `speed` | Change Movement Speed | [Speed Rate] |
| `atkspeed` | Change Attack Speed | — |
| `notdie` | Will not die | — |
| `candie` | May die | — |
| `maxatk` | Max Attack | — |
| `notmaxatk` | Reset Attack Damage | — |
| `enemy` | Opposing Team | — |
| `friend` | Ally Team | — |
| `die` | Suicide | — |
| `maxhpmp` | Recover HP/MP | — |
| `halfhpmp` | Half HP/MP | — |
| `defence` | Change Physical Defense | [Defense Value] |
| `mdefence` | Change Magical Defense | [Defense Value] |
| `stress` | Change stress value | [Daily] [PC Bang] [Weekly] |
| `ar` | Earn Ar | [Ar Value] |
| `coin` | Earn Coin | [Number of Coins] |
| `moncall` | Create monsters | [Monster Name] or [Monster Code], [Number] |
| `aiatk` | Fix AI Attack | [Monster Name], [Attack Number] |
| `aifool` | AI action disabled | [Monster Name] |
| `aicaution` | AI boundary only | [Monster Name] |
| `ainormal` | AI Initialization | [Monster Name] |
| `notdiemon` | Monster will not die | [Monster Number] |
| `candiemon` | Monster may die | [Monster Number] |
| `summon` | Monster summoned | [Monster Code] |
| `dunclear` | Dungeon Clear | — |
| `layerclear` | Layer Clear | — |
| `clear` | Screen Clear | — |
| `minimapclear` | Second Sight | — |
| `minimapnotclear` | Second Sight cancelled | — |
| `ignorewarflag` | Battle Flag ignored | — |
| `notignorewarflag` | Battle Flag cannot be ignored | — |
| `alldrop` | Dropped by monsters - 1 is always dropped for each group | — |
| `viewdrop` | Monster's probability of drop is recorded in logs | — |
| `notevsview` | Event scene OFF | — |
| `evsview` | Event scene ON | — |
| `evs` | Event scene PLAY | [File Directory] |
| `clearbag` | Empty inventory | — |
| `allpick` | Pickup all items | — |
| `itemdrop` | Create item | [Item Name], [Number] |
| `itemcall` | [Item Name], [Number], [Time (Minute)] | — |
| `upgrade` | Change reinforce level of currently equipped weapon | [Reinforce Level] |
| `quality` | Readjust the quality of item on the 1st slot of basic bag | [Quality Value to Adjust] |
| `ap` | Earn AP | [AP Value] |
| `allskill` | Learn all skills | [max] or [min] |
| `skill` | Change skill level | [Skill Number], [Skill Level] |
| `infiniteskill` | Skill Cool Down ignored | — |
| `finiteskill` | Skill Cool Down applied | — |
| `notice` | Chat window notice | [Message] |
| `mainnotice` | Main notice | [Message] |
| `questenable` | Check availability of quest | Quest ID or subtitle |
| `questinfo` | Check details of quest | — |
| `questhistory` | View history of completed quest | — |
| `questnpc` | Check list of quests given by each NPC | NPC ID |
| `questcancel` | Initialize quest completion info | — |
| `questclear` | Force-complete current quest | — |
| `questlist` | Output list of all registered quests | — |
| `queststart` | Selected quest is activated | — |
| `questdropinfo` | View quest drop info of each monster | [Monster Name] or [Monster Code] |
| `showscore` | Score on/off in dungeon | — |
| `freecamera` | Camera Manipulation | [on or off] |
| `createguild` | Create guild | [Guild Name] |
| `guildlv` | Changes guild level | [1-7] |
| `guildpoint` | Changes guild points | [Point] |
| `falloutstart` | Starts disorganizing guild if master | — |
| `falloutend` | Force-disorganizes guild if master | — |
| `dismissalend` | Force-completes resignation request if master | — |
| `guildskillinit` | Initialize all guild skills learned | — |
| `incdepot` | Expands storage by 20 slots | — |
| `sharedepot` | Shares storage of all characters in the same account | [Value (days)] |
| `move` | Teleport | [Dodot ID X Coordinate, Y Coordinate] |
| `actshow` | View Act Start/Completion Scene | [start or complete] |
| `pcroomui` | Virtual PC Bang | — |
| `showme` | Player is visible to other users | — |
| `hideme` | Player is not visible to other users | — |
| `buff` | Buff applied | [Buff ID], [Monster Name] or [Blank (Player)] |
| `passivebuff` | Apply passive buff | [Buff ID], [Monster Name] or [Blank (Player)] |
| `buildtime` | View build time | — |
| `spiritlog` | Shows calculation on chat window | CHEATDESC_100 / Open event scene viewer / Ctrl+E / Teleport in world map / Ctrl+Alt+mouse click on world map (M) |
| `durability` | [Durability Value] | Changes durability of items worn |
| `mesheffect` | Creates mesh effect | [EFFECTID],[BONE] |
| `proficiency` | Controls experience value | [Experience Index], [Value] |
| `usercall` | Summons selected user (users in square only) | [Character Name] |
| `movetouser` | Moves player to the position of selected user (users in square only) | — |
| `critical` | Critical is applied to player's character | [0~100] |
| `partychaintest` | Used to test party chain skill; triggered by oneself | [on or off] |
| `aipainatk` | Attempts attack when attacked | [Number of Hit] |
| `kick` | [Kick] | Skip scene when opening random box / Press Ctrl and click random box / Skip scene when reinforcing / Press Ctrl and click Reinforce button / Reinforcing succeeds at 100% rate / Press Alt and click Reinforce button |
| `skillinit` | Initialize skill tree | — |
| `proficiencyinit` | Initializes living skill experience | [Experience Index] |
| `burst` | Control bust value | [Value] |
| `transform` | Transform | [on or off] |
| `arenatime` | Adjust duel time | [time] |
| `arenagrade` | Control arena level | [lv][exp-percent] |
| `arenapoint` | Acquire duel point | [Point Value] |
| `reverse` | Reverse character rendering | [on or off] |
| `sysinfo` | System Info | — |
| `fps` | FPS  Info | — |
| `credit` | View credit for each Act | 1 ~ |
| `guideinit` | Initialize guide | — |
| `dungeonenterinit` | Reset entry count in instances | — |
| `pstoretime` | Extends time for using a private store | — |
| `pstoreinit` | Reset use time of your private store | — |
| `forcedrop` | All monsters perform item drop logic (increasing monsters called by cheat) | — |
| `bombmail` | The cheat for sending multiple mails | [Character Name], [Number of Mails to Send] |
| `champ` | Change head effect | [Slot ID] [Head Group ID] [Effect Index] |
| `cash` | Charging cash | — |
| `statcheckon` | Activating server and stat check | — |
| `statcheckoff` | Deactivating server and stat check | — |
| `riding` | Riding test | [Mount ID or off] |
| `missionclear` | Force-complete current mission | [Quest ID or Subtitle], [Mission Index (from 0)] |
| `forceupgrade` | Reinforce equipped item to a designated level | [Weapon or Cloth], [Reinforcing (from 1)] |
| `warflagcheckon` | Activating server and battle flag check | — |
| `warflagcheckoff` | Deactivating server and battle flag check | — |
| `dungeonmaster` | Unlocking all dungeons' unique level | — |
| `dquestclear` | Initialize daily quest | — |
| `achievedump` | Related to performance dump function | [toggle / clear] |
| `petlv` | Changes the level of the Pet you are training | — |
| `petsatiety` | Changes the Energy of the Pet you are training | [Satisfaction Level], [Cash Setting (0 or etc)] |
| `petevolution` | Evolution of Pet | [Evolution Index], [Skill Index] |
| `chakra` | Chakra Creation | [Chakra ID (0 - 3)] |
| `mapdrop` | Difficulty of treasure map to drop [easy / hard] | — |
