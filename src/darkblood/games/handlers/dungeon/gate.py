"""Dungeon gate: gate selection (5043/5044), map code (5009/5010), reselection (5052/5053) and clear history."""
from darkblood.core.serialization.jser import WireError, read_varuint
from darkblood.games.dispatcher import packet_handler
from darkblood.games.network.messages import (
    AgainSelectDungeonAck,
    ChangeMapCodeAck,
    DungeonHistory,
    SelectDungeonAck,
)
from darkblood.games.game_data.client_dict import gate_dungeons, dungeon_map_copies, dungeon_maps


class DungeonGateHandlers:
    @packet_handler(5043)
    async def handle_select_dungeon(self, correlation, body):
        # eERC_SELECT_DUNGEON_REQ (sender 0x7AC1C0), observed body:
        # ffffff7f + J-wstring gate id ("Act1_G1") -> 5044.
        gate = ''
        try:
            length, offset = read_varuint(body, 4)
            gate = body[offset:offset + length].decode('utf-16le')
        except (WireError, UnicodeDecodeError):
            pass
        char = self.current_char() or {}
        self.gate_id = gate
        ack = self._select_dungeon_ack(gate, char)
        await self.reply(ack, correlation,
                         note=f'select dungeon ack ({gate}, history {ack.dun_history}, '
                              f'{len(ack.quest_ids)} active quests)')
        # The whole party enters the gate: entering it (0x006C7920) sends P2P 0x5F
        # and waits up to 15 s (0x005C6D40(2, 15000)) until every room member has
        # answered with its own 0x5F (0x009695F0 -> 0x005C4E40). Members only enter
        # through 5044, whose global handler 0x007702E0 changes the state itself;
        # without it the leader sat 10-15 s on a black screen (live 2026-11-21).
        room = self.room
        if room is not None and room.host is self.session and room.info.name != '_singleplay':
            for member, record in list(room.members.items()):
                if member is self.session:
                    continue
                await self.send_to([member], self._select_dungeon_ack(gate, record), f'select dungeon (party gate {gate})')

    @staticmethod
    def _dungeon_history(char, dungeons=None):
        """dungeon id -> DungeonHistory for cleared dungeons (optionally only `dungeons`).

        Only cleared dungeons get an entry; the others default to Normal. Entries are
        written by _record_dungeon_clear as {'map': code, 'diff': difficulty}.
        """
        return {dungeon: DungeonHistory(rec['map'], rec['diff'], 1)
                for dungeon, rec in char.get('dungeon_history', {}).items()
                if isinstance(rec, dict) and 'map' in rec and (dungeons is None or dungeon in dungeons)}

    @staticmethod
    def _active_quest_ids(char):
        """Sorted unique u32 ids of the character's active quests."""
        ids = set()
        for quest_id in char.get('quests_active', {}):
            try:
                ids.add(int(quest_id) & 0xFFFFFFFF)
            except ValueError:
                continue
        return sorted(ids)

    def _select_dungeon_ack(self, gate, char):
        return SelectDungeonAck(gate_id=gate,
                                dun_history=self._dungeon_history(char, set(gate_dungeons().get(gate, []))),
                                quest_ids=self._active_quest_ids(char))

    def _record_dungeon_clear(self, char, map_code):
        """Remember the highest cleared difficulty per dungeon (5044 history).

        34 quest maps (QuestLink) are copies of their dungeon's regular map at that
        Difficult (e.g. Act1_G1_A16 = Act1_G1_A10: same file, monsters and stats;
        only gold, PlayOrder and QuestLink differ). Such a clear counts as the
        regular map, which the history keeps: the gate auto-selects the history
        map (0x006D1120). The other quest maps have their own content (own file,
        or e.g. Act1_G1_A15 at level 35-37 although Difficult is 2) and do not
        advance the dungeon's difficulty.
        """
        map_code = dungeon_map_copies().get(map_code, map_code)
        info = dungeon_maps().get(map_code)
        if info is None or info[2]:
            return
        dungeon, diff, _ = info
        history = char.setdefault('dungeon_history', {})
        record = history.get(dungeon)
        if record is None or diff >= record['diff']:
            history[dungeon] = {'map': map_code, 'diff': diff}

    @packet_handler(5009)
    async def handle_change_map_code(self, correlation, body):
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
        self.map_code = code
        room = self.room
        # The members sit in the same gate (5044 above): show the host's choice.
        sync = room is not None and room.host is self.session and room.info.name != '_singleplay'
        await self._reply_and_sync(ChangeMapCodeAck(map_code=code, flag=flag), correlation,
                                   'change mapcode ack (%s)' % code, 'change mapcode (party gate %s)' % code, sync)

    @packet_handler(5052)
    async def handle_again_select_dungeon(self, correlation, body):
        # eERC_AGAIN_SELECT_DUNGEON_REQ (0x007AC480) -> 5053 eERC_AGAIN_SELECT_DUNGEON_ACK (0x00770A80).
        char = self.current_char() or {}
        gate_id = self.gate_id or 'Act1_G1'
        history = self._dungeon_history(char)
        active_quests = self._active_quest_ids(char)
        await self.reply(
            AgainSelectDungeonAck(result=0, history=history, min_citadel_history=[],
                                  gate_id=gate_id, active_quests=active_quests),
            correlation, note=f'again select dungeon ack (gate={gate_id}, history={len(history)})',
        )
