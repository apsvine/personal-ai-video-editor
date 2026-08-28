# Phase 06 data contracts (preserving Phase 02–05 artifacts)

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
identity, atomic publication and scoped invalidation. Only the Phase 06 silence proposal schema below is implemented; captions and rendering remain future work. The Phase 04 transcript
schema is below.

## jobs/<job-id>.json (Phase 03)

Each job ID is 32 lowercase hexadecimal characters. All records contain:

- `schema_version: 1`, `job_id`, `project_id` (the retained source project).
- `stage`: contract names `normalize`, `transcribe`, `analyze`, `plan`, `render`.
  Only `normalize`, `transcribe` and `analyze` can execute; `plan` and `render` have no handlers.
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
Unsupported future stages cannot be requested. Requests default to normalize;
`{"stage":"transcribe"}` selects transcription. Retry preserves the stage. Busy operations return
`{error: {code: "job_busy", message: "..."}}` with HTTP 409 and no queued job.

## analysis/transcript.json (Phase 04)

The directory is created on demand on the completed output project, including
when requested via a reused import. This artifact is independent of project.json's
normalization commit marker. The old transcript survives any failed replacement.
Publication is a flushed/fsynced unique sibling followed by atomic replacement.

- schema_version: integer 1.
- content_checksum: SHA-256 of canonical sorted compact JSON excluding this field;
  detects accidental content corruption (not a security signature).
- language: provider-detected language code.
- timing_quality: "model_estimated_word_alignment". Word boundaries come from
  Whisper alignment, not interpolated segment divisions. They are estimates, not
  guaranteed frame/sample-accurate boundaries. No rounding or synthetic confidence.
- source: audio_checksum (SHA-256 of normalized/audio.wav), source_checksum
  (SHA-256 of the original uploaded source).
- provider: name "faster-whisper", version "1.2.1", model "base", model_checksum
  (SHA-256 over sorted local model filenames and their SHA-256 digests), settings.
- settings: device cpu, compute_type int8, cpu_threads 4, num_workers 1,
  beam_size 5, word_timestamps true, vad_filter false.
- segments: ordered objects with start/end seconds relative to normalized audio,
  text, confidence null, and words. Each word has text/start/end/confidence; word
  confidence is the provider's word probability, not a calibrated accuracy claim.
  Segment average log probability is deliberately not represented as confidence.
- Empty segments is a valid no-speech result, distinct from a video without audio.

All intervals must be finite, nonnegative, ordered, contained in their parent and
within audio duration. Nonempty speech segments require words. Invalid outputs
fail instead of silently clamping or manufacturing alignment. Cache identity
includes schema/source/provider/version/model content/settings. Cache hits validate
the artifact and do not construct a model; model files are still hashed. Missing
local models are setup errors, even when an older transcript remains readable.
Transcription never changes normalized output checksums or removes old transcripts.

API: POST /projects/{id}/jobs with {"stage":"transcribe"} returns 202; existing
job read/latest/cancel/retry endpoints apply. GET /projects/{id}/transcript returns
the validated artifact or structured transcript_not_ready (404). Normalization
prerequisite errors use 409. All writes retain the existing local-origin/header guard.
The transcript read endpoint checks source integrity but can return a prior valid
transcript after a failed attempt with different settings; its provenance is included.

Progress is coarse: .05 prerequisite verification, .15 inference, .90 validation
and publication, 1 success. It is not a time estimate; it can remain at .15 for the
whole inference. Retry starts fresh inference unless a valid published cache exists.

### Aligned segment envelopes

Before publication, internal segment start is the minimum of the provider segment
start and all aligned word starts; end is the maximum of the provider segment end
and all aligned word ends. Word timestamps/confidences are preserved verbatim.
Wordless segments retain provider bounds and existing validation requirements.
No padding, clamping, tolerance or synthetic timing is added. Strict finite,
nonnegative, duration-bound, interval and cross-segment ordering checks still apply
after envelope derivation. Invalid or overlapping final intervals still fail.


## overrides/user_transcript.json (Phase 05)

Review operations never mutate `analysis/transcript.json`. Overrides belong to the
completed output project, including when requested through a reused import:

```json
{
  "schema_version": 1,
  "project_id": "<32 lowercase hex output project ID>",
  "source_transcript_checksum": "<raw content_checksum: 64 lowercase hex>",
  "segments": {
    "0": { "text": "Corrected segment text" }
  }
}
```

Only the four shown top-level keys are accepted. Version is integer 1, not boolean.
Segment keys are canonical zero-based decimal indices (`0`, `1`, ...; no signs or
leading zeroes), validated against the current raw segment count after checksum
validation. Each value contains only `text`: a valid UTF-8 string up to 10,000
characters, allowing empty strings but not NUL or unpaired Unicode surrogates.
No timing, words, confidence, provider or other raw fields are copied into overrides.
The artifact contains only corrections; saving original text removes an entry.

Identity is the Phase 04 canonical JSON SHA-256 `content_checksum`, **not** a hash of
serialized file bytes. Whitespace/key-order changes alone do not change identity.
Segment index plus this checksum is a deterministic reference across refreshes.
A valid changed raw transcript invalidates the entire old override document; there
is no semantic migration. Invalid raw transcripts remain unavailable through the
existing Phase 04 validation, rather than becoming new identities.

### Review API

All endpoints are beneath `/projects/{id}/transcript`:

| Method | Suffix | Body / result |
| --- | --- | --- |
| GET | (none) | Unchanged Phase 04 raw artifact |
| GET | `/review` | Merged review representation below |
| PUT | `/overrides/{segment_id}` | `{source_transcript_checksum, text}`; returns merged review |
| POST | `/overrides/{segment_id}/reset` | `{source_transcript_checksum}`; returns merged review |
| POST | `/overrides/reset` | `{source_transcript_checksum}`; resets all, returns merged review |

Write bodies forbid extra keys, including attempted timestamp edits. Writes require
`X-Media-Import: 1` and the same local-origin guard as existing APIs. Project IDs
and all paths use the existing traversal/symlink protections. No arbitrary path is
accepted. Project, normalized source integrity and raw transcript are validated
before access. Missing projects/transcripts return 404; prerequisite failures 409;
invalid segments/text/request schemas 422; foreign/missing write guard 403;
failed storage writes produce readable `override_write_failed` (500).

A merged response contains `schema_version: 1`, resolved `project_id`,
`source_transcript_checksum`, `language`, `timing_quality`, `override_state`,
`override_message` (nullable), and `segments`. Each segment retains all raw fields
and timing/words verbatim, adds `segment_id`, `raw_text`, `edited`, and replaces
only `text` when a valid override applies. This view is not a replacement ASR
artifact and has no independent `content_checksum`.

`override_state` is `none`, `applied`, `stale`, or `invalid`. `stale` means a valid
schema references a different raw checksum; `invalid` means unreadable/malformed
JSON or invalid schema/segment references. Both return HTTP 200 with readable
`override_message` and **only raw text**, leaving the override file untouched.
Raw GET remains readable. Saves/segment resets in these states return 409
`override_stale` / `override_invalid`; Reset All can discard them using the current
raw checksum. An outdated request checksum returns 409 `transcript_changed` without
writing; reload review first. A busy heavy-operation reservation returns 409
`job_busy` without changes.

Publication uses unique temporary siblings, flush/fsync and atomic rename, exactly
as existing artifact writes; failed publication leaves the old complete file.
Reset Segment removes one entry; Reset All or removal of the final entry safely
unlinks the file. Reset All is idempotent when no file exists. No raw timestamps
or text are changed. Unlink does not claim additional power-loss durability beyond
the existing filesystem semantics.

### Review seeking semantics

Segment clicks seek to raw `start`; raw word clicks seek to their own validated
`start`. Active intervals are `[start, end)` in proxy playback seconds; gaps and
end-of-transcript have no active segment. Seeking never writes transcript data.
Missing/invalid word lists use segment-only seeking; Phase 04 still rejects speech
segments without alignment. Corrected text uses segment seeking, while original
ASR words remain available separately. No new alignment is inferred from edits.


## analysis/cuts.json (Phase 06)

The exact top-level structure is shown below (hashes/values are illustrative):

```json
{
  "schema_version": 1,
  "project_id": "<completed-output-project-id>",
  "source": {
    "source_checksum": "<source SHA-256>",
    "audio_checksum": "<WAV SHA-256>",
    "transcript_checksum": "<raw transcript content_checksum>",
    "timing_checksum": "<canonical segment/word interval SHA-256>"
  },
  "source_duration": 10.0,
  "audio_duration": 10.0,
  "audio_offset": 0.0,
  "settings": {"threshold_db": -40, "min_silence": 0.8, "padding": 0.2, "min_cut": 0.3},
  "planner": "silence-word-protection-v1",
  "detector": {"name": "ffmpeg.silencedetect", "version": "<ffmpeg -version first line>"},
  "time_basis": "normalized_proxy_seconds",
  "topology_scope": "proposal",
  "candidates": [{
    "cut_id": "<deterministic SHA-256>",
    "start": 2.2, "end": 3.8, "reason": "silence",
    "silence_start": 2.0, "silence_end": 4.0
  }],
  "keep": [{"start": 0.0, "end": 2.2}, {"start": 3.8, "end": 10.0}],
  "removed": [{"start": 2.2, "end": 3.8}],
  "warnings": ["ASR timing is estimated. Listen at every proposed boundary before accepting."],
  "content_checksum": "<canonical JSON SHA-256 excluding this field>"
}
```

All candidate/keep/removed times are half-open intervals in seconds on the original
normalized proxy timeline. `silence_start`/`silence_end` are detector evidence in
WAV time, before adding `audio_offset`. The raw transcript also remains in WAV time.
`source_duration` is the proxy presentation duration, not source container duration.
`audio_duration` is exact WAV frame count / 16000. Bounds are finite and positive;
interval sets are sorted, non-overlapping and cover the full source domain together.
Candidate endpoints round inward to microseconds, never out into protected speech.
Empty proposals mean `removed: []` and full-duration `keep`. No-speech raw transcripts
add a human-review warning; they never trigger automatic acceptance.

**Proposal topology is not an approved effective timeline.** Generated `removed`
contains all candidate intervals and generated `keep` is its deterministic complement.
No future consumer needs to reconstruct this topology from opaque metadata, but it
must use the review/effective plan when honoring user decisions.

`cut_id` hashes canonical sorted compact JSON containing the full planner identity
(all top-level fields through `topology_scope`, including source hashes, timing hash,
settings, versions, durations, offset and output project ID) plus candidate start/end.
No UUID or wall-clock field participates. The timing hash uses raw segment envelopes
and word start/end arrays, without text. The full transcript checksum also binds
provenance/text/confidence, conservatively invalidating plans if any raw content changes.
Phase 05 text overrides never participate. Identical inputs/settings yield identical
IDs, topology and artifact bytes. Input/settings/tool/planner changes invalidate cache.

Read validation checks normalized source/output hashes and the validated raw
transcript, then reconstructs candidate IDs, protection and topology from recorded
evidence. Corrupt or stale generated artifacts return `cuts_not_ready` (404).
Regeneration may atomically replace a prior artifact for changed inputs; failed
replacement preserves it. After publication, review decisions never modify it.
There is no implicit in-place acceptance flag, duplicated effective artifact or render.

## overrides/user_cuts.json (Phase 06)

Exactly these keys are accepted:

```json
{
  "schema_version": 1,
  "project_id": "<completed-output-project-id>",
  "source_cuts_checksum": "<generated content_checksum>",
  "decisions": {"<64 lowercase hexadecimal cut_id>": {"action": "accept"}}
}
```

Version must be integer 1, not boolean. IDs/checksums use lowercase SHA-256 hex.
Actions are only `accept` and `reject`; no timestamps or other fields are allowed.
Only decisions are persisted, and missing entries mean pending. Reset removes an
entry; reset-all or removing the last entry unlinks this one override file. Source,
proxy, audio, transcript and transcript overrides are never changed by these APIs.

The raw GET `/projects/{id}/cuts` is independent of decision validity. GET
`/projects/{id}/cuts/review` returns exactly `schema_version`, `project_id`,
`source_cuts_checksum`, `override_state`, `override_message`, `warnings`, `candidates`
and `effective`. Each candidate retains generated fields plus `decision`
(`pending`, `accept`, `reject`). `override_state` is `none`, `applied`, `stale`, or
`invalid`; stale/invalid states return a diagnostic and withhold all decisions.
Only current explicit accepts enter `effective.removed`; pending/rejected remain kept.

`effective` contains `source_duration`, `effective_duration`, `time_removed`, `keep`,
`removed` and `mapping`. Each mapping entry contains `original_start`, `original_end`,
`edited_start`, `edited_end`. These are derived in memory, not a third persisted file.
With zero accepted cuts, the effective map is identity and removed time is zero.

Writes use the checksum-bound PUT/reset API described in README. Unknown candidates
and malformed requests return 422; outdated checksums return 409 `cuts_changed`;
stale/invalid decision files block per-candidate writes with 409 until Reset All.
Reset All uses current generated identity and can discard malformed/stale decisions.
Missing guards/foreign origins return 403; busy reservation returns 409 `job_busy`;
storage failure returns 500 `cut_override_write_failed`. Same-candidate saves are
last-successful-save-wins; different-candidate saves preserve each other's decisions.
External file mutation while a backend runs is unsupported. No migration is implied.

### Pure Python time mapping

`python.editing.cuts.mapping(duration, removed)` derives retained spans and offsets.
`original_to_edited(duration, removed, time)` returns either
`{"removed": false, "edited_time": number}` or
`{"removed": true, "splice_time": number}`. It never claims a removed timestamp
survived. `edited_to_original(duration, removed, time)` returns `{"original_time": number}`.
At an internal splice the inverse chooses the next retained interval (right-continuous).
At the final edited endpoint it returns original duration, including trailing removals.
For a fully removed generic timeline, the only edited time 0 maps to original duration;
normal silence proposals retain edge padding. Negative, nonfinite, boolean and
out-of-range query times are rejected. Adjacent removal intervals are supported.
Round trips apply within retained intervals; removed spans collapse and are not invertible.
This logic has no frontend dependency and performs no media operation.
