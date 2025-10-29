## Neo Yakuza Shader changes and notes
 - Most shaders are accounted for, and can handle both Dragon Engine and Old Engine shaders.
 - Shaders with reflection cubemaps are not supported simply because cubemap textures aren't supported in Blender yet.

## TO-DO LIST:
- find way to upgrade existing blend files?

# V2.0 changelog
- Added asset shader support!
    - Should support MOST shaders, both OE and DE!

- Changed Neo Yakuza Shader to v2.0
    - Completely remade from scratch, should be easier to read...
    - Shader is separated by engine now!
    - GMDMaterial data now has its own nodegroup and the JSON data has been deprecated
    - Added completely cosmetic controls to adjust SSS strength and specular strength (for DE)
    - Added partial hair shader support
    - Added specular tinting for Kenzan-Y4
    - Added separate version made for assets
    - Added Asset UVs node
    
