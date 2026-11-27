"""Upgrading, durability repair, enchanting, avatar/zam, smelting and mark handlers."""
from darkblood.games.network import results
from darkblood.core.hashing import jhash
from darkblood.games.dispatcher import packet_handler
from darkblood.games.entities.items import Item, UPDATE_OWNER
from darkblood.games.network.messages import (
    AvatarChangerAck,
    AvatarChangerReq,
    AvatarMergeAck,
    AvatarMergeReq,
    AvatarZamEraseAck,
    AvatarZamEraseReq,
    AvatarZamInsertAck,
    AvatarZamInsertReq,
    AvatarZamMergeAck,
    AvatarZamMergeReq,
    AvatarZamSeparateAck,
    AvatarZamSeparateReq,
    DurabilityRepairAck,
    DurabilityRepairByItemReq,
    DurabilityRepairReq,
    FixItemUpgradeAck,
    FixItemUpgradeReq,
    ItemClassSmeltingAck,
    ItemClassSmeltingReq,
    ItemSpiritChangeAck,
    ItemSpiritChangeReq,
    ItemUpgradeAck,
    ItemUpgradeReq,
    MagicEnchantEnchantAck,
    MagicEnchantEnchantReq,
    MagicEnchantEraseOptionAck,
    MagicEnchantEraseOptionReq,
    MagicEnchantExpendSlotAck,
    MagicEnchantExpendSlotReq,
    MarkOptionChangeAck,
    MarkOptionChangeReq,
    RandomItemUpgradeAck,
    RandomItemUpgradeReq,
    RandomOptionChangeAck,
    RandomOptionChangeReq,
    RareAvatarChangeLookAck,
    RareAvatarChangeLookReq,
)
from darkblood.player_management.characters import gold_of


class CraftingHandlersMixin:
    """Item enhancement, durability repair, enchanting, avatar/zam, smelting and marks."""

    @packet_handler(ItemUpgradeReq)
    async def handle_item_upgrade(self, correlation, body):
        """Opcode 2115 (eEGS_ITEM_UPGRADE_REQ) -> 2116 (eEGS_ITEM_UPGRADE_ACK): upgrade equipment tier."""
        req = ItemUpgradeReq.decode(body)
        self.transport.record('item-upgrade-req', body, target=req.target_uid,
                              catalyst=req.catalyst_uid, protect=req.protect_uid)
        # Upgrading is not implemented yet: every request is refused.
        await self.reply(ItemUpgradeAck(result=results.INVALID_STATE), correlation, note=f'item upgrade ack (target={req.target_uid})')

    @packet_handler(DurabilityRepairReq)
    async def handle_durability_repair(self, correlation, body):
        """Opcode 2145 (eEGS_DURABILITY_REPAIR_REQ) -> 2146 (eEGS_DURABILITY_REPAIR_ACK): repair equipment with AR.

        Client formula (0x00525ea0 Lua_ShowMessageRepairEquipItem / 0x00525af0):
          max_dur = *(short *)(item_dict + 0xBE)  (integer-truncated Durability)
          missing = max(0, max_dur - ceil(cur_dur))
          cost    = missing * *(short *)(item_dict + 0xC2)  (RepairPrice)
        """
        import math
        from darkblood.games.game_data.client_dict import item_field, item_max_durability
        req = DurabilityRepairReq.decode(body)
        self.transport.record('durability-repair-req', body, count=len(req.repair_items))
        char = self.current_char()
        if char is None:
            await self.reply(DurabilityRepairAck(result=1, remain_gold=0), correlation,
                             note='durability repair ack (no char)')
            return
        gold = gold_of(char)
        items_by_uid = {int(it.get('uid', -1)): it for it in char.get('items', [])}
        repaired = {}
        total_cost = 0
        for item_uid, req_dur in req.repair_items.items():
            item = items_by_uid.get(int(item_uid))
            if item is None:
                continue
            code = item.get('code', '')
            max_dur = item_max_durability(code)
            target_dur = float(int(max_dur)) if max_dur is not None else 100.0
            stored_dur = float(item.get('durability', target_dur))
            # Client sends its current durability float; use the lower of stored and reported
            # (clamped to [0, target_dur]) in case a 2143 durability tick has not flushed yet.
            cur_dur = max(0.0, min(stored_dur, float(req_dur), target_dur))
            missing = max(0, int(target_dur) - math.ceil(cur_dur))
            if missing > 0:
                repair_price = int(item_field(code, 'RepairPrice', 0) or 0)
                total_cost += missing * repair_price
            repaired[int(item_uid)] = target_dur
        if total_cost > gold:
            await self.reply(DurabilityRepairAck(result=1, remain_gold=gold), correlation,
                             note=f'durability repair refused (need {total_cost} AR, have {gold})')
            return
        for item_uid, target_dur in repaired.items():
            items_by_uid[item_uid]['durability'] = target_dur
        gold -= total_cost
        char['gold'] = gold
        if repaired:
            self.save_char()
        await self.reply(DurabilityRepairAck(result=0, repaired_items=repaired, remain_gold=gold), correlation,
                         note=f'durability repair ack ({len(repaired)} items, -{total_cost} AR)')

    @packet_handler(DurabilityRepairByItemReq)
    async def handle_durability_repair_by_item(self, correlation, body):
        """Opcode 2154 (eEGS_DURABILITY_REPAIR_BY_ITEM_REQ) -> 2146: repair equipment using a repair kit item."""
        from darkblood.games.game_data.client_dict import item_max_durability
        req = DurabilityRepairByItemReq.decode(body)
        self.transport.record('durability-repair-by-item-req', body,
                              count=len(req.repair_items), kit=req.repair_item_uid)
        char = self.current_char()
        if char is None:
            await self.reply(DurabilityRepairAck(result=1, remain_gold=0), correlation,
                             note='durability repair by item ack (no char)')
            return
        gold = gold_of(char)
        items = char.get('items', [])
        items_by_uid = {int(it.get('uid', -1)): it for it in items}
        repaired = {}
        for item_uid in req.repair_items:
            item = items_by_uid.get(int(item_uid))
            if item is None:
                continue
            max_dur = item_max_durability(item.get('code', ''))
            target_dur = float(int(max_dur)) if max_dur is not None else 100.0
            item['durability'] = target_dur
            repaired[int(item_uid)] = target_dur
        kit = items_by_uid.get(int(req.repair_item_uid))
        if kit is not None and repaired:
            cnt = int(kit.get('count', 1))
            if cnt > 1:
                kit['count'] = cnt - 1
            else:
                items.remove(kit)
        if repaired:
            self.save_char()
        await self.reply(DurabilityRepairAck(result=0, repaired_items=repaired, remain_gold=gold), correlation,
                         note=f'durability repair by item ack ({len(repaired)} items)')

    @packet_handler(MagicEnchantEnchantReq)
    async def handle_magic_enchant(self, correlation, body):
        """Opcode 2254 (eEGS_MAGICENCHANT_ENCHANT_REQ) -> 2255 (eEGS_MAGICENCHANT_ENCHANT_ACK): apply magic enchant."""
        req = MagicEnchantEnchantReq.decode(body)
        self.transport.record('magicenchant-enchant-req', body, item_uid=req.item_uid)
        char = self.current_char()
        gold = gold_of(char)
        await self.reply(MagicEnchantEnchantAck(result=0, items=[], gold=gold), correlation,
                         note=f'magicenchant enchant ack (item={req.item_uid})')

    @packet_handler(MagicEnchantEraseOptionReq)
    async def handle_magic_enchant_erase_option(self, correlation, body):
        """Opcode 2256 (eEGS_MAGICENCHANT_ERASE_OPTION_REQ) -> 2257: erase an enchant option from an item."""
        req = MagicEnchantEraseOptionReq.decode(body)
        self.transport.record('magicenchant-erase-option-req', body, item_uid=req.item_uid)
        char = self.current_char()
        gold = gold_of(char)
        await self.reply(MagicEnchantEraseOptionAck(result=0, items=[], gold=gold), correlation,
                         note=f'magicenchant erase option ack (item={req.item_uid})')

    @packet_handler(MagicEnchantExpendSlotReq)
    async def handle_magic_enchant_expand_slot(self, correlation, body):
        """Opcode 2258 (eEGS_MAGICENCHANT_EXPEND_SLOT_REQ) -> 2259: unlock an extra magic enchant slot."""
        req = MagicEnchantExpendSlotReq.decode(body)
        self.transport.record('magicenchant-expend-slot-req', body, item_uid=req.item_uid)
        await self.reply(MagicEnchantExpendSlotAck(result=0, items=[]), correlation,
                         note=f'magicenchant expend slot ack (item={req.item_uid})')

    @packet_handler(RandomItemUpgradeReq)
    async def handle_random_item_upgrade(self, correlation, body):
        """Opcode 2284 (eEGS_RANDOM_ITEM_UPGRADE_REQ) -> 2285: perform a random upgrade roll."""
        req = RandomItemUpgradeReq.decode(body)
        self.transport.record('random-item-upgrade-req', body, item_uid=req.item_uid)
        await self.reply(RandomItemUpgradeAck(result=0, items=[]), correlation,
                         note=f'random item upgrade ack (item={req.item_uid})')

    @packet_handler(ItemSpiritChangeReq)
    async def handle_item_spirit_change(self, correlation, body):
        """Opcode 2338 (eEGS_ITEM_SPIRIT_CHANGE_REQ) -> 2339: imbue or swap weapon spirit."""
        req = ItemSpiritChangeReq.decode(body)
        self.transport.record('item-spirit-change-req', body, item_uid=req.item_uid)
        await self.reply(ItemSpiritChangeAck(result=0, spirit_uid=req.spirit_item_uid, items=[]), correlation,
                         note=f'item spirit change ack (spirit={req.spirit_item_uid})')

    @packet_handler(AvatarZamInsertReq)
    async def handle_avatar_zam_insert(self, correlation, body):
        """Opcode 2362 (eEGS_AVATAR_ZAM_INSERT_REQ) -> 2363: socket an Avatar Zam gem."""
        req = AvatarZamInsertReq.decode(body)
        self.transport.record('avatar-zam-insert-req', body,
                              avatar_uid=req.avatar_item_uid, zam_uid=req.zam_item_uid)
        await self.reply(AvatarZamInsertAck(result=0, updated_items=[]), correlation,
                         note=f'avatar zam insert ack (avatar={req.avatar_item_uid})')

    @packet_handler(AvatarZamEraseReq)
    async def handle_avatar_zam_erase(self, correlation, body):
        """Opcode 2364 (eEGS_AVATAR_ZAM_ERASE_REQ) -> 2365: destroy a socketed Avatar Zam gem."""
        req = AvatarZamEraseReq.decode(body)
        self.transport.record('avatar-zam-erase-req', body, avatar_uid=req.avatar_item_uid)
        await self.reply(AvatarZamEraseAck(result=0, updated_items=[]), correlation,
                         note=f'avatar zam erase ack (avatar={req.avatar_item_uid})')

    @packet_handler(AvatarZamMergeReq)
    async def handle_avatar_zam_merge(self, correlation, body):
        """Opcode 2408 (eEGS_AVATAR_ZAM_MERGE_REQ) -> 2409: merge two Avatar Zam gems."""
        req = AvatarZamMergeReq.decode(body)
        self.transport.record('avatar-zam-merge-req', body, zam1=req.zam1_uid, zam2=req.zam2_uid)
        await self.reply(AvatarZamMergeAck(result=0, items=[], result_zam_id=0), correlation,
                         note=f'avatar zam merge ack (zam1={req.zam1_uid})')

    @packet_handler(AvatarMergeReq)
    async def handle_avatar_merge(self, correlation, body):
        """Opcode 2432 (eEGS_AVATAR_MERGE_REQ) -> 2433: combine two avatar pieces."""
        req = AvatarMergeReq.decode(body)
        self.transport.record('avatar-merge-req', body, avatar1=req.avatar1_uid, avatar2=req.avatar2_uid)
        await self.reply(AvatarMergeAck(result=0, items=[], result_avatar_uid=req.avatar1_uid, zam_uids=[]),
                         correlation, note=f'avatar merge ack (avatar1={req.avatar1_uid})')

    @packet_handler(AvatarChangerReq)
    async def handle_avatar_changer(self, correlation, body):
        """Opcode 2543 (eEGS_AVATAR_CHANGER_REQ) -> 2544: reroll an avatar item via changer."""
        req = AvatarChangerReq.decode(body)
        char = self.current_char()
        items = char.get('items', []) if char else []
        target = next((i for i in items if i.get('uid') == req.target_avatar_uid), None)
        res_id = jhash(target.get('code', '')) if target else 0
        await self.reply(
            AvatarChangerAck(result=0, items=[], target_item_uid=req.target_avatar_uid, result_item_id=res_id),
            correlation, note=f'avatar changer ack (target={req.target_avatar_uid})')

    @packet_handler(RandomOptionChangeReq)
    async def handle_random_option_change(self, correlation, body):
        """Opcode 2547 (eEGS_RANDOM_OPTION_CHANGE_REQ) -> 2548: reroll random bonus options on an item."""
        req = RandomOptionChangeReq.decode(body)
        char = self.current_char()
        gold = gold_of(char)
        items = char.get('items', []) if char else []
        target = next((i for i in items if i.get('uid') == req.item_uid), None)
        out = [Item(owner=UPDATE_OWNER, **target)] if target else []
        await self.reply(
            RandomOptionChangeAck(result=0, target_item_uid=req.item_uid, items=out, current_gold=gold),
            correlation, note=f'random option change ack (uid={req.item_uid})')

    @packet_handler(RareAvatarChangeLookReq)
    async def handle_rare_avatar_change_look(self, correlation, body):
        """Opcode 2583 (eEGS_RAREAVATAR_CHANGE_LOOK_REQ) -> 2584: transmog a rare avatar appearance."""
        req = RareAvatarChangeLookReq.decode(body)
        await self.reply(RareAvatarChangeLookAck(result=0, target_item_uid=req.target_avatar_uid, items=[]),
                         correlation, note=f'rare avatar change look ack (target={req.target_avatar_uid})')

    @packet_handler(AvatarZamSeparateReq)
    async def handle_avatar_zam_separate(self, correlation, body):
        """Opcode 2597 (eEGS_AVATAR_ZAM_SEPARATE_REQ) -> 2598: safely extract a socketed Avatar Zam gem."""
        req = AvatarZamSeparateReq.decode(body)
        await self.reply(AvatarZamSeparateAck(result=0, items=[]), correlation,
                         note=f'avatar zam separate ack (target={req.target_item_uid} zam={req.zam_id:08x})')

    @packet_handler(ItemClassSmeltingReq)
    async def handle_item_class_smelting(self, correlation, body):
        """Opcode 2629 (eEGS_ITEM_CLASS_SMELTING_REQ) -> 2630: smelt an item into a target class item."""
        req = ItemClassSmeltingReq.decode(body)
        char = self.current_char()
        gold = gold_of(char)
        await self.reply(ItemClassSmeltingAck(result=0, items=[], current_gold=gold), correlation,
                         note=f'item class smelting ack (item={req.use_item_uid})')

    @packet_handler(FixItemUpgradeReq)
    async def handle_fix_item_upgrade(self, correlation, body):
        """Opcode 2672 (eEGS_FIX_ITEM_UPGRADE_REQ) -> 2673: perform a guaranteed fixed-tier upgrade."""
        req = FixItemUpgradeReq.decode(body)
        self.transport.record('fix-item-upgrade-req', body, item_uid=req.item_uid)
        await self.reply(FixItemUpgradeAck(result=0, items=[]), correlation,
                         note=f'fix item upgrade ack (item={req.item_uid})')

    @packet_handler(MarkOptionChangeReq)
    async def handle_mark_option_change(self, correlation, body):
        """Opcode 2701 (eEGS_MARK_OPTION_CHANGE_REQ) -> 2702 (eEGS_MARK_OPTION_CHANGE_ACK): reroll mark item options."""
        req = MarkOptionChangeReq.decode(body)
        char = self.current_char()
        gold = gold_of(char)
        items = char.get('items', []) if char else []
        target = next((i for i in items if i.get('uid') == req.target_item_uid), None)
        out = [Item(owner=UPDATE_OWNER, **target)] if target else []
        await self.reply(
            MarkOptionChangeAck(result=0, target_item_uid=req.target_item_uid, items=out, current_gold=gold),
            correlation, note=f'mark option change ack (target={req.target_item_uid})')
