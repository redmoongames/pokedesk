# Distribution notices and resource boundaries

Apache 2.0 covers original PokéDesk code. It does not relicense third-party
components, game data, artwork or trademarks. The source repository and Mac
application contain no Pokémon cartridge, prepared state or personal save.

| Component | Provenance and license |
| --- | --- |
| mGBA core | Official Libretro arm64 core, mGBA commit `7a12d6d4b9acb14c0ae62c9166b6a2f3d08007f6`; MPL 2.0, text in `licenses/mgba-MPL-2.0.txt` |
| Native lockstep adapter | Original bridge plus the mGBA lockstep implementation compiled with two documented patches in `native/build.py`; mGBA-covered files retain MPL 2.0 |
| Symbol-reference seed | Modified symbol records from 40Cakes/pokebot-gen3 commit `4bcbfa7c4018518cd4f9cb5d6c8e67691844caf2`; GPL 3.0, text in `licenses/pokebot-GPL-3.0.txt` |
| PokéAPI references | Move identifiers/slugs and research provenance from `8a92bfa7dab2f12b84b5d151562f9857c133ff30`; upstream notice in `licenses/pokeapi.txt` |
| Python and Tcl/Tk | CPython 3.12.16, python-build-standalone 20261026; runtime and dependency license texts plus `PYTHON.json` ship in the app's `Contents/Resources/licenses/` |
| Setup/navigation metadata | Functional identifiers, factual event anchors, directed links and authored policies; provenance in `src/pokemon_red/release_data/PROVENANCE.txt` |
| Local game content | Catalog tables, encounter slots, trainer names/parties and sprites are extracted on the user's Mac from their verified ROM; they are not application build inputs |

The release provides the corresponding mGBA source archive and the complete
PokéDesk source containing adapter patches. Prebuilt cinema/test cartridges and
captures are omitted from that source archive; the core source is retained.
Third-party mGBA dependency notices are included in the app/dependency archive.
The core's pinned prebuilt ABI is checked; an arbitrary installed mGBA executable
is not treated as an interchangeable dependency.

The GPL symbol seed is provided as readable source, separately attributed, with
its license. It is not relabeled as original Apache code. See the provenance file
for its upstream URL, hash and the formatting/local-label changes.

No externally downloaded sprite pack, game dialogue, event bytecode, map graphics,
block layouts, ROM-derived catalog pack or donor save is bundled. The source seed
contains declarative functional/factual metadata and authored explanations. This
notice grants no rights to redistribute generated game content or trademarks.

The four PNG files under `docs/screenshots/` document real disposable game/UI
sessions. They are a narrow documentation-image exception to source export rules,
not a game resource pack. Game artwork visible in them belongs to its respective
rights holders and is outside the license for original PokéDesk code.

PokéDesk is independent and unaffiliated with Nintendo, Game Freak or The Pokémon
Company. Pokémon names and trademarks remain those of their respective owners.
