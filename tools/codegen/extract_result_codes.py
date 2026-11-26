"""Extract the client's ACK result-code table (code -> JERI_* key -> English text).

A nonzero ACK result is shown through 0x00AB29C0: 0x00AB2980 looks the code up
in the std::map at 0x00F4BBBC (end sentinel 0x00F4BBC0) and the JERI_* key is
then resolved to text from Data/Localization_ST/error_st.dat. The initialiser
at 0x00AB3450 fills that map (and a sibling at 0x00F4BBB0) with repeated

    push <wchar* JERI_name>; lea reg, [esp+N]; push reg;
    mov ecx, 0x00F4BBBC; mov dword ptr [esp+0x14], <code reg/imm>;
    call 0x005D0D10 (operator[]); ... assign

The code is usually held in a register (esi/edi/ebx/...), so register
constants are tracked through mov/xor/or/inc/dec/lea.

Usage: python tools/codegen/extract_result_codes.py research/unpacked.analysis.exe \
           ../darkblood-client-data/files/data/localization_st/error_st.dat \
           assets/result_codes.tsv
Requires pefile and capstone. Checked against code 206 = JERI_ROUTER_00
("cannot find this character."), which mail/friend handlers already use.
"""
import re
import sys
from pathlib import Path

import capstone
import pefile

BASE = 0x400000
INIT, INIT_SIZE = 0xAB3450, 0x9000  # inserts end near 0xABBA50
CODE_MAP = 0xF4BBBC
MAP_INSERT = 0x5D0D10
REG = r'(e[a-d]x|esi|edi|ebp)'


def main(exe_path, text_path, out_path):
    data = Path(exe_path).read_bytes()
    pe = pefile.PE(data=data, fast_load=True)

    def read(va, n):
        off = pe.get_offset_from_rva(va - BASE)
        return data[off:off + n]

    def wide(va):
        raw, out = read(va, 160), []
        for i in range(0, len(raw) - 1, 2):
            c = raw[i] | raw[i + 1] << 8
            if c == 0:
                break
            out.append(chr(c))
        return ''.join(out)

    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    regs, codes = {}, {}
    key = name = None
    to_code_map = False
    for ins in md.disasm(read(INIT, INIT_SIZE), INIT):
        m, s = ins.mnemonic, ins.op_str
        if m == 'ret':
            break
        hit = re.match(REG + r', (0x[0-9a-f]+|\d+)$', s)
        if m == 'mov' and hit:
            regs[hit.group(1)] = int(hit.group(2), 0)
        elif m == 'xor' and re.match(r'(\w+), \1$', s):
            regs[s.split(',')[0]] = 0
        elif m == 'or' and s.endswith(', 0xffffffff'):
            regs[s.split(',')[0]] = -1
        elif m in ('inc', 'dec') and s in regs:
            regs[s] += 1 if m == 'inc' else -1
        elif m == 'lea':
            hit = re.match(REG + r', \[' + REG + r' \+ (0x[0-9a-f]+|\d+)\]$', s)
            if hit and hit.group(2) in regs:
                regs[hit.group(1)] = regs[hit.group(2)] + int(hit.group(3), 0)
        if m == 'push' and s.startswith('0x') and 0xC00000 < int(s, 16) < 0xE00000:
            name = wide(int(s, 16))
        hit = re.match(r'dword ptr \[esp \+ 0x14\], (\w+)$', s)
        if m == 'mov' and hit:
            v = hit.group(1)
            key = int(v, 0) if v[0].isdigit() else regs.get(v)
        if m == 'mov' and s.startswith('ecx, '):
            to_code_map = s == 'ecx, 0x%x' % CODE_MAP
        if m == 'call' and s == '0x%x' % MAP_INSERT and to_code_map and name and key is not None:
            if key >= 0x80000000:
                key -= 0x100000000
            codes[key] = name

    texts = {}
    for line in Path(text_path).read_bytes().decode('utf-16').splitlines():
        if '\t' in line:
            k, v = line.split('\t', 1)
            texts[k.strip()] = v.strip()

    lines = ['# code\tkey\ttext  (client result-code map 0x00F4BBBC, '
             'texts from error_st.dat; see tools/codegen/extract_result_codes.py)']
    for code in sorted(codes):
        lines.append('%d\t%s\t%s' % (code, codes[code], texts.get(codes[code], '')))
    Path(out_path).write_text('\n'.join(lines) + '\n', encoding='utf-8')
    with_text = sum(1 for c in codes.values() if c in texts)
    print('%d codes (%d with text) -> %s' % (len(codes), with_text, out_path))


if __name__ == '__main__':
    main(*sys.argv[1:4])
