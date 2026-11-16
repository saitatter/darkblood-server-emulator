from darkblood.core.serialization.jser import event
from darkblood.games.network.messages import FriendListAck, GuildOrAttendanceAck, PostListAck


class SocialHandlers:
    """Mailbox, friends, block list and client notifications."""

    async def on_2219(self, correlation, body):
        # eEGS_POST_REQUEST_LIST_ACK (2220), handler 0x7AEF70:
        # result, two tagged maps, u32 unread count, bool notification flag.
        # Empty mailbox is a local offline default; notification stays false.
        ack = PostListAck().encode()
        await self.transport.send_event(event(2220, ack, correlation),
                                        note='empty post list ack')

    async def on_2131(self, correlation, body):
        # eEGS_FRIEND_LIST_REQUEST_REQ -> eEGS_FRIEND_LIST_REQUEST_ACK (2132), handler 0x7712E0:
        # u32 result (0), tag 0x17 map (0x76AE20). Empty map is b'\x17\x00'.
        ack = FriendListAck().encode()
        await self.transport.send_event(event(2132, ack, correlation), note='friend list ack')

    async def on_2569(self, correlation, body):
        # Opcode 2569 -> 2570 ACK, handler 0x772160:
        # u32 result (0), tag 0x17 map (0x76AE20). Empty map is b'\x17\x00'.
        ack = GuildOrAttendanceAck().encode()
        await self.transport.send_event(event(2570, ack, correlation), note='opcode 2570 ack')

    async def on_2352(self, correlation, body):
        # eEGS_IP_ADDRESS_NOT: client LAN/WAN IP notification only.
        pass

    async def on_2203(self, correlation, body):
        # eEGS_COMPUTER_STAT_NOT: client hardware report; notification only.
        pass

    async def on_0(self, correlation, body):
        # Application-level keepalive heartbeat sent by client periodically.
        pass
