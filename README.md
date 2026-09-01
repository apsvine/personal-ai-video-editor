# Personal AI Video Editor

A private, local-first AI video editing application for one user. V1 will
target talking-head vertical videos. The current phase is **Phase 08B: Bounded Voice-Reactive Emphasis Policy**, built on approved Phases 00–08A. It converts explainable measurements into restrained renderer-independent decisions; animation and rendering remain future work.

## North-star workflow

Record → Drop Footage → Analyze → Generate Edit → Review → Export

This is a future workflow, not functionality available today.

## Intended architecture

React + TypeScript + Vite provide a minimal local status page, with a Python
3.11 + FastAPI backend providing health and local media import APIs. System
FFmpeg/ffprobe normalize one imported video; an offline transcription provider
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
are needed for import/normalization. Transcription requires a separately acquired local model. Package downloads need network access; running the installed shell
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
“Phase 07 — Caption Planning Engine”, and “API Status: Connected” when the API returns
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
The frontend build runs strict TypeScript checks before Vite. Phase 05 adds dependency-free Node tests and a browser harness, described below.

To preview the production build locally, stop the Vite development server,
keep the API running, and run `npm --prefix apps/web run preview`. Preview uses
the same loopback port 5173 so the CORS policy remains unchanged.

Manual checks: open the page, confirm Connected, stop the API and wait up to
eight seconds for Disconnected, then restart it and confirm recovery. The Phase 02 acceptance steps below cover import and playback. Phase 07 adds only the caption-plan controls and preview; no sidebar, complex timeline or rendering controls.

Dependencies are deliberately limited: React/React DOM for the UI;
TypeScript, React types, Vite and its React plugin for local development/build;
FastAPI for the API; Uvicorn without extras for the server; HTTPX for tests;
faster-whisper 1.2.1 and its required transitive dependencies for transcription.
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
transcription model configuration is described below.

## Development philosophy

Read this file and `AGENTS.md` before changing anything. Work one phase at a
time, keep dependencies minimal, preserve passing behavior, and test each
change. Prefer explicit versioned artifacts that can be inspected and reused
after failures. Keep user data local by default; any future external provider
must require an explicit user choice. Do not assume prior chat context.

## Explicitly not built yet

Conservative silence cuts, caption planning, voice-delivery feature extraction, and bounded emphasis policy are implemented. There is no caption animation, rendering, database, authentication, or desktop packaging.
Remotion and Electron are not installed. No models or media are bundled.
Phase 08B and later functionality is deliberately excluded.

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

All writes retain `X-Media-Import: 1` and local-origin protection. Phase 03 originally supported only normalization. Phase 04 adds explicit transcribe
stage selection; Phase 06 adds analyze; Phase 07 adds caption-only plan. Render remains rejected. There is no queue or database.

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

## Phase 04 — offline transcription

After normalization completes with audio, click **Transcribe**. The existing
persisted job controls show progress, Cancel and Retry. On success the UI shows
detected language and transcript text. Phase 05 adds the review controls below. Proxy playback stays available after transcription failure or refresh. Captions, edit planning and rendering remain excluded.

The only added direct dependency is `faster-whisper==1.2.1`; install using the
existing requirements command. Its required transitive dependencies include
CTranslate2, PyAV, tokenizers, Hugging Face Hub and ONNX Runtime. No additional
provider or ML framework is explicitly added. The base speech model is separate.

Default model directory: `runtime/cache/transcription/faster-whisper/base/`.
Override with `PERSONAL_AI_VIDEO_EDITOR_MODEL_PATH=/absolute/local/model/path`
when launching backend/CLI/doctor. The path must contain a complete CTranslate2
multilingual base model: model.bin, config.json, tokenizer.json, vocabulary.txt.
The provider loads only this local path and uses CPU INT8 with four threads and
one worker. Missing files produce `model_not_installed`; no automatic downloads.

### Separate model acquisition — DO NOT run without approval

The following is the proposed explicit future step, **not run during Phase 04
implementation/testing**. From the repository root, after separate approval:

```sh
HF_HOME="$PWD/runtime/cache/transcription/faster-whisper/hub" .venv/bin/python -c 'from huggingface_hub import snapshot_download; snapshot_download("Systran/faster-whisper-base", local_dir="runtime/cache/transcription/faster-whisper/base", allow_patterns=["model.bin", "config.json", "tokenizer.json", "vocabulary.txt"], token=False)'
```

This deliberately needs network access; application execution does not. All model
files/cache stay under ignored runtime. No credentials or external processing of
recordings is required. The transcript records a content fingerprint of the local
model; replacing model files or changing settings causes a cache miss.

### API and CLI

POST `/projects/{id}/jobs` with `{"stage":"transcribe"}` and `X-Media-Import: 1`
starts transcription. Existing latest/read/cancel/retry endpoints work unchanged.
GET `/projects/{id}/transcript` returns the internal transcript JSON. The canonical
artifact is `runtime/projects/<completed-output-project-id>/analysis/transcript.json`.
Reused imports resolve to that output project. Retry never silently normalizes.

Stop the backend before the debug CLI (the same lifetime lock protects recovery):

```sh
.venv/bin/python scripts/transcribe_project.py <project-id>
.venv/bin/python scripts/doctor.py --phase04
```

CLI jobs use the same engine/store, log and retry semantics as API jobs. Ctrl+C
cancels the CLI job. Doctor checks dependencies/local model files without inference,
and reports missing model as WARN rather than FAIL. It never acquires models.

### Verification and real-model acceptance

Run the foundation smoke test, full backend suite, frontend build, default doctor,
--phase01, --phase02, --phase04, and git diff --check. Unit tests use mock providers
and synthetic PCM; no real speech model is loaded. Existing Phase 02 real-media
and Phase 03 process-crash tests remain enabled.

Only after separate model approval/acquisition: import a small private spoken clip,
transcribe, inspect language/text/word boundaries against speech, and inspect the
canonical JSON. Refresh during inference and after success. Repeat transcription
and confirm cache reuse with unchanged artifact bytes. Try cancel/retry, graceful
restart and hard-kill recovery on a longer clip, verifying normalized asset hashes
and the prior transcript remain unchanged after failure. Test a video without an
audio track and an audio track containing silence. Stop the backend and run the
CLI against the same project; it should reuse the transcript. Do not commit runtime.

Limitations: model timing/recognition is approximate; multilingual/code-switching
accuracy needs manual assessment. Silence may hallucinate speech (VAD is disabled).
Strict timestamp validation rejects invalid alignment rather than inventing precision.
Progress is coarse, inference timeout is one hour, and full source/model hashing
can take time and is not instantly cancellable. No incremental inference resume.
Manual acceptance confirmed usable real-speech output. Broader language/technical-term
quality and systematic CPU/memory benchmarks remain future tuning observations.

### Phase 04 acceptance

Phase 04 manual acceptance passed: local base-model transcription, usable text,
language detection, genuine word timing, aligned segment envelopes, browser
refresh, validated cache reuse, cancellation persistence, retry lineage,
interruption/recovery, prior-transcript preservation, readable no-audio failure,
and preserved Phase 02 normalization/Phase 03 jobs were confirmed by the user.

The segment-envelope fix preserves every word timestamp and expands only its
internal parent segment before strict validation. The complete backend suite now
contains 54 tests, including the exact real-world timing regression. CPU/INT8,
four threads and VAD disabled remain the baseline. Models, source media,
normalized outputs, transcripts, jobs and logs remain ignored runtime data.
That acceptance covered Phase 04 only; Phase 05 acceptance remains separate.


## Phase 05 — transcript review

Transcript review opens automatically beside/below the proxy after normalization;
click **Transcribe** if no transcript exists. The selected project still restores
from localStorage and persisted Phase 03 jobs. Refresh after saving reloads corrections
from the API, not from browser memory. **Reload transcript** also fetches fresh state
(and discards an unsaved draft).

The raw ASR artifact `analysis/transcript.json` remains immutable to review operations.
GET `/projects/{id}/transcript` still returns the original Phase 04 artifact.
Corrections are sparse text-only overrides at
`runtime/projects/<completed-output-project-id>/overrides/user_transcript.json`.
Reused imports share their completed output project's corrections. No database,
new dependency, transcription provider, or Phase 06 feature is added.

The schema uses `schema_version: 1`, `project_id`, `source_transcript_checksum`, and
`segments: {"0": {"text": "corrected text"}}`. The checksum is the validated raw
artifact's **content_checksum** (canonical JSON SHA-256, not a byte-file checksum).
Segment IDs are canonical decimal zero-based indices valid only with that checksum.
No timestamps or copied transcript are stored. Full schema and endpoints are in
`docs/data-contracts.md`.

Playback events highlight the segment containing proxy time, using half-open
`[start, end)` intervals. Gaps have no active segment. Segment timestamp/text
buttons seek to the segment start; original timed-word buttons seek to their
unaltered start. Neither action starts playback automatically. Timing is approximate.
Without valid words, only segment seeking is offered. Corrected words do not inherit
old word timing: edited text seeks to the segment; expand **Original ASR text and
timed words** to inspect the raw text and seek its original words. The same details
view handles raw ASR segment text that differs from concatenated word text.

**Edit → Save** writes once; **Cancel** writes nothing. Empty corrections are allowed,
with a 10,000-character limit and valid UTF-8 required. **Edited** marks a correction.
Saving the exact raw text or **Reset Segment** removes that segment's override.
**Reset All Corrections** safely deletes the override file; the last segment reset
also removes it. Atomic writes use the existing unique temp-file, flush/fsync and
rename utility. Edits/reset share the existing heavy-operation reservation so they
cannot race transcription publication. Busy operations return 409; retry after
completion. Multiple clients saving the same segment use last-successful-save wins.

Stale checksums or malformed overrides are never applied. Review returns the raw
text with a readable `stale` or `invalid` state, blocks edits and offers Reset All.
Reset All requires the current raw checksum but deliberately permits clearing a
stale/malformed override file. There is no automatic migration. An outdated save
or reset returns 409 and the UI reloads review. Raw retrieval is independent of
correction validity. No source/model acquisition occurs while reviewing.

### Phase 05 verification

From the repository root:

```sh
.venv/bin/python scripts/smoke_test.py
(cd apps/api && ../../.venv/bin/python -m unittest discover -s tests -v)
(cd apps/api && ../../.venv/bin/python -m unittest discover -s tests -p test_transcript_review.py -v)
npm --prefix apps/web test
npm --prefix apps/web run build
.venv/bin/python scripts/doctor.py
.venv/bin/python scripts/doctor.py --phase01
.venv/bin/python scripts/doctor.py --phase02
.venv/bin/python scripts/doctor.py --phase04
git diff --check
```

All available doctor modes are listed above; there is no separate Phase 03/05 mode.
The full backend suite includes the real FFmpeg media integration and job/crash
recovery tests. Standard tests never download or load a model. `npm test` compiles
and tests review helpers/server-rendered markup with Node's built-in runner.
For DOM interaction tests start Vite and open
<http://127.0.0.1:5173/tests/review.html>; require **ALL PASSED**. This separate
harness mocks HTTP persistence and video time, checks remount restoration, and
never writes user projects. It is not included in the production entry/build.
Real media playback and browser refresh are covered by acceptance below.

### Manual Phase 05 acceptance

Run these steps from the repository root. Restart the backend in its own terminal
if it was already running old code; do not launch a second backend against the same
runtime. Use the previously approved installed model; do not download another.

1. Start `.venv/bin/python -m uvicorn app.main:app --app-dir apps/api --host 127.0.0.1 --port 8000`.
   Start `npm --prefix apps/web run dev` in a second terminal. Open
   <http://127.0.0.1:5173>, import a small spoken MP4/MOV and wait for normalization.
2. Click **Transcribe** and wait for succeeded. Confirm the proxy remains available.
3. Locate **Transcript review** beside/below the proxy; verify language and segment text.
   Copy the displayed **Project** ID (completed output, not Import project), then run:
   `ID='paste-project-id'; P="runtime/projects/$ID"; shasum -a 256 "$P/analysis/transcript.json" > /tmp/phase05-raw.sha256`.
4. Play the proxy; confirm the highlighted segment changes with speech. Pause it.
5. Click several segment timestamp buttons; confirm the player seeks to their starts.
6. Click several raw words; confirm approximate seeking. Wordless segments should
   have only segment seeking; exercise that case in the browser harness if needed.
7. Click **Edit** on a segment and change its text. Timestamps must not be editable.
8. Click **Save**; confirm new text and **Edited**. Expand original ASR details and
   confirm the original text and timed words remain available.
9. Refresh the browser on the same origin.
10. Confirm the correction, proxy and transcript restore; inspect
    `.venv/bin/python -m json.tool "$P/overrides/user_transcript.json"` for a sparse override.
11. Run `shasum -a 256 -c /tmp/phase05-raw.sha256`; require **OK**.
    GET `http://127.0.0.1:8000/projects/$ID/transcript` with curl and confirm raw text.
12. Click **Reset Segment** on the corrected segment.
13. Confirm its raw text returns and **Edited** disappears. If it was the only
    correction, `test ! -e "$P/overrides/user_transcript.json"` must succeed.
14. Edit/save two segments (or the single segment twice for a one-segment clip),
    then click **Reset All Corrections**. All raw text returns; the override file
    must be absent. Also try Edit → type → Cancel and verify no correction appears.
15. Refresh again; verify playback, seeking and raw transcript. Rerun the raw
    checksum check; require **OK**.
16. Test stale detection safely with the isolated fixture:
    `(cd apps/api && ../../.venv/bin/python -m unittest discover -s tests -p test_transcript_review.py -k stale -v)`.
    This publishes a changed valid transcript only in temporary storage, verifies
    stale corrections are withheld, rejects outdated saves/resets, and resets using
    the new identity. The browser harness separately tests the stale warning/reset UI.
    Do not edit your real raw transcript to simulate this case.

Phase 05 limitations: no automatic scrolling, frame-perfect alignment, word-level
text edits, new word alignment, multi-client conflict resolution, or semantic
migration. Reload/refresh is needed to observe external correction changes.
Human speech/timing accuracy and actual video playback remain manual acceptance.


### Phase 05 acceptance — approved

Phase 05 is approved following the user's completed manual acceptance checks:

- A saved single-segment correction and Edited indicator persisted after refresh.
- Reset Segment restored the original text and cleared the Edited indicator.
- Reset All Corrections restored both edited segments; originals persisted after refresh.

Final verification for project `c3ee2ffb1d014569b01a8d25911a9872` confirmed four
original segments, `override_state: none`, zero edited segments, no override file,
and unchanged raw transcript bytes. Frontend, backend health and review API returned
HTTP 200. Both servers were left running. The earlier review-loading failure was
resolved by restarting the stale backend; no transcript migration or validation
weakening was needed. A cached-transcription/no-overrides regression also covers
reused-import resolution.

No remaining Phase 05 acceptance or implementation blocker is known. Approximate
ASR timing and the documented V1 limitations remain intentional. Phase 06 is not
started. Approval does not authorize a commit, push, merge, or tag.


## Phase 06 — Smart Cuts & Silence Removal Planning

**Analyze Smart Cuts** runs a persistent `analyze` job after normalization and a
valid Phase 04 transcript exist. It consumes only verified normalized audio and
raw word timing. It never transcribes automatically and never downloads a model.
The existing source, proxy, WAV, transcript and transcript corrections are untouched.
Only `analysis/cuts.json`, `overrides/user_cuts.json`, and jobs/logs are produced.
No `plan` or `render` handler, edited playback, captions or Phase 07 feature exists.

FFmpeg `silencedetect` reads the mono 16 kHz PCM16 WAV and writes to a null sink.
Defaults: -40 dB, 0.8 s minimum silence, 0.2 s preserved at silence edges and
around raw words, 0.3 s minimum resulting cut. There is no threshold auto-tuning.
Valid wordless segments protect their entire envelope. Invalid/missing transcripts
block analysis; valid empty speech produces a prominent human-review warning.
Text corrections (including empty corrected text) never remove speech protection.

Generated `keep`/`removed` describe the **proposal topology**, as if every proposed
cut were accepted. They are not the effective user plan. The review response
separately exposes effective keep/removed/mapping: pending or rejected proposals
are retained; only accepted proposals shorten the effective plan. Accept, Reject,
Reset decision and Reset All Decisions write only sparse cut overrides. Reload
and refresh fetch saved decisions. Resetting the last decision removes the override
file. Stale/invalid overrides are withheld and can be explicitly reset. Playback
and candidate seeking always use the unchanged original proxy timeline.

### Timing and safety

`source_duration` is the normalized proxy's full presentation duration, which can
differ from source-container metadata. Detector and raw transcript times originate
at WAV sample zero. The planner records `audio_offset`, derived from the source
stream start relative to the source container origin, then shifts both detector
intervals and protected raw-word intervals into proxy time. It verifies the proxy
starts against that offset, allowing a known single AAC encoder-priming frame.
Missing, inconsistent or unsupported timing raises `cuts_alignment_uncertain`.
This does not change Phase 05's original ASR timing/seeking behavior.

ASR alignment is approximate and may omit quiet speech; energy detection is not a
speech classifier. Music, breaths and intentional pauses may be retained or proposed.
Listen to every candidate before accepting. No automatic acceptance is implemented.
No edited video exists to audition; original playback remains full length.

### APIs

POST `/projects/{id}/jobs` with `{"stage":"analyze"}` starts analysis. Existing
read/latest/cancel/retry routes apply. Cancellation checks and subprocess cleanup,
one-heavy-job exclusion, restart recovery and retry lineage remain unchanged.
Progress is coarse: .05 prerequisites, .15 detector, .8 planner, .9 publication,
1 success. Settings are versioned Python configuration, not an editable API surface.

GET `/projects/{id}/cuts` returns validated generated proposals; GET
`/projects/{id}/cuts/review` returns candidates, decisions and the effective mapping.
PUT `/projects/{id}/cuts/overrides/{cut_id}` accepts
`{"source_cuts_checksum":"<current checksum>","action":"accept"}` (or `reject`).
POST `/projects/{id}/cuts/overrides/{cut_id}/reset` and POST
`/projects/{id}/cuts/overrides/reset` accept only the checksum identity object.
All writes require `X-Media-Import: 1` and the existing local-origin guard.
See `docs/data-contracts.md` for exact schemas and mapping conventions.

### Verification and manual acceptance

Run the complete Phase 05 verification commands above; they include Phase 06
backend and frontend tests. Also run `npm --prefix apps/web test`. Both browser
harnesses must show **ALL PASSED** at `/tests/review.html` and `/tests/cuts.html`.
They use isolated mocks and never mutate user projects. All doctor modes remain
`default`, `--phase01`, `--phase02`, `--phase04`; no new doctor mode is invented.

1. Stop the old backend in its own terminal, then restart from this repository:
   `.venv/bin/python -m uvicorn app.main:app --app-dir apps/api --host 127.0.0.1 --port 8000`.
   Keep/start `npm --prefix apps/web run dev`. Do not run a second backend on the same runtime.
2. Open `http://127.0.0.1:5173`; select/import a real spoken clip and finish
   normalization/transcription using the already approved local model.
3. Record hashes of the retained source, `normalized/proxy.mp4`, `normalized/audio.wav`,
   `analysis/transcript.json` and `overrides/user_transcript.json` if present. Never
   edit raw artifacts or alter a real transcript to manufacture a stale state.
4. Click **Analyze Smart Cuts**, wait for success, inspect `analysis/cuts.json`, and
   GET `/projects/<completed-output-id>/cuts` to require successful validation.
   Check the explicit proposal `keep`/`removed`, inputs, settings and checksum.
5. Require every candidate to start **pending**, effective duration equal to original,
   and removed time zero. Seek before/after each candidate and listen through it.
   Reject anything that might clip speech or damage an intentional pause.
6. Record the `cuts.json` byte hash. Accept one candidate: effective duration must
   fall by its length. Accept another if available; durations must combine. Refresh
   and confirm saved decisions. Proxy duration/playback must remain unchanged.
7. Reject every candidate: full effective duration must return. Reset one decision:
   it becomes pending. Reset All Decisions: every candidate becomes pending, full
   duration returns, and `overrides/user_cuts.json` is absent. Refresh again.
8. Verify all protected hashes from step 3 and the generated cut hash from step 6
   are unchanged. User decisions must never appear in generated cuts or transcript files.
9. Analyze again: require a cache hit and byte-identical `cuts.json`. Exercise cancel,
   retry and backend restart on a longer clip; require persisted job states and no
   incomplete cut publication. Automated tests cover fast jobs that finish before Cancel.
10. Require both browser harnesses to pass. Use isolated automated stale/invalid
    override tests instead of tampering with real runtime files. Listen manually
    before declaring Phase 06 accepted; never begin Phase 07 from these instructions.

Verification during implementation used a temporary copy of the accepted real
Phase 05 clip. One conservative candidate of about 0.308 s was produced; decisions,
reset, topology validation, cut/transcript cache reuse and protected hashes passed.
Real normalization of a separate temporary source copy also passed. Existing user
project media/transcript files were not changed. The initial verification did not claim human listening acceptance. The stale Phase 05
backend was subsequently restarted and real browser generation/reload verified.
The user has now approved Phase 06 acceptance and explicitly authorized its commit,
branch/main pushes, merge and annotated release tag.


### Phase 06 acceptance — approved

The user personally listened around the real 0.308-second proposal and confirmed
no audible word or syllable is removed and both boundaries sound safe. Pending,
Accept, Reject, single reset, Reset All Decisions, refresh persistence and read-only
reload passed. Only explicit acceptance changes the effective plan. Generated cuts
and user decisions remain separate. Source, proxy, WAV, raw transcript and transcript
overrides remain unchanged; no rendered or destructively trimmed video exists.

Automated verification is green: 86 backend tests, 10 frontend tests, both browser
harnesses, production build, smoke, all available doctor modes and protected hashes.
This approval covers Phase 06 only. Approximate ASR timing, conservative energy
detection and supported timestamp-layout limits remain intentional. Phase 07 has
not started; captions and rendering remain excluded.

## Phase 07 — Caption Planning Engine

The earlier phase sections describe their historical acceptance boundaries.
Phase 07 now implements only this approved flow:

Phase 05 effective text + Phase 04 authoritative word timing + Phase 06
accepted-only topology → pure deterministic planner → analysis/captions.json
→ HTML/CSS preview over the unchanged proxy.

Click **Generate captions** after transcription and Smart Cuts analysis. It starts
a persistent `plan` job using existing progress, cancel, retry, recovery and locks.
It does not analyze cuts or transcribe automatically. Missing/stale cut plans must
be regenerated explicitly; invalid/stale correction or decision overlays must be
resolved explicitly. No render handler, Remotion, AI rewriting, style designer,
animations, sound effects, B-roll or Phase 08 functionality is introduced.

### Rules, safe text and timing

Defaults are 5 maximum timed words, 42 characters (including separators), 0.5 s
pause threshold, 0.7 s minimum duration, 3.0 s maximum duration, and punctuation
break preference enabled. Settings are validated/versioned and deterministic.
Groups never cross transcript segments, omitted words or accepted cuts. Greedy
grouping breaks at punctuation, pauses and maximum limits. Short groups try a
safe next-neighbor merge, then the previous; soft punctuation can merge but sentence
stops and pauses cannot. If no safe merge fits, preserve genuine timing and warn.
An indivisible word exceeding a maximum is omitted and warned, never split in time.

Exact concatenated raw word chunks can reconstruct effective text, including
separately timed compound fragments. Their original joiners are retained and
no-space fragments stay together. Otherwise, whitespace tokens must match raw
timed words one-for-one with the same lexical text after case folding and removal
of edge punctuation. This permits casing/punctuation/whitespace corrections, not
arbitrary replacement/reordering just because word counts match. Ambiguous segments
are omitted with `ambiguous_text_timing`; there is no raw-ASR fallback. Empty
effective text produces no captions. No raw data is changed.

Raw times are WAV-relative. The verified Phase 06 `audio_offset` shifts them into
proxy time; this is clock conversion, not inferred alignment. Intersecting words
are omitted without clipping. Existing Phase 06 mapping helpers convert surviving
caption endpoints into edited time, including the splice endpoint convention.
Pending/rejected proposals never shorten caption timing.

The browser compares `video.currentTime` with `original_start/original_end`,
not edited timestamps. Half-open intervals hide captions in gaps, at ends and
during accepted removals. Seeking updates the overlay immediately. Caption state
reloads after job changes, transcript saves/resets and cut decisions. Old snapshots
are hidden while reloading; stale plans require Generate captions. Reload captions
and full page refresh retrieve persisted data. Other clients' changes need a reload.
Native video fullscreen may exclude the separate HTML overlay; use inline playback.

### API, cache and publication

- POST `/projects/{id}/jobs`: `{"stage":"plan"}`.
- Optional settings patch: `{"stage":"plan","caption_settings":{"max_words":4}}`.
  The job stores the fully resolved settings and retry retains them. The UI uses defaults.
- GET `/projects/{id}/captions`: validated current plan, or a readable error.
- Existing latest/read/cancel/retry endpoints remain unchanged; render is rejected.

Writes require `X-Media-Import: 1` and the local-origin guard. Plan progress is
.05 inputs, .8 ready, .9 publication, 1 success; it is not a time estimate.
Only `analysis/captions.json` and normal jobs/logs are written.
The canonical artifact is atomically published with the existing unique sibling,
flush/fsync and rename utility. Failures preserve previous complete bytes; an old
artifact is not served as current when its inputs no longer match.

Cache identity includes raw transcript checksum, effective-text checksum, accepted
removal topology/source duration/audio offset, settings, schema and planner version.
Pending → rejected alone is a cache hit; accepting a removal or changing effective
text invalidates it. Reads and cache checks reconstruct the expected pure plan, so
even well-formed modified output is not trusted. This favors integrity over avoiding
the inexpensive grouping computation. Full media hashing can still take time.
No generated-at clock, random ID or proposal-only decision state affects the plan.
Exact fields and warnings are documented in `docs/data-contracts.md`.

### Verification and manual acceptance

Run the existing complete verification matrix, plus the Phase 07 harness:

```sh
.venv/bin/python scripts/smoke_test.py
(cd apps/api && ../../.venv/bin/python -m unittest discover -s tests -v)
npm --prefix apps/web test
npm --prefix apps/web run build
.venv/bin/python scripts/doctor.py
.venv/bin/python scripts/doctor.py --phase01
.venv/bin/python scripts/doctor.py --phase02
.venv/bin/python scripts/doctor.py --phase04
git diff --check
```

Open `/tests/review.html`, `/tests/cuts.html`, and `/tests/captions.html`
on the Vite server; all must show **ALL PASSED**. They use isolated mock state
and never modify real project artifacts. The complete backend suite also covers
Phase 02 real FFmpeg media, Phase 03 crash/recovery and Phase 04–06 regressions.

1. Restart the existing backend (do not run a second against the same runtime):
   `.venv/bin/python -m uvicorn app.main:app --app-dir apps/api --host 127.0.0.1 --port 8000`.
   Start/keep `npm --prefix apps/web run dev`. Open `http://127.0.0.1:5173`.
2. Select the previously transcribed spoken project. Preserve its current corrections
   and decisions. Record SHA-256 hashes of source, proxy, WAV, transcript, cuts,
   metadata, project.json and both overrides if present; record absent overrides too.
3. Click **Generate captions**. Require `plan — succeeded`, a group count and any
   readable warnings. Inspect `analysis/captions.json` and GET its endpoint.
4. Play inline. Check readable groups and approximate speech synchronization.
   Pause and use raw-word/segment seek buttons; verify the appropriate overlay or
   no overlay. The pre-existing transcript seek is WAV-relative; for nonzero offsets
   a seek can precede the caption slightly until proxy playback reaches it.
5. Seek before, inside and after the already accepted cut. Captions must disappear
   inside it. Downstream edited caption times shorten by cumulative accepted cuts;
   original proxy duration and caption activation remain unchanged.
6. Seek past the last caption and into a gap: no overlay. Refresh the page, seek again
   and confirm persisted plan/warnings. Click **Generate captions** again: require
   reused artifacts and unchanged caption bytes.
7. Verify all protected hashes and file-presence states from step 2 are unchanged.
   Exercise correction/cut invalidation with the isolated harnesses/tests, not by
   altering real artifacts just for verification.
8. Manually assess readability/speech timing before approving Phase 07. No commit,
   push, merge, tag or Phase 08 work is authorized by implementation completion.

Known limits: approximate ASR timing, conservative lexical mapping, no forced
realignment, whitespace-oriented token matching when exact chunk reconstruction
does not apply, max-word counts based on timed source entries, no cross-segment
minimum-duration merge, possible short genuine intervals with warnings, no edited
playback or export, and browser event-rate rather than frame-perfect activation.

## Phase 08A voice delivery features

POST `/projects/{id}/jobs` with `{"stage":"audio_features"}` runs the dedicated
Phase 08A stage; Smart Cuts keeps the existing `analyze` stage. GET
`/projects/{id}/audio-features` returns the current validated
`analysis/audio_features.json`. Both endpoints reuse the Phase 03 project
resolution, job exclusion, retry/recovery and error behavior. The extractor reads
only the verified mono 16 kHz PCM16 `normalized/audio.wav` and the raw Phase 04
transcript. Corrections, cut decisions and caption grouping never participate.

For each usable authoritative `[start,end)` word interval, sample indices are
`floor(start*16000)` through `ceil(end*16000)`, bounded to the WAV. PCM values are
scaled by 32768 and RMS is `sqrt(mean(sample²))`; dBFS uses a -120 dB numerical
floor. Project energy normalization linearly maps interpolated P10/P90 word dBFS
to 0..1 and clamps. Equal non-floor energies use neutral 0.5; all floor-energy
words use 0.0. Raw RMS/dBFS remain present. `relative_energy_db` compares a word
with the median of up to five valid words on each side.

Duration is exactly `end-start`. `relative_duration` divides it by the same local
neighbor median, uses 1.0 for a lone word, and caps at 4.0. Pauses are gaps between
adjacent valid authoritative words. Negative gaps are never made positive: they
become zero, and overlaps beyond 1 ms warn. First/last unavailable pauses are null.
Missing or invalid word timing produces an explicit invalid record and structured
warning without inferred alignment. Empty transcripts are valid. PCM clipping is
reported per word, and valid Phase 04 word confidence is preserved as provenance.
JSON validation rejects all NaN and infinities.

Cache identity contains schema/extractor versions, exact settings, normalized WAV
SHA-256, raw transcript checksum and a canonical timing checksum. Word IDs hash the
timing checksum, segment/word indices and exact bounds. Phase 05 text overlays,
Phase 06 decisions and Phase 07 grouping cannot invalidate the artifact. Publication
uses the existing flushed/fsynced temporary sibling and atomic replacement; failure
preserves the previous artifact. Known limitations: one project is treated as one
recording population; there is no speaker separation, pitch, emotion, semantics,
re-alignment, caption policy or animation.

### Phase 07 acceptance — approved

The user confirmed real proxy captions are short, readable and approximately
synchronized with speech. Seeking updates the active caption immediately; gaps
and accepted removed intervals show no caption. Refresh restores the plan.
The preview uses original proxy time while items retain both original and edited
bounds. Only accepted cuts shorten edited timing; pending/rejected cuts do not.

Safely mapped corrected text displays as intended. Ambiguous corrections are
omitted with readable warnings; authoritative Phase 04 word times remain unchanged
and no alignment is fabricated. Protected media, raw transcript and generated cuts
remain unchanged; override changes were limited to intentional manual testing and
existing decisions. Phases 00–06 remain intact. No rendered video exists.

The user explicitly authorized Phase 07 commit, feature/main pushes, merge and
annotated stable tag. This acceptance does not authorize Phase 08 or rendering.

## Phase 08B — Bounded Voice-Reactive Emphasis Policy

POST `/projects/{id}/jobs` with `{"stage":"emphasis"}` after current captions and
audio features exist. GET `/projects/{id}/emphasis` returns the validated separate
`analysis/emphasis.json`. Optional `emphasis_settings` are expanded, stored on the
job and retained on retry. The browser may show a static diagnostic word, behavior,
score and signals; it does not animate or render captions.

Caption words join to feature words only by `(segment_id, word_index)`, matching raw
transcript identity, and exact source bounds after the Phase 07 audio offset. Missing,
invalid or mismatched records warn and receive no decision. Display text is never
matched or realigned, and omitted Phase 07 words cannot be resurrected.

```text
relative_energy = clamp(relative_energy_db / 6, 0, 1)
energy = 0.60 * normalized_energy + 0.40 * relative_energy
pause = max(clamp(pause_before / 0.75), clamp(pause_after / 0.75))
duration = clamp((relative_duration - 1.0) / 1.5, 0, 1)
score = clamp(0.50 * energy + 0.30 * pause + 0.20 * duration, 0, 1)
```

Below 0.35 selects `none`; 0.35–0.62 and 0.62–0.72 select `subtle`. A strong shape
requires score ≥0.72. Deterministic priority is `punch` > `hold` > `pop` > `subtle`
> `none`: score ≥0.85 with two components ≥0.65 selects `punch`; otherwise duration
≥0.75 selects `hold`; otherwise energy ≥0.75 selects `pop`. Only those three labels are
strong. At most one source word per caption can be strong. Strong events require
1.5 seconds since the previous approved event and no more than two events in a rolling
eight-second window. Suppressed candidates become subtle while retaining evidence.

`reactive_enabled:false` produces a provenance-bound artifact with no decisions or
aggregates and does not change captions, timings or earlier artifacts. Cache identity
includes schema/policy versions, both source artifact checksums and expanded settings.
Publication is atomic. Limitations: delivery-only evidence and project-relative
loudness; no pitch, semantics, emotion, speaker separation, animation or renderer data.
