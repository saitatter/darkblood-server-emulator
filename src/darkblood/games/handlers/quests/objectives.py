"""Quest objective counters: item collection (MissionType 1) and NPC missions (2113), reported with 2075."""
from darkblood.games.dispatcher import packet_handler
from darkblood.games.game_data.client_dict import (
    quest_item_objectives,
    quest_mission_counts,
    quest_mission_objectives,
)
from darkblood.games.handlers.quests.wire import parse_mission_id
from darkblood.games.network.messages import QuestObjective, QuestUpdateMissionAck, QuestUpdateNot


def take_quest_items(char, quest_id):
    """Remove the items a collection quest asked for (MissionType 1 targets) from the bags."""
    for item_code, q_list in quest_item_objectives().items():
        for target_qid, _, target_val in q_list:
            if target_qid != quest_id:
                continue
            remaining, kept = target_val, []
            for item in char.get('items', []):
                if item.get('code') == item_code and remaining > 0:
                    count = item.get('count', 1)
                    if count <= remaining:
                        remaining -= count
                        continue
                    item['count'] = count - remaining
                    remaining = 0
                kept.append(item)
            char['items'] = kept


class QuestObjectiveHandlers:
    async def check_quest_item_objectives(self, char=None):
        """Check active quests for item collection objectives (MissionType 1).

        Compares inventory quantities against quest targets, updates active quest
        objective counters, saves to character store, and dispatches Opcode 2075
        (eEGS_QUEST_UPDATE_NOT) for changed counters.
        """
        if char is None:
            char = self.current_char()
        if not char:
            return
        active = char.get('quests_active', {})
        if not active:
            return
        item_counts = {}
        for it in char.get('items', []):
            code = it.get('code')
            cnt = it.get('count', 1)
            item_counts[code] = item_counts.get(code, 0) + cnt

        obj_map = quest_item_objectives()
        mission_counts = quest_mission_counts()
        updates = []
        for q_str, record in active.items():
            try:
                qid = int(q_str)
            except ValueError:
                continue
            counters = record.setdefault('counters', [])
            needed = mission_counts.get(qid, 0)
            while len(counters) < needed:
                counters.append(0)
            for item_code, q_list in obj_map.items():
                cur_count = item_counts.get(item_code, 0)
                for target_qid, obj_idx, target_val in q_list:
                    if target_qid == qid:
                        while len(counters) <= obj_idx:
                            counters.append(0)
                        new_val = min(target_val, cur_count)
                        if counters[obj_idx] != new_val:
                            counters[obj_idx] = new_val
                            updates.append(QuestObjective(qid, obj_idx, new_val))

        if updates:
            self.save_char()
            await self.send_msg(QuestUpdateNot(updates=updates), note=f'quest update not (item objectives: {updates})')

    @packet_handler(2113)
    async def handle_quest_update_mission(self, correlation: int, body: bytes):
        """Opcode 2113 (eEGS_QUEST_UPDATE_MISSION_REQ) -> 2114 (eEGS_QUEST_UPDATE_MISSION_ACK).

        Observed body: 0x7FFFFFFF prefix + J-wstring mission id ("QM807",
        MissionType 5, sent after meeting the NPC). The ack (JAppPageTalkBox
        case 0x00659F00 -> 0x006481E0) reads only u32 result. Progress is
        reported like kill counters: 2075 with (quest, objective, count).
        """
        mission = parse_mission_id(body)
        char = self.current_char()
        active = char.get('quests_active', {}) if char else {}
        updates = []
        for q_hash, idx, target in quest_mission_objectives().get(mission, []):
            record = active.get(str(q_hash))
            if record is None:
                continue
            counters = record.setdefault('counters', [])
            while len(counters) <= idx:
                counters.append(0)
            counters[idx] = target
            updates.append(QuestObjective(q_hash, idx, target))
        if updates:
            self.save_char()
            await self.send_msg(QuestUpdateNot(updates=updates), note='quest update not (mission %s: %s)' % (mission, updates))
        await self.reply(QuestUpdateMissionAck(), correlation,
                         note='quest update mission ack (%s, %d quests)' % (mission, len(updates)))
