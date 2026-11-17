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
from darkblood.games.handlers.base import BaseDomainService


class PetHandlers(BaseDomainService):
    """Pet summoning, evolution, feeding, mounts, and monster taming."""

    # --- Monster Taming (2348, 2350) ---

    async def on_2348(self, correlation, body):
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
        ack = TamingMonsterInsertAck(result=0, monsters=tamed).encode()
        await self.transport.send_event(event(2349, ack, correlation),
                                        note=f'tame monster insert ack (monster={req.monster_id}, slot={slot})')

    async def on_2350(self, correlation, body):
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
        ack = TamingMonsterDeleteAck(result=0, monsters=tamed, deleted_slot=req.slot).encode()
        await self.transport.send_event(event(2351, ack, correlation),
                                        note=f'tame monster delete ack (slot={req.slot})')

    # --- Mounts / Riding (2434, 2437) ---

    async def on_2434(self, correlation, body):
        # eEGS_RIDING_GET_LIST_REQ -> 2435 eEGS_RIDING_GET_LIST_ACK (0x0076C5A0)
        char = self.current_char()
        mounts = char.get('mounts', []) if char else []
        ack = RidingGetListAck(result=0, rides=mounts).encode()
        await self.transport.send_event(event(2435, ack, correlation),
                                        note=f'riding get list ack (count={len(mounts)})')

    async def on_2437(self, correlation, body):
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

    async def on_2464(self, correlation, body):
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
        ack = PetCreateAck(result=0, pets=pets, slot=new_pet['slot']).encode()
        await self.transport.send_event(event(2465, ack, correlation),
                                        note=f'pet create ack (uid={new_uid})')

    async def on_2466(self, correlation, body):
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

    async def on_2468(self, correlation, body):
        # eEGS_PET_SUMMON_REQ (0x0079E3E0) -> 2469 eEGS_PET_SUMMON_ACK (0x0079ECF0)
        req = PetSummonReq.decode(body)
        char = self.current_char()
        if not char:
            await self.transport.send_event(event(2469, PetSummonAck(result=1).encode(), correlation),
                                            note='pet summon fail (no char)')
            return
        char['summoned_pet'] = req.pet_slot
        self.store().save()
        ack = PetSummonAck(result=0, pet_slot=req.pet_slot).encode()
        await self.transport.send_event(event(2469, ack, correlation),
                                        note=f'pet summon ack (slot={req.pet_slot})')

    async def on_2470(self, correlation, body):
        # eEGS_PET_RELEASE_SUMMON_REQ (0x0079E510) -> 2471 eEGS_PET_RELEASE_SUMMON_ACK (0x0079EEE0)
        char = self.current_char()
        if char:
            char['summoned_pet'] = None
            self.store().save()
        ack = PetReleaseSummonAck(result=0).encode()
        await self.transport.send_event(event(2471, ack, correlation),
                                        note='pet release summon ack')

    async def on_2473(self, correlation, body):
        # eEGS_PET_SAVE_REQ -> 2474 eEGS_PET_SAVE_ACK (0x007758B0)
        ack = PetSaveAck(result=0, value=1).encode()
        await self.transport.send_event(event(2474, ack, correlation), note='pet save ack')

    async def on_2475(self, correlation, body):
        # eEGS_PET_LOAD_REQ (0x0079F320) -> 2476 eEGS_PET_LOAD_ACK (0x0079F560)
        req = PetLoadReq.decode(body)
        char = self.current_char()
        if char and req.pet_uid:
            char['summoned_pet'] = req.pet_uid
            self.store().save()
        ack = PetLoadAck(result=0, pet_uid=req.pet_uid).encode()
        await self.transport.send_event(event(2476, ack, correlation),
                                        note=f'pet load ack (uid={req.pet_uid})')

    async def on_2477(self, correlation, body):
        # eEGS_PET_REPLACE_REQ -> 2478 eEGS_PET_REPLACE_ACK (0x0079F770)
        req = PetReplaceReq.decode(body)
        char = self.current_char()
        if char and req.pet_uid:
            char['summoned_pet'] = req.pet_uid
            self.store().save()
        ack = PetReplaceAck(result=0, pet_uid=req.pet_uid).encode()
        await self.transport.send_event(event(2478, ack, correlation),
                                        note=f'pet replace ack (uid={req.pet_uid})')

    async def on_2480(self, correlation, body):
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
        ack = PetEatNormalAck(result=0, pets=char.get('pets', []) if char else [], satiety=satiety, status=1).encode()
        await self.transport.send_event(event(2481, ack, correlation),
                                        note=f'pet eat normal ack (satiety={satiety})')

    async def on_2484(self, correlation, body):
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

    async def on_2508(self, correlation, body):
        # Compatibility / PetCall summon request -> responds with 2469
        req = PetSummonReq.decode(body)
        char = self.current_char()
        if char:
            char['summoned_pet'] = req.pet_slot
            self.store().save()
        ack = PetSummonAck(result=0, pet_slot=req.pet_slot).encode()
        await self.transport.send_event(event(2469, ack, correlation),
                                        note=f'pet call / summon ack (slot={req.pet_slot})')

    async def on_2510(self, correlation, body):
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

    # Helper for item use integration
    async def _apply_pet_or_mount_item(self, char, code):
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
