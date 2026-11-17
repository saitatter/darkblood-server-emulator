"""Shared toggles in research/client/darkblood_options.ini (edited by tools/patcher.py).

[client] keys are applied by the shim at SteamAPI_Init (client restart needed);
[server] keys are read by the server when they are used.
"""
import configparser
import os
from pathlib import Path

from darkblood import REPO_ROOT

OPTIONS_PATH = Path(os.environ.get('DARKBLOOD_OPTIONS', REPO_ROOT / 'research' / 'client' / 'darkblood_options.ini'))

# key -> (section, default, label, description). Order is the GUI order.
OPTIONS = {
    'skip_logos': ('client', False, 'Skip start-up logos',
                   'Ends the logo clips at once (JAppStateLogo 0x006F39AB, je -> jmp).'),
    'skip_tutorial_always': ('client', False, 'Esc always skips the tutorial',
                             "Also on an account's first character (0x006FBCEE, sete -> mov bl,1)."),
    'adult_content': ('server', True, 'Adult content (blood effect)',
                      'm_bAdultUser in the welcome (5020); unlocks the Blood Effect option.'),
}


def read():
    parser = configparser.ConfigParser()
    parser.read(OPTIONS_PATH, encoding='utf-8')
    return {key: parser.getboolean(section, key, fallback=default)
            for key, (section, default, _, _) in OPTIONS.items()}


def write(values):
    parser = configparser.ConfigParser()
    for key, (section, default, label, _) in OPTIONS.items():
        if not parser.has_section(section):
            parser.add_section(section)
        parser.set(section, key, '1' if values.get(key, default) else '0')
    OPTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OPTIONS_PATH, 'w', encoding='utf-8') as stream:
        stream.write('; Dark Blood emulator options (tools/patcher.py). [client] keys need a client restart.\n')
        parser.write(stream)


def get(key):
    return read()[key]
