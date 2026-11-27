"""Arena: Extended arena room, square, team, league stat and random matching handlers."""
from __future__ import annotations

from darkblood.games.network.messages import (
    ArenaBanishUserAck,
    ArenaBanishUserReq,
    ArenaChangeRoomCharInfoAck,
    ArenaChangeRoomCharInfoReq,
    ArenaChangeRoomHostAck,
    ArenaChangeRoomHostReq,
    ArenaChangeSlotCharInfoAck,
    ArenaChangeTeamInfoAck,
    ArenaChangeTeamInfoReq,
    ArenaJoinLayerAck,
    ArenaJoinLayerReq,
    ArenaRandomMatchingRequestAck,
    ArenaReadyGameAck,
    ArenaReadyGameReq,
    ArenaStartGameAck,
    ArenaTeamBanishAck,
    ArenaTeamBanishReq,
    ArenaTeamChangeHostAck,
    ArenaTeamChangeHostReq,
    LeagueSeasonArenaCharStatInitAck,
    LeagueSeasonArenaCharStatUpdateAck,
    LeagueSeasonArenaCharStatUpdateReq,
)
from darkblood.games.dispatcher import packet_handler
from darkblood.games.network import results
from darkblood.player_management.characters import gold_of


class ArenaExtendedHandlers:
    # Extended Arena Room, Square, Team, League CharStat & Random Matching

    @packet_handler(5142)
    async def handle_arena_join_layer(self, correlation: int, body: bytes):
        req = ArenaJoinLayerReq.decode(body)
        await self.reply(
            ArenaJoinLayerAck(result=0, arena_square_uid=1, join_layer_net_id=req.layer_net_id, join_square_uid=1),
            correlation, note=f'arena join layer ack (layer={req.layer_net_id})',
        )

    @packet_handler(5163)
    async def handle_arena_banish_user(self, correlation: int, body: bytes):
        req = ArenaBanishUserReq.decode(body)
        await self.reply(ArenaBanishUserAck(result=0), correlation,
                         note=f'arena banish user ack (target={req.target_uid})')

    @packet_handler(5168)
    async def handle_arena_change_room_host(self, correlation: int, body: bytes):
        req = ArenaChangeRoomHostReq.decode(body)
        await self.reply(ArenaChangeRoomHostAck(result=0, new_host_uid=req.new_host_uid), correlation,
                         note=f'arena change room host ack (host={req.new_host_uid})')

    @packet_handler(5172)
    async def handle_arena_start_game(self, correlation: int, body: bytes):
        await self.reply(ArenaStartGameAck(result=0, rand_sync=1, played_map_id=1), correlation,
                         note='arena start game ack')

    @packet_handler(5182)
    async def handle_arena_ready_game(self, correlation: int, body: bytes):
        req = ArenaReadyGameReq.decode(body)
        char_uid, _, _, _ = self._get_active_char_info()
        await self.reply(ArenaReadyGameAck(result=0, char_uid=char_uid, is_ready=req.is_ready), correlation,
                         note=f'arena ready game ack (ready={req.is_ready})')

    @packet_handler(5202)
    async def handle_arena_random_matching_request(self, correlation: int, body: bytes):
        await self.reply(ArenaRandomMatchingRequestAck(result=0), correlation,
                         note='arena random matching request ack')

    @packet_handler(5265)
    async def handle_arena_change_room_char_info(self, correlation: int, body: bytes):
        req = ArenaChangeRoomCharInfoReq.decode(body)
        char_uid, _, _, _ = self._get_active_char_info()
        await self.reply(
            ArenaChangeRoomCharInfoAck(result=0, char_uid=char_uid, team_id=req.team_id, is_ready=req.is_ready),
            correlation, note=f'arena change room char info ack (team={req.team_id})',
        )

    @packet_handler(5267)
    async def handle_arena_change_slot_char_info(self, correlation: int, body: bytes):
        await self.reply(ArenaChangeSlotCharInfoAck(result=0), correlation,
                         note='arena change slot char info ack')

    @packet_handler(5282)
    async def handle_arena_team_banish(self, correlation: int, body: bytes):
        req = ArenaTeamBanishReq.decode(body)
        await self.reply(ArenaTeamBanishAck(result=0), correlation,
                         note=f'arena team banish ack (target={req.target_uid})')

    @packet_handler(5286)
    async def handle_arena_team_change_host(self, correlation: int, body: bytes):
        req = ArenaTeamChangeHostReq.decode(body)
        await self.reply(ArenaTeamChangeHostAck(result=0, new_host_uid=req.new_host_uid), correlation,
                         note=f'arena team change host ack (host={req.new_host_uid})')

    @packet_handler(5301)
    async def handle_arena_change_team_info(self, correlation: int, body: bytes):
        req = ArenaChangeTeamInfoReq.decode(body)
        team = self.arena.teams.get(self._current_arena_team_id)
        char_uid, _, _, _ = self._get_active_char_info()
        if team is None or not char_uid or team.leader_uid != char_uid:
            await self.reply(ArenaChangeTeamInfoAck(result=results.INVALID_STATE), correlation,
                             note='arena change team info refused')
            return

        team.team_type = req.team_type
        team.team_name = req.team_name
        await self.reply(ArenaChangeTeamInfoAck(result=0, team_type=team.team_type, team_name=team.team_name),
                         correlation, note=f'arena change team info ack ({req.team_name})')

    @packet_handler(2556)
    async def handle_league_season_arena_charstat_update(self, correlation: int, body: bytes):
        req = LeagueSeasonArenaCharStatUpdateReq.decode(body)
        char = self.current_char()
        if char is not None:
            char['league_season_stat'] = dict(req.season_stat)
            self.save_char()
        await self.reply(LeagueSeasonArenaCharStatUpdateAck(result=0, season_stat=req.season_stat),
                         correlation, note='league season arena charstat update ack')

    @packet_handler(2561)
    async def handle_league_season_arena_charstat_init(self, correlation: int, body: bytes):
        char = self.current_char()
        cur_ar = gold_of(char)
        if char is not None:
            char['league_season_stat'] = {}
            self.save_char()
        await self.reply(LeagueSeasonArenaCharStatInitAck(result=0, cur_ar=cur_ar, season_init_stat_cnt=1),
                         correlation, note='league season arena charstat init ack')
