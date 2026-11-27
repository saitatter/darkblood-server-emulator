"""Town GTargets and life skills: target list (5124/5125/5126), gathering and crafting (2177/2496) and fishing (2523-2529)."""
import asyncio

from darkblood.core import options
from darkblood.core.hashing import jhash
from darkblood.games.dispatcher import packet_handler
from darkblood.games.entities.items import DEPOT_CONTAINER, EQUIPPED, UPDATE_OWNER, Item
from darkblood.games.game_data.life_skills import (
    FISHING_PROFICIENCY,
    bait_time_reduction,
    fishing_proficiency_gain,
    fish_group,
    fishing_kairo,
    gathering_kairo,
    making_kairo,
    max_proficiency,
    target_kinds,
)
from darkblood.games.handlers.base import BaseDomainService
from darkblood.games.handlers.skills import PROFICIENCY_TO_LIFE_SKILL, proficiency_values_for_char
from darkblood.games.life_targets import square_of_layer
from darkblood.games.network import results
from darkblood.games.network.messages import (
    ActKairoAck,
    AddedItemNotice,
    ChangeGTargetNot,
    FishingFailedNot,
    FishingProficiencyNot,
    FishingResultNot,
    FishingStartAck,
    FishingStartReq,
    FishingStopAck,
    GTargetListAck,
    KairoResult,
)
from darkblood.games.world import GameWorldManager
from darkblood.player_management.characters import (
    add_gold,
    add_reward_items,
    bag_item_count,
    free_cells,
    gold_of,
    slots_needed,
    take_bag_items,
)

GATHERING_COLLECTED = 5      # JERI_GATHERING_00 "This item has been collected by another player."
FISHING_NEED_BAIT = 417      # JERI_FISHING_04 "You need more bait."
FISHING_NOTHING = 418        # JERI_FISHING_05 "You didn't catch anything."

# Scale applied to the cast time (MaxTime - bait AdjValue); tests shorten it.
FISHING_TIME_SCALE = 1.0


class LifeSkillHandlers(BaseDomainService):
    """Town GTargets (fishing holes, gathering nodes, crafting stations) and their life skills."""

    def __init__(self, session):
        super().__init__(session)
        self._fishing_task = None

    @property
    def targets(self):
        """Server-wide GTarget state (LifeTargetState) owned by the BootstrapServer."""
        return self.transport.server.life_targets

    @property
    def rng(self):
        return self.targets.rng

    def _square(self):
        return square_of_layer(self.session.square._town_layer())

    # ------------------------------------------------------------------ targets

    @packet_handler(5124)
    async def handle_get_gtarget_list(self, correlation: int, body: bytes):
        """Opcode 5124 (eERC_GTARGET_LIST_REQ) -> 5125 (eERC_GTARGET_LIST_ACK).

        Client handler: 0x00873490 -> 0x0085E150 -> JGTarget::Update 0x007F8CD0.
        Sent once a town has loaded: every fishing hole, gathering node and crafting
        station of the square with its active flag.
        """
        square = self._square()
        targets = self.targets.states(square) if square else []
        await self.reply(GTargetListAck(result=0, targets=targets), correlation,
                         note=f'gtarget list ack ({square}: {sum(t.is_active for t in targets)}/{len(targets)} active)')
        # Sent once the town has loaded: show the players already there.
        await GameWorldManager.get().player_ready(self.session)

    async def broadcast_targets(self, square, states):
        """5126 eERC_CHANGE_GTARGET_NOT to every player in the town `square`."""
        if not states:
            return
        sessions = [p.session for p in list(GameWorldManager.get().players.values())
                    if p.session is not None and square_of_layer(p.layer_id) == square]
        await self.send_to(sessions, ChangeGTargetNot(result=0, targets=states),
                           note=f'change gtarget not ({square}: {len(states)})')

    async def tick_regeneration(self, now=None):
        """Return depleted gathering nodes whose regeneration is due and announce them."""
        for square, states in self.targets.regenerate(now).items():
            await self.broadcast_targets(square, states)

    # ---------------------------------------------------------------- gathering

    def _skill_level(self, char, skill_index):
        return int((char.get('skills') or {}).get(str(skill_index), 0))

    def _raise_proficiency(self, char, proficiency_type, amount):
        """Add proficiency, capped by the skill's MaxProficiency; returns (changed, new value).

        `amount` is scaled by the launcher's life_proficiency_rate option (1 = table value).
        """
        amount = amount * options.number('life_proficiency_rate')
        values = proficiency_values_for_char(char)
        skill = PROFICIENCY_TO_LIFE_SKILL.get(proficiency_type)
        cap = max_proficiency(skill, self._skill_level(char, skill)) if skill else 0.0
        new = min(cap, values[proficiency_type] + amount)
        if new <= values[proficiency_type]:
            return False, values[proficiency_type]
        values[proficiency_type] = new
        char['proficiencies'] = values
        return True, new

    async def handle_gathering(self, correlation, req):
        """Opcode 2177 for a gathering Kairo (ge000NN) -> 2178 ActKairoAck.

        Sent by the gathering mini game on success (0x007EAE90 -> 0x007AEE00): the
        Kairo id and an i32 taken from the mini game (param_1[0x16]), read here as
        the node's GTarget UID (assumption; -1 or an unknown UID gathers without
        depleting a node). The ack's KairoResult is read by 0x0080BC30.
        """
        kairo = gathering_kairo()[req.kairo_id]
        char = self.current_char()
        if char is None:
            await self.reply(ActKairoAck(result=results.NO_EXIST_CHAR), correlation, note='gathering fail (no char)')
            return
        square = self._square()
        target = self.targets.target(square, req.param) if square and req.param not in (-1, None) else None
        node = target if target is not None and target['id'] == kairo['target'] else None
        if node is not None and not self.targets.is_active(square, req.param):
            await self.reply(ActKairoAck(result=GATHERING_COLLECTED, remain_gold=gold_of(char)), correlation,
                             note=f'gathering refused ({req.kairo_id}: node {req.param} already collected)')
            return
        kind = node or next((t for t in target_kinds().values() if t['id'] == kairo['target']), None)
        if kind and (self._skill_level(char, kind['req_skill']) < kind['req_skill_lv']
                     or proficiency_values_for_char(char)[kairo['proficiency_type']] < kind['req_proficiency']):
            await self.reply(ActKairoAck(result=results.INVALID_STATE, remain_gold=gold_of(char)), correlation,
                             note=f'gathering refused ({req.kairo_id}: skill {kind["req_skill"]} too low)')
            return
        jackpot = self.rng.random() < kairo['jackpot_prob']
        rolled = [(code, count) for code, count, prob in (kairo['jackpot_items'] if jackpot else kairo['items'])
                  if self.rng.random() < prob]
        if len(free_cells(char)) < slots_needed(rolled, char):
            await self.reply(ActKairoAck(result=results.INVEN_FULL, remain_gold=gold_of(char)), correlation,
                             note=f'gathering refused ({req.kairo_id}: bags full)')
            return
        stored = add_reward_items(char, rolled)
        changed, proficiency = self._raise_proficiency(char, kairo['proficiency_type'], kairo['proficiency_up'])
        depleted = self.targets.deplete(square, req.param) if node is not None else None
        self.save_char()
        result = KairoResult(
            kairo_id=req.kairo_id,
            proficiency_changed=changed,
            jackpot=jackpot,
            proficiency=proficiency,
            notices=[AddedItemNotice(item_id=jhash(code), count=count) for code, count in rolled],
            items=[Item(owner=UPDATE_OWNER, **item) for item in stored],
        )
        await self.reply(ActKairoAck(result=0, kairo=result, remain_gold=gold_of(char)), correlation,
                         note=f'gathering ack ({req.kairo_id} node={req.param} items={rolled} '
                              f'jackpot={jackpot} proficiency={proficiency:.2f})')
        if depleted is not None:
            await self.broadcast_targets(square, [depleted])

    # ----------------------------------------------------------------- crafting

    def _pick(self, entries):
        """One (code, count) from [(code, count, weight)] by weight (ItemIN/FailIN sum to 1), or None."""
        entries = [(code, count, prob) for code, count, prob in entries if prob > 0]
        total = sum(prob for _, _, prob in entries)
        if not entries or total <= 0:
            return None
        roll = self.rng.random() * total
        for code, count, prob in entries:
            roll -= prob
            if roll < 0:
                return code, count
        return entries[-1][0], entries[-1][1]

    def making_refusal(self, char, recipe):
        """Result code and note when `recipe` cannot be crafted now, else None."""
        if char is None:
            return results.NO_EXIST_CHAR, 'no char'
        if self._skill_level(char, recipe['req_skill']) < recipe['req_skill_lv']:
            return results.INVALID_STATE, f'recipe skill {recipe["req_skill"]} not learned'
        if proficiency_values_for_char(char)[recipe['proficiency_type']] < recipe['req_proficiency']:
            return results.INVALID_STATE, f'proficiency below {recipe["req_proficiency"]:g}'
        if gold_of(char) < recipe['buy_price']:
            return results.NOT_ENOUGH_AR, f'needs {recipe["buy_price"]} AR'
        missing = [code for code, count in recipe['req_items'] if bag_item_count(char, code) < count]
        if missing:
            return results.INVALID_STATE, f'missing materials {missing}'
        return None

    async def handle_making(self, correlation, kairo_id, ack_cls):
        """Craft one DictKairo:LoadMaking recipe: 2177 -> 2178 (station) or 2496 -> 2497 (NPC).

        Client (static, 0x0080BC30 / 0x005C60C0, Kairo kind 1): KairoResult +0x1C set =
        success ("Congrats! You've successfully crafted %s!" per notice, GAME_299) and
        the new proficiency at +0x1E is applied; +0x1C clear = failure ("Failed to make
        item and acquired %s!", GAME_300, or GAME_365 "all materials have disappeared"
        without notices). Materials and BuyPrice are consumed either way; ItemIN and
        FailIN weights each sum to 1, so one entry is rolled. Failure proficiency
        (FailProficiencyUp) is sent with 2529, whose handler 0x00776400 calls the same
        JProficiencyMgr setter 0x0073A730 for any proficiency type.
        """
        recipe = making_kairo()[kairo_id]
        char = self.current_char()
        refusal = self.making_refusal(char, recipe)
        if refusal is not None:
            code, why = refusal
            await self.reply(ack_cls(result=code, remain_gold=gold_of(char)), correlation,
                             note=f'making refused ({kairo_id}: {why})')
            return
        success = self.rng.random() < recipe['success_rate']
        product = self._pick(recipe['items'] if success else recipe['fail_items'])
        produced = [product] if product else []
        freed = sum(1 for code, count in recipe['req_items']
                    if bag_item_count(char, code) == count)  # stacks used up free their cells (upper bound)
        if len(free_cells(char)) + freed < slots_needed(produced, char):
            await self.reply(ack_cls(result=results.INVEN_FULL, remain_gold=gold_of(char)), correlation,
                             note=f'making refused ({kairo_id}: bags full)')
            return
        updates = []
        for code, count in recipe['req_items']:
            updates += take_bag_items(char, code, count)
        add_gold(char, -recipe['buy_price'])
        stored = add_reward_items(char, produced)
        changed, proficiency = self._raise_proficiency(
            char, recipe['proficiency_type'], recipe['success_up'] if success else recipe['fail_up'])
        self.save_char()
        by_uid = {u['uid']: u for u in updates}
        by_uid.update({s['uid']: s for s in stored})   # a product may land in a just-emptied cell
        result = KairoResult(
            kairo_id=kairo_id,
            proficiency_changed=success,
            proficiency=proficiency,
            notices=[AddedItemNotice(item_id=jhash(code), count=count) for code, count in produced],
            items=[Item(owner=UPDATE_OWNER, **item) for item in by_uid.values()],
        )
        await self.reply(ack_cls(result=0, kairo=result, remain_gold=gold_of(char)), correlation,
                         note=f'making ack ({kairo_id} success={success} product={product} '
                              f'proficiency={proficiency:.2f})')
        if changed and not success:
            await self.send_msg(FishingProficiencyNot(result=0, proficiency=proficiency,
                                                      proficiency_type=recipe['proficiency_type']),
                                note=f'making fail proficiency not ({kairo_id}: {proficiency:.2f})')

    # ------------------------------------------------------------------ fishing

    def _find_item(self, char, item_id):
        """The inventory item whose ItemID hash is `item_id`, or None."""
        wanted = int(item_id) & 0xFFFFFFFF
        return next((i for i in char.get('items', [])
                     if i.get('container') not in (DEPOT_CONTAINER, EQUIPPED)
                     and jhash(i.get('code', '')) & 0xFFFFFFFF == wanted and i.get('count', 1) > 0), None)

    def _cancel_fishing(self):
        task, self._fishing_task = self._fishing_task, None
        if task is not None and not task.done() and task is not asyncio.current_task():
            task.cancel()

    @packet_handler(FishingStartReq)
    async def handle_fishing_start(self, correlation: int, body: bytes):
        """Opcode 2523 (eEGS_FISHING_START_REQ, 0x007A1FF0) -> 2524 (0x0075B0B0), then a cast loop.

        Live: the fishing page (Space at a hole) sends the hole id, its hash and the
        Bait slot's ItemID once; 2524 starts the cast motion and the page shows
        "Stop Fishing". The client does not resend 2523 after a catch, so the server
        keeps casting: each cast takes MaxTime minus the bait's AdjValue ("Casting
        time reduced by N s"), uses one bait and ends with 2527. Without bait the
        loop ends with 2528 JERI_FISHING_04; 2525 stops it.
        """
        req = FishingStartReq.decode(body)
        self.transport.record('fishing-start-req', body, hole=req.fishing_hole_id,
                              bait=req.bait_item_id, boost=req.boost_item_id)
        char = self.current_char()
        kairo = fishing_kairo().get(req.fishing_hole_id)
        hole = next((t for t in target_kinds().values() if t['id'] == req.fishing_hole_id), None)
        if char is None or kairo is None or hole is None:
            await self.reply(FishingStartAck(result=results.INVALID_STATE), correlation,
                             note=f'fishing start refused (unknown hole {req.fishing_hole_id!r})')
            return
        if int(char.get('level', 1)) < hole['demand_lv']:
            await self.reply(FishingStartAck(result=results.INVALID_STATE), correlation,
                             note=f'fishing start refused (level below {hole["demand_lv"]})')
            return
        # DictTarget:LoadFishing ReqSkillIdx/ReqSkillLv/ReqProficiency (e.g. Fish_ACT1_S1:
        # Fishing lv1 + 200). The special holes' ReqItemID permits (Type 47) are checked
        # by the client page (UI_2952); the server has no license state yet.
        if (self._skill_level(char, hole['req_skill']) < hole['req_skill_lv']
                or proficiency_values_for_char(char)[FISHING_PROFICIENCY] < hole['req_proficiency']):
            await self.reply(FishingStartAck(result=results.INVALID_STATE), correlation,
                             note=f'fishing start refused ({req.fishing_hole_id}: skill/proficiency too low)')
            return
        if self._bait(char, req.bait_item_id) is None:
            await self.reply(FishingStartAck(result=FISHING_NEED_BAIT), correlation,
                             note='fishing start refused (no bait)')
            return
        self._cancel_fishing()
        await self.reply(FishingStartAck(result=0), correlation, note=f'fishing start ack ({req.fishing_hole_id})')
        self._fishing_task = asyncio.get_running_loop().create_task(
            self._fish(kairo, req.bait_item_id, self.char_id))

    def _bait(self, char, bait_item_id):
        """The inventory bait (fishing.lua Type 45) with ItemID hash `bait_item_id`, or None."""
        item = self._find_item(char, bait_item_id)
        return item if item is not None and bait_time_reduction(item.get('code')) is not None else None

    def cast_seconds(self, kairo, bait):
        """MaxTime of the hole minus the bait's casting time reduction (at least 1 s)."""
        return max(1.0, kairo['max_time'] - (bait_time_reduction(bait.get('code')) or 0)) * FISHING_TIME_SCALE

    def stop_fishing(self):
        """End the cast loop (2525, disconnect)."""
        self._cancel_fishing()

    async def _fish(self, kairo, bait_item_id, char_id):
        """Cast until the bait runs out or the player stops (2525), leaves or changes character."""
        while True:
            char = self.current_char() if self.char_id == char_id else None
            bait = self._bait(char, bait_item_id) if char is not None else None
            if bait is None:
                if char is not None:
                    await self.send_to([self.session], FishingFailedNot(result=FISHING_NEED_BAIT),
                                       note='fishing stopped (no bait)')
                return
            await asyncio.sleep(self.cast_seconds(kairo, bait))
            if self.char_id != char_id or not await self._finish_cast(kairo, bait_item_id):
                return

    async def _finish_cast(self, kairo, bait_item_id):
        """One cast: use a bait, roll the catch, send 2527 (and 2529). False ends the loop."""
        char = self.current_char()
        bait = self._bait(char, bait_item_id) if char is not None else None
        if bait is None:
            return True  # the loop reports the missing bait
        caught = self._roll_catch(kairo)
        remaining = bait.get('count', 1) - 1
        if caught:
            # The last bait frees a cell before the catch is placed in the bag.
            inventory = char if remaining else dict(char, items=[i for i in char['items'] if i is not bait])
            if len(free_cells(inventory)) < slots_needed([caught], inventory):
                await self.send_to([self.session], FishingFailedNot(result=results.INVEN_FULL),
                                   note='fishing failed (bags full)')
                return False
        bait['count'] = remaining
        if bait['count'] <= 0:
            char['items'].remove(bait)
        updates = [Item(owner=UPDATE_OWNER, **dict(bait, count=max(0, bait['count'])))]
        if not caught:
            self.save_char()
            await self.send_to([self.session], FishingResultNot(result=FISHING_NOTHING, items=updates),
                               note=f'fishing result (nothing, {kairo["target"]})')
            return True
        # A catch itself adds no proficiency: DictKairo:LoadFishing has no gain field
        # (gathering has SuccessProficiencyUp). Fishing proficiency comes from using
        # the caught Type 46 items (use_fishing_proficiency_item).
        updates += [Item(owner=UPDATE_OWNER, **item) for item in add_reward_items(char, [caught])]
        self.save_char()
        await self.send_to([self.session], FishingResultNot(result=0, items=updates),
                           note=f'fishing result ({kairo["target"]}: {caught})')
        return True

    async def use_fishing_proficiency_item(self, char, code, use_count):
        """Type 46 items: "Increases the proficiency of the fisher by N when used" (AdjValue).

        2529 FishingProficiencyNot carries the new total: its handler 0x00776400 passes
        it to JProficiencyMgr 0x0073A730, which stores the value and shows UI
        "Fishing Experience has increased (N)" with the new whole number.
        """
        gain = fishing_proficiency_gain(code)
        if not gain:
            return
        changed, proficiency = self._raise_proficiency(char, FISHING_PROFICIENCY, gain * max(1, int(use_count)))
        if not changed:
            return
        self.save_char()
        await self.send_msg(FishingProficiencyNot(result=0, proficiency=proficiency,
                                                  proficiency_type=FISHING_PROFICIENCY),
                            note=f'fishing proficiency not ({code}: {proficiency:.0f})')

    def _roll_catch(self, kairo):
        """(ItemID, count) from the hole's weighted catch groups, or None (the weights sum below 1)."""
        roll, total = self.rng.random(), 0.0
        for group_id, weight in kairo['groups']:
            total += weight
            if roll < total:
                entries = fish_group(group_id)
                if not entries:
                    return None
                code, count, _ = self.rng.choices(entries, weights=[w for _, _, w in entries])[0]
                return code, count
        return None

    @packet_handler(2525)
    async def handle_fishing_stop(self, correlation: int, body: bytes):
        """Opcode 2525 (eEGS_FISHING_STOP_REQ, 0x007A21E0) -> 2526 (0x0075B1C0): cancel the pending cast."""
        self.transport.record('fishing-stop-req', body)
        self._cancel_fishing()
        await self.reply(FishingStopAck(result=0), correlation, note='fishing stop ack')
