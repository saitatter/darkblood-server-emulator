#!/usr/bin/env python3
"""Rebuild a JPK archive, optionally replacing entries with edited plaintext.

    python tools/client_data/jpk_pack.py Data/Dict_3.jpk -o out/Dict_3.jpk \
        --from-dir ../darkblood-client-data/files            # replace changed files
    python tools/client_data/jpk_pack.py Data/Dict_3.jpk -o out.jpk \
        --replace "data\\dict\\maplist.lua=edited/maplist.lua"
    python tools/client_data/jpk_pack.py Data/Dict_3.jpk --verify      # byte-identical rebuild

Invariants checked on all 176 supplied JPK archives: entries are contiguous in
table order from offset 0, data_size equals the sum of entry sizes, the table
ends at the data base and the file ends after the last blob. The writer keeps
the header bytes before 0x218, the per-entry crc/zsize/flags words and the
archive flags unchanged (their meanings are unknown; see docs/JPK_FORMAT.md),
and recomputes head_size, data_size, sizes and offsets.

Whether the client accepts an edited archive is NOT verified yet. Test on the
working copy in research/client, never on the supplied installation, and keep
the original archive.
"""
import argparse
import hashlib
import os
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from jpk_extractor import Archive, encrypt_data  # noqa: E402


def varint(n):
    out = bytearray()
    while n >= 0x80:
        out.append(n & 0x7f)
        n >>= 7
    out.append(n | 0x80)
    return bytes(out)


def wstr(text):
    raw = text.encode('utf-16le')
    return varint(len(raw)) + raw


def wrap_j(plain, level=9):
    body = struct.pack('<I', len(plain)) + zlib.compress(plain, level)
    return varint(len(body)) + b'\x01' + body


def stored_blob(arc, entry, plain):
    blob = wrap_j(plain) if entry.name.lower().endswith('.j') else plain
    return encrypt_data(blob) if arc.encrypted else blob


def norm(name):
    return name.replace('/', '\\').lower()


def pack(src, dst, replacements):
    """replacements: {entry real name (any slash/case): plaintext bytes}."""
    arc = Archive(str(src))
    wanted = {norm(k): v for k, v in replacements.items()}
    with open(str(src), 'rb') as f:
        header = f.read(0x218)
        blobs, used = [], set()
        for e in arc.entries:
            key = norm(e.real_name)
            if key in wanted:
                blobs.append(stored_blob(arc, e, wanted[key]))
                used.add(key)
            else:
                f.seek(arc.base + e.offset)
                blobs.append(f.read(e.size))
    missing = sorted(set(wanted) - used)
    if missing:
        raise KeyError('not in archive: %s' % ', '.join(missing))
    table, offset = bytearray(), 0
    for e, blob in zip(arc.entries, blobs):
        table += wstr(e.name) + wstr(e.alias)
        table += struct.pack('<IIIIB', e.crc, e.zsize, len(blob), offset, e.flags)
        offset += len(blob)
    toc = struct.pack('<IIBBBI', len(arc.entries), offset, arc.flag_a, arc.flag_b,
                      int(arc.encrypted), arc.cipher_word) + bytes(table)
    out = header + struct.pack('<I', len(toc)) + toc + b''.join(blobs)
    if dst:
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        Path(dst).write_bytes(out)
    return out, sorted(used)


def changed_from_dir(src, root):
    """Entries whose file under root differs from the archive's plaintext."""
    arc, root, found = Archive(str(src)), Path(root), {}
    with open(str(src), 'rb') as f:
        for e in arc.entries:
            p = root / e.real_name.replace('\\', '/')
            if p.is_file():
                data = p.read_bytes()
                if data != arc.read(e, f):
                    found[e.real_name] = data
    return found


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('archive', type=Path)
    ap.add_argument('-o', '--output', type=Path)
    ap.add_argument('--replace', action='append', default=[], metavar='ENTRY=FILE')
    ap.add_argument('--from-dir', type=Path, help='workspace files/ root; repack changed entries')
    ap.add_argument('--verify', action='store_true', help='check a no-change rebuild is identical')
    a = ap.parse_args()
    if a.output and a.output.resolve() == a.archive.resolve():
        ap.error('refusing to overwrite the source archive')
    repl = {}
    if a.from_dir:
        repl.update(changed_from_dir(a.archive, a.from_dir))
    for item in a.replace:
        name, _, path = item.partition('=')
        repl[name] = Path(path).read_bytes()
    if a.verify:
        out, _ = pack(a.archive, None, {})
        same = out == a.archive.read_bytes()
        print('identical' if same else 'DIFFERENT', hashlib.sha256(out).hexdigest())
        return 0 if same else 1
    if not a.output:
        ap.error('--output is required unless --verify')
    _, used = pack(a.archive, a.output, repl)
    print('wrote %s (%d replaced)' % (a.output, len(used)))
    for name in used:
        print('  ', name)
    return 0


if __name__ == '__main__':
    sys.exit(main())
