"""Upgrading, durability repair, enchanting, avatar/zam, smelting and mark handlers."""
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


class CraftingHandlersMixin:
    """Item enhancement, durability repair, enchanting, avatar/zam, smelting and marks."""

    @packet_handler(ItemUpgradeReq)
    async def handle_item_upgrade(self, correlation, body):
        """Opcode 2115 (eEGS_ITEM_UPGRADE_REQ) -> 2116 (eEGS_ITEM_UPGRADE_ACK): upgrade equipment tier."""
        req = ItemUpgradeReq.decode(body)
        self.transport.record('item-upgrade-req', body, target=req.target_uid,
                              catalyst=req.catalyst_uid, protect=req.protect_uid)
        await self.reply(ItemUpgradeAck(result=1), correlation, note=f'item upgrade ack (target={req.target_uid})')

    @packet_handler(DurabilityRepairReq)
    async def handle_durability_repair(self, correlation, body):
        """Opcode 2145 (eEGS_DURABILITY_REPAIR_REQ) -> 2146 (eEGS_DURABILITY_REPAIR_ACK): repair equipment with AR."""
        DurabilityRepairReq.decode(body)
        self.transport.record('durability-repair-req', body)
        char = self.current_char()
        gold = char.get('gold', 100000) if char else 100000
        await self.reply(DurabilityRepairAck(result=0, remain_gold=gold), correlation,
                         note='durability repair ack (success, 0 items repaired)')

    @packet_handler(DurabilityRepairByItemReq)
    async def handle_durability_repair_by_item(self, correlation, body):
        """Opcode 2154 (eEGS_DURABILITY_REPAIR_BY_ITEM_REQ) -> 2146: repair equipment using a repair kit item."""
        DurabilityRepairByItemReq.decode(body)
        self.transport.record('durability-repair-by-item-req', body)
        char = self.current_char()
        gold = char.get('gold', 100000) if char else 100000
        await self.reply(DurabilityRepairAck(result=0, repaired_items={}, remain_gold=gold), correlation,
                         note='durability repair by item ack')

    @packet_handler(MagicEnchantEnchantReq)
    async def handle_magic_enchant(self, correlation, body):
        """Opcode 2254 (eEGS_MAGICENCHANT_ENCHANT_REQ) -> 2255 (eEGS_MAGICENCHANT_ENCHANT_ACK): apply magic enchant."""
        req = MagicEnchantEnchantReq.decode(body)
        self.transport.record('magicenchant-enchant-req', body, item_uid=req.item_uid)
        char = self.current_char()
        gold = char.get('gold', 1000) if char else 1000
        await self.reply(MagicEnchantEnchantAck(result=0, items=[], gold=gold), correlation,
                         note=f'magicenchant enchant ack (item={req.item_uid})')

    @packet_handler(MagicEnchantEraseOptionReq)
    async def handle_magic_enchant_erase_option(self, correlation, body):
        """Opcode 2256 (eEGS_MAGICENCHANT_ERASE_OPTION_REQ) -> 2257: erase an enchant option from an item."""
        req = MagicEnchantEraseOptionReq.decode(body)
        self.transport.record('magicenchant-erase-option-req', body, item_uid=req.item_uid)
        char = self.current_char()
        gold = char.get('gold', 1000) if char else 1000
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
        gold = char.get('gold', 0) if char else 0
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
        gold = char.get('gold', 0) if char else 0
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
        gold = char.get('gold', 0) if char else 0
        items = char.get('items', []) if char else []
        target = next((i for i in items if i.get('uid') == req.target_item_uid), None)
        out = [Item(owner=UPDATE_OWNER, **target)] if target else []
        await self.reply(
            MarkOptionChangeAck(result=0, target_item_uid=req.target_item_uid, items=out, current_gold=gold),
            correlation, note=f'mark option change ack (target={req.target_item_uid})')
