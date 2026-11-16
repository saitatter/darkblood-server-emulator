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

    def test_change_bag_name_messages(self):
        bname = 'Potions'.encode('utf-16le') + b'\x00\x00'
        req = messages.ChangeBagNameReq.decode(struct.pack('<q', 2) + bname)
        self.assertEqual(req.bag_uid, 2)
        self.assertEqual(req.name, 'Potions')
        ack = messages.ChangeBagNameAck(result=0, bag_uid=2, name='Potions').encode()
        self.assertEqual(struct.unpack_from('<iq', ack), (0, 2))

    def test_skill_locked_update_messages(self):
        req = messages.UpdateSkillLockedReq.decode(struct.pack('<h?', 201, True))
        self.assertEqual(req.skill_index, 201)
        self.assertTrue(req.locked)
        ack = messages.UpdateSkillLockedAck(result=0, skill_index=201, locked=True).encode()
        self.assertEqual(struct.unpack_from('<ih?', ack), (0, 201, True))

    def test_durability_repair_messages(self):
        ack = messages.DurabilityRepairAck(result=0, remain_gold=50000).encode()
        self.assertEqual(struct.unpack_from('<i', ack)[0], 0)
        self.assertEqual(ack[4:6], b'\x17\x80')
        self.assertEqual(struct.unpack_from('<q', ack, 6)[0], 50000)

    def test_item_upgrade_messages(self):
        raw_up = struct.pack('<qqq', 10, 20, 30)
        req = messages.ItemUpgradeReq.decode(raw_up)
        self.assertEqual(req.target_uid, 10)
        self.assertEqual(req.catalyst_uid, 20)
        self.assertEqual(req.protect_uid, 30)
        ack = messages.ItemUpgradeAck(result=1).encode()
        self.assertEqual(struct.unpack_from('<i', ack)[0], 1)

    def test_buy_life_water_messages(self):
        req = messages.BuyLifeWaterReq.decode(struct.pack('<?', True))
        self.assertTrue(req.flag)
        ack = messages.BuyLifeWaterAck(result=0, flag=True, remain_currency=999).encode()
        self.assertEqual(struct.unpack_from('<i?q', ack), (0, True, 999))

    def test_speaker_item_messages(self):
        msg_raw = 'Hello World'.encode('utf-16le') + b'\x00\x00'
        raw_spk = struct.pack('<q', 555) + msg_raw + struct.pack('<q', 0)
        req = messages.UseSpeakerItemReq.decode(raw_spk)
        self.assertEqual(req.speaker_uid, 555)
        self.assertEqual(req.message, 'Hello World')
        self.assertEqual(req.target_uid, 0)
        ack = messages.UseSpeakerItemAck(result=0, speaker_uid=555).encode()
        self.assertEqual(struct.unpack_from('<iq', ack[:12]), (0, 555))

    def test_guild_create_and_proposal_messages(self):
        req = messages.GuildCreateReq.decode('Knights'.encode('utf-16le') + b'\x00\x00')
        self.assertEqual(req.guild_name, 'Knights')
        ack = messages.GuildCreateAck(result=0, guild_uid=123, guild_name='Knights', remain_gold=1000).encode()
        self.assertEqual(struct.unpack_from('<iq', ack[:12]), (0, 123))
        ack_prop = messages.GuildCreateProposalAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', ack_prop)[0], 0)

    def test_contract_update_messages(self):
        req = messages.ContractUpdateReq.decode(struct.pack('<i', 42))
        self.assertEqual(req.contract_id, 42)
        ack = messages.ContractUpdateAck(result=0, contract_id=42).encode()
        self.assertEqual(struct.unpack_from('<ii', ack), (0, 42))

    def test_friend_list_update_memo_messages(self):
        memo = 'My friend'.encode('utf-16le') + b'\x00\x00'
        req = messages.FriendListUpdateReq.decode(struct.pack('<q', 999) + memo)
        self.assertEqual(req.char_uid, 999)
        self.assertEqual(req.comment, 'My friend')
        ack = messages.FriendListUpdateAck(result=0, char_uid=999, comment='My friend').encode()
        self.assertEqual(struct.unpack_from('<iq', ack), (0, 999))

    def test_durability_change_messages(self):
        ack = messages.DurabilityChangeAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', ack)[0], 0)

    def test_guild_member_join_invite_leave_messages(self):
        req_j = messages.GuildPersonJoinReq.decode(struct.pack('<q', 1001))
        self.assertEqual(req_j.guild_uid, 1001)
        ack_j = messages.GuildPersonJoinAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', ack_j)[0], 0)

        req_i = messages.GuildInviteReq.decode('Hero'.encode('utf-16le') + b'\x00\x00')
        self.assertEqual(req_i.char_name, 'Hero')
        ack_i = messages.GuildInviteAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', ack_i)[0], 0)

        req_l = messages.GuildPersonLeaveReq.decode(b'')
        self.assertIsNotNone(req_l)
        ack_l = messages.GuildPersonLeaveAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', ack_l)[0], 0)

    def test_guild_all_skill_init_messages(self):
        req = messages.GuildAllSkillInitReq.decode(b'')
        self.assertIsNotNone(req)
        ack = messages.GuildAllSkillInitAck(result=0, param=0).encode()
        self.assertEqual(struct.unpack_from('<ii', ack), (0, 0))

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

    def test_character_nick_change_encoding(self):
        req = messages.CharNickChangeReq.decode(jser.wide_string('NewHero') + struct.pack('<q', 123))
        self.assertEqual(req.new_name, 'NewHero')
        self.assertEqual(req.item_uid, 123)
        ack = messages.CharNickChangeAck(result=0, items=[], new_name='NewHero').encode()
        self.assertEqual(struct.unpack_from('<i', ack)[0], 0)
        self.assertIn(b'N\x00e\x00w\x00H\x00e\x00r\x00o\x00', ack)

    def test_guild_name_change_encoding(self):
        req = messages.GuildNameChangeReq.decode(jser.wide_string('NewGuild') + struct.pack('<q', 456))
        self.assertEqual(req.new_name, 'NewGuild')
        self.assertEqual(req.item_uid, 456)
        ack = messages.GuildNameChangeAck(result=0, items=[], new_name='NewGuild').encode()
        self.assertEqual(struct.unpack_from('<i', ack)[0], 0)
        self.assertIn(b'N\x00e\x00w\x00G\x00u\x00i\x00l\x00d\x00', ack)

    def test_keyboard_custom_key_mapping(self):
        payload = b'\x01\x02\x03\x04'
        req = messages.KeyboardSetCustomKeyReq.decode(payload)
        self.assertEqual(req.keys_blob, payload)
        ack = messages.KeyboardSetCustomKeyAck(result=0, keys_blob=payload).encode()
        self.assertEqual(struct.unpack_from('<i', ack)[0], 0)
        self.assertIn(payload, ack)

    def test_item_spirit_weapon_transformation(self):
        req = messages.ItemSpiritChangeReq.decode(struct.pack('<qq', 100, 200))
        self.assertEqual(req.item_uid, 100)
        self.assertEqual(req.spirit_item_uid, 200)
        ack = messages.ItemSpiritChangeAck(result=0, spirit_uid=200, items=[]).encode()
        self.assertEqual(struct.unpack_from('<iq', ack[:12]), (0, 200))

    def test_mentoring_request_teaching(self):
        req = messages.RequestTeachingReq.decode(struct.pack('<q', 12345))
        self.assertEqual(req.target_uid, 12345)
        ack = messages.RequestTeachingAck(result=0, target_uid=12345, target_name='Student').encode()
        self.assertEqual(struct.unpack_from('<iq', ack[:12]), (0, 12345))
        self.assertIn(b'S\x00t\x00u\x00d\x00e\x00n\x00t\x00', ack)

    def test_mentoring_accept_teaching(self):
        req = messages.AcceptRequestTeachingReq.decode(struct.pack('<q', 54321))
        self.assertEqual(req.mentor_uid, 54321)
        ack = messages.AcceptRequestTeachingAck(result=0, accepted=True, mentor_uid=54321, mentor_name='Master').encode()
        self.assertEqual(struct.unpack_from('<i?q', ack[:13]), (0, True, 54321))
        self.assertIn(b'M\x00a\x00s\x00t\x00e\x00r\x00', ack)

    def test_teaching_get_info_notification(self):
        not_info = messages.TeachingGetInfoNot().encode()
        self.assertEqual(not_info, b'\x1e\x00')

    def test_citadel_and_treasure_notifications(self):
        not_ts = messages.TreasureStartNot(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', not_ts)[0], 0)
        not_te = messages.TreasureEndNot(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', not_te)[0], 0)
        not_cit = messages.CitadelRewardNot(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', not_cit[:4])[0], 0)

    def test_gold_goblin_event_cycle(self):
        not_ga = messages.GoldGoblinAppearNot(goblin_id=42).encode()
        self.assertEqual(struct.unpack_from('<i', not_ga[:4])[0], 42)

        req_atk = messages.GoldGoblinAttackReq.decode(struct.pack('<ii', 42, 1250))
        self.assertEqual(req_atk.goblin_id, 42)
        self.assertEqual(req_atk.damage, 1250)
        ack_atk = messages.GoldGoblinAttackAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', ack_atk)[0], 0)

        req_dead = messages.GoldGoblinDeadReq.decode(struct.pack('<i', 42))
        self.assertEqual(req_dead.goblin_id, 42)
        ack_dead = messages.GoldGoblinDeadAck(result=0, goblin_id=42, items=[]).encode()
        self.assertEqual(struct.unpack_from('<ii', ack_dead[:8]), (0, 42))

        not_gd = messages.GoldGoblinDisappearNot(goblin_id=42).encode()
        self.assertEqual(struct.unpack_from('<i', not_gd)[0], 42)

    def test_character_title_change(self):
        req = messages.TitleChangeReq.decode(struct.pack('<i', 101))
        self.assertEqual(req.title_id, 101)
        ack = messages.TitleChangeAck(result=0, title_id=101).encode()
        self.assertEqual(struct.unpack_from('<ii', ack), (0, 101))

    def test_achievements_list_and_notifications(self):
        req = messages.AchieveGetListReq.decode(b'')
        self.assertIsInstance(req, messages.AchieveGetListReq)
        ack = messages.AchieveGetListAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', ack[:4])[0], 0)
        self.assertEqual(ack[4:6], b'\x1e\x17')

        not_change = messages.AchieveChangeNot().encode()
        self.assertEqual(not_change, b'\x17\x80\x17\x80\x17\x80')

        not_complete = messages.AchieveCompleteNot().encode()
        self.assertEqual(not_complete, b'\x10\x80\x10\x80')

    def test_avatar_zam_socketing_and_erase(self):
        req_ins = messages.AvatarZamInsertReq.decode(struct.pack('<qq', 10, 20))
        self.assertEqual(req_ins.avatar_item_uid, 10)
        self.assertEqual(req_ins.zam_item_uid, 20)
        ack_ins = messages.AvatarZamInsertAck(result=0, updated_items=[]).encode()
        self.assertEqual(struct.unpack_from('<i', ack_ins[:4])[0], 0)

        req_erase = messages.AvatarZamEraseReq.decode(struct.pack('<q', 10))
        self.assertEqual(req_erase.avatar_item_uid, 10)
        ack_erase = messages.AvatarZamEraseAck(result=0, updated_items=[]).encode()
        self.assertEqual(struct.unpack_from('<i', ack_erase[:4])[0], 0)

    def test_taming_monster_management(self):
        req_del = messages.TameingMonsterDeleteReq.decode(struct.pack('<ii', 5, 1))
        self.assertEqual(req_del.monster_id, 5)
        self.assertEqual(req_del.slot, 1)
        ack_del = messages.TamingMonsterDeleteAck(result=0, deleted_slot=1).encode()
        self.assertEqual(struct.unpack_from('<i', ack_del[:4])[0], 0)

    def test_class_promotion_and_skill_reset(self):
        not_init = messages.InitSkillNot(result=0, sp=50).encode()
        self.assertEqual(struct.unpack_from('<ii', not_init[:8]), (0, 50))

        not_promo = messages.PromotionNot(result=0, new_class=2, sp=20).encode()
        self.assertEqual(struct.unpack_from('<iBi', not_promo[:9]), (0, 2, 20))

        not_coin = messages.RebirthCoinChangeNot(result=0, coins=15).encode()
        self.assertEqual(struct.unpack_from('<ih', not_coin), (0, 15))

    def test_arena_sp_item_use(self):
        req = messages.UseArenaSpItemReq.decode(struct.pack('<q', 77))
        self.assertEqual(req.item_uid, 77)
        ack = messages.UseArenaSpItemAck(result=0, consumed_items=[], arena_sp=150).encode()
        self.assertEqual(struct.unpack_from('<i', ack[:4])[0], 0)

    def test_arena_back_to_square(self):
        req = messages.ArenaBackToSquareReq.decode(b'')
        self.assertIsInstance(req, messages.ArenaBackToSquareReq)
        ack = messages.ArenaBackToSquareAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', ack), (0,))

    def test_second_password_pin_lifecycle(self):
        ack1 = messages.SecondPassCreateAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', ack1), (0,))
        ack2 = messages.SecondPassModifyAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', ack2), (0,))
        ack3 = messages.SecondPassAuthAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', ack3), (0,))

    def test_remote_inspection_char_info(self):
        req = messages.RequestCharInfoReq.decode(struct.pack('<q', 123))
        self.assertEqual(req.char_uid, 123)
        ack = messages.RequestCharInfoAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', ack[:4])[0], 0)

    def test_remote_inspection_item_info(self):
        req = messages.RequestItemInfoReq.decode(struct.pack('<q', 456))
        self.assertEqual(req.item_uid, 456)
        ack = messages.RequestItemInfoAck(result=0, item_uid=456).encode()
        self.assertEqual(struct.unpack_from('<iq', ack[:12]), (0, 456))

    def test_guild_money_deposit_and_withdrawal(self):
        req_in = messages.GuildMoneyInReq.decode(struct.pack('<q', 5000))
        self.assertEqual(req_in.amount, 5000)
        ack_in = messages.GuildMoneyInAck(result=0, remain_gold=5000).encode()
        self.assertEqual(struct.unpack_from('<iq', ack_in), (0, 5000))

        req_out = messages.GuildMoneyOutReq.decode(struct.pack('<q', 2000))
        self.assertEqual(req_out.amount, 2000)
        ack_out = messages.GuildMoneyOutAck(result=0, remain_gold=3000).encode()
        self.assertEqual(struct.unpack_from('<iq', ack_out), (0, 3000))

    def test_guild_member_grade_modify(self):
        req = messages.GuildPersonGradeModifyReq.decode(struct.pack('<qh', 888, 3))
        self.assertEqual(req.member_uid, 888)
        self.assertEqual(req.new_grade, 3)
        ack = messages.GuildPersonGradeModifyAck(result=0, member_uid=888, new_grade=3).encode()
        self.assertEqual(struct.unpack_from('<iqh', ack), (0, 888, 3))

    def test_guild_level_up(self):
        req = messages.GuildLevelUpReq.decode(b'')
        self.assertIsInstance(req, messages.GuildLevelUpReq)
        ack = messages.GuildLevelUpAck(result=0, new_level=3).encode()
        self.assertEqual(struct.unpack_from('<ih', ack), (0, 3))

    def test_guild_notice_modify(self):
        notice_bytes = 'Guild Notice'.encode('utf-16le') + b'\x00\x00'
        req = messages.GuildNoticeModifyReq.decode(notice_bytes)
        self.assertEqual(req.notice, 'Guild Notice')
        ack = messages.GuildNoticeModifyAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', ack), (0,))

    def test_guild_skill_notification(self):
        not_skill = messages.GuildSkillNot(flag=True).encode()
        self.assertEqual(not_skill, b'\x01\x10\x80')

    def test_divide_item_stack(self):
        req = messages.DivideItemReq.decode(struct.pack('<qqih', 10, 0, 5, 2))
        self.assertEqual(req.source_item_uid, 10)
        self.assertEqual(req.count, 5)
        self.assertEqual(req.slot, 2)
        ack = messages.DivideItemAck(result=0, items=[]).encode()
        self.assertEqual(struct.unpack_from('<i', ack[:4])[0], 0)

    def test_use_learn_skill_item(self):
        req = messages.UseLearnSkillItemReq.decode(struct.pack('<qh', 99, 105))
        self.assertEqual(req.item_uid, 99)
        self.assertEqual(req.skill_id, 105)
        ack = messages.UseLearnSkillItemAck(
            result=0, skill_id=105, skill_level=1, item_code=50, count=1, sp=15
        ).encode()
        self.assertEqual(struct.unpack_from('<ihBii', ack[:15]), (0, 105, 1, 50, 1))

    def test_inventory_live_refresh_notification(self):
        not_inven = messages.InventoryUpdatedNot().encode()
        self.assertEqual(not_inven, b'\x10\x80\x10\x80')

    def test_item_remain_time_and_delete_notifications(self):
        not_time = messages.ItemRemainTimeNot(item_uid=123, remain_seconds=3600).encode()
        self.assertEqual(struct.unpack_from('<qq', not_time), (123, 3600))
        not_del = messages.ItemDeleteNot(item_uid=123).encode()
        self.assertEqual(struct.unpack_from('<q', not_del), (123,))

    def test_depot_save_and_load_currency(self):
        req_save = messages.DepotSaveArReq.decode(struct.pack('<q', 10000))
        self.assertEqual(req_save.gold, 10000)
        ack_save = messages.DepotSaveArAck(result=0, new_gold=10000).encode()
        self.assertEqual(struct.unpack_from('<i', ack_save[:4])[0], 0)

        req_load = messages.DepotLoadArReq.decode(struct.pack('<q', 5000))
        self.assertEqual(req_load.gold, 5000)
        ack_load = messages.DepotLoadArAck(result=0, new_gold=5000).encode()
        self.assertEqual(struct.unpack_from('<i', ack_load[:4])[0], 0)

    def test_mail_arrival_and_return(self):
        not_mail = messages.PostNewArrivalNot().encode()
        self.assertEqual(not_mail, b'')

        req_ret = messages.PostReturnReq.decode(struct.pack('<q', 777))
        self.assertEqual(req_ret.mail_id, 777)
        ack_ret = messages.PostReturnAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', ack_ret[:4])[0], 0)

    def test_combat_ap_gain_notification(self):
        not_ap = messages.InsertApNot(current_ap=50, total_ap=150).encode()
        self.assertEqual(struct.unpack_from('<ii', not_ap), (50, 150))

    def test_dungeon_penalty_notification(self):
        not_pen = messages.ChangeDungeonPenaltyNot(
            in_dungeon=True, is_penalty=True, penalty_level=2, penalty_id=10, duration=60
        ).encode()
        self.assertEqual(struct.unpack_from('<??hii', not_pen), (True, True, 2, 10, 60))

    def test_randombox_rewards_notification(self):
        not_rbox = messages.RandomboxResultItemNot(result=0, item_code=5001, count=3, is_jackpot=True).encode()
        self.assertEqual(struct.unpack_from('<iih?', not_rbox), (0, 5001, 3, True))

    def test_duel_request_and_ack(self):
        req = messages.DuelRequestReq.decode(struct.pack('<q', 12345))
        self.assertEqual(req.target_uid, 12345)
        ack = messages.DuelRequestAck(result=0, target_uid=12345, target_name="Knight", char_class=2, level=30).encode()
        self.assertEqual(struct.unpack_from('<iq', ack[:12]), (0, 12345))
        self.assertIn('Knight'.encode('utf-16le'), ack)

    def test_duel_start_and_notifications(self):
        req = messages.DuelStartReq.decode(struct.pack('<q', 67890))
        self.assertEqual(req.opponent_uid, 67890)
        ack = messages.DuelStartAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', ack[:4]), (0,))
        not_start = messages.DuelStartNot().encode()
        self.assertEqual(len(not_start), 37)  # tag 0x1e + 36 bytes

    def test_duel_result_and_giveup(self):
        req = messages.DuelResultReq.decode(struct.pack('<qq', 101, 202))
        self.assertEqual(req.winner_uid, 101)
        self.assertEqual(req.loser_uid, 202)
        ack = messages.DuelResultAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', ack[:4]), (0,))
        not_giveup = messages.DuelGiveupNot(surrender_char_uid=202).encode()
        self.assertEqual(struct.unpack_from('<q', not_giveup), (202,))

    def test_duel_refuse(self):
        req = messages.DuelRefuseReq.decode(struct.pack('<q', 555))
        self.assertEqual(req.challenger_uid, 555)
        ack = messages.DuelRefuseAck(result=0, target_uid=555, target_name="Rival", char_class=3, level=25).encode()
        self.assertEqual(struct.unpack_from('<iq', ack[:12]), (0, 555))
        self.assertIn('Rival'.encode('utf-16le'), ack)

    def test_arena_square_and_room_lists(self):
        req_sq = messages.ArenaSquareListReq.decode(struct.pack('<i', 1))
        self.assertEqual(req_sq.server_key, 1)
        ack_sq = messages.ArenaSquareListAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', ack_sq[:4]), (0,))

        req_room = messages.ArenaGetRoomListReq.decode(struct.pack('<i', 0))
        self.assertEqual(req_room.page, 0)
        ack_room = messages.ArenaGetRoomListAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', ack_room[:4]), (0,))

        req_inv = messages.ArenaGetInviteListReq.decode(b'')
        self.assertIsInstance(req_inv, messages.ArenaGetInviteListReq)
        ack_inv = messages.ArenaGetInviteListAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', ack_inv[:4]), (0,))

    def test_arena_teams_lifecycle(self):
        # Create team
        encoded_name = 'PvP Champions'.encode('utf-16le')
        name_bytes = jser.varuint(len(encoded_name)) + encoded_name + struct.pack('<h', 1)
        req_create = messages.ArenaTeamCreateReq.decode(name_bytes)
        self.assertEqual(req_create.team_type, 1)
        self.assertEqual(req_create.team_name, 'PvP Champions')
        ack_create = messages.ArenaTeamCreateAck(
            result=0, team_id=77, team_type=1, score=1500, member_count=3,
            team_name='PvP Champions', leader_name='Warlord', notice='Recruiting gladiators'
        ).encode()
        self.assertEqual(struct.unpack_from('<i', ack_create[:4]), (0,))
        self.assertIn('PvP Champions'.encode('utf-16le'), ack_create)

        # Join team
        req_join = messages.ArenaTeamJoinReq.decode(struct.pack('<q', 77))
        self.assertEqual(req_join.team_id, 77)
        ack_join = messages.ArenaTeamJoinAck(result=0, team_id=77).encode()
        self.assertEqual(struct.unpack_from('<i', ack_join[:4]), (0,))

        # Leave team
        req_leave = messages.ArenaTeamLeaveReq.decode(b'')
        self.assertIsInstance(req_leave, messages.ArenaTeamLeaveReq)
        ack_leave = messages.ArenaTeamLeaveAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', ack_leave[:4]), (0,))

    def test_league_season_arena_ranks(self):
        req_rank = messages.LeagueSeasonArenaGetRankReq.decode(struct.pack('<i', 2026))
        self.assertEqual(req_rank.season_id, 2026)
        ack_rank = messages.LeagueSeasonArenaGetRankAck(result=0, season_id=2026).encode()
        self.assertEqual(struct.unpack_from('<i', ack_rank[:4]), (0,))

        req_my_rank = messages.LeagueSeasonArenaGetMyRankReq.decode(struct.pack('<i', 2026))
        self.assertEqual(req_my_rank.season_id, 2026)
        ack_my_rank = messages.LeagueSeasonArenaGetMyRankAck(result=0, my_rank=1).encode()
        self.assertEqual(struct.unpack_from('<i', ack_my_rank[:4]), (0,))






if __name__ == '__main__':
    unittest.main()


class ItemDurabilityTest(unittest.TestCase):
    def test_item_durability_is_positive(self):
        # Item +0x07 f32 follows two empty arrays (2 bytes) and three u16.
        # Durability <= 0 marks gear broken (0x00A49920) and its stats are
        # skipped (0x009D89B0).
        wire = Item(code='Wdag1N', uid=6, owner=1, container=1, slot=5).encode()
        self.assertGreater(struct.unpack_from('<f', wire, 8)[0], 0.0)

    def test_item_durability_override(self):
        wire = Item(code='Wdag1N', uid=6, durability=7.5).encode()
        self.assertEqual(struct.unpack_from('<f', wire, 8)[0], 7.5)


class InventoryMigrationTest(unittest.TestCase):
    def test_bag_moves_off_reserved_container_2(self):
        # 0x008354D0 ignores items whose container is 2.
        from darkblood.player_management.characters import ensure_inventory
        char = {'char_class': 4, 'items': [dict(code='AgloT1N', uid=3, container=2, slot=1)],
                'bags': [{'bag_id': 1}, {'bag_id': 2, 'code': 'Ibaga0004', 'b28': 0, 'b29': 5, 'w2a': 0}]}
        self.assertTrue(ensure_inventory(char))
        self.assertEqual([b['bag_id'] for b in char['bags']], [1, 3])
        self.assertEqual(char['items'][0]['container'], 3)
