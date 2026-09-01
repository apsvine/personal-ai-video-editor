# Phase 07 data contracts (preserving Phase 02–06 artifacts)

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
identity, atomic publication and scoped invalidation. The Phase 06 silence and Phase 07 caption schemas below are implemented; rendering remains future work. The Phase 04 transcript
schema is below.

## jobs/<job-id>.json (Phase 03)

Each job ID is 32 lowercase hexadecimal characters. All records contain:

- `schema_version: 1`, `job_id`, `project_id` (the retained source project).
- `stage`: contract names `normalize`, `transcribe`, `analyze`, `audio_features`,
  `plan`, `render`. All except future `render` can execute; `analyze` remains Smart
  Cuts and `audio_features` is the independent Phase 08A extractor.
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

## analysis/captions.json (Phase 07)

Exactly these top-level fields are published. Placeholder digests below represent
64 lowercase SHA-256 hex characters; real IDs contain the full digest.

```json
{
  "schema_version": 1,
  "project_id": "<completed output project ID>",
  "planner_version": "genuine-word-captions-v1",
  "raw_transcript_checksum": "<raw content_checksum>",
  "effective_transcript_checksum": "<canonical effective texts digest>",
  "effective_cut_checksum": "<accepted topology/clock digest>",
  "settings": {
    "max_words": 5,
    "max_characters": 42,
    "pause_threshold": 0.5,
    "minimum_duration": 0.7,
    "maximum_duration": 3.0,
    "punctuation_break": true
  },
  "source_duration": 10.0,
  "audio_offset": 0.0,
  "removed": [{"start": 2.0, "end": 3.0}],
  "items": [{
    "original_start": 4.0,
    "original_end": 4.8,
    "edited_start": 3.0,
    "edited_end": 3.8,
    "text": "BINARY SEARCH",
    "words": [
      {"segment_id": "0", "word_index": 0, "text": "BINARY", "joiner": " ",
       "original_start": 4.0, "original_end": 4.3},
      {"segment_id": "0", "word_index": 1, "text": "SEARCH", "joiner": " ",
       "original_start": 4.4, "original_end": 4.8}
    ],
    "layout": "center",
    "behavior": "normal",
    "emphasis": 0.0,
    "caption_id": "caption-<deterministic SHA-256>"
  }],
  "warnings": [],
  "content_checksum": "<canonical complete artifact digest>"
}
```

All intervals are finite half-open seconds. Original intervals are on the normalized
proxy clock, not necessarily WAV zero: `raw_time + audio_offset`. The verified Phase
06 offset is retained, never estimated again. The accepted-only `removed` snapshot
is included for consumer safety; it is not generated proposal topology. No caption
may intersect it. Edited endpoints use existing Phase 06 helpers. A caption ending
exactly at a cut start uses that helper's splice time for its exclusive endpoint.

`words` references the authoritative `segments[int(segment_id)].words[word_index]`.
The reference pair is valid only with `raw_transcript_checksum`. Its original bounds
are the exact raw bounds plus the clock offset. Text is the safely mapped effective
display chunk. `joiner` is either a single space or empty string and describes the
separator before that chunk; ignore the first chunk's joiner when rendering a group.
No-space fragments reconstructed exactly from raw text stay together. If a fragment
is missing, intersects a cut or makes the atom exceed maximum limits, the indivisible
unit is omitted rather than displayed as a partial lexical word. No per-word edited
timing is invented. Layout/behavior/emphasis are semantic constants, not CSS.

### Settings and grouping contract

Partial settings are accepted through the plan job request and expanded to the
complete settings above. Unknown keys fail. `max_words` is a strict integer in
1–20, `max_characters` a strict integer in 1–200. Duration settings are finite
positive numbers up to 60 s and normalized to floats; minimum must not exceed
maximum. Punctuation preference is a strict boolean.

Within each segment, retain only safely mapped positive-duration words fully inside
one retained Phase 06 span. Group in source order. Break before a word/fragment atom
if a cut/omission intervenes, the gap is at least the pause threshold, a maximum
would be exceeded, or the preceding chunk ends in preferred punctuation.
Punctuation includes period, comma, question/exclamation marks, semicolon, colon,
their common full-width forms, and trailing closing quotes/brackets.
Maximum characters counts Unicode code points including joiners, not rendered width.
Maximum words counts timed source entries (compound fragments can count separately).

Short groups try merging with the next compatible group, then the previous,
repeating until no merge applies. Merges cannot cross segments, cuts, omitted
words, pause thresholds or sentence-final punctuation; soft punctuation may merge.
All maxima still apply. Otherwise preserve the exact genuine interval and warn.
No padding into silence, synthetic durations or alignment is generated.

### Text mapping and warnings

The effective-text list contains one Phase 05 merged string per raw segment.
First try exact reconstruction from the original word chunks, normalizing only
whitespace. Otherwise require one effective whitespace token per raw timed word,
unchanged lexical text in order after case folding and removal of Unicode edge
punctuation. This intentionally supports fewer corrections than arbitrary equal-count
substitution. Spelling replacements, insertions, deletions, reordering or mismatched
tokenization are conservatively ambiguous, unless exact chunk reconstruction applies.
Never silently substitute raw ASR text. Empty effective text means no captions.
Invalid/stale overrides fail generation/retrieval rather than using their raw fallback.

Every warning has exactly:

```json
{
  "type": "ambiguous_text_timing",
  "segment_id": "0",
  "word_index": null,
  "caption_id": null,
  "message": "Effective text could not be mapped safely to authoritative word timing. Segment omitted."
}
```

Warning types are:

| Type | Behavior/reference |
| --- | --- |
| `ambiguous_text_timing` | Whole segment omitted; word/caption references null |
| `empty_text` | Effective text empty despite raw words; segment omitted |
| `zero_duration_word` | Raw word has no positive interval; word index supplied |
| `removed_word` | Word intersects accepted removal; word index supplied |
| `unsafe_word_fragments` | Incomplete/cut-crossing no-space fragment atom omitted; first word index supplied |
| `word_exceeds_limits` | Indivisible word/atom exceeds maxima; first word index supplied |
| `minimum_duration_unmet` | Genuine short caption retained; caption ID supplied |

Messages and order are deterministic: source segments in order, segment/word
diagnostics before their caption-duration diagnostics. Multiple diagnostics may
describe one omitted fragment atom. UI displays the readable messages and one-based
segment labels. Malformed or missing authoritative alignment fails validation, not
a manufactured caption or empty-success fallback.

### Identity, validation and atomicity

All digests use Phase 04's canonical sorted compact JSON SHA-256, excluding only a
top-level `content_checksum` field. The effective text digest hashes `{"texts":[...]}`.
The effective cut digest hashes `{"source_duration":...,"removed":[...],"audio_offset":...}`.
Proposal IDs/checksums and pending/rejected decisions are intentionally excluded
from effective identity. Pending → rejected is reusable; accepting/removing acceptance
changes topology and invalidates. Effective text changes invalidate even when a
segment will be omitted. Raw identity, settings, schema/planner version and project
identity also participate. Equivalent settings patches resolve to the same settings.

Caption IDs are `caption-` plus SHA-256 of `{"identity":key,"item":item}`, where
`key` is every top-level field preceding items/warnings/checksum and `item` is the
complete item before caption_id is added. No UUID or clock enters the plan.
Changing any relevant identity may change every caption ID.

Readers revalidate protected inputs through Phase 04/06 helpers, merge overlays,
reconstruct the expected pure plan and verify both checksum and exact content.
Stale/corrupt captions return 404 `captions_not_ready`. Invalid overlays return 409;
missing transcript/cuts and normalization prerequisites preserve existing readable
errors. Generation/settings errors are 422. Publication failure is 500
`caption_write_failed`. Writes share existing heavy-operation exclusion and use the
existing unique sibling/flush/fsync/atomic rename utility. A failed attempt leaves
the previous complete plan untouched, but stale data is never served as current.
External file editing while the backend is active is unsupported.

### Jobs and preview

POST `/projects/{id}/jobs` with `{"stage":"plan","caption_settings":{...}}` starts
caption generation; settings may be omitted. Plan jobs add `caption_settings` to
the existing job record and retain it on retry. Old jobs remain readable.
Caption settings on non-plan jobs are rejected. GET `/projects/{id}/captions`
returns the current validated artifact with its persisted settings.

Browser activation uses `original_start <= video.currentTime < original_end`
and explicitly hides within `removed`. It does not compare original proxy time with
edited timestamps. Playback, seeking, reload and job/input revisions update or
invalidate the preview. There is no automatic edited playback, export or renderer.

## analysis/audio_features.json (Phase 08A)

```json
{
  "schema_version": 1,
  "project_id": "<completed output project ID>",
  "extractor_version": "pcm16-word-delivery-v1",
  "source": {
    "audio_checksum": "<normalized WAV SHA-256>",
    "transcript_checksum": "<raw transcript content_checksum>",
    "timing_checksum": "<canonical segment/word timing SHA-256>"
  },
  "settings": {
    "energy_floor_dbfs": -120.0,
    "energy_lower_percentile": 10.0,
    "energy_upper_percentile": 90.0,
    "local_window_words": 5,
    "overlap_tolerance_seconds": 0.001,
    "relative_duration_cap": 4.0
  },
  "normalization": {
    "method": "linear_interpolated_project_dbfs_percentiles",
    "lower_dbfs": -40.0, "upper_dbfs": -20.0,
    "valid_word_count": 2, "project_duration_median": 0.3
  },
  "time_basis": "normalized_audio_seconds",
  "words": [{
    "word_id": "word-<deterministic SHA-256>",
    "segment_id": "0", "word_index": 0, "text": "binary",
    "start": 1.2, "end": 1.65,
    "features": {
      "rms": 0.1, "energy_dbfs": -20.0, "normalized_energy": 1.0,
      "relative_energy_db": 3.0, "duration": 0.45,
      "relative_duration": 1.5, "pause_before": null, "pause_after": 0.2
    },
    "validity": {"timing_valid": true, "audio_available": true,
                 "feature_valid": true, "clipped_samples": false,
                 "source_confidence": 0.9}
  }],
  "warnings": [],
  "content_checksum": "<canonical complete artifact digest>"
}
```

Times are authoritative Phase 04 WAV seconds and never corrected, shifted through
cuts or inferred. RMS consumes bounded PCM indices `floor(start*16000)` through
`ceil(end*16000)`, after scaling signed PCM16 by 32768. dBFS has a -120 dB floor.
Linear-interpolated project P10/P90 dBFS maps to `[0,1]`; identical non-floor words
use 0.5 and an all-floor project uses 0.0. Relative energy and duration use the
median of up to five valid neighbors on each side. Duration is the genuine interval;
the relative ratio is capped at 4.0. Adjacent negative gaps become zero; overlaps
beyond 1 ms add `overlapping_word_timing`. First/last unavailable gaps are null.

Invalid individual word timing keeps a stable record with null times/features and
`timing_valid: false`, plus `invalid_word_timing`; absent word lists add
`missing_word_timing`. No timestamps are invented. Empty transcripts are valid.
Every float is finite and serialization forbids NaN/infinity. `clipped_samples`
reports any PCM endpoint sample. `source_confidence` preserves a valid Phase 04
word probability or is null; it is provenance, not a calibrated feature score.

Identity includes every source/settings/version field. Word IDs hash timing identity,
segment/word index and exact bounds. Phase 05 overlays, Phase 06 decisions and Phase
07 captions are excluded. GET validates by reconstructing the expected artifact.
Generation cache-hits only exact content; changed audio, raw transcript/timing,
settings, schema or extractor version regenerates. The existing atomic JSON writer
preserves an older complete artifact after failure. POST job stage is
`audio_features`; GET path is `/projects/{id}/audio-features`.
