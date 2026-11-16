# Source and private installation

There are two distinct inputs:

1. A clean source export for code review, contribution, public contracts and
   Python packaging. It contains no game resources or user data.
2. A private playable installation with a compatible native bridge/core, bundled
   Python/Tk, user-supplied ROMs, reference packs and optional local fixtures.

The existing application supports Apple Silicon macOS. Passing pure contracts
on Linux does not mean the macOS GUI, Cocoa input, audio or native bridge run on
Linux. An editable Python install supplies source code; it does not install the
missing game/runtime/resource packs.

## Source checks

Run `python3 -B tools/public_checks.py`. The command runs the ROM-free public
contracts and verifies a fresh source export in a temporary directory. It never
opens an emulator or reads a save. Public CI additionally builds and inspects a
wheel and sdist from a disposable export copy.

## Private integration checks

The full unittest suite expects native libraries and version-specific vendor
references. `tools/check.py` additionally expects `tests/fixtures/fire_red`, a
matching ROM, a manifest and its deterministic checkpoints. Those files are
intentionally excluded from the public export. This stage does not yet provide
a resource-free fixture generator or a complete clean-machine game bootstrap.

Do not copy a personal profile into public fixtures. Keep native fixtures and
their output in private directories. Use Check.command only from a prepared
private installation and keep output private.

`native/build.py --adapter-only` rebuilds the bridge using the local pinned mGBA
source archive and a pre-existing core dylib. Rebuilding the entire core/runtime
and producing a signed, downloadable app remain later release work. See
THIRD_PARTY_NOTICES.md before distributing any resource pack or binary bundle.

## Packaging without data

README.github.md documents the export/build/verify commands. The export destination
must be new and outside the working installation; no existing directory is
overwritten. The generated SOURCE_EXPORT.json records payload hashes, without
personal absolute paths. Keep that verified export unchanged and build from a
copy. Package metadata is allowed only in narrow generated namespaces; source
payload bytes must match the export.

The exporter is not a publisher and does not create a remote repository, upload
files or delete anything from the working installation. A successful scan is
not a substitute for reviewing the source and resource licensing before release.

## Local reference-pack preparation

Before gameplay on a prepared installation, run:

```sh
python3 -B tools/build_reference.py --project PRIVATE_INSTALL
python3 -B tools/build_reference.py --project PRIVATE_INSTALL --check
```

This explicit maintenance command needs the locally provided vendor inputs. It
compiles one pack per edition, writes only vendor/catalog/packs, and never opens
a ROM, save or journal. Packs remain private resource artifacts and are excluded
from source exports. Runtime reads do not build missing/outdated packs or write
SQLite. Old profile databases are preserved, including legacy reference tables.
Restart the application after updating code or packs.

Profiles and jobs record relative links in .pokedesk-paths.json. Keep the portable
folder tree intact when copying it to another M-series Mac. No absolute home
paths are written into these markers. Legacy roots and existing symlink-based
profiles continue to work without moving their saves. For a separately installed
read-only app, configure a writable library using bind_installation(library,
installation, kind='profile', library=library); all descendants inherit the app
resource root and retain their own Data and Sessions. ROMs remain user-provided
profile/library data. Resources and runtime dependencies are still the private
installation's responsibility, as described above.

## What to obtain separately

For source checks, use Python 3.12 or 3.13 from
https://www.python.org/downloads/macos/ and Git (Apple Command Line Tools), or
download this repository as a ZIP. No ROM or emulator is needed for those checks.

For gameplay, the current private installation additionally needs:

- An English ROM revision listed in src/pokemon_red/editions.py, supplied by the
  player. FireRed's primary path is Data/FireRed.gba (16 MiB, SHA-1
  dd5945db9b930750cb39d00c84da8571feebf417).
- Native arm64 native/mgba_libretro.dylib and native/libpokemon.dylib with the
  compatible mCore ABI. The pinned source is
  https://github.com/mgba-emu/mgba/tree/7a12d6d4b9acb14c0ae62c9166b6a2f3d08007f6 .
  Apple's Command Line Tools are needed for native/build.py. A standalone mGBA
  application download is not a replacement for this prepared ABI/core pair.
- The bundled Python/Tk tree at
  runtime/python/cpython-3.12.16-macos-aarch64-none, including libpython3.12.dylib.
  A system Python installation alone does not satisfy that portable layout.
- Edition symbols and reference/navigation inputs under vendor/reference and
  vendor/catalog, plus explicitly compiled vendor/catalog/packs. Symbols were
  sourced from https://github.com/40Cakes/pokebot-gen3 and reference material from
  https://github.com/PokeAPI/pokeapi and pret projects; see THIRD_PARTY_NOTICES.md.
  The complete prepared pack and its clean-machine generator are not public yet.
- Optional local artwork under assets; sprite files are not redistributed here.

There is currently no public download for a complete playable dependency pack.
Do not present these upstream links as a tested one-command installation recipe.
If you already have a prepared private installation, keep its complete folder
and backups, use its normal launcher, or pass its path explicitly:

```sh
.venv/bin/pokedesk --root PATH_TO_PRIVATE_INSTALLATION
```

Installing the source-only wheel does not install these resources. Importing a
ROM does not generate them. A missing native library, reference pack or runtime
means the private setup is incomplete; do not download arbitrary replacement
binaries or overwrite save data to work around the error.

Connecting a ROM uses an already prepared edition pack and writes only to the
user library. Installing a missing resource pack remains explicit maintenance.

## Code updates and running jobs

Ordinary launch freezes the prepared installation under the writable library's
Sessions/installations/<content-id> and restarts into that copy before opening
the UI/core. Running games and their workers keep this version, including lazy
imports; restart normally to activate updated source/resources. The first launch
of a version must hash/copy resources and can take longer. Subsequent startup
verifies the retained copy. Warm job launch does not rescan the installation.
Do not remove retained versions while a game or resumable job uses them; cache
garbage collection is future work. APFS clones share physical storage until
modified; other filesystems can require a full copy per version.

Saves, autosaves, journals and ROMs stay in their existing profile/library paths,
outside the versioned copy. Copy Sessions with the rest of the portable tree to
preserve resumable jobs. Custom scripts capture their local Python helpers;
arbitrary external files are still the script author's responsibility. Scripts
are trusted executable code, not sandboxed plugins. Direct embedding/debug
imports should bootstrap a pinned process before creating Game/UI if they need
the same host-update isolation as the normal launcher.
