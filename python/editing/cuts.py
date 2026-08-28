"""Phase 06 proposal topology and pure timeline mapping. Never writes media."""
import json
import math
from python.audio_features import silence
from python.common.control import checkpoint
from python.media import normalization as n
from python.transcription import engine as e

SETTINGS = dict(threshold_db=-40, min_silence=.8, padding=.2, min_cut=.3)
PLANNER = 'silence-word-protection-v1'


def settings_value(settings):
    if set(settings) != set(SETTINGS):
        raise ValueError('Unknown planner settings')
    for key, value in settings.items():
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError('Invalid planner setting')
        if key == 'threshold_db':
            if not -100 <= value <= -10:
                raise ValueError('Threshold outside supported bounds')
        elif not 0 < value <= 60:
            raise ValueError('Invalid duration setting')
    return dict(settings)


def ranges(items, duration):
    previous = 0
    for item in items:
        if set(item) != {'start', 'end'}:
            raise ValueError('Invalid interval keys')
        start, end = item['start'], item['end']
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in (start, end)):
            raise ValueError('Invalid interval number')
        if not previous <= start < end <= duration:
            raise ValueError('Unordered/out-of-bounds interval')
        previous = end
    return items


def topology(duration, removed):
    if type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0:
        raise ValueError('Invalid source duration')
    ranges(removed, duration)
    keep, cursor = [], 0.0
    for item in removed:
        if cursor < item['start']:
            keep.append(dict(start=cursor, end=item['start']))
        cursor = item['end']
    if cursor < duration:
        keep.append(dict(start=cursor, end=duration))
    return dict(keep=keep, removed=[dict(i) for i in removed])


def mapping(duration, removed):
    result = topology(duration, removed)
    elapsed, spans = 0.0, []
    for item in result['keep']:
        end = elapsed + item['end'] - item['start']
        spans.append(dict(original_start=item['start'], original_end=item['end'], edited_start=elapsed, edited_end=end))
        elapsed = end
    return {**result, 'source_duration': duration, 'effective_duration': elapsed,
            'time_removed': duration - elapsed, 'mapping': spans}


def checked_time(time, duration):
    if type(time) not in (int, float) or not math.isfinite(time) or not 0 <= time <= duration:
        raise ValueError('Time outside timeline')


def original_to_edited(duration, removed, time):
    mapping(duration, removed)
    checked_time(time, duration)
    elapsed_removed = 0.0
    for item in removed:
        if item['start'] <= time < item['end']:
            return dict(removed=True, splice_time=item['start'] - elapsed_removed)
        if item['end'] <= time:
            elapsed_removed += item['end'] - item['start']
    return dict(removed=False, edited_time=time - elapsed_removed)


def edited_to_original(duration, removed, time):
    plan = mapping(duration, removed)
    checked_time(time, plan['effective_duration'])
    # Right-continuous at a splice. Final endpoint chooses original duration.
    if time == plan['effective_duration']:
        return dict(original_time=duration)
    for item in plan['mapping']:
        if item['edited_start'] <= time < item['edited_end']:
            return dict(original_time=item['original_start'] + time - item['edited_start'])
    raise ValueError('No retained interval')


def protections(raw, duration, padding, offset=0):
    protected = []
    for segment in raw['segments']:
        for item in segment.get('words') or [segment]:
            start, end = max(0, item['start'] + offset - padding), min(duration, item['end'] + offset + padding)
            if start < end:
                protected.append(dict(start=start, end=end))
    return protected


def subtract(start, end, protected):
    spans = [(start, end)]
    for block in protected:
        next_spans = []
        for a, b in spans:
            if block['end'] <= a or block['start'] >= b:
                next_spans.append((a, b))
            else:
                if a < block['start']:
                    next_spans.append((a, block['start']))
                if block['end'] < b:
                    next_spans.append((block['end'], b))
        spans = next_spans
    return spans


def identity(project, raw, duration, audio_duration, settings, detector, audio_offset=0):
    if type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0:
        raise ValueError('Invalid source duration')
    if not isinstance(detector, str) or not detector:
        raise ValueError('Invalid detector version')
    if type(audio_offset) not in (int, float) or not math.isfinite(audio_offset) or not 0 <= audio_offset < duration:
        raise ValueError('Invalid audio offset')
    timing = [{'start': s['start'], 'end': s['end'],
               'words': [{'start': w['start'], 'end': w['end']} for w in s['words']]} for s in raw['segments']]
    return dict(schema_version=1, project_id=project['project_id'],
        source=dict(source_checksum=project['source']['sha256'], audio_checksum=project['outputs']['audio.wav'],
                    transcript_checksum=raw['content_checksum'], timing_checksum=e.content_checksum({'segments': timing})),
        source_duration=duration, audio_duration=audio_duration, audio_offset=audio_offset, settings=settings_value(settings), planner=PLANNER,
        detector=dict(name='ffmpeg.silencedetect', version=detector), time_basis='normalized_proxy_seconds', topology_scope='proposal')


def generate(key, raw, detected):
    duration, settings = key['source_duration'], key['settings']
    ranges(detected, key['audio_duration'])
    protected = protections(raw, duration, settings['padding'], key['audio_offset'])
    candidates = []
    for event in detected:
        if event['end'] - event['start'] + 1e-9 < settings['min_silence']:
            continue
        a = event['start'] + key['audio_offset'] + settings['padding']
        b = min(duration, event['end'] + key['audio_offset']) - settings['padding']
        for start, end in subtract(a, b, protected):
            start = math.ceil(start * 1_000_000) / 1_000_000
            end = math.floor(end * 1_000_000) / 1_000_000
            if end - start + 1e-9 < settings['min_cut']:
                continue
            cut_id = e.content_checksum({'identity': key, 'start': start, 'end': end})
            candidates.append(dict(cut_id=cut_id, start=start, end=end, reason='silence',
                                   silence_start=event['start'], silence_end=event['end']))
    removed = [dict(start=c['start'], end=c['end']) for c in candidates]
    value = {**key, 'candidates': candidates, **topology(duration, removed),
        'warnings': ['ASR timing is estimated. Listen at every proposed boundary before accepting.'] + (['empty_speech_transcript: silence proposals require human listening; speech may have been missed.']
                     if not any(s['text'].strip() or s['words'] for s in raw['segments']) else [])}
    value['content_checksum'] = e.content_checksum(value)
    return value


def validate(value, key, raw):
    if type(value.get('schema_version')) is not int or value.get('content_checksum') != e.content_checksum(value):
        raise ValueError('Invalid cuts checksum/schema')
    if any(value.get(k) != v for k, v in key.items()):
        raise ValueError('Cuts identity changed')
    if any(not isinstance(value.get(field), list) for field in ('candidates', 'keep', 'removed', 'warnings')):
        raise ValueError('Invalid cut collections')
    if type(value.get('audio_duration')) not in (int, float):
        raise ValueError('Invalid audio duration')
    ranges(value['keep'], key['source_duration'])
    ranges(value['removed'], key['source_duration'])
    ranges([dict(start=candidate['start'], end=candidate['end']) for candidate in value['candidates']], key['source_duration'])
    events = []
    for candidate in value['candidates']:
        event = dict(start=candidate['silence_start'], end=candidate['silence_end'])
        if not events or event != events[-1]:
            events.append(event)
    if generate(key, raw, events) != value:
        raise ValueError('Invalid cuts topology or candidates')
    return value


def inputs(root, project):
    project = e.normalized_project(root, project)
    raw = e.read_transcript(root, project)
    path = n.project_path(root, project['project_id'])
    audio = n.safe_path(path, 'normalized', 'audio.wav')
    return project, raw, path, audio, e.audio_duration(audio)


def read_cuts(root, project):
    project, raw, path, audio, duration = inputs(root, project)
    try:
        value = json.loads(n.safe_path(path, 'analysis', 'cuts.json').read_text())
        key = identity(project, raw, value['source_duration'], duration, value['settings'], value['detector']['version'], value['audio_offset'])
        return validate(value, key, raw)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise n.MediaError('cuts_not_ready', 'No valid current cut plan is available. Run Smart Cuts analysis.', 404) from error


def analyze(root, project, settings=None):
    checkpoint(.05)
    project, raw, path, audio, duration = inputs(root, project)
    settings = settings_value(SETTINGS if settings is None else settings)
    source_duration, offset = silence.timeline(path, project, duration)
    detector = silence.version(n.safe_path(path, 'logs', 'cuts-probe.log'))
    key = identity(project, raw, source_duration, duration, settings, detector, offset)
    try:
        cached = read_cuts(root, project)
        if all(cached[k] == v for k, v in key.items()):
            return dict(project_id=project['project_id'], reused=True)
    except n.MediaError:
        pass
    checkpoint(.15)
    detected = silence.detect(audio, duration, settings, n.safe_path(path, 'logs'))
    checkpoint(.8)
    value = generate(key, raw, detected)
    validate(value, key, raw)
    checkpoint(.9)
    n.atomic_json(n.safe_path(path, 'analysis', 'cuts.json'), value)
    return dict(project_id=project['project_id'], reused=False)
