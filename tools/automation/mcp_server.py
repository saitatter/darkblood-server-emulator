"""MCP (Model Context Protocol) stdio server for driving and inspecting Dark Blood sessions.

Exposes tools/automation/gamectl.py, tools/automation/multibox.py, darkblood.core.options, client hook
build/deploy, opcode lookup, headless tests and generator checks, scratch test characters
(tools/automation/test_data.py), the client shim's breakpoint tracer, and client look-ups
(tools/reverse/client_inspect.py: strings, UI texts, callers, decompiles) to MCP clients.
Newline-delimited JSON-RPC 2.0; the client look-ups need pefile/capstone and Ghidra.

Register (already done in this repo's .mcp.json):
    {"mcpServers": {"darkblood": {"command": "python", "args": ["tools/automation/mcp_server.py"]}}}
"""
import base64
import json
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tools' / 'automation'))
sys.path.insert(0, str(ROOT / 'tools' / 'codegen'))
sys.path.insert(0, str(ROOT / 'tools' / 'reverse'))
sys.path.insert(0, str(ROOT / 'tools' / 'client_data'))

import gamectl  # noqa: E402
import multibox  # noqa: E402
import test_data  # noqa: E402
from darkblood.core import options  # noqa: E402

PROTOCOL = '2024-11-05'


def _num(description):
    return {'type': 'number', 'description': description}


def _str(description):
    return {'type': 'string', 'description': description}


def _bool(description):
    return {'type': 'boolean', 'description': description}


TOOLS = {
    # Single-client & server lifecycle
    'game_start': (
        'Start the local emulator server (127.0.0.1:9400/9401) and/or the Dark Blood test client.',
        {
            'server_only': _bool('Start only the emulator server without launching a client window (default false)'),
            'client_only': _bool('Start only the client against an already running server (default false)'),
            'data_dir': _str('Character database folder for the server (DARKBLOOD_DATA), e.g. a scratch store '
                             'made with test_character_create; default: data/'),
        },
        [],
    ),
    'game_stop': (
        'Stop only the server/client processes started by game_start.',
        {
            'client_only': _bool('Stop only the client (default false)'),
            'server_only': _bool('Stop only the server (default false)'),
        },
        [],
    ),
    'game_status': ('Process and window status of the current gamectl session.', {}, []),

    # Multibox lifecycle
    'multibox_start': (
        'Launch 1-4 Dark Blood clients (side by side or 2x2 grid) against the local server and tile them.',
        {
            'count': _num('Number of clients (1-4, default 2)'),
            'accounts': {'type': 'array', 'items': {'type': 'string'},
                         'description': 'Account names per window (default: OfflinePlayer, Player2, Player3, Player4)'},
            'resize': _bool('Resize windows when tiling (default true)'),
            'layout': _str('Tiling layout: auto (row for 1-2, 2x2 grid for 3-4), grid, or row'),
            'with_server': _bool('Start the local server automatically if not listening (default false)'),
        },
        [],
    ),
    'multibox_status': ('Status of running multibox clients, windows, and server port.', {}, []),
    'multibox_tile': (
        'Re-tile running multibox client windows across the primary monitor.',
        {
            'resize': _bool('Resize windows when tiling (default true)'),
            'layout': _str('Tiling layout: auto (row for 1-2, 2x2 grid for 3-4), grid, or row'),
        },
        [],
    ),
    'multibox_stop': ('Stop only client processes launched by multibox_start.', {}, []),

    # Window interaction
    'game_screenshot': (
        'Capture the game client area as PNG.',
        {'width': _num('Output width in pixels (default 1280)')},
        [],
    ),
    'game_keys': (
        "Press a key chord in the game window, e.g. 'enter', 'esc', 'alt+enter', 'f1'.",
        {'chord': _str('Key chord, parts joined with +')},
        ['chord'],
    ),
    'game_type': ('Type text into the focused game control.', {'text': _str('Text to type')}, ['text']),
    'game_click': (
        'Click in the game client area. x/y <= 1 are fractions of width/height, larger values are pixels.',
        {
            'x': _num('X position'),
            'y': _num('Y position'),
            'button': {'type': 'string', 'enum': ['left', 'right']},
            'double': _bool('Double-click'),
        },
        ['x', 'y'],
    ),
    'game_skip_intro': (
        'Click through the start-up cinematics until the Server List is shown.',
        {'timeout': _num('Seconds (default 60)')},
        [],
    ),
    'game_enter_lobby': (
        'From a fresh launch: skip the intro, pick the local server and channel, and wait for character select.',
        {}, [],
    ),
    'game_select_character': (
        'Confirm the currently selected character on Character Select screen (sends opcode 2006).',
        {}, [],
    ),

    # Wire & shim inspection
    'game_events': (
        'Decoded protocol log for this session (client requests, server responses, errors).',
        {
            'include_transport': _bool('Include raw ProudNet transport frames (default false)'),
            'opcode': _num('Optional opcode filter, e.g. 5064'),
            'only_errors': _bool('Show only unhandled-event / bad-request / invalid-login lines (default false)'),
            'limit': _num('Max rows (default 60)'),
        },
        [],
    ),
    'game_wait_event': (
        'Wait until the client sends a given opcode.',
        {
            'opcode': _num('Opcode, e.g. 2008'),
            'count': _num('Occurrences (default 1)'),
            'timeout': _num('Seconds (default 30)'),
        },
        ['opcode'],
    ),
    'game_hook_log': (
        'Tail of the client shim log (hook_log.txt or hook_log.<account>.txt for multibox).',
        {
            'lines': _num('Lines (default 40)'),
            'account': _str('Optional account name for per-window multibox log, e.g. Player2'),
        },
        [],
    ),

    # Config, hook build, protocol lookup, headless tests
    'config_get': (
        'Read darkblood_options.ini (network host/ports, launcher settings, and all client/server patches).',
        {}, [],
    ),
    'config_set': (
        'Update darkblood_options.ini network settings, launcher account/clients, or client/server patch toggles.',
        {
            'host': _str('Target server IP or hostname'),
            'port': _num('Target game port (1-65535)'),
            'relay_port': _num('Target relay port (1-65535)'),
            'account': _str('Default account name'),
            'clients': _num('Default client count (1-4)'),
            'patches': {'type': 'object', 'description': 'Map of patch_key -> boolean (e.g. {"skip_logos": true})'},
        },
        [],
    ),
    'hook_build_deploy': (
        'Compile the modular client_hook/steam_api.dll via MSVC x86 and deploy it to research/client/.',
        {}, [],
    ),
    'opcode_lookup': (
        'Look up an opcode by number or enum substring: shows enum name, client handler VA, server handler, and message classes.',
        {'query': _str('Opcode number (e.g. "2545") or substring (e.g. "DECOMPOSE")')},
        ['query'],
    ),
    'run_headless_tests': (
        'Run the headless Python unittest suite (all tests or a specific module like "tests/test_inventory_flow.py").',
        {'target': _str('Optional test path or dotted module; omit to run full suite')},
        [],
    ),
    'codegen_check': (
        'Run the generator --check modes (gen_messages, gen_progress as in CI; extract_gtargets when the '
        'client maps are present) and report which outputs are stale.',
        {}, [],
    ),

    # Live-test data
    'test_character_create': (
        'Create a character in a scratch character database (never data/) for a live test. Create it before '
        'game_start(data_dir=...): the server caches the store.',
        {
            'data_dir': _str('Scratch database folder (created if missing)'),
            'name': _str('Character name'),
            'account': _str('Account (default OfflinePlayer, the launcher default)'),
            'char_class': _num('Class id (default 1)'),
            'level': _num('Level (default 1)'),
            'gold': _num('AR (default 0)'),
            'skills': {'type': 'object', 'description': 'skill index -> level, e.g. {"9007": 1} (Mining)'},
            'items': {'type': 'array', 'items': {'type': 'array'},
                      'description': '[[ItemID, count], ...] added to the bags, e.g. [["ILurN1", 5]]'},
            'layer': _str('Spawn town layer as Square:index, e.g. "Act1:4" (waypoint act1_02)'),
        },
        ['data_dir', 'name'],
    ),

    # Client analysis
    'client_breakpoints': (
        'Read or replace research/client/bp.txt, the shim INT3 tracer (read when the client starts; hits go to '
        'the hook log as [BP] lines). Lines: "<hex VA> [max=N] [reg+off] [reg+off.N] [@reg+off+off2]".',
        {
            'lines': {'type': 'array', 'items': {'type': 'string'}, 'description': 'New breakpoint lines'},
            'clear': _bool('Delete bp.txt (default false)'),
        },
        [],
    ),
    'client_strings': (
        'Read ASCII/UTF-16 strings at virtual addresses of the client (static fixture).',
        {'addresses': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Hex VAs, e.g. ["0xC95B88"]'}},
        ['addresses'],
    ),
    'client_text': (
        'Look up localized client texts (UI_*, JERI_*, GAME_*, Item_*, ...) in localization_st/*.dat.',
        {'keys': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Keys, e.g. ["UI_2933"]'}},
        ['keys'],
    ),
    'client_callers': (
        'Find direct call sites of client functions and the functions that contain them.',
        {'addresses': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Hex VAs of callees'}},
        ['addresses'],
    ),
    'client_decompile': (
        'Focused Ghidra decompile (tools/reverse/decomp.ps1) of client functions; pass function start '
        'addresses (client_callers reports them). Slow (about a minute per call).',
        {'addresses': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Hex VAs of function starts'}},
        ['addresses'],
    ),
}


def _hook_log_for_account(lines=40, account=None):
    if account:
        path = gamectl.LAB / f'hook_log.{account}.txt'
        if not path.is_file():
            return f'(no log file: {path.name})'
        return '\n'.join(path.read_text(encoding='utf-8', errors='replace').splitlines()[-lines:])
    return '\n'.join(gamectl.hook_log(lines))


def _filtered_events(include_transport=False, opcode=None, only_errors=False, limit=60):
    rows = gamectl.events(include_transport=include_transport, limit=max(limit * 4, 200))
    if opcode is not None:
        needle = f' {int(opcode)} '
        needle_eq = f'opcode={int(opcode)}'
        rows = [r for r in rows if needle in r or needle_eq in r or r.startswith(f'{int(opcode)} ')]
    if only_errors:
        err_keys = ('unhandled-event', 'bad-request', 'bad-event', 'invalid-login', 'unauthenticated')
        rows = [r for r in rows if any(k in r for k in err_keys)]
    return '\n'.join(rows[-limit:]) or '(no matching events)'


def _opcode_lookup(query):
    import gen_opcode_registry as reg
    q = str(query).strip()
    names = reg.client_names()
    client = reg.client_handlers()
    server = reg.server_handlers()
    classes = reg.message_classes()
    matches = []
    if q.isdigit():
        op = int(q)
        if op in names or op in server or op in classes:
            matches = [op]
    else:
        qu = q.upper()
        matches = [op for op, name in sorted(names.items()) if qu in name.upper()][:25]
    if not matches:
        return f'No opcodes matching {query!r}'
    out = []
    for op in matches:
        srv_mod, srv_note = server.get(op, ('—', ''))
        msgs = ', '.join(sorted(classes.get(op, []))) or '—'
        out.append({
            'opcode': op,
            'enum': names.get(op, '?'),
            'client_handler': client.get(op, '—'),
            'server_handler': srv_mod,
            'messages': msgs,
            'notes': srv_note,
        })
    return out


def _build_and_deploy_hook():
    bat = ROOT / 'client_hook' / 'build.bat'
    built = ROOT / 'client_hook' / 'steam_api.dll'
    dest = gamectl.LAB / 'steam_api.dll'
    proc = subprocess.run(['cmd.exe', '/c', str(bat)], cwd=str(bat.parent),
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise gamectl.GameError(f'Hook build failed:\n{proc.stdout}\n{proc.stderr}'.strip())
    if gamectl.LAB.is_dir():
        shutil.copy2(built, dest)
    return {'built': str(built), 'deployed': str(dest) if dest.exists() else None, 'output': proc.stdout.strip()}


def _run_tests(target=None):
    if target:
        cmd = [sys.executable, '-m', 'unittest', target, '-v']
    else:
        cmd = [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-q']
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    return {
        'ok': proc.returncode == 0,
        'returncode': proc.returncode,
        'output': (proc.stdout + '\n' + proc.stderr).strip(),
    }


def _check_generators():
    import extract_gtargets
    checks = [
        ('gen_messages', [sys.executable, 'tools/codegen/gen_messages.py', '--check']),
        ('gen_progress', [sys.executable, 'tools/codegen/gen_progress.py', '--check']),
    ]
    if extract_gtargets.DEFAULT_MAPS.is_dir():
        checks.append(('extract_gtargets', [sys.executable, 'tools/client_data/extract_gtargets.py', '--check']))
    results = {}
    for label, cmd in checks:
        proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
        results[label] = {'ok': proc.returncode == 0, 'output': (proc.stdout + proc.stderr).strip()}
    return results


def _breakpoints(lines=None, clear=False):
    path = gamectl.LAB / 'bp.txt'
    if clear:
        if path.exists():
            path.unlink()
    elif lines is not None:
        path.write_text('\n'.join(lines) + '\n', encoding='ascii')
    return {'path': str(path), 'lines': path.read_text(encoding='ascii').splitlines() if path.exists() else [],
            'note': 'bp.txt is read when the client starts: restart it (game_stop client_only, game_start '
                    'client_only) and read hits with game_hook_log.'}


def _addresses(values):
    return [int(str(v), 16) for v in values]


def call_tool(name, args):
    if name == 'game_start':
        return gamectl.start(server_only=bool(args.get('server_only', False)),
                             client_only=bool(args.get('client_only', False)),
                             data_dir=args.get('data_dir') or None)
    if name == 'game_stop':
        return gamectl.stop(client_only=bool(args.get('client_only', False)),
                            server_only=bool(args.get('server_only', False)))
    if name == 'game_status':
        return gamectl.status()
    if name == 'multibox_start':
        return multibox.start(
            count=int(args.get('count', 2)),
            resize=bool(args.get('resize', True)),
            accounts=args.get('accounts'),
            layout=str(args.get('layout', 'auto')),
            with_server=bool(args.get('with_server', False)),
        )
    if name == 'multibox_status':
        return multibox.status()
    if name == 'multibox_tile':
        return {'tiled': multibox.tile(
            resize=bool(args.get('resize', True)),
            layout=str(args.get('layout', 'auto')),
        )}
    if name == 'multibox_stop':
        return multibox.stop()
    if name == 'game_screenshot':
        png = gamectl.screenshot(width=int(args.get('width', 1280)))
        return {'image': base64.b64encode(png).decode('ascii')}
    if name == 'game_keys':
        return gamectl.keys(args['chord'])
    if name == 'game_type':
        return gamectl.type_text(args['text'])
    if name == 'game_click':
        return gamectl.click(float(args['x']), float(args['y']), args.get('button', 'left'),
                             bool(args.get('double', False)))
    if name == 'game_skip_intro':
        return gamectl.skip_intro(int(args.get('timeout', 60)))
    if name == 'game_enter_lobby':
        return gamectl.enter_lobby()
    if name == 'game_select_character':
        return gamectl.select_character()
    if name == 'game_events':
        return _filtered_events(
            include_transport=bool(args.get('include_transport')),
            opcode=args.get('opcode'),
            only_errors=bool(args.get('only_errors')),
            limit=int(args.get('limit', 60)),
        )
    if name == 'game_wait_event':
        ok = gamectl.wait_event(int(args['opcode']), int(args.get('count', 1)), int(args.get('timeout', 30)))
        return 'seen' if ok else 'timeout'
    if name == 'game_hook_log':
        return _hook_log_for_account(int(args.get('lines', 40)), args.get('account'))
    if name == 'config_get':
        cfg = options.read_all()
        cfg['path'] = str(options.OPTIONS_PATH)
        cfg['patch_sources'] = {k: options.PATCH_META[k][1] for k in options.OPTIONS}
        return cfg
    if name == 'config_set':
        net = None
        if any(k in args for k in ('host', 'port', 'relay_port')):
            cur = options.read_network()
            net = {
                'host': args.get('host', cur['host']),
                'port': args.get('port', cur['port']),
                'relay_port': args.get('relay_port', cur['relay_port']),
            }
        lnch = None
        if any(k in args for k in ('account', 'clients')):
            cur = options.read_launcher()
            lnch = {
                'account': args.get('account', cur['account']),
                'clients': args.get('clients', cur['clients']),
            }
        patches = args.get('patches')
        options.write_all(values=patches, network=net, launcher=lnch)
        return options.read_all()
    if name == 'hook_build_deploy':
        return _build_and_deploy_hook()
    if name == 'opcode_lookup':
        return _opcode_lookup(args['query'])
    if name == 'run_headless_tests':
        return _run_tests(args.get('target'))
    if name == 'codegen_check':
        return _check_generators()
    if name == 'test_character_create':
        layer = None
        if args.get('layer'):
            square, _, idx = str(args['layer']).partition(':')
            layer = (square, int(idx or 0))
        return test_data.create_character(
            args['data_dir'], args['name'], account=args.get('account', 'OfflinePlayer'),
            char_class=args.get('char_class', 1), level=args.get('level', 1), gold=args.get('gold', 0),
            skills=args.get('skills') or {}, items=[tuple(i) for i in args.get('items') or []], layer=layer)
    if name == 'client_breakpoints':
        return _breakpoints(args.get('lines'), bool(args.get('clear')))
    if name in ('client_strings', 'client_text', 'client_callers', 'client_decompile'):
        import client_inspect
        if name == 'client_text':
            return client_inspect.ui_text([str(k) for k in args['keys']])
        addresses = _addresses(args['addresses'])
        if name == 'client_strings':
            return client_inspect.strings(addresses)
        if name == 'client_callers':
            return client_inspect.callers(addresses)
        return client_inspect.decompile(addresses)
    raise KeyError(name)


def content(result):
    if isinstance(result, dict) and 'image' in result:
        return [{'type': 'image', 'data': result['image'], 'mimeType': 'image/png'}]
    text = result if isinstance(result, str) else json.dumps(result, indent=2)
    return [{'type': 'text', 'text': text}]


def handle(request):
    method = request.get('method')
    params = request.get('params') or {}
    if method == 'initialize':
        return {'protocolVersion': params.get('protocolVersion', PROTOCOL),
                'capabilities': {'tools': {}},
                'serverInfo': {'name': 'darkblood-emulator', 'version': '0.3.0'}}
    if method == 'ping':
        return {}
    if method == 'tools/list':
        return {'tools': [{'name': name, 'description': description,
                           'inputSchema': {'type': 'object', 'properties': props, 'required': required}}
                          for name, (description, props, required) in TOOLS.items()]}
    if method == 'tools/call':
        name = params.get('name')
        try:
            return {'content': content(call_tool(name, params.get('arguments') or {}))}
        except (gamectl.GameError, ValueError, RuntimeError) as exc:
            return {'content': [{'type': 'text', 'text': 'error: %s' % exc}], 'isError': True}
        except Exception:  # report tool failures to the client instead of dying
            return {'content': [{'type': 'text', 'text': traceback.format_exc()}], 'isError': True}
    raise LookupError(method)


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except ValueError:
            continue
        if 'id' not in request:  # notification
            continue
        try:
            reply = {'jsonrpc': '2.0', 'id': request['id'], 'result': handle(request)}
        except LookupError:
            reply = {'jsonrpc': '2.0', 'id': request['id'],
                     'error': {'code': -32601, 'message': 'Method not found'}}
        sys.stdout.write(json.dumps(reply) + '\n')
        sys.stdout.flush()


if __name__ == '__main__':
    main()
