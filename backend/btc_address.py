"""
Lightweight Bitcoin mainnet address validator.

- P2PKH (Base58Check, prefix 0x00, starts with '1')
- P2SH  (Base58Check, prefix 0x05, starts with '3')
- P2WPKH/P2WSH (Bech32, hrp 'bc', starts with 'bc1q')
- P2TR  (Bech32m, hrp 'bc', starts with 'bc1p')

No external Bitcoin library required — only `base58` (stdlib-style) for
Base58Check decoding; Bech32/Bech32m verified via reference implementation
adapted from BIP-173 and BIP-350.
"""
from __future__ import annotations

import hashlib
from typing import Optional, Tuple

import base58


# ----- Bech32 / Bech32m reference (BIP-173 / BIP-350) -----
CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _bech32_polymod(values):
    GEN = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3]
    chk = 1
    for v in values:
        b = chk >> 25
        chk = ((chk & 0x1ffffff) << 5) ^ v
        for i in range(5):
            chk ^= GEN[i] if (b >> i) & 1 else 0
    return chk


def _bech32_hrp_expand(hrp):
    return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]


def _bech32_verify_checksum(hrp, data):
    const = _bech32_polymod(_bech32_hrp_expand(hrp) + data)
    if const == 1:
        return "bech32"
    if const == 0x2bc830a3:
        return "bech32m"
    return None


def _bech32_decode(addr: str) -> Optional[Tuple[str, list, str]]:
    if any(ord(x) < 33 or ord(x) > 126 for x in addr):
        return None
    if addr.lower() != addr and addr.upper() != addr:
        return None
    addr = addr.lower()
    pos = addr.rfind("1")
    if pos < 1 or pos + 7 > len(addr) or len(addr) > 90:
        return None
    hrp = addr[:pos]
    data = []
    for c in addr[pos + 1 :]:
        if c not in CHARSET:
            return None
        data.append(CHARSET.find(c))
    spec = _bech32_verify_checksum(hrp, data)
    if not spec:
        return None
    return hrp, data[:-6], spec


def _convertbits(data, frombits, tobits, pad=True):
    acc = 0
    bits = 0
    ret = []
    maxv = (1 << tobits) - 1
    max_acc = (1 << (frombits + tobits - 1)) - 1
    for value in data:
        if value < 0 or (value >> frombits):
            return None
        acc = ((acc << frombits) | value) & max_acc
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)
    if pad:
        if bits:
            ret.append((acc << (tobits - bits)) & maxv)
    elif bits >= frombits or ((acc << (tobits - bits)) & maxv):
        return None
    return ret


def _decode_segwit_address(hrp_required: str, addr: str):
    d = _bech32_decode(addr)
    if d is None:
        return None
    hrp, data, spec = d
    if hrp != hrp_required:
        return None
    if not data:
        return None
    witver = data[0]
    decoded = _convertbits(data[1:], 5, 8, False)
    if decoded is None or len(decoded) < 2 or len(decoded) > 40:
        return None
    if witver > 16:
        return None
    if witver == 0 and len(decoded) != 20 and len(decoded) != 32:
        return None
    if witver == 0 and spec != "bech32":
        return None
    if witver != 0 and spec != "bech32m":
        return None
    return witver, decoded


def validate_btc_mainnet_address(addr: str) -> dict:
    """
    Returns: {valid: bool, type: 'p2pkh'|'p2sh'|'p2wpkh'|'p2wsh'|'p2tr'|None,
              error: str|None}
    """
    if not addr or not isinstance(addr, str):
        return {"valid": False, "type": None, "error": "empty"}
    addr = addr.strip()
    # Bech32 / Bech32m
    if addr.lower().startswith("bc1"):
        r = _decode_segwit_address("bc", addr)
        if r is None:
            return {"valid": False, "type": None, "error": "invalid bech32 checksum"}
        witver, prog = r
        if witver == 0 and len(prog) == 20:
            return {"valid": True, "type": "p2wpkh", "error": None}
        if witver == 0 and len(prog) == 32:
            return {"valid": True, "type": "p2wsh", "error": None}
        if witver == 1 and len(prog) == 32:
            return {"valid": True, "type": "p2tr", "error": None}
        return {"valid": True, "type": f"witness_v{witver}", "error": None}
    # Base58Check (P2PKH / P2SH)
    try:
        decoded = base58.b58decode_check(addr)
    except Exception as e:
        return {"valid": False, "type": None, "error": f"base58 decode failed: {e}"}
    if len(decoded) != 21:
        return {"valid": False, "type": None, "error": "unexpected payload length"}
    prefix = decoded[0]
    if prefix == 0x00:  # mainnet P2PKH
        return {"valid": True, "type": "p2pkh", "error": None}
    if prefix == 0x05:  # mainnet P2SH
        return {"valid": True, "type": "p2sh", "error": None}
    return {"valid": False, "type": None, "error": f"non-mainnet prefix 0x{prefix:02x}"}
