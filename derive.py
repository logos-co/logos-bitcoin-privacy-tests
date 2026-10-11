#!/usr/bin/env python3
# BIP32 public derivation and P2WPKH (bech32) addresses from an account xpub or descriptor.
# `selftest` checks the code against BIP84's published vectors for the public test phrase.
import hashlib, hmac, re, sys

P = 2**256 - 2**32 - 977
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
G = (0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
     0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8)
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
VERSIONS = {"xpub": 0x0488B21E, "tpub": 0x043587CF, "zpub": 0x04B24746, "vpub": 0x045F1CF6}


def add(p, q):
    if p is None: return q
    if q is None: return p
    if p[0] == q[0] and (p[1] + q[1]) % P == 0: return None
    if p == q: l = 3 * p[0] * p[0] * pow(2 * p[1], P - 2, P) % P
    else: l = (q[1] - p[1]) * pow(q[0] - p[0], P - 2, P) % P
    x = (l * l - p[0] - q[0]) % P
    return (x, (l * (p[0] - x) - p[1]) % P)


def mul(k, p=G):
    r = None
    while k:
        if k & 1: r = add(r, p)
        p, k = add(p, p), k >> 1
    return r


def ser(p): return bytes([2 + (p[1] & 1)]) + p[0].to_bytes(32, "big")


def deser(b):
    x = int.from_bytes(b[1:], "big")
    y = pow((x ** 3 + 7) % P, (P + 1) // 4, P)
    return (x, y if (y & 1) == (b[0] & 1) else P - y)


def h160(b): return hashlib.new("ripemd160", hashlib.sha256(b).digest()).digest()


def b58check_decode(s):
    n = 0
    for c in s: n = n * 58 + B58.index(c)
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    raw = b"\0" * (len(s) - len(s.lstrip("1"))) + raw
    body, chk = raw[:-4], raw[-4:]
    assert hashlib.sha256(hashlib.sha256(body).digest()).digest()[:4] == chk, "bad checksum"
    return body


def b58check_encode(b):
    b = b + hashlib.sha256(hashlib.sha256(b).digest()).digest()[:4]
    n, out = int.from_bytes(b, "big"), ""
    while n: n, r = divmod(n, 58); out = B58[r] + out
    return "1" * (len(b) - len(b.lstrip(b"\0"))) + out


def bech32_polymod(values):
    gen, chk = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3], 1
    for v in values:
        top = chk >> 25
        chk = (chk & 0x1ffffff) << 5 ^ v
        for i in range(5): chk ^= gen[i] if ((top >> i) & 1) else 0
    return chk


def segwit_v0(hrp, prog):
    data, acc, bits = [0], 0, 0
    for b in prog:
        acc, bits = (acc << 8) | b, bits + 8
        while bits >= 5: bits -= 5; data.append((acc >> bits) & 31)
    if bits: data.append((acc << (5 - bits)) & 31)
    exp = [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]
    pm = bech32_polymod(exp + data + [0] * 6) ^ 1
    return hrp + "1" + "".join("qpzry9x8gf2tvdw0s3jn54khce6mua7l"[d] for d in data + [(pm >> 5 * (5 - i)) & 31 for i in range(6)])


class XPub:
    def __init__(self, key, chain): self.key, self.chain = key, chain

    @classmethod
    def parse(cls, s):
        b = b58check_decode(s)
        return cls(deser(b[45:78]), b[13:45])

    def child(self, i):
        I = hmac.new(self.chain, ser(self.key) + i.to_bytes(4, "big"), hashlib.sha512).digest()
        return XPub(add(mul(int.from_bytes(I[:32], "big")), self.key), I[32:])

    def address(self, hrp): return segwit_v0(hrp, h160(ser(self.key)))


def from_descriptor(desc):
    """wpkh([fp/84h/1h/0h]tpub.../0/*) -> (xpub string, branch)."""
    m = re.search(r"\](\w+pub\w+)/(\d+)/\*", desc)
    assert desc.startswith("wpkh("), f"not a wpkh descriptor: {desc[:20]}"
    return m.group(1), int(m.group(2))


def addresses(xpub, branch, start, count, hrp):
    b = XPub.parse(xpub).child(branch)
    return [b.child(i).address(hrp) for i in range(start, start + count)]


def test_phrase_account(coin, version):
    """The public BIP39 test phrase's BIP84 account xpub, m/84'/coin'/0' (used before a wallet exists)."""
    phrase = " ".join(["abandon"] * 11 + ["about"])
    seed = hashlib.pbkdf2_hmac("sha512", phrase.encode(), b"mnemonic", 2048)
    I = hmac.new(b"Bitcoin seed", seed, hashlib.sha512).digest()
    k, c, fp = int.from_bytes(I[:32], "big"), I[32:], b""
    for i in (84 | 1 << 31, coin | 1 << 31, 0 | 1 << 31):
        fp = h160(ser(mul(k)))[:4]
        I = hmac.new(c, b"\0" + k.to_bytes(32, "big") + i.to_bytes(4, "big"), hashlib.sha512).digest()
        k, c = (int.from_bytes(I[:32], "big") + k) % N, I[32:]
    return b58check_encode(VERSIONS[version].to_bytes(4, "big") + b"\3" + fp + (1 << 31).to_bytes(4, "big") + c + ser(mul(k)))


def selftest():
    # BIP84's vectors for the public BIP39 test phrase (abandon x11 about).
    zpub = test_phrase_account(0, "zpub")
    want = "zpub6rFR7y4Q2AijBEqTUquhVz398htDFrtymD9xYYfG1m4wAcvPhXNfE3EfH1r1ADqtfSdVCToUG868RvUUkgDKf31mGDtKsAYz2oz2AGutZYs"
    assert zpub == want, zpub
    assert addresses(zpub, 0, 0, 1, "bc") == ["bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu"]
    assert addresses(zpub, 1, 0, 1, "bc") == ["bc1q8c6fshw2dlwun7ekn9qwf37cu2rn755upcp6el"]
    print("selftest ok: BIP84 account zpub and first receive/change addresses match")


if __name__ == "__main__":
    if sys.argv[1:] == ["selftest"]: selftest()
    elif sys.argv[1] == "test-phrase-account": print(test_phrase_account(1, "tpub"))
    else:
        xpub, branch = from_descriptor(sys.argv[1])
        for a in addresses(xpub, branch, int(sys.argv[2]), int(sys.argv[3]), sys.argv[4] if len(sys.argv) > 4 else "tb"): print(a)
