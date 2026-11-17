# Dark Blood Online — Master Opcode & Wire Packet Registry

> Comprehensive registry of all recovered opcodes, client/server handler virtual addresses, wire layouts, serialization types, and observed gameplay behavior.

**Total Tracked Opcodes**: 501  
**Client Handlers Mapped**: 298  
**Server Handlers Implemented**: 140  

## Overview of Wire Protocol Rules

1. **Header Prefix `0xFFFFFFFF7F`**: Most client-to-server requests prepend `b'\xff\xff\xff\x7f'` (`0x00408C60(opcode, -1, -1)`). Decoders must call `strip_prefix()` before parsing payload fields.
2. **Tag Rules at `0x00B35010`**: Struct/primitive tags only consume wire bytes when `0x0F <= tag <= 0x1A`. Tag `0x1E` and `0x0D` return immediately without reading a byte from the wire buffer. Emitting literal `0x1E` corrupts all subsequent deserialization.
3. **Variable-Length Integers**: ProudNet scalars (width-prefixed) and JSerBuffer varints (7-bit groups with bit 7 set on terminal byte) are distinct protocols.
4. **Character & Player Ownership**: Items in active bag/inventory carry owner `-1` (`items.UPDATE_OWNER`) to be accepted by `0x008354D0`.


---

## System, Handshake & ProudNet Core (0 - 1999)

| Opcode | Hex | Enum Name | Direction | Client VA | Server Handler | Message Class / Wire Notes |
| :--- | :--- | :--- | :---: | :--- | :--- | :--- |
| **0** | `0x0000` | `eE_HEART_BIT` | **C → S** | `—` | `social.py` | Application-level keepalive heartbeat sent by client periodically. |
| **1** | `0x0001` | `eE_CLOSE_CONNECTION_NOT` | **S → C** | `0x00786F10` | — | — |
| **2** | `0x0002` | `eE_ACCEPT_NOT` | **S → C** | `0x007AE730` | — | — |

---

## Lobby, Server/Channel Selection & World Entrance (2000 - 2023)

| Opcode | Hex | Enum Name | Direction | Client VA | Server Handler | Message Class / Wire Notes |
| :--- | :--- | :--- | :---: | :--- | :--- | :--- |
| **2002** | `0x07D2` | `eEGS_KNOCK_SQUARELIST_ACK` | **S → C** | `0x00757810` | — | — |
| **2003** | `0x07D3` | `eEGS_KNOCK_SQUARELIST_NOT` | **S → C** | `0x00757840` | — | — |
| **2007** | `0x07D7` | `eEGS_SELECT_CHAR_ACK` | **S → C** | `0x007AA4B0` | — | `SelectCharacterAck` (Opcode 2007: eEGS_SELECT_CHAR_ACK response.) |
| **2009** | `0x07D9` | `eEGS_GET_CHARLIST_ACK` | **S → C** | `0x0077CFA0` | — | — |
| **2010** | `0x07DA` | `eEGS_GET_ROOMINFOLIST_REQ` | **C → S** | `—` | `dungeon.py` | eEGS_GET_ROOMINFOLIST_REQ (sender 0x7AB140) -> 2011: no open rooms. |
| **2011** | `0x07DB` | `eEGS_GET_ROOMINFOLIST_ACK` | **S → C** | `0x0077A1F0` | — | `RoomInfoListAck` (Opcode 2011: eEGS_GET_ROOMINFOLIST_ACK (JUserClient handler 0x0077A1F0).) |
| **2013** | `0x07DD` | `eEGS_CREATE_CHARACTER_ACK` | **S → C** | `0x00758070` | — | — |
| **2014** | `0x07DE` | `eEGS_DELETE_CHARACTER_REQ` | **C → S** | `—` | — | `DeleteCharacterReq` (Opcode 2014: eEGS_DELETE_CHARACTER_REQ (0x00780000.c:6618).) |
| **2015** | `0x07DF` | `eEGS_DELETE_CHARACTER_ACK` | **S → C** | `0x00758370` | — | `DeleteCharacterAck` (Opcode 2015: eEGS_DELETE_CHARACTER_ACK (On_eEGS_DELETE_CHARACTER_ACK 0x00758370).) |
| **2017** | `0x07E1` | `eEGS_ENTER_MAPTOOL_ACK` | **S → C** | `0x00757D20` | — | — |
| **2019** | `0x07E3` | `eEGS_LEAVE_MAPTOOL_ACK` | **S → C** | `0x00757EC0` | — | — |
| **2020** | `0x07E4` | `eEGS_CLOSE_CONNECTION_NOT` | **S → C** | `0x007536A0` | — | — |
| **2021** | `0x07E5` | `eEGS_SQUARELIST_REQ` | **C → S** | `—` | — | `ChannelSquare` (A channel / square entry shown in the 'Channel List' dialog (Opcode 2021/2022).) |
| **2022** | `0x07E6` | `eEGS_SQUARELIST_ACK` | **S → C** | `0x0077A550` | — | — |
| **2023** | `0x07E7` | `eEGS_STRESS_CHANGED_NOT` | **S → C** | `0x00789E00` | — | — |
| **2403** | `0x0963` | `eEGS_DB_LIST_GET_ACK` | **S → C** | `0x00775340` | — | — |

---

## Inventory, Equipment, Crafting & Depot

| Opcode | Hex | Enum Name | Direction | Client VA | Server Handler | Message Class / Wire Notes |
| :--- | :--- | :--- | :---: | :--- | :--- | :--- |
| **2024** | `0x07E8` | `eEGS_GET_INVITELIST_REQ` | **C → S** | `—` | `social.py` | `GetInviteListReq` (Opcode 2024: eEGS_GET_INVITELIST_REQ (0x007A0000.c:7840).) |
| **2025** | `0x07E9` | `eEGS_GET_INVITELIST_ACK` | **S → C** | `—` | — | `GetInviteListAck` (Opcode 2025: eEGS_GET_INVITELIST_ACK (0x006A2E10).) |
| **2026** | `0x07EA` | `eEGS_OPEN_BAG_REQ` | **C → S** | `—` | `inventory.py` | `OpenBagReq` (Opcode 2026: eEGS_OPEN_BAG_REQ (sent from 0x0082D34E).) |
| **2027** | `0x07EB` | `eEGS_OPEN_BAG_ACK` | **S → C** | `—` | — | `OpenBagAck` (Opcode 2027: eEGS_OPEN_BAG_ACK (handler 0x00557860, dispatch 0x0055883F).) |
| **2028** | `0x07EC` | `eEGS_CLOSE_BAG_REQ` | **C → S** | `—` | `inventory.py` | `CloseBagReq` (Opcode 2028: eEGS_CLOSE_BAG_REQ (0x00550000.c:1773).) |
| **2030** | `0x07EE` | `eEGS_SWITCH_BAG_REQ` | **C → S** | `—` | `inventory.py` | `SwitchBagReq` (Opcode 2030: eEGS_SWITCH_BAG_REQ (0x00550000.c:626).) |
| **2031** | `0x07EF` | `eEGS_SWITCH_BAG_ACK` | **S → C** | `—` | — | `SwitchBagAck` (Opcode 2031: eEGS_SWITCH_BAG_ACK (0x00557680).) |
| **2032** | `0x07F0` | `eEGS_CHANGE_BAG_NAME_REQ` | **C → S** | `—` | `inventory.py` | `ChangeBagNameReq` (Opcode 2032: eEGS_CHANGE_BAG_NAME_REQ.) |
| **2033** | `0x07F1` | `eEGS_CHANGE_BAG_NAME_ACK` | **S → C** | `0x007528B0` | — | `ChangeBagNameAck` (Opcode 2033: eEGS_CHANGE_BAG_NAME_ACK (On_eEGS_CHANGE_BAG_NAME_ACK 0x007528B0).) |
| **2036** | `0x07F4` | `eEGS_DRAG_ITEM_REQ` | **C → S** | `—` | `inventory.py` | `DragItemReq` (Opcode 2036: eEGS_DRAG_ITEM_REQ (JUserClient::DragItemREQ 0x00790000.c:4212).) |
| **2037** | `0x07F5` | `eEGS_DRAG_ITEM_ACK` | **S → C** | `0x0077F570` | — | `DragItemAck` (Opcode 2037: eEGS_DRAG_ITEM_ACK (On_eEGS_DRAG_ITEM_ACK 0x0077F570).) |
| **2038** | `0x07F6` | `eEGS_USE_ITEM_REQ` | **C → S** | `—` | `inventory.py` | `UseItemReq` (Opcode 2038: eEGS_USE_ITEM_REQ (0x00780000.c:8159).) |
| **2039** | `0x07F7` | `eEGS_USE_ITEM_ACK` | **S → C** | `0x0077D4C0` | — | `UseItemAck` (Opcode 2039: eEGS_USE_ITEM_ACK (On_opcode_2039 0x0077D4C0).) |
| **2040** | `0x07F8` | `eEGS_DELETE_ITEM_REQ` | **C → S** | `—` | `inventory.py` | `DeleteItemReq` (Opcode 2040: eEGS_DELETE_ITEM_REQ (0x00550000.c:769).) |
| **2041** | `0x07F9` | `eEGS_DELETE_ITEM_ACK` | **S → C** | `—` | — | `DeleteItemAck` (Opcode 2041: eEGS_DELETE_ITEM_ACK (0x00557420).) |
| **2042** | `0x07FA` | `eEGS_EQUIP_ITEM_REQ` | **C → S** | `—` | `inventory.py` | `EquipItemReq` (Opcode 2042: eEGS_EQUIP_ITEM_REQ (0x00800000.c:500).) |
| **2043** | `0x07FB` | `eEGS_EQUIP_ITEM_ACK` | **S → C** | `0x007AE940` | — | `EquipItemAck` (Opcode 2043: eEGS_EQUIP_ITEM_ACK (On_eEGS_EQUIP_ITEM_ACK 0x007AE940).) |
| **2044** | `0x07FC` | `eEGS_ASSIGN_QUICKSLOT_REQ` | **C → S** | `—` | `inventory.py` | `AssignQuickslotReq` (Opcode 2044: eEGS_ASSIGN_QUICKSLOT_REQ (writer 0x0078C2E0..: u8, u8, u32, u64).) |
| **2045** | `0x07FD` | `eEGS_ASSIGN_QUICKSLOT_ACK` | **S → C** | `0x0078C4A0` | — | `AssignQuickslotAck` (Opcode 2045: eEGS_ASSIGN_QUICKSLOT_ACK (On_eEGS_ASSIGN_QUICKSLOT_ACK 0x0078C4A0).) |
| **2046** | `0x07FE` | `eEGS_SWITCH_QUCIKSLOT_REQ` | **C → S** | `—` | `inventory.py` | `SwitchQuickslotReq` (Opcode 2046: eEGS_SWITCH_QUCIKSLOT_REQ (0x00780000.c:8591).) |
| **2047** | `0x07FF` | `eEGS_SWITCH_QUCIKSLOT_ACK` | **S → C** | `0x0078C790` | — | `SwitchQuickslotAck` (Opcode 2047: eEGS_SWITCH_QUCIKSLOT_ACK (On_eEGS_SWITCH_QUCIKSLOT_ACK 0x0078C790).) |
| **2048** | `0x0800` | `eEGS_CHANGE_BAG_PROPERTY_REQ` | **C → S** | `—` | `inventory.py` | `ChangeBagPropertyReq` (Opcode 2048: eEGS_CHANGE_BAG_PROPERTY_REQ (0x00550000.c:676).) |
| **2049** | `0x0801` | `eEGS_CHANGE_BAG_PROPERTY_ACK` | **S → C** | `0x00774040` | — | `ChangeBagPropertyAck` (Opcode 2049: eEGS_CHANGE_BAG_PROPERTY_ACK (On_eEGS_CHANGE_BAG_PROPERTY_ACK 0x00774040).) |
| **2086** | `0x0826` | `eEGS_BUY_LIFE_WATER_REQ` | **C → S** | `—` | `inventory.py` | `BuyLifeWaterReq` (Opcode 2086: eEGS_BUY_LIFE_WATER_REQ (0x00780000.c:11036).) |
| **2087** | `0x0827` | `eEGS_BUY_LIFE_WATER_ACK` | **S → C** | `0x0078FF90` | — | `BuyLifeWaterAck` (Opcode 2087: eEGS_BUY_LIFE_WATER_ACK (On_eEGS_BUY_LIFE_WATER_ACK 0x0078FF90).) |
| **2092** | `0x082C` | `eEGS_INVENTORY_UPDATED_NOT` | **S → C** | `0x0077F070` | — | `InventoryUpdatedNot` (Opcode 2092: eEGS_INVENTORY_UPDATED_NOT (0x0077F070).) |
| **2095** | `0x082F` | `eEGS_NPC_FIRST_MEET_ACK` | **S → C** | `0x00752B60` | — | `NpcFirstMeetAck` (Opcode 2095: eEGS_NPC_FIRST_MEET_ACK response.) |
| **2100** | `0x0834` | `eEGS_PARTY_INVITE_REQ` | **C → S** | `—` | `social.py` | `PartyInviteReq`: party invite request |
| **2101** | `0x0835` | `eEGS_PARTY_INVITE_ACK` | **S → C** | `0x00758700` | — | `PartyInviteAck`: party invite ack |
| **2102** | `0x0836` | `eEGS_PARTY_JOIN_REQ` | **C → S** | `—` | `social.py` | `PartyJoinReq`: party join request |
| **2103** | `0x0837` | `eEGS_PARTY_JOIN_ACK` | **S → C** | `—` | — | `PartyJoinAck`: party join ack |
| **2104** | `0x0838` | `eEGS_PARTY_LEAVE_REQ` | **C → S** | `—` | `social.py` | `PartyLeaveReq`: party leave request |
| **2105** | `0x0839` | `eEGS_PARTY_LEAVE_ACK` | **S → C** | `—` | — | `PartyLeaveAck`: party leave ack / kick notification |
| **2106** | `0x083A` | `eEGS_PARTY_KICK_REQ` | **C → S** | `—` | `social.py` | `PartyKickReq`: party leader kick request |
| **2107** | `0x083B` | `eEGS_PARTY_KICK_ACK` | **S → C** | `—` | — | `PartyKickAck`: party kick ack |
| **2109** | `0x083D` | `eEGS_INSERT_AP_NOT` | **S → C** | `0x00790480` | — | `InsertApNot` (Opcode 2109: eEGS_INSERT_AP_NOT (0x00790480).) |
| **2110** | `0x083E` | `eEGS_INCREASING_STATUS_NOT` | **S → C** | `0x007743A0` | — | — |
| **2115** | `0x0843` | `eEGS_ITEM_UPGRADE_REQ` | **C → S** | `—` | `inventory.py` | `ItemUpgradeReq` (Opcode 2115: eEGS_ITEM_UPGRADE_REQ (0x00790000.c:296).) |
| **2116** | `0x0844` | `eEGS_ITEM_UPGRADE_ACK` | **S → C** | `0x007909C0` | — | `ItemUpgradeAck` (Opcode 2116: eEGS_ITEM_UPGRADE_ACK (On_eEGS_ITEM_UPGRADE_ACK 0x007909C0).) |
| **2119** | `0x0847` | `eEGS_ALARM_UPDATE_REQ` | **C → S** | `—` | `inventory.py` | eEGS_ALARM_UPDATE_REQ (observed: i32 0x7FFFFFFF, i16, tag 0x10 vector<i32>) |
| **2120** | `0x0848` | `eEGS_ALARM_UPDATE_ACK` | **S → C** | `0x00771150` | — | — |
| **2121** | `0x0849` | `eEGS_CONTRACT_UPDATE_REQ` | **C → S** | `—` | `commerce.py` | `ContractUpdateReq` (Opcode 2121: eEGS_CONTRACT_UPDATE_REQ.) |
| **2122** | `0x084A` | `eEGS_CONTRACT_UPDATE_ACK` | **S → C** | `0x00752D80` | — | `ContractUpdateAck` (Opcode 2122: eEGS_CONTRACT_UPDATE_ACK (On_eEGS_CONTRACT_UPDATE_ACK 0x00752D80).) |
| **2223** | `0x08AF` | `eEGS_POST_READ_REQ` | **C → S** | `—` | `mail.py` | `PostReadReq` (Opcode 2223: eEGS_POST_READ_REQ (0x007963C0).) |
| **2224** | `0x08B0` | `eEGS_POST_READ_ACK` | **S → C** | `0x0075A660` | — | `PostReadAck` (Opcode 2224: eEGS_POST_READ_ACK (0x0075A660).) |
| **2225** | `0x08B1` | `eEGS_POST_GET_APPEND_ITEM_REQ` | **C → S** | `—` | `mail.py` | `PostGetAppendItemReq` (Opcode 2225: eEGS_POST_GET_APPEND_ITEM_REQ (0x0079664C).) |
| **2226** | `0x08B2` | `eEGS_POST_GET_APPEND_ITEM_ACK` | **S → C** | `0x0077F8E0` | — | `PostGetAppendItemAck` (Opcode 2226: eEGS_POST_GET_APPEND_ITEM_ACK (0x0077F8E0).) |
| **2227** | `0x08B3` | `eEGS_POST_NEW_ARRIVAL_NOT` | **S → C** | `0x007965B0` | — | `PostNewArrivalNot` (Opcode 2227: eEGS_POST_NEW_ARRIVAL_NOT (0x007965B0).) |
| **2228** | `0x08B4` | `eEGS_DEPOT_SAVE_AR_REQ` | **C → S** | `—` | `inventory.py` | `DepotSaveArReq` (Opcode 2228: eEGS_DEPOT_SAVE_AR_REQ.) |
| **2229** | `0x08B5` | `eEGS_DEPOT_SAVE_AR_ACK` | **S → C** | `0x00795220` | — | `DepotSaveArAck` (Opcode 2229: eEGS_DEPOT_SAVE_AR_ACK (0x00795220).) |
| **2230** | `0x08B6` | `eEGS_DEPOT_LOAD_AR_REQ` | **C → S** | `—` | `inventory.py` | `DepotLoadArReq` (Opcode 2230: eEGS_DEPOT_LOAD_AR_REQ.) |
| **2231** | `0x08B7` | `eEGS_DEPOT_LOAD_AR_ACK` | **S → C** | `0x00795490` | — | `DepotLoadArAck` (Opcode 2231: eEGS_DEPOT_LOAD_AR_ACK (0x00795490).) |
| **2234** | `0x08BA` | `eEGS_POST_RETURN_REQ` | **C → S** | `—` | `mail.py` | `PostReturnReq` (Opcode 2234: eEGS_POST_RETURN_REQ (0x00A33907).) |
| **2235** | `0x08BB` | `eEGS_POST_RETURN_ACK` | **S → C** | `0x00771470` | — | `PostReturnAck` (Opcode 2235: eEGS_POST_RETURN_ACK (0x00771470).) |
| **2236** | `0x08BC` | `eEGS_POST_DELETE_REQ` | **C → S** | `—` | `mail.py` | `PostDeleteReq` (Opcode 2236: eEGS_POST_DELETE_REQ (0x007964EC).) |
| **2237** | `0x08BD` | `eEGS_POST_DELETE_ACK` | **S → C** | `0x007715F0` | — | `PostDeleteAck` (Opcode 2237: eEGS_POST_DELETE_ACK (0x007715F0).) |
| **2242** | `0x08C2` | `eEGS_DEPOT_SHARE_EXPIRE_TIME_GET_REQ` | **C → S** | `—` | `inventory.py` | eEGS_DEPOT_SHARE_EXPIRE_TIME_GET_REQ (empty body, sent when opening storage) -> 2243 (0x0076C040) |
| **2243** | `0x08C3` | `eEGS_DEPOT_SHARE_EXPIRE_TIME_GET_ACK` | **S → C** | `0x0076C040` | — | — |
| **2245** | `0x08C5` | `eEGS_CHEAT_SYSTEM_DELETE_CHARACTER_ACK` | **S → C** | `0x0075A9C0` | — | — |
| **2247** | `0x08C7` | `eEGS_UNDELETE_CHARACTER_ACK` | **S → C** | `0x0075A8A0` | — | `UndeleteCharacterAck` (Opcode 2247: eEGS_UNDELETE_CHARACTER_ACK (handler 0x0075A8A0).) |
| **2249** | `0x08C9` | `eEGS_POST_GET_APPEND_AR_ACK` | **S → C** | `0x007967E0` | — | — |
| **2250** | `0x08CA` | `eEGS_DIVIDE_ITEM_REQ` | **C → S** | `—` | `inventory.py` | `DivideItemReq` (Opcode 2250: eEGS_DIVIDE_ITEM_REQ (0x00795B83).) |
| **2251** | `0x08CB` | `eEGS_DIVIDE_ITEM_ACK` | **S → C** | `0x0077F570` | — | `DivideItemAck` (Opcode 2251: eEGS_DIVIDE_ITEM_ACK (0x0077F570).) |
| **2253** | `0x08CD` | `eEGS_POST_SAVE_ACK` | **S → C** | `0x0075A780` | — | — |
| **2254** | `0x08CE` | `eEGS_MAGICENCHANT_ENCHANT_REQ` | **C → S** | `—` | `inventory.py` | `MagicEnchantEnchantReq` (Opcode 2254: eEGS_MAGICENCHANT_ENCHANT_REQ.) |
| **2255** | `0x08CF` | `eEGS_MAGICENCHANT_ENCHANT_ACK` | **S → C** | `0x00796DC0` | — | `MagicEnchantEnchantAck` (Opcode 2255: eEGS_MAGICENCHANT_ENCHANT_ACK (0x00796DC0).) |
| **2256** | `0x08D0` | `eEGS_MAGICENCHANT_ERASE_OPTION_REQ` | **C → S** | `—` | `inventory.py` | `MagicEnchantEraseOptionReq` (Opcode 2256: eEGS_MAGICENCHANT_ERASE_OPTION_REQ.) |
| **2257** | `0x08D1` | `eEGS_MAGICENCHANT_ERASE_OPTION_ACK` | **S → C** | `0x00797120` | — | `MagicEnchantEraseOptionAck` (Opcode 2257: eEGS_MAGICENCHANT_ERASE_OPTION_ACK (0x00797120).) |
| **2258** | `0x08D2` | `eEGS_MAGICENCHANT_EXPEND_SLOT_REQ` | **C → S** | `—` | `inventory.py` | `MagicEnchantExpendSlotReq` (Opcode 2258: eEGS_MAGICENCHANT_EXPEND_SLOT_REQ.) |
| **2259** | `0x08D3` | `eEGS_MAGICENCHANT_EXPEND_SLOT_ACK` | **S → C** | `0x0077FC60` | — | `MagicEnchantExpendSlotAck` (Opcode 2259: eEGS_MAGICENCHANT_EXPEND_SLOT_ACK (0x0077FC60).) |
| **2280** | `0x08E8` | `eEGS_INIT_SKILL_NOT` | **S → C** | `0x00797740` | — | `InitSkillNot` (Opcode 2280: eEGS_INIT_SKILL_NOT (0x00797740).) |
| **2283** | `0x08EB` | `eEGS_PROMOTION_NOT` | **S → C** | `0x00797F00` | — | `PromotionNot` (Opcode 2283: eEGS_PROMOTION_NOT (0x00797F00).) |
| **2284** | `0x08EC` | `eEGS_RANDOM_ITEM_UPGRADE_REQ` | **C → S** | `—` | `inventory.py` | `RandomItemUpgradeReq` (Opcode 2284: eEGS_RANDOM_ITEM_UPGRADE_REQ.) |
| **2285** | `0x08ED` | `eEGS_RANDOM_ITEM_UPGRADE_ACK` | **S → C** | `0x0077FED0` | — | `RandomItemUpgradeAck` (Opcode 2285: eEGS_RANDOM_ITEM_UPGRADE_ACK (0x0077FED0).) |
| **2286** | `0x08EE` | `eEGS_REBIRTH_COIN_CHANGE_NOT` | **S → C** | `0x007983B0` | — | `RebirthCoinChangeNot` (Opcode 2286: eEGS_REBIRTH_COIN_CHANGE_NOT (0x007983B0).) |
| **2287** | `0x08EF` | `eEGS_NOT_ENOUGH_INVEN_SPACE_NOT` | **S → C** | `0x00771790` | — | — |
| **2288** | `0x08F0` | `eEGS_DUNGEON_EXP_BONUS_FINISH_NOT` | **S → C** | `0x007986F0` | — | — |
| **2301** | `0x08FD` | `eEGS_DUNGEON_BONUS_EXP_CHANGE_NOT` | **S → C** | `0x007987D0` | — | — |
| **2304** | `0x0900` | `eEGS_ARENA_SQUARELIST_REQ` | **C → S** | `—` | — | `ArenaSquareListReq` (Opcode 2304 / 2446 (eEGS_ARENA_SQUARELIST_REQ): Request arena square/channel list.) |
| **2305** | `0x0901` | `eEGS_ARENA_SQUARELIST_ACK` | **S → C** | `—` | — | `ArenaSquareListAck` (Opcode 2305 / 2447 (eEGS_ARENA_SQUARELIST_ACK): List of arena channels.) |
| **2308** | `0x0904` | `eEGS_ARENA_GET_INVITELIST_REQ` | **C → S** | `—` | — | `ArenaGetInviteListReq` (Opcode 2308 (eEGS_ARENA_GET_INVITELIST_REQ): Request pending arena invites.) |
| **2309** | `0x0905` | `eEGS_ARENA_GET_INVITELIST_ACK` | **S → C** | `—` | — | `ArenaGetInviteListAck` (Opcode 2309 (eEGS_ARENA_GET_INVITELIST_ACK): Pending arena team invites.) |
| **2310** | `0x0906` | `eEGS_CHAR_NICK_CHANGE_REQ` | **C → S** | `—` | `social.py` | `CharNickChangeReq` (Opcode 2310: eEGS_CHAR_NICK_CHANGE_REQ.) |
| **2311** | `0x0907` | `eEGS_CHAR_NICK_CHANGE_ACK` | **S → C** | `0x00780200` | — | `CharNickChangeAck` (Opcode 2311: eEGS_CHAR_NICK_CHANGE_ACK (0x00780200).) |
| **2314** | `0x090A` | `eEGS_GUILD_NAME_CHANGE_REQ` | **C → S** | `—` | `social.py` | `GuildNameChangeReq` (Opcode 2314: eEGS_GUILD_NAME_CHANGE_REQ.) |
| **2315** | `0x090B` | `eEGS_GUILD_NAME_CHANGE_ACK` | **S → C** | `0x00780590` | — | `GuildNameChangeAck` (Opcode 2315: eEGS_GUILD_NAME_CHANGE_ACK (0x00780590).) |
| **2318** | `0x090E` | `eEGS_DAILY_DUN_ENTER_COUNT_UPDATE_NOT` | **S → C** | `0x00798D20` | — | — |
| **2319** | `0x090F` | `eEGS_KEYBOARD_SET_CUSTOM_KEY_REQ` | **C → S** | `—` | `social.py` | `KeyboardSetCustomKeyReq` (Opcode 2319: eEGS_KEYBOARD_SET_CUSTOM_KEY_REQ.) |
| **2320** | `0x0910` | `eEGS_KEYBOARD_SET_CUSTOM_KEY_ACK` | **S → C** | `0x00753960` | — | `KeyboardSetCustomKeyAck` (Opcode 2320: eEGS_KEYBOARD_SET_CUSTOM_KEY_ACK (0x00753960).) |
| **2321** | `0x0911` | `eEGS_ITEM_REMAIN_TIME_NOT` | **S → C** | `0x0077AED0` | — | `ItemRemainTimeNot` (Opcode 2321: eEGS_ITEM_REMAIN_TIME_NOT (0x0077AED0).) |
| **2322** | `0x0912` | `eEGS_ITEM_DELETE_NOT` | **S → C** | `0x00774DD0` | — | `ItemDeleteNot` (Opcode 2322: eEGS_ITEM_DELETE_NOT (0x00774DD0).) |
| **2324** | `0x0914` | `eEGS_CHAR_NICK_CHANGE_BY_INTEGRATE_ACK` | **S → C** | `0x0075AD10` | — | — |
| **2327** | `0x0917` | `eEGS_ACHIEVE_GET_LIST_REQ` | **C → S** | `—` | `social.py` | `AchieveGetListReq` (Opcode 2327: eEGS_ACHIEVE_GET_LIST_REQ.) |
| **2328** | `0x0918` | `eEGS_ACHIEVE_GET_LIST_ACK` | **S → C** | `0x0079D650` | — | `AchieveGetListAck` (Opcode 2328: eEGS_ACHIEVE_GET_LIST_ACK (0x0079D650).) |
| **2329** | `0x0919` | `eEGS_ACHIEVE_CHANGE_NOT` | **S → C** | `0x0076C720` | — | `AchieveChangeNot` (Opcode 2329: eEGS_ACHIEVE_CHANGE_NOT (0x0076C720).) |
| **2330** | `0x091A` | `eEGS_ACHIEVE_COMPLETE_NOT` | **S → C** | `0x0079D240` | — | `AchieveCompleteNot` (Opcode 2330: eEGS_ACHIEVE_COMPLETE_NOT (0x0079D240).) |
| **2335** | `0x091F` | `eEGS_TITLE_CHANGE_REQ` | **C → S** | `—` | `social.py` | `TitleChangeReq` (Opcode 2335: eEGS_TITLE_CHANGE_REQ (0x00799753).) |
| **2336** | `0x0920` | `eEGS_TITLE_CHANGE_ACK` | **S → C** | `0x007751C0` | — | `TitleChangeAck` (Opcode 2336: eEGS_TITLE_CHANGE_ACK (0x007751C0).) |
| **2338** | `0x0922` | `eEGS_ITEM_SPIRIT_CHANGE_REQ` | **C → S** | `—` | `inventory.py` | `ItemSpiritChangeReq` (Opcode 2338: eEGS_ITEM_SPIRIT_CHANGE_REQ.) |
| **2339** | `0x0923` | `eEGS_ITEM_SPIRIT_CHANGE_ACK` | **S → C** | `0x00780860` | — | `ItemSpiritChangeAck` (Opcode 2339: eEGS_ITEM_SPIRIT_CHANGE_ACK (0x00780860).) |
| **2352** | `0x0930` | `eEGS_IP_ADDRESS_NOT` | **S → C** | `—` | `social.py` | eEGS_IP_ADDRESS_NOT: client LAN/WAN IP notification only. |
| **2358** | `0x0936` | `eEGS_GUIDE_BEGINNER_UPDATE_REQ` | **C → S** | `—` | `dungeon.py` | `GuideBeginnerUpdateReq` (Opcode 2358: eEGS_GUIDE_BEGINNER_UPDATE_REQ (0x0079A3B0).) |
| **2362** | `0x093A` | `eEGS_AVATAR_ZAM_INSERT_REQ` | **C → S** | `—` | `inventory.py` | `AvatarZamInsertReq` (Opcode 2362: eEGS_AVATAR_ZAM_INSERT_REQ (0x007A46CB).) |
| **2363** | `0x093B` | `eEGS_AVATAR_ZAM_INSERT_ACK` | **S → C** | `0x00782D00` | — | `AvatarZamInsertAck` (Opcode 2363: eEGS_AVATAR_ZAM_INSERT_ACK (0x00782D00).) |
| **2364** | `0x093C` | `eEGS_AVATAR_ZAM_ERASE_REQ` | **C → S** | `—` | `inventory.py` | `AvatarZamEraseReq` (Opcode 2364: eEGS_AVATAR_ZAM_ERASE_REQ (0x007A481B).) |
| **2365** | `0x093D` | `eEGS_AVATAR_ZAM_ERASE_ACK` | **S → C** | `0x00782F40` | — | `AvatarZamEraseAck` (Opcode 2365: eEGS_AVATAR_ZAM_ERASE_ACK (0x00782F40).) |
| **2385** | `0x0951` | `eEGS_INIT_PROFICIENCY_ACK` | **S → C** | `0x00797B10` | — | — |
| **2390** | `0x0956` | `eEGS_ROULETTE_MANAGER_INFO_REQ` | **C → S** | `—` | `commerce.py` | eEGS_ROULETTE_MANAGER_INFO_REQ -> eEGS_ROULETTE_MANAGER_INFO_ACK (2391), handler 0x6CC6B0. |
| **2391** | `0x0957` | `eEGS_ROULETTE_MANAGER_INFO_ACK` | **S → C** | `—` | — | `RouletteManagerInfoAck` (Opcode 2391: eEGS_ROULETTE_MANAGER_INFO_ACK response.) |
| **2398** | `0x095E` | `eEGS_BROKER_CHANGE_REGIST_COUNT` | **S → C** | `0x0077B2D0` | — | — |
| **2399** | `0x095F` | `eEGS_POST_DAILY_SEND_RECOVER_NOT` | **S → C** | `0x0079A880` | — | — |
| **2400** | `0x0960` | `eEGS_DEPOT_SHARE_EXPIRE_TIME_ADD_NOT` | **S → C** | `0x0076BE80` | — | — |
| **2401** | `0x0961` | `eEGS_DEPOT_SIZE_INCREASE_NOT` | **S → C** | `0x007535A0` | — | — |
| **2402** | `0x0962` | `eEGS_DB_LIST_GET_REQ` | **C → S** | `—` | — | `GameServer` (A game server entry shown in the initial 'Server List' dialog (Opcode 2402/2403).) |
| **2405** | `0x0965` | `eEGS_EVENT_DELETE_CHARACTER_ACK` | **S → C** | `0x0075AF00` | — | — |
| **2406** | `0x0966` | `eEGS_CHAR_VERIFY_STAT_REQ` | **C → S** | `—` | `inventory.py` | `CharVerifyStatReq` (Opcode 2406: eEGS_CHAR_VERIFY_STAT_REQ. Heartbeat / stat verification from client.) |
| **2407** | `0x0967` | `eEGS_CHAR_VERIFY_STAT_ACK` | **S → C** | `0x0074B830` | — | `CharVerifyStatAck` (Opcode 2407: eEGS_CHAR_VERIFY_STAT_ACK (On_eEGS_CHAR_VERIFY_STAT_ACK 0x0074B830).) |
| **2409** | `0x0969` | `eEGS_AVATAR_ZAM_MERGE_ACK` | **S → C** | `0x00780AF0` | — | — |
| **2410** | `0x096A` | `eEGS_QUEST_HISTORY_REFRESH_NOT` | **S → C** | `0x0076C1E0` | — | `QuestHistoryNot` (Opcode 2410: eEGS_QUEST_HISTORY_REFRESH_NOT (handler 0x0076C1E0).) |
| **2415** | `0x096F` | `eEGS_CHEAT_FORCE_ITEM_UPGRADE_ACK` | **S → C** | `0x00780DD0` | — | — |
| **2417** | `0x0971` | `eEGS_BEAUTYSHOP_CARE_ACK` | **S → C** | `0x0079B3A0` | — | — |
| **2418** | `0x0972` | `eEGS_SERVERBUFF_ADD_NOT` | **S → C** | `0x0079B880` | — | — |
| **2419** | `0x0973` | `eEGS_SERVERBUFF_DELETE_NOT` | **S → C** | `0x0079BD10` | — | — |
| **2421** | `0x0975` | `eEGS_MONSTER_DEAD_NOT` | **S → C** | `0x0076A000` | — | — |
| **2422** | `0x0976` | `eEGS_ACTIVE_WARFLAG_REQ` | **C → S** | `—` | `dungeon.py` | `ActiveWarFlagReq` (Opcode 2422: eEGS_ACTIVE_WARFLAG_REQ (0x0087D170 -> 0x0079C300).) |
| **2427** | `0x097B` | `eEGS_GUILD_PERSON_ARENA_GRADE_MODIFY_ACK` | **S → C** | `0x00771D70` | — | — |
| **2429** | `0x097D` | `eEGS_USE_SELECTED_SKILL_CHANGE_ITEM_ACK` | **S → C** | `0x0079C5E0` | — | — |
| **2442** | `0x098A` | `eEGS_CHARSLOT_EXTEND_ACK` | **S → C** | `0x00781000` | — | — |
| **2443** | `0x098B` | `eEGS_DAILY_DUN_CLEAR_COUNT_UPDATE_NOT` | **S → C** | `0x0079D0A0` | — | — |
| **2445** | `0x098D` | `eEGS_ACHIEVE_UPDATE_ACK` | **S → C** | `0x0074B830` | — | — |
| **2451** | `0x0993` | `eEGS_GUILD_SIEGE_CHANGE_OFFICER_ACK` | **S → C** | `0x0076CA40` | — | — |
| **2461** | `0x099D` | `eEGS_DEPOT_SLOT_EXTEND_REQ` | **C → S** | `—` | `inventory.py` | `DepotSlotExtendReq` (Opcode 2461: eEGS_DEPOT_SLOT_EXTEND_REQ (0x00651718).) |
| **2462** | `0x099E` | `eEGS_DEPOT_SLOT_EXTEND_ACK` | **S → C** | `—` | — | `DepotSlotExtendAck` (Opcode 2462: eEGS_DEPOT_SLOT_EXTEND_ACK (0x00651B20).) |
| **2516** | `0x09D4` | `eEGS_PET_DYEING_NOT` | **S → C** | `0x00776080` | — | — |
| **2517** | `0x09D5` | `eEGS_KEEP_BUFF_INSERT_NOT` | **S → C** | `0x007A17F0` | — | — |
| **2518** | `0x09D6` | `eEGS_KEEP_BUFF_DELETE_NOT` | **S → C** | `0x007A1C20` | — | — |
| **2519** | `0x09D7` | `eEGS_KEEP_BUFF_CLEAR_NOT` | **S → C** | `0x007A1EE0` | — | — |
| **2520** | `0x09D8` | `eEGS_KEEP_COOLTIME_DELETE_NOT` | **S → C** | `0x00771FD0` | — | — |
| **2521** | `0x09D9` | `eEGS_KEEP_COOLTIME_CLEAR_NOT` | **S → C** | `0x007641C0` | — | — |
| **2524** | `0x09DC` | `eEGS_FISHING_START_ACK` | **S → C** | `0x0075B0B0` | — | — |
| **2526** | `0x09DE` | `eEGS_FISHING_STOP_ACK` | **S → C** | `0x0075B1C0` | — | — |
| **2527** | `0x09DF` | `eEGS_FISHING_RESULT_NOT` | **S → C** | `0x00782020` | — | — |
| **2528** | `0x09E0` | `eEGS_FISHING_FAILED_NOT` | **S → C** | `0x00776310` | — | — |
| **2529** | `0x09E1` | `eEGS_FISHING_PROFICIENCY_NOT` | **S → C** | `0x00776400` | — | — |
| **2537** | `0x09E9` | `eEGS_LEAGUE_SEASON_CHAR_AWARD_NOT` | **S → C** | `0x007A22D0` | — | — |
| **2538** | `0x09EA` | `eEGS_LEAGUE_SEASON_GUILD_AWARD_NOT` | **S → C** | `0x007A2560` | — | — |
| **2541** | `0x09ED` | `eEGS_FISHING_LICENSE_CHANGE_NOT` | **S → C** | `0x0075B2E0` | — | — |
| **2542** | `0x09EE` | `eEGS_FISHING_LICENSE_EXPIRE_NOT` | **S → C** | `0x0075B480` | — | — |
| **2546** | `0x09F2` | `eEGS_ITEM_DECOMPOSE_ACK` | **S → C** | `0x00782300` | — | — |
| **2548** | `0x09F4` | `eEGS_RANDOM_OPTION_CHANGE_ACK` | **S → C** | `0x00782830` | — | — |
| **2550** | `0x09F6` | `eEGS_LEAGUE_SEASON_ARENA_GET_RANK_REQ` | **C → S** | `—` | — | `LeagueSeasonArenaGetRankReq` (Opcode 2550 / 2475 (eEGS_LEAGUE_SEASON_ARENA_GET_RANK_REQ): Request season rank ladder.) |
| **2551** | `0x09F7` | `eEGS_LEAGUE_SEASON_ARENA_GET_RANK_ACK` | **S → C** | `—` | — | `LeagueSeasonArenaGetRankAck` (Opcode 2551 / 2476 (eEGS_LEAGUE_SEASON_ARENA_GET_RANK_ACK): Arena ladder rank list.) |
| **2552** | `0x09F8` | `eEGS_LEAGUE_SEASON_ARENA_GET_MY_RANK_REQ` | **C → S** | `—` | — | `LeagueSeasonArenaGetMyRankReq` (Opcode 2552 / 2477 (eEGS_LEAGUE_SEASON_ARENA_GET_MY_RANK_REQ): Request player's personal rank.) |
| **2553** | `0x09F9` | `eEGS_LEAGUE_SEASON_ARENA_GET_MY_RANK_ACK` | **S → C** | `—` | — | `LeagueSeasonArenaGetMyRankAck` (Opcode 2553 / 2478 (eEGS_LEAGUE_SEASON_ARENA_GET_MY_RANK_ACK): Personal rank reply.) |
| **2566** | `0x0A06` | `eEGS_FRIEND_BLOCK_LIST_ADD_ACK` | **S → C** | `0x0075B640` | — | — |
| **2568** | `0x0A08` | `eEGS_FRIEND_BLOCK_LIST_DELETE_ACK` | **S → C** | `0x0075B9B0` | — | — |
| **2569** | `0x0A09` | `eEGS_FRIEND_BLOCK_LIST_REQUEST_REQ` | **C → S** | `—` | `social.py` | `GuildOrAttendanceAck` (Opcode 2570: ACK response to opcode 2569.) |
| **2570** | `0x0A0A` | `eEGS_FRIEND_BLOCK_LIST_REQUEST_ACK` | **C → S** | `0x00772160` | — | `GuildOrAttendanceAck` (Opcode 2570: ACK response to opcode 2569.) |
| **2572** | `0x0A0C` | `eEGS_FRIEND_BLOCK_LIST_UPDATE_ACK` | **S → C** | `0x00753C80` | — | — |
| **2574** | `0x0A0E` | `eEGS_USE_ITEM_LEAGUE_POINT_ADD_ACK` | **S → C** | `0x007A3140` | — | — |
| **2577** | `0x0A11` | `eEGS_DUALSKILL_EXPIRE_NOT` | **S → C** | `0x007A3530` | — | — |
| **2578** | `0x0A12` | `eEGS_DUALSKILL_ACTIVE_NOT` | **S → C** | `0x007A3990` | — | — |
| **2580** | `0x0A14` | `eEGS_DUALSKILL_CHANGE_INDEX_ACK` | **S → C** | `0x007A3F00` | — | — |
| **2582** | `0x0A16` | `eEGS_CHANGE_MAINSPIRIT_NOT` | **S → C** | `0x007A42F0` | — | — |
| **2585** | `0x0A19` | `eEGS_TREASURE_COUNT_CHANGE_NOT` | **S → C** | `0x0075BE20` | — | — |
| **2587** | `0x0A1B` | `eEGS_SALEBYBULK_OPTION_ACK` | **S → C** | `0x0076CBD0` | — | — |
| **2589** | `0x0A1D` | `eEGS_SALEBYBULK_REGIST_ACK` | **S → C** | `0x007725D0` | — | — |
| **2591** | `0x0A1F` | `eEGS_SELL_ITEM_ALL_ACK` | **S → C** | `0x007845B0` | — | — |
| **2598** | `0x0A26` | `eEGS_AVATAR_ZAM_SEPARATE_ACK` | **S → C** | `0x00783190` | — | — |
| **2600** | `0x0A28` | `eEGS_CITADEL_ROUND_CLEAR_ACK` | **S → C** | `0x0075BF20` | — | — |
| **2620** | `0x0A3C` | `eEGS_MARK_ITEM_ACTIVE_NOT` | **S → C** | `0x00776600` | — | — |
| **2621** | `0x0A3D` | `eEGS_MARK_TAB_ACTIVE_NOT` | **S → C** | `0x007767E0` | — | — |
| **2626** | `0x0A42` | `eEGS_INDULGENCE_NOT` | **S → C** | `0x0075C090` | — | — |
| **2630** | `0x0A46` | `eEGS_ITEM_CLASS_SMELTING_ACK` | **S → C** | `0x00783790` | — | — |
| **2631** | `0x0A47` | `eEGS_CIDADEL_PLAY_COUNT_UPDATE_NOT` | **S → C** | `0x007A5580` | — | — |
| **2641** | `0x0A51` | `eEGS_SERVERBUFF_ADDITION_FISHING_NOT` | **S → C** | `0x00779500` | — | — |
| **2647** | `0x0A57` | `eEGS_RIDING_EXPIRE_UPDATE_ACK` | **S → C** | `0x007839F0` | — | — |
| **2649** | `0x0A59` | `eEGS_TEACHING_STRESS_REWARD_ACK` | **S → C** | `0x0075C7B0` | — | — |
| **2650** | `0x0A5A` | `eEGS_TEACHING_GET_HISTORY_NOT` | **S → C** | `0x0077B5D0` | — | — |
| **2659** | `0x0A63` | `eEGS_TEACHING_GRADUATION_REWARD_ACK` | **S → C** | `0x0075C8E0` | — | — |
| **2672** | `0x0A70` | `eEGS_FIX_ITEM_UPGRADE_REQ` | **C → S** | `—` | `inventory.py` | `FixItemUpgradeReq` (Opcode 2672: eEGS_FIX_ITEM_UPGRADE_REQ.) |
| **2673** | `0x0A71` | `eEGS_FIX_ITEM_UPGRADE_ACK` | **S → C** | `0x00783C40` | — | `FixItemUpgradeAck` (Opcode 2673: eEGS_FIX_ITEM_UPGRADE_ACK (0x00783C40).) |
| **2675** | `0x0A73` | `eEGS_GUILD_PERSON_INTRODUTION_ACK` | **S → C** | `0x0075CCA0` | — | — |
| **2676** | `0x0A74` | `eEGS_UPDATE_CITADEL_HISTORY_NOT` | **S → C** | `0x0075CEF0` | — | — |
| **2677** | `0x0A75` | `eEGS_GUILD_MISSION_NOT` | **S → C** | `0x00753DF0` | — | — |
| **2679** | `0x0A77` | `eEGS_GUILD_BROKER_LIST_ACK` | **S → C** | `0x00776950` | — | — |
| **2681** | `0x0A79` | `eEGS_GUILD_BROKER_BID_ACK` | **S → C** | `0x0075D040` | — | — |
| **2683** | `0x0A7B` | `eEGS_GUILD_BROKER_RETURN_POINT_ACK` | **S → C** | `0x0075D180` | — | — |
| **2685** | `0x0A7D` | `eEGS_GUILD_SUPPLY_GET_REWARD_ACK` | **S → C** | `0x00783F70` | — | — |
| **2686** | `0x0A7E` | `eEGS_GUILD_SUPPLY_LIST_NOT` | **S → C** | `0x00772920` | — | — |
| **2688** | `0x0A80` | `eEGS_CHEAT_GUILD_BROKER_EXIT_ACK` | **S → C** | `0x00759D60` | — | — |
| **2690** | `0x0A82` | `eEGS_CHEAT_GUILD_BROKER_REWARD_ACK` | **S → C** | `0x00759D60` | — | — |
| **2692** | `0x0A84` | `eEGS_CHEAT_CHANGE_VALIDGUILD_COUNT_ACK` | **S → C** | `0x00759D60` | — | — |
| **2703** | `0x0A8F` | `eEGS_DECREASE_USAGELIMIT_NOT` | **S → C** | `0x00766EA0` | — | — |
| **2704** | `0x0A90` | `eEGS_CLEAR_USAGELIMIT_NOT` | **S → C** | `0x0075FEA0` | — | — |
| **2709** | `0x0A95` | `eEGS_USE_ARENA_SP_ITEM_REQ` | **C → S** | `—` | `inventory.py` | `UseArenaSpItemReq` (Opcode 2709: eEGS_USE_ARENA_SP_ITEM_REQ.) |
| **2710** | `0x0A96` | `eEGS_USE_ARENA_SP_ITEM_ACK` | **S → C** | `0x007A7CA0` | — | `UseArenaSpItemAck` (Opcode 2710: eEGS_USE_ARENA_SP_ITEM_ACK (0x007A7CA0).) |
| **2711** | `0x0A97` | `eEGS_VIP_SERVICE_INFO_NOT` | **S → C** | `0x007A8040` | — | — |
| **3012** | `0x0BC4` | `eEDB_UPDATE_DUNGEON_HISTORY_NOT` | **S → C** | `0x00752A00` | — | — |
| **3108** | `0x0C24` | `eEDB_DELETE_DUNGEON_HISTORY_NOT` | **S → C** | `0x00772790` | — | — |
| **4071** | `0x0FE7` | `eECN_UPDATE_CHAR_INDULGENCE_RATE_NOT` | **S → C** | `0x007A50A0` | — | — |
| **5367** | `0x14F7` | `eERC_GOLDGOBLIEN_DISAPPEAR_NOT` | **S → C** | `—` | — | `GoldGoblinDisappearNot` (Opcode 5367: eERC_GOLDGOBLIEN_DISAPPEAR_NOT.) |
| **5383** | `0x1507` | `eERC_QUESTITEM_DROP_ACK` | **S → C** | `0x007A78C0` | — | — |
| **6010** | `0x177A` | `eERT_TRADE_RESULT_NOT` | **S → C** | `0x0077E090` | — | — |
| **6031** | `0x178F` | `eERT_TEACHING_DELETE_ACK` | **S → C** | `0x007A5D60` | — | — |
| **6033** | `0x1791` | `eERT_TEACHING_SUMMON_REQUEST_ACK` | **C → S** | `0x0075CA40` | — | — |

---

## Skill System & Combat Abilities

| Opcode | Hex | Enum Name | Direction | Client VA | Server Handler | Message Class / Wire Notes |
| :--- | :--- | :--- | :---: | :--- | :--- | :--- |
| **2050** | `0x0802` | `eEGS_LEARN_SKILL_REQ` | **C → S** | `—` | `skills.py` | `LearnSkillReq` (Opcode 2050: eEGS_LEARN_SKILL_REQ (0x00780000.c:9504).) |
| **2051** | `0x0803` | `eEGS_LEARN_SKILL_ACK` | **S → C** | `0x0078DBE0` | — | `LearnSkillAck` (Opcode 2051: eEGS_LEARN_SKILL_ACK (On_eEGS_LEARN_SKILL_ACK 0x0078DBE0).) |
| **2053** | `0x0805` | `eEGS_MODIFY_SKILL_SPEECH_REQ` | **C → S** | `—` | `skills.py` | `ModifySkillSpeechReq` (Opcode 2053: eEGS_MODIFY_SKILL_SPEECH_REQ (0x00780000.c:9674).) |
| **2054** | `0x0806` | `eEGS_MODIFY_SKILL_SPEECH_ACK` | **S → C** | `0x0078E090` | — | `ModifySkillSpeechAck` (Opcode 2054: eEGS_MODIFY_SKILL_SPEECH_ACK (On_eEGS_MODIFY_SKILL_SPEECH_ACK 0x0078E090).) |
| **2055** | `0x0807` | `eEGS_DELETE_SKILL_SPEECH_REQ` | **C → S** | `—` | `skills.py` | `DeleteSkillSpeechReq` (Opcode 2055: eEGS_DELETE_SKILL_SPEECH_REQ (0x00780000.c:9708).) |
| **2056** | `0x0808` | `eEGS_DELETE_SKILL_SPEECH_ACK` | **S → C** | `0x0078E270` | — | `DeleteSkillSpeechAck` (Opcode 2056: eEGS_DELETE_SKILL_SPEECH_ACK (On_eEGS_DELETE_SKILL_SPEECH_ACK 0x0078E270).) |
| **2111** | `0x083F` | `eEGS_USE_LEARN_SKILL_ITEM_REQ` | **C → S** | `—` | `skills.py` | `UseLearnSkillItemReq` (Opcode 2111: eEGS_USE_LEARN_SKILL_ITEM_REQ.) |
| **2112** | `0x0840` | `eEGS_USE_LEARN_SKILL_ITEM_ACK` | **S → C** | `0x0078BCD0` | — | `UseLearnSkillItemAck` (Opcode 2112: eEGS_USE_LEARN_SKILL_ITEM_ACK (0x0078BCD0).) |
| **2117** | `0x0845` | `eEGS_UPDATE_SKILL_LOCKED_REQ` | **C → S** | `—` | `skills.py` | `UpdateSkillLockedReq` (Opcode 2117: eEGS_UPDATE_SKILL_LOCKED_REQ (0x00790000.c:1390).) |
| **2118** | `0x0846` | `eEGS_UPDATE_SKILL_LOCKED_ACK` | **S → C** | `0x00752C70` | — | `UpdateSkillLockedAck` (Opcode 2118: eEGS_UPDATE_SKILL_LOCKED_ACK (On_eEGS_UPDATE_SKILL_LOCKED_ACK 0x00752C70).) |
| **2697** | `0x0A89` | `eEGS_LEARN_SKILL_LIST_REQ` | **C → S** | `—` | `skills.py` | `LearnSkillListReq` (Opcode 2697: eEGS_LEARN_SKILL_LIST_REQ (0x007A73D0).) |
| **2698** | `0x0A8A` | `eEGS_LEARN_SKILL_LIST_ACK` | **S → C** | `0x007A74A0` | — | `LearnSkillListAck` (Opcode 2698: eEGS_LEARN_SKILL_LIST_ACK (On_opcode_2698 0x007A74A0).) |

---

## Commerce, NPC Stores, Cash Shop & Player Trade

| Opcode | Hex | Enum Name | Direction | Client VA | Server Handler | Message Class / Wire Notes |
| :--- | :--- | :--- | :---: | :--- | :--- | :--- |
| **2065** | `0x0811` | `eEGS_GET_STORE_INFO_REQ` | **C → S** | `—` | `commerce.py` | eEGS_GET_STORE_INFO_REQ (i32, u32 npc id; observed when talking to a shop NPC) -> eEGS_GET_STORE_INFO_ACK 2066: empty store. |
| **2066** | `0x0812` | `eEGS_GET_STORE_INFO_ACK` | **S → C** | `0x007842C0` | — | `StoreInfoAck` (Opcode 2066: eEGS_GET_STORE_INFO_ACK (handler 0x007842C0).) |
| **2067** | `0x0813` | `eEGS_BUY_ITEM_REQ` | **C → S** | `—` | `commerce.py` | `BuyItemReq` (Opcode 2067: eEGS_BUY_ITEM_REQ (0x00780000.c:10667).) |
| **2068** | `0x0814` | `eEGS_BUY_ITEM_ACK` | **S → C** | `0x0077E2F0` | — | `BuyItemAck` (Opcode 2068: eEGS_BUY_ITEM_ACK (On_eEGS_BUY_ITEM_ACK 0x0077E2F0).) |
| **2069** | `0x0815` | `eEGS_SELL_ITEM_REQ` | **C → S** | `—` | `commerce.py` | `SellItemReq` (Opcode 2069: eEGS_SELL_ITEM_REQ (0x00780000.c:10700).) |
| **2070** | `0x0816` | `eEGS_SELL_ITEM_ACK` | **S → C** | `0x0077E8E0` | — | `SellItemAck` (Opcode 2070: eEGS_SELL_ITEM_ACK (On_eEGS_SELL_ITEM_ACK 0x0077E8E0).) |
| **2071** | `0x0817` | `eEGS_REPURCHASE_ITEM_REQ` | **C → S** | `—` | `commerce.py` | `RepurchaseItemReq` (Opcode 2071: eEGS_REPURCHASE_ITEM_REQ (0x00780000.c:10735).) |
| **2072** | `0x0818` | `eEGS_REPURCHASE_ITEM_ACK` | **S → C** | `0x0077EC30` | — | `RepurchaseItemAck` (Opcode 2072: eEGS_REPURCHASE_ITEM_ACK (On_eEGS_REPURCHASE_ITEM_ACK 0x0077EC30).) |
| **2369** | `0x0941` | `eEGS_BILLING_GET_CURRENT_CASH_REQ` | **C → S** | `—` | `commerce.py` | eEGS_BILLING_GET_CURRENT_CASH_REQ -> 2370: result, u64 cash, u32 mileage. Cash is per account (store meta, set from the dashboard); mileage 0. |
| **2370** | `0x0942` | `eEGS_BILLING_GET_CURRENT_CASH_ACK` | **S → C** | `—` | — | `CurrentCashAck` (Opcode 2370: eEGS_BILLING_GET_CURRENT_CASH_ACK (case in 0x004DCCC0 -> 0x004CFDF0).) |
| **2592** | `0x0A20` | `eEGS_BAG_CHANGE_SELL_ENABLE_REQ` | **C → S** | `—` | `commerce.py` | eEGS_BAG_CHANGE_SELL_ENABLE_REQ. |
| **2594** | `0x0A22` | `eEGS_HTTPNOTICE_CHECK_REQ` | **C → S** | `—` | `commerce.py` | `HttpNoticeCheckReq` (Opcode 2594: eEGS_HTTPNOTICE_CHECK_REQ.) |
| **2595** | `0x0A23` | `eEGS_HTTPNOTICE_CHECK_ACK` | **S → C** | `—` | — | `HttpNoticeCheckAck` (Opcode 2595: eEGS_HTTPNOTICE_CHECK_ACK (0x005A5110).) |
| **2601** | `0x0A29` | `eEGS_MONSTERCARD_GET_LIST_REQ` | **C → S** | `—` | `commerce.py` | eEGS_MONSTERCARD_GET_LIST_REQ -> 2602. |
| **2608** | `0x0A30` | `eEGS_MONSTERCARD_GET_CHAR_DECK_REQ` | **C → S** | `—` | `commerce.py` | eEGS_MONSTERCARD_GET_CHAR_DECK_REQ -> 2609. |
| **2617** | `0x0A39` | `eEGS_MONSTERCARD_GET_ALBUM_REQ` | **C → S** | `—` | `commerce.py` | eEGS_MONSTERCARD_GET_ALBUM_REQ -> 2618. |
| **2712** | `0x0A98` | `eEGS_BILLING_STEAM_INIT_BUY_ITEM_NOT` | **S → C** | `—` | `commerce.py` | `SteamInitBuyItemNot` (Opcode 2712: eEGS_BILLING_STEAM_INIT_BUY_ITEM_NOT (sender Lua_BuyItem 0x004D1B10).) |
| **2713** | `0x0A99` | `eEGS_BILLING_STEAM_FINALIZE_BUY_ITEM_REQ` | **C → S** | `—` | `commerce.py` | eEGS_BILLING_STEAM_FINALIZE_BUY_ITEM_REQ (0x004E6440: u64 order id, bool authorized). Not reached offline; acknowledge without items. |
| **2714** | `0x0A9A` | `eEGS_BILLING_STEAM_FINALIZE_BUY_ITEM_ACK` | **S → C** | `—` | — | `SteamFinalizeBuyItemAck` (Opcode 2714: eEGS_BILLING_STEAM_FINALIZE_BUY_ITEM_ACK.) |
| **5069** | `0x13CD` | `eERC_REQUEST_TRADE_REQ` | **C → S** | `—` | `commerce.py` | `RequestTradeReq` (Opcode 5069: eERC_REQUEST_TRADE_REQ.) |
| **5070** | `0x13CE` | `eERC_REQUEST_TRADE_ACK` | **C → S** | `0x00770E50` | — | `RequestTradeAck` (Opcode 5070: eERC_REQUEST_TRADE_ACK (0x00770E50).) |
| **5071** | `0x13CF` | `eERC_ACCEPT_REQUEST_TRADE_REQ` | **C → S** | `—` | `commerce.py` | `AcceptRequestTradeReq` (Opcode 5071: eERC_ACCEPT_REQUEST_TRADE_REQ.) |
| **5072** | `0x13D0` | `eERC_ACCEPT_REQUEST_TRADE_ACK` | **C → S** | `0x007587B0` | — | `AcceptRequestTradeAck` (Opcode 5072: eERC_ACCEPT_REQUEST_TRADE_ACK (0x007587B0).) |
| **5073** | `0x13D1` | `eERC_CANCEL_TRADE_REQ` | **C → S** | `—` | `commerce.py` | `CancelTradeReq` (Opcode 5073: eERC_CANCEL_TRADE_REQ.) |
| **5074** | `0x13D2` | `eERC_CANCEL_TRADE_ACK` | **S → C** | `0x0077DE00` | — | `CancelTradeAck` (Opcode 5074: eERC_CANCEL_TRADE_ACK (0x0077DE00).) |
| **5075** | `0x13D3` | `eERC_INSERT_TRADE_ITEM_REQ` | **C → S** | `—` | `commerce.py` | `InsertTradeItemReq` (Opcode 5075: eERC_INSERT_TRADE_ITEM_REQ.) |
| **5076** | `0x13D4` | `eERC_INSERT_TRADE_ITEM_ACK` | **S → C** | `0x0077D980` | — | `InsertTradeItemAck` (Opcode 5076: eERC_INSERT_TRADE_ITEM_ACK (0x0077D980).) |
| **5077** | `0x13D5` | `eERC_DELETE_TRADE_ITEM_REQ` | **C → S** | `—` | `commerce.py` | `DeleteTradeItemReq` (Opcode 5077: eERC_DELETE_TRADE_ITEM_REQ.) |
| **5078** | `0x13D6` | `eERC_DELETE_TRADE_ITEM_ACK` | **S → C** | `0x0077DBB0` | — | `DeleteTradeItemAck` (Opcode 5078: eERC_DELETE_TRADE_ITEM_ACK (0x0077DBB0).) |
| **5079** | `0x13D7` | `eERC_UPDATE_TRADE_AR_REQ` | **C → S** | `—` | `commerce.py` | `UpdateTradeArReq` (Opcode 5079: eERC_UPDATE_TRADE_AR_REQ.) |
| **5080** | `0x13D8` | `eERC_UPDATE_TRADE_AR_ACK` | **S → C** | `0x00758940` | — | `UpdateTradeArAck` (Opcode 5080: eERC_UPDATE_TRADE_AR_ACK (0x00758940).) |
| **5081** | `0x13D9` | `eERC_ACCEPT_TRADE_REQ` | **C → S** | `—` | `commerce.py` | `AcceptTradeReq` (Opcode 5081: eERC_ACCEPT_TRADE_REQ.) |
| **5082** | `0x13DA` | `eERC_ACCEPT_TRADE_ACK` | **S → C** | `0x0078EB40` | — | `AcceptTradeAck` (Opcode 5082: eERC_ACCEPT_TRADE_ACK (0x0078EB40).) |
| **5083** | `0x13DB` | `eERC_FINALLY_ACCEPT_TRADE_REQ` | **C → S** | `—` | `commerce.py` | `FinallyAcceptTradeReq` (Opcode 5083: eERC_FINALLY_ACCEPT_TRADE_REQ.) |
| **5084** | `0x13DC` | `eERC_FINALLY_ACCEPT_TRADE_ACK` | **S → C** | `—` | — | `FinallyAcceptTradeAck` (Opcode 5084: eERC_FINALLY_ACCEPT_TRADE_ACK.) |

---

## Quests, Missions & Tutorials

| Opcode | Hex | Enum Name | Direction | Client VA | Server Handler | Message Class / Wire Notes |
| :--- | :--- | :--- | :---: | :--- | :--- | :--- |
| **2074** | `0x081A` | `eEGS_QUEST_START_ACK` | **S → C** | `—` | — | `QuestStartAck` (Opcode 2074: eEGS_QUEST_START_ACK (JAppPageTalkBox, case 0x659F00 -> 0x659790).) |
| **2075** | `0x081B` | `eEGS_QUEST_UPDATE_NOT` | **S → C** | `—` | — | `QuestUpdateNot` (Opcode 2075: eEGS_QUEST_UPDATE_NOT (JAppPageQuestDlg::On_eEGS_QUEST_UPDATE_NOT, 0x0061c7e0).) |
| **2077** | `0x081D` | `eEGS_QUEST_COMPLETE_ACK` | **S → C** | `—` | — | `QuestCompleteAck` (Opcode 2077: eEGS_QUEST_COMPLETE_ACK (JAppPageTalkBox, case 0x659F00 -> 0x656870).) |
| **2078** | `0x081E` | `eEGS_QUEST_GIVEUP_REQ` | **C → S** | `—` | — | `QuestGiveupReq` (Opcode 2078: eEGS_QUEST_GIVEUP_REQ.) |
| **2079** | `0x081F` | `eEGS_QUEST_GIVEUP_ACK` | **S → C** | `—` | — | `QuestGiveupAck` (Opcode 2079: eEGS_QUEST_GIVEUP_ACK (0x006223B0).) |
| **2080** | `0x0820` | `eEGS_QUEST_FAIL_REQ` | **C → S** | `—` | — | `QuestFailReq` (Opcode 2080: eEGS_QUEST_FAIL_REQ.) |
| **2081** | `0x0821` | `eEGS_QUEST_FAIL_ACK` | **S → C** | `—` | — | `QuestFailAck` (Opcode 2081: eEGS_QUEST_FAIL_ACK (0x006223B0).) |
| **2083** | `0x0823` | `eEGS_CLEAR_TUTORIAL_ACK` | **S → C** | `0x0077EEB0` | — | `ClearTutorialAck` (Opcode 2083: eEGS_CLEAR_TUTORIAL_ACK response.) |
| **2085** | `0x0825` | `eEGS_CHANGE_DUNGEON_PENALTY_NOT` | **S → C** | `0x0078FA70` | — | `ChangeDungeonPenaltyNot` (Opcode 2085: eEGS_CHANGE_DUNGEON_PENALTY_NOT (0x0078FA70).) |
| **2347** | `0x092B` | `eEGS_TUTORIAL_QUEST_START_ACK` | **S → C** | `—` | — | `TutorialQuestStartAck` (Opcode 2347: eEGS_TUTORIAL_QUEST_START_ACK response.) |

---

## Dungeon Instances, Party, Combat & Monster Spawns

| Opcode | Hex | Enum Name | Direction | Client VA | Server Handler | Message Class / Wire Notes |
| :--- | :--- | :--- | :---: | :--- | :--- | :--- |
| **5001** | `0x1389` | `eERC_CREATE_ROOM_REQ` | **C → S** | `—` | `dungeon.py` | eERC_CREATE_ROOM_REQ (writer 0x58B060): wstring name, i32, i32, i16, i16 (observed: "_singleplay", -1, -1, -1, 1) -> 5002 CREATE_ROOM_ACK. |
| **5002** | `0x138A` | `eERC_CREATE_ROOM_ACK` | **S → C** | `—` | — | `CreateRoomAck` (Opcode 5002: eERC_CREATE_ROOM_ACK (JAppPageGameRoom, table case 0x59D970 -> 0x5984D0).) |
| **5005** | `0x138D` | `eERC_LEAVE_ROOM_REQ` | **C → S** | `—` | `dungeon.py` | `LeaveRoomReq` (Opcode 5005: eERC_LEAVE_ROOM_REQ (0x0058B240).) |
| **5006** | `0x138E` | `eERC_LEAVE_ROOM_ACK` | **S → C** | `—` | — | `LeaveRoomAck` (Opcode 5006: eERC_LEAVE_ROOM_ACK (0x00598A00).) |
| **5009** | `0x1391` | `eERC_CHANGE_MAPCODE_REQ` | **C → S** | `—` | `dungeon.py` | eERC_CHANGE_MAPCODE_REQ (sender 0x7AD680), observed body: ffffff7f + J-wstring map code ("Act1_G1_A10") + bool -> 5010, consumed by JAppStateDungeonGate vf20 -> 0x6D4A00 (only in app state 8). |
| **5010** | `0x1392` | `eERC_CHANGE_MAPCODE_ACK` | **S → C** | `—` | — | `ChangeMapCodeAck` (Opcode 5010: eERC_CHANGE_MAPCODE_ACK (JAppStateDungeonGate vf20 -> 0x006D4A00).) |
| **5013** | `0x1395` | `eERC_START_GAME_REQ` | **C → S** | `—` | `dungeon.py` | eERC_START_GAME_REQ -> eERC_START_GAME_ACK (5014), handler 0x7880A0. Success reader: u16, u32, J-wstring (0xB35AB0), three 0x17 maps, then a 0x10 vector (0x78836B -> 0x4B94C0). Scalar/string type codes are not wire tags; empty lengths use the terminal byte 0x80. The J-wstring is the map code: 0x788539 resolves it with 0x98E630 |
| **5014** | `0x1396` | `eERC_START_GAME_ACK` | **S → C** | `0x007880A0` | — | — |
| **5015** | `0x1397` | `eERC_CHANGE_TEAM_REQ` | **C → S** | `—` | `dungeon.py` | `ChangeTeamReq` (Opcode 5015: eERC_CHANGE_TEAM_REQ.) |
| **5016** | `0x1398` | `eERC_CHANGE_TEAM_ACK` | **S → C** | `—` | — | `ChangeTeamAck` (Opcode 5016: eERC_CHANGE_TEAM_ACK.) |
| **5017** | `0x1399` | `eERC_FINISH_GAME_REQ` | **C → S** | `—` | `dungeon.py` | `FinishGameReq` (Opcode 5017: eERC_FINISH_GAME_REQ (sender 0x007AD380).) |
| **5018** | `0x139A` | `eERC_FINISH_GAME_ACK` | **S → C** | `0x007ADB60` | — | `FinishGameAck` (Opcode 5018: eERC_FINISH_GAME_ACK (handler 0x007ADB60).) |
| **5021** | `0x139D` | `eERC_USER_JOIN_SQUARE_NOT` | **S → C** | `—` | `world.py` | `UserJoinSquareNot`: spatial presence broadcast when player enters town square |
| **5022** | `0x139E` | `eERC_USER_LEAVE_SQUARE_NOT` | **S → C** | `—` | `world.py` | `UserLeaveSquareNot`: presence broadcast when player leaves square or disconnects |
| **5027** | `0x13A3` | `eERC_JOIN_LAYER_NOT` | **S → C** | `0x00787790` | — | — |
| **5029** | `0x13A5` | `eERC_JOIN_SQUARE_ACK` | **S → C** | `0x00757AD0` | — | `JoinSquareAck` (Opcode 5029: eERC_JOIN_SQUARE_ACK response.) |
| **5030** | `0x13A6` | `eERC_USER_MOVE_NOT` | **C → S** | `—` | `square.py` | `UserMoveNot`: town square movement updates decoded and broadcast to peers |
| **5031** | `0x13A7` | `eERC_JOIN_LAYER_ACK / eERC_USER_MOVE_NOT` | **S → C** | `0x00787A70` | `square.py` | `UserMoveNot` / `BackToSquareAck`: spatial movement broadcast to square occupants |
| **5033** | `0x13A9` | `eERC_LEAVE_SQUARE_ACK` | **S → C** | `0x00757960` | `square.py` | Clears player from world square presence |
| **5038** | `0x13AE` | `eERC_LEAVE_LAYER_ACK` | **S → C** | `0x007895C0` | `square.py` | Clears player from world layer presence |
| **5039** | `0x13AF` | `eERC_LEAVE_LAYER_NOT` | **S → C** | `0x00789450` | — | — |
| **5040** | `0x13B0` | `eERC_CHAT_REQ` | **C → S** | `—` | `social.py` | `ChatReq` (Opcode 5040: eERC_CHAT_REQ (0x007AC5E0).) |
| **5041** | `0x13B1` | `eERC_CHAT_ACK` | **S → C** | `0x007AC890` | — | `ChatAck` (Opcode 5041: eERC_CHAT_ACK (0x007AC890).) |
| **5043** | `0x13B3` | `eERC_SELECT_DUNGEON_REQ` | **C → S** | `—` | `dungeon.py` | eERC_SELECT_DUNGEON_REQ (sender 0x7AC1C0), observed body: ffffff7f + J-wstring gate id ("Act1_G1") -> 5044. |
| **5044** | `0x13B4` | `eERC_SELECT_DUNGEON_ACK` | **S → C** | `0x007702E0` | — | `SelectDungeonAck` (Opcode 5044: eERC_SELECT_DUNGEON_ACK (JUserClient handler 0x007702E0).) |
| **5045** | `0x13B5` | `eERC_BACK_TO_SQUARE_REQ` | **C → S** | `—` | `dungeon.py` | eERC_BACK_TO_SQUARE_REQ (0x007A0000.c:8367) -> 5046 eERC_BACK_TO_SQUARE_ACK (0x007897F0). Return to town/square from dungeon. |
| **5046** | `0x13B6` | `eERC_BACK_TO_SQUARE_ACK` | **S → C** | `0x007897F0` | — | `BackToSquareAck` (Opcode 5046: eERC_BACK_TO_SQUARE_ACK response.) |
| **5049** | `0x13B9` | `eERC_INVITE_REQ` | **C → S** | `—` | `social.py` | `PartyInviteReq` (Opcode 5049: party invitation request via UID/name) |
| **5050** | `0x13BA` | `eERC_INVITE_ACK` | **S → C** | `0x00758700` | — | `PartyInviteAck` (Opcode 5050: party invitation ack) |
| **5051** | `0x13BB` | `eERC_INVITE_NOT` | **S → C** | `0x007706E0` | `social.py` | `PartyInviteNot`: notification delivered to target player with inviter info |
| **5053** | `0x13BD` | `eERC_AGAIN_SELECT_DUNGEON_ACK` | **S → C** | `0x00770A80` | — | — |
| **5054** | `0x13BE` | `eERC_ACCEPT_INVITE_REQ` | **C → S** | `—` | `social.py` | `PartyAcceptInviteReq` (Opcode 5054: accept party invitation) |
| **5055** | `0x13BF` | `eERC_ACCEPT_INVITE_ACK` | **S → C** | `—` | — | `PartyAcceptInviteAck` (Opcode 5055: accept party invitation ack) |
| **5056** | `0x13C0` | `eERC_ACCEPT_INVITE_NOT` | **S → C** | `—` | `social.py` | `PartyAcceptInviteNot`: broadcast to party members when a new member joins |
| **5061** | `0x13C5` | `eERC_ROOM_MEM_INFO_ACK` | **S → C** | `0x0076BC60` | — | — |
| **5063** | `0x13C7` | `eERC_MONSTER_DEAD_REQ` | **C → S** | `—` | `dungeon.py` | `MonsterDeadReq` (Opcode 5063: eERC_MONSTER_DEAD_REQ (JUserClient::MonsterDeadREQ 0x0078A690).) |
| **5064** | `0x13C8` | `eERC_DROP_ITEM_NOT` | **S → C** | `0x0078A870` | — | `DropItemNot` (Opcode 5064: eERC_DROP_ITEM_NOT (JUserClient::On_eERC_DROP_ITEM_NOT 0x0078A870).) |
| **5065** | `0x13C9` | `eERC_PICK_UP_ITEM_REQ` | **C → S** | `—` | `dungeon.py` | `PickUpItemReq` (Opcode 5065: eERC_PICK_UP_ITEM_REQ (JUserClient::PickUpItemREQ, push at 0x0078AC3F).) |
| **5066** | `0x13CA` | `eERC_PICK_UP_ITEM_ACK` | **S → C** | `—` | — | `PickUpItemAck` (Opcode 5066: eERC_PICK_UP_ITEM_ACK.) |
| **5068** | `0x13CC` | `eERC_PICK_UP_ITEM_RESULT_ACK` | **S → C** | `0x0078AD80` | — | `PickUpItemResultAck` (Opcode 5068: eERC_PICK_UP_ITEM_RESULT_ACK (global handler 0x0078AD80).) |
| **5085** | `0x13DD` | `eERC_CANCEL_ACCEPT_TRADE_NOT` | **S → C** | `0x00758A70` | — | — |
| **5086** | `0x13DE` | `eERC_CHANGE_EXP_NOT` | **S → C** | `0x0078D170` | — | `ChangeExpNot` (Opcode 5086: eERC_CHANGE_EXP_NOT (On_eERC_CHANGE_EXP_NOT 0x0078D170).) |
| **5087** | `0x13DF` | `eERC_LEVEL_UP_NOT` | **S → C** | `0x0078CCF0` | — | `LevelUpNot` (Opcode 5087: eERC_LEVEL_UP_NOT (On_eERC_LEVEL_UP_NOT 0x0078CCF0).) |
| **5090** | `0x13E2` | `eERC_CHOICE_REWARD_PARTYRANK_REQ` | **C → S** | `—` | `dungeon.py` | `ChoiceRewardPartyRankReq` (Opcode 5090: eERC_CHOICE_REWARD_PARTYRANK_REQ (0x00780000.c:9280).) |
| **5091** | `0x13E3` | `eERC_CHOICE_REWARD_PARTYRANK_ACK` | **S → C** | `0x0078D660` | — | `ChoiceRewardPartyRankAck` (Opcode 5091: eERC_CHOICE_REWARD_PARTYRANK_ACK (On_opcode_5091 0x0078D660).) |
| **5093** | `0x13E5` | `eERC_GAMEPLAY_DIE_CHAR_REQ` | **C → S** | `—` | `dungeon.py` | `GameplayDieCharReq` (Opcode 5093: eERC_GAMEPLAY_DIE_CHAR_REQ (writer 0x0078EDF0).) |
| **5094** | `0x13E6` | `eERC_GAMEPLAY_DIE_CHAR_ACK` | **S → C** | `0x0078F090` | — | `GameplayDieCharAck` (Opcode 5094: eERC_GAMEPLAY_DIE_CHAR_ACK (handler 0x0078F090, assembly-checked).) |
| **5095** | `0x13E7` | `eERC_CHANGE_DUNGEON_LAYER_NOT` | **S → C** | `—` | `dungeon.py` | `ChangeDungeonLayerNot` (Opcode 5095: eERC_CHANGE_DUNGEON_LAYER_NOT (JAppStateGamePlay::Initialize -> 0x007900B0).) |
| **5096** | `0x13E8` | `eERC_UPDATE_CHAR_INFO_NOT` | **S → C** | `0x0078C990` | — | `UpdateCharInfoNot` (Opcode 5096: eERC_UPDATE_CHAR_INFO_NOT (0x0078C990).) |
| **5097** | `0x13E9` | `eERC_DUEL_START_REQ` | **C → S** | `—` | — | `DuelStartReq` (Opcode 5097 (eERC_DUEL_START_REQ): Both players accept and start the duel.) |
| **5098** | `0x13EA` | `eERC_DUEL_START_ACK` | **S → C** | `—` | — | `DuelStartAck` (Opcode 5098 (eERC_DUEL_START_ACK): Server acknowledges duel combat initialization.) |
| **5099** | `0x13EB` | `eERC_DUEL_START_NOT` | **S → C** | `—` | — | `DuelStartNot` (Opcode 5099 (eERC_DUEL_START_NOT): Notification to players that duel countdown begins.) |
| **5100** | `0x13EC` | `eERC_DUEL_REQUEST_REQ` | **C → S** | `—` | — | `DuelRequestReq` (Opcode 5100 (eERC_DUEL_REQUEST_REQ): Challenger requests a duel.) |
| **5101** | `0x13ED` | `eERC_DUEL_REQUEST_ACK` | **C → S** | `—` | — | `DuelRequestAck` (Opcode 5101 (eERC_DUEL_REQUEST_ACK): Server confirms duel request to challenger.) |
| **5105** | `0x13F1` | `eERC_DUEL_RESULT_REQ` | **C → S** | `—` | — | `DuelResultReq` (Opcode 5105 (eERC_DUEL_RESULT_REQ): Duel match outcome reported.) |
| **5106** | `0x13F2` | `eERC_DUEL_RESULT_ACK` | **S → C** | `—` | — | `DuelResultAck` (Opcode 5106 (eERC_DUEL_RESULT_ACK): Duel outcome confirmed.) |
| **5108** | `0x13F4` | `eERC_DUEL_GIVEUP_NOT` | **S → C** | `—` | — | `DuelGiveupNot` (Opcode 5108 (eERC_DUEL_GIVEUP_NOT): Player surrenders duel match.) |
| **5112** | `0x13F8` | `eERC_DUEL_REFUSE_REQ` | **C → S** | `—` | — | `DuelRefuseReq` (Opcode 5112 (eERC_DUEL_REFUSE_REQ): Target player declines the duel challenge.) |
| **5113** | `0x13F9` | `eERC_DUEL_REFUSE_ACK` | **S → C** | `—` | — | `DuelRefuseAck` (Opcode 5113 (eERC_DUEL_REFUSE_ACK): Server notifies challenger that duel was declined.) |
| **5114** | `0x13FA` | `eERC_GET_DROP_AR_NOT` | **S → C** | `0x00792700` | — | `GetDropArNot` (Opcode 5114: eERC_GET_DROP_AR_NOT (0x00792700).) |
| **5117** | `0x13FD` | `eERC_CHEAT_VIEW_ITEM_DROP_LOG_NOT` | **S → C** | `0x00758E20` | — | — |
| **5118** | `0x13FE` | `eERC_FRIEND_MY_CONNECTION_NOT` | **S → C** | `0x0077A8A0` | — | `FriendMyConnectionNot` (Opcode 5118: eERC_FRIEND_MY_CONNECTION_NOT (0x0077A8A0).) |
| **5119** | `0x13FF` | `eERC_FRIEND_MY_DISCONNECTION_NOT` | **S → C** | `0x00758FA0` | — | `FriendMyDisconnectionNot` (Opcode 5119: eERC_FRIEND_MY_DISCONNECTION_NOT (0x00758FA0).) |
| **5121** | `0x1401` | `eERC_GUILD_CREATE_PROPOSAL_REQ` | **C → S** | `—` | `social.py` | eERC_GUILD_CREATE_PROPOSAL_REQ (0x00790000.c:2514) -> 5122 eERC_GUILD_CREATE_PROPOSAL_ACK (0x00759750). |
| **5122** | `0x1402` | `eERC_GUILD_CREATE_PROPOSAL_ACK` | **S → C** | `0x00759750` | — | `GuildCreateProposalAck` (Opcode 5122: eERC_GUILD_CREATE_PROPOSAL_ACK (On_eERC_GUILD_CREATE_PROPOSAL_ACK 0x00759750).) |
| **5123** | `0x1403` | `eERC_GUILD_CREATE_COMPLETE_NOT` | **S → C** | `0x00759E10` | — | — |
| **5125** | `0x1405` | `eERC_GTARGET_LIST_ACK` | **S → C** | `—` | — | `GTargetListAck` (Opcode 5125: eERC_GTARGET_LIST_ACK (case in dispatcher 0x00874550 -> 0x00873490).) |
| **5127** | `0x1407` | `eERC_CURRENT_GUILD_SKILL_NOT` | **S → C** | `0x00794CE0` | — | — |
| **5134** | `0x140E` | `eERC_SQUARE_CHANGE_RELAY_ADDRESS_NOT` | **S → C** | `0x0075AAE0` | — | `RelayAddressNot` (Opcode 5134: eERC_SQUARE_CHANGE_RELAY_ADDRESS_NOT notification.) |
| **5135** | `0x140F` | `eERC_ARENA_SQUARE_CHANGE_RELAY_ADDRESS_NOT` | **S → C** | `0x0075AC00` | — | — |
| **5136** | `0x1410` | `eERC_FAIL_DUNGEON_ENTER_ITEM_NOT` | **S → C** | `0x00797550` | — | — |
| **5138** | `0x1412` | `eERC_ARENA_JOIN_SQUARE_ACK` | **S → C** | `—` | — | `ArenaJoinSquareAck` (Opcode 5138 (eERC_ARENA_JOIN_SQUARE_ACK): Connect to arena town channel.) |
| **5222** | `0x1466` | `eERC_FAIL_DUNGEON_ENTER_LIMIT_NOT` | **S → C** | `0x00798B30` | — | — |
| **5237** | `0x1475` | `eERC_TRAINING_JOIN_ROOM_ACK` | **S → C** | `0x0075AEC0` | — | — |
| **5239** | `0x1477` | `eERC_TRAINING_LEAVE_ROOM_ACK` | **S → C** | `0x0074B830` | — | — |
| **5241** | `0x1479` | `eERC_MONSTER_REGEN_ACK` | **S → C** | `0x0074B830` | — | — |
| **5256** | `0x1488` | `eERC_SECOND_PASS_CREATE_REQ` | **C → S** | `—` | `social.py` | `SecondPassCreateReq` (Opcode 5256: eERC_SECOND_PASS_CREATE_REQ.) |
| **5257** | `0x1489` | `eERC_SECOND_PASS_CREATE_ACK` | **S → C** | `0x0075B020` | — | `SecondPassCreateAck` (Opcode 5257: eERC_SECOND_PASS_CREATE_ACK (0x0075B020).) |
| **5258** | `0x148A` | `eERC_SECOND_PASS_MODIFY_REQ` | **C → S** | `—` | `social.py` | `SecondPassModifyReq` (Opcode 5258: eERC_SECOND_PASS_MODIFY_REQ.) |
| **5259** | `0x148B` | `eERC_SECOND_PASS_MODIFY_ACK` | **S → C** | `0x0075B050` | — | `SecondPassModifyAck` (Opcode 5259: eERC_SECOND_PASS_MODIFY_ACK (0x0075B050).) |
| **5260** | `0x148C` | `eERC_SECOND_PASS_AUTH_REQ` | **C → S** | `—` | `social.py` | `SecondPassAuthReq` (Opcode 5260: eERC_SECOND_PASS_AUTH_REQ.) |
| **5261** | `0x148D` | `eERC_SECOND_PASS_AUTH_ACK` | **S → C** | `0x0075B080` | — | `SecondPassAuthAck` (Opcode 5261: eERC_SECOND_PASS_AUTH_ACK (0x0075B080).) |
| **5269** | `0x1495` | `eERC_ARENA_TEAM_CREATE_REQ` | **C → S** | `—` | — | `ArenaTeamCreateReq` (Opcode 5269 / 2452 (eERC_ARENA_TEAM_CREATE_REQ): Create an arena PvP team.) |
| **5270** | `0x1496` | `eERC_ARENA_TEAM_CREATE_ACK` | **S → C** | `—` | — | `ArenaTeamCreateAck` (Opcode 5270 / 2453 (eERC_ARENA_TEAM_CREATE_ACK): Arena team created.) |
| **5271** | `0x1497` | `eERC_ARENA_TEAM_JOIN_REQ` | **C → S** | `—` | — | `ArenaTeamJoinReq` (Opcode 5271 / 2454 (eERC_ARENA_TEAM_JOIN_REQ): Join existing arena team.) |
| **5272** | `0x1498` | `eERC_ARENA_TEAM_JOIN_ACK` | **S → C** | `—` | — | `ArenaTeamJoinAck` (Opcode 5272 / 2455 (eERC_ARENA_TEAM_JOIN_ACK): Joined arena team.) |
| **5274** | `0x149A` | `eERC_ARENA_TEAM_LEAVE_REQ` | **C → S** | `—` | — | `ArenaTeamLeaveReq` (Opcode 5274 / 2456 (eERC_ARENA_TEAM_LEAVE_REQ): Leave arena team.) |
| **5275** | `0x149B` | `eERC_ARENA_TEAM_LEAVE_ACK` | **S → C** | `—` | — | `ArenaTeamLeaveAck` (Opcode 5275 / 2457 (eERC_ARENA_TEAM_LEAVE_ACK): Confirms departure from arena team.) |
| **5323** | `0x14CB` | `eERC_PET_LEVEL_UP_NOT` | **S → C** | `0x007754E0` | — | — |
| **5324** | `0x14CC` | `eERC_PET_CHANGE_EXP_NOT` | **S → C** | `0x0079EFA0` | — | — |
| **5326** | `0x14CE` | `eERC_FAIL_DUNGEON_HACKDOUBT_NOT` | **S → C** | `0x007A1340` | — | — |
| **5343** | `0x14DF` | `eERC_TREASURE_FIND_ACK` | **S → C** | `0x00782A80` | — | — |
| **5344** | `0x14E0` | `eERC_TREASURE_START_NOT` | **S → C** | `0x007722F0` | — | `TreasureStartNot` (Opcode 5344: eERC_TREASURE_START_NOT (0x007722F0).) |
| **5345** | `0x14E1` | `eERC_TREASURE_END_NOT` | **S → C** | `0x0075BC00` | — | `TreasureEndNot` (Opcode 5345: eERC_TREASURE_END_NOT (0x0075BC00).) |
| **5346** | `0x14E2` | `eERC_CITADEL_REWARD_NOT` | **S → C** | `0x007833F0` | — | `CitadelRewardNot` (Opcode 5346: eERC_CITADEL_REWARD_NOT (0x007833F0).) |
| **5351** | `0x14E7` | `eERC_REQUEST_TEACHING_REQ` | **C → S** | `—` | `social.py` | `RequestTeachingReq` (Opcode 5351: eERC_REQUEST_TEACHING_REQ.) |
| **5352** | `0x14E8` | `eERC_REQUEST_TEACHING_ACK` | **C → S** | `0x0075C200` | — | `RequestTeachingAck` (Opcode 5352: eERC_REQUEST_TEACHING_ACK (0x0075C200).) |
| **5353** | `0x14E9` | `eERC_ACCEPT_REQUEST_TEACHING_REQ` | **C → S** | `—` | `social.py` | `AcceptRequestTeachingReq` (Opcode 5353: eERC_ACCEPT_REQUEST_TEACHING_REQ.) |
| **5354** | `0x14EA` | `eERC_ACCEPT_REQUEST_TEACHING_ACK` | **C → S** | `0x0075C430` | — | `AcceptRequestTeachingAck` (Opcode 5354: eERC_ACCEPT_REQUEST_TEACHING_ACK (0x0075C430).) |
| **5355** | `0x14EB` | `eERC_TEACHING_GET_INFO_NOT` | **S → C** | `0x007A5890` | — | `TeachingGetInfoNot` (Opcode 5355: eERC_TEACHING_GET_INFO_NOT (0x007A5890).) |
| **5357** | `0x14ED` | `eERC_TEACHING_SUMMON_ACCEPT_ACK` | **S → C** | `0x0077B780` | — | — |
| **5362** | `0x14F2` | `eERC_GOLDGOBLIEN_APPEAR_NOT` | **S → C** | `0x007A6D10` | — | `GoldGoblinAppearNot` (Opcode 5362: eERC_GOLDGOBLIEN_APPEAR_NOT (0x007A6D10).) |
| **5363** | `0x14F3` | `eERC_GOLDGOBLIEN_ATTACK_REQ` | **C → S** | `—` | `dungeon.py` | `GoldGoblinAttackReq` (Opcode 5363: eERC_GOLDGOBLIEN_ATTACK_REQ.) |
| **5364** | `0x14F4` | `eERC_GOLDGOBLIEN_ATTACK_ACK` | **S → C** | `0x00784A10` | — | `GoldGoblinAttackAck` (Opcode 5364: eERC_GOLDGOBLIEN_ATTACK_ACK (0x00784A10).) |
| **5365** | `0x14F5` | `eERC_GOLDGOBLIEN_DEAD_REQ` | **C → S** | `—` | `dungeon.py` | `GoldGoblinDeadReq` (Opcode 5365: eERC_GOLDGOBLIEN_DEAD_REQ.) |
| **5366** | `0x14F6` | `eERC_GOLDGOBLIEN_DEAD_ACK` | **S → C** | `0x00784CA0` | — | `GoldGoblinDeadAck` (Opcode 5366: eERC_GOLDGOBLIEN_DEAD_ACK (0x00784CA0).) |

---

## PvP Arena, Duel Matches & Ranked League

| Opcode | Hex | Enum Name | Direction | Client VA | Server Handler | Message Class / Wire Notes |
| :--- | :--- | :--- | :---: | :--- | :--- | :--- |
| **2306** | `0x0902` | `eEGS_ARENA_GET_ROOMLIST_REQ` | **C → S** | `—` | — | `ArenaGetRoomListReq` (Opcode 2306 / 2448 (eEGS_ARENA_GET_ROOMLIST_REQ): Request arena rooms list.) |
| **2307** | `0x0903` | `eEGS_ARENA_GET_ROOMLIST_ACK` | **S → C** | `—` | — | `ArenaGetRoomListAck` (Opcode 2307 / 2449 (eEGS_ARENA_GET_ROOMLIST_ACK): List of open arena match rooms.) |
| **2446** | `0x098E` | `eEGS_ACHIEVE_DIV_UPDATE_REQ` | **C → S** | `—` | `social.py` | eEGS_ACHIEVE_DIV_UPDATE_REQ: tag 0x17 map of achievement progress (live: 17 84 0f 0e000000 05000000 00000000 ...; entry layout not recovered, recorded only) -> 2447 (0x0074B830 reads only the u32 result). |
| **2447** | `0x098F` | `eEGS_ACHIEVE_DIV_UPDATE_ACK` | **S → C** | `0x0074B830` | — | — |
| **2448** | `0x0990` | `eEGS_DAILY_REBIRTH_COIN_USE_REQ` | **C → S** | `—` | `dungeon.py` | `DailyRebirthCoinUseReq` (Opcode 2448: eEGS_DAILY_REBIRTH_COIN_USE_REQ (sender 0x0079D9xx): i32 prefix + bool.) |
| **2449** | `0x0991` | `eEGS_DAILY_REBIRTH_COIN_USE_ACK` | **S → C** | `0x0079DC70` | — | `DailyRebirthCoinUseAck` (Opcode 2449: eEGS_DAILY_REBIRTH_COIN_USE_ACK (On_eEGS_DAILY_REBIRTH_COIN_USE_ACK 0x0079DC70).) |
| **2452** | `0x0994` | `eEGS_GUILD_SIEGE_CHANGE_OFFICER_NOT` | **S → C** | `0x00753B90` | — | — |
| **2454** | `0x0996` | `eEGS_GUILD_PERSON_SIEGE_TEAMIDX_MODIFY_ACK` | **S → C** | `0x0077C550` | — | — |
| **2455** | `0x0997` | `eEGS_GUILD_PERSON_SIEGE_TEAMIDX_MODIFY_NOT` | **S → C** | `0x0077C860` | — | — |
| **2456** | `0x0998` | `eEGS_GUILD_UPDATE_SIEGEINFO_NOT` | **S → C** | `0x0077C370` | — | — |
| **5145** | `0x1419` | `eERC_ARENA_JOIN_ROOM_REQ` | **C → S** | `—` | — | `ArenaJoinRoomReq` (Opcode 5145 (eERC_ARENA_JOIN_ROOM_REQ): Player requests joining match room.) |
| **5146** | `0x141A` | `eERC_ARENA_JOIN_ROOM_ACK` | **S → C** | `—` | — | `ArenaJoinRoomAck` (Opcode 5146 (eERC_ARENA_JOIN_ROOM_ACK): Confirms joining match room.) |
| **5148** | `0x141C` | `eERC_ARENA_LEAVE_ROOM_REQ` | **C → S** | `—` | — | `ArenaLeaveRoomReq` (Opcode 5148 (eERC_ARENA_LEAVE_ROOM_REQ): Leave arena room.) |
| **5149** | `0x141D` | `eERC_ARENA_LEAVE_ROOM_ACK` | **S → C** | `—` | — | `ArenaLeaveRoomAck` (Opcode 5149 (eERC_ARENA_LEAVE_ROOM_ACK): Confirm room departure.) |
| **5153** | `0x1421` | `eERC_ARENA_CREATE_ROOM_REQ` | **C → S** | `—` | — | `ArenaCreateRoomReq` (Opcode 5153 (eERC_ARENA_CREATE_ROOM_REQ): Client creates match room.) |
| **5154** | `0x1422` | `eERC_ARENA_CREATE_ROOM_ACK` | **S → C** | `—` | — | `ArenaCreateRoomAck` (Opcode 5154 (eERC_ARENA_CREATE_ROOM_ACK): Room creation response.) |
| **5165** | `0x142D` | `eERC_ARENA_BACK_TO_SQUARE_REQ` | **C → S** | `—` | `social.py` | `ArenaBackToSquareReq` (Opcode 5165: eERC_ARENA_BACK_TO_SQUARE_REQ.) |
| **5166** | `0x142E` | `eERC_ARENA_BACK_TO_SQUARE_ACK` | **S → C** | `0x00758550` | — | `ArenaBackToSquareAck` (Opcode 5166: eERC_ARENA_BACK_TO_SQUARE_ACK (0x00758550).) |

---

## Social, Guilds, Mentoring, Chat & Remote Inspection

| Opcode | Hex | Enum Name | Direction | Client VA | Server Handler | Message Class / Wire Notes |
| :--- | :--- | :--- | :---: | :--- | :--- | :--- |
| **2128** | `0x0850` | `eEGS_USE_SPEAKER_ITEM_REQ` | **C → S** | `—` | `social.py` | `UseSpeakerItemReq` (Opcode 2128: eEGS_USE_SPEAKER_ITEM_REQ (0x00790000.c:1992).) |
| **2135** | `0x0857` | `eEGS_FRIEND_LIST_DELETE_REQ` | **C → S** | `—` | `social.py` | `FriendListDeleteReq` (Opcode 2135: eEGS_FRIEND_LIST_DELETE_REQ (0x00790000.c:1824).) |
| **2136** | `0x0858` | `eEGS_FRIEND_LIST_DELETE_ACK` | **S → C** | `0x00759560` | — | `FriendListDeleteAck` (Opcode 2136: eEGS_FRIEND_LIST_DELETE_ACK (On_eEGS_FRIEND_LIST_DELETE_ACK 0x00759560).) |
| **2139** | `0x085B` | `eEGS_FRIEND_LIST_ADD_REQ` | **C → S** | `—` | `social.py` | `FriendListAddReq` (Opcode 2139: eEGS_FRIEND_LIST_ADD_REQ (0x00790000.c:1595).) |
| **2140** | `0x085C` | `eEGS_FRIEND_LIST_ADD_ACK` | **S → C** | `0x007591A0` | — | `FriendListAddAck` (Opcode 2140: eEGS_FRIEND_LIST_ADD_ACK (On_eEGS_FRIEND_LIST_ADD_ACK 0x007591A0).) |
| **2143** | `0x085F` | `eEGS_DURABILITY_CHANGE_REQ` | **C → S** | `—` | `commerce.py` | `DurabilityChangeReq` (Opcode 2143: eEGS_DURABILITY_CHANGE_REQ (0x00790000.c:2049).) |
| **2144** | `0x0860` | `eEGS_DURABILITY_CHANGE_ACK` | **S → C** | `0x00774AE0` | — | `DurabilityChangeAck` (Opcode 2144: eEGS_DURABILITY_CHANGE_ACK (On_eEGS_DURABILITY_CHANGE_ACK 0x00774AE0).) |
| **2145** | `0x0861` | `eEGS_DURABILITY_REPAIR_REQ` | **C → S** | `—` | `inventory.py` | `DurabilityRepairReq` (Opcode 2145: eEGS_DURABILITY_REPAIR_REQ (0x00790000.c:2123).) |
| **2146** | `0x0862` | `eEGS_DURABILITY_REPAIR_ACK` | **S → C** | `0x007930D0` | — | `DurabilityRepairAck` (Opcode 2146: eEGS_DURABILITY_REPAIR_ACK (On_eEGS_DURABILITY_REPAIR_ACK 0x007930D0).) |
| **2150** | `0x0866` | `eEGS_GUILD_CREATE_REQ` | **C → S** | `—` | `social.py` | `GuildCreateReq` (Opcode 2150 (eEGS_GUILD_CREATE_REQ) & 5121 (eERC_GUILD_CREATE_PROPOSAL_REQ).) |
| **2151** | `0x0867` | `eEGS_GUILD_CREATE_ACK` | **S → C** | `0x00793720` | — | `GuildCreateAck` (Opcode 2151: eEGS_GUILD_CREATE_ACK (On_eEGS_GUILD_CREATE_ACK 0x00793720).) |
| **2155** | `0x086B` | `eEGS_GUILD_PERSON_JOIN_REQ` | **C → S** | `—` | `social.py` | `GuildPersonJoinReq` (Opcode 2155: eEGS_GUILD_PERSON_JOIN_REQ (0x00790000.c:2837).) |
| **2156** | `0x086C` | `eEGS_GUILD_PERSON_JOIN_ACK` | **S → C** | `0x0075A220` | — | `GuildPersonJoinAck` (Opcode 2156: eEGS_GUILD_PERSON_JOIN_ACK (On_eEGS_GUILD_PERSON_JOIN_ACK 0x0075A220).) |
| **2157** | `0x086D` | `eEGS_GUILD_INFO_NOT` | **S → C** | `0x00752FF0` | — | `GuildInfoNot` (Opcode 2157: eEGS_GUILD_INFO_NOT (0x00752FF0).) |
| **2158** | `0x086E` | `eEGS_GUILD_PERSON_LIST_NOT` | **S → C** | `0x0077ABA0` | — | `GuildPersonListNot` (Opcode 2158: eEGS_GUILD_PERSON_LIST_NOT (0x0077ABA0).) |
| **2159** | `0x086F` | `eEGS_GUILD_HISTORY_NOT` | **S → C** | `0x0077AD40` | — | — |
| **2160** | `0x0870` | `eEGS_GUILD_INVITE_REQ` | **C → S** | `—` | `social.py` | `GuildInviteReq` (Opcode 2160: eEGS_GUILD_INVITE_REQ.) |
| **2161** | `0x0871` | `eEGS_GUILD_INVITE_ACK` | **S → C** | `0x00759870` | — | `GuildInviteAck` (Opcode 2161: eEGS_GUILD_INVITE_ACK (On_eEGS_GUILD_INVITE_ACK 0x00759870).) |
| **2162** | `0x0872` | `eEGS_GUILD_PERSON_LEAVE_REQ` | **C → S** | `—` | `social.py` | `GuildPersonLeaveReq` (Opcode 2162: eEGS_GUILD_PERSON_LEAVE_REQ (0x00790000.c:2761).) |
| **2163** | `0x0873` | `eEGS_GUILD_PERSON_LEAVE_ACK` | **S → C** | `0x00759CA0` | — | `GuildPersonLeaveAck` (Opcode 2163: eEGS_GUILD_PERSON_LEAVE_ACK (On_eEGS_GUILD_PERSON_LEAVE_ACK 0x00759CA0).) |
| **2164** | `0x0874` | `eEGS_GUILD_PERSON_GRADE_MODIFY_REQ` | **C → S** | `—` | `social.py` | `GuildPersonGradeModifyReq` (Opcode 2164: eEGS_GUILD_PERSON_GRADE_MODIFY_REQ.) |
| **2165** | `0x0875` | `eEGS_GUILD_PERSON_GRADE_MODIFY_ACK` | **S → C** | `0x00753170` | — | `GuildPersonGradeModifyAck` (Opcode 2165: eEGS_GUILD_PERSON_GRADE_MODIFY_ACK (0x00753170).) |
| **2167** | `0x0877` | `eEGS_GUILD_FALLOUT_START_ACK` | **S → C** | `0x00759D60` | — | — |
| **2169** | `0x0879` | `eEGS_GUILD_FALLOUT_STOP_ACK` | **S → C** | `0x0074B830` | — | — |
| **2172** | `0x087C` | `eEGS_GUILD_FALLOUT_COMPLETE_NOT` | **S → C** | `0x00753280` | — | — |
| **2174** | `0x087E` | `eEGS_GUILD_GRADE_DELEGATION_ACK` | **S → C** | `0x0074B830` | — | — |
| **2176** | `0x0880` | `eEGS_GUILD_PERSON_EXPULSION_ACK` | **S → C** | `0x0074B830` | — | — |
| **2179** | `0x0883` | `eEGS_GUILD_MONEY_IN_REQ` | **C → S** | `—` | `social.py` | `GuildMoneyInReq` (Opcode 2179: eEGS_GUILD_MONEY_IN_REQ (0x00790000.c:3031).) |
| **2180** | `0x0884` | `eEGS_GUILD_MONEY_IN_ACK` | **S → C** | `0x00794250` | — | `GuildMoneyInAck` (Opcode 2180: eEGS_GUILD_MONEY_IN_ACK (On_eEGS_GUILD_MONEY_IN_ACK 0x00794250).) |
| **2181** | `0x0885` | `eEGS_GUILD_MONEY_OUT_REQ` | **C → S** | `—` | `social.py` | `GuildMoneyOutReq` (Opcode 2181: eEGS_GUILD_MONEY_OUT_REQ (0x00790000.c:3141).) |
| **2182** | `0x0886` | `eEGS_GUILD_MONEY_OUT_ACK` | **S → C** | `0x00794470` | — | `GuildMoneyOutAck` (Opcode 2182: eEGS_GUILD_MONEY_OUT_ACK (On_eEGS_GUILD_MONEY_OUT_ACK 0x00794470).) |
| **2183** | `0x0887` | `eEGS_GUILD_LEVEL_UP_REQ` | **C → S** | `—` | `social.py` | `GuildLevelUpReq` (Opcode 2183: eEGS_GUILD_LEVEL_UP_REQ (0x00790000.c:3250).) |
| **2184** | `0x0888` | `eEGS_GUILD_LEVEL_UP_ACK` | **S → C** | `0x00753380` | — | `GuildLevelUpAck` (Opcode 2184: eEGS_GUILD_LEVEL_UP_ACK (On_eEGS_GUILD_LEVEL_UP_ACK 0x00753380).) |
| **2185** | `0x0889` | `eEGS_GUILD_NOTICE_MODIFY_REQ` | **C → S** | `—` | `social.py` | `GuildNoticeModifyReq` (Opcode 2185: eEGS_GUILD_NOTICE_MODIFY_REQ (0x00790000.c:3278).) |
| **2186** | `0x088A` | `eEGS_GUILD_NOTICE_MODIFY_ACK` | **S → C** | `0x0075A120` | — | `GuildNoticeModifyAck` (Opcode 2186: eEGS_GUILD_NOTICE_MODIFY_ACK (On_eEGS_GUILD_NOTICE_MODIFY_ACK 0x0075A120).) |
| **2188** | `0x088C` | `eEGS_GUILD_NOTICE_DELETE_REQ` | **C → S** | `—` | `social.py` | `GuildNoticeDeleteReq` (Opcode 2188: eEGS_GUILD_NOTICE_DELETE_REQ (0x00790000.c:3388).) |
| **2189** | `0x088D` | `eEGS_GUILD_NOTICE_DELETE_ACK` | **S → C** | `0x0074B830` | — | `GuildNoticeDeleteAck` (Opcode 2189: eEGS_GUILD_NOTICE_DELETE_ACK (On_eEGS_GUILD_NOTICE_DELETE_ACK 0x0074B830).) |
| **2191** | `0x088F` | `eEGS_GUILD_DISMISSAL_START_ACK` | **S → C** | `0x0074B830` | — | — |
| **2193** | `0x0891` | `eEGS_GUILD_DISMISSAL_STOP_ACK` | **S → C** | `0x0074B830` | — | — |
| **2196** | `0x0894` | `eEGS_RANDOMBOX_RESULT_ITEM_NOT` | **S → C** | `0x0075A2E0` | — | `RandomboxResultItemNot` (Opcode 2196: eEGS_RANDOMBOX_RESULT_ITEM_NOT (0x0075A2E0).) |
| **2198** | `0x0896` | `eEGS_CHEAT_GUILD_ADD_POINT_ACK` | **S → C** | `0x0074B820` | — | — |
| **2200** | `0x0898` | `eEGS_CHEAT_GUILD_LEVEL_ACK` | **S → C** | `0x00753490` | — | — |
| **2203** | `0x089B` | `eEGS_COMPUTER_STAT_NOT` | **S → C** | `—` | `social.py` | eEGS_COMPUTER_STAT_NOT: client hardware report; notification only. |
| **2205** | `0x089D` | `eEGS_GUILD_SKILL_NOT` | **S → C** | `0x00779390` | — | `GuildSkillNot` (Opcode 2205: eEGS_GUILD_SKILL_NOT (0x00779390).) |
| **2207** | `0x089F` | `eEGS_GUILD_LEARN_SKILL_ACK` | **S → C** | `0x0074B820` | — | — |
| **2209** | `0x08A1` | `eEGS_GUILD_SKILL_CHANGE_USE_STATE_ACK` | **S → C** | `0x0074B820` | — | — |
| **2214** | `0x08A6` | `eEGS_GUILD_ALL_SKILL_INIT_REQ` | **C → S** | `—` | `social.py` | `GuildAllSkillInitReq` (Opcode 2214: eEGS_GUILD_ALL_SKILL_INIT_REQ.) |
| **2215** | `0x08A7` | `eEGS_GUILD_ALL_SKILL_INIT_ACK` | **S → C** | `—` | — | `GuildAllSkillInitAck` (Opcode 2215: eEGS_GUILD_ALL_SKILL_INIT_ACK (0x00752D80).) |
| **2216** | `0x08A8` | `eEGS_PLAY_OPTION_UPDATE_REQ` | **C → S** | `—` | `commerce.py` | `PlayOptionUpdateReq` (Opcode 2216: eEGS_PLAY_OPTION_UPDATE_REQ (0x00790000.c:3729).) |
| **6011** | `0x177B` | `eERT_REQUEST_CHAR_INFO_REQ` | **C → S** | `—` | `social.py` | `RequestCharInfoReq` (Opcode 6011: eERT_REQUEST_CHAR_INFO_REQ.) |
| **6012** | `0x177C` | `eERT_REQUEST_CHAR_INFO_ACK` | **C → S** | `0x00790FA0` | — | `RequestCharInfoAck` (Opcode 6012: eERT_REQUEST_CHAR_INFO_ACK (0x00790FA0).) |
| **6015** | `0x177F` | `eERT_GUILD_INVITE_REQ` | **C → S** | `0x00759AB0` | — | — |
| **6016** | `0x1780` | `eERT_GUILD_INVITE_ACK` | **S → C** | `0x00759990` | — | — |
| **6017** | `0x1781` | `eERT_GUILD_PERSON_EXPULSION_COMPLETE_NOT` | **S → C** | `0x0075A000` | — | — |
| **6019** | `0x1783` | `eERT_REFUSE_GUILD_INVITE_NOT` | **S → C** | `0x0075A420` | — | — |
| **6028** | `0x178C` | `eERT_REQUEST_ITEM_INFO_REQ` | **C → S** | `—` | `social.py` | `RequestItemInfoReq` (Opcode 6028: eERT_REQUEST_ITEM_INFO_REQ.) |
| **6029** | `0x178D` | `eERT_REQUEST_ITEM_INFO_ACK` | **C → S** | `0x00766C20` | — | `RequestItemInfoAck` (Opcode 6029: eERT_REQUEST_ITEM_INFO_ACK (0x00766C20).) |

---

## Mailbox & Item Attachment Post System

| Opcode | Hex | Enum Name | Direction | Client VA | Server Handler | Message Class / Wire Notes |
| :--- | :--- | :--- | :---: | :--- | :--- | :--- |
| **2129** | `0x0851` | `eEGS_USE_SPEAKER_ITEM_ACK` | **S → C** | `0x0077F320` | — | `UseSpeakerItemAck` (Opcode 2129: eEGS_USE_SPEAKER_ITEM_ACK (On_eEGS_USE_SPEAKER_ITEM_ACK 0x0077F320).) |
| **2131** | `0x0853` | `eEGS_FRIEND_LIST_REQUEST_REQ` | **C → S** | `—` | `social.py` | eEGS_FRIEND_LIST_REQUEST_REQ -> eEGS_FRIEND_LIST_REQUEST_ACK (2132), handler 0x7712E0: u32 result (0), tag 0x17 map (0x76AE20). Empty map is b'\x17\x00'. |
| **2132** | `0x0854` | `eEGS_FRIEND_LIST_REQUEST_ACK` | **C → S** | `0x007712E0` | — | `FriendListAck` (Opcode 2132: eEGS_FRIEND_LIST_REQUEST_ACK response.) |
| **2133** | `0x0855` | `eEGS_FRIEND_LIST_UPDATE_REQ` | **C → S** | `—` | `social.py` | `FriendListUpdateReq` (Opcode 2133: eEGS_FRIEND_LIST_UPDATE_REQ (0x00790000.c:1735).) |
| **2134** | `0x0856` | `eEGS_FRIEND_LIST_UPDATE_ACK` | **S → C** | `0x00752E80` | — | `FriendListUpdateAck` (Opcode 2134: eEGS_FRIEND_LIST_UPDATE_ACK (On_eEGS_FRIEND_LIST_UPDATE_ACK 0x00752E80).) |
| **2219** | `0x08AB` | `eEGS_POST_REQUEST_LIST_REQ` | **C → S** | `—` | `mail.py` | `PostListReq` (Opcode 2219: eEGS_POST_REQUEST_LIST_REQ (0x007962F0).) |
| **2220** | `0x08AC` | `eEGS_POST_REQUEST_LIST_ACK` | **C → S** | `0x007AEF70` | — | `PostListAck` (Opcode 2220: eEGS_POST_REQUEST_LIST_ACK response.) |
| **2221** | `0x08AD` | `eEGS_POST_SEND_REQ` | **C → S** | `—` | `mail.py` | `PostSendReq` (Opcode 2221: eEGS_POST_SEND_REQ (0x00795D70).) |
| **2222** | `0x08AE` | `eEGS_POST_SEND_ACK` | **S → C** | `0x00795F40` | — | `PostSendAck` (Opcode 2222: eEGS_POST_SEND_ACK (0x00795F40).) |

---

## Pets, Mounts & Monster Taming

| Opcode | Hex | Enum Name | Direction | Client VA | Server Handler | Message Class / Wire Notes |
| :--- | :--- | :--- | :---: | :--- | :--- | :--- |
| **2348** | `0x092C` | `eEGS_TAMEING_MONSTER_INSERT_REQ` | **C → S** | `—` | `pets.py` | `TameingMonsterInsertReq` (Opcode 2348: eEGS_TAMEING_MONSTER_INSERT_REQ (0x00799BA0).) |
| **2349** | `0x092D` | `eEGS_TAMEING_MONSTER_INSERT_ACK` | **S → C** | `0x00771A00` | — | `TamingMonsterInsertAck` (Opcode 2349: eEGS_TAMEING_MONSTER_INSERT_ACK response (0x00771A00).) |
| **2350** | `0x092E` | `eEGS_TAMEING_MONSTER_DELETE_REQ` | **C → S** | `—` | `pets.py` | `TameingMonsterDeleteReq` (Opcode 2350: eEGS_TAMEING_MONSTER_DELETE_REQ (0x00799D30).) |
| **2351** | `0x092F` | `eEGS_TAMEING_MONSTER_DELETE_ACK` | **S → C** | `0x00771BB0` | — | `TamingMonsterDeleteAck` (Opcode 2351: eEGS_TAMEING_MONSTER_DELETE_ACK response (0x00771BB0).) |
| **2434** | `0x0982` | `eEGS_RIDING_GET_LIST_REQ` | **C → S** | `—` | `pets.py` | `RidingGetListReq` (Opcode 2434: eEGS_RIDING_GET_LIST_REQ.) |
| **2435** | `0x0983` | `eEGS_RIDING_GET_LIST_ACK` | **S → C** | `0x0076C5A0` | — | `RidingGetListAck` (Opcode 2435: eEGS_RIDING_GET_LIST_ACK (0x0076C5A0).) |
| **2436** | `0x0984` | `eEGS_RIDING_CHANGE_LIST_NOT` | **S → C** | `0x0079C9A0` | — | — |
| **2437** | `0x0985` | `eEGS_RIDING_RIDE_OBJECT_REQ` | **C → S** | `—` | `pets.py` | `RidingRideObjectReq` (Opcode 2437: eEGS_RIDING_RIDE_OBJECT_REQ (0x0079CE00).) |
| **2438** | `0x0986` | `eEGS_RIDING_RIDE_OBJECT_ACK` | **S → C** | `0x00753A90` | — | `RidingRideObjectAck` (Opcode 2438: eEGS_RIDING_RIDE_OBJECT_ACK (0x00753A90).) |
| **2464** | `0x09A0` | `eEGS_PET_CREATE_REQ` | **C → S** | `—` | `pets.py` | `PetCreateReq` (Opcode 2464: eEGS_PET_CREATE_REQ (0x0079E0B0).) |
| **2465** | `0x09A1` | `eEGS_PET_CREATE_ACK` | **S → C** | `0x0079E620` | — | `PetCreateAck` (Opcode 2465: eEGS_PET_CREATE_ACK (0x0079E620).) |
| **2466** | `0x09A2` | `eEGS_PET_DELETE_REQ` | **C → S** | `—` | `pets.py` | `PetDeleteReq` (Opcode 2466: eEGS_PET_DELETE_REQ (0x0079E260).) |
| **2467** | `0x09A3` | `eEGS_PET_DELETE_ACK` | **S → C** | `0x0079EA50` | — | `PetDeleteAck` (Opcode 2467: eEGS_PET_DELETE_ACK (0x0079EA50).) |
| **2468** | `0x09A4` | `eEGS_PET_SUMMON_REQ` | **C → S** | `—` | `pets.py` | `PetSummonReq` (Opcode 2468: eEGS_PET_SUMMON_REQ (0x0079E3E0).) |
| **2469** | `0x09A5` | `eEGS_PET_SUMMON_ACK` | **S → C** | `0x0079ECF0` | — | `PetSummonAck` (Opcode 2469: eEGS_PET_SUMMON_ACK (0x0079ECF0).) |
| **2470** | `0x09A6` | `eEGS_PET_RELEASE_SUMMON_REQ` | **C → S** | `—` | `pets.py` | `PetReleaseSummonReq` (Opcode 2470: eEGS_PET_RELEASE_SUMMON_REQ (0x0079E510).) |
| **2471** | `0x09A7` | `eEGS_PET_RELEASE_SUMMON_ACK` | **S → C** | `0x0079EEE0` | — | `PetReleaseSummonAck` (Opcode 2471: eEGS_PET_RELEASE_SUMMON_ACK (0x0079EEE0).) |
| **2473** | `0x09A9` | `eEGS_PET_SAVE_REQ` | **C → S** | `—` | `pets.py` | `PetSaveReq` (Opcode 2473: eEGS_PET_SAVE_REQ.) |
| **2474** | `0x09AA` | `eEGS_PET_SAVE_ACK` | **S → C** | `0x007758B0` | — | `PetSaveAck` (Opcode 2474: eEGS_PET_SAVE_ACK (0x007758B0).) |
| **2475** | `0x09AB` | `eEGS_PET_LOAD_REQ` | **C → S** | `—` | `pets.py` | `PetLoadReq` (Opcode 2475: eEGS_PET_LOAD_REQ (0x0079F320).) |
| **2476** | `0x09AC` | `eEGS_PET_LOAD_ACK` | **S → C** | `0x0079F560` | — | `PetLoadAck` (Opcode 2476: eEGS_PET_LOAD_ACK (0x0079F560).) |
| **2477** | `0x09AD` | `eEGS_PET_REPLACE_REQ` | **C → S** | `—` | `pets.py` | `PetReplaceReq` (Opcode 2477: eEGS_PET_REPLACE_REQ.) |
| **2478** | `0x09AE` | `eEGS_PET_REPLACE_ACK` | **S → C** | `0x0079F770` | — | `PetReplaceAck` (Opcode 2478: eEGS_PET_REPLACE_ACK (0x0079F770).) |
| **2479** | `0x09AF` | `eEGS_PET_CONSUME_SATIETY_NOT` | **S → C** | `0x0079F980` | — | — |
| **2480** | `0x09B0` | `eEGS_PET_EAT_NORMAL_REQ` | **C → S** | `—` | `pets.py` | `PetEatNormalReq` (Opcode 2480: eEGS_PET_EAT_NORMAL_REQ (0x0079FBA0).) |
| **2481** | `0x09B1` | `eEGS_PET_EAT_NORMAL_ACK` | **S → C** | `0x00781260` | — | `PetEatNormalAck` (Opcode 2481: eEGS_PET_EAT_NORMAL_ACK (0x00781260).) |
| **2483** | `0x09B3` | `eEGS_PET_EAT_CASH_ACK` | **S → C** | `0x007815F0` | — | — |
| **2484** | `0x09B4` | `eEGS_PET_EVOLUTION_REQ` | **C → S** | `—` | `pets.py` | `PetEvolutionReq` (Opcode 2484: eEGS_PET_EVOLUTION_REQ (0x0079FE20).) |
| **2485** | `0x09B5` | `eEGS_PET_EVOLUTION_ACK` | **S → C** | `0x0079FEF0` | — | `PetEvolutionAck` (Opcode 2485: eEGS_PET_EVOLUTION_ACK (0x0079FEF0).) |
| **2487** | `0x09B7` | `eEGS_CHEAT_PET_LEVEL_ACK` | **S → C** | `0x00775AA0` | — | — |
| **2489** | `0x09B9` | `eEGS_CHEAT_PET_SATIETY_ACK` | **S → C** | `0x007A0280` | — | — |
| **2491** | `0x09BB` | `eEGS_CHEAT_PET_EVOLUTION_ACK` | **S → C** | `0x007A0450` | — | — |
| **2493** | `0x09BD` | `eEGS_PET_CASH_FOOD_EQUIP_ACK` | **S → C** | `0x007A0A20` | — | — |
| **2495** | `0x09BF` | `eEGS_PET_CASH_FOOD_UNEQUIP_ACK` | **S → C** | `0x007A0C30` | — | — |
| **2499** | `0x09C3` | `eEGS_PET_EXTEND_DEPOT_ACK` | **S → C** | `0x00781990` | — | — |
| **2501** | `0x09C5` | `eEGS_PET_SWITCH_STORAGE_ACK` | **S → C** | `0x007A0E30` | — | — |
| **2502** | `0x09C6` | `eEGS_PET_DEPOT_EXTEND_EXPIRE_NOT` | **S → C** | `0x00775EA0` | — | — |
| **2508** | `0x09CC` | `eEGS_AUTOCHECK_CHECK_INPUT_STRING_ACK` | **S → C** | `—` | `pets.py` | Compatibility / PetCall summon request -> responds with 2469 |
| **2509** | `0x09CD` | `eEGS_MONSTER_LAYER_MOVE_NOT` | **S → C** | `—` | `dungeon.py` | eEGS_MONSTER_LAYER_MOVE_NOT: notification without an ACK opcode (2510 is PET_NICK_CHANGE_REQ). Live: ffffff7f 13270006 + two (u32 layer, u32 hash) pairs, e.g. 2 -> 5 in 0x32ADCD46. Recorded only. |
| **2510** | `0x09CE` | `eEGS_PET_NICK_CHANGE_REQ` | **C → S** | `—` | `pets.py` | `PetNickChangeReq` (Opcode 2510: eEGS_PET_NICK_CHANGE_REQ (0x007A16DA).) |
| **2511** | `0x09CF` | `eEGS_PET_NICK_CHANGE_AKC` | **S → C** | `0x00781CD0` | — | `PetNickChangeAck` (Opcode 2511: eEGS_PET_NICK_CHANGE_AKC (0x00781CD0).) |