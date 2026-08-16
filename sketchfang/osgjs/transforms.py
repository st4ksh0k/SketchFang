"""OSGJS transform nodes → world matrices (generic 4x4 math lives in util.matrix)."""

from __future__ import annotations

from ..util.matrix import (
    IDENTITY_MAT,
    mat4_from_quat,
    mat4_from_scale,
    mat4_from_translation,
    mat4_is_degenerate,
    mat4_multiply,
)

__all__ = [
    "IDENTITY_MAT",
    "mat4_is_degenerate",
    "mat4_multiply",
    "matrix_from_transform",
    "stacked_scale_is_zero",
    "stacked_to_matrix",
]


def stacked_scale_is_zero(stacked: list) -> bool:
    for item in stacked or []:
        if isinstance(item, dict) and "osgAnimation.StackedScale" in item:
            scale = item["osgAnimation.StackedScale"].get("Scale") or []
            if scale and all(abs(float(v)) < 1e-12 for v in scale):
                return True
    return False


def stacked_to_matrix(stacked: list) -> list[float]:
    """
    Compose osgAnimation StackedTransforms into a matrix.

    Order matches OSG stacked update: translate, rotate, scale applied as
    T * R * S (column-major, local→parent).
    """
    T = IDENTITY_MAT[:]
    R = IDENTITY_MAT[:]
    S = IDENTITY_MAT[:]
    for item in stacked or []:
        if not isinstance(item, dict):
            continue
        if "osgAnimation.StackedTranslate" in item:
            T = mat4_from_translation(item["osgAnimation.StackedTranslate"]["Translate"])
        elif "osgAnimation.StackedQuaternion" in item:
            R = mat4_from_quat(item["osgAnimation.StackedQuaternion"]["Quaternion"])
        elif "osgAnimation.StackedScale" in item:
            S = mat4_from_scale(item["osgAnimation.StackedScale"]["Scale"])
    return mat4_multiply(T, mat4_multiply(R, S))


def matrix_from_transform(mt: dict) -> list[float] | None:
    """
    Return local matrix, or None if this transform hides the subtree
    (animated rest scale of zero).
    """
    for cb in mt.get("UpdateCallbacks") or []:
        if isinstance(cb, dict) and "osgAnimation.UpdateMatrixTransform" in cb:
            stacked = cb["osgAnimation.UpdateMatrixTransform"].get("StackedTransforms")
            if stacked_scale_is_zero(stacked):
                return None  # hidden at rest — skip for static GLB
            if mat4_is_degenerate(
                [float(x) for x in (mt.get("Matrix") or IDENTITY_MAT)]
                if isinstance(mt.get("Matrix"), list)
                else IDENTITY_MAT
            ):
                return stacked_to_matrix(stacked)

    raw = mt.get("Matrix")
    if isinstance(raw, list) and len(raw) == 16:
        return [float(x) for x in raw]
    return IDENTITY_MAT[:]
