## Neo Yakuza Shader changes and notes

 - Most (character) shaders are accounted for, and can handle both Dragon Engine and Old Engine shaders.
 - Shaders with reflection cubemaps are not supported simply because cubemap textures aren't supported in Blender yet.

## TO-DO LIST:
- find way to upgrade existing blend files?

# V2.0 changelog
- Added asset shader support!
    - Should support MOST shaders, both OE and DE!
    - Known unsupported shaders include any shader that just has an "x" in it, and emissive shaders

- Changed Neo Yakuza Shader to v2.0
    - Completely remade from scratch, should be easier to read...
    - GMDMaterial data JSON and origin data type was migrated to the nodegroup
    - Added completely cosmetic controls to adjust SSS strength and specular strength (for DE)
    - Added partial hair shader support
    - Added specular tinting for Kenzan-Y4
    - Added separate version made for assets
    - Added Asset UVs node
