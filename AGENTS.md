# Emulator ownership and UI

- `EngineRuntime` owns the main session on `pokemon-engine-owner`. Create, read,
  step, capture, restore and close every `Game` on its owner. Keep the low-level
  `Game` ownership check enabled. CLI and isolated workers own their own sessions.
- `SessionController` contains headless session logic, frame guards, Automation,
  history and checkpoint orchestration. It must not import Tk or access widgets.
- `gui.Monitor` and `runtime_views` consume detached latest-value snapshots and
  asynchronous futures. Do not add RAM reads or synchronous waits for engine
  commands to UI callbacks. Cocoa current-event queries belong to `NativeInput`.
- F9/Esc use the out-of-band revocation epoch, not the bounded normal command
  queue. Preserve checks before every frame, after-frame guards, cancellation of
  pending starts and checkpoint barriers. A cancelled session must never send a
  late button. Do not batch frames across those checks.
- FileWriter publishes detached saves and preferences in order. Settings changes
  are patches; UI has a save hook, not another disk writer. Volume application
  can be immediate while persistence stays debounced. Keep durability barriers.
- A loaded save starts a new monotonic generation. Reject stale map/query replies
  and invalidate preview work, even when frame or navigation flags coincide.
- History UI queries and exports use `AnalyticsService` futures. Wait for the
  journal write barrier off-owner, query SQLite read-only in the process worker,
  release the read transaction before aggregation, and reject stale generations
  before accepting results or publishing prepared exports. Do not call expensive
  synchronous History queries or decode/copy full query results on the owner.
- The bounded journal projection is not disk retention. Preserve active run and
  timeline records; complete analytics reads the durable database, not only RAM.
- Published collection records are read-only. Reuse frozen box records by raw
  storage revision and generation; the selected-box cursor is separate metadata.
  Explicitly deepcopy only when an editable model is needed, not on every UI tick.
- Use private temporary Data for tests and benchmarks. Never replace the live
  save with a fixture. Other chats may edit this project concurrently: compare
  source hashes, preserve their changes and back up before installation.
- After runtime changes run the bundled Python with `-m unittest discover -s tests`.
  `tests/test_engine_runtime.py` covers ownership, UI liveness, F9, save barriers,
  errors, preferences and shutdown. `tools/benchmark_runtime.py` copies supplied
  state into disposable Data; use it for native latency and cycle validation.

# Owner scheduling

- All inbound sources publish work before `WorkSignal.notify()`: UI commands,
  preferences, bot requests/events, generic futures and both file/journal writers.
  Do not call the underlying Condition.notify directly. Notifications are versioned.
- `RuntimeScheduler` owns budgets and waiting policy. A wait checks both its turn
  version and all ready sources under the signal lock. Unfinished futures and
  active frame actions are not ready work. Preserve bounded service and frame progress.
- `SessionController.tick(quantum=...)` checks cooperative yield after a complete
  guarded frame. It must not inspect transport queues. F9 remains out of band and
  is checked before every frame and between owner commands.
- Pacing uses real monotonic deadlines, action lengths use emulated frames. Keep
  `frame_blocked()` shared by pacing and execution. Periodic services expose their
  next deadline; autosave, paused operation polling and health completions stay live.
- Include scheduling changes in runtime provenance (`run_context.versions`).
  Validate wake-before/during-wait races, saturated queues, pending barriers and
  real-cycle XP/real-minute, UI latency and manual takeover on private Data.

# Localization

- English is the default UI language. New interface text uses semantic keys with
  `i18n.t()` and named placeholders in both `locales/en.json` and `ru.json`.
  Use complete sentences and plural forms; do not concatenate translated words.
- Keep game IDs, map IDs, save data, filter values and automation commands locale
  independent. Use ID-based helpers in `entity_names` for display and bilingual
  search aliases. Use `pokemon_name()` / `literal()` for user-provided names.
- Existing Russian-source screens use the explicit `localized_tk` presentation
  adapter. Do not patch Tkinter globally or compare a translated label to decide
  which command to run. New widgets should use the shared design system.
- See `docs/localization.md`. Run `tools/check_localization.py` with the bundled
  Python and the relevant tests after changing catalogs or adding UI text. The
  normal unittest suite also audits catalog completeness and interpolation.

# Paths and reference packs

- Game.root / SDK roots identify mutable profiles or private job roots. Use
  session_paths/resource for installation files; never infer an installation by
  resolving src symlinks. New profile/job layouts store relative links only.
- Profile Data and legacy filenames stay in place. Workspaces are private to the
  session; library donor registries must not be written under a read-only app.
- catalog/load_reference are read-only pack readers. Never rebuild/migrate
  reference tables in the profile journal or add implicit pack writes to a read.
  Build/check packs explicitly with tools/build_reference.py before runtime.
- Reference records are shared and read-only. Copy before editing. Preserve the
  old pack on failed publication; source changes during compilation reject it.

# Installation versions

- CLI bootstrap snapshots the whole installation before creating the UI/core and
  execs its Python/main.py. Keep all lazy imports, native libraries, references
  and child processes in that version. A running app adopts updates on restart.
- Installation preparation/verification is startup or bounded background work;
  never scan/copy installation trees on the owner or per-frame path. Use the
  preparation pool separately from ordered FileWriter saves. F9 invalidates late
  completions before they can launch a bot or adopt a result.
- Jobs record a relative installation link and immutable execution.json with
  release/run IDs. Validate worker code, RPC identity and result identity before
  accepting work. Keep state-generation and save/hash checks as separate guards.
- No Data, ROMs or profiles enter installation snapshots. Saves always target
  the mutable profile/job. Do not remove active installation versions. Snapshot
  files are independent copies/APFS clones, never source hardlinks.
- Direct embedding must bootstrap into a pinned installation to guarantee safe
  host lazy imports across source updates. Bot scripts are trusted code, not a
  sandbox; captured local Python helpers do not freeze arbitrary external paths.

# One canonical repository

- Develop, test and publish from the same Git checkout. Do not maintain a sibling
  public-source working copy or copy fixes between separate project folders.
- ROMs, profiles, saves, generated packs and fixture banks remain local and
  ignored. Stage only reviewed source paths; never add private data with force.
- Packaging exports are disposable build artifacts, never another source of
  truth. Keep README.md authoritative for both the checkout and distribution.
- Run tools/public_checks.py before publication. Its source-coverage audit must
  include every application, test and developer source file in the allowlist.
  Inspect staged names and verify package contents before pushing.
