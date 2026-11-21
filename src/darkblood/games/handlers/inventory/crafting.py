"""Upgrading, durability repair, enchanting, avatar/zam, smelting and mark handlers."""
from darkblood.core.hashing import jhash
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

    async def on_2115(self, correlation, body):
        # eEGS_ITEM_UPGRADE_REQ -> 2116 eEGS_ITEM_UPGRADE_ACK (0x007909C0).
        req = ItemUpgradeReq.decode(body)
        self.transport.record('item-upgrade-req', body, target=req.target_uid,
                              catalyst=req.catalyst_uid, protect=req.protect_uid)
        await self.reply(ItemUpgradeAck(result=1), correlation, note=f'item upgrade ack (target={req.target_uid})')

    async def on_2145(self, correlation, body):
        # eEGS_DURABILITY_REPAIR_REQ -> 2146 eEGS_DURABILITY_REPAIR_ACK (0x007930D0).
        DurabilityRepairReq.decode(body)
        self.transport.record('durability-repair-req', body)
        char = self.current_char()
        gold = char.get('gold', 100000) if char else 100000
        await self.reply(DurabilityRepairAck(result=0, remain_gold=gold), correlation,
                         note='durability repair ack (success, 0 items repaired)')

    async def on_2154(self, correlation, body):
        # eEGS_DURABILITY_REPAIR_BY_ITEM_REQ (0x00792E40) -> 2146 eEGS_DURABILITY_REPAIR_ACK.
        DurabilityRepairByItemReq.decode(body)
        self.transport.record('durability-repair-by-item-req', body)
        char = self.current_char()
        gold = char.get('gold', 100000) if char else 100000
        await self.reply(DurabilityRepairAck(result=0, repaired_items={}, remain_gold=gold), correlation,
                         note='durability repair by item ack')

    async def on_2254(self, correlation, body):
        # eEGS_MAGICENCHANT_ENCHANT_REQ -> 2255 eEGS_MAGICENCHANT_ENCHANT_ACK (0x00796DC0).
        req = MagicEnchantEnchantReq.decode(body)
        self.transport.record('magicenchant-enchant-req', body, item_uid=req.item_uid)
        char = self.current_char()
        gold = char.get('gold', 1000) if char else 1000
        await self.reply(MagicEnchantEnchantAck(result=0, items=[], gold=gold), correlation,
                         note=f'magicenchant enchant ack (item={req.item_uid})')

    async def on_2256(self, correlation, body):
        # eEGS_MAGICENCHANT_ERASE_OPTION_REQ -> 2257 eEGS_MAGICENCHANT_ERASE_OPTION_ACK (0x00797120).
        req = MagicEnchantEraseOptionReq.decode(body)
        self.transport.record('magicenchant-erase-option-req', body, item_uid=req.item_uid)
        char = self.current_char()
        gold = char.get('gold', 1000) if char else 1000
        await self.reply(MagicEnchantEraseOptionAck(result=0, items=[], gold=gold), correlation,
                         note=f'magicenchant erase option ack (item={req.item_uid})')

    async def on_2258(self, correlation, body):
        # eEGS_MAGICENCHANT_EXPEND_SLOT_REQ -> 2259 eEGS_MAGICENCHANT_EXPEND_SLOT_ACK (0x0077FC60).
        req = MagicEnchantExpendSlotReq.decode(body)
        self.transport.record('magicenchant-expend-slot-req', body, item_uid=req.item_uid)
        await self.reply(MagicEnchantExpendSlotAck(result=0, items=[]), correlation,
                         note=f'magicenchant expend slot ack (item={req.item_uid})')

    async def on_2284(self, correlation, body):
        # eEGS_RANDOM_ITEM_UPGRADE_REQ -> 2285 eEGS_RANDOM_ITEM_UPGRADE_ACK (0x0077FED0).
        req = RandomItemUpgradeReq.decode(body)
        self.transport.record('random-item-upgrade-req', body, item_uid=req.item_uid)
        await self.reply(RandomItemUpgradeAck(result=0, items=[]), correlation,
                         note=f'random item upgrade ack (item={req.item_uid})')

    async def on_2338(self, correlation, body):
        # eEGS_ITEM_SPIRIT_CHANGE_REQ -> 2339 eEGS_ITEM_SPIRIT_CHANGE_ACK (0x00780860).
        req = ItemSpiritChangeReq.decode(body)
        self.transport.record('item-spirit-change-req', body, item_uid=req.item_uid)
        await self.reply(ItemSpiritChangeAck(result=0, spirit_uid=req.spirit_item_uid, items=[]), correlation,
                         note=f'item spirit change ack (spirit={req.spirit_item_uid})')

    async def on_2362(self, correlation, body):
        # eEGS_AVATAR_ZAM_INSERT_REQ -> 2363 eEGS_AVATAR_ZAM_INSERT_ACK (0x00782D00).
        req = AvatarZamInsertReq.decode(body)
        self.transport.record('avatar-zam-insert-req', body,
                              avatar_uid=req.avatar_item_uid, zam_uid=req.zam_item_uid)
        await self.reply(AvatarZamInsertAck(result=0, updated_items=[]), correlation,
                         note=f'avatar zam insert ack (avatar={req.avatar_item_uid})')

    async def on_2364(self, correlation, body):
        # eEGS_AVATAR_ZAM_ERASE_REQ -> 2365 eEGS_AVATAR_ZAM_ERASE_ACK (0x00782F40).
        req = AvatarZamEraseReq.decode(body)
        self.transport.record('avatar-zam-erase-req', body, avatar_uid=req.avatar_item_uid)
        await self.reply(AvatarZamEraseAck(result=0, updated_items=[]), correlation,
                         note=f'avatar zam erase ack (avatar={req.avatar_item_uid})')

    async def on_2408(self, correlation, body):
        # eEGS_AVATAR_ZAM_MERGE_REQ (0x0079B100) -> 2409 eEGS_AVATAR_ZAM_MERGE_ACK (0x00780AF0).
        req = AvatarZamMergeReq.decode(body)
        self.transport.record('avatar-zam-merge-req', body, zam1=req.zam1_uid, zam2=req.zam2_uid)
        await self.reply(AvatarZamMergeAck(result=0, items=[], result_zam_id=0), correlation,
                         note=f'avatar zam merge ack (zam1={req.zam1_uid})')

    async def on_2432(self, correlation, body):
        # eEGS_AVATAR_MERGE_REQ (0x004A6C10) -> 2433 eEGS_AVATAR_MERGE_ACK (0x004B9DA0).
        req = AvatarMergeReq.decode(body)
        self.transport.record('avatar-merge-req', body, avatar1=req.avatar1_uid, avatar2=req.avatar2_uid)
        await self.reply(AvatarMergeAck(result=0, items=[], result_avatar_uid=req.avatar1_uid, zam_uids=[]),
                         correlation, note=f'avatar merge ack (avatar1={req.avatar1_uid})')

    async def on_2543(self, correlation, body):
        # eEGS_AVATAR_CHANGER_REQ (0x004A5B90) -> 2544 eEGS_AVATAR_CHANGER_ACK (0x004B99D0).
        req = AvatarChangerReq.decode(body)
        char = self.current_char()
        items = char.get('items', []) if char else []
        target = next((i for i in items if i.get('uid') == req.target_avatar_uid), None)
        res_id = jhash(target.get('code', '')) if target else 0
        await self.reply(
            AvatarChangerAck(result=0, items=[], target_item_uid=req.target_avatar_uid, result_item_id=res_id),
            correlation, note=f'avatar changer ack (target={req.target_avatar_uid})')

    async def on_2547(self, correlation, body):
        # eEGS_RANDOM_OPTION_CHANGE_REQ (0x007A2800) -> 2548 (0x00782830).
        req = RandomOptionChangeReq.decode(body)
        char = self.current_char()
        gold = char.get('gold', 0) if char else 0
        items = char.get('items', []) if char else []
        target = next((i for i in items if i.get('uid') == req.item_uid), None)
        out = [Item(owner=UPDATE_OWNER, **target)] if target else []
        await self.reply(
            RandomOptionChangeAck(result=0, target_item_uid=req.item_uid, items=out, current_gold=gold),
            correlation, note=f'random option change ack (uid={req.item_uid})')

    async def on_2583(self, correlation, body):
        # eEGS_RAREAVATAR_CHANGE_LOOK_REQ (0x0063A120) -> 2584 (0x006395D0).
        req = RareAvatarChangeLookReq.decode(body)
        await self.reply(RareAvatarChangeLookAck(result=0, target_item_uid=req.target_avatar_uid, items=[]),
                         correlation, note=f'rare avatar change look ack (target={req.target_avatar_uid})')

    async def on_2597(self, correlation, body):
        # eEGS_AVATAR_ZAM_SEPARATE_REQ (0x007A4C30) -> 2598 (0x00783190).
        req = AvatarZamSeparateReq.decode(body)
        await self.reply(AvatarZamSeparateAck(result=0, items=[]), correlation,
                         note=f'avatar zam separate ack (target={req.target_item_uid} zam={req.zam_id:08x})')

    async def on_2629(self, correlation, body):
        # eEGS_ITEM_CLASS_SMELTING_REQ (0x007A5440) -> 2630 (0x00783790).
        req = ItemClassSmeltingReq.decode(body)
        char = self.current_char()
        gold = char.get('gold', 0) if char else 0
        await self.reply(ItemClassSmeltingAck(result=0, items=[], current_gold=gold), correlation,
                         note=f'item class smelting ack (item={req.use_item_uid})')

    async def on_2672(self, correlation, body):
        # eEGS_FIX_ITEM_UPGRADE_REQ -> 2673 eEGS_FIX_ITEM_UPGRADE_ACK (0x00783C40).
        req = FixItemUpgradeReq.decode(body)
        self.transport.record('fix-item-upgrade-req', body, item_uid=req.item_uid)
        await self.reply(FixItemUpgradeAck(result=0, items=[]), correlation,
                         note=f'fix item upgrade ack (item={req.item_uid})')

    async def on_2701(self, correlation, body):
        # eEGS_MARK_OPTION_CHANGE_REQ (0x005E1360) -> 2702 (0x005FADE0).
        req = MarkOptionChangeReq.decode(body)
        char = self.current_char()
        gold = char.get('gold', 0) if char else 0
        items = char.get('items', []) if char else []
        target = next((i for i in items if i.get('uid') == req.target_item_uid), None)
        out = [Item(owner=UPDATE_OWNER, **target)] if target else []
        await self.reply(
            MarkOptionChangeAck(result=0, target_item_uid=req.target_item_uid, items=out, current_gold=gold),
            correlation, note=f'mark option change ack (target={req.target_item_uid})')
