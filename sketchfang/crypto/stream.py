"""
BINZ stream decrypt — pure Python.

Pipeline:
  protection.b → session bytecode
  file.binz    → xorshift16 (session VM) → r4Cz → Zstd frames → OSGJS
"""

from __future__ import annotations

import base64
import zlib

from ..util.log import log
from .protection import unwrap_protection
from .r4cz import inflate_r4cz
from .session_vm import decrypt_binz_with_session


def maybe_gunzip(data: bytes) -> bytes:
    if len(data) >= 2 and data[:2] == b"\x1f\x8b":
        return zlib.decompress(data, zlib.MAX_WBITS | 16)
    return data


def decrypt_binz_to_r4cz(
    encrypted: bytes,
    protection_key: bytes,
    *,
    do_key_material: bool = True,
    progress: bool = False,
) -> bytes:
    """
    Run the stream cipher only; return the decrypted r4Cz bytes.

    ``protection_key`` is raw (already base64-decoded) ``files[].p.b``.
    Extra kwargs are accepted for call-site compatibility and ignored.
    """
    del do_key_material, progress
    session = unwrap_protection(protection_key)
    return decrypt_binz_with_session(encrypted, session)


def decrypt_binz(
    raw: bytes, protection: list | dict | None, progress: bool = True
) -> bytes:
    """
    Decrypt one stream using a metadata ``files[].p`` protection entry.

    Returns OSGJS JSON bytes (or gunzipped payload if the input was gzip).
    """
    if not protection:
        return maybe_gunzip(raw)
    entry = protection[0] if isinstance(protection, list) else protection
    key_b64 = (entry or {}).get("b")
    if not key_b64:
        return maybe_gunzip(raw)
    prot = base64.b64decode(
        key_b64.replace("\n", "").replace("\r", "").replace(" ", "")
    )
    if progress:
        log(f"[*] Decrypting {len(raw):,} bytes (session VM + xorshift16) ...")
    r4 = decrypt_binz_to_r4cz(raw, prot)
    out = inflate_r4cz(r4)
    if progress:
        log(f"[*] Decrypted → {len(out):,} bytes OSGJS")
    return out
