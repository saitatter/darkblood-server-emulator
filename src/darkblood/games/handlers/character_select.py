"""2007 SelectCharacterAck and character details built from a stored character."""
import struct
import time

from darkblood.games.entities.character import Character
from darkblood.games.entities.items import DEPOT_CONTAINER, Bag, Item
from darkblood.games.missions.quests import ActiveQuest
from darkblood.games.handlers.skills import learned_proficiencies_for_char, learned_skill_map, proficiency_values_for_char
from darkblood.games import achievements
from darkblood.games.network.messages import (
    DepotInfo,
    DepotSlotInfo,
    PetDepotSlotInfo,
    PetInfo,
    QuestSpecialInfo,
    QuickSlot,
    SelectCharacterAck,
)
from darkblood.core.hashing import jhash
from darkblood.games.handlers.pets import build_ridings_map
from darkblood.games.handlers.square import waypoint_data


def build_char_details(char):
    """Serialize player details for struct 0x00A52630 using Character model."""
    c = char if isinstance(char, Character) else Character.from_dict(char)
    return c.encode_world_details()


def _build_depot_info(char_dict: dict) -> DepotInfo:
    """Build a DepotInfo entry for 2007 SelectCharacterAck (0x00A40380)."""
    char_uid = int(char_dict.get('id', 1))
    extend_remain = list(char_dict.get('depot_extend_remain', [0, 0]))
    while len(extend_remain) < 2:
        extend_remain.append(0)
    slots = [
        DepotSlotInfo(active=remain > 0, slot_index=idx if remain > 0 else 0xFFFF,
                      expire_date=0, remain_sec=max(0, int(remain)))
        for idx, remain in enumerate(extend_remain[:2])
    ]
    depot_items = [
        Item(owner=char_uid, **i)
        for i in char_dict.get('items', [])
        if i.get('container') == DEPOT_CONTAINER
    ]
    return DepotInfo(
        char_uid=char_uid,
        gold=int(char_dict.get('depot_gold', 0)),
        char_name=char_dict.get('name', ''),
        items=depot_items,
        slots=slots,
        share_expire_time=0,
    )


def build_select_char_ack(char, account_chars=None, account_data=None):
    """Serialize eEGS_SELECT_CHAR_ACK (2007) using SelectCharacterAck model.

    `char` is a stored character dict or a Character; a Character carries no
    inventory, quest or progress data, so those parts are sent empty.
    """
    c = char if isinstance(char, Character) else Character.from_dict(char)
    data = char if isinstance(char, dict) else {}
    items, depots = [], {}
    if data:
        items = [Item(owner=data.get('id', -1), **i) for i in data.get('items', [])
                 if i.get('container') != DEPOT_CONTAINER]
        for entry in (account_chars if account_chars is not None else [data]):
            if isinstance(entry, dict) and 'id' in entry:
                depots[int(entry['id'])] = _build_depot_info(entry)
    divisions, completed = achievements.total_info(data)
    card_max_slots = int((account_data or {}).get('monster_card_max_slots', 60))
    return SelectCharacterAck(
        result=0,
        proficiencies=proficiency_values_for_char(char),
        character=c,
        depots=depots,
        active_quests=sorted((ActiveQuest.from_store(q, r) for q, r in data.get('quests_active', {}).items()),
                             key=lambda q: q.uid),
        quest_special_info=_build_quest_special_info(data),
        bags=[Bag(**b) for b in data.get('bags', [])],
        items=items,
        skills=learned_skill_map(data.get('skills', {}), data.get('skill_speeches', {}),
                                 data.get('locked_skills', []), data.get('skill_show_cooltime', [])),
        quickslots=[QuickSlot(*q) for q in sorted(
            (q['type'], q['slot'], q['ref_id'], q['ref_uid'])
            for q in data.get('quickslots', {}).values() if 'slot' in q)],
        daily_dun_enter_counts={str(k): int(v) for k, v in data.get('daily_dun_enter_counts', {}).items()},
        daily_dun_clear_counts={str(k): int(v) for k, v in data.get('daily_dun_clear_counts', {}).items()},
        custom_keys=str(data.get('custom_keys', '')),
        achieve_divisions=divisions,
        achieve_completed=completed,
        waypoints=_build_waypoints_map(data),
        learned_proficiencies=learned_proficiencies_for_char(char),
        ridings=_build_ridings_map(data),
        pets=_build_pets_map(data),
        summoned_pet_uid=int(data.get('summoned_pet') or 0),
        pet_summoned=bool(data.get('summoned_pet')),
        pet_depot_slots=_build_pet_depot_slots(data),
        monster_card_add_slots=max(0, card_max_slots - 60),
        citadel_play_count=int(data.get('citadel_play_count', 3)),
    ).encode()


def _build_quest_special_info(char) -> QuestSpecialInfo:
    """Build 18-byte QuestSpecialInfo for 2007 SelectCharacterAck (0x00641E00 -> JQuestMgr::Init).

    Restores active promotion-trial temporary skills on relog so the HUD TempSkillSet activates.
    """
    if not isinstance(char, dict):
        return QuestSpecialInfo()
    ts = char.get('temp_skills')
    if not isinstance(ts, dict):
        return QuestSpecialInfo()
    qid = ts.get('quest_id')
    active_quests = char.get('quests_active') or {}
    if qid is None or str(qid) not in active_quests:
        return QuestSpecialInfo()
    t_skills = ts.get('skills') or []
    if not t_skills:
        return QuestSpecialInfo()
    qid_int = int(qid)
    qid_i32 = qid_int - 0x100000000 if qid_int >= 0x80000000 else qid_int
    return QuestSpecialInfo(
        action_type=1,
        skill_1_index=int(ts.get('target_class', 0xFFFF)) & 0xFFFF,
        skill_1_value=int(t_skills[0]),
        skill_2_index=int(t_skills[1]) if len(t_skills) > 1 else -1,
        skill_2_value=qid_i32,
    )


def _build_pet_depot_slots(char: dict, *, now=None) -> list:
    """Build 4 PetDepotSlotInfo (0x1B-byte) entries for 2007 SelectCharacterAck (0x00A3EDD0 -> 0x00A1E820)."""
    pet_extend = list(char.get('pet_depot_extend', [0, 0, 0, 0]))
    while len(pet_extend) < 4:
        pet_extend.append(0)
    now = int(time.time()) if now is None else int(now)
    for index, expires_at in char.get('pet_depot_extend_expires', {}).items():
        pet_extend[int(index)] = max(0, int(expires_at) - now)
    return [
        PetDepotSlotInfo(
            active=rem > 0,
            slot_index=idx if rem > 0 else 0xFFFF,
            expire_date=0,
            remain_sec=int(rem),
        )
        for idx, rem in enumerate(pet_extend)
    ]


def _build_pets_map(char: dict) -> dict:
    """Build {pet_uid: PetInfo} for 2007 SelectCharacterAck (0x00A1E8C0 -> 0x00A52CF0)."""
    out = {}
    for p in char.get('pets') or []:
        if not isinstance(p, dict) or 'uid' not in p:
            continue
        uid = int(p['uid'])
        code = str(p.get('code') or 'PetCall001')
        out[uid] = PetInfo(
            pet_uid=uid,
            pet_id=jhash(code),
            level=int(p.get('level', 1)),
            exp=int(p.get('exp', 0)),
            satiety=int(p.get('satiety', 100)),
            name=str(p.get('name') or 'Pet'),
            is_cash_food=bool(p.get('is_cash_food', False)),
            slot=int(p.get('slot', -1)),
        )
    return out


def _build_ridings_map(char: dict) -> dict:
    """Build {jhash(ride_code): RidingInfo} for 2007 SelectCharacterAck (0x0076ABA0)."""
    return build_ridings_map(char)


def _build_waypoints_map(char: dict) -> dict:
    """Build {layer_net_id: WaypointData} for 2007 SelectCharacterAck (0x00A3EA00)."""
    out = {}
    for raw_lid in char.get('waypoints', []):
        lid = int(raw_lid)
        out[lid] = waypoint_data(lid)
    return out
