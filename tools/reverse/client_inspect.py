"""Quick look-ups in the client binary and its data: strings, UI texts, callers, decompiles.

Works on research/unpacked.analysis.exe (static fixture, never run it) and on the
extracted client data (../darkblood-client-data). Needs pefile and capstone.

Usage:
    python tools/reverse/client_inspect.py strings 0xC95B88 0xCF6C48
    python tools/reverse/client_inspect.py text UI_2933 JERI_FISHING_05
    python tools/reverse/client_inspect.py callers 0x7A1FF0
    python tools/reverse/client_inspect.py decompile 0x00776400 [0x...]
"""
import argparse
import struct
import subprocess
import sys
import tempfile
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / 'research' / 'unpacked.analysis.exe'
LOCALIZATION = ROOT.parent / 'darkblood-client-data' / 'files' / 'data' / 'localization_st'
DECOMP = Path(__file__).resolve().parent / 'decomp.ps1'
PROLOGUE_BYTES = (0x55, 0x6A, 0x83, 0x81, 0x53, 0x56, 0x57, 0x8B, 0x64, 0x51, 0xA1, 0xB8)


@lru_cache(maxsize=None)
def _image():
    import pefile
    pe = pefile.PE(str(FIXTURE), fast_load=True)
    return pe, pe.OPTIONAL_HEADER.ImageBase, pe.get_memory_mapped_image()


def strings(addresses):
    """{va: (ascii, utf16)} read at each virtual address (each up to its NUL)."""
    _, base, img = _image()
    out = {}
    for va in addresses:
        raw = img[va - base:va - base + 256]
        ascii_text = raw.split(b'\0', 1)[0].decode('latin-1')
        wide = raw.decode('utf-16le', errors='replace').split('\0', 1)[0]
        out[hex(va)] = {'ascii': ascii_text, 'utf16': wide}
    return out


def ui_text(keys):
    """Localized English text of UI_/JERI_/GAME_... keys from localization_st/*.dat."""
    wanted, found = set(keys), {}
    for path in sorted(LOCALIZATION.glob('*.dat')):
        for line in path.read_bytes().decode('utf-16', errors='replace').splitlines():
            key, _, value = line.partition('\t')
            if key.strip() in wanted:
                found[key.strip()] = {'file': path.name, 'text': value}
    return {key: found.get(key) for key in keys}


def function_start(va):
    """Nearest preceding function start (padding followed by a common prologue byte)."""
    _, base, img = _image()
    off = va - base
    while off > 0:
        if (img[off - 1] in (0xCC, 0x90, 0xC3) and img[off - 2] in (0xCC, 0x90, 0xC3, 0x00)
                and img[off] in PROLOGUE_BYTES):
            return base + off
        off -= 1
    return None


def callers(targets):
    """Direct `call rel32` sites of each target, with the containing function start."""
    pe, base, img = _image()
    found = {hex(t): [] for t in targets}
    wanted = set(targets)
    for sec in pe.sections:
        if not sec.Characteristics & 0x20000000:  # executable
            continue
        start = sec.VirtualAddress
        data = img[start:start + sec.Misc_VirtualSize]
        for i in range(len(data) - 5):
            if data[i] != 0xE8:
                continue
            dest = (base + start + i + 5 + struct.unpack_from('<i', data, i + 1)[0]) & 0xFFFFFFFF
            if dest in wanted:
                site = base + start + i
                fn = function_start(site)
                found[hex(dest)].append({'call': hex(site), 'function': hex(fn) if fn else None})
    return found


def decompile(addresses, timeout=600):
    """Focused Ghidra decompile (tools/reverse/decomp.ps1) of function start addresses."""
    with tempfile.TemporaryDirectory(prefix='darkblood_decomp_') as tmp:
        out = Path(tmp) / 'out.c'
        cmd = ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(DECOMP), str(out)]
        cmd += ['0x%08X' % a for a in addresses]
        proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=timeout)
        if not out.exists():
            raise RuntimeError(f'decompile failed:\n{proc.stdout}\n{proc.stderr}'.strip())
        return out.read_text(encoding='utf-8', errors='replace')


def _address(text):
    return int(text, 16)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('strings', 'callers', 'decompile'):
        sub.add_parser(name).add_argument('addresses', nargs='+', type=_address)
    sub.add_parser('text').add_argument('keys', nargs='+')
    args = parser.parse_args(argv)
    if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
    if args.command == 'decompile':
        print(decompile(args.addresses))
        return 0
    import json
    result = {'strings': strings, 'callers': callers}.get(args.command)
    print(json.dumps(result(args.addresses) if result else ui_text(args.keys), indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
