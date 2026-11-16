"""Unit tests for wire message encoding and decoding."""
import struct
import unittest

from tests.common import ROOT
from darkblood.core import hashing
from darkblood.core.serialization import jser
from darkblood.games.entities.character import layer_net_id
from darkblood.games.entities.items import Item
from darkblood.games.network import messages


class WireMessagesTest(unittest.TestCase):
    def test_delete_character_messages(self):
        raw_req = struct.pack('<q', 123456789)
        req = messages.DeleteCharacterReq.decode(raw_req)
        self.assertEqual(req.char_uid, 123456789)

        ack = messages.DeleteCharacterAck(result=0, char_uid=123456789, complete_time=0)
        encoded = ack.encode()
        self.assertEqual(struct.unpack_from('<iqi', encoded), (0, 123456789, 0))

    def test_delete_item_messages(self):
        raw_req = struct.pack('<qi', 9999, 5)
        req = messages.DeleteItemReq.decode(raw_req)
        self.assertEqual((req.item_uid, req.amount), (9999, 5))

        ack = messages.DeleteItemAck(result=0, item_uid=9999, del_amount=5)
        self.assertEqual(struct.unpack_from('<iqi', ack.encode()), (0, 9999, 5))

    def test_switch_bag_messages(self):
        raw_req = struct.pack('<HH', 0, 1)
        req = messages.SwitchBagReq.decode(raw_req)
        self.assertEqual((req.from_index, req.to_index), (0, 1))

        ack = messages.SwitchBagAck(result=0, from_index=0, to_index=1)
        self.assertEqual(struct.unpack_from('<iHH', ack.encode()), (0, 0, 1))

    def test_switch_quickslot_messages(self):
        raw_req = struct.pack('<BBB', 0, 2, 3)
        req = messages.SwitchQuickslotReq.decode(raw_req)
        self.assertEqual((req.slot_type, req.from_slot, req.to_slot), (0, 2, 3))

        ack = messages.SwitchQuickslotAck(result=0, slot_type=0, from_slot=2, to_slot=3)
        self.assertEqual(struct.unpack_from('<iBBB', ack.encode()), (0, 0, 2, 3))

    def test_learn_skill_messages(self):
        raw_req = struct.pack('<HB', 105, 3)
        req = messages.LearnSkillReq.decode(raw_req)
        self.assertEqual((req.skill_index, req.level), (105, 3))

        ack = messages.LearnSkillAck(result=0, skill_index=105, level=3, remain_sp=50, remain_gold=12000)
        self.assertEqual(struct.unpack_from('<iHBiq', ack.encode()), (0, 105, 3, 50, 12000))

    def test_http_notice_messages(self):
        ack = messages.HttpNoticeCheckAck(result=0, watch=False)
        self.assertEqual(struct.unpack_from('<i?', ack.encode()), (0, False))

    def test_get_invite_list_messages(self):
        ack = messages.GetInviteListAck(result=0)
        encoded = ack.encode()
        self.assertEqual(struct.unpack_from('<i', encoded)[0], 0)
        self.assertEqual(encoded[4:], b'\x10\x80')

    def test_level_up_and_change_exp_not_messages(self):
        lvl = messages.LevelUpNot(char_uid=777, new_level=10, max_hp=1500, max_mp=800, flag=True)
        enc_lvl = lvl.encode()
        self.assertEqual(enc_lvl[0], 0x1e)
        self.assertEqual(enc_lvl[1:3], b'\r\x80')
        self.assertEqual(struct.unpack_from('<qBii?', enc_lvl, 3), (777, 10, 1500, 800, True))

        exp = messages.ChangeExpNot(exp_total=25000, exp_details=(50, 100, 0, 0, 0, 0, 0, 0, 2.0))
        enc_exp = exp.encode()
        self.assertEqual(struct.unpack_from('<i', enc_exp, 0)[0], 25000)
        self.assertEqual(enc_exp[4], 0x1e)
        details = struct.unpack_from('<iiiiiiiif', enc_exp, 5)
        self.assertEqual(details[:2], (50, 100))
        self.assertAlmostEqual(details[8], 2.0)

    def test_dungeon_messages(self):
        layer_id = (hashing.jhash('Act1_G1_A10') << 32) | 4
        msg_5095 = messages.ChangeDungeonLayerNot.decode(struct.pack('<iq', 0x7fffffff, layer_id))
        self.assertEqual(msg_5095.layer_id, 4)
        self.assertEqual(msg_5095.map_hash, hashing.jhash('Act1_G1_A10'))

        msg_2422 = messages.ActiveWarFlagReq.decode(struct.pack('<iI', 0x7fffffff, 31))
        self.assertEqual(msg_2422.war_flag_id, 31)

        raw_2358 = struct.pack('<i', 0x7fffffff) + b'\x10' + jser.varuint(2) + struct.pack('<II', 1, 2)
        msg_2358 = messages.GuideBeginnerUpdateReq.decode(raw_2358)
        self.assertEqual(msg_2358.guide_ids, [1, 2])

        msg_5063 = messages.MonsterDeadReq.decode(struct.pack('<iII', 0x7fffffff, 42, 1))
        self.assertEqual((msg_5063.monster_id, msg_5063.param), (42, 1))

        drop = messages.ItemDropEntry(drop_uid=1, item_id=hashing.jhash('Ihppa0024'), count=1, x=100.0, y=-2000.0, z=0.0)
        not_5064 = messages.DropItemNot(source_id=42, drops=[drop])
        enc_drop = not_5064.encode()
        self.assertTrue(enc_drop.startswith(struct.pack('<I', 42) + b'\x10'))

    def test_item_encoding_includes_count_at_offset_zero(self):
        item = Item(code='AbodT1N', uid=123, owner=1, container=1, slot=0, count=5)
        enc = item.encode()
        # count is at u16 +0 in the inner base structure (after two empty varuints: 2 bytes)
        self.assertEqual(struct.unpack_from('<H', enc, 2)[0], 5)

    def test_store_info_ack(self):
        ack = messages.StoreInfoAck(npc_id=1, items=[('Ihppa0001', -1)]).encode()
        self.assertEqual(ack[8:10], b'\x10\x81')
        self.assertEqual(struct.unpack_from('<Ii', ack, 10), (hashing.jhash('Ihppa0001'), -1))

    def test_change_bag_property_messages(self):
        raw_req = struct.pack('<qB', 2, 3)
        req = messages.ChangeBagPropertyReq.decode(raw_req)
        self.assertEqual((req.bag_uid, req.property), (2, 3))

        ack = messages.ChangeBagPropertyAck(result=0, bag_uid=2, property=3)
        self.assertEqual(struct.unpack_from('<iqB', ack.encode()), (0, 2, 3))

    def test_skill_speech_messages(self):
        req_mod = messages.ModifySkillSpeechReq.decode(struct.pack('<H', 105) + 'Fire!'.encode('utf-16le'))
        self.assertEqual(req_mod.skill_index, 105)

        ack_mod = messages.ModifySkillSpeechAck(result=0, skill_index=105, speech='Fire!')
        enc_mod = ack_mod.encode()
        self.assertEqual(struct.unpack_from('<iH', enc_mod[:6]), (0, 105))

        req_del = messages.DeleteSkillSpeechReq.decode(struct.pack('<H', 105))
        self.assertEqual(req_del.skill_index, 105)

        ack_del = messages.DeleteSkillSpeechAck(result=0, skill_index=105)
        self.assertEqual(struct.unpack_from('<iH', ack_del.encode()), (0, 105))

    def test_store_transaction_messages(self):
        raw_buy = struct.pack('<iiH', 1, 12345, 2)
        req_buy = messages.BuyItemReq.decode(raw_buy)
        self.assertEqual((req_buy.store_id, req_buy.item_id, req_buy.count), (1, 12345, 2))

        raw_sell = struct.pack('<iqi', 1, 7777777, 1)
        req_sell = messages.SellItemReq.decode(raw_sell)
        self.assertEqual((req_sell.npc_id, req_sell.item_uid, req_sell.count), (1, 7777777, 1))

        raw_re = struct.pack('<q', 8888888)
        req_re = messages.RepurchaseItemReq.decode(raw_re)
        self.assertEqual(req_re.item_uid, 8888888)

    def test_friend_list_management_messages(self):
        req_add = messages.FriendListAddReq.decode('BestFriend'.encode('utf-16le'))
        self.assertEqual(req_add.char_name, 'BestFriend')

        ack_add = messages.FriendListAddAck(result=0xCE)
        self.assertEqual(struct.unpack_from('<i', ack_add.encode())[0], 0xCE)

        req_del = messages.FriendListDeleteReq.decode(struct.pack('<q', 54321))
        self.assertEqual(req_del.char_uid, 54321)

        ack_del = messages.FriendListDeleteAck(result=0, char_uid=54321)
        self.assertEqual(struct.unpack_from('<iq', ack_del.encode()), (0, 54321))



if __name__ == '__main__':
    unittest.main()
