# JPK Archive Format Specification

**Verification status, 2026-11-16:** this is the earlier working layout used by `tools/jpk_extractor.py`, not a fully validated specification for every archive. Asset decryption is unresolved and existing extracted XML is malformed. The length encoding is an inverted-terminal seven-bit varint, not standard LEB128. See [STATUS.md](STATUS.md) and [CRYPTO_KEYS.md](CRYPTO_KEYS.md).

## Header Structure
- **Offset `0x000`:** `wchar_t magic[4]` = `"JPK\0"` (8 bytes)
- **Offset `0x008`:** `uint32_t num1`, `uint32_t num2`
- **Offset `0x010`:** `wchar_t timestamp[]`
- **Offset `0x218`:** `uint32_t head_size`
- **Data Base Offset:** `0x218 + 4 + head_size`

## Table of Contents (TOC)
- `uint32_t file_count`
- `uint32_t total_data_size`
- `uint8_t dummy1`, `uint16_t dummy2`, `uint32_t dummy3`

## File Entry Format
- **Path String 1:** inverted-terminal seven-bit length prefix followed by UTF-16LE bytes.
  - *LEB128 Variant:* Continuation condition is `byte <= 0x7F`; terminating byte has `byte > 0x7F`.
- **Path String 2:** Redundant / alias name (LEB128 length + UTF-16LE).
- `uint32_t crc32`
- `uint32_t zsize` (0 if uncompressed, >0 if compressed)
- `uint32_t size` (decompressed file size)
- `uint32_t offset` (relative to Data Base Offset)
- `uint8_t flags`

### Compression
Files ending in `.j` (e.g. `*.ani.j`, `*.x.j`) store an extra header at their data offset:
- LEB128 compressed size
- `uint8_t is_compressed` (1 = standard Deflate/Zlib, 0 = uncompressed raw bytes).
