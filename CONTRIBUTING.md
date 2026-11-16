# Contributing

Start with Python 3.12+ and `python3 -B tools/public_checks.py`. This public gate
uses synthetic data and does not need ROMs, Tk windows, a native core or a live
profile. It deliberately reports its limited scope.

## Runtime changes

Read AGENTS.md before editing runtime code. Every Game belongs to its creating
owner thread. UI callbacks use detached models and asynchronous commands. F9/Esc
revocation must bypass ordinary queues. Never combine frames across safety,
cancellation, learning or save barriers.

Use a private temporary Data directory for all game integration tests. Never
replace a live save with a fixture. Do not run untrusted automation scripts:
they are ordinary Python programs with the current user's filesystem rights.

On a prepared private installation, runtime changes also require:

```sh
./runtime/python/cpython-3.12.16-macos-aarch64-none/bin/python3 -B \
  -m unittest discover -s tests
./Check.command
```

The full regression runner needs privately prepared ROM/state fixtures. Its
`--quick` and `--cases` options are diagnostic profiles, not complete performance
gates. Do not silently skip missing integration assets and call the result a
full validation. See docs/SOURCE_SETUP.md for the remaining build limitations.

## Reviews and data

Keep formatting-only changes separate from behaviour changes. Add a regression
test for a meaningful bug, then test the actual boundary involved. Preserve
save ordering, rollback, checksum validation, stale-generation rejection and
manual takeover. Cancellation must never permit a late candidate adoption.

Do not commit ROMs, saves, states, profiles, logs, private benchmark outputs or
resource packs. Export using tools/export_source.py and verify both the source
folder and built artifacts. The allowlist is independent of .gitignore.

Original contributions are made under the project's Apache 2.0 license. Preserve
third-party licensing and attribution; do not copy code or datasets into this
license without checking their terms and documenting provenance.
