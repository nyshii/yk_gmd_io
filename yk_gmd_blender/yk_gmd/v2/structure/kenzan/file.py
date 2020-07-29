from dataclasses import dataclass
from typing import List, Tuple, Union, Type

import mathutils

from yk_gmd_blender.structurelib.base import BaseUnpacker
from yk_gmd_blender.structurelib.primitives import c_uint16
from yk_gmd_blender.yk_gmd.v2.structure.common.attribute import AttributeStruct_Unpack, AttributeStruct
from yk_gmd_blender.yk_gmd.v2.structure.common.matrix import MatrixUnpacker
from yk_gmd_blender.yk_gmd.v2.structure.common.unks import Unk12Struct, Unk14Struct, Unk14Struct_Unpack, Unk12Struct_Unpack
from yk_gmd_blender.yk_gmd.v2.structure.kenzan.bbox import BoundsDataStruct_Kenzan
from yk_gmd_blender.yk_gmd.v2.structure.common.checksum_str import ChecksumStrStruct_Unpack, ChecksumStrStruct
from yk_gmd_blender.yk_gmd.v2.structure.common.file import FileData_Common, FilePacker
from yk_gmd_blender.yk_gmd.v2.structure.common.node import NodeStruct_Unpack, NodeStruct
from yk_gmd_blender.yk_gmd.v2.structure.kenzan.mesh import MeshStruct_Kenzan_Unpack, MeshStruct_Kenzan
from yk_gmd_blender.yk_gmd.v2.structure.kenzan.object import ObjectStruct_Kenzan_Unpack, ObjectStruct_Kenzan
from yk_gmd_blender.yk_gmd.v2.structure.kenzan.header import GMDHeader_Kenzan_Unpack
from yk_gmd_blender.yk_gmd.v2.structure.kenzan.material import MaterialStruct_Kenzan_Unpack, MaterialStruct_Kenzan
from yk_gmd_blender.yk_gmd.v2.structure.kenzan.vertex_buffer_layout import VertexBufferLayoutStruct_Kenzan_Unpack, VertexBufferLayoutStruct_Kenzan


@dataclass(repr=False)
class FileData_Kenzan(FileData_Common):
    overall_bounds: BoundsDataStruct_Kenzan

    node_arr: List[NodeStruct]
    obj_arr: List[ObjectStruct_Kenzan]
    mesh_arr: List[MeshStruct_Kenzan]
    attribute_arr: List[AttributeStruct]
    material_arr: List[MaterialStruct_Kenzan]
    matrix_arr: List[mathutils.Matrix]
    vertex_buffer_arr: List[VertexBufferLayoutStruct_Kenzan]
    vertex_data: bytes  # byte data
    texture_arr: List[ChecksumStrStruct]
    shader_arr: List[ChecksumStrStruct]
    node_name_arr: List[ChecksumStrStruct]
    index_data: List[int]
    meshset_data: bytes
    mesh_matrix_bytestrings: bytes

    unk12: List[Unk12Struct]
    unk13: List[int]  # Is sequence 00, 7C, 7D, 7E... 92 in Kiwami bob
    # # 0x7C = 124
    # # 0x92 = 146 => this is likely a bone address
    # # 24 elements in total
    unk14: List[Unk14Struct]
    flags: List[int]

    @classmethod
    def header_pointer_fields(cls) -> List[Tuple[str, Union[BaseUnpacker, Type[bytes]]]]:
        return FileData_Common.header_pointer_fields() + [
            ("node_arr", NodeStruct_Unpack),
            ("obj_arr", ObjectStruct_Kenzan_Unpack),
            ("mesh_arr", MeshStruct_Kenzan_Unpack),
            ("attribute_arr", AttributeStruct_Unpack),
            ("material_arr", MaterialStruct_Kenzan_Unpack),
            ("matrix_arr", MatrixUnpacker),
            ("vertex_buffer_arr", VertexBufferLayoutStruct_Kenzan_Unpack),
            ("vertex_data", bytes),
            ("texture_arr", ChecksumStrStruct_Unpack),
            ("shader_arr", ChecksumStrStruct_Unpack),
            ("node_name_arr", ChecksumStrStruct_Unpack),
            ("index_data", c_uint16),
            ("meshset_data", bytes),
            ("mesh_matrix_bytestrings", bytes),
            ("unk12", Unk12Struct_Unpack),
            ("unk13", c_uint16),
            ("unk14", Unk14Struct_Unpack),
        ]

    @classmethod
    def header_fields_to_copy(cls) -> List[str]:
        return FileData_Common.header_fields_to_copy() + [
            "overall_bounds",
            "flags"
        ]

FilePacker_Kenzan = FilePacker(
    FileData_Kenzan,
    GMDHeader_Kenzan_Unpack
)