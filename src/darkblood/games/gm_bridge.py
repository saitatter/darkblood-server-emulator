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
from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, List

from darkblood.core import options
from darkblood.core.serialization.jser import event
from darkblood.games.entities.character import Character
from darkblood.games.entities.items import EQUIPPED, UPDATE_OWNER
from darkblood.games.gm_commands import (
    apply_ap_delta,
    apply_ar_delta,
    apply_clear_bag,
    apply_depot_expand,
    apply_dual_skill,
    apply_equip_durability,
    apply_equip_upgrade,
    apply_item_call,
    apply_learn_skill,
    apply_level_up,
    apply_quest_reset,
    apply_rebirth_coins_delta,
    apply_skill_reset,
    apply_stress,
)
from darkblood.games.network.messages.gm import (
    CheatDeleteAllInvenItemAck,
    CheatDepotSizeIncreaseAck,
    CheatLevelUpAck,
    CheatQuestResetAck,
)
from darkblood.games.network.messages.inventory import (
    DragItemAck,
    MarkItemActiveNot,
    MarkTabActiveNot,
)
from darkblood.games.network.messages.skills import (
    InitSkillNot,
    InsertApNot,
    LearnSkillListAck,
)
from darkblood.games.network.messages.system import RebirthCoinChangeNot
from darkblood.games.progression import level_up_not
from darkblood.games.world import GameWorldManager

logger = logging.getLogger(__name__)

GM_BRIDGE_HOST = '127.0.0.1'
GM_BRIDGE_PORT = 9402


@dataclass
class _BridgeCtx:
    session: object
    char_id: int
    char: dict
    transport: object
    cname: str

    def save(self) -> None:
        self.session.store().save_char(self.session.account, self.char_id)

    async def send(self, msg, note: str) -> None:
        await self.transport.send_event(event(msg.OPCODE, msg.encode()), note=note)

    async def send_raw(self, opcode: int, payload: bytes, note: str) -> None:
        await self.transport.send_event(event(opcode, payload), note=note)


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


def _list_clients() -> list:
    """Connected clients grouped by account, each with its full character roster and active char marked."""
    world = GameWorldManager.get()
    clients = []
    seen_accounts = {}
    for cid, wp in sorted(world.players.items()):
        session = wp.session
        account = str(getattr(session, 'account', '') or f'Client#{cid}')
        active_id = int(cid)
        roster = []
        store = session.store() if session and hasattr(session, 'store') else None
        if store is not None:
            for ch in store.characters(account):
                ch_id = int(ch.get('id', 0))
                roster.append({
                    'char_id': ch_id,
                    'name': str(ch.get('name', f'Char#{ch_id}')),
                    'level': int(ch.get('level', 1)),
                    'active': ch_id == active_id,
                })
        if not roster:
            c = wp.char_data or {}
            roster.append({
                'char_id': active_id,
                'name': str(c.get('name', f'Char#{active_id}')),
                'level': int(c.get('level', 1)),
                'active': True,
            })
        roster.sort(key=lambda r: (not r['active'], r['char_id']))
        entry = {
            'account': account,
            'active_char_id': active_id,
            'active_char_name': str((wp.char_data or {}).get('name', f'Char#{active_id}')),
            'active_char_level': int((wp.char_data or {}).get('level', 1)),
            'characters': roster,
        }
        seen_accounts[account] = entry
        clients.append(entry)
    return clients


def _resolve_player(char_id=None):
    world = GameWorldManager.get()
    if char_id is not None:
        return world.get_player(int(char_id))
    if world.players:
        return next(iter(world.players.values()))
    return None


# ------------------------------------------------------------ command handlers

async def _cmd_lv(ctx: _BridgeCtx, args: List[str]) -> dict:
    if not args:
        return {'ok': False, 'message': 'Usage: lv <1..60>'}
    target, mark_base = apply_level_up(ctx.char, int(args[0]))
    ctx.save()
    await ctx.send(CheatLevelUpAck(result=0, character=Character.from_dict(ctx.char)), f'gm bridge lv={target}')
    await ctx.send(level_up_not(ctx.char), f'gm bridge levelup not lv={target}')
    if mark_base is not None:
        await ctx.send(MarkTabActiveNot(active_mark=True), f'gm bridge mark tab active lv={target}')
        await ctx.send(
            MarkItemActiveNot(base_count=mark_base, bonus_count=int(ctx.char.get('mark_bonus_cnt', 0))),
            f'gm bridge mark item active base={mark_base}',
        )
    return {'ok': True, 'message': f'{ctx.cname}: level set to {target}.'}


async def _cmd_ar(ctx: _BridgeCtx, args: List[str]) -> dict:
    if not args:
        return {'ok': False, 'message': 'Usage: ar <amount>'}
    cur_ar = apply_ar_delta(ctx.char, int(args[0]))
    ctx.save()
    await ctx.send_raw(2104, struct.pack('<Iq', 0, cur_ar), f'gm bridge ar={cur_ar}')
    return {'ok': True, 'message': f'{ctx.cname}: AR is now {cur_ar:,}.'}


async def _cmd_ap(ctx: _BridgeCtx, args: List[str]) -> dict:
    if not args:
        return {'ok': False, 'message': 'Usage: ap <amount>'}
    delta = int(args[0])
    cur_sp, tot_ap = apply_ap_delta(ctx.char, delta)
    ctx.save()
    await ctx.send(InsertApNot(current_ap=cur_sp, total_ap=tot_ap), f'gm bridge ap +{delta}')
    return {'ok': True, 'message': f'{ctx.cname}: +{delta} AP (SP={cur_sp}, total={tot_ap}).'}


async def _cmd_coin(ctx: _BridgeCtx, args: List[str]) -> dict:
    if not args:
        return {'ok': False, 'message': 'Usage: coin <count>'}
    total = apply_rebirth_coins_delta(ctx.char, int(args[0]))
    ctx.save()
    clamped = min(total, 32767)
    await ctx.send_raw(2102, struct.pack('<Ih', 0, clamped), 'gm bridge coin')
    await ctx.send(RebirthCoinChangeNot(result=0, coins=clamped), 'gm bridge coin not')
    return {'ok': True, 'message': f'{ctx.cname}: rebirth coins = {total}.'}


async def _cmd_cash(ctx: _BridgeCtx, args: List[str]) -> dict:
    delta = int(args[0]) if args else 100000
    ctx.char['cash'] = max(0, int(ctx.char.get('cash', 0)) + delta)
    ctx.save()
    return {'ok': True, 'message': f'{ctx.cname}: cash balance = {ctx.char["cash"]:,}.'}


async def _cmd_stress(ctx: _BridgeCtx, args: List[str]) -> dict:
    if not args:
        return {'ok': False, 'message': 'Usage: stress <daily> [pcbang] [weekly]'}
    s_not = apply_stress(
        ctx.char,
        int(args[0]),
        int(args[1]) if len(args) > 1 else None,
        int(args[2]) if len(args) > 2 else None,
    )
    ctx.save()
    await ctx.send(s_not, 'gm bridge stress')
    return {'ok': True, 'message': f'{ctx.cname}: stress set to {ctx.char["stress"]}.'}


async def _cmd_itemcall(ctx: _BridgeCtx, args: List[str]) -> dict:
    if not args:
        return {'ok': False, 'message': 'Usage: itemcall <item_id> [count=1]'}
    code = args[0]
    count = max(1, int(args[1])) if len(args) > 1 else 1
    wire_items = apply_item_call(ctx.char, code, count, owner=UPDATE_OWNER)
    ctx.save()
    await ctx.send(DragItemAck(result=0, items=wire_items), f'gm bridge itemcall {code} x{count}')
    return {'ok': True, 'message': f'{ctx.cname}: spawned {code} x{count}.'}


async def _cmd_clearbag(ctx: _BridgeCtx, _args: List[str]) -> dict:
    deleted = apply_clear_bag(ctx.char)
    ctx.save()
    await ctx.send(CheatDeleteAllInvenItemAck(result=0, items=deleted), f'gm bridge clearbag ({len(deleted)})')
    return {'ok': True, 'message': f'{ctx.cname}: cleared {len(deleted)} bag item(s).'}


async def _cmd_upgrade(ctx: _BridgeCtx, args: List[str]) -> dict:
    if not args:
        return {'ok': False, 'message': 'Usage: upgrade <level>'}
    target_lv = max(0, min(20, int(args[0])))
    changed = apply_equip_upgrade(
        ctx.char, target_lv, lambda it: it.get('container') == EQUIPPED and it.get('slot') == 0
    )
    if not changed:
        return {'ok': False, 'message': f'{ctx.cname}: no matching equipped item found.'}
    ctx.save()
    await ctx.send(DragItemAck(result=0, items=changed), f'gm bridge upgrade +{target_lv}')
    return {'ok': True, 'message': f'{ctx.cname}: set {len(changed)} equipped item(s) to +{target_lv}.'}


async def _cmd_forceupgrade(ctx: _BridgeCtx, args: List[str]) -> dict:
    if len(args) < 2:
        return {'ok': False, 'message': 'Usage: forceupgrade <weapon|cloth> <level>'}
    kind = args[0].lower()
    target_lv = max(0, min(20, int(args[1])))
    slot_filter = (
        (lambda it: it.get('container') == EQUIPPED and it.get('slot') == 0)
        if kind == 'weapon'
        else (lambda it: it.get('container') == EQUIPPED and it.get('slot') != 0)
    )
    changed = apply_equip_upgrade(ctx.char, target_lv, slot_filter)
    if not changed:
        return {'ok': False, 'message': f'{ctx.cname}: no matching equipped item found.'}
    ctx.save()
    await ctx.send(DragItemAck(result=0, items=changed), f'gm bridge forceupgrade +{target_lv}')
    return {'ok': True, 'message': f'{ctx.cname}: set {len(changed)} equipped item(s) to +{target_lv}.'}


async def _cmd_durability(ctx: _BridgeCtx, args: List[str]) -> dict:
    if not args:
        return {'ok': False, 'message': 'Usage: durability <value>'}
    val = max(0, int(args[0]))
    changed = apply_equip_durability(ctx.char, val)
    ctx.save()
    if changed:
        await ctx.send(DragItemAck(result=0, items=changed), f'gm bridge durability={val}')
    return {'ok': True, 'message': f'{ctx.cname}: durability set to {val} on {len(changed)} equipped item(s).'}


async def _cmd_incdepot(ctx: _BridgeCtx, _args: List[str]) -> dict:
    apply_depot_expand(ctx.char, days=30)
    ctx.save()
    await ctx.send(CheatDepotSizeIncreaseAck(result=0), 'gm bridge incdepot')
    return {'ok': True, 'message': f'{ctx.cname}: depot expanded.'}


async def _cmd_skill(ctx: _BridgeCtx, args: List[str]) -> dict:
    if len(args) < 2:
        return {'ok': False, 'message': 'Usage: skill <skill_index> <level>'}
    from darkblood.games.handlers.skills import learned_skill_map
    sidx, slv = apply_learn_skill(ctx.char, int(args[0]), int(args[1]))
    ctx.save()
    ack = LearnSkillListAck(
        result=0,
        skills=learned_skill_map({sidx: slv}),
        remain_sp=int(ctx.char.get('sp', 0)),
        remain_gold=int(ctx.char.get('gold', 0)),
    )
    await ctx.send(ack, f'gm bridge skill {sidx}={slv}')
    return {'ok': True, 'message': f'{ctx.cname}: skill {sidx} set to Lv.{slv}.'}


async def _cmd_skillinit(ctx: _BridgeCtx, _args: List[str]) -> dict:
    sp = apply_skill_reset(ctx.char)
    ctx.save()
    await ctx.send(InitSkillNot(result=0, sp=sp, skills={}), 'gm bridge skillinit')
    return {'ok': True, 'message': f'{ctx.cname}: skills reset, refunded {sp} AP.'}


async def _cmd_questcancel(ctx: _BridgeCtx, _args: List[str]) -> dict:
    apply_quest_reset(ctx.char)
    ctx.save()
    await ctx.send(CheatQuestResetAck(result=0), 'gm bridge questcancel')
    return {'ok': True, 'message': f'{ctx.cname}: active quests cleared.'}


async def _cmd_dualskill(ctx: _BridgeCtx, args: List[str]) -> dict:
    add_days = max(1, int(args[0])) if args else 30
    ds_not = apply_dual_skill(ctx.char, add_days)
    ctx.save()
    await ctx.send(ds_not, f'gm bridge dualskill +{add_days}d')
    return {'ok': True, 'message': f'{ctx.cname}: Dual Skill activated for {add_days} day(s).'}


_BRIDGE_HANDLERS: Dict[str, Callable[[_BridgeCtx, List[str]], Awaitable[dict]]] = {
    'lv': _cmd_lv,
    'ar': _cmd_ar,
    'ap': _cmd_ap,
    'coin': _cmd_coin,
    'cash': _cmd_cash,
    'stress': _cmd_stress,
    'itemcall': _cmd_itemcall,
    'clearbag': _cmd_clearbag,
    'upgrade': _cmd_upgrade,
    'forceupgrade': _cmd_forceupgrade,
    'durability': _cmd_durability,
    'incdepot': _cmd_incdepot,
    'skill': _cmd_skill,
    'skillinit': _cmd_skillinit,
    'questcancel': _cmd_questcancel,
    'dualskill': _cmd_dualskill,
}

SERVER_LIVE_COMMANDS = frozenset(_BRIDGE_HANDLERS)


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

    handler = _BRIDGE_HANDLERS.get(cmd)
    if handler is None:
        return {
            'ok': False,
            'client_only': True,
            'message': f'"{cmd}" is a client-side command. Paste %{raw} in game chat or press Ctrl+Shift+C.',
        }

    player = _resolve_player(char_id)
    if player is None or player.session is None or getattr(player.session, 'transport', None) is None:
        return {'ok': False, 'message': 'No character is currently online in the server.'}

    ctx = _BridgeCtx(
        session=player.session,
        char_id=player.char_id,
        char=player.char_data,
        transport=player.session.transport,
        cname=player.char_data.get('name', f'Char#{player.char_id}'),
    )
    try:
        return await handler(ctx, args)
    except ValueError as exc:
        return {'ok': False, 'message': f'Invalid argument: {exc}'}
    except Exception as exc:
        logger.exception('GM bridge execution failed')
        return {'ok': False, 'message': f'Error: {exc}'}


async def _handle_bridge_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    try:
        line = await asyncio.wait_for(reader.readline(), timeout=5.0)
        if not line:
            return
        req = json.loads(line.decode('utf-8', errors='replace'))
        action = req.get('action')
        if action in ('status', 'list_players'):
            resp = {
                'ok': True,
                'gm_mode': bool(options.get('gm_mode')),
                'players': _list_players(),
                'clients': _list_clients(),
                'live_commands': sorted(SERVER_LIVE_COMMANDS),
            }
        elif action == 'exec':
            resp = await execute_gm_command(
                str(req.get('command', '')),
                char_id=req.get('char_id'),
            )
        else:
            resp = {'ok': False, 'message': f'Unknown action: {action}'}
    except Exception as exc:
        resp = {'ok': False, 'message': str(exc)}
    try:
        writer.write((json.dumps(resp) + '\n').encode('utf-8'))
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
    """Start the localhost GM bridge TCP server (best-effort; returns None if port busy)."""
    try:
        srv = await asyncio.start_server(_handle_bridge_client, host, port)
        logger.info('GM bridge listening on %s:%d', host, port)
        return srv
    except OSError as exc:
        logger.warning('GM bridge could not bind %s:%d: %s', host, port, exc)
        return None
