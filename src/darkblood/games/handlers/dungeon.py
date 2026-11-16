import struct
import time

from darkblood.core.hashing import jhash
from darkblood.core.serialization.jser import WireError, event, read_varuint, varuint, wide_string
from darkblood.frontend.relay import RELAY_PORT
from darkblood.games.network.messages import (
    ActiveWarFlagReq,
    BackToSquareAck,
    ChangeDungeonLayerNot,
    ChangeMapCodeAck,
    ChangeTeamAck,
    ChangeTeamReq,
    ChoiceRewardPartyRankAck,
    ChoiceRewardPartyRankReq,
    CreateRoomAck,
    DailyRebirthCoinUseAck,
    DailyRebirthCoinUseReq,
    DropItemNot,
    GameplayDieCharAck,
    GameplayDieCharReq,
    GuideBeginnerUpdateReq,
    LeaveRoomAck,
    MonsterDeadReq,
    PartyAcceptInviteAck,
    PartyAcceptInviteReq,
    PartyInviteAck,
    PartyInviteReq,
    RebirthCoinChangeNot,
    RoomInfoListAck,
    SelectDungeonAck,
)
from darkblood.games.state import selected_character

# The daily-claim sender refuses when owned or received coins reach 3.
DAILY_REBIRTH_COINS = 3


class DungeonHandlers:
    """Rooms, dungeon gate, map code and game start."""

    async def on_2010(self, correlation, body):
        # eEGS_GET_ROOMINFOLIST_REQ (sender 0x7AB140) -> 2011: no open rooms.
        await self.transport.send_event(event(2011, RoomInfoListAck().encode(), correlation),
                                        note='room info list ack')

    async def on_5001(self, correlation, body):
        # eERC_CREATE_ROOM_REQ (writer 0x58B060): wstring name, i32, i32, i16,
        # i16 (observed: "_singleplay", -1, -1, -1, 1) -> 5002 CREATE_ROOM_ACK.
        name, a, b, c, d = '', -1, -1, -1, 1
        try:
            length, offset = read_varuint(body, 0)
            name = body[offset:offset + length].decode('utf-16le')
            a, b, c, d = struct.unpack_from('<iihh', body, offset + length)
        except (WireError, struct.error, UnicodeDecodeError):
            pass
        self.room_id = getattr(self, 'room_id', 0) + 1
        ack = CreateRoomAck(room_id=self.room_id, name=name, req_a=a, req_b=b, req_c=c, req_d=d,
                            host_uid=selected_character.get('id', 0),
                            relay_port=RELAY_PORT).encode()
        await self.transport.send_event(event(5002, ack, correlation),
                                        note='create room ack (%s)' % name)

    async def on_5043(self, correlation, body):
        # eERC_SELECT_DUNGEON_REQ (sender 0x7AC1C0), observed body:
        # ffffff7f + J-wstring gate id ("Act1_G1") -> 5044.
        gate = ''
        try:
            length, offset = read_varuint(body, 4)
            gate = body[offset:offset + length].decode('utf-16le')
        except (WireError, UnicodeDecodeError):
            pass
        ack = SelectDungeonAck(gate_id=gate).encode()
        await self.transport.send_event(event(5044, ack, correlation),
                                        note='select dungeon ack (%s)' % gate)

    async def on_5009(self, correlation, body):
        # eERC_CHANGE_MAPCODE_REQ (sender 0x7AD680), observed body: ffffff7f
        # + J-wstring map code ("Act1_G1_A10") + bool -> 5010, consumed by
        # JAppStateDungeonGate vf20 -> 0x6D4A00 (only in app state 8).
        code, flag = '', False
        try:
            length, offset = read_varuint(body, 4)
            code = body[offset:offset + length].decode('utf-16le')
            flag = body[offset + length:offset + length + 1] == bytes([1])
        except (WireError, UnicodeDecodeError):
            pass
        ack = ChangeMapCodeAck(map_code=code, flag=flag).encode()
        await self.transport.send_event(event(5010, ack, correlation),
                                        note='change mapcode ack (%s)' % code)

    async def on_5013(self, correlation, body):
        # eERC_START_GAME_REQ -> eERC_START_GAME_ACK (5014), handler 0x7880A0.
        # Success reader: u16, u32, J-wstring (0xB35AB0), three 0x17 maps,
        # then a 0x10 vector (0x78836B -> 0x4B94C0). Scalar/string type
        # codes are not wire tags; empty lengths use the terminal byte 0x80.
        # The J-wstring is the map code: 0x788539 resolves it with 0x98E630
        # and dereferences the result (+0x28), so an empty/unknown code
        # crashes. The request (sender observed live) is ffffff7f + J-wstring
        # map code ("Act1_G1_A10"); echo it. Other field meanings and nonempty
        # entries still need recovery.
        code = ''
        try:
            length, offset = read_varuint(body, 4)
            code = body[offset:offset + length].decode('utf-16le')
        except (WireError, UnicodeDecodeError):
            pass
        ack = (struct.pack('<IHI', 0, 0, 0) + wide_string(code)
               + (b'\x17' + varuint(0)) * 3 + b'\x10' + varuint(0))
        await self.transport.send_event(event(5014, ack, correlation),
                                        note='start game ack')

    async def on_5095(self, correlation, body):
        # eERC_CHANGE_DUNGEON_LAYER_NOT (sender 0x7900B0): ffffff7f + i64 layer_net_id.
        try:
            msg = ChangeDungeonLayerNot.decode(body)
            self.current_dungeon_layer = msg.layer_id
            self.current_dungeon_map_hash = msg.map_hash
            self.transport.record('dungeon-layer', body, layer_id=msg.layer_id, map_hash='0x%08x' % msg.map_hash)
        except (struct.error, ValueError):
            pass

    async def on_2422(self, correlation, body):
        # eEGS_ACTIVE_WARFLAG_REQ (sender 0x79C300): ffffff7f + u32 war_flag_id.
        try:
            msg = ActiveWarFlagReq.decode(body)
            self.active_war_flag = msg.war_flag_id
            self.transport.record('active-warflag', body, war_flag_id=msg.war_flag_id)
        except (struct.error, ValueError):
            pass

    async def on_2358(self, correlation, body):
        # eEGS_GUIDE_BEGINNER_UPDATE_REQ (sender 0x79A3B0): ffffff7f + vector<u32> guide_ids.
        try:
            msg = GuideBeginnerUpdateReq.decode(body)
            self.transport.record('guide-beginner-update', body, guide_ids=msg.guide_ids)
        except (struct.error, ValueError):
            pass

    async def on_5063(self, correlation, body):
        # eERC_MONSTER_DEAD_REQ (sender 0x78A690): ffffff7f + u32 monster_id + u32 param.
        try:
            msg = MonsterDeadReq.decode(body)
            self.transport.record('monster-dead', body, monster_id=msg.monster_id, param=msg.param)
        except (struct.error, ValueError):
            pass

    def _current_char(self):
        char = None
        if 'id' in selected_character:
            char = self.store().get(self.account, selected_character['id'])
        if not char:
            chars = self.store().characters(self.account)
            char = chars[0] if chars else None
        return char

    async def on_5093(self, correlation, body):
        # eERC_GAMEPLAY_DIE_CHAR_REQ (writer 0x0078EDF0) -> 5094 (0x0078F090).
        # bDie = 1: echo the client's own UID so the handler opens the revive
        # window (page 0x6B). bDie = 0: revive; spend one rebirth coin and
        # report the remaining count in the trailing u16.
        req = GameplayDieCharReq.decode(body)
        char = self._current_char()
        coins = 0
        if char is not None:
            coins = int(char.get('rebirth_coins', 3))
            if not req.bDie and coins > 0:
                coins -= 1
                char['rebirth_coins'] = coins
                self.store().save()
        self.die_count = getattr(self, 'die_count', 0) + (1 if req.bDie else 0)
        ack = GameplayDieCharAck(
            result=0,
            char_uid=req.char_uid,
            other_uid=0,
            bDie=req.bDie,
            damage=req.damage,
            cur_hp=req.cur_hp,
            max_hp=req.max_hp,
            die_count=self.die_count,
            rebirth_coin=coins,
        ).encode()
        await self.transport.send_event(event(5094, ack, correlation),
                                        note='gameplay die char ack (die=%d coins=%d)' % (req.bDie, coins))

    async def on_2448(self, correlation, body):
        # eEGS_DAILY_REBIRTH_COIN_USE_REQ -> 2449 (0x0079DC70) + 2286 (0x007983B0).
        # Daily claim of free rebirth coins: top the owned coins up to 3, count
        # them as received today, then announce the new total with 2286.
        req = DailyRebirthCoinUseReq.decode(body)
        char = self._current_char()
        if char is None:
            await self.transport.send_event(event(2449, struct.pack('<I', 1), correlation),
                                            note='daily rebirth coin fail (no char)')
            return
        today = time.strftime('%Y-%m-%d')
        if char.get('daily_rebirth_day') != today:
            char['daily_rebirth_day'] = today
            char['daily_rebirth_recv'] = 0
        coins = int(char.get('rebirth_coins', 3))
        received = int(char.get('daily_rebirth_recv', 0))
        granted = max(0, min(DAILY_REBIRTH_COINS - coins, DAILY_REBIRTH_COINS - received))
        coins += granted
        received += granted
        char['rebirth_coins'] = coins
        char['daily_rebirth_recv'] = received
        self.store().save()
        ack = DailyRebirthCoinUseAck(result=0, daily_recv_cnt=received, pcbang_coin_remain=0).encode()
        await self.transport.send_event(event(2449, ack, correlation),
                                        note='daily rebirth coin use ack (pcbang=%d +%d)' % (req.coin_type, granted))
        await self.transport.send_event(event(2286, RebirthCoinChangeNot(result=0, coins=coins).encode()),
                                        note='rebirth coin change not (%d)' % coins)

    async def on_5005(self, correlation, body):
        # eERC_LEAVE_ROOM_REQ (0x0058B240) -> 5006 eERC_LEAVE_ROOM_ACK (0x00598A00).
        # Acknowledges leaving game room before eERC_BACK_TO_SQUARE_REQ (5045).
        ack = LeaveRoomAck(result=0).encode()
        await self.transport.send_event(event(5006, ack, correlation), note='leave room ack')

    async def on_5045(self, correlation, body):
        # eERC_BACK_TO_SQUARE_REQ (0x007A0000.c:8367) -> 5046 eERC_BACK_TO_SQUARE_ACK (0x007897F0).
        # Return to town/square from dungeon.
        from darkblood.games.entities.character import layer_net_id
        ack = BackToSquareAck(result=0, square_uid=1, layer_net_id=layer_net_id()).encode()
        await self.transport.send_event(event(5046, ack, correlation), note='back to square ack')

    async def on_5090(self, correlation, body):
        # eERC_CHOICE_REWARD_PARTYRANK_REQ (0x00780000.c:9280) -> 5091 eERC_CHOICE_REWARD_PARTYRANK_ACK (0x0078D660).
        req = ChoiceRewardPartyRankReq.decode(body)
        char_id = selected_character.get('id', 1)
        item_id = jhash('Ihppa0001')
        ack = ChoiceRewardPartyRankAck(
            result=0,
            char_uid=char_id,
            reward_uid=1,
            item_id=item_id,
            count=1,
            drop_type=0,
            box_type=0,
            box_cost=0
        ).encode()
        await self.transport.send_event(event(5091, ack, correlation),
                                        note='choice reward partyrank ack (card=%d)' % req.card_index)

    async def on_5049(self, correlation, body):
        # eERC_INVITE_REQ -> 5050 eERC_INVITE_ACK (0x00758700).
        req = PartyInviteReq.decode(body)
        self.transport.record('party-invite-req', body, target_uid=req.target_uid)
        ack = PartyInviteAck(result=0).encode()
        await self.transport.send_event(event(5050, ack, correlation), note=f'party invite ack (target={req.target_uid})')

    async def on_5054(self, correlation, body):
        # eERC_ACCEPT_INVITE_REQ -> 5055 eERC_ACCEPT_INVITE_ACK.
        req = PartyAcceptInviteReq.decode(body)
        self.transport.record('party-accept-invite-req', body, host_uid=req.host_uid)
        ack = PartyAcceptInviteAck(result=0).encode()
        await self.transport.send_event(event(5055, ack, correlation), note=f'party accept invite ack (host={req.host_uid})')

    async def on_5015(self, correlation, body):
        # eERC_CHANGE_TEAM_REQ -> 5016 eERC_CHANGE_TEAM_ACK.
        req = ChangeTeamReq.decode(body)
        self.transport.record('change-team-req', body, team_id=req.team_id)
        ack = ChangeTeamAck(result=0, team_id=req.team_id).encode()
        await self.transport.send_event(event(5016, ack, correlation), note=f'change team ack (team={req.team_id})')

    async def on_5065(self, correlation, body):
        # eERC_PICK_UP_ITEM_REQ -> 5066 eERC_PICK_UP_ITEM_ACK & 5068 eERC_PICK_UP_ITEM_RESULT_ACK (0x0078AD80).
        from darkblood.games.network.messages import PickUpItemAck, PickUpItemReq, PickUpItemResultAck
        req = PickUpItemReq.decode(body)
        self.transport.record('pick-up-item-req', body, drop_uid=req.drop_uid)
        char_uid = selected_character.get('id', 1)
        ack = PickUpItemAck(result=0).encode()
        await self.transport.send_event(event(5066, ack, correlation), note=f'pick up item ack (drop={req.drop_uid})')
        res_ack = PickUpItemResultAck(result=0, picker_uid=char_uid, item=None).encode()
        await self.transport.send_event(event(5068, res_ack), note=f'pick up item result ack (drop={req.drop_uid})')

    async def on_5363(self, correlation, body):
        # eERC_GOLDGOBLIEN_ATTACK_REQ -> 5364 eERC_GOLDGOBLIEN_ATTACK_ACK (0x00784A10).
        from darkblood.games.network.messages import GoldGoblinAttackAck, GoldGoblinAttackReq
        req = GoldGoblinAttackReq.decode(body)
        self.transport.record('gold-goblin-attack-req', body, goblin_id=req.goblin_id, damage=req.damage)
        ack = GoldGoblinAttackAck(result=0).encode()
        await self.transport.send_event(event(5364, ack, correlation), note=f'gold goblin attack ack (goblin={req.goblin_id})')

    async def on_5365(self, correlation, body):
        # eERC_GOLDGOBLIEN_DEAD_REQ -> 5366 eERC_GOLDGOBLIEN_DEAD_ACK (0x00784CA0).
        from darkblood.games.network.messages import GoldGoblinDeadAck, GoldGoblinDeadReq
        req = GoldGoblinDeadReq.decode(body)
        self.transport.record('gold-goblin-dead-req', body, goblin_id=req.goblin_id)
        ack = GoldGoblinDeadAck(result=0, goblin_id=req.goblin_id, items=[]).encode()
        await self.transport.send_event(event(5366, ack, correlation), note=f'gold goblin dead ack (goblin={req.goblin_id})')


