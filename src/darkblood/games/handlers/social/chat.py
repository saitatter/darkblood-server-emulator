"""Town/party/whisper chat and speaker item handlers."""
from darkblood.core.serialization.jser import event
from darkblood.games.dispatcher import packet_handler


class ChatHandlers:
    @packet_handler(2128)
    async def handle_use_speaker_item(self, correlation, body):
        # eEGS_USE_SPEAKER_ITEM_REQ (0x00790000.c:1992) -> 2129 eEGS_USE_SPEAKER_ITEM_ACK (0x0077F320).
        from darkblood.games.network.messages import UseSpeakerItemAck, UseSpeakerItemReq
        req = UseSpeakerItemReq.decode(body)
        self.transport.record('use-speaker-req', body, speaker=req.speaker_uid, msg=req.message)
        ack = UseSpeakerItemAck(result=0, speaker_uid=req.speaker_uid).encode()
        await self.transport.send_event(event(2129, ack, correlation),
                                        note=f'use speaker ack (speaker={req.speaker_uid} msg={req.message[:20]})')


    @packet_handler(5040)
    async def handle_chat(self, correlation, body):
        # eERC_CHAT_REQ (0x007AC5E0) -> 5041 eERC_CHAT_ACK (0x007AC890).
        from darkblood.games.network.messages import ChatAck, ChatReq
        req = ChatReq.decode(body)
        msg = req.message.strip()
        self.transport.record('chat-req', body, message=msg)

        char = self.current_char()
        char_name = char.get('name', 'Player') if char else 'Player'
        target = req.target
        ack = ChatAck(result=0, channel=req.channel, target=target, sender=char_name, message=msg).encode()
        await self.transport.send_event(event(5041, ack, correlation), note=f'chat ack ({msg})')
        if not msg:
            return
        # Other players receive the line as an unsolicited 5041 (global handler
        # 0x007AC890). Channel 1 is normal chat (live), 2 a whisper (the handler
        # compares server_key at +0x76 against local bits 54-58 and target name);
        # any other channel goes to the sender's party room.
        recipients = self._chat_recipients(req.channel, target)
        packet = event(5041, ack)
        for session in recipients:
            try:
                await session.transport.send_event(packet, note=f'chat from {char_name} (channel {req.channel})')
            except (ConnectionError, OSError):
                pass
        self.transport.record('chat-route', b'', channel=req.channel, target=target, recipients=len(recipients))


    def _chat_recipients(self, channel, target):
        """Sessions other than the sender that should see a chat line."""
        from darkblood.games.world import GameWorldManager
        world = GameWorldManager.get()
        me = self.session
        if channel == 2:
            wanted = (target or '').strip().lower()
            return [p.session for p in world.players.values()
                    if p.session is not me and p.char_data.get('name', '').lower() == wanted]
        room = me.dungeon.room
        in_party = room is not None and room.info.name != '_singleplay'
        if channel != 1 or (in_party and room.started):
            # Party channel, or normal chat inside a shared dungeon run.
            return [m for m in room.members if m is not me] if in_party else []
        player = world.get_player(me.active_char_id) if me.active_char_id else None
        square = player.square_id if player else me.square_id
        return [p.session for p in world.get_players_in_square(square) if p.session is not me]


    @packet_handler(2354)
    async def handle_chat_notify(self, correlation, body):
        # eEGS_CHAT_NOTIFY_REQ (0x004E6D30) -> 2355 eEGS_CHAT_NOTIFY_ACK.
        from darkblood.games.network.messages.social import ChatNotifyAck, ChatNotifyReq
        req = ChatNotifyReq.decode(body)
        self.transport.record('chat-notify-req', body, target=req.target_name, category=req.category)
        await self.reply(ChatNotifyAck(result=0), correlation, note='chat notify ack')

