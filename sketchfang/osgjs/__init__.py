"""
OSGJS scene decoding: buffers, compression codecs, transforms, scene walk.

Pure decode — no HTTP, no image handling, no material knowledge. The scene walk
takes a binder (see ``materials.stateset.StateSetBinder``) so material joining
stays out of this layer.
"""

from .geometry import decode_geometry
from .walk import walk_geometries

__all__ = ["decode_geometry", "walk_geometries"]
