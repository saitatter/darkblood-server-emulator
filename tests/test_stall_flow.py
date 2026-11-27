"""End-to-end and unit tests for Personal Shop (Player Stalls) and Marketplace / Broker."""
import struct
import unittest

from tests.common import ServerTestCase, create_request, lobby_flow
from darkblood.games.entities.items import Item, UPDATE_OWNER
from darkblood.games.network.messages.stalls import (
    BrokerBuyItemAck,
    BrokerBuyItemReq,
    BrokerCancelAck,
    BrokerCancelReq,
    BrokerListAck,
    BrokerListReq,
    BrokerMyListAck,
    BrokerMyListReq,
    BrokerPriceAck,
    BrokerPriceReq,
    BrokerProduct,
    BrokerRegistItemAck,
    BrokerRegistItemReq,
    PersonalShopBuyAck,
    PersonalShopBuyReq,
    PersonalShopChangeNot,
    PersonalShopCloseAck,
    PersonalShopCloseReq,
    PersonalShopCloseNot,
    PersonalShopGetProductsAck,
    PersonalShopGetProductsReq,
    PersonalShopOpenAck,
    PersonalShopOpenReq,
    PersonalShopStartNot,
    StallItem, StallOffer,
)
from darkblood.games.session import GameSession
from darkblood.games.stalls import BrokerManager, PersonalShopManager
from headless_client import HeadlessClient


class StallFlowTest(ServerTestCase):
    """Personal shop (Player Stalls) and Broker (Marketplace) integration tests."""

    def setUp(self):
        super().setUp()
        # Reset in-memory managers between tests
        PersonalShopManager.get().stalls.clear()
        BrokerManager.get().listings.clear()
        BrokerManager.get().price_history.clear()

    def test_personal_shop_stall_lifecycle_flow(self):
        """End-to-end stall lifecycle: open stall, change title, browse, purchase, close."""
        async def scenario(client1):
            # 1. Setup seller client
            await lobby_flow(client1)
            client1.send_event(2012, create_request('StallMaster', char_class=1))
            _, created1 = await client1.expect_event(2013)
            seller_id = struct.unpack_from('<Q', created1, 10)[0]

            # Setup buyer character in the same store
            store = GameSession.store()
            client1.send_event(2012, create_request('StallBuyer', char_class=6))
            _, created2 = await client1.expect_event(2013)
            buyer_id = struct.unpack_from('<Q', created2, 10)[0]

            # Select seller (StallMaster)
            client1.send_event(2006, struct.pack('<iQ', 0x7fffffff, seller_id))
            await client1.expect_event(2007)

            # Equip seller with an item to sell and initial gold
            seller_char = store.get('OfflinePlayer', seller_id)
            seller_char['gold'] = 1000
            item_uid = 9001
            seller_char['items'] = [
                dict(code='Ihppa0001', uid=item_uid, count=5, container=3, slot=0)
            ]
            store.save()

            # Prepare buyer funds
            buyer_char = store.get('OfflinePlayer', buyer_id)
            buyer_char['gold'] = 25000
            store.save()

            # Connect buyer as a second client on the same server
            client2 = HeadlessClient(port=client1.port)
            try:
                await lobby_flow(client2)
                client2.send_event(2006, struct.pack('<iQ', 0x7fffffff, buyer_id))
                await client2.expect_event(2007)
                # The buyer's town has loaded (5124), so square broadcasts reach it.
                client2.send_event(5124, struct.pack('<i', 0x7fffffff))
                await client2.expect_event(5125)

                # 2. Seller opens stall via Opcode 2340
                open_req = PersonalShopOpenReq(
                    title='Rare Potions Stall',
                    items=[StallOffer(item_uid, 2, 3000)]  # sell 2 for 3000 AR each
                ).encode()
                client1.send_event(2340, open_req)

                # Expect Opcode 2341 (eEGS_PERSONALSHOP_START_ACK)
                _, ack2341 = await client1.expect_event(2341)
                self.assertEqual(struct.unpack_from('<i', ack2341, 0)[0], 0)  # result 0
                self.assertIn('Rare Potions Stall'.encode('utf-16le'), ack2341)
                # The buyer on the same square layer sees the stall open (5254).
                _, start_not = await client2.expect_event(5254)
                self.assertEqual(PersonalShopStartNot.decode(start_not).seller_uid, seller_id)

                # Verify stall is active in PersonalShopManager
                stall = PersonalShopManager.get().get_stall(seller_id)
                self.assertIsNotNone(stall)
                self.assertEqual(stall.title, 'Rare Potions Stall')
                self.assertIn(item_uid, stall.items)
                self.assertEqual(stall.items[item_uid].price, 3000)

                # 4. Buyer browses seller stall products via Opcode 6021
                browse_req = PersonalShopGetProductsReq(seller_uid=seller_id).encode()
                client2.send_event(6021, browse_req)

                # Expect Opcode 6022 (eERT_PERSONALSHOP_GET_PRODUCTS_ACK)
                _, ack6022 = await client2.expect_event(6022)
                self.assertEqual(struct.unpack_from('<i', ack6022, 0)[0], 0)
                self.assertEqual(struct.unpack_from('<q', ack6022, 4)[0], seller_id)
                self.assertIn('Rare Potions Stall'.encode('utf-16le'), ack6022)

                # 5. Buyer purchases 1 item from seller stall via Opcode 5242
                from darkblood.player_management.characters import add_reward_items, free_cells

                buy_req = PersonalShopBuyReq(seller_uid=seller_id, item_uid=item_uid, count=1).encode()
                fillers = add_reward_items(buyer_char, [('Ihppa0000', 1)] * len(free_cells(buyer_char)))
                client2.send_event(5242, buy_req)
                _, refused = await client2.expect_event(5243)
                self.assertNotEqual(struct.unpack_from('<i', refused)[0], 0)
                self.assertEqual((buyer_char['gold'], seller_char['gold'], stall.items[item_uid].count),
                                 (25000, 1000, 2))
                for filler in fillers:
                    buyer_char['items'].remove(filler)

                client2.send_event(5242, buy_req)

                # Expect Opcode 5243 (eERC_PERSONALSHOP_BUYITEM_ACK)
                _, ack5243 = await client2.expect_event(5243)
                self.assertEqual(struct.unpack_from('<i', ack5243, 0)[0], 0)

                # Verify atomic gold transfer:
                # Buyer spent 3000 gold: 25000 -> 22000
                buyer_updated = store.get('OfflinePlayer', buyer_id)
                self.assertEqual(buyer_updated.get('gold'), 22000)

                # Seller earned 3000 gold: 1000 -> 4000
                seller_updated = store.get('OfflinePlayer', seller_id)
                self.assertEqual(seller_updated.get('gold'), 4000)

                # Buyer received item in inventory
                buyer_items = buyer_updated.get('items', [])
                bought = next((i for i in buyer_items if i.get('code') == 'Ihppa0001'), None)
                self.assertIsNotNone(bought)
                self.assertEqual(bought.get('count', 1), 1)

                # Stall stock reduced: 2 -> 1
                self.assertEqual(stall.items[item_uid].count, 1)

                # 6. Seller closes stall via Opcode 2342
                close_req = PersonalShopCloseReq(owner_uid=seller_id).encode()
                client1.send_event(2342, close_req)

                # Expect Opcode 2343 (eEGS_PERSONALSHOP_CLOSE_ACK)
                _, ack2343 = await client1.expect_event(2343)
                self.assertEqual(struct.unpack_from('<i', ack2343, 0)[0], 0)
                self.assertEqual(struct.unpack_from('<q', ack2343, 4)[0], seller_id)

                # Stall removed from active manager
                self.assertIsNone(PersonalShopManager.get().get_stall(seller_id))

            finally:
                await client2.close()

        self.run_async(self.with_server(scenario))

    def test_personal_shop_canonical_opcodes_flow(self):
        """End-to-end flow using canonical engine opcodes (2340/2341, 5242/5243, 2342/2343)."""
        async def scenario(client1):
            await lobby_flow(client1)
            client1.send_event(2012, create_request('CanonVendor', char_class=2))
            _, created1 = await client1.expect_event(2013)
            vendor_id = struct.unpack_from('<Q', created1, 10)[0]

            store = GameSession.store()
            client1.send_event(2012, create_request('CanonShopper', char_class=3))
            _, created2 = await client1.expect_event(2013)
            shopper_id = struct.unpack_from('<Q', created2, 10)[0]

            # Select vendor
            client1.send_event(2006, struct.pack('<iQ', 0x7fffffff, vendor_id))
            await client1.expect_event(2007)

            vendor_char = store.get('OfflinePlayer', vendor_id)
            vendor_char['gold'] = 500
            item_uid = 9100
            vendor_char['items'] = [
                dict(code='Imppa0001', uid=item_uid, count=10, container=3, slot=0)
            ]
            store.save()

            shopper_char = store.get('OfflinePlayer', shopper_id)
            shopper_char['gold'] = 10000
            store.save()

            client2 = HeadlessClient(port=client1.port)
            try:
                await lobby_flow(client2)
                client2.send_event(2006, struct.pack('<iQ', 0x7fffffff, shopper_id))
                await client2.expect_event(2007)

                # Vendor starts shop via Opcode 2340 (eEGS_PERSONALSHOP_START_REQ)
                start_req = PersonalShopOpenReq(
                    title='Mana Supplies',
                    items=[StallOffer(item_uid, 4, 1500)]
                ).encode()
                client1.send_event(2340, start_req)

                # Expect Opcode 2341 (eEGS_PERSONALSHOP_START_ACK)
                _, ack2341 = await client1.expect_event(2341)
                self.assertEqual(struct.unpack_from('<i', ack2341, 0)[0], 0)

                # Shopper buys item via Opcode 5242 (eERC_PERSONALSHOP_BUYITEM_REQ)
                buy_req = PersonalShopBuyReq(seller_uid=vendor_id, item_uid=item_uid, count=2).encode()
                client2.send_event(5242, buy_req)

                # Expect Opcode 5243 (eERC_PERSONALSHOP_BUYITEM_ACK)
                _, ack5243 = await client2.expect_event(5243)
                self.assertEqual(struct.unpack_from('<i', ack5243, 0)[0], 0)

                # Verify balances: 2 items * 1500 = 3000 gold
                shopper_updated = store.get('OfflinePlayer', shopper_id)
                self.assertEqual(shopper_updated.get('gold'), 7000)

                vendor_updated = store.get('OfflinePlayer', vendor_id)
                self.assertEqual(vendor_updated.get('gold'), 3500)

                # Vendor closes shop via Opcode 2342 (eEGS_PERSONALSHOP_CLOSE_REQ)
                close_req = PersonalShopCloseReq(owner_uid=vendor_id).encode()
                client1.send_event(2342, close_req)

                # Expect Opcode 2343 (eEGS_PERSONALSHOP_CLOSE_ACK)
                _, ack2343 = await client1.expect_event(2343)
                self.assertEqual(struct.unpack_from('<i', ack2343, 0)[0], 0)
            finally:
                await client2.close()

        self.run_async(self.with_server(scenario))

    def test_broker_marketplace_flow(self):
        """End-to-end Broker / Auction House marketplace flow (Opcodes 2262-2273)."""
        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('BrokerUser', char_class=1))
            _, created = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', created, 10)[0]

            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)

            store = GameSession.store()
            char = store.get('OfflinePlayer', char_id)
            char['gold'] = 50000
            item_uid = 9200
            char['items'] = [
                dict(code='Iwpna0002', uid=item_uid, count=1, container=3, slot=0)
            ]
            store.save()

            # 1. Query Broker listings when empty (Opcode 2262 -> 2263)
            client.send_event(2262, BrokerListReq(page=0, category=0).encode())
            _, ack2263 = await client.expect_event(2263)
            self.assertEqual(struct.unpack_from('<i', ack2263, 0)[0], 0)

            # 2. Register item to Broker (Opcode 2266 -> 2267, exact 16-byte live format without header)
            reg_req = struct.pack('<qq', item_uid, 12000)
            client.send_event(2266, reg_req)
            _, ack2267 = await client.expect_event(2267)
            self.assertEqual(struct.unpack_from('<i', ack2267, 0)[0], 0)
            self.assertIn('BrokerUser'.encode('utf-16le'), ack2267)

            # Verify item removed from inventory and listed in BrokerManager
            self.assertEqual(len(BrokerManager.get().listings), 1)
            listing = list(BrokerManager.get().listings.values())[0]
            self.assertEqual(listing.price, 12000)
            self.assertEqual(listing.code, 'Iwpna0002')

            # 3. Query My Listings (Opcode 2264 -> 2265)
            client.send_event(2264, BrokerMyListReq().encode())
            _, ack2265 = await client.expect_event(2265)
            self.assertEqual(struct.unpack_from('<i', ack2265, 0)[0], 0)
            self.assertIn('BrokerUser'.encode('utf-16le'), ack2265)

            # 4. Check market price statistics (Opcode 2272 -> 2273)
            from darkblood.core.hashing import jhash
            price_req = BrokerPriceReq(item_id=jhash('Iwpna0002')).encode()
            client.send_event(2272, price_req)
            _, ack2273 = await client.expect_event(2273)
            self.assertEqual(struct.unpack_from('<i', ack2273, 0)[0], 0)

            # 5. Cancel listing (Opcode 2270 -> 2271)
            cancel_req = BrokerCancelReq(listing_id=listing.listing_id).encode()
            client.send_event(2270, cancel_req)
            _, ack2271 = await client.expect_event(2271)
            self.assertEqual(struct.unpack_from('<i', ack2271, 0)[0], 0)

            # Item returned to inventory
            self.assertEqual(len(BrokerManager.get().listings), 0)
            char_reloaded = store.get('OfflinePlayer', char_id)
            returned = next((i for i in char_reloaded.get('items', []) if i.get('code') == 'Iwpna0002'), None)
            self.assertIsNotNone(returned)

        self.run_async(self.with_server(scenario))


class StallWireMessagesTest(unittest.TestCase):
    """Unit tests for wire message serialization and deserialization."""

    def test_stall_item_encoding(self):
        item = Item(owner=UPDATE_OWNER, uid=101, code='Ihppa0001', count=3)
        stall_item = StallItem(item=item, price=2500)
        encoded = stall_item.encode()
        self.assertEqual(encoded, item.encode() + struct.pack('<q', 2500))  # no 0x1E byte

    def test_personal_shop_open_req_and_ack_roundtrip(self):
        req = PersonalShopOpenReq(title='Grand Emporium', items=[StallOffer(1001, 2, 5000), StallOffer(1002, 1, 9999)])
        encoded_req = req.encode()
        decoded_req = PersonalShopOpenReq.decode(encoded_req)
        self.assertEqual(decoded_req.title, 'Grand Emporium')
        self.assertEqual(len(decoded_req.items), 2)
        self.assertEqual(decoded_req.items[0], StallOffer(1001, 2, 5000))

        item1 = Item(owner=UPDATE_OWNER, uid=1001, code='Ihppa0001', count=2)
        stall_items = [StallItem(item=item1, price=5000)]
        ack = PersonalShopOpenAck(result=0, owner_uid=777, title='Grand Emporium', items=stall_items)
        encoded_ack = ack.encode()
        self.assertEqual(struct.unpack_from('<i', encoded_ack, 0)[0], 0)
        self.assertIn('Grand Emporium'.encode('utf-16le'), encoded_ack)

    def test_personal_shop_buy_req_and_ack(self):
        req = PersonalShopBuyReq(seller_uid=555, item_uid=12345, count=3)
        encoded = req.encode()
        decoded = PersonalShopBuyReq.decode(encoded)
        self.assertEqual(decoded.seller_uid, 555)
        self.assertEqual(decoded.item_uid, 12345)
        self.assertEqual(decoded.count, 3)

        bought_item = Item(owner=UPDATE_OWNER, uid=12345, code='Ihppa0001', count=3)
        ack = PersonalShopBuyAck(result=0, gold=18000, items=[bought_item], seller_uid=555)
        encoded_ack = ack.encode()
        self.assertEqual(struct.unpack_from('<i', encoded_ack, 0)[0], 0)
        self.assertIn(struct.pack('<q', 18000), encoded_ack)

    def test_personal_shop_close_req_and_ack(self):
        req = PersonalShopCloseReq(owner_uid=888)
        encoded = req.encode()
        decoded = PersonalShopCloseReq.decode(encoded)
        self.assertEqual(decoded.owner_uid, 888)

        ack = PersonalShopCloseAck(result=0, owner_uid=888)
        encoded_ack = ack.encode()
        res, uid = struct.unpack_from('<iq', encoded_ack, 0)
        self.assertEqual(res, 0)
        self.assertEqual(uid, 888)

    def test_broker_messages_roundtrip(self):
        list_req = BrokerListReq(page=1, category=2, filter_name='Sword')
        encoded = list_req.encode()
        decoded = BrokerListReq.decode(encoded)
        self.assertEqual(decoded.page, 1)
        self.assertEqual(decoded.category, 2)
        self.assertEqual(decoded.filter_name, 'Sword')

        item = Item(owner=UPDATE_OWNER, uid=7001, code='Iwpna0001', count=1)
        prod = BrokerProduct(item=item, price=50000, seller_name='VendorKing', listing_id=42)
        ack = BrokerListAck(result=0, products=[prod], page=0, total_count=1)
        encoded_ack = ack.encode()
        self.assertEqual(struct.unpack_from('<i', encoded_ack, 0)[0], 0)
        self.assertIn('VendorKing'.encode('utf-16le'), encoded_ack)


if __name__ == '__main__':
    unittest.main()
