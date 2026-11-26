"""Texture decoding for client images that Pillow cannot open on its own.

Survey of the extracted data (2026-11-26):
* 4,906 ``.tga`` files are colour-mapped (image type 1) with a **32-bit BGRA
  palette**; Pillow rejects that palette depth ("unrecognized raw mode").
* 7 ``.dds`` files (e.g. ``unit/character/fighter/lod.dds``) store ``dwSize = 24``
  instead of 124 in an otherwise standard DXT header.
* Many ``.tga`` names actually contain DDS data; Pillow detects those by content.
"""
import io
import struct

import numpy as np
from PIL import Image


def _decode_colormapped_tga(data):
    id_len, cmap_type, img_type = data[0], data[1], data[2]
    first, length, entry_bits = struct.unpack_from('<HHB', data, 3)
    width, height, depth, desc = struct.unpack_from('<HHBB', data, 12)
    if cmap_type != 1 or img_type not in (1, 9) or depth != 8 or entry_bits not in (24, 32):
        raise ValueError('not a supported colour-mapped TGA')
    pos = 18 + id_len
    esize = entry_bits // 8
    pal = np.frombuffer(data, np.uint8, length * esize, pos).reshape(length, esize)
    pos += length * esize
    rgba = np.full((first + length, 4), 255, np.uint8)
    rgba[first:, 0], rgba[first:, 1], rgba[first:, 2] = pal[:, 2], pal[:, 1], pal[:, 0]
    if esize == 4:
        rgba[first:, 3] = pal[:, 3]
    n = width * height
    if img_type == 1:
        idx = np.frombuffer(data, np.uint8, n, pos)
    else:  # RLE
        out = bytearray()
        while len(out) < n:
            h = data[pos]
            pos += 1
            count = (h & 0x7F) + 1
            if h & 0x80:
                out += bytes([data[pos]]) * count
                pos += 1
            else:
                out += data[pos:pos + count]
                pos += count
        idx = np.frombuffer(bytes(out[:n]), np.uint8)
    img = rgba[idx].reshape(height, width, 4)
    if not desc & 0x20:          # origin bottom-left
        img = img[::-1]
    if desc & 0x10:              # origin right
        img = img[:, ::-1]
    if esize == 4 and not img[..., 3].any():
        img = img.copy()
        img[..., 3] = 255        # an all-zero alpha channel means "no alpha"
    return Image.fromarray(np.ascontiguousarray(img), 'RGBA')


def _fix_dds_header(data):
    if data[:4] == b'DDS ' and struct.unpack_from('<I', data, 4)[0] != 124:
        return data[:4] + struct.pack('<I', 124) + data[8:]
    return data


def load_image(path):
    """Open any client texture as an RGBA PIL image."""
    with open(path, 'rb') as f:
        data = f.read()
    if len(data) >= 18 and data[1] == 1 and data[2] in (1, 9) and data[16] == 8:
        try:
            return _decode_colormapped_tga(data)
        except (ValueError, IndexError):
            pass
    img = Image.open(io.BytesIO(_fix_dds_header(data)))
    img.load()
    return img.convert('RGBA')
