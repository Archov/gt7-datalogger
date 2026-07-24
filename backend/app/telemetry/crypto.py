"""Salsa20 decryption of GT7 telemetry packets.

GT7 encrypts every UDP packet with Salsa20. The 32-byte key is fixed and
publicly known; the 8-byte nonce is derived from a 4-byte IV embedded
(unencrypted, as part of the keystream quirk) at offset 0x40 of the packet.
"""

from __future__ import annotations

import struct

from Crypto.Cipher import Salsa20

KEY = b"Simulator Interface Packet GT7 ver 0.0"[:32]
IV_OFFSET = 0x40
IV_XOR = 0xDEADBEAF
MAGIC = 0x47375330  # "G7S0" little-endian


def decrypt_packet(data: bytes) -> bytes | None:
    """Decrypt a raw GT7 UDP packet. Returns None if the result is invalid."""
    if len(data) < IV_OFFSET + 4:
        return None
    iv1 = struct.unpack_from("<I", data, IV_OFFSET)[0]
    iv2 = iv1 ^ IV_XOR
    nonce = struct.pack("<II", iv2, iv1)
    plain = Salsa20.new(key=KEY, nonce=nonce).decrypt(data)
    if struct.unpack_from("<I", plain, 0)[0] != MAGIC:
        return None
    return plain


def encrypt_packet(plain: bytes) -> bytes:
    """Encrypt a plaintext packet the way GT7 would (used by tests/simulator).

    Salsa20 is symmetric, but the IV must survive encryption at IV_OFFSET so the
    receiver can derive the nonce. We encrypt, then splice the keystream so the
    IV bytes remain readable — mirroring how the real packets carry it.
    """
    iv1 = struct.unpack_from("<I", plain, IV_OFFSET)[0]
    iv2 = iv1 ^ IV_XOR
    nonce = struct.pack("<II", iv2, iv1)
    cipher = Salsa20.new(key=KEY, nonce=nonce).encrypt(plain)
    # Restore the IV bytes in the ciphertext: decrypt_packet reads them raw.
    return cipher[:IV_OFFSET] + plain[IV_OFFSET : IV_OFFSET + 4] + cipher[IV_OFFSET + 4 :]
