#!/usr/bin/env python3
"""Build the private decrypted client-data workspace from the game's JPK archives.

Usage:
    python tools/build_client_data.py --data "C:/.../Dark Blood/Data" \
        --out ../darkblood-client-data [--only dict ui]

Output layout (inside --out):
    files/<archive path>      every entry, deciphered (archives whose header
                              flag 0x226 is set) and inflated (.j suffix removed)
    lua_listing/<path>.txt    constants/function listing of each Lua 5.1 chunk
                              (tools/luac51_dump.py), for grep and diffs
    loose/                    non-JPK files copied from Data (videos, etc.)
    archives.tsv              per-archive header fields
    manifest.tsv              archive, entry, alias, header fields, bytes, kind
    errors.tsv                entries that failed to read, inflate or list

The output is game data: keep it out of the public emulator repository.
"""
import argparse
import io
import shutil
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from jpk_extractor import Archive, MAGIC  # noqa: E402
import luac51_dump  # noqa: E402

KINDS = ((b'\x1bLuaQ', 'lua51'), (b'<?xml', 'xml'), (b'\xef\xbb\xbf<?xml', 'xml'),
         (b'\xff\xfe<\x00?\x00x\x00m\x00l', 'xml-utf16'), (b'DDS ', 'dds'),
         (b'xof ', 'x'), (b'RIFF', 'riff'), (b'OggS', 'ogg'), (b'\x89PNG', 'png'),
         (b'BM', 'bmp'), (b'ID3', 'mp3'), (b'\xff\xd8\xff', 'jpg'), (b'EFFECT', 'eff'))


def kind_of(data):
    for magic, kind in KINDS:
        if data.startswith(magic):
            return kind
    return ''


def safe_join(root, rel):
    rel = rel.replace('\\', '/').lstrip('/')
    out = (root / rel).resolve()
    if root.resolve() not in out.parents:
        raise ValueError('entry escapes output directory: %r' % rel)
    return out


def lua_listing(data):
    buf = io.StringIO()
    with redirect_stdout(buf):
        luac51_dump.dump(luac51_dump.load(data))
    return buf.getvalue()


def build(data_dir, out, groups=None):
    files_root, listing_root = out / 'files', out / 'lua_listing'
    for d in (files_root, listing_root, out / 'loose'):
        d.mkdir(parents=True, exist_ok=True)
    arch = open(out / 'archives.tsv', 'w', encoding='utf-8', newline='\n')
    manifest = open(out / 'manifest.tsv', 'w', encoding='utf-8', newline='\n')
    errors = open(out / 'errors.tsv', 'w', encoding='utf-8', newline='\n')
    arch.write('archive\tentries\tdata_size\tflag_224\tflag_225\tencrypted\tword_227\n')
    manifest.write('archive\tentry\talias\tcrc\tzsize\tsize\toffset\tflags\tbytes\tkind\n')
    errors.write('archive\tentry\terror\n')
    totals = dict(archives=0, entries=0, encrypted_archives=0, lua=0, errors=0)
    for item in sorted(data_dir.iterdir(), key=lambda p: p.name.lower()):
        is_jpk = False
        if item.is_file():
            with open(str(item), 'rb') as probe:
                is_jpk = probe.read(8) == MAGIC
        if not is_jpk:
            if groups is None:
                dest = out / 'loose' / item.name
                if item.is_dir():
                    shutil.copytree(str(item), str(dest), dirs_exist_ok=True)
                else:
                    shutil.copy2(str(item), str(dest))
            continue
        if groups and item.stem.rsplit('_', 1)[0].lower() not in groups:
            continue
        arc = Archive(str(item))
        totals['archives'] += 1
        totals['encrypted_archives'] += arc.encrypted
        arch.write('%s\t%d\t%d\t%d\t%d\t%d\t%08x\n' % (
            item.name, len(arc.entries), arc.data_size, arc.flag_a, arc.flag_b,
            arc.encrypted, arc.cipher_word))
        print('[*] %s (%d entries, encrypted=%d)' % (item.name, len(arc.entries), arc.encrypted),
              flush=True)
        with open(str(item), 'rb') as f:
            for e in arc.entries:
                try:
                    data = arc.read(e, f)
                except Exception as exc:  # keep going; report in errors.tsv
                    errors.write('%s\t%s\t%s\n' % (item.name, e.name, exc))
                    totals['errors'] += 1
                    continue
                kind = kind_of(data)
                dest = safe_join(files_root, e.real_name)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
                if kind == 'lua51':
                    try:
                        lst = safe_join(listing_root, e.real_name + '.txt')
                        lst.parent.mkdir(parents=True, exist_ok=True)
                        lst.write_bytes(lua_listing(data).encode('utf-8'))
                        totals['lua'] += 1
                    except Exception as exc:
                        errors.write('%s\t%s\tlua listing: %s\n' % (item.name, e.real_name, exc))
                manifest.write('%s\t%s\t%s\t%08x\t%d\t%d\t%d\t%d\t%d\t%s\n' % (
                    item.name, e.real_name, e.alias, e.crc, e.zsize, e.size, e.offset,
                    e.flags, len(data), kind))
                totals['entries'] += 1
    for fh in (arch, manifest, errors):
        fh.close()
    return totals


def decompile_lua(out, unluac, java='java'):
    """Decompile every Lua 5.1 chunk under files/ into lua_src/ with unluac.

    unluac (https://sourceforge.net/projects/unluac/) is a third-party jar the
    user downloads; it is not part of this repository. Output is reconstructed
    source: verify against lua_listing/ before relying on details.
    """
    files_root, src_root = out / 'files', out / 'lua_src'
    done = failed = 0
    for path in sorted(files_root.rglob('*.lua')):
        with open(str(path), 'rb') as f:
            if f.read(5) != b'\x1bLuaQ':
                continue
        rel = path.relative_to(files_root)
        dest = src_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run([java, '-jar', str(unluac), str(path)],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600)
        if proc.returncode == 0 and proc.stdout:
            dest.write_bytes(proc.stdout)
            done += 1
        else:
            failed += 1
            print('[!] unluac failed: %s: %s' % (rel, proc.stderr.decode(errors='replace')[:200]))
    return dict(decompiled=done, failed=failed)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--data', type=Path, help='game Data directory (omit to only decompile)')
    ap.add_argument('--out', required=True, type=Path, help='private workspace root')
    ap.add_argument('--only', nargs='*', help='archive groups, e.g. dict ui map')
    ap.add_argument('--unluac', type=Path, help='unluac jar: also write lua_src/')
    ap.add_argument('--java', default='java', help='java executable for unluac')
    a = ap.parse_args()
    if a.data:
        groups = {x.lower() for x in a.only} if a.only else None
        print(build(a.data, a.out, groups))
    if a.unluac:
        print(decompile_lua(a.out, a.unluac, a.java))


if __name__ == '__main__':
    main()
