"""Dungeon entry validation, Citadel/daily limit enforcement, stress cost, and start-game fan-out."""
import random
import time

from darkblood.games.network import results
from darkblood.core.serialization.jser import WireError, event
from darkblood.games.dispatcher import packet_handler
from darkblood.games.entities.items import DEPOT_CONTAINER, EQUIPPED, Item, UPDATE_OWNER
from darkblood.games.game_data.world import dungeon_entry_rule
from darkblood.games.handlers.pets.pets import consume_pet_energy
from darkblood.games.handlers.skills import learned_skill_map
from darkblood.games.network.messages.dungeon import (
    DailyDunEnterCountUpdateNot,
    FailDungeonEnterItemNot,
    FailDungeonEnterLimitNot,
    StartGameAck,
    StartGameReq,
)
from darkblood.games.network.messages.guild import CitadelPlayCountUpdateNot
from darkblood.games.network.messages.inventory import DragItemAck
from darkblood.games.progression import (
    STRESS_PER_DUNGEON_ROOM,
    consume_stress,
    refresh_dungeon_entry_limits,
    stress_changed_not,
)


class DungeonEntryHandlers:
    @packet_handler(StartGameReq)
    async def handle_start_game(self, correlation, body):
        try:
            request = StartGameReq.decode(body)
            if not request.map_code or '\x00' in request.map_code:
                raise WireError('Missing or invalid dungeon map code')
        except (WireError, UnicodeDecodeError):
            # The success path assumes the map code resolves to a client property.
            ack = StartGameAck(result=results.INVALID_STATE)
        else:
            room = self.room
            participants = [self.session]
            if room is not None and room.info.name != '_singleplay':
                # Guests enter via the host's 5014. An unfinished start must keep
                # its seed, admission costs, and accumulated combat state.
                if room.host is not self.session:
                    await self.reply(StartGameAck(result=results.INVALID_STATE), correlation,
                                     note='party start requires host')
                    return
                if room.started and self._finish_game_reply is None:
                    await self.reply(StartGameAck(result=results.ALREADY_PLAY_GAME), correlation,
                                     note='party run already started')
                    return
                participants = [m for m in room.members if m.dungeon.room is room]
            entry_err = await self._validate_dungeon_entry(request.map_code, participants)
            if entry_err is not None:
                fail_opcode, fail_uid = entry_err
                await self._notify_dungeon_entry_failure(participants, fail_opcode, fail_uid)
                # 0x007880A0 skips duplicate chat output specifically for 0x8A (138, item) and 0x8B (139, limit)
                # because 5136/5222 already displayed the error and re-enabled the gate UI.
                ack = StartGameAck(result=138 if fail_opcode == 5136 else 139)
            else:
                await self._consume_dungeon_entry(request.map_code, participants)
                ack = self._start_game_ack(request.map_code, participants)
                self.map_code = request.map_code
                self._reset_dungeon_stats()
                if self.room is not None and self.room.host is self.session:
                    self.room.started = True
                    self.room.dead.clear()
                    self.room.floor_drops.clear()
                    self.room.floor_gold.clear()
        await self.reply(ack, correlation, note='start game ack')
        if ack.result == 0:
            self.in_dungeon = True
            self.dungeon_cleared = False
            await self._consume_session_stress(self.session)
            await self._consume_pet_dungeon_entry_energy(self.session)
        room = self.room
        if ack.result == 0 and room is not None and room.host is self.session and room.info.name != '_singleplay':
            # Shared dungeon, step 1: the members sit in the same gate (5044 at the
            # host's 5043), whose dispatcher handles 5014 (0x007880A0). Start them on
            # the host's map so all clients load it and meet in its relay group.
            for member in list(room.members):
                if member is self.session or member.dungeon.room is not room:
                    continue
                member.dungeon.map_code = request.map_code
                member.dungeon.in_dungeon = True
                member.dungeon.dungeon_cleared = False
                member.dungeon._reset_dungeon_stats()
                try:
                    await member.transport.send_event(
                        event(5014, ack.encode()),
                        note='start game (party, %s)' % request.map_code,
                    )
                    await self._consume_session_stress(member)
                    await self._consume_pet_dungeon_entry_energy(member)
                except (ConnectionError, OSError):
                    pass

    @staticmethod
    async def _consume_pet_dungeon_entry_energy(member):
        """Consume 1 Energy when entering a dungeon with a summoned pet and arm the 30s drain timer."""
        char = member.dungeon.current_char()
        if char is not None and char.get('summoned_pet'):
            if await consume_pet_energy(member, char, 1):
                member.dungeon.save_char()
            member.pets.pet_energy_last_tick = time.time() if char.get('summoned_pet') else None

    @staticmethod
    def _start_game_ack(map_code, participants):
        """One 5014 for every participant: each client skips its own UID in peer_skills.

        A solo run keeps the live-verified reply (zero count and seed, empty maps).
        """
        if len(participants) < 2:
            return StartGameAck(map_code=map_code)
        peer_skills = {}
        for member in participants:
            char = member.dungeon.current_char()
            if isinstance(char, dict) and 'id' in char:
                peer_skills[int(char['id'])] = learned_skill_map(
                    char.get('skills', {}), char.get('skill_speeches', {}),
                    char.get('locked_skills', []), char.get('skill_show_cooltime', []))
        return StartGameAck(map_code=map_code, player_count=len(participants),
                            rand_seed=random.getrandbits(31), peer_skills=peer_skills)

    async def _validate_dungeon_entry(self, map_code: str, participants):
        """Enforce Fortress/Special dungeon entry limits and required entry items (#22).

        Returns None when all participants may enter, or (fail_opcode, fail_char_uid)
        where fail_opcode is 5222 (FailDungeonEnterLimitNot) or 5136 (FailDungeonEnterItemNot).
        """
        rule = dungeon_entry_rule(map_code)
        if not rule:
            return None

        for member in participants:
            char = member.dungeon.current_char()
            if char is None:
                continue
            if refresh_dungeon_entry_limits(char):
                member.dungeon.save_char()
            cid = int(member.active_char_id or char.get('id', 0))

            if rule.get('is_citadel') and int(char.get('citadel_play_count', 0)) <= 0:
                return (5222, cid)

            limit = int(rule.get('enter_limit', 0))
            if limit > 0:
                used = int(char.get('daily_dun_enter_counts', {}).get(map_code, 0))
                if used >= limit:
                    return (5222, cid)

            req_item = rule.get('enter_item_id') or ''
            req_amt = int(rule.get('enter_item_amount', 0))
            if req_item and req_amt > 0:
                owned = sum(
                    int(it.get('count', 1))
                    for it in char.get('items', [])
                    if it.get('code') == req_item and it.get('container') not in (EQUIPPED, DEPOT_CONTAINER)
                )
                if owned < req_amt:
                    return (5136, cid)
        return None

    async def _notify_dungeon_entry_failure(self, participants, fail_opcode: int, fail_char_uid: int):
        msg = (
            FailDungeonEnterItemNot(fail_char_uid=fail_char_uid)
            if fail_opcode == 5136
            else FailDungeonEnterLimitNot(fail_char_uid=fail_char_uid)
        )
        await self.send_to(participants, msg, f'dungeon entry fail {fail_opcode} (char={fail_char_uid})')

    async def _consume_dungeon_entry(self, map_code: str, participants):
        """Decrement Citadel/daily entry counts and consume required entry items on dungeon start."""
        rule = dungeon_entry_rule(map_code)
        if not rule:
            return

        for member in participants:
            char = member.dungeon.current_char()
            if char is None:
                continue
            changed = False

            if rule.get('is_citadel'):
                remain = max(0, int(char.get('citadel_play_count', 0)) - 1)
                char['citadel_play_count'] = remain
                changed = True
                await self.send_to([member], CitadelPlayCountUpdateNot(remain_play_count=remain),
                                   f'citadel play count update ({remain})')

            if int(rule.get('enter_limit', 0)) > 0:
                counts = char.setdefault('daily_dun_enter_counts', {})
                counts[map_code] = int(counts.get(map_code, 0)) + 1
                changed = True
                await self.send_to([member], DailyDunEnterCountUpdateNot(
                    enter_counts={str(k): int(v) for k, v in counts.items()}),
                    f'daily dun enter count ({map_code}={counts[map_code]})')

            req_item = rule.get('enter_item_id') or ''
            req_amt = int(rule.get('enter_item_amount', 0))
            if req_item and req_amt > 0:
                items = char.get('items', [])
                remaining_to_take = req_amt
                wire_updates = []
                for it in list(items):
                    if remaining_to_take <= 0:
                        break
                    if it.get('code') != req_item or it.get('container') in (EQUIPPED, DEPOT_CONTAINER):
                        continue
                    stack = int(it.get('count', 1))
                    if stack <= remaining_to_take:
                        remaining_to_take -= stack
                        items.remove(it)
                        wire_updates.append(Item(
                            owner=UPDATE_OWNER, uid=0, code='',
                            container=it.get('container', 1), slot=it.get('slot', 0), count=0,
                        ))
                    else:
                        it['count'] = stack - remaining_to_take
                        remaining_to_take = 0
                        wire_updates.append(Item(owner=UPDATE_OWNER, **it))
                if wire_updates:
                    changed = True
                    await self.send_to([member], DragItemAck(result=0, items=wire_updates),
                                       f'consume dungeon entry item ({req_item} x{req_amt})')

            if changed:
                member.dungeon.save_char()

    def _reset_dungeon_stats(self):
        self.dungeon_kill_count = 0
        self.dungeon_score = 0
        self.dungeon_exp = 0
        self.visited_dungeon_layers = set()
        self._finish_game_reply = None
        self.reward_card = None
        self.reward_cards_claimed = set()

    async def _consume_session_stress(self, session, amount=None):
        char = session.dungeon.current_char()
        if char is None:
            return
        pts = STRESS_PER_DUNGEON_ROOM if amount is None else amount
        if consume_stress(char, pts):
            session.dungeon.save_char()
            await session.transport.send_event(
                event(2023, stress_changed_not(char).encode()),
                note=f"stress changed not ({char['stress']})",
            )
