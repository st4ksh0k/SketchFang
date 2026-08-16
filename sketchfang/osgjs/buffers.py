"""
OSGJS array readers.

An OSGJS `Array` entry is either inline (base64 / Elements) or File-backed into
the decrypted model binary, optionally varint-encoded.
"""

from __future__ import annotations

import base64
import json
import struct


def parse_userdata(node: dict) -> dict:
    """`UserDataContainer.Values` → plain dict, JSON-decoding values when possible."""
    out: dict = {}
    for item in (node.get("UserDataContainer") or {}).get("Values") or []:
        name = item.get("Name")
        val = item.get("Value")
        if name is None:
            continue
        try:
            out[name] = json.loads(val)
        except (TypeError, json.JSONDecodeError):
            out[name] = val
    return out


def decode_varint(data: bytes, offset: int, count: int, type_name: str) -> list[int]:
    out: list[int] = []
    o = offset
    for _ in range(count):
        s = 0
        shift = 0
        while True:
            b = data[o]
            o += 1
            s |= (b & 127) << shift
            shift += 7
            if (b & 128) == 0:
                break
        out.append(s & 0xFFFFFFFF)
    if not type_name.startswith("U"):
        out = [(c >> 1) ^ (-(c & 1)) for c in out]
    return out


def read_typed_array(data: bytes, offset: int, count: int, type_name: str) -> list[int]:
    if type_name == "Uint8Array":
        return list(data[offset : offset + count])
    if type_name == "Uint16Array":
        return list(struct.unpack_from(f"<{count}H", data, offset))
    if type_name == "Uint32Array":
        return list(struct.unpack_from(f"<{count}I", data, offset))
    if type_name == "Int32Array":
        return list(struct.unpack_from(f"<{count}i", data, offset))
    if type_name == "Float32Array":
        return list(struct.unpack_from(f"<{count}f", data, offset))
    raise ValueError(f"Unsupported typed array {type_name}")


def read_array_buffer(meta: dict, item_size: int, bin_map: dict[str, bytes]) -> list:
    """Read an OSGJS Array entry (inline or File-backed, optionally varint)."""
    type_name = next(iter(meta))
    info = meta[type_name]
    count = int(info["Size"]) * int(item_size)
    if "File" in info:
        fname = info["File"]
        # decrypted buffers are keyed without .binz, and with original name
        blob = bin_map.get(fname) or bin_map.get(fname.replace(".binz", ".bin"))
        if blob is None:
            # try bare name
            for k, v in bin_map.items():
                if k.endswith(fname) or fname.endswith(k):
                    blob = v
                    break
        if blob is None:
            raise KeyError(f"Missing binary file {fname!r} (have {list(bin_map)})")
        off = int(info.get("Offset") or 0)
        if info.get("Encoding") == "varint":
            return decode_varint(blob, off, count, type_name)
        return read_typed_array(blob, off, count, type_name)

    # Inline
    if "Elements" in info:
        return list(info["Elements"])
    raw_b64 = info.get("Array") or info.get("array")
    if isinstance(raw_b64, str):
        raw = base64.b64decode(raw_b64)
        return read_typed_array(raw, 0, count, type_name)
    raise ValueError(f"Unrecognized array buffer: {info!r}")
