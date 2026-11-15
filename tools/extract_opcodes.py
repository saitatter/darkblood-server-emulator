"""Extract the client's JEvent opcode -> name table from an unpacked image.

The client registers names in a std::map with code shaped like
    push <wchar* name> ... mov dword ptr [esp+0x10], <opcode> ... call insert
(around 0xA20000-0xA40000 in the analysed build). This is a heuristic scan;
entries whose push is farther than 24 bytes from the key are missed.

Usage: python tools/extract_opcodes.py research/normal.bin server/data/opcodes.tsv
"""
import re
import struct
import sys

BASE = 0x400000


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


def main(source, output):
    image = open(source, 'rb').read()
    region = image[0xA20000 - BASE:0xA40000 - BASE]
    names = {}
    for match in re.finditer(rb'\xc7\x44\x24\x10(....)', region):
        key = struct.unpack('<I', match.group(1))[0]
        if key > 0x10000:
            continue
        back = region[max(0, match.start() - 24):match.start()]
        push = back.rfind(b'\x68')
        if push < 0 or push + 5 > len(back):
            continue
        va = struct.unpack('<I', back[push + 1:push + 5])[0]
        if 0xC00000 < va < 0xF00000:
            name = read_wide(image, va)
            if name and re.fullmatch(r'[A-Za-z0-9_]+', name):
                names[key] = name
    with open(output, 'w', encoding='utf-8', newline='\n') as stream:
        stream.write('# opcode\tname  (extracted from client hash a82ae3d7...; see tools/extract_opcodes.py)\n')
        for key in sorted(names):
            stream.write('%d\t%s\n' % (key, names[key]))
    print('%d names -> %s' % (len(names), output))


if __name__ == '__main__':
    main(*sys.argv[1:3])
