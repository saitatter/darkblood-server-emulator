#!/usr/bin/env python3
"""Read-only dump of a running client's memory regions and module list.

Opens the process with PROCESS_QUERY_INFORMATION | PROCESS_VM_READ only (no
debugger attach, no writes) and saves committed regions in [lo, hi) plus the
loaded module table, so protector stubs (e.g. ``nop; call 0x600xxxxx``) can be
resolved offline with tools/resolve_stubs.py.

    python tools/dump_stubs.py PID -o research/stubs
"""
import argparse
import ctypes
import ctypes.wintypes as wt
import json
from pathlib import Path

k32 = ctypes.WinDLL('kernel32', use_last_error=True)
psapi = ctypes.WinDLL('psapi', use_last_error=True)


HANDLE = ctypes.c_void_p
k32.OpenProcess.restype = HANDLE
k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.CloseHandle.argtypes = [HANDLE]
k32.ReadProcessMemory.argtypes = [HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                                  ctypes.POINTER(ctypes.c_size_t)]
k32.VirtualQueryEx.argtypes = [HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
k32.VirtualQueryEx.restype = ctypes.c_size_t
psapi.EnumProcessModulesEx.argtypes = [HANDLE, ctypes.POINTER(ctypes.c_void_p), wt.DWORD,
                                       ctypes.POINTER(wt.DWORD), wt.DWORD]
psapi.GetModuleFileNameExW.argtypes = [HANDLE, ctypes.c_void_p, wt.LPWSTR, wt.DWORD]
psapi.GetModuleInformation.argtypes = [HANDLE, ctypes.c_void_p, ctypes.c_void_p, wt.DWORD]


class MBI(ctypes.Structure):
    _fields_ = [('BaseAddress', ctypes.c_void_p), ('AllocationBase', ctypes.c_void_p),
                ('AllocationProtect', wt.DWORD), ('RegionSize', ctypes.c_size_t),
                ('State', wt.DWORD), ('Protect', wt.DWORD), ('Type', wt.DWORD)]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('pid', type=int)
    ap.add_argument('--image-lo', type=lambda s: int(s, 0), default=0x400000,
                    help='game EXE image start (dumped in full)')
    ap.add_argument('--image-hi', type=lambda s: int(s, 0), default=0x11A0000)
    ap.add_argument('-o', '--out', type=Path, required=True)
    a = ap.parse_args()
    h = k32.OpenProcess(0x0400 | 0x0010, False, a.pid)
    if not h:
        raise OSError(ctypes.get_last_error(), 'OpenProcess')
    a.out.mkdir(parents=True, exist_ok=True)
    for old in a.out.glob('*.bin'):
        old.unlink()
    # Dump the EXE image (its call sites hold this session's stub targets)
    # plus every executable private/mapped region (protector thunks). DLL
    # images are not dumped: their exports are resolved from the files on disk.
    regions, addr = [], 0x10000
    mbi = MBI()
    while addr < 0x7FFF0000 and k32.VirtualQueryEx(h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
        base, size = mbi.BaseAddress or 0, mbi.RegionSize
        in_image = a.image_lo <= base < a.image_hi
        executable = mbi.Protect & 0xF0 and mbi.Type != 0x1000000  # not MEM_IMAGE
        if mbi.State == 0x1000 and not (mbi.Protect & 0x101) and (in_image or executable):
            buf = ctypes.create_string_buffer(size)
            got = ctypes.c_size_t()
            if k32.ReadProcessMemory(h, ctypes.c_void_p(base), buf, size, ctypes.byref(got)):
                (a.out / ('%08x.bin' % base)).write_bytes(buf.raw[:got.value])
                regions.append(dict(base=base, size=got.value, protect=mbi.Protect, type=mbi.Type))
        addr = base + size
    mods = (ctypes.c_void_p * 1024)()
    need = wt.DWORD()
    psapi.EnumProcessModulesEx(h, mods, ctypes.sizeof(mods), ctypes.byref(need), 3)
    modules = []
    for m in mods[:need.value // ctypes.sizeof(ctypes.c_void_p)]:
        name = ctypes.create_unicode_buffer(520)
        psapi.GetModuleFileNameExW(h, m, name, 520)
        info = (ctypes.c_void_p * 3)()  # MODULEINFO: base, size, entry
        psapi.GetModuleInformation(h, m, info, ctypes.sizeof(info))
        modules.append(dict(base=m or 0, size=info[1] or 0, path=name.value))
    k32.CloseHandle(h)
    (a.out / 'regions.json').write_text(json.dumps(dict(regions=regions, modules=modules), indent=1))
    print('%d regions, %d modules -> %s' % (len(regions), len(modules), a.out))


if __name__ == '__main__':
    main()
