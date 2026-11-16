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

    async def on_2024(self, correlation, body):
        # eEGS_GET_INVITELIST_REQ -> 2025 eEGS_GET_INVITELIST_ACK (0x006A2E10).
        from darkblood.games.network.messages import GetInviteListAck
        ack = GetInviteListAck().encode()
        await self.transport.send_event(event(2025, ack, correlation), note='invite list ack')

    async def on_2139(self, correlation, body):
        # eEGS_FRIEND_LIST_ADD_REQ (0x00790000.c:1595) -> 2140 eEGS_FRIEND_LIST_ADD_ACK (0x007591A0).
        from darkblood.games.network.messages import FriendListAddAck, FriendListAddReq
        req = FriendListAddReq.decode(body)
        self.transport.record('friend-add', body, name=req.char_name)
        # Default response: 0xCE (player not found or offline)
        ack = FriendListAddAck(result=0xCE).encode()
        await self.transport.send_event(event(2140, ack, correlation), note=f'friend add ack ({req.char_name})')

    async def on_2135(self, correlation, body):
        # eEGS_FRIEND_LIST_DELETE_REQ (0x00790000.c:1824) -> 2136 eEGS_FRIEND_LIST_DELETE_ACK (0x00759560).
        from darkblood.games.network.messages import FriendListDeleteAck, FriendListDeleteReq
        req = FriendListDeleteReq.decode(body)
        self.transport.record('friend-delete', body, char_uid=req.char_uid)
        ack = FriendListDeleteAck(result=0, char_uid=req.char_uid).encode()
        await self.transport.send_event(event(2136, ack, correlation), note=f'friend delete ack ({req.char_uid})')

