# Development rules

- Read `README.md` and this file before any modification.
- Inspect the repository, Git status, and relevant files before editing.
- Identify the files to change and keep changes within the requested scope.
- Implement exactly one requested phase per task. Current phase: **00**.
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

## Phase 00 boundary

Only repository structure, documentation, lightweight diagnostics, cleanup,
and a minimal health test belong here. Do not implement application behavior,
video import, transcription, AI, captions, or rendering. Do not install Remotion,
Electron, databases, or large dependencies. Future architecture documentation
does not authorize implementation.
