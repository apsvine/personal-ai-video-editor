"""Sparse cut decisions, separate from immutable generated proposals."""
import json
import re
from python.editing import cuts
from python.media import normalization as n


def snapshot(root, project_id):
    raw = cuts.read_cuts(root, n.read_project(root, project_id))
    path = n.safe_path(n.project_path(root, raw['project_id']), 'overrides', 'user_cuts.json')
    return raw, path


def read_override(path, raw):
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {}, 'none', None
    except (OSError, ValueError):
        return {}, 'invalid', 'Saved cut decisions are unreadable. Reset All Decisions to continue.'
    try:
        if (not isinstance(value, dict) or set(value) != {'schema_version', 'project_id', 'source_cuts_checksum', 'decisions'}
                or type(value['schema_version']) is not int or value['schema_version'] != 1
                or value['project_id'] != raw['project_id'] or not isinstance(value['source_cuts_checksum'], str)
                or not re.fullmatch('[a-f0-9]{64}', value['source_cuts_checksum']) or not isinstance(value['decisions'], dict)):
            raise ValueError('Invalid override')
        for key, decision in value['decisions'].items():
            if (not re.fullmatch('[a-f0-9]{64}', key) or not isinstance(decision, dict)
                    or set(decision) != {'action'} or decision['action'] not in ('accept', 'reject')):
                raise ValueError('Invalid decision')
        if value['source_cuts_checksum'] != raw['content_checksum']:
            return {}, 'stale', 'The generated plan changed. Saved decisions are withheld. Reset All Decisions to continue.'
        if set(value['decisions']) - {c['cut_id'] for c in raw['candidates']}:
            raise ValueError('Unknown cut')
        return value['decisions'], 'applied' if value['decisions'] else 'none', None
    except (ValueError, TypeError, KeyError):
        return {}, 'invalid', 'Saved cut decisions are invalid. Reset All Decisions to continue.'


def merged(raw, decisions, state, message):
    candidates = [{**c, 'decision': decisions.get(c['cut_id'], {}).get('action', 'pending')} for c in raw['candidates']]
    removed = [dict(start=c['start'], end=c['end']) for c in candidates if c['decision'] == 'accept']
    return dict(schema_version=1, project_id=raw['project_id'], source_cuts_checksum=raw['content_checksum'],
                override_state=state, override_message=message, warnings=raw['warnings'], candidates=candidates,
                effective=cuts.mapping(raw['source_duration'], removed))


def get_review(root, project_id):
    raw, path = snapshot(root, project_id)
    return merged(raw, *read_override(path, raw))


def change_review(root, project_id, checksum, cut_id=None, action=None, reset=False):
    """Caller owns existing heavy-operation reservation for the entire transaction."""
    raw, path = snapshot(root, project_id)
    if checksum != raw['content_checksum']:
        raise n.MediaError('cuts_changed', 'The generated plan changed. Reload Smart Cuts.', 409)
    decisions, state, message = read_override(path, raw)
    if cut_id is not None:
        if cut_id not in {c['cut_id'] for c in raw['candidates']}:
            raise n.MediaError('invalid_cut', 'Unknown cut candidate.', 422)
        if state in ('stale', 'invalid'):
            raise n.MediaError('cut_override_' + state, message, 409)
        if reset:
            decisions.pop(cut_id, None)
        elif action in ('accept', 'reject'):
            decisions[cut_id] = dict(action=action)
        else:
            raise n.MediaError('invalid_cut_action', 'Choose accept or reject.', 422)
    elif reset:
        decisions = {}
    else:
        raise n.MediaError('invalid_cut', 'A cut candidate is required.', 422)
    try:
        if decisions:
            path.parent.mkdir(exist_ok=True)
            n.atomic_json(path, dict(schema_version=1, project_id=raw['project_id'], source_cuts_checksum=checksum, decisions=decisions))
        else:
            path.unlink(missing_ok=True)
    except OSError as error:
        raise n.MediaError('cut_override_write_failed', 'Cut decisions could not be saved. Check storage and retry.', 500) from error
    return merged(raw, decisions, 'applied' if decisions else 'none', None)
