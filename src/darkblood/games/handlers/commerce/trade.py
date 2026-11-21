"""Player-to-player trade request, item/gold staking and completion."""
"""Store / NPC commerce, cash shop, Steam purchases, player trade and notices."""
import struct

from darkblood.core.hashing import jhash
from darkblood.core.serialization.jser import event, strip_prefix
from darkblood.games.entities.items import Item, UPDATE_OWNER
from darkblood.games.game_data import cash_shop
from darkblood.games.network.messages import (
    AcceptRequestTradeAck,
    AcceptRequestTradeReq,
    AcceptTradeAck,
    BuyItemAck,
    BuyItemReq,
    CancelTradeAck,
    ContractUpdateAck,
    ContractUpdateReq,
    CurrentCashAck,
    DeleteTradeItemAck,
    DeleteTradeItemReq,
    DragItemAck,
    DurabilityChangeAck,
    DurabilityChangeReq,
    FinallyAcceptTradeAck,
    HttpNoticeCheckAck,
    InsertTradeItemAck,
    InsertTradeItemReq,
    MonsterCardAlbumAck,
    MonsterCardDeckAck,
    MonsterCardListAck,
    StoreRecord,
    PlayOptionUpdateReq,
    RepurchaseItemAck,
    RepurchaseItemReq,
    RequestTradeAck,
    RequestTradeReq,
    RouletteManagerInfoAck,
    SellItemAck,
    SellItemReq,
    SteamFinalizeBuyItemAck,
    SteamInitBuyItemNot,
    StoreInfoAck,
    TamingMonsterDeleteAck,
    TamingMonsterInsertAck,
    UpdateTradeArAck,
    UpdateTradeArReq,
    PersonalShopOpenReq,
    PersonalShopOpenAck,
    PersonalShopCloseReq,
    PersonalShopCloseAck,
    PersonalShopBuyReq,
    PersonalShopBuyAck,
    PersonalShopGetProductsReq,
    PersonalShopGetProductsAck,
    PersonalShopChangeNot,
    PersonalShopStartNot,
    PersonalShopCloseNot,
    BrokerListReq,
    BrokerListAck,
    BrokerMyListReq,
    BrokerMyListAck,
    BrokerRegistItemReq,
    BrokerRegistItemAck,
    BrokerBuyItemReq,
    BrokerBuyItemAck,
    BrokerCancelReq,
    BrokerCancelAck,
    BrokerPriceReq,
    BrokerPriceAck,
    StallItem,
    BrokerProduct,
)
from darkblood.games.stalls import PersonalShopManager, BrokerManager
from darkblood.player_management.characters import (
    add_reward_items,
    free_bag_slots,
    slots_needed,
)
from darkblood.games.dispatcher import packet_handler
from darkblood.games.handlers.base import BaseDomainService

MONSTER_CARD_ACKS = {2602: MonsterCardListAck, 2609: MonsterCardDeckAck, 2618: MonsterCardAlbumAck}


def store_record(item: str, stock: int = -1, price: int = None) -> StoreRecord:
    """Store record for an item id; price defaults to the item's BuyPrice.

    The stock is clamped to i16 (storelist.lua -1 = unlimited)."""
    if price is None:
        from darkblood.games.game_data.client_dict import item_field
        price = item_field(item, 'BuyPrice', 0)
    return StoreRecord(item_hash=jhash(item), price=price & 0xFFFFFFFF,
                       stock=max(-0x8000, min(0x7FFF, stock)))




class TradeHandlers:
    @packet_handler(RequestTradeReq)
    async def handle_request_trade(self, correlation, body):
        # eERC_REQUEST_TRADE_REQ -> 5070 eERC_REQUEST_TRADE_ACK (0x00770E50).
        req = RequestTradeReq.decode(body)
        self.transport.record('trade-request-req', body, target=req.target_uid)
        ack = RequestTradeAck(result=0, target_uid=req.target_uid, target_name='Partner').encode()
        await self.transport.send_event(event(5070, ack, correlation), note=f'trade request ack (target={req.target_uid})')


    @packet_handler(AcceptRequestTradeReq)
    async def handle_accept_request_trade(self, correlation, body):
        # eERC_ACCEPT_REQUEST_TRADE_REQ -> 5072 eERC_ACCEPT_REQUEST_TRADE_ACK (0x007587B0).
        req = AcceptRequestTradeReq.decode(body)
        self.transport.record('trade-accept-request-req', body, source=req.source_uid)
        my_uid = self.char_id
        ack = AcceptRequestTradeAck(result=0, source_uid=req.source_uid, target_uid=my_uid).encode()
        await self.transport.send_event(event(5072, ack, correlation), note='trade accept request ack')


    @packet_handler(5073)
    async def handle_cancel_trade(self, correlation, body):
        # eERC_CANCEL_TRADE_REQ -> 5074 eERC_CANCEL_TRADE_ACK (0x0077DE00).
        self.transport.record('trade-cancel-req', body)
        ack = CancelTradeAck(result=0, items=[]).encode()
        await self.transport.send_event(event(5074, ack, correlation), note='trade cancel ack')


    @packet_handler(InsertTradeItemReq)
    async def handle_insert_trade_item(self, correlation, body):
        # eERC_INSERT_TRADE_ITEM_REQ -> 5076 eERC_INSERT_TRADE_ITEM_ACK (0x0077D980).
        req = InsertTradeItemReq.decode(body)
        self.transport.record('trade-insert-item-req', body, item_uid=req.item_uid, slot=req.slot)
        ack = InsertTradeItemAck(result=0, items=[]).encode()
        await self.transport.send_event(event(5076, ack, correlation), note=f'trade insert item ack (item={req.item_uid})')


    @packet_handler(DeleteTradeItemReq)
    async def handle_delete_trade_item(self, correlation, body):
        # eERC_DELETE_TRADE_ITEM_REQ -> 5078 eERC_DELETE_TRADE_ITEM_ACK (0x0077DBB0).
        req = DeleteTradeItemReq.decode(body)
        self.transport.record('trade-delete-item-req', body, item_uid=req.item_uid)
        ack = DeleteTradeItemAck(result=0, items=[]).encode()
        await self.transport.send_event(event(5078, ack, correlation), note=f'trade delete item ack (item={req.item_uid})')


    @packet_handler(UpdateTradeArReq)
    async def handle_update_trade_ar(self, correlation, body):
        # eERC_UPDATE_TRADE_AR_REQ -> 5080 eERC_UPDATE_TRADE_AR_ACK (0x00758940).
        req = UpdateTradeArReq.decode(body)
        self.transport.record('trade-update-ar-req', body, gold=req.gold)
        my_uid = self.char_id
        ack = UpdateTradeArAck(result=0, char_uid=my_uid, gold=req.gold).encode()
        await self.transport.send_event(event(5080, ack, correlation), note=f'trade update ar ack (gold={req.gold})')


    @packet_handler(5081)
    async def handle_accept_trade(self, correlation, body):
        # eERC_ACCEPT_TRADE_REQ -> 5082 eERC_ACCEPT_TRADE_ACK (0x0078EB40).
        self.transport.record('trade-accept-req', body)
        my_uid = self.char_id
        ack = AcceptTradeAck(result=0, char_uid=my_uid, accepted=True).encode()
        await self.transport.send_event(event(5082, ack, correlation), note='trade accept ack')


    @packet_handler(5083)
    async def handle_finally_accept_trade(self, correlation, body):
        # eERC_FINALLY_ACCEPT_TRADE_REQ -> 5084 eERC_FINALLY_ACCEPT_TRADE_ACK.
        self.transport.record('trade-finally-accept-req', body)
        ack = FinallyAcceptTradeAck(result=0).encode()
        await self.transport.send_event(event(5084, ack, correlation), note='trade finally accept ack')

