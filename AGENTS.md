# Development rules

- Read `README.md` and this file before any modification.
- Inspect the repository, Git status, and relevant files before editing.
- Identify the files to change and keep changes within the requested scope.
- Implement exactly one requested phase per task. Current phase: **04**.
- Never silently implement future phases; stop when the requested phase is complete.
- Do not refactor unrelated files or overwrite user changes.
- Add no dependency without an explicit justification; prefer the standard library.
- Preserve previous passing behavior. Do not weaken tests to hide regressions.
- Always run tests: `python scripts/smoke_test.py` (or `python3`). Run the doctor
  when changing environment or foundation behavior. Report blocked checks honestly.
- Keep secrets, private recordings, generated artifacts, models, and runtime
  data out of Git. Runtime directories are generated locally, with no tracked placeholders.
- Fixtures must be tiny, intentional, and checked for privacy before committing.
- Report changed files, commands/tests executed, results, warnings, limitations,
  and anything the user must manually verify.
- Do not commit or push unless explicitly requested.

## Historical Phase 01 boundary (superseded only by approved Phases 02–04)

Preserve all Phase 00 utilities and checks. Phase 01 adds only a local React +
TypeScript + Vite status page and Python 3.11 + FastAPI `GET /health` API.
Keep both servers on loopback and CORS restricted to the local frontend.
Run backend tests from `apps/api` with `../../.venv/bin/python -m unittest discover -s tests -v`,
and run `npm run build` from `apps/web`. Also run the foundation smoke test
and both default and `--phase01` doctor modes.
Do not implement uploads, video import/preview, processing, transcription,
AI, captions, rendering, authentication, databases, or desktop packaging.
Do not install media libraries, Remotion, Electron, or AI SDKs. Stop at Phase 01;
future architecture documentation does not authorize later implementation.

## Phase 04 boundary

Only normalize/transcribe jobs execute. Canonical transcript: analysis/transcript.json.
Use faster-whisper==1.2.1, multilingual base, CPU INT8. No model acquisition during
startup/import/tests/doctor. Acquisition is a separate explicit user approval.
Shared controls belong in python/common; normalization keeps compatible imports.
No Phase 05 features, other providers, diarization, captions, editing, or rendering.
Run all existing checks and --phase04 doctor. Missing model is WARN, not FAIL.
