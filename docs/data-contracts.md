# Phase 03 data contracts (preserving Phase 02 artifacts)

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
plan, captions, rendering or provider payload schema is implemented.

## jobs/<job-id>.json (Phase 03)

Each job ID is 32 lowercase hexadecimal characters. All records contain:

- `schema_version: 1`, `job_id`, `project_id` (the retained source project).
- `stage`: contract names `normalize`, `transcribe`, `analyze`, `plan`, `render`.
  Only `normalize` can be created/executed today; other names have no handlers.
- `status`: `pending`, `running`, `succeeded`, `failed`, `cancelled`, `interrupted`.
- `progress`: finite numeric value in [0.0, 1.0]; 1.0 on success.
  Milestones: 0 pending, .05 setup/hash/cache, .15 probe, .25 proxy, .65 audio,
  .90 publication, 1 success. Cache hits skip unnecessary work.
- `created_at`: UTC ISO timestamp; nullable `started_at` and `finished_at`.
- `error`: null or `{code, message, ...optional details}`. Codes include
  `cancelled`, `backend_interrupted`, `job_failed`, and existing media errors.
- `log_path`: project-relative `logs/job-<id>.log`; job exception details and a
  reference to `logs/media.log` for subprocess diagnostics. Never served by API.
- `retry_of`: null or the original attempt's job ID. Retrying never rewrites
  the original record and creates fresh timestamps/progress/error fields.
- `result_project_id`: null until success, then the completed output project;
  it can differ from `project_id` on cache reuse. `reused` is a boolean.

Normal transitions: pending → running → succeeded / failed / cancelled.
Restart/shutdown transitions: pending/running → interrupted. Terminal records
are retained. Retry is permitted only for failed/interrupted/cancelled records.
Cancellation is acknowledged with HTTP 202 but does not claim completion until
cleanup finishes; poll for terminal status. A cancellation arriving after media
publication may lose the race to success. Jobs describe orchestration; the
existing `project.json` normalization status still describes artifact readiness.
An interrupted/cancelled attempt may leave project status `failed` or an old
in-progress stage. Never infer job lifecycle from project status.

Job/project JSON is written using a unique sibling temporary file, flushed and
fsynced, then atomically replaced. Readers see old or new complete JSON. Unique
names avoid crash leftovers blocking retries; old JSON temporary files from a
hard crash may remain for manual cleanup while idle. No multi-record transaction
is claimed. On restart, even an unpublished success is marked interrupted; retry
then checks completed media and reuses it if verified. Media formats, checksums,
and completion marker semantics remain unchanged.

Latest-job lookup returns the newest `created_at`, or JSON null. Upload with
`?background=true` returns a job and HTTP 202 once source persistence completes;
the default synchronous response still returns the completed/cached project.
All job writes require the same local-origin/custom-header guard as uploads.
Unsupported future stages cannot be requested. Busy operations return
`{error: {code: "job_busy", message: "..."}}` with HTTP 409 and no queued job.
