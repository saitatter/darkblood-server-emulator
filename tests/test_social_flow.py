"""Tests for social handlers: mailbox, friends, invite lists, web notices, and NPC interactions."""
import struct
import unittest

from tests.common import ServerTestCase, chat_request, create_request, lobby_flow
from darkblood.games.network.messages import (
    CharNickChangeReq, FriendListAddReq, FriendListUpdateReq, RequestCharInfoReq, RequestItemInfoReq, UseSpeakerItemReq,
    GuildCreateProposalReq, GuildNameChangeReq, GuildNoticeModifyReq, GuildPersonGradeModifyReq,
    PostDeleteReq, PostGetAppendItemReq, PostListReq, PostReadReq, PostReturnReq, PostSendReq,
)


class SocialFlowTest(ServerTestCase):
    def test_social_messages_and_notices(self):
        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('Socialite'))
            _, created = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', created, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)

            # 1. Post list (2219 -> 2220)
            client.send_event(2219, PostListReq().encode())
            _, ack2220 = await client.expect_event(2220)
            self.assertEqual(struct.unpack_from('<i', ack2220)[0], 0)

            # 2. Friend list (2131 -> 2132)
            client.send_event(2131)
            _, ack2132 = await client.expect_event(2132)
            self.assertEqual(struct.unpack_from('<i', ack2132)[0], 0)

            # 3. Friend block list (2569 -> 2570)
            client.send_event(2569)
            _, ack2570 = await client.expect_event(2570)
            self.assertEqual(struct.unpack_from('<i', ack2570)[0], 0)

            # 4. Invite list (2024 -> 2025)
            client.send_event(2024, b'')
            _, ack2025 = await client.expect_event(2025)
            self.assertEqual(struct.unpack_from('<i', ack2025)[0], 0)
            self.assertEqual(ack2025[4:], b'\x10\x80')

            # 5. Http notice check (2594 -> 2595)
            client.send_event(2594, b'')
            _, ack2595 = await client.expect_event(2595)
            self.assertEqual(struct.unpack_from('<i?', ack2595), (0, False))

            # 6. Play option update (2216: fire and forget)
            client.send_event(2216, struct.pack('<q', char_id) + b'\x1e\x00')

            # 7. NPC first meet (2094 -> 2095)
            client.send_event(2094, struct.pack('<iI', 0x7fffffff, 0xeaec51bd))
            _, ack2095 = await client.expect_event(2095)
            self.assertEqual(struct.unpack_from('<II', ack2095), (0, 0xeaec51bd))

            # 8. Friend list add (2139 -> 2140: returns 0xCE player offline / not found)
            fname = 'Buddy'.encode('utf-16le') + b'\x00\x00'
            client.send_event(2139, FriendListAddReq(char_name='Buddy').encode())
            _, ack2140 = await client.expect_event(2140)
            self.assertEqual(struct.unpack_from('<i', ack2140)[0], 0xCE)

            # 9. Friend list delete (2135 -> 2136)
            client.send_event(2135, struct.pack('<q', 123456))
            _, ack2136 = await client.expect_event(2136)
            self.assertEqual(struct.unpack_from('<iq', ack2136), (0, 123456))

            # 10. Use speaker megaphone (2128 -> 2129)
            client.send_event(2128, UseSpeakerItemReq(speaker_uid=888, message='Party at town!').encode())
            _, ack2129 = await client.expect_event(2129)
            self.assertEqual(struct.unpack_from('<iq', ack2129), (0, 888))

            # 11. Guild create proposal (5121 -> 5122)
            gname = 'Vanguard'.encode('utf-16le') + b'\x00\x00'
            client.send_event(5121, GuildCreateProposalReq(guild_name='Vanguard').encode())
            _, ack5122 = await client.expect_event(5122)
            self.assertEqual(struct.unpack_from('<i', ack5122)[0], 0)

            # 12. Guild create (2150 -> 2151)
            client.send_event(2150, gname)
            _, ack2151 = await client.expect_event(2151)
            self.assertEqual(struct.unpack_from('<iq', ack2151), (0, 1001))

            # 13. Friend list update memo (2133 -> 2134)
            client.send_event(2133, FriendListUpdateReq(char_uid=123456, comment='Best ally').encode())
            _, ack2134 = await client.expect_event(2134)
            self.assertEqual(struct.unpack_from('<iq', ack2134), (0, 123456))

            # 14. Guild invite (2160 -> 2161)
            target = 'FriendHero'.encode('utf-16le') + b'\x00\x00'
            client.send_event(2160, target)
            _, ack2161 = await client.expect_event(2161)
            self.assertEqual(struct.unpack_from('<i', ack2161)[0], 0)

            # 15. Guild leave (2162 -> 2163)
            client.send_event(2162, b'')
            _, ack2163 = await client.expect_event(2163)
            self.assertEqual(struct.unpack_from('<i', ack2163)[0], 0)

            # 16. Guild person join (2155 -> 2156)
            client.send_event(2155, struct.pack('<q', 2002))
            _, ack2156 = await client.expect_event(2156)
            self.assertEqual(struct.unpack_from('<i', ack2156)[0], 0)

            # 17. Guild money deposit (2179 -> 2180): a new character (0 AR) is refused
            # with JERI_NOT_ENOUGH_AR; with AR, the deposit leaves the player's AR in the ack
            # (0x00794250 writes it to player +0x70).
            from darkblood.games.session import GameSession
            char = GameSession.store().get('OfflinePlayer', char_id)
            client.send_event(2179, struct.pack('<q', 500))
            _, ack2180 = await client.expect_event(2180)
            self.assertEqual(ack2180, struct.pack('<i', 168))
            self.assertEqual(char.get('guild_money', 0), 0)
            char['gold'] = 1000
            client.send_event(2179, struct.pack('<q', 500))
            _, ack2180 = await client.expect_event(2180)
            self.assertEqual(struct.unpack_from('<iq', ack2180), (0, 500))
            self.assertEqual(char['guild_money'], 500)

            # 18. Guild money withdraw (2181 -> 2182): moves AR back, capped by the guild bank.
            client.send_event(2181, struct.pack('<q', 200))
            _, ack2182 = await client.expect_event(2182)
            self.assertEqual(struct.unpack_from('<iq', ack2182), (0, 700))
            self.assertEqual(char['guild_money'], 300)

            # 19. Guild level up (2183 -> 2184)
            client.send_event(2183, b'')
            _, ack2184 = await client.expect_event(2184)
            self.assertEqual(struct.unpack_from('<i', ack2184)[0], 0)

            # 20. Guild notice modify (2185 -> 2186)
            gnotice = 'Guild rules apply'.encode('utf-16le') + b'\x00\x00'
            client.send_event(2185, GuildNoticeModifyReq(notice='Guild rules apply').encode())
            _, ack2186 = await client.expect_event(2186)
            self.assertEqual(struct.unpack_from('<i', ack2186)[0], 0)

            # 21. Guild notice delete (2188 -> 2189)
            client.send_event(2188, b'')
            _, ack2189 = await client.expect_event(2189)
            self.assertEqual(struct.unpack_from('<i', ack2189)[0], 0)

            # 22. Guild all skill init (2214 -> 2215)
            client.send_event(2214, b'')
            _, ack2215 = await client.expect_event(2215)
            self.assertEqual(struct.unpack_from('<i', ack2215)[0], 0)

            # 23. Mailbox send (2221 -> 2222)
            client.send_event(2221, PostSendReq().encode())
            _, ack2222 = await client.expect_event(2222)
            self.assertEqual(struct.unpack_from('<i', ack2222)[0], 0)

            # 24. Mailbox read (2223 -> 2224)
            client.send_event(2223, PostReadReq(mail_uid=888).encode())
            _, ack2224 = await client.expect_event(2224)
            self.assertEqual(struct.unpack_from('<iq', ack2224), (0, 888))

            # 25. Mailbox get append item (2225 -> 2226)
            client.send_event(2225, PostGetAppendItemReq(mail_uid=888).encode())
            _, ack2226 = await client.expect_event(2226)
            self.assertEqual(struct.unpack_from('<iq', ack2226[:12]), (0, 888))

            # 26. Mailbox delete (2236 -> 2237)
            client.send_event(2236, PostDeleteReq(mail_uids=[888]).encode())
            _, ack2237 = await client.expect_event(2237)
            self.assertEqual(struct.unpack_from('<i', ack2237)[0], 0)

            # 27. Chat message (5040 -> 5041)
            client.send_event(5040, chat_request('Hello from test'))
            _, ack5041 = await client.expect_event(5041)
            self.assertEqual(struct.unpack_from('<iB', ack5041[:5]), (0, 0))

            # 31. Character nickname change (2310 -> 2311)
            from darkblood.core.serialization.jser import wide_string
            nick_payload = CharNickChangeReq(item_uid=123, new_name='RenamedHero').encode()
            client.send_event(2310, nick_payload)
            _, ack2311 = await client.expect_event(2311)
            self.assertEqual(struct.unpack_from('<i', ack2311)[0], 0)

            # 32. Guild name change (2314 -> 2315)
            gname_payload = GuildNameChangeReq(item_uid=456, new_name='RenamedGuild').encode()
            client.send_event(2314, gname_payload)
            _, ack2315 = await client.expect_event(2315)
            self.assertEqual(struct.unpack_from('<i', ack2315)[0], 0)

            # 33. Keyboard custom key set (2319 -> 2320) + 2007 relog persistence
            from darkblood.games.network.messages.system import KeyboardSetCustomKeyAck, KeyboardSetCustomKeyReq
            custom_keys_str = '0=17;1=31;2=30;3=32;'
            client.send_event(2319, KeyboardSetCustomKeyReq(keys=custom_keys_str).encode())
            _, ack2320 = await client.expect_event(2320)
            decoded2320 = KeyboardSetCustomKeyAck.decode(ack2320)
            self.assertEqual(decoded2320.result, 0)
            self.assertEqual(decoded2320.keys, custom_keys_str)
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            _, ack2007_keys = await client.expect_event(2007)
            self.assertIn(custom_keys_str.encode('utf-16le'), ack2007_keys)

            # 34. Request teaching / mentorship (5351 -> 5352)
            client.send_event(5351, struct.pack('<q', 12345))
            _, ack5352 = await client.expect_event(5352)
            self.assertEqual(struct.unpack_from('<i', ack5352)[0], 0)

            # 35. Accept request teaching (5353 -> 5354)
            client.send_event(5353, struct.pack('<q', 54321))
            _, ack5354 = await client.expect_event(5354)
            self.assertEqual(struct.unpack_from('<i', ack5354)[0], 0)

            # 36. Title change (2335 -> 2336)
            client.send_event(2335, struct.pack('<i', 55))
            _, ack2336 = await client.expect_event(2336)
            self.assertEqual(struct.unpack_from('<ii', ack2336), (0, 55))

            # 37. Achieve get list (2327 -> 2328)
            client.send_event(2327, b'')
            _, ack2328 = await client.expect_event(2328)
            self.assertEqual(struct.unpack_from('<i', ack2328[:4])[0], 0)

            # 38. Arena back to square (5165 -> 5166)
            client.send_event(5165, b'')
            _, ack5166 = await client.expect_event(5166)
            self.assertEqual(struct.unpack_from('<i', ack5166)[0], 0)

            # 39. Second pass create (5256 -> 5257)
            client.send_event(5256, b'\x01\x02\x03\x04')
            _, ack5257 = await client.expect_event(5257)
            self.assertEqual(struct.unpack_from('<i', ack5257)[0], 0)

            # 40. Second pass auth (5260 -> 5261)
            client.send_event(5260, b'\x01\x02\x03\x04')
            _, ack5261 = await client.expect_event(5261)
            self.assertEqual(struct.unpack_from('<i', ack5261)[0], 0)

            # 41. Request char info (6011 -> 6012)
            client.send_event(6011, RequestCharInfoReq(is_other=True, char_uid=char_id).encode())
            _, ack6012 = await client.expect_event(6012)
            self.assertEqual(struct.unpack_from('<i', ack6012[:4])[0], 0)

            # 42. Request item info (6028 -> 6029)
            # An unknown item answers 63 (JERI_INVEN_01) with the result only.
            client.send_event(6028, RequestItemInfoReq(item_info_id=9999, target_char_uid=9999).encode())
            _, ack6029 = await client.expect_event(6029)
            self.assertEqual(ack6029, struct.pack('<i', 63))

            # 43. Guild money in (2179 -> 2180)
            from darkblood.games.session import GameSession
            char = GameSession.store().get('OfflinePlayer', char_id)
            char['gold'] = 20000
            char['guild_money'] = 0
            client.send_event(2179, struct.pack('<q', 15000))
            _, ack2180 = await client.expect_event(2180)
            self.assertEqual(struct.unpack_from('<iq', ack2180), (0, 5000))   # player AR left

            # 44. Guild money out (2181 -> 2182)
            client.send_event(2181, struct.pack('<q', 5000))
            _, ack2182 = await client.expect_event(2182)
            self.assertEqual(struct.unpack_from('<iq', ack2182), (0, 10000))  # player AR after
            self.assertEqual(char['guild_money'], 10000)

            # 45. Guild person grade modify (2164 -> 2165)
            client.send_event(2164, GuildPersonGradeModifyReq(member_uids=[888], new_grade=2).encode())
            _, ack2165 = await client.expect_event(2165)
            self.assertEqual(struct.unpack_from('<iqh', ack2165), (0, 888, 2))

            # 46. Guild level up (2183 -> 2184)
            client.send_event(2183, b'')
            _, ack2184 = await client.expect_event(2184)
            self.assertEqual(struct.unpack_from('<ih', ack2184), (0, 3))

            # 47. Guild notice modify (2185 -> 2186)
            notice_text = 'Welcome allies'.encode('utf-16le') + b'\x00\x00'
            client.send_event(2185, GuildNoticeModifyReq(notice='Welcome allies').encode())
            _, ack2186 = await client.expect_event(2186)
            self.assertEqual(struct.unpack_from('<i', ack2186)[0], 0)

            # 48. Post return after the message is gone (2234 -> 2235).
            from darkblood.games.network import results

            client.send_event(2234, PostReturnReq(mail_id=12345).encode())
            _, ack2235 = await client.expect_event(2235)
            self.assertEqual(ack2235, struct.pack('<i', results.INVALID_STATE))

        self.run_async(self.with_server(scenario))

    def test_extended_social_party_guild_opcodes(self):
        """Test newly recovered Social, Party/Teaching/Guide, and Guild opcodes."""
        from darkblood.games.network.messages.social import (
            BanishUserAck, BanishUserReq, ChatNotifyAck, ChatNotifyReq,
            FriendBlockListAddAck, FriendBlockListAddReq,
            FriendBlockListDeleteAck, FriendBlockListDeleteReq,
            FriendBlockListUpdateAck, FriendBlockListUpdateReq,
            RequestCharInfoByNickReq, WatchEventSeenAck, WatchEventSeenReq,
        )
        from darkblood.games.network.messages.party import (
            GuideDonelistUpdateAck, GuideDonelistUpdateReq,
            GuideWaitlistUpdateAck, GuideWaitlistUpdateReq,
            SummonAcknowledgeAck, SummonAcknowledgeReq,
            TeachingDeleteAck, TeachingDeleteReq,
            TeachingGraduationRewardAck, TeachingGraduationRewardReq,
            TeachingStressRewardAck, TeachingStressRewardReq,
            TeachingSummonAcceptAck, TeachingSummonAcceptReq,
            TeachingSummonRequestAck, TeachingSummonRequestReq,
        )
        from darkblood.games.network.messages.guild import (
            CitadelRoundClearAck, CitadelRoundClearReq,
            GuildBrokerBidAck, GuildBrokerBidReq,
            GuildBrokerListAck, GuildBrokerListReq,
            GuildBrokerReturnPointAck, GuildBrokerReturnPointReq,
            GuildDismissalStartAck, GuildDismissalStartReq,
            GuildDismissalStopAck, GuildDismissalStopReq,
            GuildFalloutStartAck, GuildFalloutStartReq,
            GuildFalloutStopAck, GuildFalloutStopReq,
            GuildGradeDelegationAck, GuildGradeDelegationReq,
            GuildLearnSkillAck, GuildLearnSkillReq,
            GuildPersonArenaGradeModifyAck, GuildPersonArenaGradeModifyReq,
            GuildPersonExpulsionAck, GuildPersonExpulsionReq,
            GuildPersonIntroductionAck, GuildPersonIntroductionReq,
            GuildPersonSiegeTeamIdxModifyAck, GuildPersonSiegeTeamIdxModifyReq,
            GuildSiegeChangeOfficerAck, GuildSiegeChangeOfficerReq,
            GuildSkillChangeUseStateAck, GuildSkillChangeUseStateReq,
            GuildSupplyGetRewardAck, GuildSupplyGetRewardReq,
            GuildViewedNoticeNot, RefuseGuildInviteNot,
        )

        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('GuildHero'))
            _, c1 = await client.expect_event(2013)
            char1_id = struct.unpack_from('<Q', c1, 10)[0]

            client.send_event(2012, create_request('BlockTarget'))
            _, c2 = await client.expect_event(2013)
            char2_id = struct.unpack_from('<Q', c2, 10)[0]

            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char1_id))
            await client.expect_event(2007)

            # --- Social ---
            client.send_event(2354, ChatNotifyReq(char_uid=char1_id, category=1, target_name='BlockTarget', message='spam').encode())
            _, r = await client.expect_event(2355)
            self.assertEqual(ChatNotifyAck.decode(r).result, 0)

            client.send_event(2565, FriendBlockListAddReq(char_name='BlockTarget').encode())
            _, r = await client.expect_event(2566)
            ack = FriendBlockListAddAck.decode(r)
            self.assertEqual(ack.result, 0)
            self.assertEqual(ack.block.uid, char2_id)

            client.send_event(2571, FriendBlockListUpdateReq(char_uid=char2_id, memo='noisy').encode())
            _, r = await client.expect_event(2572)
            ack = FriendBlockListUpdateAck.decode(r)
            self.assertEqual((ack.result, ack.char_uid, ack.memo), (0, char2_id, 'noisy'))

            # 2570 lists the block list as FriendEntry records (mapFriendBlockList).
            from darkblood.games.network.messages import FriendBlockListRequestAck
            client.send_event(2569)
            _, r = await client.expect_event(2570)
            blocked = FriendBlockListRequestAck.decode(r).block_list
            self.assertEqual(list(blocked), [char2_id])
            self.assertEqual((blocked[char2_id].name, blocked[char2_id].memo), ('BlockTarget', 'noisy'))

            client.send_event(2567, FriendBlockListDeleteReq(char_uid=char2_id).encode())
            _, r = await client.expect_event(2568)
            ack = FriendBlockListDeleteAck.decode(r)
            self.assertEqual((ack.result, ack.char_uid), (0, char2_id))

            client.send_event(2693, WatchEventSeenReq().encode())
            _, r = await client.expect_event(2694)
            self.assertEqual(WatchEventSeenAck.decode(r).result, 0)

            client.send_event(5007, BanishUserReq(target_uid=char2_id).encode())
            _, r = await client.expect_event(5008)
            self.assertEqual(BanishUserAck.decode(r).result, 12)  # not in a room: JERI_INVALID_STATE

            client.send_event(6018, RequestCharInfoByNickReq(target_nick='BlockTarget', my_char_uid=char1_id).encode())
            _, r = await client.expect_event(6012)
            self.assertEqual(struct.unpack_from('<i', r)[0], 0)

            # --- Party / Guide / Teaching ---
            client.send_event(2356, GuideWaitlistUpdateReq(guide_ids=[1, 2]).encode())
            _, r = await client.expect_event(2357)
            self.assertEqual(GuideWaitlistUpdateAck.decode(r).result, 0)

            client.send_event(2360, GuideDonelistUpdateReq(guide_ids=[1]).encode())
            _, r = await client.expect_event(2361)
            self.assertEqual(GuideDonelistUpdateAck.decode(r).result, 0)

            client.send_event(2648, TeachingStressRewardReq(reward_idx=1).encode())
            _, r = await client.expect_event(2649)
            self.assertEqual(TeachingStressRewardAck.decode(r).result, 0)

            client.send_event(2658, TeachingGraduationRewardReq(reward_idx=1, mentor_name='GuildHero', student_name='BlockTarget').encode())
            _, r = await client.expect_event(2659)
            self.assertEqual(TeachingGraduationRewardAck.decode(r).result, 0)

            client.send_event(5130, SummonAcknowledgeReq(accept=True).encode())
            _, r = await client.expect_event(5131)
            self.assertEqual(SummonAcknowledgeAck.decode(r).result, 0)

            client.send_event(5356, TeachingSummonAcceptReq(accept=True).encode())
            _, r = await client.expect_event(5357)
            ack = TeachingSummonAcceptAck.decode(r)
            self.assertEqual((ack.result, ack.answer, ack.nick), (0, True, 'GuildHero'))

            client.send_event(6030, TeachingDeleteReq(target_uid=char2_id).encode())
            _, r = await client.expect_event(6031)
            ack = TeachingDeleteAck.decode(r)
            self.assertEqual((ack.result, ack.nick), (0, 'BlockTarget'))

            client.send_event(6032, TeachingSummonRequestReq(target_nick='BlockTarget', pos_x=1.0, pos_y=2.0).encode())
            _, r = await client.expect_event(6033)
            self.assertEqual(TeachingSummonRequestAck.decode(r).result, 0xCE)  # target offline

            # --- Guild ---
            client.send_event(2166, GuildFalloutStartReq().encode())
            _, r = await client.expect_event(2167)
            self.assertEqual(GuildFalloutStartAck.decode(r).result, 0)

            client.send_event(2168, GuildFalloutStopReq().encode())
            _, r = await client.expect_event(2169)
            self.assertEqual(GuildFalloutStopAck.decode(r).result, 0)

            client.send_event(2173, GuildGradeDelegationReq(target_uid=char2_id).encode())
            _, r = await client.expect_event(2174)
            self.assertEqual(GuildGradeDelegationAck.decode(r).result, 0)

            client.send_event(2175, GuildPersonExpulsionReq(member_uids=[char2_id]).encode())
            _, r = await client.expect_event(2176)
            self.assertEqual(GuildPersonExpulsionAck.decode(r).result, 0)

            client.send_event(2187, GuildViewedNoticeNot(notice_time=123456).encode())
            client.send_event(2218, RefuseGuildInviteNot(inviter_name='BlockTarget').encode())

            client.send_event(2190, GuildDismissalStartReq().encode())
            _, r = await client.expect_event(2191)
            self.assertEqual(GuildDismissalStartAck.decode(r).result, 0)

            client.send_event(2192, GuildDismissalStopReq().encode())
            _, r = await client.expect_event(2193)
            self.assertEqual(GuildDismissalStopAck.decode(r).result, 0)

            client.send_event(2206, GuildLearnSkillReq(skill_id=10, skill_level=1).encode())
            _, r = await client.expect_event(2207)
            self.assertEqual(GuildLearnSkillAck.decode(r).result, 0)
            await client.expect_event(2205)

            client.send_event(2208, GuildSkillChangeUseStateReq(skill_id=10).encode())
            _, r = await client.expect_event(2209)
            self.assertEqual(GuildSkillChangeUseStateAck.decode(r).result, 0)
            await client.expect_event(5127)

            client.send_event(2674, GuildPersonIntroductionReq(greeting='Hi!', memo='Tank').encode())
            _, r = await client.expect_event(2675)
            ack = GuildPersonIntroductionAck.decode(r)
            self.assertEqual((ack.result, ack.greeting, ack.memo), (0, 'Hi!', 'Tank'))

            client.send_event(2678, GuildBrokerListReq().encode())
            _, r = await client.expect_event(2679)
            self.assertEqual(GuildBrokerListAck.decode(r).result, 0)

            client.send_event(2680, GuildBrokerBidReq(broker_id=5, bid_point=100).encode())
            _, r = await client.expect_event(2681)
            ack = GuildBrokerBidAck.decode(r)
            self.assertEqual((ack.result, ack.broker_id, ack.bid_point), (0, 5, 100))

            client.send_event(2682, GuildBrokerReturnPointReq(broker_id=5).encode())
            _, r = await client.expect_event(2683)
            self.assertEqual(GuildBrokerReturnPointAck.decode(r).result, 0)

            client.send_event(2684, GuildSupplyGetRewardReq(supply_reward_uid=77).encode())
            _, r = await client.expect_event(2685)
            self.assertEqual(struct.unpack_from('<iq', r), (0, 77))

            client.send_event(2426, GuildPersonArenaGradeModifyReq(char_uids=[char2_id], arena_permission=1).encode())
            _, r = await client.expect_event(2427)
            self.assertEqual(GuildPersonArenaGradeModifyAck.decode(r).arena_permission, 1)

            client.send_event(2450, GuildSiegeChangeOfficerReq(change_char_uid=char2_id).encode())
            _, r = await client.expect_event(2451)
            self.assertEqual(GuildSiegeChangeOfficerAck.decode(r).change_char_uid, char2_id)

            client.send_event(2453, GuildPersonSiegeTeamIdxModifyReq(team_changes={char2_id: 2}).encode())
            _, r = await client.expect_event(2454)
            ack = GuildPersonSiegeTeamIdxModifyAck.decode(r)
            self.assertEqual(ack.result, 0)
            self.assertIn(2, ack.team_char_list)

            client.send_event(2599, CitadelRoundClearReq(cur_round=3).encode())
            _, r = await client.expect_event(2600)
            ack = CitadelRoundClearAck.decode(r)
            self.assertEqual((ack.result, ack.next_round), (0, 4))

        self.run_async(self.with_server(scenario))


if __name__ == '__main__':
    unittest.main()
