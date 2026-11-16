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
        ack_buy = messages.BuyItemAck(result=0, gold=99800, items=[])
        enc_buy = ack_buy.encode()
        self.assertEqual(struct.unpack_from('<i', enc_buy)[0], 0)
        self.assertEqual(enc_buy[4:5], b'\x1e')

        raw_sell = struct.pack('<iqi', 1, 7777777, 1)
        req_sell = messages.SellItemReq.decode(raw_sell)
        self.assertEqual((req_sell.npc_id, req_sell.item_uid, req_sell.count), (1, 7777777, 1))
        ack_sell = messages.SellItemAck(result=0, gold=100050, items=[])
        enc_sell = ack_sell.encode()
        self.assertEqual(struct.unpack_from('<i', enc_sell)[0], 0)

        raw_re = struct.pack('<q', 8888888)
        req_re = messages.RepurchaseItemReq.decode(raw_re)
        self.assertEqual(req_re.item_uid, 8888888)
        ack_re = messages.RepurchaseItemAck(result=0, gold=100050, items=[])
        enc_re = ack_re.encode()
        self.assertEqual(struct.unpack_from('<i', enc_re)[0], 0)

    def test_friend_list_management_messages(self):
        req_add = messages.FriendListAddReq.decode('BestFriend'.encode('utf-16le'))
        self.assertEqual(req_add.char_name, 'BestFriend')

        ack_add = messages.FriendListAddAck(result=0xCE)
        self.assertEqual(struct.unpack_from('<i', ack_add.encode())[0], 0xCE)

        req_del = messages.FriendListDeleteReq.decode(struct.pack('<q', 54321))
        self.assertEqual(req_del.char_uid, 54321)

        ack_del = messages.FriendListDeleteAck(result=0, char_uid=54321)
        self.assertEqual(struct.unpack_from('<iq', ack_del.encode()), (0, 54321))

    def test_new_opcodes_messages(self):
        # 1. Change bag name (2032 / 2033)
        bname = 'Potions'.encode('utf-16le') + b'\x00\x00'
        req_bn = messages.ChangeBagNameReq.decode(struct.pack('<q', 2) + bname)
        self.assertEqual((req_bn.bag_uid, req_bn.name), (2, 'Potions'))
        ack_bn = messages.ChangeBagNameAck(result=0, bag_uid=2, name='Potions').encode()
        self.assertEqual(struct.unpack_from('<iq', ack_bn), (0, 2))

        # 2. Skill locked (2117 / 2118)
        req_sl = messages.UpdateSkillLockedReq.decode(struct.pack('<h?', 201, True))
        self.assertEqual((req_sl.skill_index, req_sl.locked), (201, True))
        ack_sl = messages.UpdateSkillLockedAck(result=0, skill_index=201, locked=True).encode()
        self.assertEqual(struct.unpack_from('<ih?', ack_sl), (0, 201, True))

        # 3. Durability repair (2145 / 2146)
        ack_rep = messages.DurabilityRepairAck(result=0, remain_gold=50000).encode()
        self.assertEqual(struct.unpack_from('<i', ack_rep)[0], 0)
        self.assertEqual(ack_rep[4:6], b'\x17\x80')
        self.assertEqual(struct.unpack_from('<q', ack_rep, 6)[0], 50000)

        # 4. Item upgrade (2115 / 2116)
        raw_up = struct.pack('<qqq', 10, 20, 30)
        req_up = messages.ItemUpgradeReq.decode(raw_up)
        self.assertEqual((req_up.target_uid, req_up.catalyst_uid, req_up.protect_uid), (10, 20, 30))
        ack_up = messages.ItemUpgradeAck(result=1).encode()
        self.assertEqual(struct.unpack_from('<i', ack_up)[0], 1)

        # 5. Buy life water (2086 / 2087)
        req_lw = messages.BuyLifeWaterReq.decode(struct.pack('<?', True))
        self.assertTrue(req_lw.flag)
        ack_lw = messages.BuyLifeWaterAck(result=0, flag=True, remain_currency=999).encode()
        self.assertEqual(struct.unpack_from('<i?q', ack_lw), (0, True, 999))

        # 6. Speaker item (2128 / 2129)
        msg_raw = 'Hello World'.encode('utf-16le') + b'\x00\x00'
        raw_spk = struct.pack('<q', 555) + msg_raw + struct.pack('<q', 0)
        req_spk = messages.UseSpeakerItemReq.decode(raw_spk)
        self.assertEqual((req_spk.speaker_uid, req_spk.message, req_spk.target_uid), (555, 'Hello World', 0))
        ack_spk = messages.UseSpeakerItemAck(result=0, speaker_uid=555).encode()
        self.assertEqual(struct.unpack_from('<iq', ack_spk[:12]), (0, 555))

        # 7. Guild create (2150 / 2151 / 5121 / 5122)
        req_gc = messages.GuildCreateReq.decode('Knights'.encode('utf-16le') + b'\x00\x00')
        self.assertEqual(req_gc.guild_name, 'Knights')
        ack_gc = messages.GuildCreateAck(result=0, guild_uid=123, guild_name='Knights', remain_gold=1000).encode()
        self.assertEqual(struct.unpack_from('<iq', ack_gc[:12]), (0, 123))
        ack_prop = messages.GuildCreateProposalAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', ack_prop)[0], 0)

        # 8. Contract update (2121 / 2122)
        req_cu = messages.ContractUpdateReq.decode(struct.pack('<i', 42))
        self.assertEqual(req_cu.contract_id, 42)
        ack_cu = messages.ContractUpdateAck(result=0, contract_id=42).encode()
        self.assertEqual(struct.unpack_from('<ii', ack_cu), (0, 42))

        # 9. Friend list update (2133 / 2134)
        memo = 'My friend'.encode('utf-16le') + b'\x00\x00'
        req_fu = messages.FriendListUpdateReq.decode(struct.pack('<q', 999) + memo)
        self.assertEqual((req_fu.char_uid, req_fu.comment), (999, 'My friend'))
        ack_fu = messages.FriendListUpdateAck(result=0, char_uid=999, comment='My friend').encode()
        self.assertEqual(struct.unpack_from('<iq', ack_fu), (0, 999))

        # 10. Durability change (2143 / 2144)
        ack_dc = messages.DurabilityChangeAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', ack_dc)[0], 0)

        # 11. Guild member actions (2155/2156, 2160/2161, 2162/2163)
        req_gj = messages.GuildPersonJoinReq.decode(struct.pack('<q', 1001))
        self.assertEqual(req_gj.guild_uid, 1001)
        ack_gj = messages.GuildPersonJoinAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', ack_gj)[0], 0)

        req_gi = messages.GuildInviteReq.decode('Hero'.encode('utf-16le') + b'\x00\x00')
        self.assertEqual(req_gi.char_name, 'Hero')
        ack_gi = messages.GuildInviteAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', ack_gi)[0], 0)

        req_gl = messages.GuildPersonLeaveReq.decode(b'')
        self.assertIsNotNone(req_gl)
        ack_gl = messages.GuildPersonLeaveAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', ack_gl)[0], 0)

        # 12. Guild banking & economy (2179/2180, 2181/2182)
        req_gmi = messages.GuildMoneyInReq.decode(struct.pack('<q', 50000))
        self.assertEqual(req_gmi.amount, 50000)
        ack_gmi = messages.GuildMoneyInAck(result=0, remain_gold=25000).encode()
        self.assertEqual(struct.unpack_from('<iq', ack_gmi), (0, 25000))

        req_gmo = messages.GuildMoneyOutReq.decode(struct.pack('<q', 10000))
        self.assertEqual(req_gmo.amount, 10000)
        ack_gmo = messages.GuildMoneyOutAck(result=0, remain_gold=35000).encode()
        self.assertEqual(struct.unpack_from('<iq', ack_gmo), (0, 35000))

        # 13. Guild progression & notice (2183/2184, 2185/2186, 2188/2189, 2214/2215)
        req_glu = messages.GuildLevelUpReq.decode(b'')
        self.assertIsNotNone(req_glu)
        ack_glu = messages.GuildLevelUpAck(result=0, new_level=3).encode()
        self.assertEqual(struct.unpack_from('<ih', ack_glu), (0, 3))

        notice_text = 'Welcome to the guild!'.encode('utf-16le')
        req_gnm = messages.GuildNoticeModifyReq.decode(notice_text)
        self.assertEqual(req_gnm.notice, 'Welcome to the guild!')
        ack_gnm = messages.GuildNoticeModifyAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', ack_gnm)[0], 0)

        req_gnd = messages.GuildNoticeDeleteReq.decode(b'')
        self.assertIsNotNone(req_gnd)
        ack_gnd = messages.GuildNoticeDeleteAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', ack_gnd)[0], 0)

        req_gsi = messages.GuildAllSkillInitReq.decode(b'')
        self.assertIsNotNone(req_gsi)
        ack_gsi = messages.GuildAllSkillInitAck(result=0, param=0).encode()
        self.assertEqual(struct.unpack_from('<ii', ack_gsi), (0, 0))





if __name__ == '__main__':
    unittest.main()
