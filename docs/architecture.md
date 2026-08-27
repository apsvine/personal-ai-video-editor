# Architecture — Phase 02 media and future boundaries

Phase 00 established repository boundaries. Phase 01 implements only the local
React + TypeScript + Vite status page and Python 3.11 + FastAPI health endpoint.
Vite binds to `127.0.0.1:5173`; Uvicorn runs on `127.0.0.1:8000`.
The page fetches `/health` directly from the API, with a three-second timeout
and another check five seconds after each result. CORS permits only
`http://127.0.0.1:5173` and `http://localhost:5173`, GET/POST/PUT, and no credentials.
There is no authentication, database, or general pipeline. API docs routes
are disabled to keep this shell local and avoid remote docs assets.

Phase 02 adds `apps/api/app/media.py` for one-file import and status APIs, and
`python/media/normalization.py` for FFprobe/FFmpeg execution and persisted
artifacts. The upload request runs normalization in a thread, while the frontend
polls persisted status. A process-local lock rejects concurrent uploads; there
is no queue, background worker, job pipeline, or database. Source bytes are
streamed to temporary storage, size-checked, and preserved in the project.
Writes require a custom header and reject foreign browser origins. Serve only
on loopback with one Uvicorn worker. CORS is not local-user authentication.

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
