# Contributing

Start with Python 3.12/3.13 and `python3 -B tools/public_checks.py`. This public
gate uses synthetic data and requires no ROM, Tk window, native core or profile.
It reports its limited scope. Do not treat a source-check pass as a game pass.

## One checkout

The Git repository is the working project. Develop, test and push from that same
folder. Do not keep another manually synchronized public-source folder. Private
ROMs, profiles, saves, generated packs and fixture banks may coexist in ignored
folders; they never belong in commits or release assets.

`README.md` is the single player/developer entry point. Packaging exports are
disposable artifacts. `tools/public_checks.py` audits source coverage so a new
module, test, benchmark or launcher cannot silently be omitted from publication.
Review the diff and stage explicit source paths before pushing.

## Runtime and safety changes

Read [AGENTS.md](AGENTS.md) and [architecture](docs/architecture.md) first.
Every Game belongs to its creating owner thread. UI callbacks consume detached
models and asynchronous commands. F9/Esc revocation bypasses ordinary queues.
Never batch frames across safety, cancellation, learning or save barriers.

Add a regression test for the actual boundary being changed. Keep formatting
changes separate from behavior changes. Preserve save ordering, rollback,
checksum checks, stale-generation rejection and manual takeover. A cancelled
start or candidate adoption must never publish late.

Use private disposable copies for native checks. The public Mac builder and
`tools/check_macos_release.py` are documented in [SOURCE_SETUP.md](docs/SOURCE_SETUP.md).
They let a contributor test a built app using their own supported ROM and save,
without redistributing either. The full historical integration suite additionally
requires locally prepared multi-edition fixtures; on a fixture-equipped checkout
run `python3 -B -m unittest discover -s tests`. Missing fixtures are not passes.
`Run.command`/`Check.command` are included for existing prepared portable layouts;
use the Finder app or the documented build process for a clean installation.
Native benchmarks and reference compilers are included under `tools/`; some need
locally prepared ROMs, fixture banks or upstream data. Their inclusion does not
mean every adapter has a supported binary release.

## Releases and user data

The application builder takes clean allowlisted source plus pinned, checksummed
dependencies. A playable private project is never a build input. Review resources
and provenance before adding anything to `release_data`; no game dialogue,
graphics, executable game bytecode, ROM catalog dumps or personal state belongs
there. Existing seeds are functional/factual metadata and authored explanations;
ROM catalogs, sprites and encounter tables are compiled locally at first run.

Never commit ROMs, saves, prepared states, profiles, logs or generated resource
packs. Export with `tools/export_source.py`, verify built source packages, audit
the `.app`, and inspect release archives before publishing. The allowlist is
independent of `.gitignore`. Keep dependency notices and corresponding mGBA source
available with binary releases. Document signing/notarization status accurately.

## Licensing

Original contributions are under Apache 2.0. Third-party components retain their
licenses and attribution; the symbol-reference seed is GPL-3.0, mGBA-covered
files are MPL-2.0, and runtime dependencies have their own notices. Do not relabel
third-party material as Apache code. Bot scripts are trusted local programs, not
a sandbox; do not run untrusted scripts to review a contribution.
