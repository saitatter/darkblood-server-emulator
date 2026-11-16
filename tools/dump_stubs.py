#!/usr/bin/env python3
"""Read-only dump of a running client's memory regions and module list.

Opens the process with PROCESS_QUERY_INFORMATION | PROCESS_VM_READ only (no
debugger attach, no writes) and saves committed regions in [lo, hi) plus the
loaded module table, so protector stubs (e.g. ``nop; call 0x600xxxxx``) can be
resolved offline with tools/resolve_stubs.py.

    python tools/dump_stubs.py PID --lo 0x60000000 --hi 0x62000000 -o research/stubs
"""
import argparse
import ctypes
import ctypes.wintypes as wt
import json
from pathlib import Path

k32 = ctypes.WinDLL('kernel32', use_last_error=True)
psapi = ctypes.WinDLL('psapi', use_last_error=True)


class MBI(ctypes.Structure):
    _fields_ = [('BaseAddress', ctypes.c_void_p), ('AllocationBase', ctypes.c_void_p),
                ('AllocationProtect', wt.DWORD), ('RegionSize', ctypes.c_size_t),
                ('State', wt.DWORD), ('Protect', wt.DWORD), ('Type', wt.DWORD)]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('pid', type=int)
    ap.add_argument('--lo', type=lambda s: int(s, 0), default=0x60000000)
    ap.add_argument('--hi', type=lambda s: int(s, 0), default=0x62000000)
    ap.add_argument('-o', '--out', type=Path, required=True)
    a = ap.parse_args()
    h = k32.OpenProcess(0x0400 | 0x0010, False, a.pid)
    if not h:
        raise OSError(ctypes.get_last_error(), 'OpenProcess')
    a.out.mkdir(parents=True, exist_ok=True)
    regions, addr = [], a.lo
    mbi = MBI()
    while addr < a.hi and k32.VirtualQueryEx(h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
        base, size = mbi.BaseAddress or 0, mbi.RegionSize
        if mbi.State == 0x1000 and not (mbi.Protect & 0x101):  # committed, not NOACCESS/GUARD
            buf = ctypes.create_string_buffer(size)
            got = ctypes.c_size_t()
            if k32.ReadProcessMemory(h, ctypes.c_void_p(base), buf, size, ctypes.byref(got)):
                (a.out / ('%08x.bin' % base)).write_bytes(buf.raw[:got.value])
                regions.append(dict(base=base, size=got.value, protect=mbi.Protect, type=mbi.Type))
        addr = base + size
    mods = (wt.HMODULE * 1024)()
    need = wt.DWORD()
    psapi.EnumProcessModulesEx(h, mods, ctypes.sizeof(mods), ctypes.byref(need), 3)
    modules = []
    for m in mods[:need.value // ctypes.sizeof(wt.HMODULE)]:
        name = ctypes.create_unicode_buffer(520)
        psapi.GetModuleFileNameExW(h, m, name, 520)
        info = (wt.DWORD * 3)()
        psapi.GetModuleInformation(h, m, info, ctypes.sizeof(info))
        modules.append(dict(base=m or 0, size=info[1], path=name.value))
    k32.CloseHandle(h)
    (a.out / 'regions.json').write_text(json.dumps(dict(regions=regions, modules=modules), indent=1))
    print('%d regions, %d modules -> %s' % (len(regions), len(modules), a.out))


if __name__ == '__main__':
    main()
