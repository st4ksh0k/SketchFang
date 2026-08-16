"""
SketchFang texture unscrambler — ports the viewer's GPU shader path.

EDUCATIONAL USE ONLY. Mirrors Sketchfab viewer `applyTexImage2D` when `image.pk`
is set: upload scrambled tex → fullscreen pass with offset `-(pk*64 % (w*h))`.

Source: viewer chunk `applyTexImage2D` → helper `y()` → fragment shader uniforms
`uT` / `uS` / `uO` / `uY` (8×8 tile diagonal serialize + per-tile rotate).
"""

from __future__ import annotations

import math
from pathlib import Path

try:
    from PIL import Image
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Missing dependency: pip install pillow") from exc


# ---------------------------------------------------------------------------
# GLSL integer helpers (exact port; names mirror overloaded shader funcs)
# ---------------------------------------------------------------------------

def _mod(i: int, u: int) -> int:
    """f(int,int) — GLSL-style toward-zero remainder."""
    return i - (i // u) * u


def _min(a: int, b: int) -> int:
    return a if a < b else b


def _max(a: int, b: int) -> int:
    return b if a < b else a


def _tri(y: int, t: int, f: int) -> int:
    """f(int y, int t, int f) — prefix length along diagonal serialize."""
    x = _min(y, t)
    n = _max(y, t)
    if f < x:
        return f * (f + 1) // 2
    if f < n:
        return x * (x + 1) // 2 + x * (f - x)
    r = f - n
    return x * (x + 1) // 2 + x * (n - x) + (x - 1) * r - (r - 1) * r // 2


def _tile_index(y: int, t: int, xx: int, xy: int) -> int:
    """i(int y, int t, ivec2 x) — 2D tile coord → diagonal index."""
    r = _min(y, t)
    n = _max(y, t)
    v = xx + xy
    h = _mod(v, 2) == 0
    if v < r:
        if h:
            return _tri(y, t, v) + v - xy
        return _tri(y, t, v) + xy
    if v < n:
        s = t - xy - 1
        if y < t:
            s = r - (y - xx)
        if h:
            return _tri(y, t, v) + s
        return _tri(y, t, v) + r - s - 1
    s = t - xy - 1
    e = r + n - v - 1
    if h:
        return _tri(y, t, v) + s
    return _tri(y, t, v) + e - s - 1


def _tile_coord(y: int, t: int, x: int) -> tuple[int, int]:
    """u(int y, int t, int x) — diagonal index → 2D tile coord."""
    v = _min(y, t)
    r = _max(y, t)
    if x < v * (v + 1) // 2:
        n = (-1 + int(1e-6 + math.sqrt(float(8 * x + 1)))) // 2
        h = x - _tri(y, t, n)
        s = _mod(n, 2) == 0
        if s:
            return h, n - h
        return n - h, h
    if x < v * (v + 1) // 2 + v * (r - v):
        x = x - v * (v + 1) // 2
        n = v + x // v
        s = _mod(x, v)
        h = _mod(n, 2) == 0
        g = n - v + s + 1
        e = v - s - 1
        S = n - s
        T = s
        if y > t:
            if h:
                return g, e
            return S, T
        if h:
            return T, S
        return e, g
    n = v * (v - 1) // 2 - (x - (v * (v + 1) // 2 + v * (r - v))) - 1
    s = (-1 + int(math.sqrt(float(8 * n + 1)))) // 2
    n = r + v - s - 2
    h = x - _tri(y, t, n)
    g = _mod(n, 2) == 0
    e = v + r - n - 1
    if g:
        h = e - h - 1
    S = n + h - y + 1
    return n - S, S


def _pix_to_linear(w: int, h: int, px: int, py: int) -> int:
    """f(ivec2) — output pixel → scrambled linear index."""
    tiles_x = w // 8
    tiles_y = h // 8
    x = _tile_index(tiles_x, tiles_y, px // 8, py // 8)
    n = _mod(x, 4)
    vx = _mod(px, 8)
    vy = _mod(py, 8)
    rx, ry = vx, vy
    if n == 1:
        rx = 7 - vx
    elif n == 2:
        rx, ry = vy, vx
    elif n == 3:
        rx, ry = 7 - vy, vx
    return x * 64 + rx + ry * 8


def _linear_to_pix(w: int, h: int, i: int) -> tuple[int, int]:
    """i(int) — scrambled linear index → source pixel."""
    v = w * h
    if i < 0:
        i += v
    i = _mod(i, v)
    tiles_x = w // 8
    tiles_y = h // 8
    tile = i // 64
    r = i - tile * 64
    s = r // 8
    S = r - s * 8
    e = _mod(tile, 4)
    gx, gy = _tile_coord(tiles_x, tiles_y, tile)
    tx, ty = gx * 8, gy * 8
    if e == 0:
        tx += S
        ty += s
    elif e == 1:
        tx += 7 - S
        ty += s
    elif e == 2:
        tx += s
        ty += S
    elif e == 3:
        tx += s
        ty += 7 - S
    return tx, ty


def _apply_offset(w: int, h: int, px: int, py: int, offset: int) -> int | None:
    """t(ivec2, int) — linear index after offset, or None if out of range."""
    v = w * h
    n = _pix_to_linear(w, h, px, py) + offset
    if n > v:
        n -= v
    if n < 0:
        n += v
    if n > v:
        return None
    if n < 0:
        return None
    return n


def pk_offset(pk: int, width: int, height: int) -> int:
    """Viewer: e = pk; e *= 64; e %= W*H; prepare(-e, ...)."""
    return -((pk * 64) % (width * height))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def unscramble_image(
    image: Image.Image,
    pk: int,
    *,
    flip_y: bool = False,
    flip_x: bool = False,
) -> Image.Image:
    """
    Unscramble a Sketchfab CDN texture using its `pk` field.

    Prefer power-of-two processed variants (width/height divisible by 8);
    non-multiples of 8 still run (viewer uses integer tile counts).

    ``flip_y`` reproduces the viewer's ``uY`` pass: the shader draws into a GL
    framebuffer with a bottom-left origin, so a top-left PNG needs the row
    flip. Callers writing glTF want it on.

    ``flip_x`` is a debugging aid only. Mirroring X makes silkscreen look
    upright in an image viewer but moves it to the wrong side of the mesh,
    because OSG UVs already run with the CDN texel order.
    """
    src = image.convert("RGBA")
    w, h = src.size
    if w < 8 or h < 8:
        return src

    offset = pk_offset(int(pk), w, h)
    src_px = src.load()
    out = Image.new("RGBA", (w, h))
    dst_px = out.load()

    # Shader: fragCoord y=0 at FBO bottom; with uY, lookup uses (h-1-y).
    # Writing PIL row y (top-left) from that lookup matches reading the FBO
    # back into a top-left image (glTF / PNG convention).
    for y in range(h):
        oy = (h - y - 1) if flip_y else y
        for x in range(w):
            n = _apply_offset(w, h, x, oy, offset)
            if n is None:
                dst_px[x, y] = (255, 0, 0, 255)
                continue
            sx, sy = _linear_to_pix(w, h, n)
            if 0 <= sx < w and 0 <= sy < h:
                dst_px[x, y] = src_px[sx, sy]
            else:
                dst_px[x, y] = (255, 0, 0, 255)

    if flip_x:
        out = out.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    return out


def unscramble_file(
    path: Path | str,
    pk: int,
    dest: Path | str | None = None,
    *,
    flip_y: bool = False,
    flip_x: bool = False,
) -> Path:
    path = Path(path)
    img = Image.open(path)
    out = unscramble_image(img, pk, flip_y=flip_y, flip_x=flip_x)
    dest_path = Path(dest) if dest else path.with_name(path.stem + "_decoded" + path.suffix)
    save_image(out, dest_path)
    return dest_path


def save_image(image: Image.Image, dest: Path) -> None:
    """Preserve JPEG/PNG sensibly."""
    if dest.suffix.lower() in {".jpg", ".jpeg"}:
        image.convert("RGB").save(dest, quality=95)
    else:
        image.save(dest)
