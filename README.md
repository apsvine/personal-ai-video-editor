# Personal AI Video Editor

A private, local-first AI video editing application for one user. V1 will
target talking-head vertical videos. This repository currently contains only
**Phase 00: Repository Foundation**; it is not a working video editor.

## North-star workflow

Record → Drop Footage → Analyze → Generate Edit → Review → Export

This is a future workflow, not functionality available today.

## Intended architecture

React + TypeScript will provide the local web interface, with a Python +
FastAPI backend. FFmpeg will handle media operations; a transcription provider
abstraction and Python edit planner will produce reusable JSON artifacts.
Remotion rendering comes later. Electron packaging comes only after the
pipeline is stable. No part of this application stack is installed or
implemented in Phase 00. See [architecture](docs/architecture.md),
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
│   ├── web/
│   └── api/
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

## Phase 00 setup

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
Node, npm, FFmpeg, and ffprobe are optional in Phase 00.

Cleanup defaults to a dry run. `python scripts/clean_temp.py --apply` deletes
regular files only inside `runtime/temp`; it leaves directories and symlinks
alone and never touches projects, cache, or logs. Do not run cleanup concurrently
with other processes writing temporary files.

`.env.example` is a safe placeholder; copying it is optional. No utility loads
`.env` automatically. Frontend/backend startup commands, dependency manifests,
provider configuration, and installation steps are deferred to their phases.

## Development philosophy

Read this file and `AGENTS.md` before changing anything. Work one phase at a
time, keep dependencies minimal, preserve passing behavior, and test each
change. Prefer explicit versioned artifacts that can be inspected and reused
after failures. Keep user data local by default; any future external provider
must require an explicit user choice. Do not assume prior chat context.

## Explicitly not built yet

There is no video import, transcription, AI functionality, edit planning,
captions, rendering, database, web/API application, or desktop packaging.
Remotion and Electron are not installed. No models or media are bundled.
Phase 01 must be requested separately.
