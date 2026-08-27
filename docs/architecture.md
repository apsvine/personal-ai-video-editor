# Architecture — Phase 03 persistent jobs and future boundaries

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
on loopback. CORS is not local-user authentication. No dependencies were added;
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
