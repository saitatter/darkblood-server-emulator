"""Shared configuration in research/client/darkblood_options.ini (edited by tools/launcher.py).

Sections:
  [network]  - Server host, game port, and relay port used by patches/network_redirect.c.
  [launcher] - Default account name and client count for tools/launcher.py / steam_api.dll.
  [client]   - Per-file client patches/hooks loaded by steam_api.dll on SteamAPI_Init.
  [server]   - Server-side toggles read by the Python server when used.
"""
import configparser
import os
from pathlib import Path

from darkblood import REPO_ROOT

OPTIONS_PATH = Path(os.environ.get(
    'DARKBLOOD_OPTIONS', REPO_ROOT / 'research' / 'client' / 'darkblood_options.ini'))

NETWORK_DEFAULTS = {
    'host': '127.0.0.1',
    'port': 9400,
    'relay_port': 9401,
}

LAUNCHER_DEFAULTS = {
    'account': 'OfflinePlayer',
    'clients': 1,
}

# key -> (section, default, label, description). Order is the GUI order.
OPTIONS = {
    'borderless_fullscreen': (
        'client', True, 'Borderless fullscreen',
        'Converts exclusive fullscreen into a monitor-pinned borderless popup window.',
    ),
    'auto_reconnect': (
        'client', True, 'Return to server list on disconnect',
        'Returns to the lobby on disconnect instead of exiting, with reconnect crash guards.',
    ),
    'peer_update_interval': (
        'client', True, 'Faster town peer sync (100 ms)',
        'Lowers the town P2P position revision throttle from 2000 ms to 100 ms (0x00966C9C).',
    ),
    'char_slots_14': (
        'client', True, '14 character slots counter (X / 14)',
        'Updates the character select slot label from "X / 6" to "X / 14" (0x006DD64A).',
    ),
    'skip_logos': (
        'client', True, 'Skip start-up logos',
        'Ends the logo clips at once (JAppStateLogo 0x006F39AB, je -> jmp).',
    ),
    'skip_tutorial_always': (
        'client', True, 'Always allow tutorial skip (Esc)',
        "Allows skipping the tutorial even on an account's first character (0x006FBCEE).",
    ),
    'adult_content': (
        'server', True, 'Adult content (blood effect)',
        'Sets m_bAdultUser in the welcome (5020); unlocks the Blood Effect option.',
    ),
    'gm_mode': (
        'server', True, 'GM console & cheat commands',
        'Sets nAuthLevel=1 in welcome (5020), unlocking the native in-game GM console.',
    ),
    'diagnostic_hooks': (
        'client', True, 'Protocol & handler diagnostics',
        'Logs ProudNet join/welcome/messages and writes handler_map.txt on connect.',
    ),
    'debug_tools': (
        'client', True, 'Breakpoint tracer & sampler',
        'Enables bp.txt INT3 tracer and sample.txt thread sampler when those files exist.',
    ),
}

# Category and backing implementation file for each option (used by the launcher UI).
PATCH_META = {
    'borderless_fullscreen': ('improvement', 'patches/borderless_fullscreen.c'),
    'auto_reconnect':        ('improvement', 'patches/auto_reconnect.c'),
    'peer_update_interval':  ('improvement', 'patches/peer_update_interval.c'),
    'char_slots_14':         ('improvement', 'patches/char_slots.c'),
    'skip_logos':            ('hack',        'patches/skip_logos.c'),
    'skip_tutorial_always':  ('hack',        'patches/skip_tutorial_always.c'),
    'adult_content':         ('server',      'server/frontend.py'),
    'gm_mode':               ('server',      'server/gm.py'),
    'diagnostic_hooks':      ('diagnostic',  'patches/diagnostic_hooks.c'),
    'debug_tools':           ('diagnostic',  'patches/debug_tools.c'),
}

CATEGORIES = (
    ('improvement', 'Improvements & QoL (Client)'),
    ('hack',        'Hacks & Gameplay (Client)'),
    ('server',      'Server Behaviour'),
    ('diagnostic',  'Diagnostics & Dev Tools (Client)'),
)


def _load_parser():
    parser = configparser.ConfigParser()
    parser.read(OPTIONS_PATH, encoding='utf-8')
    return parser


def _parse_port(raw, default):
    try:
        port = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return port if 1 <= port <= 65535 else default


def validate_network(host, port, relay_port=None):
    """Validate and normalize network settings; raises ValueError on bad input."""
    host_str = (host or '').strip()
    if not host_str or any(ch.isspace() for ch in host_str):
        raise ValueError('Server IP/host must be a non-empty hostname or IPv4 address')
    try:
        port_int = int(str(port).strip())
    except (TypeError, ValueError):
        raise ValueError('Game port must be an integer between 1 and 65535')
    if not (1 <= port_int <= 65535):
        raise ValueError('Game port must be between 1 and 65535')
    if relay_port is None or str(relay_port).strip() == '':
        relay_int = NETWORK_DEFAULTS['relay_port']
    else:
        try:
            relay_int = int(str(relay_port).strip())
        except (TypeError, ValueError):
            raise ValueError('Relay port must be an integer between 1 and 65535')
        if not (1 <= relay_int <= 65535):
            raise ValueError('Relay port must be between 1 and 65535')
    return {'host': host_str, 'port': port_int, 'relay_port': relay_int}


def read():
    """Return boolean toggle values for all OPTIONS."""
    parser = _load_parser()
    return {key: parser.getboolean(section, key, fallback=default)
            for key, (section, default, _, _) in OPTIONS.items()}


def read_network():
    """Return [network] settings: host, port, relay_port."""
    parser = _load_parser()
    host = parser.get('network', 'host', fallback=NETWORK_DEFAULTS['host']).strip()
    if not host:
        host = NETWORK_DEFAULTS['host']
    port = _parse_port(parser.get('network', 'port', fallback=str(NETWORK_DEFAULTS['port'])),
                       NETWORK_DEFAULTS['port'])
    relay_port = _parse_port(
        parser.get('network', 'relay_port', fallback=str(NETWORK_DEFAULTS['relay_port'])),
        NETWORK_DEFAULTS['relay_port'])
    return {'host': host, 'port': port, 'relay_port': relay_port}


def read_launcher():
    """Return [launcher] settings: account, clients."""
    parser = _load_parser()
    account = parser.get('launcher', 'account', fallback=LAUNCHER_DEFAULTS['account']).strip()
    if not account:
        account = LAUNCHER_DEFAULTS['account']
    try:
        clients = int(parser.get('launcher', 'clients', fallback=str(LAUNCHER_DEFAULTS['clients'])))
    except (TypeError, ValueError):
        clients = LAUNCHER_DEFAULTS['clients']
    clients = max(1, min(4, clients))
    return {'account': account, 'clients': clients}


def read_all():
    """Return full configuration dictionary: network, launcher, and options."""
    return {
        'network': read_network(),
        'launcher': read_launcher(),
        'options': read(),
    }


def write_all(values=None, network=None, launcher=None):
    """Write configuration to OPTIONS_PATH, preserving unspecified sections."""
    current = read_all()
    opts = dict(current['options'])
    if values is not None:
        for key, (_, default, _, _) in OPTIONS.items():
            if key in values:
                opts[key] = bool(values[key])
            elif key not in opts:
                opts[key] = default

    net = dict(current['network'])
    if network is not None:
        net = validate_network(
            network.get('host', net['host']),
            network.get('port', net['port']),
            network.get('relay_port', net['relay_port']),
        )

    lnch = dict(current['launcher'])
    if launcher is not None:
        acc = (launcher.get('account', lnch['account']) or '').strip()
        lnch['account'] = acc or LAUNCHER_DEFAULTS['account']
        try:
            cnt = int(launcher.get('clients', lnch['clients']))
        except (TypeError, ValueError):
            cnt = LAUNCHER_DEFAULTS['clients']
        lnch['clients'] = max(1, min(4, cnt))

    parser = configparser.ConfigParser()
    parser.add_section('network')
    parser.set('network', 'host', net['host'])
    parser.set('network', 'port', str(net['port']))
    parser.set('network', 'relay_port', str(net['relay_port']))

    parser.add_section('launcher')
    parser.set('launcher', 'account', lnch['account'])
    parser.set('launcher', 'clients', str(lnch['clients']))

    for key, (section, default, _, _) in OPTIONS.items():
        if not parser.has_section(section):
            parser.add_section(section)
        parser.set(section, key, '1' if opts.get(key, default) else '0')

    OPTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OPTIONS_PATH, 'w', encoding='utf-8') as stream:
        stream.write(
            '; Dark Blood custom launcher & emulator options (tools/launcher.py).\n'
            '; [network] and [client] keys are applied by steam_api.dll on client start.\n'
            '; [server] keys are read by the Python server.\n'
        )
        parser.write(stream)


def write(values):
    """Write boolean toggle values while preserving [network] and [launcher]."""
    write_all(values=values)


def get(key):
    return read()[key]
