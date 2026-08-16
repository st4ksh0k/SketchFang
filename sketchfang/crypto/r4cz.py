"""
Sketchfab `r4Cz` container — post-decrypt BINZ payload.

After the stream cipher transforms ``file.binz`` in place,
the buffer is:

    magic      : b'r4Cz'          (4)
    version    : u32le            (4)  — observed 1
    nframes    : u32le            (4)
    unc_size   : u32le            (4)  — total decompressed bytes
    hdr_size   : u32le            (4)  — == 20 + 4*nframes
    ends[i]    : u32le * nframes  — exclusive end offset of frame i
    frames     : nframes × Zstd frames (each starts with 28 B5 2F FD)

Concatenating Zstd-decompress(frame[i]) yields OSGJS JSON and matches
``unc_size``.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

try:
    import zstandard as zstd
except ImportError:  # pragma: no cover
    zstd = None  # type: ignore

MAGIC = b"r4Cz"


@dataclass(frozen=True)
class R4Cz:
    version: int
    uncompressed_size: int
    header_size: int
    frame_ends: tuple[int, ...]
    data: bytes

    @property
    def nframes(self) -> int:
        return len(self.frame_ends)

    def frame_slices(self) -> list[bytes]:
        start = self.header_size
        out: list[bytes] = []
        for end in self.frame_ends:
            if end < start or end > len(self.data):
                raise ValueError(f"bad frame end {end} (start={start}, len={len(self.data)})")
            out.append(self.data[start:end])
            start = end
        return out


def parse_r4cz(data: bytes) -> R4Cz:
    if len(data) < 20 or data[:4] != MAGIC:
        raise ValueError(f"not an r4Cz buffer (head={data[:4]!r})")
    version, nframes, unc, hdr = struct.unpack_from("<4I", data, 4)
    if nframes == 0 or nframes > 4096:
        raise ValueError(f"unreasonable nframes={nframes}")
    expect_hdr = 20 + 4 * nframes
    if hdr != expect_hdr:
        raise ValueError(f"hdr_size {hdr} != {expect_hdr}")
    if len(data) < hdr:
        raise ValueError("truncated r4Cz header")
    ends = struct.unpack_from("<" + "I" * nframes, data, 20)
    if ends[-1] != len(data):
        # some streams may pad; allow ends[-1] <= len
        if ends[-1] > len(data):
            raise ValueError(f"last end {ends[-1]} beyond buffer {len(data)}")
    return R4Cz(
        version=version,
        uncompressed_size=unc,
        header_size=hdr,
        frame_ends=tuple(ends),
        data=data,
    )


def inflate_r4cz(data: bytes) -> bytes:
    """Parse r4Cz and Zstd-decompress all frames → OSGJS bytes."""
    if zstd is None:
        raise RuntimeError("Missing dependency: pip install zstandard")
    container = parse_r4cz(data)
    dctx = zstd.ZstdDecompressor()
    parts: list[bytes] = []
    limit = container.uncompressed_size + 1024
    for i, frame in enumerate(container.frame_slices()):
        if frame[:4] != b"\x28\xb5\x2f\xfd":
            raise ValueError(f"frame[{i}] missing Zstd magic: {frame[:4]!r}")
        parts.append(dctx.decompress(frame, max_output_size=limit))
    out = b"".join(parts)
    if len(out) != container.uncompressed_size:
        raise ValueError(
            f"decompressed size {len(out)} != header unc_size {container.uncompressed_size}"
        )
    return out
