"""Mailbox (Post) system handlers for Dark Blood Online.

Opcodes handled:
- 2219: eEGS_POST_REQUEST_LIST_REQ -> 2220 eEGS_POST_REQUEST_LIST_ACK (0x007AEF70)
- 2221: eEGS_POST_SEND_REQ -> 2222 eEGS_POST_SEND_ACK (0x00795F40)
- 2223: eEGS_POST_READ_REQ -> 2224 eEGS_POST_READ_ACK (0x0075A660)
- 2225: eEGS_POST_GET_APPEND_ITEM_REQ -> 2226 eEGS_POST_GET_APPEND_ITEM_ACK (0x0077F8E0)
- 2234: eEGS_POST_RETURN_REQ -> 2235 eEGS_POST_RETURN_ACK (0x00771470)
- 2236: eEGS_POST_DELETE_REQ -> 2237 eEGS_POST_DELETE_ACK (0x007715F0)
"""
from __future__ import annotations
import json

from darkblood.games.entities.items import Item
from darkblood.games.network import results
from darkblood.games.network.messages.mail import (
    PostDeleteAck,
    PostDeleteReq,
    PostEntry,
    PostGetAppendArAck,
    PostGetAppendArReq,
    PostGetAppendItemAck,
    PostGetAppendItemReq,
    PostListAck,
    PostListReq,
    PostNewArrivalNot,
    PostReadAck,
    PostReadReq,
    PostReturnAck,
    PostReturnReq,
    PostSaveAck,
    PostSaveReq,
    PostSendAck,
    PostSendReq,
)
from darkblood.player_management.characters import (
    add_gold,
    free_cells,
    gold_of,
    next_item_uid,
)
from darkblood.games.dispatcher import packet_handler
from darkblood.games.handlers.base import BaseDomainService
from darkblood.games.world import GameWorldManager


class MailHandlers(BaseDomainService):
    """Mailbox / Post domain handlers."""

    def _to_post_entry(self, r: dict) -> PostEntry:
        raw_items = r.get('items_json', '[]')
        items_list = json.loads(raw_items) if isinstance(raw_items, str) else (raw_items or [])
        items = []
        for it in items_list:
            if isinstance(it, Item):
                items.append(it)
            elif isinstance(it, dict):
                items.append(Item(
                    code=it.get('code', ''),
                    uid=it.get('uid', 0),
                    owner=it.get('owner', -1),
                    container=it.get('container', -1),
                    slot=it.get('slot', 0),
                    count=it.get('count', 1),
                    durability=it.get('durability'),
                    upgrade=it.get('upgrade'),
                    quality=it.get('quality', 0),
                ))
        return PostEntry(
            uid=r['uid'],
            post_type=r.get('post_type', 0),
            sender_uid=r.get('sender_char_id', 0),
            is_read=bool(r.get('is_read', 0)),
            has_item=bool(r.get('has_item', 0)),
            can_return=bool(r.get('can_return', 1)),
            remain_days=r.get('remain_days', 30),
            gold=gold_of(r),
            send_time=r.get('send_time', 0),
            sender_name=r.get('sender_name', ''),
            title=r.get('title', ''),
            content=r.get('content', ''),
            items=items,
        )

    @packet_handler(PostListReq)
    async def handle_post_list(self, correlation, body):
        # eEGS_POST_REQUEST_LIST_REQ (0x007962F0) -> 2220 eEGS_POST_REQUEST_LIST_ACK (0x007AEF70).
        req = PostListReq.decode(body)
        self.transport.record('post-request-list-req', body, flag=req.flag)
        char = self.current_char()
        char_id = char.get('id', self.char_id) if char else self.char_id

        inbox_rows = self.store().get_mail_inbox(char_id)
        outbox_rows = self.store().get_mail_outbox(char_id)

        inbox = {r['uid']: self._to_post_entry(r) for r in inbox_rows}
        outbox = {r['uid']: self._to_post_entry(r) for r in outbox_rows}
        unread_count = len([m for m in inbox.values() if not m.is_read])
        notify = unread_count > 0

        ack = PostListAck(result=0, inbox=inbox, outbox=outbox, unread_count=unread_count, notify=notify)
        await self.reply(ack, correlation, note=f'post list ack (inbox={len(inbox)}, outbox={len(outbox)}, unread={unread_count})')

    @packet_handler(PostSendReq)
    async def handle_post_send(self, correlation, body):
        # eEGS_POST_SEND_REQ (0x00795D70) -> 2222 eEGS_POST_SEND_ACK (0x00795F40).
        req = PostSendReq.decode(body)
        self.transport.record('post-send-req', body, recipient=req.recipient, title=req.title, gold=req.gold)
        char = self.current_char()
        sender_id = char.get('id', self.char_id) if char else self.char_id
        sender_name = char.get('name', 'Sender') if char else 'Sender'
        current_gold = gold_of(char)

        if not req.recipient:
            # Empty / test request
            ack = PostSendAck(result=0, remain_gold=current_gold)
            await self.reply(ack, correlation, note='post send ack (default/empty)')
            return

        _, recipient_char = self.store().get_by_name(req.recipient)
        if not recipient_char:
            # 0xCE = player not found / offline
            ack = PostSendAck(result=0xCE, remain_gold=current_gold)
            await self.reply(ack, correlation, note=f'post send fail ({req.recipient} not found)')
            return

        # Check gold
        if current_gold < req.gold:
            ack = PostSendAck(result=1, remain_gold=current_gold)
            await self.reply(ack, correlation, note='post send fail (insufficient gold)')
            return

        # Deduct gold
        if req.gold > 0:
            char['gold'] = current_gold - req.gold

        # Extract attached items
        attached_items = []
        if req.items and char and 'items' in char:
            for item_uid in req.items:
                item_record = next((i for i in char['items'] if i.get('uid') == item_uid), None)
                if item_record:
                    char['items'].remove(item_record)
                    attached_items.append(dict(item_record))

        if char:
            self.save_char()

        # Insert mail
        self.store().send_mail(
            sender_char_id=sender_id,
            sender_name=sender_name,
            recipient_char_id=recipient_char['id'],
            title=req.title,
            content='',
            gold=req.gold,
            extra=req.extra,
            items=attached_items,
            post_type=0,
        )

        # Notify recipient if online
        recipient = GameWorldManager.get().players.get(recipient_char['id'])
        if recipient is not None:
            await self.send_to([recipient.session], PostNewArrivalNot(),
                               note=f'post new arrival not to {recipient_char.get("name")}')

        ack = PostSendAck(result=0, items=[], remain_gold=gold_of(char))
        await self.reply(ack, correlation, note=f'post send ack to {req.recipient}')

    @packet_handler(PostReadReq)
    async def handle_post_read(self, correlation, body):
        # eEGS_POST_READ_REQ (0x007963C0) -> 2224 eEGS_POST_READ_ACK (0x0075A660).
        req = PostReadReq.decode(body)
        self.transport.record('post-read-req', body, mail_uid=req.mail_uid)
        self.store().read_mail(req.mail_uid)
        ack = PostReadAck(result=0, mail_uid=req.mail_uid)
        await self.reply(ack, correlation, note=f'post read ack (uid={req.mail_uid})')

    @packet_handler(PostGetAppendItemReq)
    async def handle_post_get_append_item(self, correlation, body):
        # eEGS_POST_GET_APPEND_ITEM_REQ (0x0079664C) -> 2226 eEGS_POST_GET_APPEND_ITEM_ACK (0x0077F8E0).
        req = PostGetAppendItemReq.decode(body)
        self.transport.record('post-get-append-item-req', body, mail_uid=req.mail_uid)
        char = self.current_char()
        if not char:
            await self.reply(PostGetAppendItemAck(result=results.NO_EXIST_CHAR), correlation, note='post get append fail (no char)')
            return

        cells = free_cells(char)
        claim = self.store().claim_mail_append(
            req.mail_uid, recipient_char_id=char['id'], available_slots=len(cells),
        )
        if claim is None:
            await self.reply(PostGetAppendItemAck(result=results.INVEN_FULL), correlation,
                             note='post get append fail (inventory full)')
            return

        claimed_gold, claimed_items = claim
        if claimed_gold > 0:
            add_gold(char, claimed_gold)

        new_items = []
        for it, (container, slot) in zip(claimed_items, cells):
            it['uid'] = next_item_uid(char)
            it.pop('owner', None)
            it['container'] = container
            it['slot'] = slot
            char.setdefault('items', []).append(it)
            new_items.append(Item(
                code=it.get('code', ''),
                uid=it['uid'],
                owner=char['id'],
                container=container,
                slot=slot,
                count=it.get('count', 1),
                durability=it.get('durability'),
                upgrade=it.get('upgrade'),
                quality=it.get('quality', 0),
            ))

        self.save_char()
        ack = PostGetAppendItemAck(result=0, mail_uid=req.mail_uid, gold=claimed_gold, items=new_items)
        await self.reply(ack, correlation, note=f'post get append item ack (uid={req.mail_uid}, gold={claimed_gold}, items={len(new_items)})')

    @packet_handler(PostReturnReq)
    async def handle_post_return(self, correlation, body):
        # eEGS_POST_RETURN_REQ (0x00A33907) -> 2235 eEGS_POST_RETURN_ACK (0x00771470).
        req = PostReturnReq.decode(body)
        self.transport.record('post-return-req', body, mail_id=req.mail_id)
        if not self.store().return_mail(req.mail_id, self.char_id):
            await self.reply(PostReturnAck(result=results.INVALID_STATE), correlation,
                             note=f'post return refused (mail={req.mail_id})')
            return
        ack = PostReturnAck(result=0, mail_uids=[req.mail_id])
        await self.reply(ack, correlation, note=f'post return ack (mail={req.mail_id})')

    @packet_handler(PostDeleteReq)
    async def handle_post_delete(self, correlation, body):
        # eEGS_POST_DELETE_REQ (0x007964EC) -> 2237 eEGS_POST_DELETE_ACK (0x007715F0).
        req = PostDeleteReq.decode(body)
        self.transport.record('post-delete-req', body, mail_uids=req.mail_uids)
        self.store().delete_mail(req.mail_uids)
        ack = PostDeleteAck(result=0, mail_uids=req.mail_uids)
        await self.reply(ack, correlation, note=f'post delete ack (count={len(req.mail_uids)})')

    @packet_handler(PostGetAppendArReq)
    async def handle_post_get_append_ar(self, correlation, body):
        # eEGS_POST_GET_APPEND_AR_REQ (0x00796700) -> 2249 eEGS_POST_GET_APPEND_AR_ACK (0x007967E0).
        req = PostGetAppendArReq.decode(body)
        self.transport.record('post-get-append-ar-req', body, mail_uid=req.mail_uid)
        char = self.current_char()
        if not char:
            await self.reply(PostGetAppendArAck(result=results.NO_EXIST_CHAR), correlation, note='post get append ar fail (no char)')
            return
        claimed_gold = self.store().claim_mail_gold(req.mail_uid)
        if claimed_gold > 0:
            add_gold(char, claimed_gold)
            self.save_char()
        cur_ar = gold_of(char)
        await self.reply(
            PostGetAppendArAck(result=0, mail_uid=req.mail_uid, current_ar=cur_ar),
            correlation,
            note=f'post get append ar ack (uid={req.mail_uid}, claimed={claimed_gold}, ar={cur_ar})',
        )

    @packet_handler(PostSaveReq)
    async def handle_post_save(self, correlation, body):
        # eEGS_POST_SAVE_REQ (0x007969D0) -> 2253 eEGS_POST_SAVE_ACK (0x0075A780).
        req = PostSaveReq.decode(body)
        self.transport.record('post-save-req', body, mail_uid=req.mail_uid)
        self.store().save_mail(req.mail_uid)
        await self.reply(
            PostSaveAck(result=0, mail_uid=req.mail_uid),
            correlation,
            note=f'post save ack (uid={req.mail_uid})',
        )
