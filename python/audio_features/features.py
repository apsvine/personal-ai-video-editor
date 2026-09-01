"""Deterministic delivery features from authoritative word timing and PCM16 audio."""
from array import array
import json
import math
import statistics
import sys
import wave

from python.common.control import checkpoint
from python.media import normalization as n
from python.transcription import engine


SCHEMA_VERSION = 1
EXTRACTOR_VERSION = 'pcm16-word-delivery-v1'
SETTINGS = {
    'energy_floor_dbfs': -120.0,
    'energy_lower_percentile': 10.0,
    'energy_upper_percentile': 90.0,
    'local_window_words': 5,
    'overlap_tolerance_seconds': 0.001,
    'relative_duration_cap': 4.0,
}


def _finite_number(value):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value))


def _percentile(values, percentile):
    """Linear interpolation over a sorted finite population (inclusive endpoints)."""
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile / 100.0
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _word_id(timing_checksum, segment_id, word_index, start, end):
    return 'word-' + engine.content_checksum({
        'timing_checksum': timing_checksum,
        'segment_id': segment_id,
        'word_index': word_index,
        'start': start,
        'end': end,
    })


def _read_audio(path):
    try:
        with wave.open(str(path), 'rb') as stream:
            if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate(), stream.getcomptype()) != (1, 2, 16000, 'NONE'):
                raise ValueError('Unexpected WAV format')
            frame_count = stream.getnframes()
            samples = array('h')
            samples.frombytes(stream.readframes(frame_count))
    except (OSError, EOFError, wave.Error, ValueError) as error:
        raise n.MediaError('invalid_audio', 'Expected complete mono 16 kHz PCM16 normalized audio.', 409) from error
    if sys.byteorder != 'little':
        samples.byteswap()
    if len(samples) != frame_count:
        raise n.MediaError('invalid_audio', 'Normalized audio frame data is incomplete.', 409)
    return samples, frame_count / 16000.0


def _transcript_snapshot(path, project):
    try:
        value = json.loads(path.read_text())
        if (not isinstance(value, dict) or value.get('schema_version') != 1
                or value.get('content_checksum') != engine.content_checksum(value)
                or value.get('source') != {'audio_checksum': project['outputs']['audio.wav'],
                                           'source_checksum': project['source']['sha256']}
                or not isinstance(value.get('segments'), list)):
            raise ValueError('Invalid transcript identity')
        return value
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise n.MediaError('transcript_not_ready', 'No safely identifiable authoritative transcript is available.', 404) from error


def _timing_snapshot(raw):
    result = []
    for segment_index, segment in enumerate(raw['segments']):
        words = segment.get('words') if isinstance(segment, dict) else None
        if not isinstance(words, list):
            result.append({'segment_id': str(segment_index), 'words': None})
            continue
        result.append({'segment_id': str(segment_index), 'words': [
            {'word_index': word_index,
             'start': word.get('start') if isinstance(word, dict) else None,
             'end': word.get('end') if isinstance(word, dict) else None}
            for word_index, word in enumerate(words)]})
    return result


def _rms(samples, start, end):
    first = max(0, min(len(samples), math.floor(start * 16000)))
    last = max(first, min(len(samples), math.ceil(end * 16000)))
    if last == first:
        return None, False
    total = sum((sample / 32768.0) ** 2 for sample in samples[first:last])
    return math.sqrt(total / (last - first)), any(abs(sample) == 32768 or sample == 32767 for sample in samples[first:last])


def _warning(kind, segment_id, word_index, message):
    return {'type': kind, 'segment_id': segment_id, 'word_index': word_index, 'message': message}


def generate(project, raw, samples, audio_duration, settings=None):
    settings = dict(SETTINGS if settings is None else settings)
    if settings != SETTINGS:
        raise ValueError('Phase 08A v1 uses the documented extractor settings exactly')
    timing = _timing_snapshot(raw)
    timing_checksum = engine.content_checksum({'segments': timing})
    words, warnings, valid = [], [], []
    for segment_index, segment in enumerate(raw['segments']):
        segment_id = str(segment_index)
        source_words = segment.get('words') if isinstance(segment, dict) else None
        if not isinstance(source_words, list):
            warnings.append(_warning('missing_word_timing', segment_id, None,
                'Segment has no usable authoritative word list and was not analyzed.'))
            continue
        for word_index, source in enumerate(source_words):
            text = source.get('text', '') if isinstance(source, dict) and isinstance(source.get('text', ''), str) else ''
            start = source.get('start') if isinstance(source, dict) else None
            end = source.get('end') if isinstance(source, dict) else None
            confidence = source.get('confidence') if isinstance(source, dict) else None
            confidence = confidence if (_finite_number(confidence) and 0 <= confidence <= 1) else None
            identity_start = start if _finite_number(start) else None
            identity_end = end if _finite_number(end) else None
            record = {
                'word_id': _word_id(timing_checksum, segment_id, word_index, identity_start, identity_end),
                'segment_id': segment_id, 'word_index': word_index, 'text': text,
                'start': identity_start, 'end': identity_end, 'features': None,
                'validity': {'timing_valid': False, 'audio_available': True, 'feature_valid': False,
                             'clipped_samples': False, 'source_confidence': confidence},
            }
            if (identity_start is None or identity_end is None or identity_start < 0
                    or identity_start >= identity_end or identity_end > audio_duration):
                warnings.append(_warning('invalid_word_timing', segment_id, word_index,
                    'Word timing is missing or outside normalized audio and was not analyzed.'))
                words.append(record)
                continue
            rms, clipped = _rms(samples, identity_start, identity_end)
            record['validity'].update(timing_valid=True, clipped_samples=clipped)
            if rms is None:
                warnings.append(_warning('empty_audio_interval', segment_id, word_index,
                    'Timed word contains no addressable PCM sample and was not analyzed.'))
                words.append(record)
                continue
            dbfs = max(settings['energy_floor_dbfs'], 20.0 * math.log10(max(rms, 10 ** (settings['energy_floor_dbfs'] / 20.0))))
            record['features'] = {'rms': rms, 'energy_dbfs': dbfs, 'normalized_energy': None,
                                  'relative_energy_db': None, 'duration': identity_end - identity_start,
                                  'relative_duration': None, 'pause_before': None, 'pause_after': None}
            record['validity']['feature_valid'] = True
            words.append(record)
            valid.append(record)

    energies = [word['features']['energy_dbfs'] for word in valid]
    durations = [word['features']['duration'] for word in valid]
    low = _percentile(energies, settings['energy_lower_percentile']) if energies else settings['energy_floor_dbfs']
    high = _percentile(energies, settings['energy_upper_percentile']) if energies else settings['energy_floor_dbfs']
    duration_median = statistics.median(durations) if durations else None
    window = settings['local_window_words']
    for index, word in enumerate(valid):
        features = word['features']
        if not energies or high == low:
            features['normalized_energy'] = 0.0 if high <= settings['energy_floor_dbfs'] else 0.5
        else:
            features['normalized_energy'] = max(0.0, min(1.0, (features['energy_dbfs'] - low) / (high - low)))
        neighbors = valid[max(0, index-window):index] + valid[index+1:index+window+1]
        local_energy = statistics.median([item['features']['energy_dbfs'] for item in neighbors]) if neighbors else features['energy_dbfs']
        local_duration = statistics.median([item['features']['duration'] for item in neighbors]) if neighbors else features['duration']
        features['relative_energy_db'] = features['energy_dbfs'] - local_energy
        features['relative_duration'] = min(settings['relative_duration_cap'], features['duration'] / local_duration)
        if index:
            gap = word['start'] - valid[index-1]['end']
            if gap < 0:
                if gap < -settings['overlap_tolerance_seconds']:
                    warnings.append(_warning('overlapping_word_timing', word['segment_id'], word['word_index'],
                        'Word overlaps the previous valid word; pause_before is zero.'))
                gap = 0.0
            features['pause_before'] = gap
        if index + 1 < len(valid):
            gap = valid[index+1]['start'] - word['end']
            features['pause_after'] = max(0.0, gap)

    value = {
        'schema_version': SCHEMA_VERSION, 'project_id': project['project_id'],
        'extractor_version': EXTRACTOR_VERSION,
        'source': {'audio_checksum': project['outputs']['audio.wav'],
                   'transcript_checksum': raw['content_checksum'], 'timing_checksum': timing_checksum},
        'settings': settings,
        'normalization': {'method': 'linear_interpolated_project_dbfs_percentiles',
                          'lower_dbfs': low, 'upper_dbfs': high,
                          'valid_word_count': len(valid), 'project_duration_median': duration_median},
        'time_basis': 'normalized_audio_seconds', 'words': words, 'warnings': warnings,
    }
    value['content_checksum'] = engine.content_checksum(value)
    validate(value)
    return value


def validate(value):
    if (not isinstance(value, dict) or type(value.get('schema_version')) is not int
            or value.get('schema_version') != SCHEMA_VERSION
            or value.get('extractor_version') != EXTRACTOR_VERSION
            or value.get('content_checksum') != engine.content_checksum(value)):
        raise ValueError('Invalid audio feature identity')
    encoded = json.dumps(value, allow_nan=False, sort_keys=True)
    if not encoded or not isinstance(value.get('words'), list) or not isinstance(value.get('warnings'), list):
        raise ValueError('Invalid audio feature artifact')
    for word in value['words']:
        if not isinstance(word.get('validity'), dict):
            raise ValueError('Invalid word validity')
        features = word.get('features')
        if features is not None:
            for number in features.values():
                if number is not None and not _finite_number(number):
                    raise ValueError('Nonfinite audio feature')
            if not 0 <= features['normalized_energy'] <= 1:
                raise ValueError('Normalized energy outside range')
    return value


def _inputs(root, project):
    project = engine.normalized_project(root, project)
    path = n.project_path(root, project['project_id'])
    audio = n.safe_path(path, 'normalized', 'audio.wav')
    samples, duration = _read_audio(audio)
    raw = _transcript_snapshot(n.safe_path(path, 'analysis', 'transcript.json'), project)
    return project, path, raw, samples, duration


def read_audio_features(root, project):
    try:
        project, path, raw, samples, duration = _inputs(root, project)
        expected = generate(project, raw, samples, duration)
        saved = json.loads(n.safe_path(path, 'analysis', 'audio_features.json').read_text())
        if saved != expected:
            raise ValueError('Stale or corrupt audio features')
        return validate(saved)
    except n.MediaError:
        raise
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise n.MediaError('audio_features_not_ready', 'No current audio delivery features are available.', 404) from error


def analyze(root, project):
    checkpoint(.05)
    project, path, raw, samples, duration = _inputs(root, project)
    checkpoint(.4)
    value = generate(project, raw, samples, duration)
    output = n.safe_path(path, 'analysis', 'audio_features.json')
    try:
        saved = json.loads(output.read_text())
        if saved == value:
            return {'project_id': project['project_id'], 'reused': True}
    except (OSError, ValueError):
        pass
    checkpoint(.9)
    try:
        n.atomic_json(output, value)
    except OSError as error:
        raise n.MediaError('audio_features_write_failed',
                           'Audio features could not be saved. The previous artifact was preserved.', 500) from error
    return {'project_id': project['project_id'], 'reused': False}
