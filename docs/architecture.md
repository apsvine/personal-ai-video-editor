# Architecture — Phase 07 caption planning and preserved pipeline

Phase 00 established repository boundaries. Phase 01 implements only the local
React + TypeScript + Vite status page and Python 3.11 + FastAPI health endpoint.
Vite binds to `127.0.0.1:5173`; Uvicorn runs on `127.0.0.1:8000`.
The page fetches `/health` directly from the API, with a three-second timeout
and another check five seconds after each result. CORS permits only
`http://127.0.0.1:5173` and `http://localhost:5173`, GET/POST/PUT, and no credentials.
There is no authentication or database. API docs routes
are disabled to keep this shell local and avoid remote docs assets.

Phase 02 adds `apps/api/app/media.py` for one-file import and status APIs, and
`python/media/normalization.py` for FFprobe/FFmpeg execution and persisted
artifacts. Phase 03 wraps normalization with `python/common/jobs.py`, a JSON
job store and one background thread. The UI uses asynchronous upload submission
and polls persisted job status; the original synchronous PUT response remains
available for Phase 02 clients. Source bytes are streamed, size-checked and
preserved before the normalization job starts.

The manager reserves one heavy-operation slot across uploads and normalization.
An in-process lock plus POSIX flock rejects competing work with HTTP 409; there
is no queue. A separate lifetime backend lock prevents two servers recovering
one another's live jobs. Only one Uvicorn worker is supported. Startup marks
abandoned pending/running records interrupted; graceful shutdown signals an
interrupt and waits for cleanup. A hard-killed backend's surviving tool retains
the heavy lock until exit, preventing overlap with retries. It can write only
an unfinished stage output, not publish completion. Locks live at
`runtime/.projects-backend.lock` and `runtime/projects/.heavy.lock`.

The media layer accepts a thread-local job control context without changing
normalization command construction or existing direct-call behavior. Cancellation
checks occur at milestones and in the subprocess wait loop (100 ms). Terminate,
two-second grace, kill and reap handles cancellation and timeouts; no shell or
user-supplied command execution is exposed. Normalization cleans partial outputs.
Completed verified caches are reused, including the same project after a crash
between media publication and job success publication. Each retry is a new linked
attempt; no automatic retry or sub-command resume occurs.

The frontend persists the selected import project ID in localStorage, fetches
its latest job on mount, and polls through backend outages. Successful jobs carry
the actual output project ID for cache reuse and playback. Errors are readable
messages only. Job tracebacks and media command logs stay on disk. Progress is
coarse stage completion, not an FFmpeg frame/time estimate.

Writes require a custom header and reject foreign browser origins. Serve only
on loopback. CORS is not local-user authentication. Phase 03 added no dependencies;
POSIX file locking makes Phase 03 macOS/Linux-only. `scripts/job_demo.py` is an
explicit acceptance launcher adding a cancellable delay before normalization;
it does not add production API routes or implement future stages.

The table describes boundaries, not permission to implement future phases.

| Location | Future responsibility |
| --- | --- |
| `apps/web` | React + TypeScript local review interface |
| `apps/api` | Python + FastAPI orchestration and local API |
| `python/media` | FFmpeg/ffprobe media inspection and transformations |
| `python/transcription` | Transcription provider abstraction; provider details stay behind this boundary |
| `python/audio_features` | Audio analysis for future editing and voice-reactive captions |
| `python/editing` | Python edit planner producing JSON, independent of rendering |
| `python/common` | Small shared Python utilities, when justified |
| `packages/renderer` | Remotion rendering later, consuming planned edits |

The intended local web application keeps orchestration separate from media
operations, provider integrations, edit planning, and rendering. The frontend
should not directly manipulate raw media files or provider credentials.

Future expensive stages will exchange persisted versioned JSON artifacts;
see `data-contracts.md`. User recordings and artifacts belong in ignored local
runtime storage. No network service or external AI provider is required now.
Future external processing must be an explicit user choice, never an assumed
part of the local-first workflow.

Electron desktop packaging is deferred until pipeline stability. This avoids
coupling foundational pipeline work to desktop lifecycle and distribution.
Phase 00 introduced no application dependencies. Phase 01 adds only the
frontend stack, FastAPI, Uvicorn, and HTTPX for tests; no Python media or AI dependencies. Phase 02 uses system FFmpeg/ffprobe only.

## Phase 04 transcription

The existing manager dispatches normalize/transcribe, defaults to normalize, and
preserves stage on retry. Transcribe resolves reused imports to completed output
projects, verifies source and all normalized checksums, and consumes only
normalized/audio.wav. No normalization rerun occurs. A missing audio stream is a
structured no_audio error; speech-free audio can produce an empty segments list.

python/transcription/engine.py owns validation, cache identity and publication at
analysis/transcript.json. provider.py adapts faster-whisper 1.2.1 to our schema.
worker.py runs in a separate Python process, with offline Hub flags and a complete
explicit local model directory. No model download function is used in production.
The parent owns publication; the child only writes an attempt's temporary result.

python/common/control.py holds the extracted Phase 03 control context and new
worker runner. python/common/errors.py holds the compatible structured error.
Normalization re-exports the existing interfaces; media commands are unchanged.
The worker inherits the heavy lock; cancellation/shutdown terminates, waits two
seconds, then kills/reaps. Worker timeout is one hour. Startup interrupts abandoned
jobs; retries validate a published transcript before invoking inference. A surviving
orphan cannot publish a transcript, and retains the lock until exit. Hard-crash
attempt files may remain for manual cleanup while idle.

The CLI uses the same manager and engine, requires the backend stopped, and never
downloads. UI readiness derives from project normalization, not the latest job;
failed transcription does not hide the proxy. Transcript fetching occurs on job
state changes rather than repeatedly hashing media on every polling tick.
Phase 04 added a button, status/progress, language, and read-only plain text; Phase 05 extends that surface below.


## Phase 05 review overlays

`python/transcription/review.py` owns sparse correction validation, merge and reset.
`apps/api/app/media.py` exposes review/save/reset routes through the existing local
origin/header guard. The Phase 04 raw API and engine are unchanged. Reused imports
resolve to the completed output project before selecting the override artifact.

`analysis/transcript.json` is never written by review. Only
`overrides/user_transcript.json` is created/replaced, using the existing atomic JSON
utility (unique sibling, flush/fsync, rename). Reset unlinks that file when no
corrections remain. The existing manager reservation serializes writes with each
other and raw transcription publication, including cross-process heavy-operation
exclusion. No new job stage, database, lock format or recovery path is introduced.
A read can return a consistent older transcript snapshot during publication; the
next load detects a changed checksum. All writes revalidate identity under lock.

Override segment identities pair canonical index strings with the validated raw
`content_checksum`. Stale/invalid overrides return raw text with diagnostics, never
silently merge. Saves and segment resets are blocked until Reset All clears such
state. Reset All checks the current raw identity before deleting. Raw retrieval
remains available regardless of override validity. Sequential edits from different
clients preserve other segment overrides; the last successful save to the same
segment wins. External file edits while the backend runs are unsupported.

`TranscriptReview.tsx` owns the proxy ref, playback time, review loading, and explicit
Save/Cancel/reset controls. App retains Phase 03 selected-project/job restoration
and passes job revision changes to trigger reload. A fresh mount loads persisted
corrections; no correction text lives in localStorage. `transcript.ts` holds small
pure timing helpers. `timeupdate`/`seeked` choose the half-open active interval;
buttons set `video.currentTime`, clamping only to a known media duration. No automatic
play, frame-perfect sync, timeline or scrolling is introduced.

Raw word buttons use validated original timestamps. Missing/invalid word lists fall
back to segment seeking without changing the Phase 04 validation contract. Edited
segment text and raw text/word details are distinct; corrected words are never
assigned old ASR timestamps. The model-estimated timing diagnostic and optional
low word-probability tooltip remain understated. All original timing is retained.

Node's built-in runner and React server rendering provide dependency-free tests.
A separate Vite browser harness exercises real DOM event handlers with mock HTTP
and media time; backend integration tests cover actual disk/API persistence.


## Phase 06 conservative cut planning

`python/audio_features/silence.py` invokes the existing cancellable FFmpeg runner
on verified normalized WAV, with null output and attempt-specific detector logs.
It probes timestamp alignment and accounts for supported source audio offsets and
AAC priming; uncertain timing is refused rather than silently treated as zero.
`python/editing/cuts.py` owns versioned input identity, speech protection,
deterministic candidate IDs, proposal topology, validation, atomic publication,
cache reuse and pure original/edited timeline mapping. No media is ever written.
The parent Python process alone publishes; a surviving FFmpeg process can write
only its log and retains the inherited heavy lock until it exits.

The existing Phase 03 manager dispatches `analyze` to the planner without changing
job formats, retries, locks or recovery. `plan` and `render` remain unsupported.
The Phase 04 normalized-input/read-transcript helpers are reused without changing
their validation contract. They resolve reused imports to completed output projects.
Only generated cuts, sparse cut decisions and normal jobs/logs are written.

`python/editing/cut_review.py` follows the Phase 05 sparse-overlay architecture.
The generated artifact always contains explicit proposal keep/removed intervals;
review constructs a separate accepted-only effective topology and mapping in memory.
Decisions cannot change proposal intervals or raw speech timing. All decision writes
share the existing heavy reservation, revalidate checksums under lock, and use
atomic JSON replacement. Stale/malformed decisions are never applied; Reset All
uses the current generated identity to clear them explicitly. Same-candidate
multi-client writes are last-successful-save-wins. No semantic migration is attempted.

`App.tsx` starts analyze through existing job controls. `CutReview.tsx` is a small
section composed inside `TranscriptReview.tsx`, sharing its original-time seek
callback without taking ownership of video playback. It loads on job revisions,
remount or explicit reload. It shows pending/accepted/rejected proposals and
estimated original/effective/removed durations supplied by Python. No edit timeline,
auto-skipping, rendering, localStorage decision cache or client-side mapping engine
is introduced. The Phase 05 browser mock explicitly responds to the new optional
cut route without changing transcript tests.

## Phase 07 deterministic caption planning

The earlier sections retain historical phase boundaries; Phase 07 adds the
existing `plan` stage's caption-only handler. `render` remains unsupported.

`python/editing/captions.py` is pure logic: raw Phase 04 timing and validated
Phase 05 effective strings are distinct inputs, alongside Phase 06 accepted-only
removals and verified audio-to-proxy offset. It owns grouping, deterministic IDs,
structured warnings and the renderer-independent data schema. It reuses Phase 06
`mapping` and `original_to_edited`; no second timeline-math implementation exists.

`python/editing/caption_store.py` validates source/normalized/raw/cut provenance
through existing helpers, applies both sparse overlays against current identities,
and fails closed for invalid/stale overrides. It never falls back to raw text in
that state. Reads reconstruct the expected deterministic plan to reject stale or
corrupt artifacts. Generation compares that plan with the saved artifact and
publishes only on cache miss using the existing atomic JSON writer.

`python/common/jobs.py` dispatches `plan`, stores resolved `caption_settings`
only on plan jobs, and preserves them on retry. Existing heavy reservation
serializes caption publication with transcription/cut/correction writes. There is
no new lock, queue, database, worker process or model. Existing recovery handles
plan jobs too. Cancellation is checked before/after planning and immediately before
publication; pure planning and hashing are not instantly cancellable.

`CaptionPreview.tsx` loads the plan and exposes a simple overlay/status panel
inside `TranscriptReview.tsx`, which retains video ownership. Revision-keyed
snapshots prevent late requests from restoring old captions. CutReview notifies its
parent after loads and mutations; transcript state changes likewise invalidate the
caption snapshot. The player uses original proxy seconds, with an explicit removal
guard. Edited seconds are stored for future consumers only. No playback skipping
or media rendering occurs. `captions.ts` contains the pure activation helper.

Exact original word chunks, including no-space fragments, retain source references
and spacing. Other safe text mappings require unchanged lexical words in order;
case/punctuation/whitespace changes may display with unchanged times. Ambiguity
omits the segment with a warning. Genuine caption envelopes never pad timing.
An accepted cut splits retained groups, and intersecting words/fragments are omitted.

The only new project artifact is `analysis/captions.json`. Source, normalized media,
transcript, transcript overrides, cuts and cut overrides are read-only to Phase 07.
Tests cover pure grouping/cut safety, atomicity/cache/immutability, jobs, original
clock activation, seeking, stale snapshots and browser reload.

## Phase 08A voice delivery feature extraction

`python/audio_features/features.py` is a dependency-free PCM16 extractor. It reads
the original normalized WAV clock and raw Phase 04 word timing, never corrected
text, effective cuts or captions. It publishes only `analysis/audio_features.json`.
The explicit `audio_features` job stage avoids overloading Phase 06 `analyze` and
otherwise uses the existing Phase 03 manager, heavy-operation lock, recovery,
retry, progress and atomic writer. A read endpoint rebuilds the deterministic
expected value against current protected inputs before serving the artifact.

RMS/dBFS, robust project percentiles, local energy/duration medians and adjacent
word gaps are pure deterministic calculations. Invalid individual timing is
represented and warned without inference. Original-time values are not mapped
through Phase 06. No frontend, waveform, caption behavior, pitch analysis, semantic
model, speaker model, renderer or future-stage infrastructure is introduced.
