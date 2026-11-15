"""ProudNet session crypto as recovered from the Dark Blood client.

Static evidence (client hash in docs/STATUS.md):
  0xB83CB0  libtomcrypt rsa_import + rsa_encrypt_key_ex(padding=2 OAEP,
            hash "sha1" 0xD79E28, prng "fortuna" 0xD79E30)
  0xB73740  CRijndael::MakeKey(key, keylen 16/24/32, block 16)
  0xB74B30  block encrypt; mode 0 = ECB (used by 0xB74E00/0xB74E90)
  0xB95F60  standard CRC-32 (table 0xE45D50)

Envelope written by 0xB74B30 before in-place ECB encryption:
  plaintext | pad filler (pad bytes) | u32 crc32(plaintext) | u8 pad
  pad = block - (len + 5) % block   (1..block)
Only the standard library is used; this is research code, not hardened crypto.
"""
import hashlib
import os
import struct
import zlib

# --------------------------------------------------------------- AES (FIPS-197)
_SBOX = [0] * 256
_INV = [0] * 256


def _init_tables():
    p = q = 1
    while True:
        p = p ^ ((p << 1) & 0xff) ^ (0x1b if p & 0x80 else 0)
        q ^= q << 1
        q ^= q << 2
        q ^= q << 4
        q &= 0xff
        if q & 0x80:
            q ^= 0x09
        x = q ^ ((q << 1) | (q >> 7)) ^ ((q << 2) | (q >> 6)) ^ ((q << 3) | (q >> 5)) ^ ((q << 4) | (q >> 4))
        x = (x ^ 0x63) & 0xff
        _SBOX[p] = x
        _INV[x] = p
        if p == 1:
            break
    _SBOX[0] = 0x63
    _INV[0x63] = 0


_init_tables()


def _xt(a):
    return ((a << 1) ^ 0x1b) & 0xff if a & 0x80 else a << 1


def _mul(a, b):
    r = 0
    while b:
        if b & 1:
            r ^= a
        a = _xt(a)
        b >>= 1
    return r


class AES:
    def __init__(self, key):
        if len(key) not in (16, 24, 32):
            raise ValueError('AES key must be 16, 24 or 32 bytes')
        nk = len(key) // 4
        self.rounds = nk + 6
        words = [list(key[4 * i:4 * i + 4]) for i in range(nk)]
        rcon = 1
        for i in range(nk, 4 * (self.rounds + 1)):
            t = list(words[i - 1])
            if i % nk == 0:
                t = [_SBOX[b] for b in t[1:] + t[:1]]
                t[0] ^= rcon
                rcon = _xt(rcon)
            elif nk > 6 and i % nk == 4:
                t = [_SBOX[b] for b in t]
            words.append([a ^ b for a, b in zip(words[i - nk], t)])
        self.keys = [sum(words[4 * r:4 * r + 4], []) for r in range(self.rounds + 1)]

    def encrypt_block(self, block):
        s = [b ^ k for b, k in zip(block, self.keys[0])]
        for r in range(1, self.rounds + 1):
            s = [_SBOX[b] for b in s]
            s = [s[(i + 4 * (i % 4)) % 16] for i in range(16)]  # ShiftRows
            if r != self.rounds:
                t = []
                for c in range(4):
                    a = s[4 * c:4 * c + 4]
                    t += [_xt(a[0]) ^ _xt(a[1]) ^ a[1] ^ a[2] ^ a[3],
                          a[0] ^ _xt(a[1]) ^ _xt(a[2]) ^ a[2] ^ a[3],
                          a[0] ^ a[1] ^ _xt(a[2]) ^ _xt(a[3]) ^ a[3],
                          _xt(a[0]) ^ a[0] ^ a[1] ^ a[2] ^ _xt(a[3])]
                s = t
            s = [b ^ k for b, k in zip(s, self.keys[r])]
        return bytes(s)

    def decrypt_block(self, block):
        s = [b ^ k for b, k in zip(block, self.keys[self.rounds])]
        for r in range(self.rounds - 1, -1, -1):
            s = [s[(i - 4 * (i % 4)) % 16] for i in range(16)]  # InvShiftRows
            s = [_INV[b] for b in s]
            s = [b ^ k for b, k in zip(s, self.keys[r])]
            if r:
                t = []
                for c in range(4):
                    a = s[4 * c:4 * c + 4]
                    t += [_mul(a[0], 14) ^ _mul(a[1], 11) ^ _mul(a[2], 13) ^ _mul(a[3], 9),
                          _mul(a[0], 9) ^ _mul(a[1], 14) ^ _mul(a[2], 11) ^ _mul(a[3], 13),
                          _mul(a[0], 13) ^ _mul(a[1], 9) ^ _mul(a[2], 14) ^ _mul(a[3], 11),
                          _mul(a[0], 11) ^ _mul(a[1], 13) ^ _mul(a[2], 9) ^ _mul(a[3], 14)]
                s = t
        return bytes(s)


class CryptoError(ValueError):
    pass


def envelope_encrypt(aes, plain, block=16):
    pad = block - (len(plain) + 5) % block
    data = plain + b'\x00' * pad + struct.pack('<I', zlib.crc32(plain) & 0xffffffff) + bytes([pad])
    return b''.join(aes.encrypt_block(data[i:i + block]) for i in range(0, len(data), block))


def envelope_decrypt(aes, cipher, block=16):
    if not cipher or len(cipher) % block:
        raise CryptoError('Ciphertext is not a whole number of blocks')
    data = b''.join(aes.decrypt_block(cipher[i:i + block]) for i in range(0, len(cipher), block))
    pad = data[-1]
    size = len(data) - 5 - pad
    if not 1 <= pad <= block or size < 0:
        raise CryptoError('Invalid envelope padding')
    plain = data[:size]
    if struct.unpack_from('<I', data, size + pad)[0] != zlib.crc32(plain) & 0xffffffff:
        raise CryptoError('Envelope CRC mismatch')
    return plain


# ----------------------------------------------------------------- RSA / OAEP
def _probable_prime(n):
    if n < 2:
        return False
    for p in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        if n % p == 0:
            return n == p
    d, s = n - 1, 0
    while d % 2 == 0:
        d //= 2
        s += 1
    for _ in range(40):
        a = int.from_bytes(os.urandom(len(str(n))), 'big') % (n - 3) + 2
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(s - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def _prime(bits):
    while True:
        n = int.from_bytes(os.urandom(bits // 8), 'big') | (3 << (bits - 2)) | 1
        if _probable_prime(n):
            return n


class RSAKey:
    def __init__(self, n, e, d):
        self.n, self.e, self.d = n, e, d
        self.size = (n.bit_length() + 7) // 8

    @classmethod
    def generate(cls, bits=1024, e=65537):
        while True:
            p, q = _prime(bits // 2), _prime(bits // 2)
            phi = (p - 1) * (q - 1)
            if p != q and phi % e:
                return cls(p * q, e, pow(e, -1, phi))

    @classmethod
    def load_or_create(cls, path, bits=1024):
        try:
            n, e, d = (int(x, 16) for x in open(path).read().split())
            return cls(n, e, d)
        except (OSError, ValueError):
            key = cls.generate(bits)
            os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
            with open(path, 'w') as stream:
                stream.write('%x %x %x\n' % (key.n, key.e, key.d))
            return key

    def public_der(self):
        """PKCS#1 RSAPublicKey: SEQUENCE { INTEGER n, INTEGER e }."""
        return _der(0x30, _der_int(self.n) + _der_int(self.e))

    def oaep_decrypt(self, cipher, label=b''):
        if len(cipher) != self.size:
            raise CryptoError('RSA ciphertext has wrong length')
        em = pow(int.from_bytes(cipher, 'big'), self.d, self.n).to_bytes(self.size, 'big')
        h = hashlib.sha1
        hl = h().digest_size
        if em[0] != 0:
            raise CryptoError('OAEP leading byte')
        seed = bytes(a ^ b for a, b in zip(em[1:1 + hl], _mgf1(em[1 + hl:], hl)))
        db = bytes(a ^ b for a, b in zip(em[1 + hl:], _mgf1(seed, self.size - hl - 1)))
        if db[:hl] != h(label).digest():
            raise CryptoError('OAEP label hash mismatch')
        rest = db[hl:].lstrip(b'\x00')
        if not rest or rest[0] != 1:
            raise CryptoError('OAEP separator missing')
        return rest[1:]


def _mgf1(seed, length):
    out = b''
    counter = 0
    while len(out) < length:
        out += hashlib.sha1(seed + struct.pack('>I', counter)).digest()
        counter += 1
    return out[:length]


def _der_len(n):
    if n < 128:
        return bytes([n])
    raw = n.to_bytes((n.bit_length() + 7) // 8, 'big')
    return bytes([0x80 | len(raw)]) + raw


def _der(tag, body):
    return bytes([tag]) + _der_len(len(body)) + body


def _der_int(value):
    raw = value.to_bytes(value.bit_length() // 8 + 1, 'big')
    return _der(0x02, raw)
