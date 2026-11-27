"""Cronos attendance, Explore, Clear Rank, war flags and dungeon telemetry."""
import struct
import time

from darkblood.games.dispatcher import packet_handler
from darkblood.games.network.messages import (
    ActiveWarFlagReq,
    ClearRankHistoryInfoAck,
    ClearRankHistoryInfoReq,
    ClearRankInfoAck,
    ClearRankInfoReq,
    CronosDateAck,
    CronosInfoAck,
    CronosRewardAck,
    CronosRewardReq,
    CronosStampAck,
    CronosTodayTimeAck,
    DungeonClearRankInfo,
    ExploreCancelAck,
    ExploreCancelByUserUidAck,
    ExploreCancelByUserUidReq,
    ExploreCancelReq,
    ExploreGetRewardAck,
    ExploreGetRewardReq,
    ExploreJoinAck,
    ExploreLeaveAck,
    ExploreStartAck,
    ExploreStartReq,
    GuideBeginnerUpdateReq,
)


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
        req = CronosRewardReq.decode(body)
        await self.reply(CronosRewardAck(result=0, items=[], index=req.index, reward_select=req.reward_select),
                         correlation, note=f'cronos reward ack (idx={req.index})')


    @packet_handler(2292)
    async def handle_cronos_info(self, correlation, body):
        await self.reply(CronosInfoAck(result=0), correlation, note='cronos info ack')


    @packet_handler(2294)
    async def handle_cronos_date(self, correlation, body):
        await self.reply(CronosDateAck(result=0), correlation, note='cronos date ack')


    @packet_handler(2296)
    async def handle_cronos_today_time(self, correlation, body):
        await self.reply(CronosTodayTimeAck(result=0, today_login_second=60), correlation,
                         note='cronos today time ack')


    @packet_handler(2299)
    async def handle_cronos_stamp(self, correlation, body):
        await self.reply(CronosStampAck(result=0, items=[], item_id=0), correlation, note='cronos stamp ack')


    @packet_handler(2651)
    async def handle_explore_start(self, correlation, body):
        req = ExploreStartReq.decode(body)
        await self.reply(
            ExploreStartAck(result=0, explore_char_uid=req.char_uid, explore_time=req.explore_time, items=[], stress=0),
            correlation, note=f'explore start ack (char={req.char_uid})',
        )


    @packet_handler(2653)
    async def handle_explore_cancel(self, correlation, body):
        req = ExploreCancelReq.decode(body)
        await self.reply(ExploreCancelAck(result=0, explore_char_uid=req.explore_char_uid), correlation,
                         note=f'explore cancel ack (char={req.explore_char_uid})')


    @packet_handler(2656)
    async def handle_explore_get_reward(self, correlation, body):
        req = ExploreGetRewardReq.decode(body)
        await self.reply(ExploreGetRewardAck(result=0, reward_uid=req.reward_uid, items=[]), correlation,
                         note=f'explore get reward ack (uid={req.reward_uid})')


    @packet_handler(2662)
    async def handle_explore_cancel_by_user_uid(self, correlation, body):
        req = ExploreCancelByUserUidReq.decode(body)
        await self.reply(ExploreCancelByUserUidAck(result=0, explore_char_uid=req.explore_char_uid), correlation,
                         note=f'explore cancel by uid ack (char={req.explore_char_uid})')

    @packet_handler(5358)
    async def handle_explore_join(self, correlation, body):
        """Opcode 5358 (eERC_EXPLORE_JOIN_REQ) -> 5359 (0x006C35B0, Forest of Oblivion)."""
        await self.reply(ExploreJoinAck(result=0), correlation, note='explore join ack (Forest of Oblivion)')

    @packet_handler(5360)
    async def handle_explore_leave(self, correlation, body):
        """Opcode 5360 (eERC_EXPLORE_LEAVE_REQ) -> 5361 (0x006B5F00, return to town)."""
        await self.reply(ExploreLeaveAck(result=0), correlation, note='explore leave ack')


    @packet_handler(2539)
    async def handle_clear_rank_history_info(self, correlation, body):
        import time
        req = ClearRankHistoryInfoReq.decode(body)
        await self.reply(
            ClearRankHistoryInfoAck(result=0, start_time=int(time.time()), cur_page=req.page,
                                    map_id=req.map_id, rank_infos=[], my_rank_info=DungeonClearRankInfo()),
            correlation, note=f'clear rank history ack (map={req.map_id} page={req.page})',
        )


    @packet_handler(5228)
    async def handle_clear_rank_info(self, correlation, body):
        req = ClearRankInfoReq.decode(body)
        await self.reply(
            ClearRankInfoAck(result=0, cur_page=req.page, map_id=req.map_id,
                             rank_infos=[], my_rank_info=DungeonClearRankInfo()),
            correlation, note=f'clear rank info ack (map={req.map_id} page={req.page})',
        )

