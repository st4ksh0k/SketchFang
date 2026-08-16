"""`GET /i/models/{uid}` — model metadata and the encrypted stream URLs."""

from __future__ import annotations

from ..util.log import log
from .client import API_ROOT, get_json

API_METADATA = API_ROOT + "/i/models/{uid}"


def fetch_metadata(uid: str, *, progress: bool = True) -> dict:
    url = API_METADATA.format(uid=uid)
    if progress:
        log(f"[*] Fetching metadata: {url}")
    data = get_json(url)
    if progress:
        log(
            f"[*] Model: {data.get('name', uid)}  |  "
            f"{data.get('vertexCount', '?')} verts  |  "
            f"{data.get('faceCount', '?')} faces"
        )
    return data


def pick_best_file(meta: dict) -> dict:
    """The largest `files[]` entry — the full-resolution stream the viewer loads."""
    files = meta.get("files") or []
    if not files:
        raise RuntimeError("No files in model metadata")
    return max(files, key=lambda f: f.get("modelSize", 0))


def osgjs_url_of(entry: dict) -> str:
    url = entry.get("osgjsUrl") or ""
    if not url:
        raise RuntimeError("No osgjsUrl in metadata")
    return url


def model_file_url(osgjs_url: str) -> str:
    if "file.binz" in osgjs_url:
        return osgjs_url.replace("file.binz", "model_file.binz")
    if osgjs_url.endswith(".binz"):
        return osgjs_url[:-5] + "_model.binz"
    return osgjs_url.rsplit("/", 1)[0] + "/model_file.binz"
