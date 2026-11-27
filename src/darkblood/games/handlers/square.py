"""Town (square) play: tutorial, layers, NPCs, waypoints."""
import json
import struct

from darkblood.core.serialization.jser import event, strip_prefix
from darkblood.games.entities.character import layer_net_id, SQUARE_IDS
from darkblood.games.entities.items import Item, UPDATE_OWNER
from darkblood.games.network import results
from darkblood.games.network.messages import (
    BackToSquareAck,
    ClearTutorialAck,
    EnterMaptoolAck,
    FishingStartAck,
    FishingStartReq,
    FishingStopAck,
    GTargetListAck,
    LeaveLayerAck,
    LeaveSquareAck,
    NpcFirstMeetAck,
    QuestObjective,
    QuestUpdateNot,
    TargetState,
    WaypointData,
    WaypointInsertAck,
)

# Tutorial quest Q0882S01 (0x34c58e7c) objective mappings:
# Objective 0: QM788 (Wild Hog / ResourceNum 71, TargetValue = 2)
# Objective 1: QM789 (Black Hog / ResourceNum 72, TargetValue = 2)
TUTORIAL_HOG_OBJECTIVES = {
    # 71 Wild Hog variants (16npi4, etc.)
    0x5b3fec1c: 0, 0x5b3fec3d: 0, 0x5b42aa43: 0, 0x172c8965: 0, 0x1b371aa7: 0, 0x1f41abe9: 0,
    # 72 Black Hog variants (17bpi9, etc.)
    0x96926131: 1, 0x2f15f1e8: 1, 0x98e78a14: 1, 0x5b3fec7f: 1, 0x96951f9a: 1, 0x2f18b051: 1,
    0x98ea487d: 1, 0x04168f5d: 1, 0x0821209f: 1, 0x0c2bb1e1: 1, 0xf6ceaeaa: 1, 0x27c20c2c: 1,
}
TUTORIAL_QUEST_ID = 0x34c58e7c

from darkblood.games.dispatcher import packet_handler
from darkblood.games.handlers.base import BaseDomainService
from darkblood.player_management.characters import add_reward_items, gold_of, spend_gold
from darkblood.core.hashing import jhash
from darkblood.games.game_data.world import waypoint_info, portal_cost
from darkblood.games.world import square_uid, GameWorldManager
from darkblood.games.progression import refresh_stress, stress_changed_not
from darkblood import REPO_ROOT
from darkblood.games.game_data.client_dict import tutorial_rewards

_GTARGETS_CACHE = None


def _gtargets_for_layer(layer_id: int) -> list:
    """Return enabled TargetState entries for the town square of `layer_id`."""
    global _GTARGETS_CACHE
    if _GTARGETS_CACHE is None:
        _GTARGETS_CACHE = {}
        path = REPO_ROOT / 'assets' / 'gtargets.json'
        if path.is_file():
            data = json.loads(path.read_text(encoding='utf-8'))
            for square_name, uids in data.items():
                _GTARGETS_CACHE[jhash(square_name) & 0xFFFFFFFF] = [
                    TargetState(target_uid=int(uid), is_active=True, is_jackpot=False)
                    for uid in uids
                ]
    sq_hash = (int(layer_id) >> 32) & 0xFFFFFFFF
    return list(_GTARGETS_CACHE.get(sq_hash, ()))


class SquareHandlers(BaseDomainService):
    """Town (square) play: tutorial, layers, NPCs, waypoints."""

    @packet_handler(2082)
    async def handle_clear_tutorial(self, correlation: int, body: bytes):
        """Opcode 2082 (eEGS_CLEAR_TUTORIAL_REQ) -> 2083 (eEGS_CLEAR_TUTORIAL_ACK).

        Client handler: 0x0077EEB0.
        Marks tutorial quest sequence as finished on character record, unlocking full
        town access, NPC interactions, and dungeon gates.

        Body: i32 prefix + bool. The quest talk SQ0882S01c1 calls
        On_Tutorial_Exit(true) and the skip button sends 0 (live: ffffff7f 00),
        so the bool is read as "completed". The rewards come from
        tutorialreward.lua (CompleteLoad / SkipLoad) and are granted once.
        """
        completed = len(body) > 4 and body[4] != 0
        char_id = self.char_id
        char = self.store().get(self.account, char_id)
        items = []
        granted = 0
        if char:
            if not char.get('tutorial_cleared'):
                rewards = tutorial_rewards()['complete' if completed else 'skip']
                granted = len(add_reward_items(char, rewards))
            char['tutorial_cleared'] = True
            self.save_char()
            # 0x0077EEB0 applies this vector with 0x007FEC40 and switches
            # straight to town without a new 2007. Live: a knight that skipped
            # the tutorial showed no armour until relogging, so the whole
            # inventory (worn gear included) is resent, not only the rewards.
            items = [Item(owner=UPDATE_OWNER, **i) for i in char.get('items', [])]
        ack = ClearTutorialAck(elements=items)
        await self.reply(ack, correlation, note='clear tutorial ack (completed=%d, %d rewards, %d items)'
                                             % (completed, granted, len(items)))

    @packet_handler(2084)
    async def handle_clear_opening(self, correlation: int, body: bytes):
        """Opcode 2084 (eEGS_CLEAR_OPENING_NOT): Cinematic intro complete."""
        pass

    @packet_handler(2353)
    async def handle_tutorial_monster_dead(self, correlation: int, body: bytes):
        """Opcode 2353 (eEGS_TUTORIAL_MONSTER_DEAD_NOT).

        Client dispatcher: 0x00809eb0 (ReportDeathToServer) -> 0x00799e60.
        Body: 4-byte prefix 0x7FFFFFFF + u32 monster template hash.
        Updates active tutorial quest Q0882S01 objective kill counters and
        broadcasts opcode 2075 (eEGS_QUEST_UPDATE_NOT) to advance quest status.
        """
        body = strip_prefix(body)
        if len(body) < 4:
            return
        monster_hash = struct.unpack_from('<I', body, 0)[0]

        if monster_hash not in TUTORIAL_HOG_OBJECTIVES:
            return

        obj_idx = TUTORIAL_HOG_OBJECTIVES[monster_hash]
        char_id = self.char_id
        char = self.store().get(self.account, char_id)
        if not char:
            return

        active = char.setdefault('quests_active', {})
        q_key = str(TUTORIAL_QUEST_ID)
        if q_key not in active:
            uid = max([0] + [q.get('uid', 0) for q in active.values() if isinstance(q, dict)]) + 1
            active[q_key] = dict(uid=uid, tracked=True, counters=[0, 0])

        q_record = active[q_key]
        counters = q_record.setdefault('counters', [0, 0])
        while len(counters) < 2:
            counters.append(0)

        target = 2
        if counters[obj_idx] < target:
            counters[obj_idx] += 1
            self.save_char()

            update = QuestUpdateNot(updates=[QuestObjective(TUTORIAL_QUEST_ID, obj_idx, counters[obj_idx])])
            await self.send_msg(update, note=f'quest update not (Q0882S01 obj={obj_idx} count={counters[obj_idx]}/{target})')

    @packet_handler(2094)
    async def handle_npc_first_meet(self, correlation: int, body: bytes):
        """Opcode 2094 (eEGS_NPC_FIRST_MEET_REQ) -> 2095 (eEGS_NPC_FIRST_MEET_ACK).

        Client handler: 0x00752B60.
        Acknowledges dialogue greeting when a player interacts with an NPC for the first time.
        """
        npc_id = struct.unpack_from('<I', body, 4)[0] if len(body) >= 8 else 0
        ack = NpcFirstMeetAck(result=0, npc_id=npc_id)
        await self.reply(ack, correlation, note='npc first meet ack (npc %d)' % npc_id)

    @packet_handler(5045)
    async def handle_back_to_square(self, correlation: int, body: bytes):
        """Opcode 5045 (eERC_BACK_TO_SQUARE_REQ) -> 5046 (eERC_BACK_TO_SQUARE_ACK).

        Client handler: 0x007897F0.
        Transitions the player entity from a dungeon session back to the default town square.
        """
        # Leaving a party has its own request (5005). Back to square ends only the
        # solo room; a party survives the gate or a run and is open again. Leaving
        # it here sent 5036 for the host, and the member saw "all members left the
        # party" when the leader closed the dungeon gate (live 2026-11-21).
        self.session.dungeon.in_dungeon = False
        self.session.dungeon.dungeon_cleared = False
        room = self.session.dungeon.room
        party_members = []
        if room is not None and room.info.name == '_singleplay':
            await self.session.dungeon.leave_room()
        elif room is not None:
            room.started = False
            # In a party dungeon/gate, only the host sends 5045 when the result
            # timer expires or the gate is closed (live 2026-11-21); return all
            # other party members to town as well so nobody is left stranded.
            if room.host is self.session:
                party_members = [m for m in list(room.members) if m is not self.session]
                for member in party_members:
                    member.dungeon.in_dungeon = False
                    member.dungeon.dungeon_cleared = False
        # Return to the layer the player left town from: after GamePlay the
        # client places the unit by that layer's waypoint (0x008EC230).
        ack = BackToSquareAck(square_uid=_wire_square_uid(self.session.square_id), layer_net_id=self._town_layer(),
                              cur_ar=self._current_gold())
        await self.reply(ack, correlation, note='back to square ack')
        await self._sync_passive_stress()
        for member in party_members:
            try:
                m_ack = BackToSquareAck(
                    square_uid=_wire_square_uid(member.square_id),
                    layer_net_id=member.square._town_layer(),
                    cur_ar=member.square._current_gold(),
                ).encode()
                await member.transport.send_event(event(5046, m_ack),
                                                  note='back to square ack (party)')
                await member.square._sync_passive_stress()
            except (ConnectionError, OSError):
                pass

    async def _sync_passive_stress(self):
        """Apply passive town stress recovery (1/min) and daily reset, notifying client on change."""
        char = self.current_char()
        if char is not None and refresh_stress(char):
            self.save_char()
            await self.send_msg(stress_changed_not(char), note=f"stress recovery not ({char['stress']})")

    def _town_layer(self):
        char = self.current_char()
        stored = char.get('join_layer_net_id') if char else None
        return stored if stored is not None and _is_town_layer(stored) else layer_net_id()

    def _remember_layer(self, layer_id):
        """Keep the last town layer (5030) so 2007 and 5046 spawn the player there."""
        char = self.current_char()
        if char is None or not _is_town_layer(layer_id) or char.get('join_layer_net_id') == layer_id:
            return
        char['join_layer_net_id'] = layer_id
        self.save_char()

    def _current_gold(self):
        char = self.current_char()
        return gold_of(char)

    @packet_handler(5124)
    async def handle_get_gtarget_list(self, correlation: int, body: bytes):
        """Opcode 5124 (eERC_GTARGET_LIST_REQ) -> 5125 (eERC_GTARGET_LIST_ACK).

        Client handler: 0x00873490 -> 0x0085E150 -> 0x007F8CD0.
        Enables 3D interactive town GTargets (furnace ma2700, potion station ma2710,
        gathering nodes) on the current town square.
        """
        targets = _gtargets_for_layer(self._town_layer())
        await self.reply(GTargetListAck(result=0, targets=targets), correlation, note=f'gtarget list ack ({len(targets)})')
        # Sent once the town has loaded: show the players already there.
        await GameWorldManager.get().player_ready(self.session)

    @packet_handler(5030)
    async def handle_join_layer(self, correlation: int, body: bytes):
        """Opcode 5030 changes the town layer; positions travel via the relay."""

        layer_id = struct.unpack_from('<Q', body, 4)[0] if len(body) >= 12 else layer_net_id()
        use_waypoint = bool(body[12]) if len(body) >= 13 else False
        prev_layer = self._town_layer()
        if use_waypoint:
            char = self.current_char()
            src_wp = waypoint_info(prev_layer)
            dst_wp = waypoint_info(layer_id)
            if char is not None and src_wp and dst_wp and src_wp['id'] != dst_wp['id']:
                cost = portal_cost(src_wp['id'], dst_wp['id'], char.get('level', 1))
                if cost > 0:
                    if not spend_gold(char, cost):
                        refused = BackToSquareAck(
                            result=results.NOT_ENOUGH_AR,
                            square_uid=_wire_square_uid(self.session.square_id),
                            layer_net_id=prev_layer,
                            cur_ar=gold_of(char),
                        )
                        await self.transport.send_event(event(5031, refused.encode(), correlation),
                                                        note='waypoint travel refused (not enough AR)')
                        return
                    self.save_char()
        self._remember_layer(layer_id)
        world = GameWorldManager.get()
        player, previous_layer = world.change_layer(self.session, layer_id)
        ack = BackToSquareAck(
            square_uid=_wire_square_uid(self.session.square_id),
            layer_net_id=layer_id,
            use_waypoint=use_waypoint,
            cur_ar=self._current_gold(),
        ).encode()
        await self.transport.send_event(event(5031, ack, correlation),
                                        note='join layer ack (%d, wp=%d)' % (layer_id, int(use_waypoint)))
        await self._sync_passive_stress()
        if previous_layer is not None:
            if previous_layer != layer_id:
                await world.broadcast_layer_leave(player, previous_layer)
            await world.broadcast_player_spawn(player)

    @packet_handler(2016)
    async def handle_enter_maptool(self, correlation: int, body: bytes):
        """Opcode 2016 (eEGS_ENTER_MAPTOOL_REQ) -> 2017 (eEGS_ENTER_MAPTOOL_ACK).

        Client handler: 0x00757D20.
        Triggers scene transition.
        """
        await self.reply(EnterMaptoolAck(), correlation,
                         note='enter maptool ack')

    @packet_handler(2344)
    async def handle_waypoint_insert(self, correlation: int, body: bytes):
        """Opcode 2344 (eEGS_WAYPOINT_INSERT_REQ) -> 2345 (eEGS_WAYPOINT_INSERT_ACK).

        Client handler: 0x0064AE00 (JAppPageSquarePortal::OneEGS_WAYPOINT_INSERT_ACK).
        Registers visited portal waypoint in the world map. jData (0x00A49700) MUST carry
        layer_net_id, localization name (@LayerName_*), waypoint_id hash (for DictSquarePortal::GetCost),
        and destination (x, y) from the town map file.
        """
        layer = struct.unpack_from('<Q', body, 4)[0] if len(body) >= 12 else layer_net_id()
        char = self.current_char()
        if char is not None:
            wps = char.setdefault('waypoints', [])
            if layer not in wps:
                wps.append(layer)
                self.save_char()
        ack = WaypointInsertAck(
            result=0,
            layer_net_id=layer,
            waypoint=waypoint_data(layer),
        )
        await self.reply(ack, correlation, note='waypoint insert ack (%016x)' % layer)

    @packet_handler(5037)
    async def handle_leave_layer(self, correlation: int, body: bytes):
        """Opcode 5037 (eERC_LEAVE_LAYER_REQ) -> 5038 (eERC_LEAVE_LAYER_ACK).

        Sent by the in-game menu's "Select Character": OnBtn_SelectChar
        (0x00564490) opens MB_Square_To_SelChar, whose OnOK runs
        SquareToSelChar (0x006FB360). That sends 5037 (0x007ADA30), waits
        for 5038, then sends 2008 (0x00788DA0) and waits for 2009 before it
        switches to character select. Without 5038 the client timed out and
        dropped the connection (live, 2026-11-16 22:43).

        Client handler 0x007895C0 reads only the u32 result (0x00A1EA20(0));
        0 continues, any other value opens an error box. The player leaves
        the town, so it is removed from the world presence list.
        """
        await self.session.dungeon.leave_room()
        if self.session.active_char_id:
            await GameWorldManager.get().remove_session_player(self.session)
        await self.reply(LeaveLayerAck(), correlation,
                         note='leave layer ack')

    @packet_handler(5032)
    async def handle_leave_square(self, correlation: int, body: bytes):
        """Opcode 5032 (eERC_LEAVE_SQUARE_REQ) -> 5033 (eERC_LEAVE_SQUARE_ACK).

        Sent when going back from character select to the server list (live,
        empty body, 2026-11-16 23:02). Handler 0x00757960 reads only a u32
        result: 0 leaves the channel and clears the stored square (+0xB0/+0xB4
        of state 8); other values open an error box.
        """
        await self.session.dungeon.leave_room()
        if self.session.active_char_id:
            await GameWorldManager.get().remove_session_player(self.session)
        await self.reply(LeaveSquareAck(), correlation,
                         note='leave square ack')

    # =========================================================================
    # Fishing System Handlers (2523-2526)
    # =========================================================================

    @packet_handler(2523)
    async def handle_fishing_start(self, correlation: int, body: bytes):
        """Opcode 2523 (eEGS_FISHING_START_REQ, 0x007A1FF0) -> 2524 (0x0075B0B0)."""
        req = FishingStartReq.decode(body)
        self.transport.record('fishing-start-req', body, hole=req.fishing_hole_id,
                              rod=req.rod_item_id, bait=req.bait_item_id)
        await self.reply(FishingStartAck(result=0), correlation,
                         note=f'fishing start ack ({req.fishing_hole_id})')

    @packet_handler(2525)
    async def handle_fishing_stop(self, correlation: int, body: bytes):
        """Opcode 2525 (eEGS_FISHING_STOP_REQ, 0x007A21E0) -> 2526 (0x0075B1C0)."""
        self.transport.record('fishing-stop-req', body)
        await self.reply(FishingStopAck(result=0), correlation, note='fishing stop ack')


def _is_town_layer(layer_id: int) -> bool:
    """High dword must be a loaded SquareID hash (CanEnter 0x006FA540)."""
    return (layer_id >> 32) in {jhash(sq) for sq in SQUARE_IDS}


def waypoint_data(layer_id: int):
    """Build WaypointData (0x00A49700) for a town layer from assets/waypoints.json."""
    info = waypoint_info(layer_id)
    if info is not None:
        return WaypointData(
            layer_net_id=layer_id,
            name=info['name'],
            waypoint_id=info['id_hash'],
            x=info['x'],
            y=info['y'],
        )
    return WaypointData(
        layer_net_id=layer_id,
        name=_waypoint_label(layer_id),
        waypoint_id=0,
        x=0,
        y=0,
    )


def _waypoint_label(layer_id: int) -> str:
    """Human-readable label for a town waypoint (high dword = jhash(SquareID), low dword = layer)."""
    sq_hash = layer_id >> 32
    layer_idx = layer_id & 0xFFFFFFFF
    names = {
        jhash('Act1'): 'Elwood Village',
        jhash('Act2'): 'Watervale Village',
        jhash('Act4'): 'Durion Castle',
        jhash('ArenaLobby'): 'Arena',
    }
    for sq in SQUARE_IDS:
        names.setdefault(jhash(sq), sq)
    base = names.get(sq_hash, 'Town')
    return f'{base} #{layer_idx}' if layer_idx else base


def _wire_square_uid(square_id: int) -> int:
    return square_uid(square_id)
