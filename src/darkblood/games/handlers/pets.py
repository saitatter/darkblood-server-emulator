"""Pet, Mount and Taming domain handlers."""
from darkblood.core.serialization.jser import event
from darkblood.games.network.messages.pets import (
    PetCreateAck,
    PetCreateReq,
    PetDeleteAck,
    PetDeleteReq,
    PetEatNormalAck,
    PetEatNormalReq,
    PetEvolutionAck,
    PetEvolutionReq,
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
    RidingGetListAck,
    RidingGetListReq,
    RidingRideObjectAck,
    RidingRideObjectReq,
    TameingMonsterDeleteReq,
    TameingMonsterInsertReq,
    TamingMonsterDeleteAck,
    TamingMonsterInsertAck,
)
from darkblood.games.dispatcher import packet_handler
from darkblood.games.handlers.base import BaseDomainService


class PetHandlers(BaseDomainService):
    """Pet summoning, evolution, feeding, mounts, and monster taming."""

    # --- Monster Taming (2348, 2350) ---

    @packet_handler(TameingMonsterInsertReq)
    async def handle_taming_monster_insert(self, correlation, body):
        # eEGS_TAMEING_MONSTER_INSERT_REQ (0x00799BA0) -> 2349 eEGS_TAMEING_MONSTER_INSERT_ACK (0x00771A00)
        req = TameingMonsterInsertReq.decode(body)
        char = self.current_char()
        if not char:
            await self.transport.send_event(event(2349, TamingMonsterInsertAck(result=1).encode(), correlation),
                                            note='tame monster insert fail (no char)')
            return
        tamed = char.setdefault('tamed_monsters', [])
        slot = req.slot if req.slot else len(tamed)
        m_entry = {'monster_id': req.monster_id, 'slot': slot}
        tamed.append(m_entry)
        self.store().save()
        ack = TamingMonsterInsertAck(result=0).encode()
        await self.transport.send_event(event(2349, ack, correlation),
                                        note=f'tame monster insert ack (monster={req.monster_id}, slot={slot})')

    @packet_handler(TameingMonsterDeleteReq)
    async def handle_taming_monster_delete(self, correlation, body):
        # eEGS_TAMEING_MONSTER_DELETE_REQ (0x00799D30) -> 2351 eEGS_TAMEING_MONSTER_DELETE_ACK (0x00771BB0)
        req = TameingMonsterDeleteReq.decode(body)
        char = self.current_char()
        if not char:
            await self.transport.send_event(event(2351, TamingMonsterDeleteAck(result=1).encode(), correlation),
                                            note='tame monster delete fail (no char)')
            return
        tamed = char.setdefault('tamed_monsters', [])
        for m in list(tamed):
            if m.get('slot') == req.slot or (req.monster_id and m.get('monster_id') == req.monster_id):
                tamed.remove(m)
                break
        self.store().save()
        ack = TamingMonsterDeleteAck(result=0, deleted_slot=req.slot).encode()
        await self.transport.send_event(event(2351, ack, correlation),
                                        note=f'tame monster delete ack (slot={req.slot})')

    # --- Mounts / Riding (2434, 2437) ---

    @packet_handler(RidingGetListReq)
    async def handle_riding_get_list(self, correlation, body):
        # eEGS_RIDING_GET_LIST_REQ -> 2435 eEGS_RIDING_GET_LIST_ACK (0x0076C5A0)
        char = self.current_char()
        mounts = char.get('mounts', []) if char else []
        ack = RidingGetListAck(result=0).encode()
        await self.transport.send_event(event(2435, ack, correlation),
                                        note=f'riding get list ack (count={len(mounts)})')

    @packet_handler(RidingRideObjectReq)
    async def handle_riding_ride_object(self, correlation, body):
        # eEGS_RIDING_RIDE_OBJECT_REQ (0x0079CE00) -> 2438 eEGS_RIDING_RIDE_OBJECT_ACK (0x00753A90)
        req = RidingRideObjectReq.decode(body)
        char = self.current_char()
        if not char:
            await self.transport.send_event(event(2438, RidingRideObjectAck(result=1).encode(), correlation),
                                            note='riding ride object fail (no char)')
            return
        current_mount = char.get('mounted_ride_id', 0)
        if current_mount == req.ride_object_id:
            # Toggle: dismount
            char['mounted_ride_id'] = 0
            new_state = 0
        else:
            # Mount
            char['mounted_ride_id'] = req.ride_object_id
            new_state = req.ride_object_id
        self.store().save()
        ack = RidingRideObjectAck(result=0, ride_object_id=new_state).encode()
        await self.transport.send_event(event(2438, ack, correlation),
                                        note=f'riding ride object ack (ride_id={new_state})')

    # --- Pets Lifecycle (2464, 2466, 2468, 2470, 2473, 2475, 2477, 2480, 2484, 2508, 2510) ---

    @packet_handler(PetCreateReq)
    async def handle_pet_create(self, correlation, body):
        # eEGS_PET_CREATE_REQ (0x0079E0B0) -> 2465 eEGS_PET_CREATE_ACK (0x0079E620)
        req = PetCreateReq.decode(body)
        char = self.current_char()
        if not char:
            await self.transport.send_event(event(2465, PetCreateAck(result=1).encode(), correlation),
                                            note='pet create fail (no char)')
            return
        pets = char.setdefault('pets', [])
        new_uid = req.pet_uid if req.pet_uid else (len(pets) + 1)
        new_pet = {
            'uid': new_uid,
            'code': 'PetCall001',
            'name': 'Pet',
            'level': 1,
            'satiety': 100,
            'slot': len(pets),
        }
        pets.append(new_pet)
        self.store().save()
        ack = PetCreateAck(result=0, slot=new_pet['slot']).encode()
        await self.transport.send_event(event(2465, ack, correlation),
                                        note=f'pet create ack (uid={new_uid})')

    @packet_handler(PetDeleteReq)
    async def handle_pet_delete(self, correlation, body):
        # eEGS_PET_DELETE_REQ (0x0079E260) -> 2467 eEGS_PET_DELETE_ACK (0x0079EA50)
        req = PetDeleteReq.decode(body)
        char = self.current_char()
        if not char:
            await self.transport.send_event(event(2467, PetDeleteAck(result=1).encode(), correlation),
                                            note='pet delete fail (no char)')
            return
        pets = char.setdefault('pets', [])
        target = next((p for p in pets if p.get('uid') == req.pet_uid), None)
        if target:
            pets.remove(target)
        if char.get('summoned_pet') == req.pet_uid:
            char['summoned_pet'] = None
        self.store().save()
        ack = PetDeleteAck(result=0, pet_uid=req.pet_uid).encode()
        await self.transport.send_event(event(2467, ack, correlation),
                                        note=f'pet delete ack (uid={req.pet_uid})')

    @packet_handler(PetSummonReq)
    async def handle_pet_summon(self, correlation, body):
        # eEGS_PET_SUMMON_REQ (0x0079E3E0) -> 2469 eEGS_PET_SUMMON_ACK (0x0079ECF0)
        PetSummonReq.decode(body)
        pet_slot = 0  # 2468 carries no fields (sender 0x0079E3C0)
        char = self.current_char()
        if not char:
            await self.transport.send_event(event(2469, PetSummonAck(result=1).encode(), correlation),
                                            note='pet summon fail (no char)')
            return
        char['summoned_pet'] = pet_slot
        self.store().save()
        ack = PetSummonAck(result=0, pet_slot=pet_slot).encode()
        await self.transport.send_event(event(2469, ack, correlation),
                                        note=f'pet summon ack (slot={pet_slot})')

    @packet_handler(PetReleaseSummonReq)
    async def handle_pet_release_summon(self, correlation, body):
        # eEGS_PET_RELEASE_SUMMON_REQ (0x0079E510) -> 2471 eEGS_PET_RELEASE_SUMMON_ACK (0x0079EEE0)
        char = self.current_char()
        if char:
            char['summoned_pet'] = None
            self.store().save()
        ack = PetReleaseSummonAck(result=0).encode()
        await self.transport.send_event(event(2471, ack, correlation),
                                        note='pet release summon ack')

    @packet_handler(PetSaveReq)
    async def handle_pet_save(self, correlation, body):
        # eEGS_PET_SAVE_REQ -> 2474 eEGS_PET_SAVE_ACK (0x007758B0)
        ack = PetSaveAck(result=0, value=1).encode()
        await self.transport.send_event(event(2474, ack, correlation), note='pet save ack')

    @packet_handler(PetLoadReq)
    async def handle_pet_load(self, correlation, body):
        # eEGS_PET_LOAD_REQ (0x0079F320) -> 2476 eEGS_PET_LOAD_ACK (0x0079F560)
        req = PetLoadReq.decode(body)
        char = self.current_char()
        if char and req.pet_uid:
            char['summoned_pet'] = req.pet_uid
            self.store().save()
        ack = PetLoadAck(result=0, pet_uid=req.pet_uid).encode()
        await self.transport.send_event(event(2476, ack, correlation),
                                        note=f'pet load ack (uid={req.pet_uid})')

    @packet_handler(PetReplaceReq)
    async def handle_pet_replace(self, correlation, body):
        # eEGS_PET_REPLACE_REQ -> 2478 eEGS_PET_REPLACE_ACK (0x0079F770)
        req = PetReplaceReq.decode(body)
        char = self.current_char()
        if char and req.pet_uid:
            char['summoned_pet'] = req.pet_uid
            self.store().save()
        ack = PetReplaceAck(result=0, pet_uid=req.pet_uid).encode()
        await self.transport.send_event(event(2478, ack, correlation),
                                        note=f'pet replace ack (uid={req.pet_uid})')

    @packet_handler(PetEatNormalReq)
    async def handle_pet_eat_normal(self, correlation, body):
        # eEGS_PET_EAT_NORMAL_REQ (0x0079FBA0) -> 2481 eEGS_PET_EAT_NORMAL_ACK (0x00781260)
        req = PetEatNormalReq.decode(body)
        char = self.current_char()
        satiety = 100
        if char:
            pets = char.setdefault('pets', [])
            if pets:
                active = next((p for p in pets if p.get('uid') == char.get('summoned_pet')), pets[0])
                active['satiety'] = min(100, active.get('satiety', 50) + 30)
                satiety = active['satiety']
                self.store().save()
        ack = PetEatNormalAck(result=0, satiety=satiety, status=1).encode()
        await self.transport.send_event(event(2481, ack, correlation),
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
                self.store().save()
        ack = PetEvolutionAck(result=0, old_pet_uid=old_uid, new_pet_id=new_pet_id, new_pet_uid=new_uid).encode()
        await self.transport.send_event(event(2485, ack, correlation),
                                        note=f'pet evolution ack (uid={new_uid})')

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
            self.store().save()
        ack = PetNickChangeAck(result=0, pet_uid=req.pet_uid, new_name=req.new_name).encode()
        await self.transport.send_event(event(2511, ack, correlation),
                                        note=f'pet nick change ack (uid={req.pet_uid}, name={req.new_name})')

    @packet_handler(2482)
    async def handle_pet_eat_cash(self, correlation, body):
        # eEGS_PET_EAT_CASH_REQ (0x0079FCC0) -> 2483 eEGS_PET_EAT_CASH_ACK (0x007815F0)
        from darkblood.games.network.messages.pets import PetEatCashAck, PetEatCashReq
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
        from darkblood.games.network.messages.pets import PetCashFoodEquipAck, PetCashFoodEquipReq
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
        from darkblood.games.network.messages.pets import PetCashFoodUnequipAck
        char = self.current_char()
        if char is not None:
            char.pop('pet_cash_food_uid', None)
            self.save_char()
        await self.reply(PetCashFoodUnequipAck(result=0), correlation, note='pet cash food unequip ack')

    @packet_handler(2498)
    async def handle_pet_extend_depot(self, correlation, body):
        # eEGS_PET_EXTEND_DEPOT_REQ (0x007A1030) -> 2499 eEGS_PET_EXTEND_DEPOT_ACK (0x00781990)
        from darkblood.games.network.messages.pets import PetExtendDepotAck, PetExtendDepotReq
        req = PetExtendDepotReq.decode(body)
        extend_time = 30 * 86400
        await self.reply(
            PetExtendDepotAck(result=0, depot_slot_index=req.depot_slot_index, extend_time=extend_time, items=[]),
            correlation, note=f'pet extend depot ack (slot={req.depot_slot_index})',
        )

    @packet_handler(2500)
    async def handle_pet_switch_storage(self, correlation, body):
        # eEGS_PET_SWITCH_STORAGE_REQ (0x007A0D00) -> 2501 eEGS_PET_SWITCH_STORAGE_ACK (0x007A0E30)
        from darkblood.games.network.messages.pets import PetSwitchStorageAck, PetSwitchStorageReq
        req = PetSwitchStorageReq.decode(body)
        await self.reply(
            PetSwitchStorageAck(result=0, move_slot_index=req.move_slot_index,
                                target_slot_index=req.target_slot_index),
            correlation, note=f'pet switch storage ack ({req.move_slot_index}->{req.target_slot_index})',
        )

    @packet_handler(2646)
    async def handle_riding_expire_update(self, correlation, body):
        # eEGS_RIDING_EXPIRE_UPDATE_REQ (0x007A6530) -> 2647 eEGS_RIDING_EXPIRE_UPDATE_ACK (0x007839F0)
        from darkblood.games.network.messages.pets import RidingExpireUpdateAck, RidingExpireUpdateReq
        req = RidingExpireUpdateReq.decode(body)
        await self.reply(RidingExpireUpdateAck(result=0, items=[]), correlation,
                         note=f'riding expire update ack (ride={req.riding_id})')

    # =========================================================================
    # Monster Card & Card Lotto Handlers (2604 - 2639)
    # =========================================================================

    @packet_handler(2604)
    async def handle_monster_card_insert(self, correlation, body):
        from darkblood.games.network.messages.pets import MonsterCardInsertAck, MonsterCardInsertReq
        req = MonsterCardInsertReq.decode(body)
        await self.reply(MonsterCardInsertAck(result=0), correlation,
                         note=f'monster card insert ack (item={req.item_uid})')

    @packet_handler(2606)
    async def handle_monster_card_merge(self, correlation, body):
        from darkblood.games.network.messages.pets import MonsterCardMergeAck, MonsterCardMergeReq
        req = MonsterCardMergeReq.decode(body)
        char = self.current_char()
        cur_ar = int(char.get('gold', 0)) if char else 0
        await self.reply(MonsterCardMergeAck(result=0, new_cards=[], del_cards=req.card_uids, cur_ar=cur_ar),
                         correlation, note=f'monster card merge ack (count={len(req.card_uids)})')

    @packet_handler(2610)
    async def handle_monster_card_set_char_deck(self, correlation, body):
        from darkblood.games.network.messages.pets import MonsterCardSetCharDeckAck, MonsterCardSetCharDeckReq
        req = MonsterCardSetCharDeckReq.decode(body)
        char = self.current_char()
        if char is not None:
            char['monster_card_deck'] = list(req.deck_uids)
            self.save_char()
        await self.reply(MonsterCardSetCharDeckAck(result=0, deck_uids=req.deck_uids, updated_cards=[]),
                         correlation, note=f'monster card set deck ack ({len(req.deck_uids)})')

    @packet_handler(2613)
    async def handle_monster_card_release_all_char(self, correlation, body):
        from darkblood.games.network.messages.pets import (
            MonsterCardInfo, MonsterCardReleaseAllCharAck, MonsterCardReleaseAllCharReq,
        )
        req = MonsterCardReleaseAllCharReq.decode(body)
        char = self.current_char()
        if char is not None:
            char['monster_card_deck'] = []
            self.save_char()
        await self.reply(MonsterCardReleaseAllCharAck(result=0, deck_uids=[], card=MonsterCardInfo(card_uid=req.card_uid)),
                         correlation, note='monster card release all ack')

    @packet_handler(2615)
    async def handle_monster_card_extend_slot(self, correlation, body):
        from darkblood.games.network.messages.pets import MonsterCardExtendSlotAck, MonsterCardExtendSlotReq
        req = MonsterCardExtendSlotReq.decode(body)
        char = self.current_char()
        cur_ar = int(char.get('gold', 0)) if char else 0
        max_cnt = int((char or {}).get('monster_card_max_slots', 50)) + max(1, req.count) * 10
        if char is not None:
            char['monster_card_max_slots'] = max_cnt
            self.save_char()
        await self.reply(MonsterCardExtendSlotAck(result=0, max_inven_cnt=max_cnt, cur_ar=cur_ar),
                         correlation, note=f'monster card extend slot ack (max={max_cnt})')

    @packet_handler(2633)
    async def handle_monster_card_lotto_reg(self, correlation, body):
        from darkblood.games.network.messages.pets import (
            MonsterCardLottoEntry, MonsterCardLottoRegAck, MonsterCardLottoRegReq,
        )
        req = MonsterCardLottoRegReq.decode(body)
        char = self.current_char()
        cur_ar = int(char.get('gold', 0)) if char else 0
        entry = MonsterCardLottoEntry(reg_uid=1, char_uid=self.char_id or 0, lotto_key=1, numbers=req.numbers)
        await self.reply(MonsterCardLottoRegAck(result=0, entry=entry, event_cards_out={}, cur_ar=cur_ar),
                         correlation, note='monster card lotto reg ack')

    @packet_handler(2636)
    async def handle_monster_card_get_reward_lotto(self, correlation, body):
        from darkblood.games.network.messages.pets import (
            MonsterCardGetRewardLottoAck, MonsterCardGetRewardLottoReq,
        )
        req = MonsterCardGetRewardLottoReq.decode(body)
        await self.reply(MonsterCardGetRewardLottoAck(result=0, lotto_reg_uid=req.lotto_reg_uid, rank=1, items=[]),
                         correlation, note=f'monster card lotto reward ack (uid={req.lotto_reg_uid})')

    @packet_handler(2638)
    async def handle_monster_card_get_reward_point_arrival(self, correlation, body):
        from darkblood.games.network.messages.pets import (
            MonsterCardGetRewardPointArrivalAck, MonsterCardGetRewardPointArrivalReq,
        )
        req = MonsterCardGetRewardPointArrivalReq.decode(body)
        await self.reply(MonsterCardGetRewardPointArrivalAck(result=0, choice_point=req.choice_point, items=[]),
                         correlation, note=f'monster card point reward ack (pt={req.choice_point})')

    # Helper for item use integration
    async def apply_pet_or_mount_item(self, char, code):
        """When an inventory item starting with PetCall or ridecall is consumed."""
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
            self.store().save()
        elif code.startswith('ridecall'):
            mounts = char.setdefault('mounts', [])
            try:
                num = int(''.join(c for c in code if c.isdigit()))
            except ValueError:
                num = 0
            ride_id = num + 1
            if not any(m.get('ride_id') == ride_id for m in mounts):
                mounts.append({
                    'ride_id': ride_id,
                    'code': code,
                    'name': 'Mount',
                    'expire_time': 0,
                })
            self.store().save()
