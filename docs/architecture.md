# Intended architecture — not implemented

Phase 00 establishes repository boundaries only. These are future directions,
not installed dependencies, working services, or permission to start a later phase.

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
No database or application dependency is introduced in Phase 00.
