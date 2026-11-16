# JPK Archive Format

**Verification status, 2026-11-16 (saitatter machine):** `tools/jpk_extractor.py`
reads all 176 JPK archives of the supplied client; 36,648 entries extract and
only 6 placeholder entries (`a_temp_dummy*.j` in Unit_4) fail to inflate. Field meanings marked *unknown* are not recovered. The
private workspace built from these archives is described in
`tools/build_client_data.py` and lives outside this repository.

## Header

| Offset | Type | Meaning |
| --- | --- | --- |
| `0x000` | `wchar[4]` | magic `"JPK\0"` |
| `0x008` | `u32, u32` | observed `14`, then a per-group value; *unknown* |
| `0x010` | `wchar[]` | build timestamp/text; *unknown* |
| `0x218` | `u32` | `head_size`; data base = `0x218 + 4 + head_size` |
| `0x21C` | `u32` | entry count |
| `0x220` | `u32` | data size |
| `0x224` | `u8` | 1 on the last archive of several groups; *unknown* |
| `0x225` | `u8` | observed 0; *unknown* |
| `0x226` | `u8` | **encrypted flag** |
| `0x227` | `u32` | `2` when encrypted, `0xFFFFFFFF` otherwise; *unknown* |
| `0x22B` | entries | see below |

Encrypted groups (flag 1): Common, Dict, Effect, EventScene, EvsStoryxml,
Localization_ST, Shader, Tile, TreasureMap, UI, UI_ST, Unit, WorldMap.
Plain groups (flag 0): DetailMap, Font_ST, Image, Image_ST, Map, Part,
Part_ST, Sound, Sound_ST. (Classification checked against content signatures:
zlib headers in `.j` entries, DDS/`xof `/XML/Lua/`EFFECT` magics.)

## Entry

- `wstr name` — inverted-terminal seven-bit varint byte length + UTF-16LE
  (continue while `byte <= 0x7F`; the byte with bit 7 set ends the length).
- `wstr alias` — original build path, e.g. `d:\depot\hound\...\data\common\action.lua`.
- `u32 crc` — repeats for every file of a folder (e.g. `5334d051` for
  `data\common`), so it is **not** a content CRC; *unknown*.
- `u32 zsize` — observed 0 even for compressed entries; *unknown*.
- `u32 size` — stored blob size.
- `u32 offset` — from the data base.
- `u8 flags` — observed 1; *unknown*.

## Entry blob

The blob is `size` bytes at `data base + offset`. When the archive flag is set,
the **whole blob** is deciphered first with the 73-byte cipher (see
[CRYPTO_KEYS.md](CRYPTO_KEYS.md)); the client tests the flag at archive object
`+0x5E` (`0x0041DC2E`, `0x0041DD34`) before calling `0x00411F90`. This applies
to every file type (textures, `.eff`, models), not only XML/Lua. The earlier
extractor deciphered only `.xml/.lua/.txt/.ini`, so older extractions of
encrypted archives contain still-encrypted binaries and failed `.j` entries.

Names ending in `.j` then contain: `varint length`, `u8 compressed`; when
compressed, `u32 inflated size` followed by a zlib stream of `length - 4`
bytes; when not, `length` raw bytes. The extracted name drops `.j`.

## Not yet done

Repacking: a writer must reproduce an unmodified archive byte-for-byte before
edited assets are tested in the client. Whether the client validates `crc`,
`zsize` or the header words above is unknown.
