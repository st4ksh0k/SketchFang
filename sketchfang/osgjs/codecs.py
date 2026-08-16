"""
OSGJS compression codecs (viewer Mq9W / H+3W / IuDx / vNR5).

Pure list-in / list-out functions: index compression, vertex prediction,
spherical normal unpacking, and bbox dequantization.
"""

from __future__ import annotations

import math

# `attributes` bit field on a geometry's UserData
ATTR_VERTEX = 1
ATTR_NORMAL = 2
ATTR_TEXCOORD = 4
ATTR_TRIANGLE = 16
ATTR_TANGENT = 32

# `triangle_mode` bit field
TRI_DELTA = 1
TRI_WATERMARK = 2
TRI_IMPLICIT = 4

# `vertex_mode` / `uv_*_mode` bit field
VTX_BBOX = 1
VTX_PREDICT = 2


def delta_decode(arr: list[int], start: int = 0) -> list[int]:
    if start >= len(arr):
        return arr
    r = arr[start]
    for i in range(start + 1, len(arr)):
        o = arr[i]
        r = arr[i] = (r + ((o >> 1) ^ (-(o & 1)))) & 0xFFFFFFFF
    return arr


def watermark_decode_u16(arr: list[int], state: list[int]) -> list[int]:
    n = state[0]
    for i in range(len(arr)):
        o = n - arr[i]
        arr[i] = o & 0xFFFF
        if n <= o:
            n = o + 1
    state[0] = n
    return arr


def implicit_expand(src: list[int], out_len: int, stream_start: int, use_repeat: bool) -> list[int]:
    """Port of viewer implicit triangle-strip index expand (MSB mask walk)."""
    mask_len = src[1]
    expected = src[2]
    unused = 32 * mask_len - out_len
    i = stream_start
    r = expected
    out = [0] * out_len
    for u in range(mask_len):
        c = src[3 + u] & 0xFFFFFFFF
        d = unused if u == mask_len - 1 else 0
        h = 32 * u
        while d < 32:
            if h < out_len:
                bit = (c & (0x80000000 >> d)) != 0
                if bit:
                    out[h] = src[i] & 0xFFFF
                    i += 1
                else:
                    out[h] = r & 0xFFFF
                    if not use_repeat:
                        r += 1
            d += 1
            h += 1
    return out


def strip_to_triangles(strip: list[int]) -> list[int]:
    tris: list[int] = []
    for i in range(len(strip) - 2):
        a, b, c = strip[i], strip[i + 1], strip[i + 2]
        if a == b or b == c or a == c:
            continue
        if i & 1:
            tris.extend((a, c, b))
        else:
            tris.extend((a, b, c))
    return tris


def predict_vertices(verts: list[int], item_size: int, indices: list[int]) -> None:
    """Parallelogram prediction, in place, following the strip index order."""
    n = len(verts) // item_size
    if n == 0 or len(indices) < 4:
        return
    seen = bytearray(n)
    for ii in (0, 1, 2):
        if 0 <= indices[ii] < n:
            seen[indices[ii]] = 1
    for o in range(2, len(indices) - 1):
        l, u, c, h = indices[o - 2], indices[o - 1], indices[o], indices[o + 1]
        if not (0 <= h < n) or seen[h]:
            continue
        seen[h] = 1
        L, U, C, H = l * item_size, u * item_size, c * item_size, h * item_size
        for d in range(item_size):
            verts[H + d] = verts[H + d] + verts[U + d] + verts[C + d] - verts[L + d]


def unpack_normals(packed: list[int], epsilon: float = 0.25, nphi: int = 720) -> list[float]:
    """IuDx spherical pack → XYZ normals."""
    pi = 3.14159265359
    u = math.cos(0.01745329251 * epsilon)
    d = pi / (nphi - 1)
    g = 1.57079632679 / (nphi - 1)
    count = len(packed) // 2
    out = [0.0] * (3 * count)
    for i in range(count):
        s = packed[2 * i]
        x = packed[2 * i + 1]
        a = s * d
        r = math.cos(a)
        w = math.sin(a)
        a += g
        e = (u - r * math.cos(a)) / max(1e-5, w * math.sin(a))
        e = max(-1.0, min(1.0, e))
        p = 6.28318530718 * x / math.ceil(pi / max(1e-5, math.acos(e)))
        out[3 * i] = w * math.cos(p)
        out[3 * i + 1] = w * math.sin(p)
        out[3 * i + 2] = r
    return out


def dequantize(values: list[int], item_size: int, bbl: list[float], step: list[float]) -> list[float]:
    out: list[float] = []
    n = len(values) // item_size
    for i in range(n):
        for d in range(item_size):
            out.append(bbl[d] + values[i * item_size + d] * step[d])
    return out
