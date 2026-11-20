"""Unit tests for wire message encoding and decoding."""
import struct
import unittest

from tests.common import ROOT
from darkblood.core import hashing
from darkblood.core.serialization import jser
from darkblood.games.entities.character import Character, layer_net_id
from darkblood.games.entities.items import Item
from darkblood.games.handlers.commerce import store_record
from darkblood.games.handlers.skills import learned_skill_map
from darkblood.games.network import messages


class WireMessagesTest(unittest.TestCase):
    def test_delete_character_messages(self):
        raw_req = bytes.fromhex('ffffff7f') + struct.pack('<q', 123456789)
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

    def test_learn_skill_list_messages(self):
        # Captured wire packet from client: ffffff7f 10 83 0f 050001 0f fb0001 0f 230001
        raw_req = bytes.fromhex('ffffff7f10830f0500010ffb00010f230001')
        req = messages.LearnSkillListReq.decode(raw_req)
        self.assertEqual([(s.skill_index, s.level) for s in req.skills], [(5, 1), (251, 1), (35, 1)])

        # Test ack encoding
        ack = messages.LearnSkillListAck(result=0, skills=learned_skill_map({5: 1, 251: 1, 35: 1}),
                                        remain_sp=100, remain_gold=10000)
        encoded = ack.encode()
        self.assertEqual(encoded[:4], b'\x00\x00\x00\x00')
        self.assertEqual(encoded[4], 0x17)  # map tag
        # Remaining SP (int32) and Gold (int64) at the end
        sp, gold = struct.unpack_from('<iq', encoded[-12:])
        self.assertEqual((sp, gold), (100, 10000))

    def test_http_notice_messages(self):
        ack = messages.HttpNoticeCheckAck(result=0, watch=False)
        self.assertEqual(struct.unpack_from('<i?', ack.encode()), (0, False))

    def test_get_invite_list_messages(self):
        ack = messages.GetInviteListAck(result=0)
        encoded = ack.encode()
        self.assertEqual(struct.unpack_from('<i', encoded)[0], 0)
        self.assertEqual(encoded[4:], b'\x10\x80')

    def test_level_up_and_change_exp_not_messages(self):
        lvl = messages.LevelUpNot(ap_slots=[10, 10], char_uid=777, new_level=10, exp=25, total_ap=27, flag=True)
        enc_lvl = lvl.encode()
        # No tag bytes: 0x1E / array tag are not on the wire (0x00B35010).
        self.assertEqual(enc_lvl[0:1], bytes.fromhex('82'))
        self.assertEqual(struct.unpack_from('<IIqBII?', enc_lvl, 1), (10, 10, 777, 10, 25, 27, True))

        exp = messages.ChangeExpNot(exp_total=25000, gain_0=50, gain_1=100)
        enc_exp = exp.encode()
        self.assertEqual(struct.unpack_from('<i', enc_exp, 0)[0], 25000)
        # 8 x i32 then an empty J-wstring (0x00A49E20 ends with 0x00B35AB0).
        self.assertEqual(len(enc_exp), 4 + 32 + 1)
        self.assertEqual(struct.unpack_from('<8i', enc_exp, 4)[:2], (50, 100))
        self.assertEqual(enc_exp[-1:], b'\x80')

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

        drop = messages.ItemDropEntry(drop_uid=1, item_id=hashing.jhash('Ihppa0024'), count=1)
        enc_entry = drop.encode()
        # u32 uid, u32 code, u16 0, u16 count, tag 0x13 + empty set, u16 0xFFFF (no 0x1E byte).
        self.assertEqual(len(enc_entry), 16)
        self.assertEqual(struct.unpack_from('<IIHH', enc_entry), (1, hashing.jhash('Ihppa0024') & 0xFFFFFFFF, 0, 1))
        self.assertEqual(enc_entry[12:], bytes.fromhex('1380ffff'))
        not_5064 = messages.DropItemNot(source_id=42, drops=[drop])
        self.assertEqual(not_5064.encode()[:6], struct.pack('<I', 42) + bytes.fromhex('1081'))

        # FinishGameReq and FinishGameAck (5017 / 5018)
        req_5017 = messages.FinishGameReq.decode(b'\x01\x17\x81\x0f')
        self.assertTrue(req_5017.is_clear)

        reward = messages.SingleReward(total=300, exp=300)
        ack_5018 = messages.FinishGameAck(result=0, is_clear=True, map_code='Act1_G1_A10', char_uid=123,
                                          reward=reward).encode()
        self.assertEqual(struct.unpack_from('<I?', ack_5018[:5]), (0, True))
        self.assertTrue(ack_5018.endswith(b'\x10\x80'))
        # mapSingleReward: one 0x0F entry, i64 uid, then the untagged 40-byte block.
        entry = ack_5018.index(b'\x17\x81\x0f') + 3
        self.assertEqual(struct.unpack_from('<q', ack_5018, entry)[0], 123)
        stats = struct.unpack_from('<10i', ack_5018, entry + 8)
        self.assertEqual(stats, (0, 300, 100, 100, 300, 0, 0, 0, 0, 0))
        # +0x20 is the extra-box count the result screen loops over (0x0071FF0F).
        self.assertEqual(len(reward.encode()), 40)

        # SelectDungeonAck (5044): history (map id, ucDiff, cleared) and active quest ids
        dun_hist = {'Act1_G1_A1': ('Act1_G1_A10', 0, 1)}
        quest = hashing.jhash('Q0002S01')
        ack_5044 = messages.SelectDungeonAck(gate_id='Act1_G1', dun_history=dun_hist,
                                             quest_ids=[quest]).encode()
        self.assertIn(b'\x17\x81\x0f' + jser.wide_string("Act1_G1_A1") + jser.wide_string("Act1_G1_A10") + b'\x00\x01',
                      ack_5044)
        self.assertEqual(struct.unpack_from('<I', ack_5044[:4])[0], 0)
        self.assertEqual(ack_5044[4], 0x17)  # tag 0x17 map
        self.assertIn('Act1_G1'.encode('utf-16le'), ack_5044)
        self.assertTrue(ack_5044.endswith(b'\x13\x81' + struct.pack('<I', quest)))
        empty_5044 = messages.SelectDungeonAck(gate_id='Act1_G1').encode()
        self.assertTrue(empty_5044.endswith(b'\x13\x80'))

        # ChoiceRewardPartyRankAck (5091)
        reward_item = Item(code='Ihppa0001', uid=1, owner=1, container=1, slot=0, count=1)
        ack_5091 = messages.ChoiceRewardPartyRankAck(result=0, char_uid=999,
                                                    item_id=hashing.jhash('Ihppa0001'), count=1,
                                                    box_type=0, box_cost=0,
                                                    items=[reward_item], gold=12345).encode()
        self.assertEqual(struct.unpack_from('<iq', ack_5091[:12]), (0, 999))
        # 0x00713AB0 reads the item code at +0 and the count at +6.
        self.assertEqual(struct.unpack_from('<IHHI', ack_5091, 12), (hashing.jhash('Ihppa0001') & 0xFFFFFFFF, 0, 1, 0))
        self.assertEqual(struct.unpack_from('<ii', ack_5091, 24), (0, 0))
        self.assertEqual(ack_5091[32:34], b'\x10\x81')  # tag 0x10 + 1 item
        self.assertEqual(struct.unpack_from('<q', ack_5091, len(ack_5091) - 8)[0], 12345)

    def test_item_encoding_includes_count_at_offset_zero(self):
        item = Item(code='AbodT1N', uid=123, owner=1, container=1, slot=0, count=5)
        enc = item.encode()
        # count is at u16 +0 in the inner base structure (after two empty varuints: 2 bytes)
        self.assertEqual(struct.unpack_from('<H', enc, 2)[0], 5)

    def test_store_info_ack(self):
        ack = messages.StoreInfoAck(npc_id=1, records=[store_record('Ihppa0001', -1)]).encode()
        self.assertEqual(ack[8:10], b'\x10\x81')
        self.assertEqual(struct.unpack_from('<I', ack, 10)[0], hashing.jhash('Ihppa0001'))
        # +0x18 stock (0 = "Not enough products", 0x0059A5DC), +0x1A -1.
        self.assertEqual(struct.unpack_from('<hh', ack, 10 + 0x18), (-1, -1))
        record = store_record('Ihppa0001', 3, price=150).encode()
        self.assertEqual(struct.unpack_from('<IIIi', record), (hashing.jhash('Ihppa0001'), 150, 0, 0))
        self.assertEqual(struct.unpack_from('<h', record, 0x18)[0], 3)

    def test_change_bag_property_messages(self):
        raw_req = struct.pack('<qB', 2, 3)
        req = messages.ChangeBagPropertyReq.decode(raw_req)
        self.assertEqual((req.bag_uid, req.property), (2, 3))

        ack = messages.ChangeBagPropertyAck(result=0, bag_uid=2, property=3)
        self.assertEqual(struct.unpack_from('<iqB', ack.encode()), (0, 2, 3))

    def test_skill_speech_messages(self):
        req_mod = messages.ModifySkillSpeechReq.decode(struct.pack('<H', 105) + jser.wide_string('Fire!'))
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
        self.assertEqual(struct.unpack_from('<i', enc_buy)[0], 0)

        # Live shape: prefix + npc id + item uid + u16 count.
        raw_sell = bytes.fromhex('ffffff7f') + struct.pack('<iqH', 1, 7777777, 1)
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
        # Live shape: prefix + J-wstring name.
        req_add = messages.FriendListAddReq.decode(bytes.fromhex('ffffff7f') + jser.wide_string('BestFriend'))
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
        raw_spk = struct.pack('<q', 555) + jser.wide_string('Hello World') + struct.pack('<q', 0)
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
        req = messages.FriendListUpdateReq.decode(struct.pack('<q', 999) + jser.wide_string('My friend'))
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
        # Client requests start with the 0x7FFFFFFF header word (live: 2219 = ffffff7f 00).
        self.assertEqual(messages.PostListReq().encode(), bytes.fromhex('ffffff7f00'))
        self.assertEqual(messages.PostListReq.decode(bytes.fromhex('ffffff7f00')).flag, False)

        send = messages.PostSendReq(recipient='Bob', title='Hi', items=[7, 8], gold=50, extra=5, is_cod=True)
        self.assertEqual(messages.PostSendReq.decode(send.encode()), send)
        with self.assertRaises(jser.WireError):
            messages.PostSendReq.decode(b'')
        ack_send = messages.PostSendAck(result=0, items=[]).encode()
        self.assertEqual(ack_send[:5], b'\x00\x00\x00\x00\x10')
        self.assertEqual(messages.PostSendAck(result=0xCE).encode(), struct.pack('<i', 0xCE))

        raw_read = bytes.fromhex('ffffff7f') + struct.pack('<q', 12345)
        self.assertEqual(messages.PostReadReq.decode(raw_read).mail_uid, 12345)
        ack_read = messages.PostReadAck(result=0, mail_uid=12345).encode()
        self.assertEqual(struct.unpack_from('<iq', ack_read), (0, 12345))

        # 2225 carries an item record after the uid (0x00A4FAA0); it is kept raw.
        raw_item = bytes.fromhex('ffffff7f') + struct.pack('<q', 54321) + b'\x01\x02'
        req_item = messages.PostGetAppendItemReq.decode(raw_item)
        self.assertEqual((req_item.mail_uid, req_item.item_record), (54321, b'\x01\x02'))
        self.assertEqual(req_item.encode(), raw_item)
        ack_item = messages.PostGetAppendItemAck(result=0, mail_uid=54321, gold=500, items=[]).encode()
        self.assertEqual(struct.unpack_from('<iqq', ack_item[:20]), (0, 54321, 500))

        del_payload = bytes.fromhex('ffffff7f') + b'\x10' + jser.varuint(2) + struct.pack('<qq', 101, 102)
        req_del = messages.PostDeleteReq.decode(del_payload)
        self.assertEqual(req_del.mail_uids, [101, 102])
        self.assertEqual(req_del.encode(), del_payload)
        ack_del = messages.PostDeleteAck(result=0, mail_uids=[101, 102])
        self.assertEqual(ack_del.encode()[:5], b'\x00\x00\x00\x00\x10')
        self.assertEqual(messages.PostDeleteAck.decode(ack_del.encode()), ack_del)

    def test_mail_list_has_no_struct_tag(self):
        # 0x00B35010 consumes no byte for tag 0x1E: the entry starts with its uid.
        entry = messages.PostEntry(uid=0x1122334455667788, title='T')
        ack = messages.PostListAck(inbox={entry.uid: entry}).encode()
        self.assertEqual(ack[:7], b'\x00\x00\x00\x00\x17\x81\x0f')
        self.assertEqual(struct.unpack_from('<qq', ack, 7), (entry.uid, entry.uid))
        self.assertEqual(messages.PostListAck.OPCODE, 2220)

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

        req_iti = messages.InsertTradeItemReq.decode(struct.pack('<qH', 9999, 1))
        self.assertEqual((req_iti.item_uid, req_iti.slot), (9999, 1))
        ack_iti = messages.InsertTradeItemAck(result=0, items=[]).encode()
        self.assertEqual(ack_iti[:5], b'\x00\x00\x00\x00\x10')

        req_dti = messages.DeleteTradeItemReq.decode(struct.pack('<qq', 9999, 0))
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
        req_pi = messages.PartyInviteReq.decode(struct.pack('<q?q', 5555, False, 0))
        self.assertEqual(req_pi.target_uid, 5555)
        ack_pi = messages.PartyInviteAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', ack_pi), (0,))

        req_pa = messages.PartyAcceptInviteReq.decode(struct.pack('<qq', 1, 4444))
        self.assertEqual(req_pa.host_uid, 4444)
        ack_pa = messages.PartyAcceptInviteAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', ack_pa), (0,))

        req_ct = messages.ChangeTeamReq.decode(struct.pack('<i', 2))
        self.assertEqual(req_ct.team_id, 2)
        ack_ct = messages.ChangeTeamAck(result=0, team_id=2).encode()
        self.assertEqual(struct.unpack_from('<ii', ack_ct), (0, 2))

    def test_chat_messages(self):
        # Captured form: u8 channel, sender, target, message, undecoded tail.
        raw = bytes.fromhex('0180808a2f0062006100670073000010801080010000') + b'\xff' * 28
        req_chat = messages.ChatReq.decode(raw)
        self.assertEqual((req_chat.channel, req_chat.message), (1, '/bags'))
        self.assertEqual(req_chat.encode(), raw)
        ack_chat = messages.ChatAck(result=0, channel=0, sender='Tester', message='Hello world').encode()
        self.assertEqual(struct.unpack_from('<iB', ack_chat[:5]), (0, 0))

    def test_select_char_ack_carries_learned_skills(self):
        # 2007 map 0x4B1240 shares the 2698 element reader 0x4ACB80.
        skills = learned_skill_map({'5': 2, '35': 1}, {'5': 'Hi'}, [35])
        smap = messages.LearnSkillListAck(skills=skills).encode()[4:-12]
        self.assertEqual(smap[:2], b'\x17\x82')
        self.assertEqual(smap[2:8], b'\x0f' + struct.pack('<HHB', 5, 5, 2))
        self.assertEqual(smap[8:15], jser.wide_string('Hi') + b'\x00\x00')
        self.assertEqual(smap[-2:], b'\x01\x00')  # skill 35 locked
        ack = messages.SelectCharacterAck(skills=skills).encode()
        self.assertIn(smap, ack)
        empty = messages.SelectCharacterAck().encode()
        self.assertEqual(len(ack) - len(empty), len(smap) - 2)

    def test_lobby_entry_town_is_join_layer(self):
        # Character select resolves the high dword of +0x37 as the town
        # (0x00704278); 0 shows "default town".
        from darkblood.games.entities.character import Character
        char = Character(name='T')
        out = char.encode_lobby_entry()
        name_end = 1 + 5 + 10 + 1 + len('T'.encode('utf-16le'))
        town = struct.unpack_from('<Q', out, name_end + 12)[0]
        self.assertEqual(town >> 32, hashing.jhash('Act1'))
        self.assertEqual(town, layer_net_id())

    def test_quest_giveup_fail_messages(self):
        req_gu = messages.QuestGiveupReq.decode(
            bytes.fromhex('aa') + '2015-02-23 15:42:11, '.encode('utf-16le') + struct.pack('<I', 0x12345678))
        self.assertEqual(req_gu.quest_id, 0x12345678)
        ack_gu = messages.QuestGiveupAck(result=0, quest_ids=[0x12345678]).encode()
        self.assertEqual(struct.unpack_from('<i', ack_gu[:4])[0], 0)
        self.assertEqual(ack_gu[4:6], b'\x10\x81')
        self.assertEqual(struct.unpack_from('<I', ack_gu, 6)[0], 0x12345678)

        req_fl = messages.QuestFailReq.decode(bytes.fromhex('82') + 'x'.encode('utf-16le') + struct.pack('<I', 0x87654321))
        self.assertEqual(req_fl.quest_id, 0x87654321)
        ack_fl = messages.QuestFailAck(result=0, quest_ids=[0x87654321]).encode()
        self.assertEqual(struct.unpack_from('<i', ack_fl[:4])[0], 0)
        self.assertEqual(ack_fl[4:6], b'\x10\x81')
        self.assertEqual(struct.unpack_from('<I', ack_fl, 6)[0], 0x87654321)

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
        req_p = messages.PickUpItemReq.decode(struct.pack('<iI', 0x7fffffff, 999))  # live form
        self.assertEqual(req_p.drop_uid, 999)
        ack_p = messages.PickUpItemAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', ack_p)[0], 0)

        ack_res = messages.PickUpItemResultAck(result=0, picker_uid=123).encode()
        self.assertEqual(struct.unpack_from('<iq', ack_res[:12]), (0, 123))

        not_ar = messages.GetDropArNot(result=0, gold=500, drop_id=1, picker_uid=123).encode()
        self.assertEqual(struct.unpack_from('<iiiq', not_ar), (0, 500, 1, 123))

    def test_friend_presence_and_char_info_messages(self):
        not_conn = messages.FriendMyConnectionNot(char_uid=777, is_online=True).encode()
        self.assertEqual(struct.unpack_from('<q?', not_conn[:9]), (777, True))

        not_disc = messages.FriendMyDisconnectionNot(char_uid=777, notify=True).encode()
        self.assertEqual(struct.unpack_from('<q?', not_disc), (777, True))

        char = Character(name='Spawned')
        not_info = messages.UpdateCharInfoNot(character=char, guild_name='Guild').encode()
        self.assertEqual(not_info, char.encode_world_details() + jser.wide_string('Guild'))

    def test_character_nick_change_encoding(self):
        req = messages.CharNickChangeReq.decode(struct.pack('<q', 123) + jser.wide_string('NewHero'))
        self.assertEqual(req.new_name, 'NewHero')
        self.assertEqual(req.item_uid, 123)
        ack = messages.CharNickChangeAck(result=0, items=[], new_name='NewHero').encode()
        self.assertEqual(struct.unpack_from('<i', ack)[0], 0)
        self.assertIn(b'N\x00e\x00w\x00H\x00e\x00r\x00o\x00', ack)

    def test_guild_name_change_encoding(self):
        req = messages.GuildNameChangeReq.decode(struct.pack('<q', 456) + jser.wide_string('NewGuild'))
        self.assertEqual(req.new_name, 'NewGuild')
        self.assertEqual(req.item_uid, 456)
        ack = messages.GuildNameChangeAck(result=0, items=[], new_name='NewGuild').encode()
        self.assertEqual(struct.unpack_from('<i', ack)[0], 0)
        self.assertIn(b'N\x00e\x00w\x00G\x00u\x00i\x00l\x00d\x00', ack)

    def test_keyboard_custom_key_mapping(self):
        payload = b'\x01\x02\x03\x04'
        req = messages.KeyboardSetCustomKeyReq.decode(payload)
        self.assertEqual(req.keys_blob, payload)
        ack = messages.KeyboardSetCustomKeyAck(result=0, keys=payload.decode('utf-16le')).encode()
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
        self.assertEqual(len(not_info), 32)

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
        self.assertEqual(ack[4:6], b'\x17\x80')

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
        req = messages.RequestCharInfoReq.decode(struct.pack('<?qq', False, 123, 0))
        self.assertEqual(req.char_uid, 123)
        ack = messages.RequestCharInfoAck(result=0).encode()
        self.assertEqual(struct.unpack_from('<i', ack[:4])[0], 0)

    def test_remote_inspection_item_info(self):
        req = messages.RequestItemInfoReq.decode(struct.pack('<iqq', 0, 456, 0))
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
        req = messages.GuildPersonGradeModifyReq.decode(b'\x10' + jser.varuint(1) + struct.pack('<qh', 888, 3))
        self.assertEqual(req.member_uids, [888])
        self.assertEqual(req.new_grade, 3)
        ack = messages.GuildPersonGradeModifyAck(result=0, member_uid=888, new_grade=3).encode()
        self.assertEqual(struct.unpack_from('<iqh', ack), (0, 888, 3))

    def test_guild_level_up(self):
        req = messages.GuildLevelUpReq.decode(b'')
        self.assertIsInstance(req, messages.GuildLevelUpReq)
        ack = messages.GuildLevelUpAck(result=0, new_level=3).encode()
        self.assertEqual(struct.unpack_from('<ih', ack), (0, 3))

    def test_guild_notice_modify(self):
        req = messages.GuildNoticeModifyReq.decode(jser.wide_string('Guild Notice'))
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
        req = messages.UseLearnSkillItemReq.decode(struct.pack('<qi', 99, 105))
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
        req_save = messages.DepotSaveArReq.decode(struct.pack('<qq', 10000, 0))
        self.assertEqual(req_save.gold, 10000)
        ack_save = messages.DepotSaveArAck(result=0, new_gold=10000).encode()
        self.assertEqual(struct.unpack_from('<i', ack_save[:4])[0], 0)

        req_load = messages.DepotLoadArReq.decode(struct.pack('<qq', 5000, 0))
        self.assertEqual(req_load.gold, 5000)
        ack_load = messages.DepotLoadArAck(result=0, new_gold=5000).encode()
        self.assertEqual(struct.unpack_from('<i', ack_load[:4])[0], 0)

    def test_depot_slot_extend_messages(self):
        req = messages.DepotSlotExtendReq.decode(struct.pack('<qh', 987654321, 5))
        self.assertEqual(req.item_uid, 987654321)
        self.assertEqual(req.slot_index, 5)

        ack = messages.DepotSlotExtendAck(result=0, slot_index=5, expire_time=1700000000).encode()
        res, sidx, exp = struct.unpack_from('<ihq', ack, 0)
        self.assertEqual((res, sidx, exp), (0, 5, 1700000000))
        self.assertEqual(ack[14:16], b'\x10\x80')

    def test_mail_arrival_and_return(self):
        not_mail = messages.PostNewArrivalNot().encode()
        self.assertEqual(not_mail, b'')

        req_ret = messages.PostReturnReq.decode(bytes.fromhex('ffffff7f') + struct.pack('<q', 777))
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
        self.assertEqual(len(not_start), 36)

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

    def test_arena_room_management_messages(self):
        room = messages.ArenaRoomInfo(
            room_id=42, room_name="Deathmatch Colosseum", map_id=3,
            game_mode=2, max_players=6, host_uid=1001, team_id=2001,
            password="secret_pass", notice="High level gladiators"
        )
        encoded_room = room.encode()
        decoded_room, _ = messages.ArenaRoomInfo.decode(encoded_room)
        self.assertEqual(decoded_room.room_id, 42)
        self.assertEqual(decoded_room.room_name, "Deathmatch Colosseum")
        self.assertEqual(decoded_room.map_id, 3)
        self.assertEqual(decoded_room.game_mode, 2)
        self.assertEqual(decoded_room.host_uid, 1001)

        # Create room req/ack
        create_req = messages.ArenaCreateRoomReq(room=room)
        dec_create_req = messages.ArenaCreateRoomReq.decode(create_req.encode())
        self.assertEqual(dec_create_req.room.room_id, 42)

        create_ack = messages.ArenaCreateRoomAck(result=0, room=room)
        dec_create_ack = messages.ArenaCreateRoomAck.decode(create_ack.encode())
        self.assertEqual(dec_create_ack.result, 0)
        self.assertEqual(dec_create_ack.room.room_id, 42)

        # Join room req/ack
        join_req = messages.ArenaJoinRoomReq(room_id=42, password="secret_pass")
        dec_join_req = messages.ArenaJoinRoomReq.decode(join_req.encode())
        self.assertEqual(dec_join_req.room_id, 42)
        self.assertEqual(dec_join_req.password, "secret_pass")

        join_ack = messages.ArenaJoinRoomAck(result=0, room=room, host_uid=1001)
        dec_join_ack = messages.ArenaJoinRoomAck.decode(join_ack.encode())
        self.assertEqual(dec_join_ack.result, 0)
        self.assertEqual(dec_join_ack.host_uid, 1001)

        # Leave room req/ack
        leave_req = messages.ArenaLeaveRoomReq()
        self.assertEqual(leave_req.encode(), b'')
        leave_ack = messages.ArenaLeaveRoomAck(result=0)
        dec_leave_ack = messages.ArenaLeaveRoomAck.decode(leave_ack.encode())
        self.assertEqual(dec_leave_ack.result, 0)

    def test_league_season_arena_ranks(self):
        req_rank = messages.LeagueSeasonArenaGetRankReq.decode(struct.pack('<i', 2026))
        self.assertEqual(req_rank.season_id, 2026)

        entry1 = messages.LeagueRankEntry(rank=1, char_uid=101, char_name="GladiatorOne", score=2400)
        entry2 = messages.LeagueRankEntry(rank=2, char_uid=102, char_name="GladiatorTwo", score=2300)
        ack_rank = messages.LeagueSeasonArenaGetRankAck(result=0, season_id=2026, ranks=[entry1, entry2]).encode()
        self.assertEqual(struct.unpack_from('<i', ack_rank[:4]), (0,))

        dec_rank = messages.LeagueSeasonArenaGetRankAck.decode(ack_rank)
        self.assertEqual(dec_rank.result, 0)
        self.assertEqual(dec_rank.season_id, 2026)
        self.assertEqual(len(dec_rank.ranks), 2)
        self.assertEqual(dec_rank.ranks[0].char_name, "GladiatorOne")
        self.assertEqual(dec_rank.ranks[1].char_name, "GladiatorTwo")

        req_my_rank = messages.LeagueSeasonArenaGetMyRankReq.decode(struct.pack('<i', 2026))
        self.assertEqual(req_my_rank.season_id, 2026)
        ack_my_rank = messages.LeagueSeasonArenaGetMyRankAck(result=0, my_rank=1).encode()
        self.assertEqual(struct.unpack_from('<i', ack_my_rank[:4]), (0,))
        dec_my_rank = messages.LeagueSeasonArenaGetMyRankAck.decode(ack_my_rank)
        self.assertEqual(dec_my_rank.my_rank, 1)






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
