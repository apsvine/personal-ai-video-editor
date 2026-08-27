# Personal AI Video Editor

A private, local-first AI video editing application for one user. V1 will
target talking-head vertical videos. The current phase is **Phase 03: Persistent Job Pipeline and Crash Recovery**
(approved; manual acceptance passed), built on approved Phase 02 media
normalization and the preserved Phase 00 foundation. It is not a video editor yet.

## North-star workflow

Record → Drop Footage → Analyze → Generate Edit → Review → Export

This is a future workflow, not functionality available today.

## Intended architecture

React + TypeScript + Vite provide a minimal local status page, with a Python
3.11 + FastAPI backend providing health and local media import APIs. System
FFmpeg/ffprobe normalize one imported video; a future transcription provider
abstraction and Python edit planner will produce reusable JSON artifacts.
Remotion rendering comes later. Electron packaging comes only after the
pipeline is stable. The status page, health API, import, normalization, and proxy preview are implemented.
See [architecture](docs/architecture.md),
[data contracts](docs/data-contracts.md), and [the initial decision](docs/decisions/0001-local-web-first.md).

## Repository structure

```text
personal-ai-video-editor/
├── README.md
├── AGENTS.md
├── .gitignore
├── .env.example
├── docs/
│   ├── architecture.md
│   ├── data-contracts.md
│   └── decisions/
├── apps/
│   ├── web/                 # React/TypeScript/Vite; src/, package.json, lockfile
│   └── api/                 # FastAPI; app/, tests/, requirements*.txt
├── packages/renderer/
├── python/
│   ├── media/
│   ├── transcription/
│   ├── audio_features/
│   ├── editing/
│   └── common/
├── tests/
│   ├── fixtures/
│   ├── unit/
│   └── integration/
├── scripts/
│   ├── doctor.py
│   ├── smoke_test.py
│   └── clean_temp.py
├── runtime/                 # Generated locally; never tracked
│   ├── projects/
│   ├── cache/
│   ├── logs/
│   └── temp/
└── sample_media/
```

Empty source and test directories use `.gitkeep` placeholders. Runtime has no
placeholders. Raw recordings, generated media, models, secrets, and runtime
artifacts must stay out of Git. Tiny intentional fixtures under `tests/fixtures/`
and `sample_media/` can be committed after manual size and privacy review.

## Setup and local development

Prerequisites: **Python 3.11**, Node **20.19.x or newer 20.x, or 22.12+**, and npm.
These Node constraints follow the [Vite requirements](https://vite.dev/guide/).
Use a maintained Node release. Python 3.11 is the backend target even if another
Python version is your system default. Phase 02 requires system `ffmpeg` and
`ffprobe` on the backend PATH, with `libx264`, AAC and PCM encoders. Install them
yourself using a trusted system package manager; the application never installs
them. The health shell still works without them. No models, API keys, or database
are needed. Package downloads need network access; running the installed shell
uses only local connections.

From the repository root (macOS/Linux):

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -r apps/api/requirements-dev.txt
npm --prefix apps/web ci
```

If Python 3.11 is not on PATH, replace `python3.11` with its absolute executable
path. The `.python-version` file records the target but does not install Python.
On Windows use `py -3.11 -m venv .venv` and `.venv\Scripts\python.exe`.
The virtual environment, Node dependencies, and build outputs stay ignored.

Terminal 1, from the repository root — backend:

```sh
.venv/bin/python -m uvicorn app.main:app --app-dir apps/api --host 127.0.0.1 --port 8000 --reload
```

Terminal 2, from the repository root — frontend:

```sh
npm --prefix apps/web run dev
```

Open <http://127.0.0.1:5173>. The page displays the project title,
“Phase 03 — Persistent Job Pipeline and Crash Recovery”, and “API Status: Connected” when the API returns
the expected JSON. It starts at “Checking…” and shows “Disconnected” for
network errors, timeouts, non-success responses, or unexpected JSON. Each
request times out after three seconds; another check follows five seconds
after completion, so status recovers when the API restarts.

Check the API directly:

```sh
curl http://127.0.0.1:8000/health
# {"status":"ok","service":"personal-ai-video-editor-api"}
```

Both servers bind to loopback only. CORS allows only `http://127.0.0.1:5173`
and `http://localhost:5173`, with GET/POST/PUT and no credentials. Import writes
require the `X-Media-Import: 1` header; foreign browser origins are rejected. Ports are fixed;
Vite exits if 5173 is occupied instead of selecting an incompatible origin.
Stop an existing server or explicitly update both configurations if needed.
No API docs UI is exposed in this shell. CORS is not authentication; do not
expose the API to a public interface. Stop either server with Ctrl+C.

## Tests and build

Run from the repository root:

```sh
.venv/bin/python scripts/smoke_test.py
(cd apps/api && ../../.venv/bin/python -m unittest discover -s tests -v)
npm --prefix apps/web run build
.venv/bin/python scripts/doctor.py
.venv/bin/python scripts/doctor.py --phase01
.venv/bin/python scripts/doctor.py --phase02
```

Backend tests use standard-library `unittest` with FastAPI's
[TestClient](https://fastapi.tiangolo.com/tutorial/testing/) and HTTPX. They check
the health JSON, permitted local origins, excluded external origins, and GET-only
behavior on `/health`. Phase 02 tests cover projects, safe paths, metadata,
commands, disk rejection, cache integrity, failed writes, import APIs, and byte
ranges. A real integration test generates one tiny synthetic portrait clip in
temporary storage when system tools are available; otherwise it explicitly skips.
The frontend build runs strict TypeScript checks before Vite. No frontend test
framework is added.

To preview the production build locally, stop the Vite development server,
keep the API running, and run `npm --prefix apps/web run preview`. Preview uses
the same loopback port 5173 so the CORS policy remains unchanged.

Manual checks: open the page, confirm Connected, stop the API and wait up to
eight seconds for Disconnected, then restart it and confirm recovery. The Phase 02 acceptance steps below cover import and playback. There should be
no sidebar, timeline, or editing controls.

Dependencies are deliberately limited: React/React DOM for the UI;
TypeScript, React types, Vite and its React plugin for local development/build;
FastAPI for the API; Uvicorn without extras for the server; HTTPX for tests.
Frontend resolutions are recorded in `package-lock.json`; direct Python
dependencies are pinned in the requirements files, while transitive Python
dependencies are resolved by pip.

## Preserved Phase 00 utilities

Use Python 3.10 or newer; no package installation is needed. From this directory:

```sh
python scripts/smoke_test.py
python scripts/doctor.py
python scripts/clean_temp.py
```

If your system exposes Python as `python3`, substitute that command. The doctor
creates only the four local runtime directories and briefly writes/removes a
probe file in each. It never installs packages or changes system configuration.
PASS means a check succeeded, WARN means an optional/future prerequisite is
missing, and FAIL means a foundation requirement failed. FAIL gives exit code 1.
Node, npm, FFmpeg, and ffprobe remain optional in default Phase 00 mode.
The opt-in `--phase01` mode additionally requires compatible Node/npm, Python
3.11, installed FastAPI/Uvicorn/HTTPX, and the frontend Vite installation.
It warns if no virtual environment is active. Existing runtime, disk-space,
optional environment, and FFmpeg/ffprobe checks remain in both modes. Neither
mode installs anything; FFmpeg and ffprobe are still optional warnings in these
two modes. `--phase02` includes Phase 01 checks and makes missing or failing
FFmpeg/ffprobe mandatory failures.

Cleanup defaults to a dry run. `python scripts/clean_temp.py --apply` deletes
regular files only inside `runtime/temp`; it leaves directories and symlinks
alone and never touches projects, cache, or logs. Do not run cleanup concurrently
with other processes writing temporary files.

`.env.example` is a safe placeholder; copying it is optional. No Python utility
loads `.env` automatically. Vite follows its standard environment-file loading
behavior; never put secrets in frontend `VITE_*` variables. The shell needs no environment variables or credentials;
provider configuration is deferred to a later phase.

## Development philosophy

Read this file and `AGENTS.md` before changing anything. Work one phase at a
time, keep dependencies minimal, preserve passing behavior, and test each
change. Prefer explicit versioned artifacts that can be inspected and reused
after failures. Keep user data local by default; any future external provider
must require an explicit user choice. Do not assume prior chat context.

## Explicitly not built yet

There is no transcription, AI functionality, edit planning,
captions, rendering, database, authentication, or desktop packaging.
Remotion and Electron are not installed. No models or media are bundled.
Phase 04 and later functionality is deliberately excluded.

## Phase 02 behavior and API

Use **Import Video** to select one `.mp4` or `.mov` file. The browser sends its
filename, size and last-modified timestamp, then streams its bytes into a new
project. No original filesystem path is exposed to the server, and the original
file is never written. The uploaded copy is retained even if conversion fails.
The API validates the upload size and uses FFprobe to reject corrupt/non-video
inputs. Tool inputs are restricted to the MOV/MP4 demuxer and local file
protocol; renamed playlists cannot trigger network reads. Browser timestamps
are provenance supplied by the client, not trusted
content identity; SHA-256 of the received bytes establishes identity.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| POST | `/projects` | JSON `{filename, size_bytes, last_modified_ms?}`; create project, return ID (201) |
| PUT | `/projects/{id}/source` | Raw `application/octet-stream` body; upload and normalize; return project or cached project (200) |
| GET | `/projects/{id}` | Persisted stage/status and structured error |
| GET | `/projects/{id}/metadata` | Completed metadata |
| GET | `/projects/{id}/proxy` | Completed MP4, including byte-range playback |

Both write endpoints require `X-Media-Import: 1`. Errors use
`{"error":{"code":"...","message":"..."}}`, plus disk-space byte counts when
applicable; malformed request schemas use FastAPI's standard 422 `detail`.
Only one upload/conversion runs at a time; a second gets structured 409
`job_busy`, with no queue. Run a single Uvicorn worker. The original PUT remains
synchronous for compatibility, but now executes through a persisted job. The UI
uses `?background=true`, returning 202 after upload, and polls job status.
Progress represents stage milestones, not time or frame percentage.

The proxy is H.264/yuv420p, AAC when audio exists, fast-start MP4, 30 fps CFR,
with an aspect-preserving 1280x720 landscape or 720x1280 portrait bounding box.
FFmpeg autorotation is enabled and sample aspect ratio is normalized. Audio is
mono 16 kHz PCM signed 16-bit WAV. A source with no audio completes with
`audio_status: no_audio` and no WAV. Undecodable audio fails explicitly instead
of silently producing a successful transcript-ready asset.

Disk checks require four times the source size plus 256 MiB before transfer;
after inspection, three times source size plus expected PCM bytes plus 256 MiB
must remain. These are conservative estimates, not a guarantee against running
out of space, competing writers, or unusually large outputs.

Reuse requires completed status, matching configuration and source SHA-256,
and matching checksums of the saved source and every expected output. A corrupt
or missing output is not reused. A repeat import still uploads and preserves a
new source copy; its project records `reused_project_id`, while the response and
player use the previously completed project. This avoids conversion, not upload
or hashing. Cache lookup is a simple scan; there is no cache database or eviction.

Temporary conversion files are renamed only after all conversion commands
succeed. `project.json` completion is the commit marker; the API never serves
non-completed artifacts. Handled failures remove normalized outputs and keep
source/error/logs. An abrupt process kill may leave temporary or complete files
under an unfinished project, but those are never treated as a valid cache entry.
Phase 03 marks abandoned jobs interrupted and permits retry from the retained
source. Abandoned/failed/reused projects remain on disk for inspection and
require manual cleanup while idle.

## Manual Phase 02 acceptance

Run all commands below from the repository root. First install system FFmpeg
and ffprobe yourself, restart the backend environment, and require this to pass:

```sh
.venv/bin/python scripts/doctor.py --phase02
(cd apps/api && ../../.venv/bin/python -m unittest discover -s tests -v)
```

1. Start the backend in terminal 1:
   `.venv/bin/python -m uvicorn app.main:app --app-dir apps/api --host 127.0.0.1 --port 8000 --reload`.
2. Start the frontend in terminal 2: `npm --prefix apps/web run dev`.
   Open <http://127.0.0.1:5173> and confirm API Connected.
3. Choose a small MP4/MOV with audio. Before import, in terminal 3 run
   `SOURCE='/absolute/path/to/your/test.mp4'` and
   `shasum -a 256 "$SOURCE" > /tmp/phase02-original.sha256`.
   Click **Import Video**, select that file, and observe status then success.
4. Run `shasum -a 256 -c /tmp/phase02-original.sha256`; it must say OK.
5. Copy the displayed ID into `ID='paste-project-id'`, then set
   `P="runtime/projects/$ID"`. Run `find "$P" -maxdepth 2 -type f`.
   Confirm `project.json`, `source/<filename>`, and `logs/media.log` exist.
   Run `cmp "$SOURCE" "$P/source/$(basename "$SOURCE")"`; it must exit 0.
6. Run `.venv/bin/python -m json.tool "$P/normalized/metadata.json"`.
   Confirm source SHA-256, duration, dimensions, codecs, frame rate and rotation.
7. Run `ffprobe -v error -show_streams "$P/normalized/proxy.mp4"`.
   Confirm H.264, AAC, 30 fps and expected dimensions/orientation.
8. Play and seek the proxy in the browser. Confirm picture, orientation and sound.
9. Run `ffprobe -v error -show_streams "$P/normalized/audio.wav"`.
   Confirm `pcm_s16le`, 16000 Hz, one channel. To verify decoding, run
   `ffmpeg -v error -i "$P/normalized/audio.wav" -f null -`.
10. Run `shasum -a 256 "$P"/normalized/*` and note the result. Import the same
    source again. Confirm the UI says reused, displays the same completed ID,
    and the checksums are unchanged. The newly created project points to it.
11. Create a corrupt test file with
    `mkdir -p runtime/temp; printf 'not video' > runtime/temp/corrupt.mp4`.
    Import it and confirm a readable error. For unsupported extensions, the
    picker normally filters them; the API can be checked with
    `curl -i -H 'X-Media-Import: 1' -H 'Content-Type: application/json' -d '{"filename":"bad.txt","size_bytes":4}' http://127.0.0.1:8000/projects`.
    Expect 400 and `unsupported_input`.
12. Find the corrupt import's `project.json` under `runtime/projects` (its source
    filename is `corrupt.mp4`). Confirm status `failed`, source retained, readable
    `logs/media.log`, and an empty `normalized/` directory with no final or temp
    outputs. Automated tests also simulate a failure after proxy generation but
    during audio extraction and check that no partial output set survives.

Also try a silent source: success must explicitly say there is no audio; WAV
absence is intentional in that case. Do not commit any of these runtime files.

## Phase 03 jobs

Normalization runs in one background thread independently of the HTTP request.
Jobs persist at `runtime/projects/<project-id>/jobs/<job-id>.json`. Writes use a
unique temporary sibling, file flush/fsync, and atomic rename. The UI stores only
the selected project ID in localStorage and reloads authoritative job status from
the API every 750 ms. Keep using the same browser origin for refresh restoration.
Refreshing during normalization is safe; refreshing during the upload can abort
that upload, which is not resumable. Re-import an incomplete upload.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| PUT | `/projects/{id}/source?background=true` | Upload source and start normalization; 202 job |
| POST | `/projects/{id}/jobs` | Start normalization from a complete retained source; 202 job |
| GET | `/projects/{id}/jobs/latest` | Latest attempt, or null if none |
| GET | `/projects/{id}/jobs/{job_id}` | Persisted job |
| POST | `/projects/{id}/jobs/{job_id}/cancel` | Request cancellation; 202, poll for terminal status |
| POST | `/projects/{id}/jobs/{job_id}/retry` | New linked attempt for failed/interrupted/cancelled job; 202 |

All writes retain `X-Media-Import: 1` and local-origin protection. There is no
stage selection: only normalization can execute. Future stage names are contracts
only. No queue, database, AI, or new dependency is introduced.

Lifecycle: pending → running → succeeded / failed / cancelled / interrupted.
Startup converts abandoned pending/running records to interrupted. Graceful
shutdown also interrupts active work. Retry creates a new ID and `retry_of` link,
preserving the original attempt. Existing verified assets are reused; otherwise
normalization reruns from the retained source. It does not resume partway through
an FFmpeg command. Failed uploads need a new import, not a job retry.

Cancel checks run between stages and every 100 ms while a subprocess runs.
The runner terminates the child, waits up to two seconds, then kills/reaps it if
needed. No shell is used. Normalization removes partial outputs; completed cache
assets are not deleted. Cancellation after the publication boundary may resolve
as succeeded. Hashing and final publication are not instantaneously cancellable.
Readable errors appear in the UI; tracebacks and FFmpeg output remain in local
`logs/job-<id>.log` and `logs/media.log`, never returned by a log endpoint.

POSIX advisory locks protect one backend per runtime and one heavy operation.
A tool inherits the heavy lock: after SIGKILL, a surviving child may finish its
current command, but new jobs receive 409 until that child exits. It cannot
publish project completion. Recovery never assumes success. Do not delete lock
files while any backend/tool is alive. This phase targets macOS/Linux, not Windows.
No automatic retry or progress time estimate is provided. Damaged/unreadable job
JSON causes startup to fail visibly; restore it from backup or inspect it locally
while all processes are stopped. No automatic destructive repair is attempted.

### Manual Phase 03 acceptance

Run commands from the repository root. Stop existing frontend/backend processes
in their own terminals first; do not run two backends against the same runtime.

1. Start the backend: `.venv/bin/python -m uvicorn app.main:app --app-dir apps/api --host 127.0.0.1 --port 8000`.
2. Start the frontend: `npm --prefix apps/web run dev`. Open <http://127.0.0.1:5173>.
3. Import a small real MP4/MOV, observe stage/status/progress, and confirm proxy
   playback and metadata. Refresh while normalization is running; the same job
   must return. If it finishes too quickly, use the delayed launcher below.
4. Stop only the backend with Ctrl+C. Start the acceptance-only launcher:
   `.venv/bin/python scripts/job_demo.py --delay 20`. It waits in a cancellable
   subprocess before every normalization attempt; the normal launcher has no delay.
5. Import the small video again. During the 20-second running state, refresh;
   confirm the same job ID and progress. Click **Cancel**, wait for **cancelled**,
   and refresh again to confirm persistence. The source must remain intact.
6. Click **Retry**. Confirm a new job ID; wait about 20 seconds for **succeeded**
   and playback. Verified cached output may be reused. The old cancelled JSON
   remains on disk, linked by the new record's `retry_of`.
7. Import again to trigger another delayed job. While running, stop the backend
   with Ctrl+C. Restart the same demo command. Refresh if necessary; confirm
   **interrupted** and a readable message. Click **Retry**, then wait for success.
8. For a hard crash, start the demo in a terminal using:
   `.venv/bin/python scripts/job_demo.py --delay 20 & BACKEND_PID=$!; echo "$BACKEND_PID"; wait "$BACKEND_PID"`.
   Note the displayed shell PID, import again, and in another terminal run
   `kill -KILL <that-backend-pid>` while running. Restart the demo server.
   Confirm interrupted. A retry may return `job_busy` until the orphan's
   20-second wait finishes; retry again, and confirm success. Never kill an
   unrelated process or the frontend.
9. During any delayed running job, copy the displayed **Import project** ID:
   `ID='paste-import-project-id'`. Request a second heavy operation:
   `curl -i -X POST -H 'X-Media-Import: 1' "http://127.0.0.1:8000/projects/$ID/jobs"`.
   Require HTTP 409 with `error.code: job_busy`, and no second job file.
10. Inspect status without the browser:
    `curl "http://127.0.0.1:8000/projects/$ID/jobs/latest"`.
    Inspect `runtime/projects/$ID/jobs/` and local logs. Confirm progress stays
    within 0–1 and no raw technical logs appear in the UI.
11. Stop the demo and return to the normal backend command. Repeat Phase 02
    source-integrity, cache, corrupt-input and playback checks above. Do not
    commit generated runtime files.

Automated coverage includes simulated and real process interruption, actual
subprocess cancellation/reaping, exclusion across managers, graceful shutdown,
API recovery, retry lineage, atomic JSON failure, partial-output cleanup, and
preservation of successful cached assets, alongside all existing Phase 02 tests.
