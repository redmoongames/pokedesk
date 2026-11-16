# Third-party components and resource boundaries

Apache 2.0 applies to original PokéDesk code, not to every file in an existing
private installation. Existing third-party notices must be preserved. The clean
source export contains the application and native adapter sources, plus the
license texts listed below; it does not redistribute the referenced binaries,
ROMs, symbol packs, game data, sprites or Python runtime.

| Component in the private installation | Provenance | License / distribution status |
| --- | --- | --- |
| mGBA | commit `7a12d6d4b9acb14c0ae62c9166b6a2f3d08007f6`, https://github.com/mgba-emu/mgba | MPL 2.0, preserved in `licenses/mgba-MPL-2.0.txt`; binaries and corresponding source archive are excluded from this source export |
| Symbol references from pokebot-gen3 | https://github.com/40Cakes/pokebot-gen3 | GPL 3.0 text preserved in `licenses/pokebot-GPL-3.0.txt`; symbol files are excluded, not relicensed as Apache |
| PokéAPI reference material | https://github.com/PokeAPI/pokeapi | Existing notice preserved in `licenses/pokeapi.txt`; datasets are excluded pending resource-pack review |
| Pokémon sprites | https://github.com/PokeAPI/sprites | Excluded; upstream hosting is not a blanket license for underlying game artwork |
| ROM-derived tables, game headers and prepared states | Local ROMs / pret references | Excluded; no distribution clearance is asserted |
| Python, Tcl/Tk and binary runtime dependencies | Existing bundled runtime | Excluded; a future binary release must ship its dependency notices and source obligations |

`native/build.py` currently builds the adapter against a previously prepared
`native/mgba_libretro.dylib`. It does **not** provide a full source-only build of
the mGBA core or the Python runtime. The local mGBA source archive and its patches
remain available in the private installation. A public playable release needs a
complete dependency build recipe, ABI/version checks and resource provenance
review before it is advertised as reproducible.

Game ROMs and playthroughs must be supplied and managed locally. No permission to
redistribute game content or trademarks is granted by the Apache license.

The three PNG files under docs/screenshots show actual interface windows from a
disposable demo profile. They are documentation images, not a sprite/resource
pack. Game artwork visible in them remains the property of its respective
rights holders and is outside the Apache license for original application code.
