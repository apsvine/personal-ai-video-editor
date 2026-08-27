# Phase 02 data contracts

All implemented JSON schemas use integer `schema_version: 1`. Files live at
`runtime/projects/<32 lowercase hex characters>/`; runtime is never tracked.

## project.json

- `project_id`, UTC ISO `created_at`, `schema_version`.
- `source`: original `filename`, `size_bytes`, client `last_modified_ms` (nullable),
  and `sha256` added after upload. The original client file is never modified;
  the byte-identical uploaded source copy is the immutable processing input.
- `configuration`: `h264-aac-720-fit-cfr30-mono16k-v1`; changing normalization
  settings must change this cache identity.
- `normalization_status`: `awaiting_upload`, `uploading`, `uploaded`, `inspecting`,
  `creating_proxy`, `extracting_audio`, `completed`, `reused`, or `failed`.
- Completed projects contain `audio_status` (`available` or `no_audio`) and
  `outputs`, mapping normalized filenames to SHA-256 checksums.
- Reused imports contain `reused_project_id`; their upload response returns the
  completed target project and `reused: true`. New success returns `reused: false`.
- Failed projects contain `error: {code, message, ...optional details}`.

`source/<filename>` contains the retained source; paths/filenames reject traversal
and runtime symlinks. No arbitrary filesystem path is accepted over the API.

## normalized/metadata.json

`schema_version`, `duration_seconds`, source `width`, `height`, numeric
`frame_rate`, `video_codec`, `video_stream_index`, `rotation_degrees`,
`audio_codec`, `audio_sample_rate`, `audio_channels`, `audio_stream_index`,
`audio_status`, and the same `source` fingerprint record. Audio fields are null
when absent. Dimensions describe the encoded source, before display rotation;
the preview may have different dimensions. Rotation is FFprobe's reported
rotation value, not a separate frontend transform. No full probe dump is embedded.

## Media and publication

`normalized/proxy.mp4`: 30 fps CFR H.264/yuv420p + AAC when present, fast-start,
aspect-preserving landscape 1280x720 / portrait 720x1280 bounds; smaller sources
are not upscaled for the bounding box. Pixel aspect ratio is normalized first.
`normalized/audio.wav`: mono, PCM signed 16-bit, 16 kHz; absent for `no_audio`.
`logs/media.log`: local detailed tool stdout/stderr and readable failures.

JSON uses a temporary sibling and atomic rename. Media uses `proxy.tmp.mp4`
and `audio.tmp.wav`; all commands must succeed and outputs must be nonempty
before final names are published. Only a completed `project.json` makes an
output set consumable. Handled failures remove normalized final/temp outputs.
Abrupt termination can leave an unfinished project, never a reusable success.
Reuse requires matching schema, configuration, source checksum, and every
expected output checksum; source/output corruption invalidates the cache.

## Future contracts (not implemented)

Later stages should use versioned JSON artifacts, explicit provenance and input
identity, atomic publication and scoped invalidation. No transcription, edit
plan, captions, jobs, rendering or provider schema is defined by Phase 02.
