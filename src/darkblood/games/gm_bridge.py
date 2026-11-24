"""Localhost-only GM command bridge (127.0.0.1:9402) for the Dark Blood Launcher.

Allows the launcher's GM Commands tab (when `[server] gm_mode = 1`) to list
online characters and execute server-backed GM commands live on connected
sessions without requiring in-game typing.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shlex
import struct
import time

from darkblood.core import options
from darkblood.core.hashing import jhash
from darkblood.core.serialization.jser import event
from darkblood.games.entities.character import Character
from darkblood.games.entities.items import EQUIPPED, Item, UPDATE_OWNER
from darkblood.games.network.messages.gm import (
    CheatDeleteAllInvenItemAck,
    CheatDepotSizeIncreaseAck,
    CheatLevelUpAck,
    CheatQuestResetAck,
)
from darkblood.games.network.messages.inventory import DragItemAck
from darkblood.games.network.messages.skills import (
    DualSkillActiveNot,
    InitSkillNot,
    InsertApNot,
    LearnSkillListAck,
)
from darkblood.games.network.messages.system import RebirthCoinChangeNot
from darkblood.games.progression import (
    MAX_LEVEL,
    add_ap,
    advance_level,
    level_up_not,
    stress_changed_not,
    total_ap,
)
from darkblood.games.world import GameWorldManager
from darkblood.player_management.characters import add_reward_items

logger = logging.getLogger(__name__)

GM_BRIDGE_HOST = '127.0.0.1'
GM_BRIDGE_PORT = 9402

SERVER_LIVE_COMMANDS = frozenset({
    'lv',
    'ar',
    'ap',
    'coin',
    'cash',
    'stress',
    'itemcall',
    'clearbag',
    'upgrade',
    'forceupgrade',
    'durability',
    'incdepot',
    'skill',
    'skillinit',
    'questcancel',
    'dualskill',
})


def _list_players() -> list:
    world = GameWorldManager.get()
    out = []
    for cid, wp in sorted(world.players.items()):
        c = wp.char_data or {}
        out.append({
            'char_id': int(cid),
            'name': str(c.get('name', f'Char#{cid}')),
            'account': str(getattr(wp.session, 'account', '')),
            'level': int(c.get('level', 1)),
            'gold': int(c.get('gold', 0)),
            'sp': int(c.get('sp', 0)),
        })
    return out


def _resolve_player(char_id=None):
    world = GameWorldManager.get()
    if char_id is not None:
        return world.get_player(int(char_id))
    if len(world.players) == 1:
        return next(iter(world.players.values()))
    if world.players:
        return next(iter(world.players.values()))
    return None


async def execute_gm_command(command_line: str, char_id=None) -> dict:
    """Execute a GM command line against a connected character session."""
    if not options.get('gm_mode'):
        return {'ok': False, 'message': 'GM Mode is disabled in darkblood_options.ini.'}

    raw = (command_line or '').strip()
    if raw.startswith(('%', '/')):
        raw = raw[1:].strip()
    if not raw:
        return {'ok': False, 'message': 'Empty command.'}

    try:
        tokens = shlex.split(raw)
    except ValueError:
        tokens = raw.split()
    cmd = tokens[0].lower()
    args = tokens[1:]

    if cmd not in SERVER_LIVE_COMMANDS:
        return {
            'ok': False,
            'client_only': True,
            'message': f'"{cmd}" is a client-side command. Paste %{raw} in game chat or press Ctrl+Shift+C.',
        }

    player = _resolve_player(char_id)
    if player is None or player.session is None or getattr(player.session, 'transport', None) is None:
        return {'ok': False, 'message': 'No character is currently online in the server.'}

    session = player.session
    char = player.char_data
    transport = session.transport
    cname = char.get('name', f'Char#{player.char_id}')

    def save():
        session.store().save_char(session.account, player.char_id)

    try:
        if cmd == 'lv':
            if not args:
                return {'ok': False, 'message': 'Usage: lv <1..60>'}
            target = max(1, min(int(args[0]), MAX_LEVEL))
            advance_level(char, target, exp=0)
            save()
            await transport.send_event(
                event(2058, CheatLevelUpAck(result=0, character=Character.from_dict(char)).encode()),
                note=f'gm bridge lv={target}',
            )
            await transport.send_event(
                event(level_up_not(char).OPCODE, level_up_not(char).encode()),
                note=f'gm bridge levelup not lv={target}',
            )
            return {'ok': True, 'message': f'{cname}: level set to {target}.'}

        if cmd == 'ar':
            if not args:
                return {'ok': False, 'message': 'Usage: ar <amount>'}
            delta = int(args[0])
            cur_ar = max(0, int(char.get('gold', 0)) + delta)
            char['gold'] = cur_ar
            char['u66'] = cur_ar
            save()
            await transport.send_event(
                event(2104, struct.pack('<Iq', 0, cur_ar)),
                note=f'gm bridge ar={cur_ar}',
            )
            return {'ok': True, 'message': f'{cname}: AR is now {cur_ar:,}.'}

        if cmd == 'ap':
            if not args:
                return {'ok': False, 'message': 'Usage: ap <amount>'}
            delta = int(args[0])
            add_ap(char, delta)
            save()
            msg = InsertApNot(current_ap=char['sp'], total_ap=char['total_ap'])
            await transport.send_event(event(msg.OPCODE, msg.encode()), note=f'gm bridge ap +{delta}')
            return {'ok': True, 'message': f'{cname}: +{delta} AP (SP={char["sp"]}, total={char["total_ap"]}).'}

        if cmd == 'coin':
            if not args:
                return {'ok': False, 'message': 'Usage: coin <count>'}
            delta = int(args[0])
            total = max(0, int(char.get('rebirth_coins', 3)) + delta)
            char['rebirth_coins'] = total
            save()
            await transport.send_event(event(2102, struct.pack('<Ih', 0, min(total, 32767))), note='gm bridge coin')
            not_msg = RebirthCoinChangeNot(result=0, coins=min(total, 32767))
            await transport.send_event(event(not_msg.OPCODE, not_msg.encode()), note='gm bridge coin not')
            return {'ok': True, 'message': f'{cname}: rebirth coins = {total}.'}

        if cmd == 'cash':
            delta = int(args[0]) if args else 100000
            char['cash'] = max(0, int(char.get('cash', 0)) + delta)
            save()
            return {'ok': True, 'message': f'{cname}: cash balance = {char["cash"]:,}.'}

        if cmd == 'stress':
            if not args:
                return {'ok': False, 'message': 'Usage: stress <daily> [pcbang] [weekly]'}
            char['stress'] = max(0, min(330, int(args[0])))
            if len(args) > 1:
                char['stress_pcb'] = max(0, min(330, int(args[1])))
            if len(args) > 2:
                char['stress_week'] = max(0, min(330, int(args[2])))
            save()
            s_not = stress_changed_not(char)
            await transport.send_event(event(s_not.OPCODE, s_not.encode()), note='gm bridge stress')
            return {'ok': True, 'message': f'{cname}: stress set to {char["stress"]}.'}

        if cmd == 'itemcall':
            if not args:
                return {'ok': False, 'message': 'Usage: itemcall <item_id> [count=1]'}
            code = args[0]
            count = max(1, int(args[1])) if len(args) > 1 else 1
            stored = add_reward_items(char, [(code, count)])
            save()
            wire_items = [Item(owner=UPDATE_OWNER, **i) for i in stored]
            await transport.send_event(
                event(2037, DragItemAck(result=0, items=wire_items).encode()),
                note=f'gm bridge itemcall {code} x{count}',
            )
            return {'ok': True, 'message': f'{cname}: spawned {code} x{count}.'}

        if cmd == 'clearbag':
            deleted, kept = [], []
            for it in char.get('items', []):
                if it.get('container') == EQUIPPED:
                    kept.append(it)
                else:
                    deleted.append(Item(
                        code=it.get('code', ''), uid=it.get('uid', 0), owner=-1,
                        container=it.get('container', 3), slot=it.get('slot', 0), count=0,
                    ))
            char['items'] = kept
            save()
            await transport.send_event(
                event(2108, CheatDeleteAllInvenItemAck(result=0, items=deleted).encode()),
                note=f'gm bridge clearbag ({len(deleted)})',
            )
            return {'ok': True, 'message': f'{cname}: cleared {len(deleted)} bag item(s).'}

        if cmd in ('upgrade', 'forceupgrade'):
            if cmd == 'upgrade':
                if not args:
                    return {'ok': False, 'message': 'Usage: upgrade <level>'}
                target_lv = max(0, min(20, int(args[0])))
                slot_filter = lambda it: it.get('container') == EQUIPPED and it.get('slot') == 0
            else:
                if len(args) < 2:
                    return {'ok': False, 'message': 'Usage: forceupgrade <weapon|cloth> <level>'}
                kind = args[0].lower()
                target_lv = max(0, min(20, int(args[1])))
                slot_filter = (
                    (lambda it: it.get('container') == EQUIPPED and it.get('slot') == 0)
                    if kind == 'weapon'
                    else (lambda it: it.get('container') == EQUIPPED and it.get('slot') != 0)
                )
            changed = []
            for it in char.get('items', []):
                if slot_filter(it):
                    it['upgrade'] = target_lv
                    changed.append(Item(owner=UPDATE_OWNER, **it))
            if not changed:
                return {'ok': False, 'message': f'{cname}: no matching equipped item found.'}
            save()
            await transport.send_event(
                event(2037, DragItemAck(result=0, items=changed).encode()),
                note=f'gm bridge {cmd} +{target_lv}',
            )
            return {'ok': True, 'message': f'{cname}: set {len(changed)} equipped item(s) to +{target_lv}.'}

        if cmd == 'durability':
            if not args:
                return {'ok': False, 'message': 'Usage: durability <value>'}
            val = max(0, int(args[0]))
            changed = []
            for it in char.get('items', []):
                if it.get('container') == EQUIPPED:
                    it['durability'] = val
                    changed.append(Item(owner=UPDATE_OWNER, **it))
            save()
            if changed:
                await transport.send_event(
                    event(2037, DragItemAck(result=0, items=changed).encode()),
                    note=f'gm bridge durability={val}',
                )
            return {'ok': True, 'message': f'{cname}: durability set to {val} on {len(changed)} equipped item(s).'}

        if cmd == 'incdepot':
            rem = list(char.get('depot_extend_remain', [0, 0]))
            while len(rem) < 2:
                rem.append(0)
            rem[0] = max(rem[0], 30 * 86400)
            char['depot_extend_remain'] = rem
            save()
            await transport.send_event(
                event(CheatDepotSizeIncreaseAck.OPCODE, CheatDepotSizeIncreaseAck(result=0).encode()),
                note='gm bridge incdepot',
            )
            return {'ok': True, 'message': f'{cname}: depot expanded.'}

        if cmd == 'skill':
            if len(args) < 2:
                return {'ok': False, 'message': 'Usage: skill <skill_index> <level>'}
            from darkblood.games.handlers.skills import learned_skill_map
            sidx = int(args[0])
            slv = max(1, int(args[1]))
            char.setdefault('skills', {})[str(sidx)] = slv
            save()
            ack = LearnSkillListAck(
                result=0,
                skills=learned_skill_map({sidx: slv}),
                remain_sp=int(char.get('sp', 0)),
                remain_gold=int(char.get('gold', 0)),
            )
            await transport.send_event(event(2698, ack.encode()), note=f'gm bridge skill {sidx}={slv}')
            return {'ok': True, 'message': f'{cname}: skill {sidx} set to Lv.{slv}.'}

        if cmd == 'skillinit':
            char['skills'] = {}
            char['sp'] = total_ap(char)
            save()
            not_msg = InitSkillNot(result=0, sp=char['sp'], skills={})
            await transport.send_event(event(not_msg.OPCODE, not_msg.encode()), note='gm bridge skillinit')
            return {'ok': True, 'message': f'{cname}: skills reset, refunded {char["sp"]} AP.'}

        if cmd == 'questcancel':
            char['quests_active'] = {}
            char['quests'] = []
            save()
            await transport.send_event(
                event(2097, CheatQuestResetAck(result=0).encode()),
                note='gm bridge questcancel',
            )
            return {'ok': True, 'message': f'{cname}: active quests cleared.'}

        if cmd == 'dualskill':
            add_days = max(1, int(args[0])) if args else 30
            now = int(time.time())
            base_exp = max(now, int(char.get('dual_skill_expire', 0)))
            char['dual_skill_expire'] = base_exp + add_days * 86400
            remain_sec = char['dual_skill_expire'] - now
            cur_idx = int(char.get('dual_skill_index', 0))
            save()
            ds_not = DualSkillActiveNot(
                extend_time=remain_sec,
                add_day=add_days,
                cur_dual_skill_index=cur_idx,
                item_id=jhash('IDSk1Cash269'),
            )
            await transport.send_event(event(ds_not.OPCODE, ds_not.encode()), note=f'gm bridge dualskill +{add_days}d')
            return {'ok': True, 'message': f'{cname}: Dual Skill activated for {add_days} day(s).'}
    except ValueError as exc:
        return {'ok': False, 'message': f'Invalid argument: {exc}'}
    except Exception as exc:
        logger.exception('GM bridge execution failed')
        return {'ok': False, 'message': f'Error: {exc}'}

    return {'ok': False, 'message': f'Unhandled command: {cmd}'}


async def _handle_bridge_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    try:
        line = await asyncio.wait_for(reader.readline(), timeout=5.0)
        if not line:
            return
        req = json.loads(line.decode('utf-8', errors='replace'))
        action = req.get('action')
        if action == 'list_players':
            resp = {
                'ok': True,
                'gm_mode': bool(options.get('gm_mode')),
                'players': _list_players(),
                'live_commands': sorted(SERVER_LIVE_COMMANDS),
            }
        elif action == 'exec':
            resp = await execute_gm_command(req.get('command', ''), char_id=req.get('char_id'))
        else:
            resp = {'ok': False, 'message': f'Unknown action: {action}'}
        writer.write((json.dumps(resp) + '\n').encode('utf-8'))
        await writer.drain()
    except Exception as exc:
        try:
            writer.write((json.dumps({'ok': False, 'message': str(exc)}) + '\n').encode('utf-8'))
            await writer.drain()
        except OSError:
            pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except OSError:
            pass


async def start_gm_bridge(host: str = GM_BRIDGE_HOST, port: int = GM_BRIDGE_PORT):
    """Start the localhost-only GM bridge TCP server."""
    server = await asyncio.start_server(_handle_bridge_client, host, port)
    logger.info('GM bridge listening on %s:%d (localhost only)', host, port)
    return server
