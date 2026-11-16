# Architecture and safety boundaries

Tk owns widgets. EngineRuntime owns the main emulator on pokemon-engine-owner.
UI commands return futures; detached snapshots travel back to the UI. Game
enforces thread ownership. Isolated jobs have their own cores and private Data.

RuntimeScheduler uses versioned WorkSignal notifications and bounded cooperative
service. F9/Esc revokes authority out of band; checks surround every frame.
The scheduler cannot preempt a long synchronous command. History queries now
wait for an ordered journal write barrier in AnalyticsService's dispatcher and
run in a separate read-only process. It releases its SQLite read transaction
before JSON aggregation. Results are decoded incrementally off the owner and
transferred without another full deepcopy. Export payloads are prepared by the
worker, then published through the ordered FileWriter after generation checks.

The owner's journal projection keeps recent events/battles/cycles rather than
loading all historical cycles. Complete analytics and exports read the durable
database, so this memory bound is not a history retention policy.

Inventory publication freezes box records once per raw storage revision and
reuses the same read-only objects across UI ticks. Party information stays
fresh. Generation, edition, trainer identity and PC bytes invalidate the cache.
UI code must explicitly deepcopy a published collection before editing it;
ordinary dict/list reads and JSON serialization remain supported. The first
publication of a genuinely changed collection still needs a full freeze.

SaveSnapshot contains detached state/SRAM bytes. FileWriter publishes them in
order, preserving named save barriers. SaveTimeline checks hashes and maintains
rollback anchors. Loading a state changes generation; stale replies/plans cannot
become authority to send input or overwrite newer progress.

Healing predicates live in pokemon_red.healing and have no emulator, reference
pack, UI or storage dependency. Training wraps their error in TrainingProblem;
the isolated Player wraps it in AcquisitionAttention. A healthy call sends no
input. A completed nurse interaction must confirm restored HP, statuses and PP.
Journey.center travels and ensures healing; callers must not immediately heal
again unless they actually changed the party or consumed resources.

Navigation uses directed transitions and exact local paths. A preview is not
permission to skip live obstacle, scene or movement checks. Reference data,
actual reachability and tested game support are different scopes.

The planned modular split is domain rules, application use cases, game adapters,
persistence/process infrastructure and Tk presentation. This first preparation
stages have introduced the pure healing boundary, source distribution guard,
process analytics and revisioned collection publication. Other domain and
application boundaries are still incremental refactoring work.

Run tools/benchmark_analytics.py on a prepared private installation to compare
takeover during 50,000-cycle aggregation. It uses disposable data and requires
the local clinic fixture; neither ROM nor live save is copied into its report.

## Installation, profile and workspace paths

paths.SessionPaths gives InstallationPaths (source/native/runtime/assets/reference
packs), ProfilePaths (Data and the mutable journal) and WorkspacePaths (Sessions).
Game.root and SDK project roots still identify the profile or private job, never
an implicit installation. A legacy root needs no marker and keeps its Data in
place. New profiles/jobs use .pokedesk-paths.json with relative installation and
library links. Resource reads resolve through InstallationPaths; jobs have their
own Data. Mutable shared donor registries belong to the library, not to source
resources. No source-directory symlinks are needed in new profiles or workers.

The default portable tree stays together: Data, Profiles, Sessions, vendor and
runtime can still live beside the source. A separate writable library/profile
can also point to a read-only installation; move their common portable ancestor
together. Resolution is read-only and cached. Explicit bind_installation is a
setup operation and invalidates layout caches; do not edit markers in an active
session. Legacy resource symlinks remain compatible and are not migrated/deleted.

Reference packs are compiled by tools/build_reference.py, not by catalog reads.
Each edition has vendor/catalog/packs/<edition>.json with schema/game/source
version and enriched species/moves/encounters. Runtime loads read-only frozen
records, shared by resolved pack path; no SQLite connection or implicit build.
Missing/incompatible packs fail explicitly. Rebuilds validate inputs, publish
atomically and durably, and leave old readers untouched until normal restart.
The --check build mode verifies source freshness without publishing anything.
New journals contain only mutable profile tables. Old reference tables are left
untouched for backward compatibility; no destructive journal migration is needed.

Ordinary ROM import only validates and installs the user file in the writable
library. It requires a prepared edition pack and never rewrites catalog resources.

## Immutable execution versions

The ordinary CLI snapshots src, native, vendor, assets, runtime, Bots and main.py
before UI/core creation, then execs the captured Python and entry point. This
pins the owner and its lazy imports as well as workers. An app keeps the same
installation until normal restart, including jobs started after a source update.
The content-addressed cache lives under the writable library's
Sessions/installations. It excludes Data, ROMs, Profiles and Templates. Relative
job links preserve portability when their common folder tree moves together.

Publication hashes source and copied contents, rejects concurrent edits, then
atomically publishes a read-only manifest/tree. macOS uses independent APFS
clones where available, with ordinary file-copy fallback; never source hardlinks.
Startup verifies an existing version fully. Warm jobs in a pinned process reuse
its in-memory version without a tree scan. Cache collection is not implemented;
old versions remain available for active and resumable jobs. Read-only flags and
hashes protect accidental mixups, not a malicious user who can alter the cache.

Every game-changing job records a release ID and unique run ID in execution.json.
Workers check their actual imported version; progress/results and bot RPC packets
carry the identity. Parents reject mismatches before applying state. Read-only
analytics/planning/travel replies carry their installation ID too. Existing
generation, parent process, ROM/trainer/save hashes and per-frame guards remain
independent checks. Management can launch a retained older acquisition job in
an isolated worker without changing the current owner's installation.

Bot launch and operation preparation use a bounded background pool, separate
from ordered FileWriter persistence. Completion notifies WorkSignal; the owner
checks the cancellation token and state generation before launching/adopting.
F9 invalidates pending launches. Capturing the main Game still belongs to its
owner. The core scheduler, guarded frame loop and autosave ordering are unchanged.

Custom bot entry points, sibling Python modules and local Python packages are
copied into a private run. Scripts remain trusted Python: arbitrary external
files and dependencies selected by script code are outside this guarantee.
Direct unbootstrapped embedding freezes child jobs for compatibility but cannot
retroactively freeze already imported host modules; embedding hosts must use the
pinned bootstrap for update isolation. The standard CLI does so automatically.

tools/benchmark_installations.py separates cold construction, verified reuse,
warm lookup, durable job preparation and worker import timings. Use the native
fixed-frame and large-history takeover benchmarks for runtime comparisons;
installation timings alone are not XP or UI-latency claims.
