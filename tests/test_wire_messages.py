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

    def test_mailbox_messages(self):
        req_send = messages.PostSendReq.decode(b'')
        self.assertIsNotNone(req_send)
        ack_send = messages.PostSendAck(result=0, items=[]).encode()
        self.assertEqual(ack_send[:5], b'\x00\x00\x00\x00\x10')

        req_read = messages.PostReadReq.decode(struct.pack('<q', 12345))
        self.assertEqual(req_read.mail_uid, 12345)
        ack_read = messages.PostReadAck(result=0, mail_uid=12345).encode()
        self.assertEqual(struct.unpack_from('<iq', ack_read), (0, 12345))

        req_item = messages.PostGetAppendItemReq.decode(struct.pack('<q', 54321))
        self.assertEqual(req_item.mail_uid, 54321)
        ack_item = messages.PostGetAppendItemAck(result=0, mail_uid=54321, gold=500, items=[]).encode()
        self.assertEqual(struct.unpack_from('<iqq', ack_item[:20]), (0, 54321, 500))

        del_payload = b'\x10' + jser.varuint(2) + struct.pack('<qq', 101, 102)
        req_del = messages.PostDeleteReq.decode(del_payload)
        self.assertEqual(req_del.mail_uids, [101, 102])
        ack_del = messages.PostDeleteAck(result=0, mail_uids=[101, 102]).encode()
        self.assertEqual(ack_del[:5], b'\x00\x00\x00\x00\x10')

    def test_trade_messages(self):
        req_tr = messages.RequestTradeReq.decode(struct.pack('<q', 8888))
        self.assertEqual(req_tr.target_uid, 8888)
        ack_tr = messages.RequestTradeAck(result=0, target_uid=8888, target_name='Partner').encode()
        self.assertEqual(struct.unpack_from('<iq', ack_tr[:12]), (0, 8888))

        req_art = messages.AcceptRequestTradeReq.decode(struct.pack('<q', 7777))
        self.assertEqual(req_art.source_uid, 7777)
        ack_art = messages.AcceptRequestTradeAck(result=0, source_uid=7777, target_uid=8888).encode()
        self.assertEqual(struct.unpack_from('<iqq', ack_art), (0, 7777, 8888))

        req_ct = messages.CancelTradeReq.decode(b'')
        self.assertIsNotNone(req_ct)
        ack_ct = messages.CancelTradeAck(result=0, items=[]).encode()
        self.assertEqual(ack_ct[:5], b'\x00\x00\x00\x00\x10')

        req_iti = messages.InsertTradeItemReq.decode(struct.pack('<qi', 9999, 1))
        self.assertEqual((req_iti.item_uid, req_iti.slot), (9999, 1))
        ack_iti = messages.InsertTradeItemAck(result=0, items=[]).encode()
        self.assertEqual(ack_iti[:5], b'\x00\x00\x00\x00\x10')

        req_dti = messages.DeleteTradeItemReq.decode(struct.pack('<q', 9999))
        self.assertEqual(req_dti.item_uid, 9999)
        ack_dti = messages.DeleteTradeItemAck(result=0, items=[]).encode()
        self.assertEqual(ack_dti[:5], b'\x00\x00\x00\x00\x10')

        req_uta = messages.UpdateTradeArReq.decode(struct.pack('<q', 50000))
        self.assertEqual(req_uta.gold, 50000)
        ack_uta = messages.UpdateTradeArAck(result=0, char_uid=1, gold=50000).encode()
        self.assertEqual(struct.unpack_from('<iqq', ack_uta), (0, 1, 50000))

        req_at = messages.AcceptTradeReq.decode(b'')
        self.assertIsNotNone(req_at)
        ack_at = messages.AcceptTradeAck(result=0, char_uid=1, accepted=True).encode()
        self.assertEqual(struct.unpack_from('<iq?', ack_at), (0, 1, True))

        req_fat = messages.FinallyAcceptTradeReq.decode(b'')
        self.assertIsNotNone(req_fat)
        ack_fat = messages.FinallyAcceptTradeAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', ack_fat), (0,))

    def test_party_and_team_messages(self):
        req_pi = messages.PartyInviteReq.decode(struct.pack('<q', 5555))
        self.assertEqual(req_pi.target_uid, 5555)
        ack_pi = messages.PartyInviteAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', ack_pi), (0,))

        req_pa = messages.PartyAcceptInviteReq.decode(struct.pack('<q', 4444))
        self.assertEqual(req_pa.host_uid, 4444)
        ack_pa = messages.PartyAcceptInviteAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', ack_pa), (0,))

        req_ct = messages.ChangeTeamReq.decode(struct.pack('<i', 2))
        self.assertEqual(req_ct.team_id, 2)
        ack_ct = messages.ChangeTeamAck(result=0, team_id=2).encode()
        self.assertEqual(struct.unpack_from('<ii', ack_ct), (0, 2))

    def test_chat_messages(self):
        msg_raw = b'\x00' + 'Hello world'.encode('utf-16le')
        req_chat = messages.ChatReq.decode(msg_raw)
        self.assertEqual(req_chat.channel, 0)
        ack_chat = messages.ChatAck(result=0, channel=0, sender='Tester', message='Hello world').encode()
        self.assertEqual(struct.unpack_from('<iB', ack_chat[:5]), (0, 0))

    def test_quest_giveup_fail_messages(self):
        req_gu = messages.QuestGiveupReq.decode(struct.pack('<I', 0x12345678))
        self.assertEqual(req_gu.quest_id, 0x12345678)
        ack_gu = messages.QuestGiveupAck(result=0, quest_id=0x12345678).encode()
        self.assertEqual(struct.unpack_from('<iI', ack_gu[:8]), (0, 0x12345678))

        req_fl = messages.QuestFailReq.decode(struct.pack('<I', 0x87654321))
        self.assertEqual(req_fl.quest_id, 0x87654321)
        ack_fl = messages.QuestFailAck(result=0, quest_id=0x87654321).encode()
        self.assertEqual(struct.unpack_from('<iI', ack_fl[:8]), (0, 0x87654321))

    def test_magic_enchant_and_upgrade_messages(self):
        req_enc = messages.MagicEnchantEnchantReq.decode(struct.pack('<qqq', 1, 2, 3))
        self.assertEqual((req_enc.item_uid, req_enc.catalyst_uid, req_enc.scroll_uid), (1, 2, 3))
        ack_enc = messages.MagicEnchantEnchantAck(result=0, items=[], gold=1000).encode()
        self.assertEqual(struct.unpack_from('<i', ack_enc)[0], 0)

        req_era = messages.MagicEnchantEraseOptionReq.decode(struct.pack('<q', 1))
        self.assertEqual(req_era.item_uid, 1)
        ack_era = messages.MagicEnchantEraseOptionAck(result=0, items=[], gold=1000).encode()
        self.assertEqual(struct.unpack_from('<i', ack_era)[0], 0)

        req_exp = messages.MagicEnchantExpendSlotReq.decode(struct.pack('<qq', 1, 2))
        self.assertEqual((req_exp.item_uid, req_exp.stone_uid), (1, 2))
        ack_exp = messages.MagicEnchantExpendSlotAck(result=0, items=[]).encode()
        self.assertEqual(struct.unpack_from('<i', ack_exp)[0], 0)

        req_rnd = messages.RandomItemUpgradeReq.decode(struct.pack('<qq', 1, 2))
        self.assertEqual((req_rnd.item_uid, req_rnd.stone_uid), (1, 2))
        ack_rnd = messages.RandomItemUpgradeAck(result=0, items=[]).encode()
        self.assertEqual(struct.unpack_from('<i', ack_rnd)[0], 0)

        req_fix = messages.FixItemUpgradeReq.decode(struct.pack('<qq', 1, 2))
        self.assertEqual((req_fix.item_uid, req_fix.stone_uid), (1, 2))
        ack_fix = messages.FixItemUpgradeAck(result=0, items=[]).encode()
        self.assertEqual(struct.unpack_from('<i', ack_fix)[0], 0)

    def test_item_pickup_and_drop_messages(self):
        req_p = messages.PickUpItemReq.decode(struct.pack('<q', 999))
        self.assertEqual(req_p.drop_uid, 999)
        ack_p = messages.PickUpItemAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', ack_p)[0], 0)

        ack_res = messages.PickUpItemResultAck(result=0, picker_uid=123, item=None).encode()
        self.assertEqual(struct.unpack_from('<iq', ack_res[:12]), (0, 123))

        not_ar = messages.GetDropArNot(result=0, gold=500, drop_id=1, picker_uid=123).encode()
        self.assertEqual(struct.unpack_from('<iiiq', not_ar), (0, 500, 1, 123))

    def test_friend_presence_and_char_info_messages(self):
        not_conn = messages.FriendMyConnectionNot(char_uid=777, is_online=True).encode()
        self.assertEqual(struct.unpack_from('<q?', not_conn[:9]), (777, True))

        not_disc = messages.FriendMyDisconnectionNot(char_uid=777, notify=True).encode()
        self.assertEqual(struct.unpack_from('<q?', not_disc), (777, True))

        not_info = messages.UpdateCharInfoNot(char_details=b'\x01\x02\x03', layer_net_id=555).encode()
        self.assertEqual(not_info[0], 0x1E)

    def test_customization_and_keymapping_messages(self):
        req_nick = messages.CharNickChangeReq.decode(jser.wide_string('NewHero') + struct.pack('<q', 123))
        self.assertEqual((req_nick.new_name, req_nick.item_uid), ('NewHero', 123))
        ack_nick = messages.CharNickChangeAck(result=0, items=[], new_name='NewHero').encode()
        self.assertEqual(struct.unpack_from('<i', ack_nick)[0], 0)

        req_gname = messages.GuildNameChangeReq.decode(jser.wide_string('NewGuild') + struct.pack('<q', 456))
        self.assertEqual((req_gname.new_name, req_gname.item_uid), ('NewGuild', 456))
        ack_gname = messages.GuildNameChangeAck(result=0, items=[], new_name='NewGuild').encode()
        self.assertEqual(struct.unpack_from('<i', ack_gname)[0], 0)

        req_key = messages.KeyboardSetCustomKeyReq.decode(b'\x01\x02\x03\x04')
        self.assertEqual(req_key.keys_blob, b'\x01\x02\x03\x04')
        ack_key = messages.KeyboardSetCustomKeyAck(result=0, keys_blob=b'\x01\x02\x03\x04').encode()
        self.assertEqual(struct.unpack_from('<i', ack_key)[0], 0)

        req_sp = messages.ItemSpiritChangeReq.decode(struct.pack('<qq', 1, 2))
        self.assertEqual((req_sp.item_uid, req_sp.spirit_item_uid), (1, 2))
        ack_sp = messages.ItemSpiritChangeAck(result=0, spirit_uid=2, items=[]).encode()
        self.assertEqual(struct.unpack_from('<iq', ack_sp[:12]), (0, 2))

    def test_mentoring_and_teaching_messages(self):
        req_tr = messages.RequestTeachingReq.decode(struct.pack('<q', 12345))
        self.assertEqual(req_tr.target_uid, 12345)
        ack_tr = messages.RequestTeachingAck(result=0, target_uid=12345, target_name='Student').encode()
        self.assertEqual(struct.unpack_from('<iq', ack_tr[:12]), (0, 12345))

        req_at = messages.AcceptRequestTeachingReq.decode(struct.pack('<q', 54321))
        self.assertEqual(req_at.mentor_uid, 54321)
        ack_at = messages.AcceptRequestTeachingAck(result=0, accepted=True, mentor_uid=54321, mentor_name='Master').encode()
        self.assertEqual(struct.unpack_from('<i?q', ack_at[:13]), (0, True, 54321))

        not_info = messages.TeachingGetInfoNot().encode()
        self.assertEqual(not_info, b'\x1e\x00')

    def test_citadel_and_gold_goblin_messages(self):
        not_ts = messages.TreasureStartNot(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', not_ts)[0], 0)

        not_te = messages.TreasureEndNot(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', not_te)[0], 0)

        not_cit = messages.CitadelRewardNot(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', not_cit[:4])[0], 0)

        not_ga = messages.GoldGoblinAppearNot(goblin_id=1).encode()
        self.assertEqual(struct.unpack_from('<i', not_ga[:4])[0], 1)

        req_atk = messages.GoldGoblinAttackReq.decode(struct.pack('<ii', 1, 500))
        self.assertEqual((req_atk.goblin_id, req_atk.damage), (1, 500))
        ack_atk = messages.GoldGoblinAttackAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', ack_atk)[0], 0)

        req_dead = messages.GoldGoblinDeadReq.decode(struct.pack('<i', 1))
        self.assertEqual(req_dead.goblin_id, 1)
        ack_dead = messages.GoldGoblinDeadAck(result=0, goblin_id=1, items=[]).encode()
        self.assertEqual(struct.unpack_from('<ii', ack_dead[:8]), (0, 1))

        not_gd = messages.GoldGoblinDisappearNot(goblin_id=1).encode()
        self.assertEqual(struct.unpack_from('<i', not_gd)[0], 1)

    def test_achieve_and_title_messages(self):
        req_title = messages.TitleChangeReq.decode(struct.pack('<i', 101))
        self.assertEqual(req_title.title_id, 101)
        ack_title = messages.TitleChangeAck(result=0, title_id=101).encode()
        self.assertEqual(struct.unpack_from('<ii', ack_title), (0, 101))

        req_ach = messages.AchieveGetListReq.decode(b'')
        self.assertIsInstance(req_ach, messages.AchieveGetListReq)
        ack_ach = messages.AchieveGetListAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', ack_ach[:4])[0], 0)
        self.assertEqual(ack_ach[4:6], b'\x1e\x17')

        not_change = messages.AchieveChangeNot().encode()
        self.assertEqual(not_change, b'\x17\x80\x17\x80\x17\x80')

        not_complete = messages.AchieveCompleteNot().encode()
        self.assertEqual(not_complete, b'\x10\x80\x10\x80')

    def test_avatar_zam_and_taming_messages(self):
        req_zam = messages.AvatarZamInsertReq.decode(struct.pack('<qq', 10, 20))
        self.assertEqual((req_zam.avatar_item_uid, req_zam.zam_item_uid), (10, 20))
        ack_zam = messages.AvatarZamInsertAck(result=0, updated_items=[]).encode()
        self.assertEqual(struct.unpack_from('<i', ack_zam[:4])[0], 0)

        req_ezam = messages.AvatarZamEraseReq.decode(struct.pack('<q', 10))
        self.assertEqual(req_ezam.avatar_item_uid, 10)
        ack_ezam = messages.AvatarZamEraseAck(result=0, updated_items=[]).encode()
        self.assertEqual(struct.unpack_from('<i', ack_ezam[:4])[0], 0)

        req_tdel = messages.TameingMonsterDeleteReq.decode(struct.pack('<ii', 5, 1))
        self.assertEqual((req_tdel.monster_id, req_tdel.slot), (5, 1))
        ack_tdel = messages.TamingMonsterDeleteAck(result=0, deleted_slot=1).encode()
        self.assertEqual(struct.unpack_from('<i', ack_tdel[:4])[0], 0)

    def test_promotion_skill_reset_and_rebirth_coins(self):
        not_init = messages.InitSkillNot(result=0, sp=50).encode()
        self.assertEqual(struct.unpack_from('<ii', not_init[:8]), (0, 50))

        not_promo = messages.PromotionNot(result=0, new_class=2, sp=20).encode()
        self.assertEqual(struct.unpack_from('<iBi', not_promo[:9]), (0, 2, 20))

        not_coin = messages.RebirthCoinChangeNot(result=0, coins=15).encode()
        self.assertEqual(struct.unpack_from('<ih', not_coin), (0, 15))

    def test_arena_sp_and_second_pass_messages(self):
        req_asp = messages.UseArenaSpItemReq.decode(struct.pack('<q', 77))
        self.assertEqual(req_asp.item_uid, 77)
        ack_asp = messages.UseArenaSpItemAck(result=0, consumed_items=[], arena_sp=150).encode()
        self.assertEqual(struct.unpack_from('<i', ack_asp[:4])[0], 0)

        req_aback = messages.ArenaBackToSquareReq.decode(b'')
        self.assertIsInstance(req_aback, messages.ArenaBackToSquareReq)
        ack_aback = messages.ArenaBackToSquareAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', ack_aback), (0,))

        ack_sp1 = messages.SecondPassCreateAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', ack_sp1), (0,))
        ack_sp2 = messages.SecondPassModifyAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', ack_sp2), (0,))
        ack_sp3 = messages.SecondPassAuthAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', ack_sp3), (0,))

    def test_remote_inspection_messages(self):
        req_c = messages.RequestCharInfoReq.decode(struct.pack('<q', 123))
        self.assertEqual(req_c.char_uid, 123)
        ack_c = messages.RequestCharInfoAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', ack_c[:4])[0], 0)

        req_i = messages.RequestItemInfoReq.decode(struct.pack('<q', 456))
        self.assertEqual(req_i.item_uid, 456)
        ack_i = messages.RequestItemInfoAck(result=0, item_uid=456).encode()
        self.assertEqual(struct.unpack_from('<iq', ack_i[:12]), (0, 456))

    def test_guild_banking_and_level_up_messages(self):
        req_in = messages.GuildMoneyInReq.decode(struct.pack('<q', 5000))
        self.assertEqual(req_in.amount, 5000)
        ack_in = messages.GuildMoneyInAck(result=0, remain_gold=5000).encode()
        self.assertEqual(struct.unpack_from('<iq', ack_in), (0, 5000))

        req_out = messages.GuildMoneyOutReq.decode(struct.pack('<q', 2000))
        self.assertEqual(req_out.amount, 2000)
        ack_out = messages.GuildMoneyOutAck(result=0, remain_gold=3000).encode()
        self.assertEqual(struct.unpack_from('<iq', ack_out), (0, 3000))

        req_grade = messages.GuildPersonGradeModifyReq.decode(struct.pack('<qh', 888, 3))
        self.assertEqual((req_grade.member_uid, req_grade.new_grade), (888, 3))
        ack_grade = messages.GuildPersonGradeModifyAck(result=0, member_uid=888, new_grade=3).encode()
        self.assertEqual(struct.unpack_from('<iqh', ack_grade), (0, 888, 3))

        req_lvl = messages.GuildLevelUpReq.decode(b'')
        self.assertIsInstance(req_lvl, messages.GuildLevelUpReq)
        ack_lvl = messages.GuildLevelUpAck(result=0, new_level=3).encode()
        self.assertEqual(struct.unpack_from('<ih', ack_lvl), (0, 3))

        notice_bytes = 'Guild Notice'.encode('utf-16le') + b'\x00\x00'
        req_not = messages.GuildNoticeModifyReq.decode(notice_bytes)
        self.assertEqual(req_not.notice, 'Guild Notice')
        ack_not = messages.GuildNoticeModifyAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', ack_not), (0,))

        not_skill = messages.GuildSkillNot(flag=True).encode()
        self.assertEqual(not_skill, b'\x01\x10\x80')

    def test_depot_and_item_split_messages(self):
        req_div = messages.DivideItemReq.decode(struct.pack('<qqih', 10, 0, 5, 2))
        self.assertEqual((req_div.source_item_uid, req_div.count, req_div.slot), (10, 5, 2))
        ack_div = messages.DivideItemAck(result=0, items=[]).encode()
        self.assertEqual(struct.unpack_from('<i', ack_div[:4])[0], 0)

        req_lskill = messages.UseLearnSkillItemReq.decode(struct.pack('<qh', 99, 105))
        self.assertEqual((req_lskill.item_uid, req_lskill.skill_id), (99, 105))
        ack_lskill = messages.UseLearnSkillItemAck(result=0, skill_id=105, skill_level=1, item_code=50, count=1, sp=15).encode()
        self.assertEqual(struct.unpack_from('<ihBii', ack_lskill[:15]), (0, 105, 1, 50, 1))

        not_inven = messages.InventoryUpdatedNot().encode()
        self.assertEqual(not_inven, b'\x10\x80\x10\x80')

        not_time = messages.ItemRemainTimeNot(item_uid=123, remain_seconds=3600).encode()
        self.assertEqual(struct.unpack_from('<qq', not_time), (123, 3600))

        not_del = messages.ItemDeleteNot(item_uid=123).encode()
        self.assertEqual(struct.unpack_from('<q', not_del), (123,))

        req_dsave = messages.DepotSaveArReq.decode(struct.pack('<q', 10000))
        self.assertEqual(req_dsave.gold, 10000)
        ack_dsave = messages.DepotSaveArAck(result=0, new_gold=10000).encode()
        self.assertEqual(struct.unpack_from('<i', ack_dsave[:4])[0], 0)

        req_dload = messages.DepotLoadArReq.decode(struct.pack('<q', 5000))
        self.assertEqual(req_dload.gold, 5000)
        ack_dload = messages.DepotLoadArAck(result=0, new_gold=5000).encode()
        self.assertEqual(struct.unpack_from('<i', ack_dload[:4])[0], 0)

        not_mail = messages.PostNewArrivalNot().encode()
        self.assertEqual(not_mail, b'')

        req_pret = messages.PostReturnReq.decode(struct.pack('<q', 777))
        self.assertEqual(req_pret.mail_id, 777)
        ack_pret = messages.PostReturnAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', ack_pret[:4])[0], 0)

    def test_combat_ap_and_randombox_messages(self):
        not_ap = messages.InsertApNot(current_ap=50, total_ap=150).encode()
        self.assertEqual(struct.unpack_from('<ii', not_ap), (50, 150))

        not_pen = messages.ChangeDungeonPenaltyNot(in_dungeon=True, is_penalty=True, penalty_level=2, penalty_id=10, duration=60).encode()
        self.assertEqual(struct.unpack_from('<??hii', not_pen), (True, True, 2, 10, 60))

        not_rbox = messages.RandomboxResultItemNot(result=0, item_code=5001, count=3, is_jackpot=True).encode()
        self.assertEqual(struct.unpack_from('<iih?', not_rbox), (0, 5001, 3, True))






if __name__ == '__main__':
    unittest.main()
