"""MCP (Model Context Protocol) stdio server for driving a Dark Blood session.

Exposes tools/gamectl.py to MCP clients (Claude Code, etc.): start/stop the
emulator and client, screenshots, keyboard/mouse input, decoded protocol
events and shim logs. Standard library only; newline-delimited JSON-RPC 2.0.

Register (already done in this repo's .mcp.json):
    {"mcpServers": {"darkblood": {"command": "python", "args": ["tools/mcp_server.py"]}}}
"""
import base64
import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gamectl  # noqa: E402

PROTOCOL = '2024-11-05'


def _num(description):
    return {'type': 'number', 'description': description}


def _str(description):
    return {'type': 'string', 'description': description}


TOOLS = {
    'game_start': ('Start the local emulator server (127.0.0.1:9400) and the Dark Blood test client. '
                   'Fails if a session is already running.', {}, []),
    'game_stop': ('Stop only the server/client processes started by game_start.', {}, []),
    'game_status': ('Process and window status of the current session.', {}, []),
    'game_screenshot': ('Capture the game client area as PNG.',
                        {'width': _num('Output width in pixels (default 1280)')}, []),
    'game_keys': ("Press a key chord in the game window, e.g. 'enter', 'esc', 'alt+enter', 'f1'.",
                  {'chord': _str('Key chord, parts joined with +')}, ['chord']),
    'game_type': ('Type text into the focused game control.', {'text': _str('Text to type')}, ['text']),
    'game_click': ('Click in the game client area. x/y <= 1 are fractions of width/height, '
                   'larger values are pixels in the client area.',
                   {'x': _num('X position'), 'y': _num('Y position'),
                    'button': {'type': 'string', 'enum': ['left', 'right']},
                    'double': {'type': 'boolean'}}, ['x', 'y']),
    'game_skip_intro': ('Click through the start-up cinematics until the Server List is shown.',
                        {'timeout': _num('Seconds (default 60)')}, []),
    'game_enter_lobby': ('From a fresh launch: skip the intro, pick the local server and channel, '
                         'and wait for character select.', {}, []),
    'game_select_character': ('Confirm the currently selected character on Character Select screen (sends opcode 2006).', {}, []),
    'game_events': ('Decoded protocol log for this session: client requests (opcode + enum name), '
                    'server responses, handshake steps.',
                    {'include_transport': {'type': 'boolean'}, 'limit': _num('Max rows (default 60)')}, []),
    'game_wait_event': ('Wait until the client sends a given opcode.',
                        {'opcode': _num('Opcode, e.g. 2008'), 'count': _num('Occurrences (default 1)'),
                         'timeout': _num('Seconds (default 30)')}, ['opcode']),
    'game_hook_log': ('Tail of the client shim log (Steam shim, redirect, breakpoints, samples).',
                      {'lines': _num('Lines (default 40)')}, []),
}


def call_tool(name, args):
    if name == 'game_start':
        return gamectl.start()
    if name == 'game_stop':
        return gamectl.stop()
    if name == 'game_status':
        return gamectl.status()
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
        return '\n'.join(gamectl.events(include_transport=bool(args.get('include_transport')),
                                        limit=int(args.get('limit', 60)))) or '(no events)'
    if name == 'game_wait_event':
        ok = gamectl.wait_event(int(args['opcode']), int(args.get('count', 1)), int(args.get('timeout', 30)))
        return 'seen' if ok else 'timeout'
    if name == 'game_hook_log':
        return '\n'.join(gamectl.hook_log(int(args.get('lines', 40))))
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
                'serverInfo': {'name': 'darkblood-emulator', 'version': '0.1.0'}}
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
        except gamectl.GameError as exc:
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
