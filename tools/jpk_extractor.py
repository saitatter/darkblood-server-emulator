#!/usr/bin/env python3
"""
Dark Blood Online — JPK Archive Extractor & Decrypter
Extracts and automatically decrypts XML and Lua assets.
"""

import sys
import os
import struct
import zlib
import argparse

KEY_73 = b'305D006B-8D74-458f-BB80-CA243100F0DA-11406C9F-8393-42e8-9037-077D988CCF80'

def read_varint(f):
    num = 0
    shift = 0
    while True:
        b = f.read(1)
        if not b:
            return 0
        val = b[0]
        num |= (val & 0x7F) << shift
        shift += 7
        if val > 0x7F:
            break
    return num

def read_ugly_string(f):
    sz = read_varint(f)
    raw = f.read(sz)
    return raw.decode('utf-16le', 'ignore')

def decrypt_data(data: bytes) -> bytes:
    key_len = len(KEY_73)
    return bytes([((b - 1) & 0xFF) ^ KEY_73[i % key_len] for i, b in enumerate(data)])

def extract_jpk(jpk_path: str, output_dir: str, decrypt: bool = True):
    print(f"[*] Processing: {jpk_path}")
    with open(jpk_path, 'rb') as f:
        magic = f.read(8)
        if magic != b'J\x00P\x00K\x00\x00\x00':
            print(f"[!] Warning: Magic mismatch: {magic}")

        f.seek(0x218)
        head_size, = struct.unpack('<I', f.read(4))
        base_off = 0x218 + 4 + head_size

        files, data_size, dummy_b, dummy_s, dummy_l = struct.unpack('<IIBHI', f.read(15))
        print(f"    Total files: {files}, Data size: {data_size} bytes")

        extracted_count = 0
        for i in range(files):
            name1 = read_ugly_string(f)
            name2 = read_ugly_string(f)
            crc, zsize, size, offset, dummy = struct.unpack('<IIIIB', f.read(17))

            file_offset = offset + base_off
            cur_pos = f.tell()

            f.seek(file_offset)
            file_data = b''

            if name1.lower().endswith('.j'):
                real_name = name1[:-2]
                comp_zsize = read_varint(f)
                is_zip = f.read(1)
                if is_zip == b'\x00':
                    file_data = f.read(comp_zsize)
                else:
                    raw_len = struct.unpack('<I', f.read(4))[0]
                    comp_data = f.read(comp_zsize - 4)
                    try:
                        file_data = zlib.decompress(comp_data)
                    except Exception as e:
                        file_data = comp_data
            else:
                real_name = name1
                file_data = f.read(size)

            if decrypt and real_name.lower().endswith(('.xml', '.lua', '.txt', '.ini')):
                if not (file_data.startswith(b'<?xml') or file_data.startswith(b'\x1bLua') or file_data.startswith(b'--')):
                    dec = decrypt_data(file_data)
                    if (dec.startswith(b'<?xml') or dec.startswith(b'\x1bLua') or
                        dec.startswith(b'--') or dec.startswith(b'\r\n') or
                        dec.startswith(b'\n') or b'=' in dec[:50] or b'SETUP' in dec[:50] or b'COMMAND' in dec[:50]):
                        file_data = dec

            dest_path = os.path.join(output_dir, real_name)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            with open(dest_path, 'wb') as out_fp:
                out_fp.write(file_data)

            extracted_count += 1
            f.seek(cur_pos)

        print(f"[+] Extracted {extracted_count} files to: {output_dir}")

def main():
    parser = argparse.ArgumentParser(description="Dark Blood JPK Extractor")
    parser.add_argument("input", help="Path to a .jpk file or directory containing .jpk files")
    parser.add_argument("-o", "--output", default="extracted", help="Destination directory")
    parser.add_argument("--no-decrypt", action="store_true", help="Do not apply 73-byte XOR decryption")
    args = parser.parse_args()

    if os.path.isfile(args.input):
        extract_jpk(args.input, args.output, decrypt=not args.no_decrypt)
    elif os.path.isdir(args.input):
        for f in sorted(os.listdir(args.input)):
            if f.lower().endswith('.jpk'):
                full_path = os.path.join(args.input, f)
                extract_jpk(full_path, args.output, decrypt=not args.no_decrypt)
    else:
        print(f"Error: {args.input} not found.")

if __name__ == "__main__":
    main()
