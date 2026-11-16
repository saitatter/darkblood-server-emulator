"""Extract the client's JEvent opcode tables from an unpacked image.

The client fills three std::maps in one initialiser (0xA20000-0xA40000 in the
analysed build, hash a82ae3d7...). Every insert is anchored on
``mov ecx, <map>; [push]; call <operator[]>``; the key is the nearest preceding
``mov dword ptr [esp+N], imm32`` and, for the name map, the value is the
nearest preceding valid ``push <wchar* name>``:

  0x00F49CF8  opcode -> name       (operator[] 0x005D0D10, then assign)
  0x00F49CE8  request -> response  (operator[] 0x005221E0, then mov [eax], imm)
  0x00F49D04  opcode -> 1          (operator[] 0x005221E0, then mov [eax], 1;
                                    meaning not recovered)

Earlier versions matched one fixed instruction order and dropped names whose
bytes contained 0x0A (regex without re.S) or 0x68 inside immediates; anchoring
on the map insert covers the compiler's scheduling variants.

Usage: python tools/extract_opcodes.py research/normal.bin server/data/opcodes.tsv
       (also writes opcode_pairs.tsv and opcode_flags.tsv next to the output)
"""
import re
import struct
import sys
from pathlib import Path

BASE = 0x400000
LO, HI = 0xA20000, 0xA40000
NAME_MAP, PAIR_MAP, FLAG_MAP = 0xF49CF8, 0xF49CE8, 0xF49D04
NAME_RE = re.compile(r'(_NOUSE_)?e[A-Za-z0-9]*_[A-Za-z0-9_]+')
STORE_KEY = re.compile(rb'\xc7\x44\x24(.)(....)', re.S)        # mov [esp+d8], imm32
STORE_KEY32 = re.compile(rb'\xc7\x84\x24(....)(....)', re.S)   # mov [esp+d32], imm32
STORE_EAX = re.compile(rb'\xc7\x00(....)', re.S)               # mov dword ptr [eax], imm32


def read_wide(image, va):
    offset = va - BASE
    end = offset
    while end + 1 < len(image) and image[end:end + 2] != b'\0\0':
        end += 2
    try:
        text = image[offset:end].decode('utf-16le')
    except UnicodeDecodeError:
        return None
    return text if text.isprintable() and text else None


def last_key(window):
    best = None
    for rx in (STORE_KEY, STORE_KEY32):
        for m in rx.finditer(window):
            value = struct.unpack('<I', m.group(2))[0]
            if 0 < value <= 0x10000 and (best is None or m.start() > best[0]):
                best = (m.start(), value)
    return best[1] if best else None


def last_name(image, window):
    for i in range(len(window) - 5, -1, -1):
        if window[i] != 0x68:
            continue
        va = struct.unpack('<I', window[i + 1:i + 5])[0]
        if 0xC00000 < va < 0xF00000:
            name = read_wide(image, va)
            if name and NAME_RE.fullmatch(name):
                return name
    return None


def extract(image):
    """Instruction-level pass: track ecx, the last [esp+N] imm store and the
    last push imm before each insert call; the value of a pair/flag insert is
    the first ``mov dword ptr [eax], imm`` after its call."""
    import capstone
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    names, pairs, flags = {}, {}, {}
    maps = {NAME_MAP: names, PAIR_MAP: pairs, FLAG_MAP: flags}
    ecx = key = None
    pushes = []
    zero = set()
    pending = None  # (table, key) waiting for mov [eax], imm
    for ins in md.disasm(image[LO - BASE:HI - BASE], LO):
        op = ins.op_str
        if ins.mnemonic == 'mov' and op.startswith('ecx, 0x'):
            ecx = int(op[5:], 16)
        elif ins.mnemonic == 'xor' and op.split(', ')[0] == op.split(', ')[-1]:
            zero.add(op.split(', ')[0])
        elif ins.mnemonic == 'mov' and op.startswith('dword ptr [esp'):
            src = op.rsplit(', ', 1)[1]
            if src.startswith('0x') or src == '0':
                value = int(src, 16)
                key = value if value <= 0x10000 else key
            elif src in zero:  # e.g. xor ebx, ebx; mov [esp+0x10], ebx (eE_HEART_BIT = 0)
                key = 0
            else:
                key = None
        elif ins.mnemonic == 'push' and op.startswith('0x'):
            pushes = (pushes + [int(op, 16)])[-3:]
        elif (ins.mnemonic == 'mov' and op.startswith('dword ptr [eax], 0x') or
              op == 'dword ptr [eax], 0') and pending:
            pending[0].setdefault(pending[1], int(op.rsplit(', ', 1)[1], 16))
            pending = None
        elif ins.mnemonic == 'call':
            if ecx in maps and key is not None:
                if ecx == NAME_MAP:
                    for va in reversed(pushes):
                        name = read_wide(image, va) if 0xC00000 < va < 0xF00000 else None
                        if name and NAME_RE.fullmatch(name):
                            names.setdefault(key, name)
                            break
                    pushes = []
                else:
                    pending = (maps[ecx], key)
            ecx = None if ecx in maps else ecx
    byte_names = extract_bytes(image)[0]
    for k, v in byte_names.items():
        names.setdefault(k, v)
    return names, pairs, flags


def extract_bytes(image):
    names, pairs, flags = {}, {}, {}
    region = image[LO - BASE:HI - BASE]
    for target, table in ((NAME_MAP, 'name'), (PAIR_MAP, 'pair'), (FLAG_MAP, 'flag')):
        anchor = b'\xb9' + struct.pack('<I', target)
        for m in re.finditer(re.escape(anchor), region):
            pos = m.start()
            back = region[max(0, pos - 32):pos]
            # the key store may also sit between the anchor and the call
            fwd = region[pos + 5:pos + 20]
            call = fwd.find(b'\xe8')
            key = last_key(back + (fwd[:call] if call > 0 else b''))
            if key is None:
                continue
            if table == 'name':
                name = last_name(image, back)
                if name:
                    names.setdefault(key, name)
                continue
            after = region[pos + 5:pos + 40]
            store = STORE_EAX.search(after)
            if not store:
                continue
            value = struct.unpack('<I', store.group(1))[0]
            (pairs if table == 'pair' else flags).setdefault(key, value)
    return names, pairs, flags


def main(source, output):
    image = open(source, 'rb').read()
    names, pairs, flags = extract(image)
    out = Path(output)
    header = '# %s  (extracted from client hash a82ae3d7...; see tools/extract_opcodes.py)\n'
    with open(out, 'w', encoding='utf-8', newline='\n') as stream:
        stream.write(header % 'opcode\tname')
        for key in sorted(names):
            stream.write('%d\t%s\n' % (key, names[key]))
    with open(out.with_name('opcode_pairs.tsv'), 'w', encoding='utf-8', newline='\n') as stream:
        stream.write(header % 'request\tresponse\trequest_name\tresponse_name')
        for key in sorted(pairs):
            stream.write('%d\t%d\t%s\t%s\n' % (key, pairs[key], names.get(key, ''),
                                             names.get(pairs[key], '')))
    with open(out.with_name('opcode_flags.tsv'), 'w', encoding='utf-8', newline='\n') as stream:
        stream.write(header % 'opcode\tvalue\tname  (map 0xF49D04, meaning unknown)')
        for key in sorted(flags):
            stream.write('%d\t%d\t%s\n' % (key, flags[key], names.get(key, '')))
    print('%d names, %d request->response pairs, %d flags -> %s' % (
        len(names), len(pairs), len(flags), out.parent))


if __name__ == '__main__':
    main(*sys.argv[1:3])
