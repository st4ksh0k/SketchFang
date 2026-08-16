"""
Material resolution, in three stages:

    SketchfabMaterial   server channels, exactly as `/options` describes them
    PbrMaterial         projected onto glTF 2.0 metallic-roughness
    ResolvedMaterial    joined to a StateSet, textures baked, ready for GLB

``stateset`` owns the OSGJS side of the join, ``bake`` owns every Pillow write,
``resolve`` owns the orchestration.
"""

from .resolve import ResolvedMaterial, prepare_materials, resolve_material
from .stateset import GeometryBinding, MaterialDef, StateSetBinder

__all__ = [
    "GeometryBinding",
    "MaterialDef",
    "ResolvedMaterial",
    "StateSetBinder",
    "prepare_materials",
    "resolve_material",
]
