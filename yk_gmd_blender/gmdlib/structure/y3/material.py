from dataclasses import dataclass
from typing import List

from ..common.material_base import MaterialBaseStruct
from ....structurelib.base import StructureUnpacker, FixedSizeArrayUnpacker
from ....structurelib.primitives import *


@dataclass(frozen=False)
class MaterialStruct_Y3(MaterialBaseStruct):
    diffuse: List[int]
    opacity: float
    specular: List[int]
    ambient: List[int]
    emissive: float

    power: float
    intensity: float

    padding: int = 0


# These are best guesses, we don't have a textdump of this like we do for Kenzan
MaterialStruct_Y3_Unpack = StructureUnpacker(
    MaterialStruct_Y3,
    fields=[
        ("power", c_float16),
        ("intensity", c_float16),

        ("specular", FixedSizeArrayUnpacker(c_uint8, 3)),
        ("padding", c_uint8),

        ("diffuse", FixedSizeArrayUnpacker(c_uint8, 3)),
        ("opacity", c_unorm8),
        
        ("ambient", FixedSizeArrayUnpacker(c_uint8, 3)),
        ("emissive", c_unorm8)
    ]
)
