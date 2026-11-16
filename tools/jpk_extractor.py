#!/usr/bin/env python3
"""
Dark Blood Online — JPK archive reader / extractor.

Layout (verified on all 176 JPK archives of the supplied client, 2026-11-16):
  0x000  wchar magic "JPK\\0"
  0x218  u32 head_size; data base = 0x218 + 4 + head_size
  0x21C  u32 entry_count
  0x220  u32 data_size
  0x224  u8  unknown (1 on the last archive of several groups)
  0x225  u8  unknown (observed 0)
  0x226  u8  encrypted flag (1: every entry blob uses the 73-byte cipher)
  0x227  u32 2 when encrypted, 0xFFFFFFFF otherwise (meaning unknown)
  0x22B  entries: wstr name, wstr build alias, u32 crc?, u32 zsize?, u32 size,
         u32 offset (from data base), u8 flags
Entry blob = `size` bytes at base + offset. When the archive is encrypted the
whole blob is deciphered first (client: flag at archive object +0x5E checked
at 0x0041DC2E before 0x00411F90). Names ending in `.j` then hold
`varint length, u8 compressed, [u32 raw size], zlib data`.
"""

import argparse
import io
import os
import struct
import zlib

KEY_73 = b'305D006B-8D74-458f-BB80-CA243100F0DA-11406C9F-8393-42e8-9037-077D988CCF80'
MAGIC = b'J\x00P\x00K\x00\x00\x00'


def read_varint(f):
    """JSerBuffer-style varint: 7-bit groups, the byte with bit 7 SET ends it."""
    num = shift = 0
    while True:
        b = f.read(1)
        if not b:
            raise EOFError('truncated varint')
        num |= (b[0] & 0x7F) << shift
        shift += 7
        if b[0] > 0x7F:
            return num


def read_ugly_string(f):
    return f.read(read_varint(f)).decode('utf-16le', 'ignore')


def decrypt_data(data: bytes) -> bytes:
    key, n = KEY_73, len(KEY_73)
    return bytes(((b - 1) & 0xFF) ^ key[i % n] for i, b in enumerate(data))


def encrypt_data(data: bytes) -> bytes:
    key, n = KEY_73, len(KEY_73)
    return bytes(((b ^ key[i % n]) + 1) & 0xFF for i, b in enumerate(data))


def unwrap_j(blob: bytes) -> bytes:
    s = io.BytesIO(blob)
    length = read_varint(s)
    if s.read(1) == b'\x00':
        return s.read(length)
    s.read(4)  # inflated size
    return zlib.decompress(s.read(length - 4))


class Entry:
    __slots__ = ('name', 'alias', 'crc', 'zsize', 'size', 'offset', 'flags')

    def __init__(self, *values):
        for slot, value in zip(self.__slots__, values):
            setattr(self, slot, value)

    @property
    def real_name(self):
        return self.name[:-2] if self.name.lower().endswith('.j') else self.name


class Archive:
    def __init__(self, path):
        self.path = path
        with open(path, 'rb') as f:
            if f.read(8) != MAGIC:
                raise ValueError('not a JPK archive: %s' % path)
            f.seek(0x218)
            head_size, count, self.data_size = struct.unpack('<III', f.read(12))
            self.flag_a, self.flag_b, self.encrypted, self.cipher_word = struct.unpack('<BBBI', f.read(7))
            self.encrypted = bool(self.encrypted)
            self.base = 0x218 + 4 + head_size
            self.entries = []
            for _ in range(count):
                name, alias = read_ugly_string(f), read_ugly_string(f)
                self.entries.append(Entry(name, alias, *struct.unpack('<IIIIB', f.read(17))))

    def read(self, entry, f=None):
        """Return the entry's plaintext (deciphered and inflated)."""
        own = f is None
        f = f or open(self.path, 'rb')
        try:
            f.seek(self.base + entry.offset)
            blob = f.read(entry.size)
        finally:
            if own:
                f.close()
        if self.encrypted:
            blob = decrypt_data(blob)
        if entry.name.lower().endswith('.j'):
            blob = unwrap_j(blob)
        return blob


def extract_jpk(jpk_path: str, output_dir: str, decrypt: bool = True):
    print(f"[*] Processing: {jpk_path}")
    try:
        arc = Archive(jpk_path)
    except ValueError as exc:
        print(f"[!] Skipping: {exc}")
        return
    if not decrypt:
        arc.encrypted = False
    print(f"    Entries: {len(arc.entries)}, encrypted: {arc.encrypted}")
    done = 0
    with open(jpk_path, 'rb') as f:
        for entry in arc.entries:
            try:
                data = arc.read(entry, f)
            except Exception as exc:
                print(f"[!] {entry.name}: {exc}")
                continue
            dest = os.path.join(output_dir, entry.real_name.replace('\\', os.sep))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, 'wb') as out:
                out.write(data)
            done += 1
    print(f"[+] Extracted {done} files to: {output_dir}")


def main():
    parser = argparse.ArgumentParser(description="Dark Blood JPK Extractor")
    parser.add_argument("input", help="Path to a .jpk file or directory containing .jpk files")
    parser.add_argument("-o", "--output", default="extracted", help="Destination directory")
    parser.add_argument("--no-decrypt", action="store_true",
                        help="Do not apply the 73-byte cipher even if the archive flag is set")
    args = parser.parse_args()

    if os.path.isfile(args.input):
        extract_jpk(args.input, args.output, decrypt=not args.no_decrypt)
    elif os.path.isdir(args.input):
        for name in sorted(os.listdir(args.input)):
            if name.lower().endswith('.jpk'):
                extract_jpk(os.path.join(args.input, name), args.output,
                            decrypt=not args.no_decrypt)
    else:
        print(f"Error: {args.input} not found.")


if __name__ == "__main__":
    main()
