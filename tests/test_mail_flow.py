"""End-to-end headless tests for Dark Blood Online Mailbox (Post) system."""
import struct
import unittest

from tests.common import ServerTestCase, create_request, lobby_flow
from darkblood.games.network.messages.mail import (
    PostDeleteReq,
    PostGetAppendItemReq,
    PostListReq,
    PostReadReq,
    PostReturnReq,
    PostSendReq,
)


class MailFlowTest(ServerTestCase):
    def test_mail_lifecycle_flow(self):
        """Test mail sending, inbox listing, reading, claiming attachments, and deleting."""
        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('PostMaster'))
            _, created1 = await client.expect_event(2013)
            char1_id = struct.unpack_from('<Q', created1, 10)[0]

            client.send_event(2012, create_request('MailRecipient'))
            _, created2 = await client.expect_event(2013)
            char2_id = struct.unpack_from('<Q', created2, 10)[0]

            # Select char 1 (PostMaster)
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char1_id))
            await client.expect_event(2007)

            # Give PostMaster some gold and items
            from darkblood.games.session import GameSession
            char1 = GameSession.store().get('OfflinePlayer', char1_id)
            char1['gold'] = 50000
            from darkblood.games.entities.items import Item

            gear = dict(code='Wlsww0001', uid=1001, container=3, slot=0,
                        upgrade=7, quality=3, durability=25.0)
            char1['items'] = [gear]
            GameSession.store().save()

            # 1. Post List (Empty initially)
            client.send_event(2219, PostListReq().encode())
            _, ack2220 = await client.expect_event(2220)
            self.assertEqual(struct.unpack_from('<I', ack2220, 0)[0], 0)

            # 2. Attach an item from PostMaster's inventory
            char1_items = char1.get('items', [])
            self.assertGreater(len(char1_items), 0)
            attached_item_uid = char1_items[0]['uid']
            initial_item_count = len(char1_items)

            # Send mail to MailRecipient with 15,000 gold and 1 attached item
            send_req = PostSendReq(
                recipient='MailRecipient',
                title='Package For You',
                items=[attached_item_uid],
                gold=15000,
            ).encode()
            client.send_event(2221, send_req)
            _, ack2222 = await client.expect_event(2222)
            self.assertEqual(struct.unpack_from('<i', ack2222, 0)[0], 0)

            # Verify sender's gold was deducted
            char1_updated = GameSession.store().get('OfflinePlayer', char1_id)
            self.assertEqual(char1_updated['gold'], 35000)
            self.assertEqual(len(char1_updated['items']), initial_item_count - 1)

            # 3. Check outbox for PostMaster
            client.send_event(2219, PostListReq().encode())
            _, ack2220_out = await client.expect_event(2220)
            self.assertEqual(struct.unpack_from('<I', ack2220_out, 0)[0], 0)

            # Now switch to MailRecipient
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char2_id))
            await client.expect_event(2007)

            # 4. MailRecipient checks inbox: should see 1 unread mail with item & gold
            client.send_event(2219, PostListReq().encode())
            _, ack2220_in = await client.expect_event(2220)
            self.assertEqual(struct.unpack_from('<I', ack2220_in, 0)[0], 0)
            self.assertIn(Item(**gear).encode(), ack2220_in)

            inbox = GameSession.store().get_mail_inbox(char2_id)
            self.assertEqual(len(inbox), 1)
            mail = inbox[0]
            mail_uid = mail['uid']
            self.assertEqual(mail['sender_name'], 'PostMaster')
            self.assertEqual(mail['title'], 'Package For You')
            self.assertEqual(mail['gold'], 15000)
            self.assertEqual(mail['has_item'], 1)
            self.assertEqual(mail['is_read'], 0)

            # 5. Read mail
            client.send_event(2223, PostReadReq(mail_uid=mail_uid).encode())
            _, ack2224 = await client.expect_event(2224)
            self.assertEqual(struct.unpack_from('<iq', ack2224), (0, mail_uid))

            inbox_after_read = GameSession.store().get_mail_inbox(char2_id)
            self.assertEqual(inbox_after_read[0]['is_read'], 1)

            # 6. Claim attached item and gold
            char2_before = GameSession.store().get('OfflinePlayer', char2_id)
            char2_gold_before = char2_before.get('gold', 0)
            char2_items_before = len(char2_before.get('items', []))

            client.send_event(2225, PostGetAppendItemReq(mail_uid=mail_uid).encode())
            _, ack2226 = await client.expect_event(2226)
            self.assertEqual(struct.unpack_from('<iqq', ack2226[:20]), (0, mail_uid, 15000))

            char2_after = GameSession.store().get('OfflinePlayer', char2_id)
            self.assertEqual(char2_after.get('gold', 0), char2_gold_before + 15000)
            self.assertEqual(len(char2_after.get('items', [])), char2_items_before + 1)
            attachment = char2_after['items'][-1]
            self.assertIn(Item(**dict(attachment, owner=char2_id)).encode(), ack2226)

            self.assertNotIn('owner', char2_after['items'][-1])
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char2_id))
            _, selected = await client.expect_event(2007)
            self.assertEqual(struct.unpack_from('<i', selected)[0], 0)

            # 7. Delete mail
            client.send_event(2236, PostDeleteReq(mail_uids=[mail_uid]).encode())
            _, ack2237 = await client.expect_event(2237)
            self.assertEqual(struct.unpack_from('<i', ack2237, 0)[0], 0)

            inbox_after_del = GameSession.store().get_mail_inbox(char2_id)
            self.assertEqual(len(inbox_after_del), 0)

        self.run_async(self.with_server(scenario))

    def test_mail_return_flow(self):
        """Test returning a mail back to sender."""
        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('SenderChar'))
            _, created1 = await client.expect_event(2013)
            char1_id = struct.unpack_from('<Q', created1, 10)[0]

            client.send_event(2012, create_request('ReceiverChar'))
            _, created2 = await client.expect_event(2013)
            char2_id = struct.unpack_from('<Q', created2, 10)[0]

            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char1_id))
            await client.expect_event(2007)

            from darkblood.games.session import GameSession
            mail_uid = GameSession.store().send_mail(
                sender_char_id=char1_id,
                sender_name='SenderChar',
                recipient_char_id=char2_id,
                title='Returnable Mail',
                gold=1000,
            )

            # Receiver selects character
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char2_id))
            await client.expect_event(2007)

            client.send_event(2223, PostReadReq(mail_uid=mail_uid).encode())
            await client.expect_event(2224)

            # Receiver returns the mail
            client.send_event(2234, PostReturnReq(mail_id=mail_uid).encode())
            _, ack2235 = await client.expect_event(2235)
            self.assertEqual(struct.unpack_from('<i', ack2235, 0)[0], 0)

            # Sender now has the mail in their inbox
            sender_inbox = GameSession.store().get_mail_inbox(char1_id)
            self.assertEqual(len(sender_inbox), 1)
            self.assertEqual(sender_inbox[0]['uid'], mail_uid)
            self.assertEqual(sender_inbox[0]['post_type'], 2)  # returned
            self.assertEqual(sender_inbox[0]['sender_name'], 'ReceiverChar')
            self.assertFalse(sender_inbox[0]['is_read'])
            self.assertEqual(sender_inbox[0]['gold'], 1000)

        self.run_async(self.with_server(scenario))

    def test_mail_multi_item_and_error_handling(self):
        """Test mail with multiple items, error cases (unknown recipient, insufficient gold)."""
        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('Tycoon'))
            _, created = await client.expect_event(2013)
            tycoon_id = struct.unpack_from('<Q', created, 10)[0]

            client.send_event(2012, create_request('Peasant'))
            _, created2 = await client.expect_event(2013)
            peasant_id = struct.unpack_from('<Q', created2, 10)[0]

            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, tycoon_id))
            await client.expect_event(2007)

            from darkblood.games.session import GameSession
            tycoon = GameSession.store().get('OfflinePlayer', tycoon_id)
            tycoon['gold'] = 100000
            tycoon['items'] = [
                dict(code='Iwpna0001', uid=2001, container=3, slot=0),
                dict(code='Iwpna0002', uid=2002, container=3, slot=1),
                dict(code='Ibaga0004', uid=2003, container=3, slot=2),
            ]
            GameSession.store().save()

            # Error Case 1: Recipient does not exist -> Result 0xCE
            fail_send = PostSendReq(
                recipient='NonExistentHero',
                title='Ghost Mail',
                gold=5000,
            ).encode()
            client.send_event(2221, fail_send)
            _, ack_fail = await client.expect_event(2222)
            self.assertEqual(struct.unpack_from('<i', ack_fail, 0)[0], 0xCE)

            # Error Case 2: Insufficient Gold -> Result 1
            poor_send = PostSendReq(
                recipient='Peasant',
                title='Too Expensive',
                gold=999999999,
            ).encode()
            client.send_event(2221, poor_send)
            _, ack_poor = await client.expect_event(2222)
            self.assertEqual(struct.unpack_from('<i', ack_poor, 0)[0], 1)

            # Success: Send multiple items (2 items attached) + 20,000 gold
            multi_send = PostSendReq(
                recipient='Peasant',
                title='Care Package',
                items=[2001, 2002],
                gold=20000,
            ).encode()
            client.send_event(2221, multi_send)
            _, ack_multi = await client.expect_event(2222)
            self.assertEqual(struct.unpack_from('<i', ack_multi, 0)[0], 0)

            # Switch to Peasant and verify receiving 2 items
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, peasant_id))
            await client.expect_event(2007)

            inbox = GameSession.store().get_mail_inbox(peasant_id)
            self.assertEqual(len(inbox), 1)
            mail_uid = inbox[0]['uid']

            client.send_event(2225, PostGetAppendItemReq(mail_uid=mail_uid).encode())
            _, ack_claim = await client.expect_event(2226)
            self.assertEqual(struct.unpack_from('<iqq', ack_claim[:20]), (0, mail_uid, 20000))

            peasant_after = GameSession.store().get('OfflinePlayer', peasant_id)
            self.assertEqual(peasant_after['gold'], 20000)
            # Peasant items now have the 2 attached items
            claimed_codes = [i['code'] for i in peasant_after.get('items', [])]
            self.assertIn('Iwpna0001', claimed_codes)
            self.assertIn('Iwpna0002', claimed_codes)

            # Multi-mail deletion test
            mail2 = GameSession.store().send_mail(
                sender_char_id=tycoon_id,
                sender_name='Tycoon',
                recipient_char_id=peasant_id,
                title='Second Letter',
            )
            del_multi = PostDeleteReq(mail_uids=[mail_uid, mail2]).encode()
            client.send_event(2236, del_multi)
            _, ack_del_multi = await client.expect_event(2237)
            self.assertEqual(struct.unpack_from('<i', ack_del_multi, 0)[0], 0)

            self.assertEqual(len(GameSession.store().get_mail_inbox(peasant_id)), 0)

        self.run_async(self.with_server(scenario))

    def test_mail_claim_ar_and_save(self):
        """Test claiming attached AR only (2248 -> 2249) and saving/protecting mail (2252 -> 2253)."""
        from darkblood.games.network.messages.mail import (
            PostGetAppendArAck, PostGetAppendArReq, PostSaveAck, PostSaveReq,
        )

        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('GoldSender'))
            _, c1 = await client.expect_event(2013)
            sender_id = struct.unpack_from('<Q', c1, 10)[0]

            client.send_event(2012, create_request('GoldReceiver'))
            _, c2 = await client.expect_event(2013)
            recv_id = struct.unpack_from('<Q', c2, 10)[0]

            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, recv_id))
            await client.expect_event(2007)

            from darkblood.games.session import GameSession
            mail_uid = GameSession.store().send_mail(
                sender_char_id=sender_id,
                sender_name='GoldSender',
                recipient_char_id=recv_id,
                title='AR Only',
                gold=12345,
            )

            # Claim AR only (2248 -> 2249)
            client.send_event(2248, PostGetAppendArReq(mail_uid=mail_uid).encode())
            _, raw2249 = await client.expect_event(2249)
            ack2249 = PostGetAppendArAck.decode(raw2249)
            self.assertEqual(ack2249.result, 0)
            self.assertEqual(ack2249.mail_uid, mail_uid)
            self.assertEqual(ack2249.current_ar, 12345)

            # Save mail (2252 -> 2253)
            client.send_event(2252, PostSaveReq(mail_uid=mail_uid).encode())
            _, raw2253 = await client.expect_event(2253)
            ack2253 = PostSaveAck.decode(raw2253)
            self.assertEqual(ack2253.result, 0)
            self.assertEqual(ack2253.mail_uid, mail_uid)

            inbox = GameSession.store().get_mail_inbox(recv_id)
            self.assertEqual(inbox[0]['gold'], 0)
            self.assertEqual(inbox[0]['remain_days'], 90)

        self.run_async(self.with_server(scenario))


if __name__ == '__main__':
    unittest.main()
