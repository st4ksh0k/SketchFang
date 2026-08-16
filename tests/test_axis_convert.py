"""Sketchfab Z-up → glTF Y-up root transform."""

from __future__ import annotations

from sketchfang.api.options import orientation_matrix
from sketchfang.gltf.writer import root_axis_matrix
from sketchfang.util.matrix import IDENTITY_MAT, Z_UP_TO_Y_UP, transform_point


def test_z_up_to_y_up_swizzles_basis_vectors():
    assert transform_point(Z_UP_TO_Y_UP, (1.0, 0.0, 0.0)) == (1.0, 0.0, 0.0)
    assert transform_point(Z_UP_TO_Y_UP, (0.0, 1.0, 0.0)) == (0.0, 0.0, -1.0)
    assert transform_point(Z_UP_TO_Y_UP, (0.0, 0.0, 1.0)) == (0.0, 1.0, 0.0)


def test_orientation_matrix_defaults_to_identity():
    assert orientation_matrix(None) == IDENTITY_MAT
    assert orientation_matrix({}) == IDENTITY_MAT
    assert orientation_matrix({"orientation": {"matrix": list(range(16))}}) == [
        float(i) for i in range(16)
    ]


def test_root_axis_matrix_applies_orientation_before_axis_swap():
    # 90° around Z in OSG space: (x,y,z) → (-y, x, z)
    rot_z = [
        0.0, 1.0, 0.0, 0.0,
        -1.0, 0.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    ]
    root = root_axis_matrix(rot_z)
    # OSG +X → after rot_z becomes +Y → after Z→Y becomes (0,0,-1)
    assert transform_point(root, (1.0, 0.0, 0.0)) == (0.0, 0.0, -1.0)
    # OSG +Z (up) stays up in glTF
    assert transform_point(root, (0.0, 0.0, 1.0)) == (0.0, 1.0, 0.0)
