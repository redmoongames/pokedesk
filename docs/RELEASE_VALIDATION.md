# Mac beta validation — 2026-11-16

Target: Apple Silicon, macOS 13+ deployment target. Native and interactive checks
were performed on one **arm64 Mac running macOS 27.2**. This is not a claim of
testing every supported OS/hardware combination. The app is ad-hoc signed and
has not been notarized by Apple.

## Checks performed

- **86 public ROM-free contracts** and source/package export checks pass. CI runs these
  on macOS/Linux with Python 3.12/3.13; CI success is not a game-integration pass.
- The full existing integration suite passed: **1,117 tests**, 280.613 seconds,
  in a disposable installation with the locally required multi-edition fixtures.
- First-run generation was compared to the working reference: species, moves,
  abilities, XP curves, types, effectiveness and item names matched exactly.
  All 29 existing ordinary-land route slot tables matched exactly. The complete
  ordinary encounter index (land, water, fishing and Rock Smash) was compared
  with the working FireRed index. Unreleased Altering Cave event populations
  are excluded; a synthetic regression test covers this boundary.
- Interactive Finder-app testing covered ROM selection, background preparation,
  the playthrough menu, native Continue, rendering FireRed, F9/manual takeover,
  pause/resume, Enter and normal Quit. No Terminal was used for that player flow.
- The bundle audit rejects ROM/save payloads, external/broken links and native
  dependencies pointing into a developer's home/Homebrew installation. The final
  app passes deep/strict code-signature verification. Signing is ad-hoc.
- The source export and binary bundle builders have separate allowlists. Game
  catalogs/sprites are generated locally from the user's ROM, not copied from a
  playable project into the public application.

## Native disposable-save check

The app mounted read-only from the final DMG passed the same signature check and
used its own Python to prepare a fresh library from **copies** of an existing
ROM/state/save. The pinned runtime then ran a long observation bot at **16×**,
confirmed an autosave while the bot remained active, revoked control six times,
resumed simulation and recorded actual manual button masks entering the core after revocation, closed through save barriers and loaded
the saved state into a fresh core. This is a safety/startup smoke test, not an
XP/min benchmark or a complete route-grind test.

- Initial preparation: approximately **7.52 seconds**.
- Measured takeover acknowledgement: **2.46–7.91 ms** across six samples.
- Autosave during automation, post-takeover manual commands and cold restore: passed.
- Original ROM/state/save hashes and pre-setup copied save bytes: unchanged.

These timings measure the owner-thread revocation acknowledgement using a
2 ms polling observer. They are not end-to-end physical-key/display latency,
a worst-case guarantee, or a general performance comparison.

Reproduce with `tools/check_macos_release.py` and your own supported ROM/save;
see [SOURCE_SETUP.md](SOURCE_SETUP.md). Private fixtures, raw logs, ROMs, saves and
personal profile paths are not published with this report.

## Limits

- This binary release supports English FireRed Rev 1 only. Other source adapters
  and unreviewed story routes are not advertised as supported binary targets.
- Prepared donor saves/templates are excluded. Existing private installations
  and their profiles remain in place; the Finder build uses a separate data folder.
- Reference text localization is incomplete; Pokémon/entity names are prepared
  from the English cartridge. Old pinned installation caches are retained for
  resumable jobs, without automatic collection yet.
- Gatekeeper first-opening approval on another user's quarantined download was
  not bypassed or represented as a notarized/signing validation. Follow Apple's
  documented per-app opening flow if you choose to trust this beta.
