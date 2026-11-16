# Building and verifying PokéDesk

Players should use the [prebuilt Mac release](https://github.com/redmoongames/pokedesk/releases/tag/v0.1.0-beta.1).
The DMG needs no Terminal, system Python, CUDA or standalone mGBA installation.
It contains no game cartridge, save, prepared state or game-art pack.

## Public source checks

Use Python 3.12 or 3.13:

```sh
python3 -B tools/public_checks.py
```

These synthetic contracts need no game resources. They are distinct from native
integration and interactive macOS tests. Wheel/sdist are developer packages;
installing a wheel alone is not equivalent to downloading the `.app`.

## Rebuild the Mac application

Build host: Apple Silicon macOS 13+ with Apple's Command Line Tools and Python
3.12+. These are developer requirements; they are not player requirements.

1. Download `pokedesk-dependencies-macos-arm64.tar.gz` and `SHA256SUMS.txt` from
   [v0.1.0-beta.1](https://github.com/redmoongames/pokedesk/releases/tag/v0.1.0-beta.1).
   Compare the downloaded archive's SHA-256 with the published checksum.
2. Unpack the archive, which contains `pokedesk-dependencies/`.
3. Run from the source checkout:

```sh
python3 -B tools/build_macos.py \
  --dependencies /path/to/pokedesk-dependencies \
  --output build/macos-beta \
  --version 0.1.0-beta.1
```

The output directory must be new. The builder verifies every dependency hash,
checks adapter-source compatibility, uses an allowlisted source selection and
includes only runtime code, explicitly reviewed setup seeds and dependency
notices. It rejects ROM/save files, external/broken links and nonportable native
link dependencies. `codesign --verify --deep --strict` checks the final envelope.
It never reads `Data`, `Profiles`, `Sessions`, `ROMs`, `templates` or an installed
playthrough as build inputs.

The result is ad-hoc signed. Public distribution without a first-opening macOS
exception requires the maintainer's Apple Developer ID signing and notarization;
those credentials are not part of the repository. Do not disable Gatekeeper.

To re-audit an existing application:

```sh
python3 -B tools/build_macos.py --audit /path/to/PokeDesk.app
```

## Rebuild dependencies and the adapter

The release also provides `mgba-7a12d6d-source.tar.gz`, corresponding to mGBA commit
`7a12d6d4b9acb14c0ae62c9166b6a2f3d08007f6`. Prebuilt regression test cartridges and
cinema captures are omitted; all emulator core source is retained. The adapter
build applies its two documented lockstep patches to the extracted source.

The pinned core is the official Libretro Apple Silicon mGBA binary, SHA-256:
`54ae92e80b012013f6d777fb3158b9f925be22c97896049b8549614d7514f505`.
It is included in the dependency archive, with MPL and third-party notices.
An arbitrary standalone mGBA installation is not ABI-compatible by assumption.

Python is the upstream `python-build-standalone` distribution:

- CPython 3.12.16, build 20261026, aarch64-apple-darwin, pgo+lto full archive.
- [Pinned upstream download](https://github.com/astral-sh/python-build-standalone/releases/download/20261026/cpython-3.12.16%2B20261026-aarch64-apple-darwin-pgo%2Blto-full.tar.zst).
- SHA-256: `016758f4881e5f71d63eddfbcdd53f25c5a9152435a863e4dc0770758eae32c3`.

```sh
python3 -B tools/prepare_macos_dependencies.py \
  --python-archive /path/to/python-full.tar.zst \
  --core /path/to/pokedesk-dependencies/native/mgba_libretro.dylib \
  --mgba-source /path/to/mgba-7a12d6d-source.tar.gz \
  --output build/dependencies
```

This checks pinned Python/core hashes, retains runtime dependency notices,
removes developer-only static libraries, package managers and stdlib test data,
and compiles the adapter from the current `native/` source. The manifest records
source and output hashes. The existing core remains a pinned prebuilt dependency;
this recipe does not claim a bit-identical source rebuild of the upstream core.

## First-run architecture

`native/app_launcher.m` keeps the `.app` process identity. Before initializing
Python/Tk, it selects either the bundled setup runtime or the pinned runtime from
the local installation receipt. Tk must create its own TKApplication subclass
before any activation request.

On first launch `desktop.py` asks for a supported English FireRed Rev 1 ROM.
`desktop_install.py` validates it and performs setup off the UI thread under an
exclusive library/application lock. `rom_resources.py` extracts catalogs,
encounters, trainer parties/names and sprites from the user's cartridge. Setup
uses a disposable core without loading an existing save; readers never rebuild
resources implicitly.

Code, native libraries, runtime and generated resources are frozen together in a
local installation. Only after verification are the relative profile link and
commit receipt published. Failed/cancelled preparation keeps the previous
selection. A damaged cache is repaired in a fresh namespace without replacing
code held by existing jobs. No save bytes are rewritten by this transaction.

A native-loader restart finishes setup while preserving the application bundle
identity; it does not turn the GUI into an unrelated Python application. Every
session/job still uses the pinned installation and existing safety epochs. Spawned
analytics workers also re-import the pinned main.py, not an updateable app bootstrap.

## Test a built app using your own save

The developer verifier deliberately requires a **new disposable work directory**:

```sh
python3 -B tools/check_macos_release.py \
  --app /path/to/PokeDesk.app \
  --rom /path/to/your/FireRed.gba \
  --state /path/to/your/FireRed.state \
  --save /path/to/your/FireRed.sav \
  --work /path/to/new-disposable-directory
```

It copies inputs, prepares resources with the bundled runtime, runs the pinned
core and a cancellable observation bot, checks autosave during automation,
measures revocation acknowledgement at 16×, accepts later manual input, closes
through durability barriers and cold-loads the save. It checks the original
ROM/state/save hashes at the end. It does not replace interactive testing or
claim that every route/story event is supported.

The historical full integration suite additionally requires locally prepared
multi-edition fixtures. Do not skip missing fixtures and report a complete pass.
Use private temporary Data for every native test.

## User data and legacy installations

The Finder build defaults to `~/Library/Application Support/PokeDesk/`.
**File → Open saves folder** opens it. Back up/copy the whole folder while the app
is closed, including its local ROM and pinned versions. Relative links preserve
portability between M-series Macs; app updates do not move profile contents.
`POKEDESK_LIBRARY` is an optional developer override for isolated launch tests.

A legacy portable project remains separate and is not silently migrated. Back it
up in full before importing anything. A source command can still select an
already prepared legacy installation using `pokedesk --root /path/to/project`.
Never upload a working data folder or attach ROMs/saves to an issue.
