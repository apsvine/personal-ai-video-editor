# Personal AI Video Editor

A private, local-first AI video editing application for one user. V1 will
target talking-head vertical videos. The current phase is **Phase 01: Local App
Shell**, built on the preserved Phase 00 foundation. It is not a video editor yet.

## North-star workflow

Record → Drop Footage → Analyze → Generate Edit → Review → Export

This is a future workflow, not functionality available today.

## Intended architecture

React + TypeScript + Vite provide a minimal local status page, with a Python
3.11 + FastAPI backend providing `GET /health`. In future phases, FFmpeg will
handle media operations; a transcription provider
abstraction and Python edit planner will produce reusable JSON artifacts.
Remotion rendering comes later. Electron packaging comes only after the
pipeline is stable. Only the status page and health API are implemented.
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

## Phase 01 setup and local development

Prerequisites: **Python 3.11**, Node **20.19.x or newer 20.x, or 22.12+**, and npm.
These Node constraints follow the [Vite requirements](https://vite.dev/guide/).
Use a maintained Node release. Python 3.11 is the backend target even if another
Python version is your system default. No FFmpeg, models, API keys, or database
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
“Phase 01 — Local App Shell”, and “API Status: Connected” when the API returns
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
and `http://localhost:5173`, with GET and no credentials. Ports are fixed;
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
```

Backend tests use standard-library `unittest` with FastAPI's
[TestClient](https://fastapi.tiangolo.com/tutorial/testing/) and HTTPX. They check
the health JSON, permitted local origins, excluded external origins, and GET-only
behavior. The frontend build runs strict TypeScript checks before Vite.
No frontend unit-test framework is added for this three-line page.

To preview the production build locally, stop the Vite development server,
keep the API running, and run `npm --prefix apps/web run preview`. Preview uses
the same loopback port 5173 so the CORS policy remains unchanged.

Manual checks: open the page, confirm Connected, stop the API and wait up to
eight seconds for Disconnected, then restart it and confirm recovery. There
should be no upload, sidebar, timeline, or editing controls.

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
mode installs anything; FFmpeg and ffprobe are still optional warnings.

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

There is no video import, transcription, AI functionality, edit planning,
captions, rendering, database, authentication, or desktop packaging.
Remotion and Electron are not installed. No models or media are bundled.
The shell performs health checks only. Phase 02 must be requested separately.
