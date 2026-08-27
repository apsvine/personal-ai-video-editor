"""Text-only review overlays. The Phase 04 artifact is never written here."""
import json
import re

from python.media import normalization as n
from python.transcription.engine import read_transcript

MAX_TEXT = 10000


def valid_text(value):
    if not isinstance(value, str) or len(value) > MAX_TEXT:
        raise ValueError('Text must be a string of at most 10000 characters.')
    value.encode('utf-8', errors='strict')
    if '\x00' in value:
        raise ValueError('Text must not contain NUL characters.')
    return value


def snapshot(root, project_id):
    project = n.read_project(root, project_id)
    raw = read_transcript(root, project)
    output_id = project['reused_project_id'] if project.get('normalization_status') == 'reused' else project_id
    path = n.safe_path(n.project_path(root, output_id), 'overrides', 'user_transcript.json')
    return output_id, path, raw


def read_override(path, project_id, raw):
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {}, 'none', None
    except (OSError, ValueError):
        return {}, 'invalid', 'Saved corrections are unreadable. Reset all corrections to continue.'
    try:
        if (not isinstance(value, dict)
                or set(value) != {'schema_version', 'project_id', 'source_transcript_checksum', 'segments'}
                or type(value['schema_version']) is not int or value['schema_version'] != 1
                or value['project_id'] != project_id
                or not isinstance(value['source_transcript_checksum'], str)
                or not re.fullmatch(r'[a-f0-9]{64}', value['source_transcript_checksum'])
                or not isinstance(value['segments'], dict)):
            raise ValueError('Invalid override schema')
        for key, segment in value['segments'].items():
            if (not re.fullmatch(r'0|[1-9][0-9]{0,9}', key)
                    or not isinstance(segment, dict) or set(segment) != {'text'}):
                raise ValueError('Invalid segment override')
            valid_text(segment['text'])
        if value['source_transcript_checksum'] != raw['content_checksum']:
            return {}, 'stale', 'The source transcript changed. Saved corrections were not applied. Reset all corrections to continue.'
        if any(int(key) >= len(raw['segments']) for key in value['segments']):
            raise ValueError('Unknown segment')
        return value['segments'], 'applied' if value['segments'] else 'none', None
    except (ValueError, TypeError, KeyError):
        return {}, 'invalid', 'Saved corrections have an invalid schema. Reset all corrections to continue.'


def merged(project_id, raw, overrides, state, message):
    return dict(schema_version=1, project_id=project_id,
                source_transcript_checksum=raw['content_checksum'],
                language=raw['language'], timing_quality=raw['timing_quality'],
                override_state=state, override_message=message,
                segments=[{**segment, 'segment_id': str(index), 'raw_text': segment['text'],
                           'text': overrides.get(str(index), {}).get('text', segment['text']),
                           'edited': str(index) in overrides}
                          for index, segment in enumerate(raw['segments'])])


def get_review(root, project_id):
    output_id, path, raw = snapshot(root, project_id)
    overrides, state, message = read_override(path, output_id, raw)
    return merged(output_id, raw, overrides, state, message)


def change_review(root, project_id, checksum, segment_id=None, text=None, reset=False):
    """Caller holds the existing heavy-operation reservation, including across publication."""
    output_id, path, raw = snapshot(root, project_id)
    if checksum != raw['content_checksum']:
        raise n.MediaError('transcript_changed', 'The source transcript changed. Reload review before saving or resetting.', 409)
    overrides, state, message = read_override(path, output_id, raw)
    if segment_id is not None:
        if segment_id not in {str(i) for i in range(len(raw['segments']))}:
            raise n.MediaError('invalid_segment', 'Transcript segment does not exist.', 422)
        if state in ('stale', 'invalid'):
            raise n.MediaError('override_' + state, message, 409)
        if reset:
            overrides.pop(segment_id, None)
        else:
            try:
                valid_text(text)
            except (ValueError, UnicodeError) as error:
                raise n.MediaError('invalid_text', 'Use valid UTF-8 text, at most 10000 characters, without NUL.', 422) from error
            if text == raw['segments'][int(segment_id)]['text']:
                overrides.pop(segment_id, None)
            else:
                overrides[segment_id] = {'text': text}
    elif reset:
        overrides = {}
    else:
        raise n.MediaError('invalid_segment', 'A segment is required.', 422)
    try:
        if overrides:
            path.parent.mkdir(exist_ok=True)
            n.atomic_json(path, dict(schema_version=1, project_id=output_id,
                                    source_transcript_checksum=checksum, segments=overrides))
        else:
            path.unlink(missing_ok=True)
    except OSError as error:
        raise n.MediaError('override_write_failed', 'Corrections could not be saved. Check local storage and try again.', 500) from error
    return merged(output_id, raw, overrides, 'applied' if overrides else 'none', None)
