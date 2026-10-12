# Bundled retro shader

`5XBR_NoBlend.fx` is spiderh's 2018 ReShade port of Hyllian/Jararaca's
5xBR v4.0 (level 3), based on Libretro's `5xbr-v4.0-noblend.cg`.

- Author's presentation: https://reshade.me/forum/shader-presentation/4409-5xbr-filter
- Original download: https://www.mediafire.com/file/sc9zt5vs6bg53vj/5XBR_NoBlend.fx/file
- License: GPL-2.0-or-later. Original source notices are retained; a copy of GPL v2 is in `LICENSE`.
- The source is bundled because the author distributes it as an individual file rather than a shader repository.
- It is copied unchanged into the game's private ReShade shader set when the Retro model is selected. It is not enabled automatically.
- Technique name: `xBR5x_NoBlend`; initial `Strength`: 1.5.

The other retro additions are downloaded on demand from the pinned sources in
`../reshade-extra-shaders.json`. No GShade runtime is installed.
