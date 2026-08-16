"""
`GET /i/models/{uid}/options` — the shading state the viewer itself loads.

Every material here carries its `stateSetID`, which is the exact join key back
to an OSGJS StateSet (see ``materials.stateset``). The payload also carries the
author's root ``orientation.matrix`` that the Sketchfab viewer applies before
display.
"""

from __future__ import annotations

from ..util.matrix import IDENTITY_MAT
from .client import API_ROOT, get_json

API_OPTIONS = API_ROOT + "/i/models/{uid}/options"


def fetch_options(uid: str, *, timeout: int = 30) -> dict:
    return get_json(API_OPTIONS.format(uid=uid), timeout=timeout, referer=True)


def orientation_matrix(options: dict | None) -> list[float]:
    """Column-major 4×4 from `options.orientation.matrix`, or identity."""
    raw = ((options or {}).get("orientation") or {}).get("matrix")
    if isinstance(raw, list) and len(raw) == 16:
        return [float(x) for x in raw]
    return IDENTITY_MAT[:]
