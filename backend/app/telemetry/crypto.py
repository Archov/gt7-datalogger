"""Salsa20 decryption of GT7 telemetry packets.

GT7 encrypts every UDP packet with Salsa20. The 32-byte key is fixed and
publicly known; the 8-byte nonce is derived from a 4-byte IV embedded
(unencrypted, as part of the keystream quirk) at offset 0x40 of the packet.

The IV XOR constant differs per packet format (A/B/~/C, distinguished by
size), so decryption picks the constant matching the datagram length and
falls back to trying the others — the magic check tells us when it worked.
"""

from __future__ import annotations

import struct

from Crypto.Cipher import Salsa20

from app.telemetry.packet import (
    PACKET_SIZE_A,
    PACKET_SIZE_B,
    PACKET_SIZE_C,
    PACKET_SIZE_TILDE,
)

KEY = b"Simulator Interface Packet GT7 ver 0.0"[:32]
IV_OFFSET = 0x40
MAGIC = 0x47375330  # "G7S0" little-endian

# Per-format IV XOR constants (community-documented; B and C share one).
XOR_A = 0xDEADBEAF
XOR_B = 0xDEADBEEF
XOR_TILDE = 0x55FABB4F
_XOR_BY_SIZE = {
    PACKET_SIZE_A: XOR_A,
    PACKET_SIZE_B: XOR_B,
    PACKET_SIZE_TILDE: XOR_TILDE,
    PACKET_SIZE_C: XOR_B,
}


def _try_decrypt(data: bytes, xor: int) -> bytes | None:
    iv1 = struct.unpack_from("<I", data, IV_OFFSET)[0]
    iv2 = iv1 ^ xor
    nonce = struct.pack("<II", iv2, iv1)
    plain = Salsa20.new(key=KEY, nonce=nonce).decrypt(data)
    if struct.unpack_from("<I", plain, 0)[0] != MAGIC:
        return None
    return plain


def decrypt_packet(data: bytes) -> bytes | None:
    """Decrypt a raw GT7 UDP packet. Returns None if the result is invalid."""
    if len(data) < IV_OFFSET + 4:
        return None
    first = _XOR_BY_SIZE.get(len(data), XOR_A)
    for xor in (first, *(x for x in (XOR_A, XOR_B, XOR_TILDE) if x != first)):
        plain = _try_decrypt(data, xor)
        if plain is not None:
            return plain
    return None


def encrypt_packet(plain: bytes) -> bytes:
    """Encrypt a plaintext packet the way GT7 would (used by tests/simulator).

    Salsa20 is symmetric, but the IV must survive encryption at IV_OFFSET so the
    receiver can derive the nonce. We encrypt, then splice the keystream so the
    IV bytes remain readable — mirroring how the real packets carry it.
    """
    iv1 = struct.unpack_from("<I", plain, IV_OFFSET)[0]
    iv2 = iv1 ^ _XOR_BY_SIZE.get(len(plain), XOR_A)
    nonce = struct.pack("<II", iv2, iv1)
    cipher = Salsa20.new(key=KEY, nonce=nonce).encrypt(plain)
    # Restore the IV bytes in the ciphertext: decrypt_packet reads them raw.
    return cipher[:IV_OFFSET] + plain[IV_OFFSET : IV_OFFSET + 4] + cipher[IV_OFFSET + 4 :]
