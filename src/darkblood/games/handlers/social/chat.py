"""Town/party/whisper chat, speaker items and GM slash commands."""
import struct

from darkblood.core.serialization.jser import WireError, event
from darkblood.games.dispatcher import packet_handler
from darkblood.games.network.messages import FriendListAck, GuildOrAttendanceAck, PostListAck


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
        from darkblood.games.progression import level_up_not
        from darkblood.games.progression import MAX_LEVEL, add_ap, advance_level
        req = ChatReq.decode(body)
        msg = req.message.strip()
        self.transport.record('chat-req', body, message=msg)

        char = self.current_char()

        char_name = char.get('name', 'Player') if char else 'Player'
        system_reply = None

        # In-Game GM Console Commands
        if msg.startswith('/'):
            parts = msg.split()
            cmd = parts[0].lower()
            if cmd == '/gold' and len(parts) > 1 and char:
                try:
                    amount = int(parts[1])
                    char['gold'] = char.get('gold', 0) + amount
                    char['u66'] = char['gold']
                    self.save_char()
                    system_reply = f'[GM] Added {amount} gold. Balance: {char["gold"]}'
                except ValueError:
                    system_reply = '[GM] Usage: /gold <amount>'
            elif cmd == '/levelup' and char:
                levels = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
                previous = char.get('level', 1)
                gained = min(levels, max(0, MAX_LEVEL - previous))
                if gained:
                    level = previous + gained
                    advance_level(char, level, exp=0)
                    self.save_char()
                    await self.transport.send_event(event(5087, level_up_not(char).encode()),
                                                    note=f'gm levelup not (level={level})')
                system_reply = f'[GM] Leveled up by {gained}. Current level: {previous + gained}, SP: {char.get("sp", 0)}'
            elif cmd == '/sp' and len(parts) > 1 and char:
                try:
                    sp_amt = int(parts[1])
                    add_ap(char, sp_amt)
                    self.save_char()
                    system_reply = f'[GM] Added {sp_amt} SP. Total SP: {char["sp"]}'
                except ValueError:
                    system_reply = '[GM] Usage: /sp <amount>'
            elif cmd == '/item' and len(parts) > 1 and char:
                from darkblood.player_management.characters import add_reward_items
                icode = parts[1]
                icnt = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1
                add_reward_items(char, [(icode, icnt)])
                self.save_char()
                system_reply = f'[GM] Granted {icnt}x {icode}'
            elif cmd == '/bags' and char:
                from darkblood.player_management.characters import free_bag_slots, grant_test_bags
                changed = grant_test_bags(char)
                self.save_char()
                system_reply = (f'[GM] {changed} bag(s) set to 20 cells, {free_bag_slots(char)} free. '
                                'Select the character again to load them.')

        reply_msg = system_reply if system_reply else msg
        sender = 'System' if system_reply else char_name
        target = req.target
        ack = ChatAck(result=0, channel=req.channel, target=target, sender=sender, message=reply_msg).encode()
        await self.transport.send_event(event(5041, ack, correlation), note=f'chat ack ({reply_msg})')
        if system_reply or not msg:
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

