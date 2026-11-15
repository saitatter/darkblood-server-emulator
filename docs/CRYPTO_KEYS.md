# Provisional Asset Encryption Notes

**Status, 2026-11-16:** the candidate key below is inherited from the earlier investigation and is not verified. Existing files in `extracted_sample/` contain malformed XML. The former README also listed a different candidate key. Do not treat this document as a validated decoder specification or use the candidate for bulk extraction until the client algorithm and multiple parseable outputs have been checked. See [STATUS.md](STATUS.md) and [ROADMAP.md](../ROADMAP.md).

## Earlier Cipher Hypothesis
- **Algorithm:** Polyalphabetic Repeating XOR Cipher
- **Period:** 73 bytes

## Candidate Key Data
### ASCII
```text
234G335C,;G67,54;e,CC;3,B@372233E3GD,00735B:E,;2:2,73d;,:326,366G:;;BBE;3
```

### Hexadecimal
```text
32 33 34 47 33 33 35 43 2c 3b 47 36 37 2c 35 34
3b 65 2c 43 43 3b 33 2c 42 40 33 37 32 32 33 33
45 33 47 44 2c 30 30 37 33 35 42 3a 45 2c 3b 32
3a 32 2c 37 33 64 3b 2c 3a 33 32 36 2c 33 36 36
47 3a 3b 3b 42 42 45 3b 33
```

## Application
The earlier extractor applies this repeating XOR candidate to selected text assets. The claim that it correctly decodes all XML/Lua files has not been validated; the observed malformed sample contradicts treating those outputs as valid plaintext. Additional layers, a different key, or an incorrect transformation remain possible.
