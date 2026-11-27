"""Quest NPC services: Kairo (Act/Making), NPC item sealing and quest item drops."""
from darkblood.games.entities.items import Item, UPDATE_OWNER
from darkblood.games.network import results
from darkblood.games.network.messages import (
    ActKairoAck,
    ActKairoReq,
    KairoResult,
    NpcMakingKairoAck,
    NpcMakingKairoReq,
    NpcSealItemAck,
    NpcSealItemReq,
    QuestItemDropAck,
    QuestItemDropReq,
)
from darkblood.games.dispatcher import packet_handler
from darkblood.games.game_data.life_skills import gathering_kairo, making_kairo
from darkblood.player_management.characters import gold_of


class QuestNpcHandlers:
    @packet_handler(ActKairoReq)
    async def handle_act_kairo(self, correlation: int, body: bytes):
        """Opcode 2177 (eEGS_ACT_KAIRO_REQ) -> 2178 (eEGS_ACT_KAIRO_ACK): execute Kairo box/action."""
        req = ActKairoReq.decode(body)
        self.transport.record('act-kairo-req', body, kairo_id=req.kairo_id, param=req.param)
        if req.kairo_id in gathering_kairo():
            await self.session.life.handle_gathering(correlation, req)
            return
        if req.kairo_id in making_kairo():
            await self.session.life.handle_making(correlation, req.kairo_id, ActKairoAck)
            return
        char = self.current_char()
        gold = gold_of(char)
        await self.reply(
            ActKairoAck(result=0, kairo=KairoResult(kairo_id=req.kairo_id), remain_gold=gold),
            correlation, note=f'act kairo ack ({req.kairo_id})',
        )

    @packet_handler(NpcMakingKairoReq)
    async def handle_npc_making_kairo(self, correlation: int, body: bytes):
        """Opcode 2496 (eEGS_NPC_MAKING_KAIRO_REQ) -> 2497 (eEGS_NPC_MAKING_KAIRO_ACK): NPC Kairo crafting."""
        req = NpcMakingKairoReq.decode(body)
        self.transport.record('npc-making-kairo-req', body, kairo_id=req.kairo_id)
        if req.kairo_id in making_kairo():
            await self.session.life.handle_making(correlation, req.kairo_id, NpcMakingKairoAck)
            return
        char = self.current_char()
        gold = gold_of(char)
        await self.reply(
            NpcMakingKairoAck(result=0, kairo=KairoResult(kairo_id=req.kairo_id), remain_gold=gold),
            correlation, note=f'npc making kairo ack ({req.kairo_id})',
        )

    @packet_handler(NpcSealItemReq)
    async def handle_npc_seal_item(self, correlation: int, body: bytes):
        """Opcode 2728 (eEGS_NPC_SEAL_ITEM_REQ) -> 2729 (eEGS_NPC_SEAL_ITEM_ACK): seal an equipment item at NPC."""
        req = NpcSealItemReq.decode(body)
        self.transport.record('npc-seal-item-req', body, item_uid=req.item_uid)
        char = self.current_char()
        items = char.get('items', []) if char else []
        target = next((i for i in items if i.get('uid') == req.item_uid), None)
        if not target:
            await self.reply(NpcSealItemAck(result=results.INVEN_ITEM_NOT_FOUND), correlation,
                             note=f'npc seal item fail (uid={req.item_uid} not found)')
            return
        gold = gold_of(char)
        await self.reply(
            NpcSealItemAck(result=0, items=[Item(owner=UPDATE_OWNER, **target)], remain_gold=gold),
            correlation, note=f'npc seal item ack (uid={req.item_uid})',
        )

    @packet_handler(QuestItemDropReq)
    async def handle_quest_item_drop(self, correlation: int, body: bytes):
        """Opcode 5382 (eERC_QUESTITEM_DROP_REQ) -> 5383 (eERC_QUESTITEM_DROP_ACK): spawn quest item floor drop."""
        req = QuestItemDropReq.decode(body)
        self.transport.record('quest-item-drop-req', body, mission_id=req.mission_id, layer_id=req.layer_id)
        await self.reply(
            QuestItemDropAck(
                result=0,
                mission_id=req.mission_id,
                layer_id=req.layer_id,
                pos_x=req.pos_x,
                pos_y=req.pos_y,
                jump=req.jump,
                drops=[],
            ),
            correlation, note=f'quest item drop ack (mission={req.mission_id:#010x})',
        )
