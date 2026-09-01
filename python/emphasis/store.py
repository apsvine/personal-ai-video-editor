"""Validated Phase 08B inputs, cache identity and atomic artifact publication."""
import json

from python.audio_features import features
from python.common.control import checkpoint
from python.editing import caption_store
from python.emphasis import policy
from python.media import normalization as n


def expected(root, project, settings=None):
    captions = caption_store.read_captions(root, project)
    audio = features.read_audio_features(root, project)
    try:
        value = policy.generate(captions['project_id'], captions, audio, settings)
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise n.MediaError('emphasis_inputs_invalid', 'Emphasis inputs or settings are invalid; no policy was published.', 422) from error
    path = n.safe_path(n.project_path(root, captions['project_id']), 'analysis', 'emphasis.json')
    return path, value


def read_emphasis(root, project):
    try:
        resolved = features.engine.normalized_project(root, project)
        path = n.safe_path(n.project_path(root, resolved['project_id']), 'analysis', 'emphasis.json')
        saved = json.loads(path.read_text())
        _, value = expected(root, project, saved['settings'])
        if saved != value:
            raise ValueError('Stale or corrupt emphasis')
        return policy.validate(saved)
    except n.MediaError:
        raise
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise n.MediaError('emphasis_not_ready', 'No current voice-reactive emphasis policy is available.', 404) from error


def analyze(root, project, settings=None):
    checkpoint(.05)
    path, value = expected(root, project, settings)
    checkpoint(.8)
    try:
        if json.loads(path.read_text()) == value:
            return {'project_id': value['project_id'], 'reused': True}
    except (OSError, ValueError):
        pass
    checkpoint(.9)
    try:
        n.atomic_json(path, value)
    except OSError as error:
        raise n.MediaError('emphasis_write_failed', 'Emphasis could not be saved. The previous artifact was preserved.', 500) from error
    return {'project_id': value['project_id'], 'reused': False}
