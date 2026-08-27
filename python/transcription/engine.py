"""Verified normalized audio -> atomic, provider-independent transcript artifact."""
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import uuid
import wave

from python.media import normalization as n
from python.common.control import checkpoint, run_worker
from python.transcription import provider


def model_path(root):
    return Path(os.environ.get('PERSONAL_AI_VIDEO_EDITOR_MODEL_PATH',
                root.parent / 'cache/transcription/faster-whisper/base')).absolute()


def normalized_project(root, project):
    if project.get('normalization_status') == 'reused':
        target = n.read_project(root, project['reused_project_id'])
        if target['source'].get('sha256') != project['source'].get('sha256'):
            raise n.MediaError('normalization_not_ready', 'Reused source identity does not match.', 409)
        project = target
    if (project.get('normalization_status') != 'completed' or project.get('schema_version') != n.SCHEMA
            or project.get('configuration') != n.CONFIG):
        raise n.MediaError('normalization_not_ready', 'Complete normalization before transcription.', 409)
    path = n.project_path(root, project['project_id'])
    expected = {'metadata.json', 'proxy.mp4'} | ({'audio.wav'} if project.get('audio_status') == 'available' else set())
    if project.get('audio_status') not in ('available', 'no_audio') or set(project.get('outputs', {})) != expected:
        raise n.MediaError('normalization_not_ready', 'Normalized output manifest is invalid.', 409)
    checks = [(n.safe_path(path, 'source', project['source']['filename']), project['source'].get('sha256'))]
    checks += [(n.safe_path(path, 'normalized', name), value) for name, value in project['outputs'].items()]
    for file, digest in checks:
        if not file.is_file() or n.checksum(file) != digest:
            raise n.MediaError('normalization_not_ready', 'Normalized media integrity check failed.', 409)
    if project['audio_status'] == 'no_audio':
        raise n.MediaError('no_audio', 'This video has no audio stream to transcribe.', 409)
    return project


def validate(value, duration):
    if value.get('schema_version') != 1 or value.get('timing_quality') != 'model_estimated_word_alignment':
        raise ValueError('Unsupported transcript schema/timing')
    if not isinstance(value.get('language'), str) or not value['language']:
        raise ValueError('Missing language')
    if not isinstance(value.get('segments'), list):
        raise ValueError('Missing segments')
    def interval(item, low, high):
        start, end = item['start'], item['end']
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in (start, end)):
            raise ValueError('Invalid timestamp')
        if not low <= start <= end <= high or not isinstance(item['text'], str):
            raise ValueError('Invalid interval/text')
        c = item['confidence']
        if c is not None and (isinstance(c, bool) or not isinstance(c, (int, float)) or not math.isfinite(c) or not 0 <= c <= 1):
            raise ValueError('Invalid confidence')
        return end
    previous = 0
    for segment in value['segments']:
        previous = interval(segment, previous, duration)
        word_end = segment['start']
        if not isinstance(segment['words'], list):
            raise ValueError('Invalid words')
        if segment['text'].strip() and not segment['words']:
            raise ValueError('Speech segment lacks word alignment')
        for word in segment['words']:
            word_end = interval(word, word_end, segment['end'])
    return value


def audio_duration(audio):
    with wave.open(str(audio), 'rb') as stream:
        if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate(), stream.getcomptype()) != (1, 2, 16000, 'NONE'):
            raise n.MediaError('invalid_audio', 'Expected mono 16 kHz PCM16 normalized audio.', 409)
        return stream.getnframes() / 16000


def identity(project, model, settings):
    # Content fingerprint detects replacement weights without tying identity to a machine path.
    digest = hashlib.sha256()
    for file in sorted(model.iterdir()):
        if file.is_file():
            digest.update(file.name.encode()); digest.update(n.checksum(file).encode())
    return dict(schema_version=1, source=dict(audio_checksum=project['outputs']['audio.wav'],
                source_checksum=project['source']['sha256']), provider=dict(name='faster-whisper',
                version=provider.VERSION, model='base', model_checksum=digest.hexdigest(), settings=settings))


def content_checksum(value):
    payload = {k: v for k, v in value.items() if k != 'content_checksum'}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def read_transcript(root, project):
    project = normalized_project(root, project)
    path = n.project_path(root, project['project_id'])
    try:
        value = json.loads(n.safe_path(path, 'analysis', 'transcript.json').read_text())
        if value.get('content_checksum') != content_checksum(value):
            raise ValueError('Transcript checksum mismatch')
        validate(value, audio_duration(n.safe_path(path, 'normalized', 'audio.wav')))
        if value['source'] != dict(audio_checksum=project['outputs']['audio.wav'], source_checksum=project['source']['sha256']):
            raise ValueError('Stale source')
        return value
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise n.MediaError('transcript_not_ready', 'No valid transcript is available.', 404) from error


def transcribe(root, project, model=None, settings=None, runner=None):
    checkpoint(.05)
    project = normalized_project(root, project)
    path = n.project_path(root, project['project_id'])
    audio = n.safe_path(path, 'normalized', 'audio.wav')
    duration = audio_duration(audio)
    model = provider.require_model(model or model_path(root))
    settings = dict(provider.SETTINGS if settings is None else settings)
    key = identity(project, model, settings)
    try:
        cached = read_transcript(root, project)
        if all(cached.get(k) == v for k, v in key.items()):
            return dict(project_id=project['project_id'], reused=True)
    except n.MediaError:
        pass
    directory = n.safe_path(path, 'analysis'); directory.mkdir(exist_ok=True)
    temporary = n.safe_path(directory, f'transcript-{uuid.uuid4().hex}.tmp')
    request = n.safe_path(directory, f'request-{uuid.uuid4().hex}.tmp')
    log = n.safe_path(path, 'logs', 'transcription.log')
    try:
        checkpoint(.15)
        if runner:
            result = runner(audio, model, settings)
        else:
            n.atomic_json(request, dict(audio=str(audio), model=str(model), settings=settings, output=str(temporary)))
            run_worker([sys.executable, '-m', 'python.transcription.worker', str(request)], log)
            result = json.loads(temporary.read_text())
            if 'error' in result:
                raise n.MediaError(result['error']['code'], result['error']['message'], 422)
        checkpoint(.9)
        value = validate({**result, **key}, duration)
        # Never overwrite the previous artifact until the complete replacement is valid.
        value['content_checksum'] = content_checksum(value)
        n.atomic_json(n.safe_path(directory, 'transcript.json'), value)
        return dict(project_id=project['project_id'], reused=False)
    finally:
        temporary.unlink(missing_ok=True); request.unlink(missing_ok=True)
