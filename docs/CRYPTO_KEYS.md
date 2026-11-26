# Asset Encryption Specification & Verified Decoder

**Status: FULLY VERIFIED & RECOVERED (2026-11-16)**
The asset encryption algorithm and key used in all Dark Blood Online JPK containers have been decompiled from `DarkBlood.exe` at `0x00411F90` and verified against live game assets.

## 1. Verified Cipher Specification

* **Algorithm:** Subtract-1 then Polyalphabetic Repeating XOR
* **Period:** 73 bytes
* **Decryption Formula:**
  $$\text{Plaintext}[i] = ((\text{Ciphertext}[i] - 1) \pmod{256}) \oplus \text{Key}[i \pmod{73}]$$
* **Encryption Formula:**
  $$\text{Ciphertext}[i] = ((\text{Plaintext}[i] \oplus \text{Key}[i \pmod{73}]) + 1) \pmod{256}$$

## 2. Verified 73-Byte Secret Key Data

Recovered directly from `DarkBlood.exe` image at VA `0x00C4A848`:

### ASCII (73 bytes)
```text
305D006B-8D74-458f-BB80-CA243100F0DA-11406C9F-8393-42e8-9037-077D988CCF80
```

### Hexadecimal
```text
33 30 35 44 30 30 36 42 2d 38 44 37 34 2d 34 35 
38 66 2d 42 42 38 30 2d 43 41 32 34 33 31 30 30 
46 30 44 41 2d 31 31 34 30 36 43 39 46 2d 38 33 
39 33 2d 34 32 65 38 2d 39 30 33 37 2d 30 37 37 
44 39 38 38 43 43 46 38 30
```

## 3. Binary Decompilation Reference (`0x00411F90`)

```c
void FUN_00411f90(int param_1, int param_2)
{
  byte *key = (byte *)0x00C4A848; // "305D006B-8D74-458f-BB80-CA243100F0DA-11406C9F-8393-42e8-9037-077D988CCF80"
  int key_len = 73;
  int key_idx = 0;
  for (int i = 0; i < param_2; i++) {
    *(byte *)(i + param_1) = (*(char *)(i + param_1) - 1U) ^ key[key_idx];
    key_idx = (key_idx + 1) % key_len;
  }
}
```

## 4. Verification Results
* **`Common_0.jpk`:** Clean plaintext `configure.txt`, `action.lua`, `macro.lua`.
* **`Dict_*.jpk`:** Standard Lua 5.1 bytecode chunks beginning with `\x1bLuaQ\x00\x01\x04\x04\x04\x08...` and compiled function `lua_tinker::compile()`.
* **`Map_0.jpk` / `UI_*.jpk`:** Clean uncompressed and decompressed XML/Lua assets.
* Implemented in `tools/client_data/jpk_extractor.py`.

**Correction (2026-11-16, saitatter machine):** the cipher is selected per
archive by the header byte at `0x226` and applies to the whole stored blob of
every entry, including binary assets and the `.j` compression wrapper.
`Map_0.jpk` is *not* encrypted (flag 0). See [JPK_FORMAT.md](JPK_FORMAT.md).
With this rule the supplied client's 36,648 entries extract; only 6 placeholder entries (`a_temp_dummy*.j`, Unit_4) fail to inflate.
