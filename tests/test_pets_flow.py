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
        ack_insert = TamingMonsterInsertAck(result=0, monsters=[{'monster_id': 101}]).encode()
        self.assertEqual(struct.unpack_from('<I', ack_insert, 0)[0], 0)
        self.assertEqual(ack_insert[4], 0x10)  # tag 0x10 vector

        # 2350: Delete req
        req_del = TameingMonsterDeleteReq(monster_id=101, slot=2)
        encoded_del = req_del.encode()
        decoded_del = TameingMonsterDeleteReq.decode(encoded_del)
        self.assertEqual(decoded_del.monster_id, 101)
        self.assertEqual(decoded_del.slot, 2)

        # 2351: Delete ack
        ack_del = TamingMonsterDeleteAck(result=0, monsters=[], deleted_slot=2).encode()
        self.assertEqual(struct.unpack_from('<I', ack_del, 0)[0], 0)
        self.assertEqual(struct.unpack_from('<i', ack_del, -4)[0], 2)

    def test_riding_messages_encoding_and_decoding(self):
        # 2434: Get list req
        req_list = RidingGetListReq()
        self.assertEqual(req_list.encode(), b'')
        self.assertIsInstance(RidingGetListReq.decode(b''), RidingGetListReq)

        # 2435: Get list ack
        ack_list = RidingGetListAck(result=0, rides=[]).encode()
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
        # 2464 / 2465: Create
        req_create = PetCreateReq(pet_uid=42)
        self.assertEqual(PetCreateReq.decode(req_create.encode()).pet_uid, 42)
        ack_create = PetCreateAck(result=0, pets=[], slot=0).encode()
        self.assertEqual(struct.unpack_from('<I', ack_create, 0)[0], 0)
        self.assertEqual(ack_create[4], 0x10)  # tag 0x10 vector

        # 2466 / 2467: Delete
        req_delete = PetDeleteReq(pet_uid=42)
        self.assertEqual(PetDeleteReq.decode(req_delete.encode()).pet_uid, 42)
        ack_delete = PetDeleteAck(result=0, pet_uid=42).encode()
        self.assertEqual(struct.unpack_from('<Iq', ack_delete, 0), (0, 42))

        # 2468 / 2469: Summon
        req_summon = PetSummonReq(pet_slot=1)
        self.assertEqual(PetSummonReq.decode(req_summon.encode()).pet_slot, 1)
        ack_summon = PetSummonAck(result=0, pet_slot=1).encode()
        self.assertEqual(struct.unpack_from('<IH', ack_summon, 0), (0, 1))

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

            # 5. Pet Lifecycle: Create pet (2464 -> 2465)
            client.send_event(2464, PetCreateReq(pet_uid=10).encode())
            _, ack2465 = await client.expect_event(2465)
            self.assertEqual(struct.unpack_from('<I', ack2465, 0)[0], 0)
            char = session.GameSession.store().get('OfflinePlayer', char_id)
            self.assertEqual(len(char.get('pets', [])), 1)
            self.assertEqual(char['pets'][0]['uid'], 10)

            # 6. Pet Lifecycle: Summon pet (2468 -> 2469)
            client.send_event(2468, PetSummonReq(pet_slot=0).encode())
            _, ack2469 = await client.expect_event(2469)
            res, slot = struct.unpack_from('<IH', ack2469, 0)
            self.assertEqual(res, 0)
            self.assertEqual(slot, 0)
            char = session.GameSession.store().get('OfflinePlayer', char_id)
            self.assertEqual(char.get('summoned_pet'), 0)

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

            client.send_event(2038, struct.pack('<qI', 1001, 1))
            _, ack2039_pet = await client.expect_event(2039)
            self.assertEqual(struct.unpack_from('<i', ack2039_pet, 0)[0], 0)
            char = session.GameSession.store().get('OfflinePlayer', char_id)
            self.assertEqual(len(char.get('pets', [])), 1)
            self.assertEqual(char['pets'][0]['code'], 'PetCall001')

            # 14. Item Use: ridecall whistle item consumption activates mount
            client.send_event(2038, struct.pack('<qI', 1002, 1))
            _, ack2039_ride = await client.expect_event(2039)
            self.assertEqual(struct.unpack_from('<i', ack2039_ride, 0)[0], 0)
            char = session.GameSession.store().get('OfflinePlayer', char_id)
            self.assertEqual(len(char.get('mounts', [])), 1)
            self.assertEqual(char['mounts'][0]['code'], 'ridecall0')

        self.run_async(self.with_server(scenario))


if __name__ == '__main__':
    unittest.main()
