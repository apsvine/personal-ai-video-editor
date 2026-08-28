"""Phase 07 validated snapshots and atomic publication; caller owns the job gate."""
import json
from python.common.control import checkpoint
from python.editing import captions, cuts, cut_review
from python.media import normalization as n
from python.transcription import review, engine


def matches(saved, expected_value):
    return (isinstance(saved, dict) and type(saved.get('schema_version')) is int
            and saved.get('content_checksum') == engine.content_checksum(saved)
            and saved == expected_value)


def expected(root, project, settings=None):
    # Read one validated raw snapshot through Phase 06, then apply both sparse
    # overlays to that snapshot. Never consume proposal topology as accepted cuts.
    try:
        raw_cuts = cuts.read_cuts(root, project)
        pid, override_path, raw = review.snapshot(root, raw_cuts['project_id'])
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise n.MediaError('caption_inputs_invalid', 'Malformed transcript or cut inputs; no plan was published.', 422) from error
    if raw['content_checksum'] != raw_cuts['source']['transcript_checksum']:
        raise n.MediaError('caption_inputs_changed', 'Inputs changed. Reload and regenerate captions.', 409)
    overrides, state, message = review.read_override(override_path, pid, raw)
    if state in ('stale', 'invalid'):
        raise n.MediaError('caption_transcript_' + state, message, 409)
    path = n.project_path(root, pid)
    decisions, state, message = cut_review.read_override(n.safe_path(path, 'overrides', 'user_cuts.json'), raw_cuts)
    if state in ('stale', 'invalid'):
        raise n.MediaError('caption_cuts_' + state, message, 409)
    effective = cut_review.merged(raw_cuts, decisions, state, message)['effective']
    texts = [overrides.get(str(i), {}).get('text', s['text']) for i, s in enumerate(raw['segments'])]
    try:
        value = captions.generate(pid, raw, texts, effective['source_duration'], effective['removed'],
                                  raw_cuts['audio_offset'], settings)
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise n.MediaError('caption_inputs_invalid', 'Caption inputs or settings are invalid; no plan was published.', 422) from error
    return n.safe_path(path, 'analysis', 'captions.json'), value


def read_captions(root, project):
    # Settings are persisted in the artifact; GET validates against its own settings.
    try:
        raw_cuts = cuts.read_cuts(root, project)
        path = n.safe_path(n.project_path(root, raw_cuts['project_id']), 'analysis', 'captions.json')
        saved = json.loads(path.read_text())
        _, value = expected(root, project, saved['settings'])
        if not matches(saved, value):
            raise ValueError('Stale or corrupt captions')
        return value
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise n.MediaError('captions_not_ready', 'No current caption plan. Generate captions to refresh the preview.', 404) from error


def plan(root, project, settings=None):
    checkpoint(.05)
    path, value = expected(root, project, settings)
    checkpoint(.8)
    try:
        if matches(json.loads(path.read_text()), value):
            return dict(project_id=value['project_id'], reused=True)
    except (OSError, ValueError):
        pass
    checkpoint(.9)
    try:
        n.atomic_json(path, value)
    except OSError as error:
        raise n.MediaError('caption_write_failed', 'Captions could not be saved. Previous plan was preserved.', 500) from error
    return dict(project_id=value['project_id'], reused=False)
