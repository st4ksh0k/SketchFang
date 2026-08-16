"""
16-bit xorshift stream cipher for Sketchfab BINZ.

Word-wise over little-endian ``u16`` lanes:
  state ^= state >> 7
  state ^= state << 9
  state ^= state >> 13
  word ^= state

Odd trailing bytes are left untouched (``length >> 1`` words only).
"""

from __future__ import annotations

import struct


def xorshift16_step(state: int) -> int:
    state &= 0xFFFF
    state ^= (state >> 7) & 0xFFFF
    state ^= (state << 9) & 0xFFFF
    state ^= (state >> 13) & 0xFFFF
    return state & 0xFFFF


def apply_xorshift16(buf: bytearray, offset: int, length: int, seed: int) -> int:
    """
    XOR ``buf[offset:offset+length]`` in place with the xorshift16 keystream.

    Returns the PRNG state after the last emitted word.
    Only ``length // 2`` words are processed; a final odd byte is unchanged.
    """
    state = seed & 0xFFFF
    end = offset + (length >> 1 << 1)
    pos = offset
    while pos < end:
        state = xorshift16_step(state)
        w = struct.unpack_from("<H", buf, pos)[0] ^ state
        struct.pack_into("<H", buf, pos, w)
        pos += 2
    return state
