"""Comprehensive test suite for Pet, Mount and Taming subsystem."""
import struct
import unittest

from tests.common import ServerTestCase, create_request, lobby_flow
from darkblood.games import session
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


class PetsWireMessagesTest(unittest.TestCase):
    """Wire encoding and decoding tests for pet and mount messages."""

    def test_taming_messages_encoding_and_decoding(self):
        # 2348: Insert req
        req_insert = TameingMonsterInsertReq(monster_id=101, slot=2)
        encoded_ins = req_insert.encode()
        decoded_ins = TameingMonsterInsertReq.decode(encoded_ins)
        self.assertEqual(decoded_ins.monster_id, 101)
        self.assertEqual(decoded_ins.slot, 2)

        # 2349: Insert ack
        ack_insert = TamingMonsterInsertAck(result=0).encode()
        self.assertEqual(ack_insert, b'\x00\x00\x00\x00\x10\x80')  # empty vector: element layout unknown

        # 2350: Delete req
        req_del = TameingMonsterDeleteReq(monster_id=101, slot=2)
        encoded_del = req_del.encode()
        decoded_del = TameingMonsterDeleteReq.decode(encoded_del)
        self.assertEqual(decoded_del.monster_id, 101)
        self.assertEqual(decoded_del.slot, 2)

        # 2351: Delete ack
        ack_del = TamingMonsterDeleteAck(result=0, deleted_slot=2).encode()
        self.assertEqual(struct.unpack_from('<I', ack_del, 0)[0], 0)
        self.assertEqual(struct.unpack_from('<i', ack_del, -4)[0], 2)

    def test_riding_messages_encoding_and_decoding(self):
        # 2434: Get list req
        req_list = RidingGetListReq()
        self.assertEqual(req_list.encode(), b'\xff\xff\xff\x7f')
        self.assertIsInstance(RidingGetListReq.decode(b''), RidingGetListReq)  # header is optional

        # 2435: Get list ack
        ack_list = RidingGetListAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<I', ack_list, 0)[0], 0)
        self.assertEqual(ack_list[4], 0x17)  # tag 0x17 container map

        # 2437: Ride object req
        req_ride = RidingRideObjectReq(ride_object_id=5)
        encoded_ride = req_ride.encode()
        decoded_ride = RidingRideObjectReq.decode(encoded_ride)
        self.assertEqual(decoded_ride.ride_object_id, 5)

        # 2438: Ride object ack
        ack_ride = RidingRideObjectAck(result=0, ride_object_id=5).encode()
        decoded_ack_ride = RidingRideObjectAck.decode(ack_ride)
        self.assertEqual(decoded_ack_ride.result, 0)
        self.assertEqual(decoded_ack_ride.ride_object_id, 5)

    def test_pet_lifecycle_messages_encoding_and_decoding(self):
        # 2464 / 2465: Create (vecItem >> nItemID >> jNewPetInfo 0x00A52CF0)
        from darkblood.games.network.messages.pets import PetInfo
        req_create = PetCreateReq(pet_uid=42)
        self.assertEqual(PetCreateReq.decode(req_create.encode()).pet_uid, 42)
        ack_create = PetCreateAck(
            result=0, items=[], item_id=0x12345678,
            pet=PetInfo(pet_uid=42, pet_id=0xAABBCCDD, level=1, satiety=100, name='Pet', slot=-1),
        ).encode()
        self.assertEqual(ack_create[:10], b'\x00\x00\x00\x00\x10\x80\x78\x56\x34\x12')
        # PetInfo starts with empty dye array (0x80), then i64 pet_uid, h32 pet_id, u8 level
        self.assertEqual(ack_create[10], 0x80)
        self.assertEqual(struct.unpack_from('<qIB', ack_create, 11), (42, 0xAABBCCDD, 1))

        # 2466 / 2467: Delete
        req_delete = PetDeleteReq(pet_uid=42)
        self.assertEqual(PetDeleteReq.decode(req_delete.encode()).pet_uid, 42)
        ack_delete = PetDeleteAck(result=0, pet_uid=42).encode()
        self.assertEqual(struct.unpack_from('<Iq', ack_delete, 0), (0, 42))

        # 2468 / 2469: Summon
        self.assertEqual(PetSummonReq().encode(), b'')  # sender 0x0079E3C0 writes no fields
        ack_summon = PetSummonAck(result=0, satiety=100).encode()
        self.assertEqual(struct.unpack_from('<IH', ack_summon, 0), (0, 100))

        # 2470 / 2471: Release summon
        ack_release = PetReleaseSummonAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<I', ack_release, 0)[0], 0)

        # 2475 / 2476: Load
        req_load = PetLoadReq(pet_uid=99)
        self.assertEqual(PetLoadReq.decode(req_load.encode()).pet_uid, 99)
        ack_load = PetLoadAck(result=0, pet_uid=99).encode()
        self.assertEqual(struct.unpack_from('<Iq', ack_load, 0), (0, 99))

        # 2480 / 2481: Eat
        req_eat = PetEatNormalReq(item_uid=123)
        self.assertEqual(PetEatNormalReq.decode(req_eat.encode()).item_uid, 123)
        ack_eat = PetEatNormalAck(result=0, satiety=80, status=1).encode()
        self.assertEqual(struct.unpack_from('<I', ack_eat, 0)[0], 0)
        self.assertEqual(ack_eat[4], 0x10)

        # 2484 / 2485: Evolution
        ack_evo = PetEvolutionAck(result=0, old_pet_uid=1, new_pet_id=8001, new_pet_uid=1).encode()
        self.assertEqual(struct.unpack_from('<IqI', ack_evo, 0), (0, 1, 8001))

        # 2510 / 2511: Nick change
        req_nick = PetNickChangeReq(pet_uid=10, new_name="Furry")
        encoded_nick = req_nick.encode()
        decoded_nick = PetNickChangeReq.decode(encoded_nick)
        self.assertEqual(decoded_nick.pet_uid, 10)
        self.assertEqual(decoded_nick.new_name, "Furry")

        ack_nick = PetNickChangeAck(result=0, pet_uid=10, new_name="Furry").encode()
        self.assertEqual(struct.unpack_from('<I', ack_nick, 0)[0], 0)


class PetsFlowTest(ServerTestCase):
    """Headless integration test for Pet, Mount and Taming server session handling."""

    def test_pets_and_mounts_lifecycle(self):
        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('PetHero', char_class=1))
            _, ack2013 = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', ack2013, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)

            char = session.GameSession.store().get('OfflinePlayer', char_id)

            # 1. Monster Taming: Insert (2348 -> 2349)
            client.send_event(2348, TameingMonsterInsertReq(monster_id=501, slot=0).encode())
            _, ack2349 = await client.expect_event(2349)
            self.assertEqual(struct.unpack_from('<I', ack2349, 0)[0], 0)
            char = session.GameSession.store().get('OfflinePlayer', char_id)
            self.assertEqual(len(char.get('tamed_monsters', [])), 1)
            self.assertEqual(char['tamed_monsters'][0]['monster_id'], 501)

            # 2. Monster Taming: Delete (2350 -> 2351)
            client.send_event(2350, TameingMonsterDeleteReq(monster_id=501, slot=0).encode())
            _, ack2351 = await client.expect_event(2351)
            self.assertEqual(struct.unpack_from('<I', ack2351, 0)[0], 0)
            char = session.GameSession.store().get('OfflinePlayer', char_id)
            self.assertEqual(len(char.get('tamed_monsters', [])), 0)

            # 3. Mounts: Get List (2434 -> 2435)
            client.send_event(2434, RidingGetListReq().encode())
            _, ack2435 = await client.expect_event(2435)
            self.assertEqual(struct.unpack_from('<I', ack2435, 0)[0], 0)
            self.assertEqual(ack2435[4], 0x17)

            # 4. Mounts: Ride Object / Mount activation (2437 -> 2438)
            client.send_event(2437, RidingRideObjectReq(ride_object_id=2).encode())
            _, ack2438 = await client.expect_event(2438)
            res, r_id = struct.unpack_from('<II', ack2438, 0)
            self.assertEqual(res, 0)
            self.assertEqual(r_id, 2)
            char = session.GameSession.store().get('OfflinePlayer', char_id)
            self.assertEqual(char.get('mounted_ride_id'), 2)

            # 4b. Mounts: Dismount toggle (2437 -> 2438)
            client.send_event(2437, RidingRideObjectReq(ride_object_id=2).encode())
            _, ack2438_off = await client.expect_event(2438)
            res, r_id = struct.unpack_from('<II', ack2438_off, 0)
            self.assertEqual(res, 0)
            self.assertEqual(r_id, 0)
            char = session.GameSession.store().get('OfflinePlayer', char_id)
            self.assertEqual(char.get('mounted_ride_id'), 0)

            # 5. Pet Lifecycle: Create pet from Pet Egg (2464 -> 2465)
            char = session.GameSession.store().get('OfflinePlayer', char_id)
            char.setdefault('items', []).append(dict(code='Pegg1Cash96', uid=10, container=3, slot=0, count=1))
            session.GameSession.store().save_char('OfflinePlayer', char_id)
            client.send_event(2464, PetCreateReq(pet_uid=10).encode())
            _, ack2465 = await client.expect_event(2465)
            self.assertEqual(struct.unpack_from('<I', ack2465, 0)[0], 0)
            char = session.GameSession.store().get('OfflinePlayer', char_id)
            self.assertFalse(any(i.get('uid') == 10 for i in char.get('items', [])))
            self.assertEqual(len(char.get('pets', [])), 1)
            self.assertEqual(char['pets'][0]['uid'], 10)
            self.assertEqual(char['pets'][0]['code'], 'PetCall001')

            # 6. Pet Lifecycle: Summon pet (2468 -> 2469)
            client.send_event(2468, PetSummonReq().encode())
            _, ack2469 = await client.expect_event(2469)
            res, satiety = struct.unpack_from('<IH', ack2469, 0)
            self.assertEqual(res, 0)
            self.assertEqual(satiety, 100)
            char = session.GameSession.store().get('OfflinePlayer', char_id)
            self.assertEqual(char.get('summoned_pet'), 10)

            # 7. Pet Lifecycle: Feed pet (2480 -> 2481)
            client.send_event(2480, PetEatNormalReq(item_uid=999).encode())
            _, ack2481 = await client.expect_event(2481)
            self.assertEqual(struct.unpack_from('<I', ack2481, 0)[0], 0)

            # 8. Pet Lifecycle: Change nickname (2510 -> 2511)
            client.send_event(2510, PetNickChangeReq(pet_uid=10, new_name='Kittie').encode())
            _, ack2511 = await client.expect_event(2511)
            self.assertEqual(struct.unpack_from('<I', ack2511, 0)[0], 0)
            char = session.GameSession.store().get('OfflinePlayer', char_id)
            self.assertEqual(char['pets'][0]['name'], 'Kittie')

            # 9. Pet Lifecycle: Evolution (2484 -> 2485)
            client.send_event(2484, PetEvolutionReq().encode())
            _, ack2485 = await client.expect_event(2485)
            self.assertEqual(struct.unpack_from('<I', ack2485, 0)[0], 0)
            char = session.GameSession.store().get('OfflinePlayer', char_id)
            self.assertEqual(char['pets'][0]['level'], 2)

            # 10. Pet Lifecycle: Dismiss / Release Summon (2470 -> 2471)
            client.send_event(2470, PetReleaseSummonReq().encode())
            _, ack2471 = await client.expect_event(2471)
            self.assertEqual(struct.unpack_from('<I', ack2471, 0)[0], 0)
            char = session.GameSession.store().get('OfflinePlayer', char_id)
            self.assertIsNone(char.get('summoned_pet'))

            # 11. Pet Lifecycle: Delete (2466 -> 2467)
            client.send_event(2466, PetDeleteReq(pet_uid=10).encode())
            _, ack2467 = await client.expect_event(2467)
            self.assertEqual(struct.unpack_from('<Iq', ack2467, 0), (0, 10))
            char = session.GameSession.store().get('OfflinePlayer', char_id)
            self.assertEqual(len(char.get('pets', [])), 0)

            # 12. Item Use: PetCall egg item consumption activates pet
            char['items'] = [
                {'uid': 1001, 'code': 'PetCall001', 'container': 3, 'slot': 0, 'count': 1},
                {'uid': 1002, 'code': 'ridecall0', 'container': 3, 'slot': 1, 'count': 1},
            ]
            session.GameSession.store().save()

            client.send_event(2038, struct.pack('<iqI', 0x7fffffff, 1001, 1))
            _, ack2039_pet = await client.expect_event(2039)
            self.assertEqual(struct.unpack_from('<i', ack2039_pet, 0)[0], 0)
            char = session.GameSession.store().get('OfflinePlayer', char_id)
            self.assertEqual(len(char.get('pets', [])), 1)
            self.assertEqual(char['pets'][0]['code'], 'PetCall001')

            # 14. Item Use: ridecall whistle item consumption activates mount
            client.send_event(2038, struct.pack('<iqI', 0x7fffffff, 1002, 1))
            _, ack2039_ride = await client.expect_event(2039)
            self.assertEqual(struct.unpack_from('<i', ack2039_ride, 0)[0], 0)
            await client.expect_event(2436)
            char = session.GameSession.store().get('OfflinePlayer', char_id)
            self.assertIn('ridecall0', char.get('ridings', {}))

        self.run_async(self.with_server(scenario))

    def test_extended_fishing_commerce_stalls_and_pets(self):
        """Test newly recovered Fishing, Commerce, Stalls, and Pets opcodes."""
        from darkblood.games.network.messages.fishing import (
            FishingStartAck, FishingStartReq, FishingStopAck, FishingStopReq,
        )
        from darkblood.games.network.messages.stalls import (
            SaleByBulkOptionAck, SaleByBulkOptionReq, SaleByBulkRegistAck, SaleByBulkRegistReq,
        )
        from darkblood.games.network.messages.commerce import (
            BeautyShopCareReq, BeautyShopInfo, SellItemAllReq, SteamBuyPackageAck, SteamBuyPackageReq,
        )
        from darkblood.games.network.messages.pets import (
            PetCashFoodEquipAck, PetCashFoodEquipReq, PetCashFoodUnequipAck, PetCashFoodUnequipReq,
            PetEatCashReq, PetExtendDepotReq, PetSwitchStorageAck, PetSwitchStorageReq,
            RidingExpireUpdateReq,
        )

        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('AnglerHero', char_class=2))
            _, created = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', created, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)

            # Fishing (2523-2526)
            client.send_event(2523, FishingStartReq(fishing_hole_id='Act1_Fish01', rod_item_id=1, bait_item_id=2).encode())
            _, r = await client.expect_event(2524)
            self.assertEqual(FishingStartAck.decode(r).result, 0)

            client.send_event(2525, FishingStopReq().encode())
            _, r = await client.expect_event(2526)
            self.assertEqual(FishingStopAck.decode(r).result, 0)

            # Stalls / SaleByBulk (2586-2589)
            client.send_event(2586, SaleByBulkOptionReq(equip_idx=3, enable=True).encode())
            _, r = await client.expect_event(2587)
            ack = SaleByBulkOptionAck.decode(r)
            self.assertEqual(ack.result, 0)
            self.assertTrue(ack.sell_equip_info.get(3))

            client.send_event(2588, SaleByBulkRegistReq(reg_item_id=555, is_add=True).encode())
            _, r = await client.expect_event(2589)
            ack = SaleByBulkRegistAck.decode(r)
            self.assertEqual(ack.result, 0)
            self.assertIn(555, ack.custom_item_list)

            # Commerce: BeautyShop (2416), SellItemAll (2590), SteamBuyPackage (2721)
            client.send_event(2416, BeautyShopCareReq(info=BeautyShopInfo(style_slots=[1, 2, 3], style_param1=0, style_param2=0)).encode())
            _, r = await client.expect_event(2417)
            self.assertEqual(struct.unpack_from('<i', r)[0], 0)

            client.send_event(2590, SellItemAllReq().encode())
            _, r = await client.expect_event(2591)
            self.assertEqual(struct.unpack_from('<i', r)[0], 0)

            client.send_event(2721, SteamBuyPackageReq(package_id=42).encode())
            _, r = await client.expect_event(2722)
            self.assertEqual(SteamBuyPackageAck.decode(r).result, 0)

            # Pets (2482, 2492, 2494, 2498, 2500, 2646)
            client.send_event(2482, PetEatCashReq(item_uid=700).encode())
            _, r = await client.expect_event(2483)
            self.assertEqual(struct.unpack_from('<I', r)[0], 0)

            client.send_event(2492, PetCashFoodEquipReq(cash_food_item_uid=701).encode())
            _, r = await client.expect_event(2493)
            ack = PetCashFoodEquipAck.decode(r)
            self.assertEqual((ack.result, ack.cash_food_item_uid), (0, 701))

            client.send_event(2494, PetCashFoodUnequipReq().encode())
            _, r = await client.expect_event(2495)
            self.assertEqual(PetCashFoodUnequipAck.decode(r).result, 0)

            client.send_event(2498, PetExtendDepotReq(item_uid=702, depot_slot_index=1).encode())
            _, r = await client.expect_event(2499)
            self.assertEqual(struct.unpack_from('<Ih', r), (0, 1))

            client.send_event(2500, PetSwitchStorageReq(move_slot_index=0, target_slot_index=1).encode())
            _, r = await client.expect_event(2501)
            ack = PetSwitchStorageAck.decode(r)
            self.assertEqual((ack.result, ack.move_slot_index, ack.target_slot_index), (0, 0, 1))

            client.send_event(2646, RidingExpireUpdateReq(item_uid=703, riding_id=5).encode())
            _, r = await client.expect_event(2647)
            self.assertEqual(struct.unpack_from('<I', r)[0], 0)

        self.run_async(self.with_server(scenario))

    def test_monster_card_roulette_cronos_explore_clear_rank(self):
        """Test MonsterCard, Roulette, StorageShare, Cronos, Explore, and ClearRank opcodes."""
        from darkblood.games.network.messages.pets import (
            MonsterCardExtendSlotAck, MonsterCardExtendSlotReq,
            MonsterCardGetRewardLottoReq, MonsterCardGetRewardPointArrivalReq,
            MonsterCardInsertAck, MonsterCardInsertReq,
            MonsterCardLottoRegAck, MonsterCardLottoRegReq,
            MonsterCardMergeAck, MonsterCardMergeReq,
            MonsterCardReleaseAllCharAck, MonsterCardReleaseAllCharReq,
            MonsterCardSetCharDeckAck, MonsterCardSetCharDeckReq,
        )
        from darkblood.games.network.messages.commerce import (
            RouletteNoticeReq, RoulettePointInsertNot, RouletteRollDiceAck, RouletteRollDiceReq,
            StorageShareReq,
        )
        from darkblood.games.network.messages.dungeon import (
            ClearRankHistoryInfoAck, ClearRankHistoryInfoReq,
            ClearRankInfoAck, ClearRankInfoReq,
            CronosDateAck, CronosDateReq, CronosInfoAck, CronosInfoReq,
            CronosRewardReq, CronosStampReq, CronosTodayTimeAck, CronosTodayTimeReq,
            ExploreCancelAck, ExploreCancelByUserUidAck, ExploreCancelByUserUidReq,
            ExploreCancelReq, ExploreGetRewardReq, ExploreStartReq,
        )

        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('CardMaster', char_class=1))
            _, created = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', created, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)

            # Monster Card
            client.send_event(2604, MonsterCardInsertReq(item_uid=10).encode())
            _, r = await client.expect_event(2605)
            self.assertEqual(MonsterCardInsertAck.decode(r).result, 0)

            client.send_event(2606, MonsterCardMergeReq(card_uids=[1, 2]).encode())
            _, r = await client.expect_event(2607)
            self.assertEqual(MonsterCardMergeAck.decode(r).result, 0)

            client.send_event(2610, MonsterCardSetCharDeckReq(deck_uids=[1, 2, 3]).encode())
            _, r = await client.expect_event(2611)
            self.assertEqual(MonsterCardSetCharDeckAck.decode(r).deck_uids, [1, 2, 3])

            client.send_event(2613, MonsterCardReleaseAllCharReq(card_uid=1).encode())
            _, r = await client.expect_event(2614)
            self.assertEqual(MonsterCardReleaseAllCharAck.decode(r).result, 0)

            client.send_event(2615, MonsterCardExtendSlotReq(count=1).encode())
            _, r = await client.expect_event(2616)
            self.assertEqual(MonsterCardExtendSlotAck.decode(r).max_inven_cnt, 60)

            client.send_event(2633, MonsterCardLottoRegReq(numbers=[1, 2, 3]).encode())
            _, r = await client.expect_event(2634)
            self.assertEqual(MonsterCardLottoRegAck.decode(r).result, 0)

            client.send_event(2636, MonsterCardGetRewardLottoReq(lotto_reg_uid=1).encode())
            _, r = await client.expect_event(2637)
            self.assertEqual(struct.unpack_from('<Iq', r), (0, 1))

            client.send_event(2638, MonsterCardGetRewardPointArrivalReq(choice_point=100).encode())
            _, r = await client.expect_event(2639)
            self.assertEqual(struct.unpack_from('<Ii', r), (0, 100))

            # Roulette & StorageShare
            from darkblood.core.hashing import jhash
            from darkblood.games.handlers.commerce.stores import ROULETTE_REWARDS
            from darkblood.games.network.messages.events import RouletteManagerInfoAck
            client.send_event(2390, b'')
            _, r2391 = await client.expect_event(2391)
            self.assertEqual(len(r2391), 14)
            self.assertEqual(r2391[0], 0x1E)
            mgr2391 = RouletteManagerInfoAck.decode(r2391)
            self.assertTrue(mgr2391.active)
            self.assertGreater(mgr2391.jackpot_ar, 0)

            client.send_event(2386, RouletteRollDiceReq(count=1).encode())
            _, r = await client.expect_event(2387)
            self.assertEqual(r[4], 0x1E)
            ack2387 = RouletteRollDiceAck.decode(r)
            self.assertEqual(ack2387.result, 0)
            valid_reward_hashes = {jhash(entry[0]) & 0xFFFFFFFF for entry in ROULETTE_REWARDS}
            self.assertIn(ack2387.reward_id & 0xFFFFFFFF, valid_reward_hashes)

            client.send_event(2388, RouletteNoticeReq().encode())
            _, r = await client.expect_event(2389)
            self.assertEqual(len(r), 5)
            self.assertEqual(r[0], 0x1E)
            self.assertEqual(RoulettePointInsertNot.decode(r).roulette_points, 0.0)

            client.send_event(2530, StorageShareReq(item_uid=5).encode())
            _, r = await client.expect_event(2531)
            self.assertEqual(struct.unpack_from('<I', r)[0], 0)

            # Cronos (Attendance)
            client.send_event(2289, CronosRewardReq(index=1, reward_select=0).encode())
            _, r = await client.expect_event(2290)
            self.assertEqual(struct.unpack_from('<I', r)[0], 0)

            client.send_event(2292, CronosInfoReq().encode())
            _, r = await client.expect_event(2293)
            self.assertEqual(CronosInfoAck.decode(r).result, 0)

            client.send_event(2294, CronosDateReq().encode())
            _, r = await client.expect_event(2295)
            self.assertEqual(CronosDateAck.decode(r).result, 0)

            client.send_event(2296, CronosTodayTimeReq().encode())
            _, r = await client.expect_event(2297)
            self.assertEqual(CronosTodayTimeAck.decode(r).today_login_second, 60)

            client.send_event(2299, CronosStampReq().encode())
            _, r = await client.expect_event(2300)
            self.assertEqual(struct.unpack_from('<I', r)[0], 0)

            # Explore
            client.send_event(2651, ExploreStartReq(char_uid=char_id, explore_time=60).encode())
            _, r = await client.expect_event(2652)
            self.assertEqual(struct.unpack_from('<Iq', r), (0, char_id))

            client.send_event(2653, ExploreCancelReq(explore_char_uid=char_id).encode())
            _, r = await client.expect_event(2654)
            self.assertEqual(ExploreCancelAck.decode(r).explore_char_uid, char_id)

            client.send_event(2656, ExploreGetRewardReq(reward_uid=9).encode())
            _, r = await client.expect_event(2657)
            self.assertEqual(struct.unpack_from('<Iq', r), (0, 9))

            client.send_event(2662, ExploreCancelByUserUidReq(explore_char_uid=char_id).encode())
            _, r = await client.expect_event(2663)
            self.assertEqual(ExploreCancelByUserUidAck.decode(r).explore_char_uid, char_id)

            # Clear Rank
            client.send_event(2539, ClearRankHistoryInfoReq(map_id=100, page=1).encode())
            _, r = await client.expect_event(2540)
            self.assertEqual(ClearRankHistoryInfoAck.decode(r).map_id, 100)

            client.send_event(5228, ClearRankInfoReq(map_id=100, page=1).encode())
            _, r = await client.expect_event(5229)
            self.assertEqual(ClearRankInfoAck.decode(r).map_id, 100)

        self.run_async(self.with_server(scenario))

    def test_mount_item_unlock_and_relog_persistence(self):
        from darkblood.core.hashing import jhash
        from darkblood.games.network.messages.inventory import UseItemReq
        from darkblood.games.network.messages.lobby import SelectCharacterAck
        from darkblood.games.network.messages.pets import (
            RidingChangeListNot,
            RidingExpireUpdateAck,
            RidingExpireUpdateReq,
            RidingInfo,
        )

        # Round-trip RidingInfo wire layout (0x00A4BD80)
        rid = jhash('ridecall2')
        info = RidingInfo(dye_colors=[], riding_id=rid, remain_sec=864000, expire_date=1800000000)
        decoded_info = RidingInfo.decode(info.encode())
        self.assertEqual(decoded_info.riding_id, rid)
        self.assertEqual(decoded_info.remain_sec, 864000)
        self.assertEqual(decoded_info.expire_date, 1800000000)
        self.assertEqual(decoded_info.dye_colors, [])

        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('MountHero', char_class=1))
            _, ack2013 = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', ack2013, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)

            # Give two mount items (IRid1Cash46 -> ridecall2, 240h)
            char = session.GameSession.store().get('OfflinePlayer', char_id)
            char.setdefault('items', []).append(dict(code='IRid1Cash46', uid=501, container=3, slot=0, count=2))
            session.GameSession.store().save_char('OfflinePlayer', char_id)

            # Use one mount item via 2038 -> expect 2039 + 2436 RidingChangeListNot
            client.send_event(2038, UseItemReq(item_uid=501, use_count=1).encode())
            _, ack2039 = await client.expect_event(2039)
            self.assertEqual(struct.unpack_from('<I', ack2039, 0)[0], 0)
            _, not2436 = await client.expect_event(2436)
            msg2436 = RidingChangeListNot.decode(not2436)
            self.assertIn(rid, msg2436.ridings)
            self.assertGreater(msg2436.ridings[rid].remain_sec, 239 * 3600)

            # 2434 -> 2435 RidingGetListAck returns the unlocked mount
            client.send_event(2434, RidingGetListReq().encode())
            _, ack2435 = await client.expect_event(2435)
            msg2435 = RidingGetListAck.decode(ack2435)
            self.assertEqual(msg2435.result, 0)
            self.assertIn(rid, msg2435.ridings)

            # 2646 -> 2647 RidingExpireUpdateAck extends duration using second item
            from darkblood.core.serialization.jser import JSerBufferReader
            prev_remain = msg2435.ridings[rid].remain_sec
            client.send_event(2646, RidingExpireUpdateReq(item_uid=501, riding_id=rid).encode())
            _, ack2647 = await client.expect_event(2647)
            r = JSerBufferReader(ack2647)
            self.assertEqual(r.read_u32(), 0)
            ridings2647 = r.read_tagged_map(JSerBufferReader.read_u32, RidingInfo.read)
            self.assertIn(rid, ridings2647)
            self.assertGreater(ridings2647[rid].remain_sec, prev_remain + 239 * 3600)

            # Relog (2006 -> 2007 SelectCharacterAck) persists the mount in 2007.ridings
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            _, ack2007 = await client.expect_event(2007)
            # Verify raw wire contains the RidingInfo map entry (0x0F + rid + 0x80 + rid)
            marker = b'\x0f' + struct.pack('<I', rid) + b'\x80' + struct.pack('<I', rid)
            self.assertIn(marker, ack2007)

            # Explore (Forest of Oblivion): 5358 -> 5359 and 5360 -> 5361
            client.send_event(5358, b'')
            _, ack5359 = await client.expect_event(5359)
            self.assertEqual(struct.unpack_from('<I', ack5359, 0)[0], 0)
            client.send_event(5360, b'')
            _, ack5361 = await client.expect_event(5361)
            self.assertEqual(struct.unpack_from('<I', ack5361, 0)[0], 0)

        self.run_async(self.with_server(scenario))

    def test_pet_depot_slot_wire_size_matches_client_reader(self):
        """0x00A1E820 reads 0x1B (27) raw bytes per pet_depot_slots entry (unlike 0x00A1EBF0's 0x13 bytes)."""
        from darkblood.games.network.messages import DepotSlotInfo, PetDepotSlotInfo
        self.assertEqual(len(DepotSlotInfo().encode()), 0x13)
        self.assertEqual(len(PetDepotSlotInfo().encode()), 0x1B)


if __name__ == '__main__':
    unittest.main()
