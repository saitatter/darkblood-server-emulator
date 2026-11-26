"""Pet lifecycle and monster taming domain handlers."""
import struct
import time

from darkblood.core.hashing import jhash
from darkblood.core.serialization.jser import event
from darkblood.games.dispatcher import packet_handler
from darkblood.games.entities.items import Item, UPDATE_OWNER
from darkblood.games.handlers.pets.mounts import build_ridings_map, mount_item_info
from darkblood.games.network.messages.pets import (
    PetCashFoodEquipAck,
    PetCashFoodEquipReq,
    PetCashFoodUnequipAck,
    PetChangeExpNot,
    PetCreateAck,
    PetCreateReq,
    PetDeleteAck,
    PetDeleteReq,
    PetEatCashAck,
    PetEatCashReq,
    PetEatNormalAck,
    PetEatNormalReq,
    PetEvolutionAck,
    PetEvolutionReq,
    PetExtendDepotAck,
    PetExtendDepotReq,
    PetInfo,
    PetLevelUpNot,
    PetLoadAck,
    PetLoadReq,
    PetNickChangeAck,
    PetNickChangeReq,
    PetReleaseSummonAck,
    PetReleaseSummonReq,
    PetReplaceAck,
    PetReplaceReq,
    PetSaveAck,
    PetSaveReq,
    PetSummonAck,
    PetSummonReq,
    PetSwitchStorageAck,
    PetSwitchStorageReq,
    RidingChangeListNot,
    TameingMonsterDeleteReq,
    TameingMonsterInsertReq,
    TamingMonsterDeleteAck,
    TamingMonsterInsertAck,
)


async def grant_pet_exp(session, char: dict, exp_amount: int) -> bool:
    """Grant EXP to the character's currently summoned pet and send 5324 / 5323 notifications.

    Uses the UPExp curve from DictPet:LoadPetStat (identical to char_level_stat(0, lv)['upexp']).
    Returns True if the pet record was updated.
    """
    if not char or exp_amount <= 0:
        return False
    pet_uid = char.get('summoned_pet')
    if not pet_uid:
        return False
    pet = next((p for p in (char.get('pets') or []) if p.get('uid') == pet_uid), None)
    if pet is None:
        return False

    from darkblood.games.game_data.client_dict import char_level_stat
    from darkblood.games.progression import MAX_LEVEL

    gain = max(1, int(exp_amount))
    level = max(1, int(pet.get('level', 1)))
    cur_exp = max(0, int(pet.get('exp', 0))) + gain
    leveled_up = False
    while level < MAX_LEVEL:
        up_exp = max(1, int(char_level_stat(0, level)['upexp']))
        if cur_exp >= up_exp:
            cur_exp -= up_exp
            level += 1
            leveled_up = True
        else:
            break
    if level >= MAX_LEVEL:
        cur_exp = 0

    pet['level'] = level
    pet['exp'] = cur_exp
    char_uid = int(char.get('id', 0))

    if leveled_up:
        # 5323 eERC_PET_LEVEL_UP_NOT (0x007754E0 -> 0x00A48B80 -> 0x00952300): 21 raw bytes <qqBi
        payload = struct.pack('<qqBi', char_uid, int(pet_uid), level & 0xFF, cur_exp)
        await session.transport.send_event(
            event(5323, PetLevelUpNot(level_up_info=payload).encode()),
            note=f'pet level up not (pet={pet_uid} lv={level} exp={cur_exp})',
        )
    else:
        # 5324 eERC_PET_CHANGE_EXP_NOT (0x0079EFA0 -> 0x009522A0): gain_2 > 0 required
        await session.transport.send_event(
            event(5324, PetChangeExpNot(pet_uid=int(pet_uid), change_exp=cur_exp, gain_2=gain).encode()),
            note=f'pet change exp not (pet={pet_uid} +{gain} exp={cur_exp})',
        )
    return True


class PetCoreHandlersMixin:
    """Monster taming and pet hatching, summoning, feeding, evolution and storage."""

    # --- Monster Taming (2348, 2350) ---

    @packet_handler(TameingMonsterInsertReq)
    async def handle_taming_monster_insert(self, correlation, body):
        # eEGS_TAMEING_MONSTER_INSERT_REQ (0x00799BA0) -> 2349 eEGS_TAMEING_MONSTER_INSERT_ACK (0x00771A00)
        req = TameingMonsterInsertReq.decode(body)
        char = self.current_char()
        if not char:
            await self.reply(TamingMonsterInsertAck(result=1), correlation, note='tame monster insert fail (no char)')
            return
        tamed = char.setdefault('tamed_monsters', [])
        slot = req.slot if req.slot else len(tamed)
        tamed.append({'monster_id': req.monster_id, 'slot': slot})
        self.save_char()
        await self.reply(TamingMonsterInsertAck(result=0), correlation,
                         note=f'tame monster insert ack (monster={req.monster_id}, slot={slot})')

    @packet_handler(TameingMonsterDeleteReq)
    async def handle_taming_monster_delete(self, correlation, body):
        # eEGS_TAMEING_MONSTER_DELETE_REQ (0x00799D30) -> 2351 eEGS_TAMEING_MONSTER_DELETE_ACK (0x00771BB0)
        req = TameingMonsterDeleteReq.decode(body)
        char = self.current_char()
        if not char:
            await self.reply(TamingMonsterDeleteAck(result=1), correlation, note='tame monster delete fail (no char)')
            return
        tamed = char.setdefault('tamed_monsters', [])
        for m in list(tamed):
            if m.get('slot') == req.slot or (req.monster_id and m.get('monster_id') == req.monster_id):
                tamed.remove(m)
                break
        self.save_char()
        await self.reply(TamingMonsterDeleteAck(result=0, deleted_slot=req.slot), correlation,
                         note=f'tame monster delete ack (slot={req.slot})')

    # --- Pets Lifecycle (2464..2511) ---

    @packet_handler(PetCreateReq)
    async def handle_pet_create(self, correlation, body):
        # eEGS_PET_CREATE_REQ (0x0079E090) -> 2465 eEGS_PET_CREATE_ACK (0x0079E620)
        req = PetCreateReq.decode(body)
        char = self.current_char()
        if not char:
            await self.reply(PetCreateAck(result=1), correlation, note='pet create fail (no char)')
            return
        items = char.get('items', [])
        egg = next((i for i in items if i.get('uid') == req.pet_uid), None)
        wire_items = []
        egg_code = 'Pegg1Cash96'
        if egg is not None:
            egg_code = egg.get('code', egg_code)
            rem = egg.get('count', 1) - 1
            if rem <= 0:
                items.remove(egg)
                wire_items.append(Item(
                    owner=UPDATE_OWNER,
                    uid=0,
                    code='',
                    container=egg.get('container', 3),
                    slot=egg.get('slot', 0),
                    count=0,
                ))
            else:
                egg['count'] = rem
                wire_items.append(Item(owner=UPDATE_OWNER, **egg))

        pets = char.setdefault('pets', [])
        new_uid = req.pet_uid if req.pet_uid else (len(pets) + 1)
        pet_code = 'PetCall001'
        new_pet = {
            'uid': new_uid,
            'code': pet_code,
            'name': 'Pet',
            'level': 1,
            'exp': 0,
            'satiety': 100,
            'slot': -1,
        }
        pets.append(new_pet)
        self.save_char()
        await self.reply(
            PetCreateAck(
                result=0,
                items=wire_items,
                item_id=jhash(egg_code),
                pet=PetInfo(
                    pet_uid=new_uid,
                    pet_id=jhash(pet_code),
                    level=new_pet['level'],
                    exp=new_pet['exp'],
                    satiety=new_pet['satiety'],
                    name=new_pet['name'],
                    is_cash_food=False,
                    slot=new_pet['slot'],
                ),
            ),
            correlation,
            note=f'pet create ack (uid={new_uid} egg={egg_code} pet={pet_code})',
        )

    @packet_handler(PetDeleteReq)
    async def handle_pet_delete(self, correlation, body):
        # eEGS_PET_DELETE_REQ (0x0079E260) -> 2467 eEGS_PET_DELETE_ACK (0x0079EA50)
        req = PetDeleteReq.decode(body)
        char = self.current_char()
        if not char:
            await self.reply(PetDeleteAck(result=1), correlation, note='pet delete fail (no char)')
            return
        pets = char.setdefault('pets', [])
        target = next((p for p in pets if p.get('uid') == req.pet_uid), None)
        if target:
            pets.remove(target)
        if char.get('summoned_pet') == req.pet_uid:
            char['summoned_pet'] = None
        self.save_char()
        await self.reply(PetDeleteAck(result=0, pet_uid=req.pet_uid), correlation,
                         note=f'pet delete ack (uid={req.pet_uid})')

    @packet_handler(PetSummonReq)
    async def handle_pet_summon(self, correlation, body):
        # eEGS_PET_SUMMON_REQ (0x0079E3C0) -> 2469 eEGS_PET_SUMMON_ACK (0x0079ECF0)
        # 0x0079ECF0 reads u16 sNurturePoint (satiety) and writes it via 0x009524F0.
        # Sending 0 zeroed the pet's satiety, blocking subsequent summons (0x008625D0).
        PetSummonReq.decode(body)
        char = self.current_char()
        if not char:
            await self.reply(PetSummonAck(result=1), correlation, note='pet summon fail (no char)')
            return
        pets = char.get('pets', [])
        active = next((p for p in pets if p.get('slot', -1) == -1), pets[0] if pets else None)
        satiety = max(2, int(active.get('satiety', 100))) if active else 100
        if active is not None:
            active['satiety'] = satiety
        char['summoned_pet'] = active['uid'] if active else 0
        self.save_char()
        await self.reply(PetSummonAck(result=0, satiety=satiety), correlation,
                         note=f'pet summon ack (satiety={satiety})')

    @packet_handler(PetReleaseSummonReq)
    async def handle_pet_release_summon(self, correlation, body):
        # eEGS_PET_RELEASE_SUMMON_REQ (0x0079E510) -> 2471 eEGS_PET_RELEASE_SUMMON_ACK (0x0079EEE0)
        char = self.current_char()
        if char:
            char['summoned_pet'] = None
            self.save_char()
        await self.reply(PetReleaseSummonAck(result=0), correlation, note='pet release summon ack')

    @packet_handler(PetSaveReq)
    async def handle_pet_save(self, correlation, body):
        # eEGS_PET_SAVE_REQ -> 2474 eEGS_PET_SAVE_ACK (0x007758B0)
        await self.reply(PetSaveAck(result=0, value=1), correlation, note='pet save ack')

    @packet_handler(PetLoadReq)
    async def handle_pet_load(self, correlation, body):
        # eEGS_PET_LOAD_REQ (0x0079F320) -> 2476 eEGS_PET_LOAD_ACK (0x0079F560)
        req = PetLoadReq.decode(body)
        char = self.current_char()
        if char and req.pet_uid:
            char['summoned_pet'] = req.pet_uid
            self.save_char()
        await self.reply(PetLoadAck(result=0, pet_uid=req.pet_uid), correlation,
                         note=f'pet load ack (uid={req.pet_uid})')

    @packet_handler(PetReplaceReq)
    async def handle_pet_replace(self, correlation, body):
        # eEGS_PET_REPLACE_REQ -> 2478 eEGS_PET_REPLACE_ACK (0x0079F770)
        req = PetReplaceReq.decode(body)
        char = self.current_char()
        if char and req.pet_uid:
            char['summoned_pet'] = req.pet_uid
            self.save_char()
        await self.reply(PetReplaceAck(result=0, pet_uid=req.pet_uid), correlation,
                         note=f'pet replace ack (uid={req.pet_uid})')

    @packet_handler(PetEatNormalReq)
    async def handle_pet_eat_normal(self, correlation, body):
        # eEGS_PET_EAT_NORMAL_REQ (0x0079FBA0) -> 2481 eEGS_PET_EAT_NORMAL_ACK (0x00781260)
        PetEatNormalReq.decode(body)
        char = self.current_char()
        satiety = 100
        if char:
            pets = char.setdefault('pets', [])
            if pets:
                active = next((p for p in pets if p.get('uid') == char.get('summoned_pet')), pets[0])
                active['satiety'] = min(100, active.get('satiety', 50) + 30)
                satiety = active['satiety']
                self.save_char()
        await self.reply(PetEatNormalAck(result=0, satiety=satiety, status=1), correlation,
                         note=f'pet eat normal ack (satiety={satiety})')

    @packet_handler(PetEvolutionReq)
    async def handle_pet_evolution(self, correlation, body):
        # eEGS_PET_EVOLUTION_REQ (0x0079FE20) -> 2485 eEGS_PET_EVOLUTION_ACK (0x0079FEF0)
        char = self.current_char()
        old_uid = 1
        new_uid = 1
        new_pet_id = 8000
        if char:
            pets = char.setdefault('pets', [])
            if pets:
                active = next((p for p in pets if p.get('uid') == char.get('summoned_pet')), pets[0])
                old_uid = active.get('uid', 1)
                active['level'] = active.get('level', 1) + 1
                active['code'] = 'PetCall111' if active.get('code') == 'PetCall001' else 'PetCall121'
                new_uid = old_uid
                new_pet_id = 8001
                self.save_char()
        await self.reply(
            PetEvolutionAck(result=0, old_pet_uid=old_uid, new_pet_id=new_pet_id, new_pet_uid=new_uid),
            correlation,
            note=f'pet evolution ack (uid={new_uid})',
        )

    @packet_handler(PetNickChangeReq)
    async def handle_pet_nick_change(self, correlation, body):
        # eEGS_PET_NICK_CHANGE_REQ (0x007A16DA) -> 2511 eEGS_PET_NICK_CHANGE_AKC (0x00781CD0)
        req = PetNickChangeReq.decode(body)
        char = self.current_char()
        if char:
            pets = char.setdefault('pets', [])
            target = next((p for p in pets if p.get('uid') == req.pet_uid), None)
            if target:
                target['name'] = req.new_name
            self.save_char()
        await self.reply(PetNickChangeAck(result=0, pet_uid=req.pet_uid, new_name=req.new_name), correlation,
                         note=f'pet nick change ack (uid={req.pet_uid}, name={req.new_name})')

    @packet_handler(2482)
    async def handle_pet_eat_cash(self, correlation, body):
        # eEGS_PET_EAT_CASH_REQ (0x0079FCC0) -> 2483 eEGS_PET_EAT_CASH_ACK (0x007815F0)
        req = PetEatCashReq.decode(body)
        char = self.current_char()
        satiety = 100
        if char:
            pets = char.setdefault('pets', [])
            if pets:
                active = next((p for p in pets if p.get('uid') == char.get('summoned_pet')), pets[0])
                active['satiety'] = 100
                satiety = 100
                self.save_char()
        await self.reply(PetEatCashAck(result=0, items=[], satiety=satiety, is_cash_food=True),
                         correlation, note=f'pet eat cash ack (item={req.item_uid} satiety={satiety})')

    @packet_handler(2492)
    async def handle_pet_cash_food_equip(self, correlation, body):
        # eEGS_PET_CASH_FOOD_EQUIP_REQ (0x007A07C0) -> 2493 eEGS_PET_CASH_FOOD_EQUIP_ACK (0x007A0A20)
        req = PetCashFoodEquipReq.decode(body)
        char = self.current_char()
        if char is not None:
            char['pet_cash_food_uid'] = req.cash_food_item_uid
            self.save_char()
        await self.reply(PetCashFoodEquipAck(result=0, cash_food_item_uid=req.cash_food_item_uid),
                         correlation, note=f'pet cash food equip ack (uid={req.cash_food_item_uid})')

    @packet_handler(2494)
    async def handle_pet_cash_food_unequip(self, correlation, body):
        # eEGS_PET_CASH_FOOD_UNEQUIP_REQ (0x007A0930) -> 2495 eEGS_PET_CASH_FOOD_UNEQUIP_ACK (0x007A0C30)
        char = self.current_char()
        if char is not None:
            char.pop('pet_cash_food_uid', None)
            self.save_char()
        await self.reply(PetCashFoodUnequipAck(result=0), correlation, note='pet cash food unequip ack')

    @packet_handler(2498)
    async def handle_pet_extend_depot(self, correlation, body):
        # eEGS_PET_EXTEND_DEPOT_REQ (0x007A1030) -> 2499 eEGS_PET_EXTEND_DEPOT_ACK (0x00781990)
        req = PetExtendDepotReq.decode(body)
        extend_time = 30 * 86400
        wire_items = []
        char = self.current_char()
        if char is not None:
            pet_extend = list(char.get('pet_depot_extend', [0, 0, 0, 0]))
            slot = max(0, int(req.depot_slot_index))
            while len(pet_extend) <= slot:
                pet_extend.append(0)
            pet_extend[slot] = int(pet_extend[slot]) + extend_time
            char['pet_depot_extend'] = pet_extend
            items = char.get('items', [])
            used = next((i for i in items if i.get('uid') == req.item_uid), None)
            if used is not None:
                rem = int(used.get('count', 1)) - 1
                if rem <= 0:
                    items.remove(used)
                    wire_items.append(Item(
                        owner=UPDATE_OWNER,
                        uid=0,
                        code='',
                        container=used.get('container', 3),
                        slot=used.get('slot', 0),
                        count=0,
                    ))
                else:
                    used['count'] = rem
                    wire_items.append(Item(owner=UPDATE_OWNER, **used))
            self.save_char()
        await self.reply(
            PetExtendDepotAck(result=0, depot_slot_index=req.depot_slot_index,
                              extend_time=extend_time, items=wire_items),
            correlation, note=f'pet extend depot ack (slot={req.depot_slot_index}, time={extend_time})',
        )

    @packet_handler(2500)
    async def handle_pet_switch_storage(self, correlation, body):
        # eEGS_PET_SWITCH_STORAGE_REQ (0x007A0D00) -> 2501 eEGS_PET_SWITCH_STORAGE_ACK (0x007A0E30)
        req = PetSwitchStorageReq.decode(body)
        await self.reply(
            PetSwitchStorageAck(result=0, move_slot_index=req.move_slot_index,
                                target_slot_index=req.target_slot_index),
            correlation, note=f'pet switch storage ack ({req.move_slot_index}->{req.target_slot_index})',
        )

    # Helper for item use integration
    async def apply_pet_or_mount_item(self, char, code):
        """When an inventory item for a pet or mount (Type=38 / ridecall*) is consumed."""
        if not char or not code:
            return
        if code.startswith('PetCall'):
            pets = char.setdefault('pets', [])
            new_uid = len(pets) + 1
            pets.append({
                'uid': new_uid,
                'code': code,
                'name': 'Pet',
                'level': 1,
                'satiety': 100,
                'slot': len(pets),
            })
            self.save_char()
            return
        minfo = mount_item_info(code)
        if minfo is not None:
            ride_code, valid_hours = minfo
            now = int(time.time())
            ridings = char.setdefault('ridings', {})
            existing = ridings.get(ride_code, {})
            base_expire = max(now, int(existing.get('expire_ts', 0)))
            ridings[ride_code] = {
                'expire_ts': base_expire + max(1, valid_hours) * 3600,
                'dye_colors': existing.get('dye_colors', []),
            }
            self.save_char()
            ridings_map = build_ridings_map(char)
            await self.send_msg(
                RidingChangeListNot(ridings=ridings_map),
                note=f'riding change list not ({ride_code}, +{valid_hours}h, count={len(ridings_map)})',
            )
