"""Column-major 4x4 matrix math shared by the OSGJS decoder and the GLB tools."""

from __future__ import annotations

IDENTITY_MAT = [
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
]

# Sketchfab OSGJS is Z-up (+Y forward); glTF is Y-up (+Z forward).
# Maps (x, y, z)_osg → (x, z, -y)_gltf.
Z_UP_TO_Y_UP = [
    1.0, 0.0, 0.0, 0.0,
    0.0, 0.0, -1.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
]


def mat4_multiply(a: list[float], b: list[float]) -> list[float]:
    """Column-major 4x4 multiply: out = a * b."""
    out = [0.0] * 16
    for col in range(4):
        for row in range(4):
            out[col * 4 + row] = (
                a[0 * 4 + row] * b[col * 4 + 0]
                + a[1 * 4 + row] * b[col * 4 + 1]
                + a[2 * 4 + row] * b[col * 4 + 2]
                + a[3 * 4 + row] * b[col * 4 + 3]
            )
    return out


def mat4_from_translation(t: list[float]) -> list[float]:
    m = IDENTITY_MAT[:]
    m[12], m[13], m[14] = float(t[0]), float(t[1]), float(t[2])
    return m


def mat4_from_scale(s: list[float]) -> list[float]:
    return [
        float(s[0]), 0.0, 0.0, 0.0,
        0.0, float(s[1]), 0.0, 0.0,
        0.0, 0.0, float(s[2]), 0.0,
        0.0, 0.0, 0.0, 1.0,
    ]


def mat4_from_quat(q: list[float]) -> list[float]:
    """Quaternion [x,y,z,w] → column-major rotation matrix."""
    x, y, z, w = (float(v) for v in q)
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    return [
        1 - 2 * (yy + zz), 2 * (xy + wz), 2 * (xz - wy), 0.0,
        2 * (xy - wz), 1 - 2 * (xx + zz), 2 * (yz + wx), 0.0,
        2 * (xz + wy), 2 * (yz - wx), 1 - 2 * (xx + yy), 0.0,
        0.0, 0.0, 0.0, 1.0,
    ]


def mat4_is_degenerate(m: list[float]) -> bool:
    # Zero 3x3 (common when Matrix is a stale animation target)
    return all(abs(m[i]) < 1e-12 for i in range(12))


def transform_point(
    m: list[float], p: tuple[float, float, float]
) -> tuple[float, float, float]:
    x, y, z = p
    return (
        m[0] * x + m[4] * y + m[8] * z + m[12],
        m[1] * x + m[5] * y + m[9] * z + m[13],
        m[2] * x + m[6] * y + m[10] * z + m[14],
    )
