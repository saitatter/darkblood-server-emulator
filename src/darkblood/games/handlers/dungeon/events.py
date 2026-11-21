"""Cronos attendance, Explore, Clear Rank, war flags and dungeon telemetry."""
import struct
import time
from dataclasses import dataclass, field

from darkblood.core.hashing import jhash
from darkblood.core.network.proudnet import relay_address
from darkblood.core.serialization.jser import WireError, event, read_varuint, strip_prefix
from darkblood.games.entities.character import Character
from darkblood.games.network.messages import (
    ActiveWarFlagReq,
    ChangeDungeonLayerNot,
    ChangeItemObtainAck,
    ChangeItemObtainReq,
    ChangeRoomInfoAck,
    ChangeRoomInfoReq,
    ChangeMapCodeAck,
    ChangeTeamAck,
    ChangeTeamReq,
    ChoiceRewardPartyRankAck,
    ChoiceRewardPartyRankReq,
    CreateRoomAck,
    CreateRoomReq,
    DailyRebirthCoinUseAck,
    DailyRebirthCoinUseReq,
    DropItemNot,
    GameplayDieCharAck,
    GameplayDieCharReq,
    GuideBeginnerUpdateReq,
    JoinRoomAck,
    JoinRoomReq,
    LeaveRoomAck,
    MonsterDeadReq,
    PartyAcceptInviteAck,
    PartyAcceptInviteReq,
    PartyInviteAck,
    PartyInviteReq,
    RebirthCoinChangeNot,
    RoomInfo,
    RoomInfoListAck,
    RoomMember,
    RoomMemberJoinedNot,
    RoomMemberLeftNot,
    DungeonHistory,
    SelectDungeonAck,
    StartGameAck,
    StartGameReq,
)
from darkblood.games.dispatcher import packet_handler
from darkblood.games.handlers.base import BaseDomainService
from darkblood.games.network import results

# The daily-claim sender refuses when owned or received coins reach 3.
DAILY_REBIRTH_COINS = 3


@dataclass
class DungeonRoom:
    info: RoomInfo
    host: object
    members: dict = field(default_factory=dict)
    started: bool = False
    # Shared run state (reset at the host's 5013): monster kills already credited
    # ((monster id, instance) from 5063) and the floor drops all members see.
    dead: set = field(default_factory=set)
    floor_drops: dict = field(default_factory=dict)
    floor_gold: dict = field(default_factory=dict)
    next_drop_uid: int = 0
    # 5047 join requests waiting for the host: char id -> (session, correlation).
    join_requests: dict = field(default_factory=dict)
    loot_mode: int = 1  # 5088 mode: 1 = free for all (fresh page default), 0 = random looting (0x00584460)



class DungeonEventsHandlers:
    @packet_handler(ActiveWarFlagReq)
    async def handle_active_war_flag(self, correlation, body):
        # eEGS_ACTIVE_WARFLAG_REQ (sender 0x79C300): ffffff7f + u32 war_flag_id.
        try:
            msg = ActiveWarFlagReq.decode(body)
            self.active_war_flag = msg.war_flag_id
            self.transport.record('active-warflag', body, war_flag_id=msg.war_flag_id)
        except (struct.error, ValueError):
            pass


    @packet_handler(2204)
    async def handle_frame_stat(self, correlation, body):
        # eEGS_FRAME_STAT_NOT: client frame-rate telemetry sent after dungeon
        # results (live: ffffff7f 3a f9010000, the u32 varies per run). The
        # opcode has no ACK; recorded only so it no longer shows as unhandled.
        self.transport.record('frame-stat', body)


    @packet_handler(GuideBeginnerUpdateReq)
    async def handle_guide_beginner_update(self, correlation, body):
        # eEGS_GUIDE_BEGINNER_UPDATE_REQ (sender 0x79A3B0): ffffff7f + vector<u32> guide_ids.
        try:
            msg = GuideBeginnerUpdateReq.decode(body)
            self.transport.record('guide-beginner-update', body, guide_ids=msg.guide_ids)
        except (struct.error, ValueError):
            pass


    @packet_handler(2289)
    async def handle_cronos_reward(self, correlation, body):
        from darkblood.games.network.messages.dungeon import CronosRewardAck, CronosRewardReq
        req = CronosRewardReq.decode(body)
        await self.reply(CronosRewardAck(result=0, items=[], index=req.index, reward_select=req.reward_select),
                         correlation, note=f'cronos reward ack (idx={req.index})')


    @packet_handler(2292)
    async def handle_cronos_info(self, correlation, body):
        from darkblood.games.network.messages.dungeon import CronosInfoAck
        await self.reply(CronosInfoAck(result=0), correlation, note='cronos info ack')


    @packet_handler(2294)
    async def handle_cronos_date(self, correlation, body):
        from darkblood.games.network.messages.dungeon import CronosDateAck
        await self.reply(CronosDateAck(result=0), correlation, note='cronos date ack')


    @packet_handler(2296)
    async def handle_cronos_today_time(self, correlation, body):
        from darkblood.games.network.messages.dungeon import CronosTodayTimeAck
        await self.reply(CronosTodayTimeAck(result=0, today_login_second=60), correlation,
                         note='cronos today time ack')


    @packet_handler(2299)
    async def handle_cronos_stamp(self, correlation, body):
        from darkblood.games.network.messages.dungeon import CronosStampAck
        await self.reply(CronosStampAck(result=0, items=[], item_id=0), correlation, note='cronos stamp ack')


    @packet_handler(2651)
    async def handle_explore_start(self, correlation, body):
        from darkblood.games.network.messages.dungeon import ExploreStartAck, ExploreStartReq
        req = ExploreStartReq.decode(body)
        await self.reply(
            ExploreStartAck(result=0, explore_char_uid=req.char_uid, explore_time=req.explore_time, items=[], stress=0),
            correlation, note=f'explore start ack (char={req.char_uid})',
        )


    @packet_handler(2653)
    async def handle_explore_cancel(self, correlation, body):
        from darkblood.games.network.messages.dungeon import ExploreCancelAck, ExploreCancelReq
        req = ExploreCancelReq.decode(body)
        await self.reply(ExploreCancelAck(result=0, explore_char_uid=req.explore_char_uid), correlation,
                         note=f'explore cancel ack (char={req.explore_char_uid})')


    @packet_handler(2656)
    async def handle_explore_get_reward(self, correlation, body):
        from darkblood.games.network.messages.dungeon import ExploreGetRewardAck, ExploreGetRewardReq
        req = ExploreGetRewardReq.decode(body)
        await self.reply(ExploreGetRewardAck(result=0, reward_uid=req.reward_uid, items=[]), correlation,
                         note=f'explore get reward ack (uid={req.reward_uid})')


    @packet_handler(2662)
    async def handle_explore_cancel_by_user_uid(self, correlation, body):
        from darkblood.games.network.messages.dungeon import ExploreCancelByUserUidAck, ExploreCancelByUserUidReq
        req = ExploreCancelByUserUidReq.decode(body)
        await self.reply(ExploreCancelByUserUidAck(result=0, explore_char_uid=req.explore_char_uid), correlation,
                         note=f'explore cancel by uid ack (char={req.explore_char_uid})')


    @packet_handler(2539)
    async def handle_clear_rank_history_info(self, correlation, body):
        import time
        from darkblood.games.network.messages.dungeon import (
            ClearRankHistoryInfoAck, ClearRankHistoryInfoReq, DungeonClearRankInfo,
        )
        req = ClearRankHistoryInfoReq.decode(body)
        await self.reply(
            ClearRankHistoryInfoAck(result=0, start_time=int(time.time()), cur_page=req.page,
                                    map_id=req.map_id, rank_infos=[], my_rank_info=DungeonClearRankInfo()),
            correlation, note=f'clear rank history ack (map={req.map_id} page={req.page})',
        )


    @packet_handler(5228)
    async def handle_clear_rank_info(self, correlation, body):
        from darkblood.games.network.messages.dungeon import (
            ClearRankInfoAck, ClearRankInfoReq, DungeonClearRankInfo,
        )
        req = ClearRankInfoReq.decode(body)
        await self.reply(
            ClearRankInfoAck(result=0, cur_page=req.page, map_id=req.map_id,
                             rank_infos=[], my_rank_info=DungeonClearRankInfo()),
            correlation, note=f'clear rank info ack (map={req.map_id} page={req.page})',
        )

