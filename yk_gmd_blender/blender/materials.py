import json
import os
import re
from pathlib import Path
from typing import Optional, Tuple, cast
from collections import defaultdict

import bpy
from bpy.props import FloatVectorProperty, StringProperty, BoolProperty, IntProperty
from bpy.types import NodeSocket, NodeSocketColor, ShaderNodeTexImage, \
    PropertyGroup
from .common import AttribSetLayerNames
from .error_reporter import BlenderErrorReporter
from ..gmdlib.structure.version import GMDVersion
from ..gmdlib.abstract.gmd_attributes import GMDAttributeSet
from ..gmdlib.abstract.gmd_shader import GMDVertexBufferLayout
from ..gmdlib.errors.error_reporter import StrictErrorReporter, ErrorReporter


class YakuzaPropertyGroup(PropertyGroup):
    """
    PropertyGroup holding all of the Yakuza data for an attribute set that can't be easily changed by the user
    or stored in the Yakuza Shader node.

    This includes a lot of data arrays, like unk12 or unk14, and also includes various flags that we can't work out
    ourselves right now.
    """

    # Has this PropertyGroup been initialized from a GMD file?
    # Used to hide data for normal Blender materials
    inited: BoolProperty(name="Initialized", default=False)  # type: ignore

    # Version of the nodegroup the material was loaded in
    nodegroup_version: IntProperty(name='Shader Nodegroup Version') # type: ignore
    asset_nodegroup_version: IntProperty(name='Asset Shader Nodegroup Version') # type: ignore

    shader_name: StringProperty(name="Shader Name")  # type: ignore
    # These flags are stored as a hex-string encoding a 64-bit unsigned number.
    # It can't be stored as an int because blender uses primitive C types and would try to store it in 32 bits.
    shader_vertex_layout_flags: StringProperty(name="Vertex Layout Flags")  # type: ignore
    assume_skinned: BoolProperty(name="Assumes Skinned Context",  # type: ignore
                                 description="Was imported from a skinned mesh and requires bone-weight pairs")
    cached_expected_uv_layers: StringProperty(name="Uses UV Layers", set=None)  # type: ignore
    cached_expected_color_layers: StringProperty(name="Uses Vertex Color Layers", set=None)  # type: ignore

    attribute_set_flags: StringProperty(name="Attribute Layout Flags")  # type: ignore

    unk12: FloatVectorProperty(name="GMD Unk12 Data", size=32)  # type: ignore
    unk14: FloatVectorProperty(name="GMD Unk14 Data", size=32)  # type: ignore
    attribute_set_floats: FloatVectorProperty(name="GMD Attribute Set Floats", size=16)  # type: ignore
    material_origin_type: IntProperty(name="GMDMaterial origin type")  # type: ignore


class YakuzaPropertyPanel(bpy.types.Panel):
    """
    Panel that displays the YakuzaPropertyGroup attached to the selected material.
    """

    bl_label = "Yakuza Properties"

    bl_order = 1  # Make it appear near the top

    bl_space_type = "PROPERTIES"
    bl_context = "material"
    bl_region_type = "WINDOW"

    def draw(self, context):
        ob = context.object
        if not ob:
            return
        ma = ob.active_material
        if not ma:
            return

        def matrix_prop(prop_name, length: int, text=""):
            self.layout.label(text=text)
            box = self.layout.box().grid_flow(row_major=True, columns=4, even_rows=True, even_columns=True)
            for i in range(length // 4):
                for j in range(i * 4, (i + 1) * 4):
                    box.prop(ma.yakuza_data, prop_name, index=j, text="")

        if ma.yakuza_data.inited:
            self.layout.prop(ma.yakuza_data, "shader_name")

            vertex_layout_box = self.layout.box()
            vertex_layout_box.prop(ma.yakuza_data, "shader_vertex_layout_flags")
            vertex_layout_box.prop(ma.yakuza_data, "assume_skinned")
            vertex_layout_box.prop(ma.yakuza_data, "cached_expected_uv_layers")
            vertex_layout_box.prop(ma.yakuza_data, "cached_expected_color_layers")
            vertex_layout_box.operator("material.yakuza_update_expected_layers")

            self.layout.prop(ma.yakuza_data, "attribute_set_flags")

            matrix_prop("attribute_set_floats", 16, text="Attribute Set Floats")
            matrix_prop("unk12", 32, text="Unk 12")
            matrix_prop("unk14", 32, text="Unk 14 (Should be ints)")
        else:
            self.layout.label(text=f"No Yakuza Data present for this material")


class MATERIAL_OT_yakuza_update_expected_layers(bpy.types.Operator):
    """Re-check the expected color and UV layers based on the vertex layout flags"""
    bl_idname = "material.yakuza_update_expected_layers"
    bl_label = "Re-check expected layers for Yakuza material"

    @classmethod
    def poll(cls, context):
        ob = context.object
        return ob is not None and ob.active_material is not None and ob.active_material.yakuza_data.inited

    def execute(self, context):
        ob = context.object
        if not ob:
            return
        ma = ob.active_material
        if not ma or not ma.yakuza_data.inited:
            return

        error = BlenderErrorReporter(self.report, StrictErrorReporter({"ALL"}))

        try:
            vertex_layout_flags = int(ma.yakuza_data.shader_vertex_layout_flags, base=16)
        except ValueError as ex:
            error.fatal_exception(ex)

        vertex_layout = GMDVertexBufferLayout.build_vertex_buffer_layout_from_flags(vertex_layout_flags,
                                                                                    ma.yakuza_data.assume_skinned,
                                                                                    error)

        layer_names = AttribSetLayerNames.build_from(vertex_layout, ma.yakuza_data.assume_skinned)

        expected_uv_layers = ", ".join(layer_names.get_blender_uv_layers())
        expected_color_layers = ", ".join(layer_names.get_blender_color_layers())

        ma.yakuza_data.cached_expected_uv_layers = expected_uv_layers
        ma.yakuza_data.cached_expected_color_layers = expected_color_layers

        return {'FINISHED'}


# Custom property group for textures imported from GMD files.
# Allows for "Yakuza relinking": updating the file associated with an image based on the texture name,
# potentially using a different file format.
class YakuzaTexturePropertyGroup(PropertyGroup):
    # Has this PropertyGroup been initialized from a GMD file?
    inited: BoolProperty(name="Initialized", default=False)  # type: ignore

    # Name of the texture from the GMD file
    yk_name: StringProperty(name="Texture Name (from GMD)")  # type: ignore


# Inspired by XNALara importer code - https://github.com/johnzero7/XNALaraMesh/blob/eaccfddf39aef8d3cb60a50c05f2585398fe26ca/material_creator.py#L527
YAKUZA_SHADER_NODE_GROUPS = {
    "OLD_SKINNED_SHADER" : "Neo Yakuza Shader - OE",
    "DRAGON_SKINNED_SHADER" : "Neo Yakuza Shader - DE",
    "OLD_UNSKINNED_SHADER" : "Neo Yakuza Shader (Asset) - OE",
    "DRAGON_UNSKINNED_SHADER" : "Neo Yakuza Shader (Asset) - DE",
}
YAKUZA_SHADER_NODE_GROUP_VERSION = 2 # Futureproofing for whenever the shader is updated
YAKUZA_ASSET_SHADER_NODE_GROUP_VERSION = 1
YAKUZA_GMDMATERIAL_NODEGROUP = 'GMDMaterial data'
YAKUZA_UV_SCALER = "UV scaler"
YAKUZA_ASSET_UVS = "Asset UVs"
PATTERN_SHADERS = ["[rd]", "[rt]", "[rs]", "_m2"]

DEFAULT_DIFFUSE_COLOR = (1, 1, 1, 1)
DEFAULT_UNUSED_COLOR = (0, 0, 0, 1)
DEFAULT_NORMAL_COLOR = (0.5, 0.5, 1, 1)
DEFAULT_MULTI_COLOR = (0, 1, 0, 1)
DEFAULT_Z_COLOR = (0.5, 1, 0.5, 1)

def create_proxy_texture(name: str, filename: str, color: Tuple[float, float, float, float]) -> bpy.types.Image:
    """
    Create an Image with a given name and filename, which is of a given color.
    Returns an 128x128 image.
    :param name: The name of the new image.
    :param filename: The filepath to be associated with the new image.
    :param color: The color to fill the image with.
    :return: A 128x128 Image of the given color, with the given filepath and name.
    """

    # Create an image where the Blender name = the file name i.e. the name + extension.
    image = bpy.data.images.new(filename, 128, 128, alpha=True)

    # set all imported textures to non-color, this makes making shaders easier so you dont have to set every non-di
    # texture to noncolor. _di textures are simply just multiplied by themselves - this is how the ingame shaders do it
    image.colorspace_settings.name = "Non-Color"

    # Set up the Yakuza Data for this texture to contain the GMD name i.e. the name without an extension.
    image.yakuza_data.inited = True
    image.yakuza_data.yk_name = name

    # Using a GENERATED image means Blender won't try to save it out to a file when you exit
    image.source = 'GENERATED'
    image.generated_type = 'BLANK'
    image.generated_color = color
    image.generated_width = 128
    image.generated_height = 128

    return image


def load_texture_from_name(node_tree: bpy.types.NodeTree, gmd_folder: str, tex_name: str,
                           color_if_not_found=(1, 0, 1, 1)) -> ShaderNodeTexImage:
    """
    Given a GMD texture name, find or create the Blender counterpart and add a texture node to the given material tree
    using that texture.
    It will try to load the image from the gmd_folder if possible, but if it's not there then a dummy image
    will be created filled with a specific color.
    Yakuza dummy textures "dummy_{black,white,multi,nmap}" will be created with the correct colors,
    and won't be searched for in the gmd_folder.
    :param node_tree: The node tree to add the texture node to.
    :param gmd_folder: The folder to search for as-yet-not-found textures.
    :param tex_name: The name of the texture.
    :param color_if_not_found: The color to fill the dummy image with, if an actual texture cannot be found.
    :return: A Texture node containing an image relevant to the name tex_name.
    """

    # Always create the image node
    image_node = node_tree.nodes.new('ShaderNodeTexImage')

    # use the texture basename i.e. "c_am_kiryu_suit_di.dds" with the dds extension always.
    # bpy.data.images.load() uses this convension, so when we look up images in bpy.data.images we have to match.
    tex_filepath_basename = f"{tex_name}.dds"
    if tex_filepath_basename in bpy.data.images:
        # The texture already exists, just use that one
        image_node.image = bpy.data.images[tex_filepath_basename]
    elif tex_name == "dummy_black":
        image_node.image = create_proxy_texture(tex_name, tex_filepath_basename, (0, 0, 0, 1))
    elif tex_name == "dummy_white":
        image_node.image = create_proxy_texture(tex_name, tex_filepath_basename, (1, 1, 1, 1))
    elif tex_name == "default_z":
        image_node.image = create_proxy_texture(tex_name, tex_filepath_basename, DEFAULT_Z_COLOR)
    elif tex_name == "dummy_multi":
        image_node.image = create_proxy_texture(tex_name, tex_filepath_basename, DEFAULT_MULTI_COLOR)
    elif tex_name == "dummy_nmap":
        image_node.image = create_proxy_texture(tex_name, tex_filepath_basename, DEFAULT_NORMAL_COLOR)
    else:
        # The texture doesn't already exist, and isn't a dummy texture we can create ourselves.
        # Try to find it in the gmd_folder.
        tex_filepath = os.path.join(gmd_folder, tex_filepath_basename)
        if not os.path.isfile(tex_filepath):
            # The texture doesn't exist.
            image_node.image = create_proxy_texture(tex_name, tex_filepath_basename, color_if_not_found)
        else:
            # The texture does exist, load it!
            image = bpy.data.images.load(tex_filepath, check_existing=True)
            image.colorspace_settings.name = "Non-Color"
            image.yakuza_data.inited = True
            image.yakuza_data.yk_name = tex_name
            image_node.image = image

    return cast(ShaderNodeTexImage, image_node)

   # Function to analyze the shader name
   # This is to guess what type of shader it is. It should be right most of the time until they
   # decide to change up their shader naming convention.
def decode_shader_name(shader_name):
    token_split_re = re.compile(r'(?=(?:_[a-zA-Z0-9(])|(?:[0-9]))(?![^\[\(]*[\]\)])')
    tag_re = re.compile(r'\[[^\[\]]+\]?')
    mix_token_re = re.compile(r'^(_[A-Za-z0-9]+)(\([^\)]*\))?$')

    print(shader_name)
    decoded_shader = {}

    shader_textures_dict = {
        "d": "diffuse",
        "m": "diffuse_opaque",
        "x": "diffuse",
        "s": "specular",
        "z": "multi",
        "u": "multi_asset",
        "t": "normal",
        "i": "emit",
        "h": "hair",
    }

    shader_mix_dict = {
        "_a": "add",
        "_b": "blend",
        "_m": "multiply",
        "_sss": "sss",
    }

    transparent_shader_dict = {
        "o": "opaque",
        "b": "blend",
        "c": "dither",
        "d": "blend",
        "p": "dither",
        "a": "blend",
    }

    shader_prefixes_dict = {
        "s":"skinned",
        "r":"unskinned",
        "sd":"skinned",
        "rs":"unskinned",
        "ss":"skinned",
        "sw":"skinned",
    }

    # split prefix and remaining name
    prefix, _, rest = shader_name.partition('_')
    decoded_shader['shader_type'] = shader_prefixes_dict.get(prefix, prefix)

    if rest:
        trans_char, rest = rest[0], rest[1:]
        decoded_shader['transparency'] = transparent_shader_dict.get(trans_char, trans_char)
    else:
        decoded_shader['transparency'] = ''

    split_shader_name = [t for t in token_split_re.split(rest) if t]

    tags = []
    pending_mix = ''
    pending_mix_mask = ''
    tex_get = shader_textures_dict.get
    mix_get = shader_mix_dict.get

    textures = {}
    counters = defaultdict(int)   # track index per texture base (diffuse, specular, ...)

    for split in split_shader_name:
        found = tag_re.findall(split)
        if found:
            tags.extend(found)
            split = tag_re.sub('', split)

        if not split:
            continue

        if split[0].isdigit():
            # if 1st character is a digit its a UV, check its textures
            uv = 0
            for ch in split:
                if ch.isdigit():
                    uv = int(ch) - 1
                else:
                    mapped = tex_get(ch, ch)
                    idx = counters[mapped]
                    key_name = f"{mapped}{idx}_uv{uv}"
                    counters[mapped] += 1

                    textures.update({
                        key_name : {
                        "mix": mix_get(pending_mix, pending_mix) if pending_mix else '',
                        "mix_mask": pending_mix_mask if pending_mix_mask else ''
                        }
                    })

            pending_mix = ''
            pending_mix_mask = ''

        elif split[0] == "_":
            # if 1st char is an underscore it's the mixing method 

            # separate base mix like "_b" from optional mask "(vr)"
            m = mix_token_re.match(split)
            if m:
                pending_mix = m.group(1)
                pending_mix_mask = m.group(2) or ''
            else:
                pending_mix = split
                pending_mix_mask = ''

    decoded_shader["tags"] = tags
    decoded_shader['textures'] = textures
    decoded_shader['uvs'] = len(set(x[-1] for x in textures))

    print(decoded_shader)
    return decoded_shader

def set_yakuza_shader_material_from_attributeset(material: bpy.types.Material, yakuza_inputs: bpy.types.NodeInputs,
                                                 gmddata_inputs: bpy.types.NodeInputs, attribute_set: GMDAttributeSet, 
                                                 gmd_folder: str):
    """
    Given a material and an attribute set, attach all of the relevant data from the attribute set to the material.
    :param material: The material to update
    :param yakuza_inputs: The inputs to the Yakuza Shader node in the material
    :param attribute_set: The GMDAttributeSet this Material represents.
    :param gmd_folder: The folder to examine for new textures.
    :return: None
    """

    layer_names = AttribSetLayerNames.build_from(attribute_set.shader.vertex_buffer_layout,
                                                 attribute_set.shader.assume_skinned)

    # Setup the yakuza_data inside the material
    material.yakuza_data.inited = True
    material.yakuza_data.nodegroup_version = YAKUZA_SHADER_NODE_GROUP_VERSION
    material.yakuza_data.asset_nodegroup_version = YAKUZA_ASSET_SHADER_NODE_GROUP_VERSION
    material.yakuza_data.shader_name = attribute_set.shader.name
    material.yakuza_data.shader_vertex_layout_flags = f"{attribute_set.shader.vertex_buffer_layout.packing_flags:016x}"
    material.yakuza_data.assume_skinned = attribute_set.shader.assume_skinned
    material.yakuza_data.attribute_set_flags = f"{attribute_set.attr_flags:016x}"
    material.yakuza_data.cached_expected_uv_layers = ", ".join(layer_names.get_blender_uv_layers())
    material.yakuza_data.cached_expected_color_layers = ", ".join(layer_names.get_blender_color_layers())
    material.yakuza_data.unk12 = attribute_set.unk12.float_data if attribute_set.unk12 else [0] * 32
    material.yakuza_data.unk14 = attribute_set.unk14.int_data if attribute_set.unk14 else [0] * 32
    material.yakuza_data.attribute_set_floats = attribute_set.attr_extra_properties
    material.yakuza_data.material_origin_type = attribute_set.material.origin_version.value

    ### Handy functions for setting nodegroup inputs!
    shader_name = attribute_set.shader.name
    decoded_shader_name = decode_shader_name(material.yakuza_data.shader_name)

    def nodegroup_to_input(nodegroup: str):
        match nodegroup:
            case 'gmddata_inputs': return gmddata_inputs
            case _: return yakuza_inputs
    # function to set shader input
    def set_shader_input(input: str, value, ignore_if_doesnt_exist: bool = True, nodegroup = 'yakuza_inputs'):
        try:
           nodegroup_to_input(nodegroup)[input].default_value = value
        except Exception as e:
            if ignore_if_doesnt_exist:
                print(f'WARNING: {e} - Ignored as it is a non-vital input.')
            else:
                raise(e)
    # function to set shader inputs that are vectors
    def set_vector_shader_input(input: str, value: list, ignore_if_doesnt_exist: bool = True, nodegroup = 'yakuza_inputs'):
        try:
                nodegroup_to_input(nodegroup)[input].default_value[0] = value[0]/255
                nodegroup_to_input(nodegroup)[input].default_value[1] = value[1]/255
                nodegroup_to_input(nodegroup)[input].default_value[2] = value[2]/255
        except Exception as e:
            if ignore_if_doesnt_exist:
                print(f'WARNING: {e} - Ignored as it is a non-vital input.')
            else:
                raise(e)
    # function to set boolean shader inputs
    def set_bool_shader_input(input: str, if_condition: bool, ignore_if_doesnt_exist: bool = True, nodegroup = 'yakuza_inputs'):
        if if_condition:
            set_shader_input(input, True if bpy.app.version >= (4, 2, 0) else 1, ignore_if_doesnt_exist, nodegroup)
        else:
            set_shader_input(input, False if bpy.app.version >= (4, 2, 0) else 0, ignore_if_doesnt_exist, nodegroup)
    # COSMETIC VALUE CHECKS
    set_bool_shader_input('[rough]', "[rough]" in decoded_shader_name['tags']) 
    set_bool_shader_input('Is _sp shader', any('specular' in d for d in decoded_shader_name["textures"]))
    set_bool_shader_input('Is opaque shader', decoded_shader_name['transparency'] == 'opaque')
    set_bool_shader_input('Is _m4d shader', '_m4d' in shader_name)
    
    if material.yakuza_data.assume_skinned:
        set_bool_shader_input('Has imperfection', "h2dz" in shader_name)

        if material.yakuza_data.material_origin_type == 4:
            set_bool_shader_input('Is hair shader', "[hair]" in decoded_shader_name['tags'])
        else: 
            set_bool_shader_input('Is hair shader', any(d == 'hair' for d in decoded_shader_name["textures"]))

        set_bool_shader_input('Is skin shader', "[skin]" in decoded_shader_name['tags'])
        set_bool_shader_input('Is OE pattern shader', any([x in shader_name for x in PATTERN_SHADERS]))
        set_bool_shader_input('Is Y3 [rs] shader', "[rd]" not in decoded_shader_name['tags'] \
                              and "[rs]" in decoded_shader_name['tags'])
    else:
    # ASSET COSMETIC CHECKS
        def match_mix_mask_cases(mix: str):
            match mix:
                case "(vr)" : val = 1
                case "(va)" : val = 2
                case "(vr3i)" : val = 3
                case _: val = 1
            return(val)
        def match_mix_cases(mask: str):
            match mask:
                case 'blend': val = 1
                case 'multiply': val = 2
                case 'add': val = 3
                case _: val = 0
            return(val)

        texture_map = {
            'diffuse': 'Diffuse',
            'multi': 'Multi',
            "multi_asset": "Multi",
            'specular': 'Multi',
            'normal': 'Normal',
        }

        if decoded_shader_name['uvs'] > 1:
            for texture in decoded_shader_name['textures']:
                texture_idx = int(texture[-5])
                texture_uv = int(texture[-1])
                texture_type = texture[0:-5]
                
                if decoded_shader_name['textures'][texture]['mix'] == 'multiply' \
                and texture_uv == 3 and texture_type == 'diffuse':
                    yakuza_inputs['Diffuse mix mode'].default_value[2] = 2
                elif texture_idx != 0 and texture_type in texture_map:        
                    texture_input = texture_map[texture_type] 
                    yakuza_inputs[f'{texture_input} mix mode'].default_value[texture_idx - 1] = \
                        match_mix_cases(decoded_shader_name['textures'][texture]['mix'])
                    yakuza_inputs[f'{texture_input} mix mask mode'].default_value[texture_idx - 1] = \
                        match_mix_mask_cases(decoded_shader_name['textures'][texture]['mix_mask'])

        diffuse_alpha_flags = ['1','1','1','1']
        # 0 - doesnt use alpha (diffuse_opaque), # 1 - uses alpha (diffuse), default behavior is 1
        # bit order: diffuse0, diffuse1, diffuse2, diffuse3
        if material.yakuza_data.material_origin_type != 4: #doesnt exist in DE so it should always be 1111
            if any('diffuse_opaque' in d for d in decoded_shader_name['textures']):    
                for texture in decoded_shader_name['textures']:
                    texture_idx = int(texture[-5])  
                    if texture[0:-5] == 'diffuse_opaque':
                        diffuse_alpha_flags[texture_idx] =  '0'
            set_shader_input('Diffuse alpha flags', int(''.join(diffuse_alpha_flags), 2))


    # GMDMaterial data
    set_shader_input('GMDMaterial Origin type', material.yakuza_data.material_origin_type, False)
    set_vector_shader_input('Diffuse color', attribute_set.material.origin_data.diffuse, False, 'gmddata_inputs')
    set_shader_input('Opacity',attribute_set.material.origin_data.opacity, False, 'gmddata_inputs')
    set_vector_shader_input('Specular color', attribute_set.material.origin_data.specular, False, 'gmddata_inputs')
    set_shader_input('Specular power',attribute_set.material.origin_data.power, False, 'gmddata_inputs')
    set_shader_input('Specular intensity',attribute_set.material.origin_data.intensity, False, 'gmddata_inputs')
    set_shader_input('Padding', attribute_set.material.origin_data.padding, False)
    set_vector_shader_input('Ambient (Y3) / Material params', attribute_set.material.origin_data.ambient, False, 'gmddata_inputs')
    set_shader_input('Emissive (Y3) / Unk', attribute_set.material.origin_data.emissive, False, 'gmddata_inputs')

    # Convenience function for creating a texture node for an Optional texture
    def set_texture(set_into: NodeSocketColor, tex_name: Optional[str],
                    next_image_y: int = 0, color_if_not_found=(1, 0, 1, 1)) -> Tuple[Optional[ShaderNodeTexImage], int]:
        if not tex_name:
            return None, next_image_y
        image_node = load_texture_from_name(material.node_tree, gmd_folder, tex_name, color_if_not_found)
        image_node.location = (-500, next_image_y)
        # image_node.label = tex_name
        image_node.hide = True
        material.node_tree.links.new(image_node.outputs["Color"], set_into)
        next_image_y -= 100
        return image_node, next_image_y

    # Create the diffuse texture
    diffuse_tex, next_y = set_texture(yakuza_inputs["texture_diffuse"], attribute_set.texture_diffuse)

    if diffuse_tex:
        # Link the texture alpha with the Yakuza Shader, and make the material do hashed or blended alpha
        # (depending on shader), and set shadow method to none.
            material.node_tree.links.new(diffuse_tex.outputs["Alpha"], yakuza_inputs["Diffuse Alpha"])
            if decoded_shader_name['transparency'] == 'blend':
                material.blend_method = "BLEND"
            else:
                material.blend_method = "HASHED"
            try:
                # Try setting the shadow method directly
                material.shadow_method = "NONE"
            except AttributeError:
                # Handle Blender 4.3+ where shadow_method is removed
                print(f"Warning: shadow_method is not available in Blender {bpy.app.version_string}")

    # Attach the other textures.
    multi_tex, next_y = set_texture(yakuza_inputs["texture_multi"], attribute_set.texture_multi, next_y,
                                    DEFAULT_MULTI_COLOR)
    if multi_tex:
        material.node_tree.links.new(multi_tex.outputs["Alpha"], yakuza_inputs["Multi Alpha"])
    normal_tex, next_y = set_texture(yakuza_inputs["texture_normal"], attribute_set.texture_normal, next_y,
                                     DEFAULT_NORMAL_COLOR)
    if normal_tex:
        material.node_tree.links.new(normal_tex.outputs["Alpha"], yakuza_inputs["Normal Alpha"])
    _, next_y = set_texture(yakuza_inputs["texture_refl"], attribute_set.texture_refl, next_y, DEFAULT_Z_COLOR)
    _, next_y = set_texture(yakuza_inputs["texture_rm"], attribute_set.texture_rm, next_y, DEFAULT_Z_COLOR)
    _, next_y = set_texture(yakuza_inputs["texture_rs"], attribute_set.texture_rs, next_y, DEFAULT_NORMAL_COLOR)
    rt_tex, next_y = set_texture(yakuza_inputs["texture_rt"], attribute_set.texture_rt, next_y, DEFAULT_NORMAL_COLOR)
    if rt_tex:
        material.node_tree.links.new(rt_tex.outputs["Alpha"], yakuza_inputs["RT Alpha"])
    rd_tex, next_y = set_texture(yakuza_inputs["texture_rd"], attribute_set.texture_rd, next_y, DEFAULT_DIFFUSE_COLOR)
    if rd_tex:
        material.node_tree.links.new(rd_tex.outputs["Alpha"], yakuza_inputs["RD Alpha"])


def append_data_from_yakuza_shader(error: ErrorReporter):
    blend_file = 'yakuza_shader_4.2.blend' if bpy.app.version >= (4, 2, 0) else "yakuza_shader.blend"

    file_path = Path(__file__).parent / blend_file
    with bpy.data.libraries.load(str(file_path)) as (data_from, data_to):
        for node_group in YAKUZA_SHADER_NODE_GROUPS:
            if YAKUZA_SHADER_NODE_GROUPS[node_group] not in data_from.node_groups:
                error.fatal(
                    f"Couldn't find the node group '{YAKUZA_SHADER_NODE_GROUPS[node_group]}' in the built-in shader .blend library")
            data_to.node_groups.append(YAKUZA_SHADER_NODE_GROUPS[node_group])

        if YAKUZA_GMDMATERIAL_NODEGROUP not in data_from.node_groups:
            error.fatal(f"Couldn't find the node group '{YAKUZA_GMDMATERIAL_NODEGROUP}' in the built-in shader .blend library")
        if YAKUZA_UV_SCALER not in data_from.node_groups:
            error.fatal(f"Couldn't find the node group '{YAKUZA_UV_SCALER}' in the built-in shader .blend library")
        if YAKUZA_ASSET_UVS not in data_from.node_groups:
            error.fatal(f"Couldn't find the node group '{YAKUZA_ASSET_UVS}' in the built-in shader .blend library")
        data_to.node_groups.append(YAKUZA_GMDMATERIAL_NODEGROUP)
        data_to.node_groups.append(YAKUZA_UV_SCALER)
        data_to.node_groups.append(YAKUZA_ASSET_UVS)

def get_yakuza_shader_node_groups(error: ErrorReporter, attribute_set: GMDAttributeSet):
    """
    Create or retrieve the Yakuza Shader node group, depending on whether it exists.
    :return: The Yakuza Shader node group.
    """
    engine = attribute_set.material.origin_version
    skinned = True if attribute_set.shader.assume_skinned else False
    if skinned and engine == GMDVersion.Dragon:
        YAKUZA_SHADER_NODE_GROUP = YAKUZA_SHADER_NODE_GROUPS['DRAGON_SKINNED_SHADER']
    elif skinned and engine != GMDVersion.Dragon:
        YAKUZA_SHADER_NODE_GROUP = YAKUZA_SHADER_NODE_GROUPS['OLD_SKINNED_SHADER']
    elif not skinned and engine == GMDVersion.Dragon: 
        YAKUZA_SHADER_NODE_GROUP = YAKUZA_SHADER_NODE_GROUPS['DRAGON_UNSKINNED_SHADER']
    elif not skinned and engine != GMDVersion.Dragon: 
        YAKUZA_SHADER_NODE_GROUP = YAKUZA_SHADER_NODE_GROUPS['OLD_UNSKINNED_SHADER']

    if YAKUZA_SHADER_NODE_GROUP in bpy.data.node_groups:
        return bpy.data.node_groups[YAKUZA_SHADER_NODE_GROUP]
    else:
        append_data_from_yakuza_shader(error)
        return bpy.data.node_groups[YAKUZA_SHADER_NODE_GROUP]

def get_gmdmaterial_data_node_group(error: ErrorReporter):
    if YAKUZA_GMDMATERIAL_NODEGROUP in bpy.data.node_groups:
        return bpy.data.node_groups[YAKUZA_GMDMATERIAL_NODEGROUP]
    else:
        append_data_from_yakuza_shader(error)
        return bpy.data.node_groups[YAKUZA_GMDMATERIAL_NODEGROUP]
    
def get_uv_scaler_node_group(error: ErrorReporter):
    if YAKUZA_UV_SCALER in bpy.data.node_groups:
        return bpy.data.node_groups[YAKUZA_UV_SCALER]
    else:
        append_data_from_yakuza_shader(error)
        return bpy.data.node_groups[YAKUZA_UV_SCALER]

def get_asset_uvs_node_group(error: ErrorReporter):
    if YAKUZA_ASSET_UVS in bpy.data.node_groups:
        return bpy.data.node_groups[YAKUZA_ASSET_UVS]
    else:
        append_data_from_yakuza_shader(error)
        return bpy.data.node_groups[YAKUZA_ASSET_UVS]
