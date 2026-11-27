"""Town GTargets (5124/5125/5126), gathering (2177/2178) and fishing (2523-2529)."""
import asyncio
import random
import struct
import unittest
from unittest.mock import patch

from tests.common import ServerTestCase, create_request, lobby_flow
from darkblood.games.entities.items import UPDATE_OWNER, Item
from darkblood.games.game_data.life_skills import FISHING, GATHERING, MAKING, town_gtargets
from darkblood.games.handlers import life_skills as life_handlers
from darkblood.games.life_targets import LifeTargetState
from darkblood.games.network.messages import (
    ActKairoReq,
    ChangeGTargetNot,
    FishingProficiencyNot,
    FishingStartAck,
    FishingStartReq,
    FishingStopReq,
    GTargetListAck,
)
from darkblood.games.session import GameSession


async def enter_town(client, name, level=1, skills=None):
    await lobby_flow(client)
    client.send_event(2012, create_request(name))
    _, created = await client.expect_event(2013)
    char_id = struct.unpack_from('<Q', created, 10)[0]
    char = GameSession.store().get('OfflinePlayer', char_id)
    char['level'] = level
    char.setdefault('skills', {}).update(skills or {})
    client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
    await client.expect_event(2007)
    client.send_event(5124, struct.pack('<i', 0x7fffffff))
    _, body = await client.expect_event(5125)
    return char, {t.target_uid: t.is_active for t in GTargetListAck.decode(body).targets}


class LifeTargetStateTest(unittest.TestCase):
    def test_town_targets_come_from_the_map_objects(self):
        act1 = town_gtargets()['Act1']
        kinds = {}
        for _, kind in act1:
            kinds[kind['kind']] = kinds.get(kind['kind'], 0) + 1
        self.assertEqual(kinds, {MAKING: 2, GATHERING: 152, FISHING: 8})
        fishing_ids = {kind['id'] for _, kind in act1 if kind['kind'] == FISHING}
        self.assertEqual(fishing_ids, {'Fish_ACT1_N0', 'Fish_ACT1_S1'})

    def test_quota_depletion_and_regeneration(self):
        state = LifeTargetState(rng=random.Random(7))
        states = {s.target_uid: s.is_active for s in state.states('Act1', now=0)}
        act1 = dict(town_gtargets()['Act1'])
        self.assertTrue(all(states[uid] for uid, kind in act1.items() if kind['kind'] in (FISHING, MAKING)))
        mines = [uid for uid, kind in act1.items() if kind['id'] == 'G1mscA01n0']
        active = [uid for uid in mines if states[uid]]
        self.assertEqual(len(active), 9)  # ceil(EnableRate 0.1 * 82)

        node = active[0]
        self.assertEqual(state.deplete('Act1', node, now=10).is_active, False)
        self.assertIsNone(state.deplete('Act1', node, now=11))  # already collected
        self.assertEqual(state.regenerate(now=30), {})           # RegenSecond 60 not reached
        regenerated = {}
        for now in range(70, 2000, 60):
            for square, changes in state.regenerate(now=now).items():
                regenerated.setdefault(square, []).extend(changes)
            if regenerated:
                break
        returned = [s.target_uid for s in regenerated.get('Act1', [])]
        self.assertTrue(returned and all(s.is_active for s in regenerated['Act1']))
        self.assertEqual(sum(state.is_active('Act1', uid) for uid in mines), 9)


class LifeSkillsFlowTest(ServerTestCase):
    def test_town_load_lists_every_target(self):
        async def scenario(client):
            _, states = await enter_town(client, 'NodeWatcher')
            act1 = dict(town_gtargets()['Act1'])
            self.assertEqual(set(states), set(act1))
            self.assertTrue(all(states[uid] for uid, kind in act1.items() if kind['kind'] == FISHING))
            self.assertTrue(any(states[uid] for uid, kind in act1.items() if kind['kind'] == GATHERING))
            self.assertFalse(all(states[uid] for uid, kind in act1.items() if kind['kind'] == GATHERING))

        self.run_async(self.with_server(scenario))

    def test_gathering_yields_items_proficiency_and_depletes_the_node(self):
        async def scenario(client):
            char, states = await enter_town(client, 'RockMiner', level=20, skills={'9007': 1})
            act1 = dict(town_gtargets()['Act1'])
            node = next(uid for uid, kind in act1.items() if kind['id'] == 'G1mscA01n0' and states[uid])
            request = ActKairoReq(kairo_id='ge00001', param=node).encode()

            client.send_event(2177, request)
            _, body = await client.expect_event(2178)
            self.assertEqual(struct.unpack_from('<i', body)[0], 0)
            kairo_id = 'ge00001'.encode('utf-16le')
            self.assertIn(kairo_id, body)
            flags_at = body.index(kairo_id) + len(kairo_id)
            proficiency_changed, _jackpot, proficiency = struct.unpack_from('<??f', body, flags_at)
            self.assertTrue(proficiency_changed)
            self.assertAlmostEqual(proficiency, 0.2666666667, places=5)
            ore = next(item for item in char['items'] if item['code'] == 'IMnr20N')
            self.assertIn(Item(owner=UPDATE_OWNER, **ore).encode(), body)
            self.assertAlmostEqual(char['proficiencies'][0], 0.2666666667, places=5)
            _, change = await client.expect_event(5126)
            self.assertEqual([(t.target_uid, t.is_active) for t in ChangeGTargetNot.decode(change).targets],
                             [(node, False)])

            client.send_event(2177, request)
            _, again = await client.expect_event(2178)
            self.assertEqual(struct.unpack_from('<i', again)[0], life_handlers.GATHERING_COLLECTED)

        self.run_async(self.with_server(scenario))

    def test_gathering_requires_the_life_skill(self):
        async def scenario(client):
            _, states = await enter_town(client, 'NoPickaxe', level=20)
            act1 = dict(town_gtargets()['Act1'])
            node = next(uid for uid, kind in act1.items() if kind['id'] == 'G1mscA01n0' and states[uid])
            client.send_event(2177, ActKairoReq(kairo_id='ge00001', param=node).encode())
            _, body = await client.expect_event(2178)
            self.assertEqual(struct.unpack_from('<i', body)[0], 12)  # INVALID_STATE: Mining not learned

        self.run_async(self.with_server(scenario))

    def test_fishing_loop_casts_until_the_bait_runs_out(self):
        """Live: one 2523 with the Bait slot's ItemID; the server keeps casting (2527 per cast)."""
        from darkblood.core.hashing import jhash

        async def scenario(client):
            char, _ = await enter_town(client, 'PierAngler', level=10)
            char['items'].append(dict(code='ILurS3', uid=7700, container=3, slot=20, count=2))
            request = FishingStartReq(fishing_hole_id='Fish_ACT1_N0', hole_hash=jhash('Fish_ACT1_N0'),
                                      bait_item_id=jhash('ILurS3'))
            catches = iter([('INfiN8', 1), None])
            with patch.object(life_handlers, 'FISHING_TIME_SCALE', 0.001),                     patch.object(life_handlers.LifeSkillHandlers, '_roll_catch', side_effect=lambda kairo: next(catches)):
                client.send_event(2523, request.encode())
                _, start = await client.expect_event(2524)
                self.assertEqual(FishingStartAck.decode(start).result, 0)
                _, first = await client.expect_event(2527)
                _, second = await client.expect_event(2527)
                _, stopped = await client.expect_event(2528)
            self.assertEqual(struct.unpack_from('<i', first)[0], 0)
            fish = next(item for item in char['items'] if item['code'] == 'INfiN8')
            self.assertIn(Item(owner=UPDATE_OWNER, **fish).encode(), first)
            self.assertEqual(char.get('proficiencies', [0.0] * 10)[9], 0.0)  # a catch adds no proficiency
            self.assertEqual(struct.unpack_from('<i', second)[0], life_handlers.FISHING_NOTHING)
            self.assertIn(Item(owner=UPDATE_OWNER, code='ILurS3', uid=7700, container=3, slot=20, count=0).encode(),
                          second)  # a miss still carries the bait update
            self.assertEqual(struct.unpack_from('<i', stopped)[0], life_handlers.FISHING_NEED_BAIT)
            self.assertFalse(any(item['code'] == 'ILurS3' for item in char['items']))

        self.run_async(self.with_server(scenario))

    def test_catch_can_use_the_last_bait_cell(self):
        from darkblood.core.hashing import jhash
        from darkblood.games.network import results
        from darkblood.player_management.characters import add_reward_items, free_cells

        async def scenario(client):
            char, _ = await enter_town(client, 'FullBagAngler', level=10)
            free = len(free_cells(char))
            bait, *_ = add_reward_items(char, [('ILurN1', 2)] + [('Ihppa0001', 1)] * (free - 1))
            self.assertFalse(free_cells(char))
            request = FishingStartReq(fishing_hole_id='Fish_ACT1_N0', bait_item_id=jhash('ILurN1')).encode()
            with patch.object(life_handlers, 'FISHING_TIME_SCALE', 0.001), \
                 patch.object(life_handlers.LifeSkillHandlers, '_roll_catch', return_value=('INfiN8', 1)):
                client.send_event(2523, request)
                await client.expect_event(2524)
                _, full = await client.expect_event(2528)
                self.assertEqual(struct.unpack_from('<i', full)[0], results.INVEN_FULL)
                self.assertEqual(bait['count'], 2)

                bait['count'] = 1
                client.send_event(2523, request)
                await client.expect_event(2524)
                _, stopped = await client.expect_event(2528)
                self.assertEqual(struct.unpack_from('<i', stopped)[0], life_handlers.FISHING_NEED_BAIT)
                fish = next(item for item in char['items'] if item['code'] == 'INfiN8')
                self.assertEqual((fish['container'], fish['slot']), (bait['container'], bait['slot']))
                self.assertNotIn(bait, char['items'])

        self.run_async(self.with_server(scenario))

    def test_fishing_proficiency_items_raise_the_total(self):
        """Type 46: "Increases the proficiency of the fisher by N when used"; 2529 carries the total."""
        from darkblood.games.network.messages import UseItemReq

        async def scenario(client):
            char, _ = await enter_town(client, 'ShrimpEater', level=10)
            char['items'] += [dict(code='ISfiS21', uid=7800, container=3, slot=22, count=1),   # Starfish +2
                              dict(code='ISfiS20', uid=7801, container=3, slot=23, count=3)]   # Red Shrimp +1
            totals = []
            for uid, count in ((7800, 1), (7801, 2)):
                client.send_event(2038, UseItemReq(item_uid=uid, use_count=count).encode())
                _, used = await client.expect_event(2039)
                self.assertEqual(struct.unpack_from('<i', used)[0], 0)
                _, prof = await client.expect_event(2529)
                notice = FishingProficiencyNot.decode(prof)
                totals.append((notice.proficiency_type, notice.proficiency))
            self.assertEqual(totals, [(9, 2.0), (9, 4.0)])
            self.assertEqual(char['proficiencies'][9], 4.0)

            char['proficiencies'][9] = 199.0  # Fishing Lv1 MaxProficiency is 200
            char['items'].append(dict(code='ISfiS23', uid=7802, container=3, slot=24, count=1))  # +8
            client.send_event(2038, UseItemReq(item_uid=7802, use_count=1).encode())
            await client.expect_event(2039)
            _, capped = await client.expect_event(2529)
            self.assertEqual(FishingProficiencyNot.decode(capped).proficiency, 200.0)

        self.run_async(self.with_server(scenario))

    def test_cast_time_is_max_time_minus_the_bait_reduction(self):
        handlers = life_handlers.LifeSkillHandlers.__new__(life_handlers.LifeSkillHandlers)
        kairo = {'max_time': 60}
        self.assertEqual(handlers.cast_seconds(kairo, {'code': 'ILurN1'}), 60)  # "reduced by 0 s"
        self.assertEqual(handlers.cast_seconds(kairo, {'code': 'ILurS4'}), 30)

    def test_fishing_refusals_and_stop(self):
        from darkblood.core.hashing import jhash

        async def scenario(client):
            char, _ = await enter_town(client, 'ShoreNovice', level=5)
            char['items'].append(dict(code='ILurN1', uid=7701, container=3, slot=21, count=5))
            request = FishingStartReq(fishing_hole_id='Fish_ACT1_N0', bait_item_id=jhash('ILurN1')).encode()
            client.send_event(2523, request)
            _, low = await client.expect_event(2524)
            self.assertEqual(FishingStartAck.decode(low).result, 12)  # DemandLv 10

            char['level'] = 10
            client.send_event(2523, FishingStartReq(fishing_hole_id='Fish_ACT1_N0', bait_item_id=12345).encode())
            _, no_bait = await client.expect_event(2524)
            self.assertEqual(FishingStartAck.decode(no_bait).result, life_handlers.FISHING_NEED_BAIT)

            with patch.object(life_handlers, 'FISHING_TIME_SCALE', 0.005):  # 0.3 s casts
                client.send_event(2523, request)
                await client.expect_event(2524)
                client.send_event(2525, FishingStopReq().encode())
                await client.expect_event(2526)
                with self.assertRaises(asyncio.TimeoutError):
                    await asyncio.wait_for(client.expect_event(2527), 0.6)
            self.assertEqual(next(i for i in char['items'] if i['uid'] == 7701)['count'], 5)

        self.run_async(self.with_server(scenario))

if __name__ == '__main__':
    unittest.main()
