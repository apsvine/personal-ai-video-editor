"""Pure deterministic Phase 08B emphasis policy. No I/O or visual execution."""
import json
import math

from python.transcription import engine

SCHEMA_VERSION = 1
POLICY_VERSION = 'bounded-voice-emphasis-v1'
STRONG_BEHAVIORS = ('pop', 'hold', 'punch')
SETTINGS = {
    'reactive_enabled': True,
    'normalized_energy_weight': .6,
    'relative_energy_weight': .4,
    'relative_energy_full_scale_db': 6.0,
    'energy_weight': .5,
    'pause_weight': .3,
    'duration_weight': .2,
    'pause_full_scale_seconds': .75,
    'duration_baseline': 1.0,
    'duration_full_scale_above_baseline': 1.5,
    'subtle_threshold': .35,
    'strong_score_threshold': .72,
    'shape_threshold': .75,
    'punch_score_threshold': .85,
    'punch_component_threshold': .65,
    'cooldown_seconds': 1.5,
    'rate_window_seconds': 8.0,
    'max_strong_per_window': 2,
}


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def clamp(value):
    return max(0.0, min(1.0, float(value)))


def settings_value(settings=None):
    value = dict(SETTINGS)
    if settings is not None:
        if not isinstance(settings, dict) or set(settings) - set(SETTINGS):
            raise ValueError('Unknown emphasis settings')
        value.update(settings)
    if type(value['reactive_enabled']) is not bool:
        raise ValueError('reactive_enabled must be boolean')
    for key in set(SETTINGS) - {'reactive_enabled', 'max_strong_per_window'}:
        if not _number(value[key]) or value[key] < 0:
            raise ValueError('Invalid emphasis setting')
        value[key] = float(value[key])
    if type(value['max_strong_per_window']) is not int or value['max_strong_per_window'] < 1:
        raise ValueError('Invalid strong-event limit')
    if not math.isclose(value['normalized_energy_weight'] + value['relative_energy_weight'], 1.0):
        raise ValueError('Energy subweights must sum to one')
    if not math.isclose(value['energy_weight'] + value['pause_weight'] + value['duration_weight'], 1.0):
        raise ValueError('Signal weights must sum to one')
    if any(value[key] <= 0 for key in ('relative_energy_full_scale_db', 'pause_full_scale_seconds',
                                       'duration_full_scale_above_baseline', 'rate_window_seconds')):
        raise ValueError('Emphasis scales must be positive')
    thresholds = [value[k] for k in ('subtle_threshold', 'strong_score_threshold', 'shape_threshold',
                                     'punch_score_threshold', 'punch_component_threshold')]
    if any(not 0 <= item <= 1 for item in thresholds):
        raise ValueError('Emphasis thresholds must be bounded')
    return value


def score_features(features, settings=None):
    settings = settings_value(settings)
    required = ('normalized_energy', 'relative_energy_db', 'relative_duration', 'pause_before', 'pause_after')
    if not isinstance(features, dict) or any(key not in features for key in required):
        raise ValueError('Missing validated delivery feature')
    for key in required:
        if features[key] is not None and not _number(features[key]):
            raise ValueError('Invalid delivery feature')
    if features['normalized_energy'] is None or features['relative_energy_db'] is None or features['relative_duration'] is None:
        raise ValueError('Incomplete delivery feature')
    normalized = clamp(features['normalized_energy'])
    relative = clamp(features['relative_energy_db'] / settings['relative_energy_full_scale_db'])
    energy = clamp(settings['normalized_energy_weight'] * normalized + settings['relative_energy_weight'] * relative)
    pauses = [value for value in (features['pause_before'], features['pause_after']) if value is not None]
    pause = max((clamp(value / settings['pause_full_scale_seconds']) for value in pauses), default=0.0)
    duration = clamp((features['relative_duration'] - settings['duration_baseline']) /
                     settings['duration_full_scale_above_baseline'])
    score = clamp(settings['energy_weight'] * energy + settings['pause_weight'] * pause +
                  settings['duration_weight'] * duration)
    return score, {'energy': energy, 'pause': pause, 'duration': duration}


def _candidate_behavior(score, signals, settings):
    if score < settings['subtle_threshold']:
        return 'none'
    if score < settings['strong_score_threshold']:
        return 'subtle'
    high = sum(signals[key] >= settings['punch_component_threshold'] for key in ('energy', 'pause', 'duration'))
    if score >= settings['punch_score_threshold'] and high >= 2:
        return 'punch'
    if signals['duration'] >= settings['shape_threshold']:
        return 'hold'
    if signals['energy'] >= settings['shape_threshold']:
        return 'pop'
    return 'subtle'


def generate(project_id, captions, audio_features, settings=None):
    settings = settings_value(settings)
    if captions.get('project_id') != project_id or audio_features.get('project_id') != project_id:
        raise ValueError('Project identities do not match')
    if audio_features.get('source', {}).get('transcript_checksum') != captions.get('raw_transcript_checksum'):
        raise ValueError('Caption and audio-feature transcript identities do not match')
    key = {'schema_version': SCHEMA_VERSION, 'project_id': project_id, 'policy_version': POLICY_VERSION,
           'source_audio_features_checksum': audio_features.get('content_checksum'),
           'source_captions_checksum': captions.get('content_checksum'), 'settings': settings}
    warnings, decisions, aggregates = [], [], []
    if not settings['reactive_enabled']:
        value = {**key, 'decisions': [], 'caption_aggregates': [], 'warnings': [],
                 'summary': {'eligible_caption_count': len(captions.get('items', [])),
                             'eligible_word_count': sum(len(item.get('words', [])) for item in captions.get('items', [])),
                             'decision_count': 0,
                             'behavior_counts': {name: 0 for name in ('none', 'subtle', 'pop', 'hold', 'punch')},
                             'strong_count': 0, 'cooldown_suppressed_count': 0, 'rate_limited_count': 0}}
        value['content_checksum'] = engine.content_checksum(value)
        validate(value)
        return value
    feature_index = {}
    for feature in audio_features.get('words', []):
        identity = (feature.get('segment_id'), feature.get('word_index'))
        if identity in feature_index:
            raise ValueError('Duplicate audio-feature word identity')
        feature_index[identity] = feature
    candidates, selected_by_caption = [], []
    for caption_order, caption in enumerate(captions.get('items', [])):
        caption_decisions = []
        for word_order, word in enumerate(caption.get('words', [])):
            identity = (word.get('segment_id'), word.get('word_index'))
            feature = feature_index.get(identity)
            reason = None
            if not feature:
                reason = 'missing_feature_record'
            elif not feature.get('validity', {}).get('feature_valid') or feature.get('features') is None:
                reason = 'invalid_feature_record'
            elif (not _number(feature.get('start')) or not _number(feature.get('end')) or
                  not math.isclose(feature['start'] + captions['audio_offset'], word.get('original_start', math.inf), abs_tol=1e-9) or
                  not math.isclose(feature['end'] + captions['audio_offset'], word.get('original_end', math.inf), abs_tol=1e-9)):
                reason = 'timing_identity_mismatch'
            if reason:
                warnings.append({'type': reason, 'caption_id': caption['caption_id'],
                                 'segment_id': word.get('segment_id'), 'word_index': word.get('word_index'),
                                 'message': 'Caption word has no safely linkable valid audio feature; reactive emphasis was omitted.'})
                continue
            try:
                score, signals = score_features(feature['features'], settings)
            except ValueError:
                warnings.append({'type': 'invalid_feature_record', 'caption_id': caption['caption_id'],
                                 'segment_id': word.get('segment_id'), 'word_index': word.get('word_index'),
                                 'message': 'Caption word audio features are invalid; reactive emphasis was omitted.'})
                continue
            behavior = _candidate_behavior(score, signals, settings)
            raw = {'caption_id': caption['caption_id'], 'source_word_id': feature['word_id'],
                   'segment_id': word['segment_id'], 'word_index': word['word_index'], 'text': word['text'],
                   'original_start': word['original_start'], 'original_end': word['original_end'],
                   'score': score, 'signals': signals, 'behavior': behavior,
                   'strong': behavior in STRONG_BEHAVIORS, 'suppression': None,
                   'reasons': [name for name in ('energy', 'pause', 'duration') if signals[name] >= settings['punch_component_threshold']]}
            decisions.append(raw)
            caption_decisions.append((word_order, raw))
        if caption_decisions:
            _, selected = max(caption_decisions, key=lambda item: (item[1]['score'], -item[0]))
            for _, decision in caption_decisions:
                if decision is not selected and decision['strong']:
                    decision.update(behavior='subtle', strong=False, suppression='caption_selection')
            if selected['strong']:
                selected_word_order = next(order for order, decision in caption_decisions if decision is selected)
                candidates.append((selected['original_start'], caption_order, selected_word_order, selected))
            selected_by_caption.append((caption['caption_id'], selected))
    approved_times = []
    cooldown_count = rate_count = 0
    for _, _, _, decision in sorted(candidates, key=lambda item: item[:3]):
        recent = [time for time in approved_times if decision['original_start'] - time < settings['rate_window_seconds']]
        suppression = None
        if approved_times and decision['original_start'] - approved_times[-1] < settings['cooldown_seconds']:
            suppression = 'cooldown_suppressed'; cooldown_count += 1
        elif len(recent) >= settings['max_strong_per_window']:
            suppression = 'rate_limited'; rate_count += 1
        if suppression:
            decision.update(behavior='subtle', strong=False, suppression=suppression)
        else:
            approved_times.append(decision['original_start'])
    for decision in decisions:
        decision['decision_id'] = 'emphasis-' + engine.content_checksum({'identity': key, 'decision': decision})
    for caption_id, selected in selected_by_caption:
        aggregates.append({'caption_id': caption_id, 'selected_decision_id': selected['decision_id'],
                           'source_word_id': selected['source_word_id'], 'score': selected['score'],
                           'behavior': selected['behavior'], 'strong': selected['strong']})
    behavior_counts = {name: sum(item['behavior'] == name for item in decisions)
                       for name in ('none', 'subtle', 'pop', 'hold', 'punch')}
    summary = {'eligible_caption_count': len(captions.get('items', [])),
               'eligible_word_count': sum(len(item.get('words', [])) for item in captions.get('items', [])),
               'decision_count': len(decisions), 'behavior_counts': behavior_counts,
               'strong_count': sum(item['strong'] for item in decisions),
               'cooldown_suppressed_count': cooldown_count, 'rate_limited_count': rate_count}
    value = {**key, 'decisions': decisions, 'caption_aggregates': aggregates, 'warnings': warnings, 'summary': summary}
    value['content_checksum'] = engine.content_checksum(value)
    validate(value)
    return value


def validate(value):
    if (not isinstance(value, dict) or value.get('schema_version') != SCHEMA_VERSION or
            value.get('policy_version') != POLICY_VERSION or
            not isinstance(value.get('source_audio_features_checksum'), str) or
            not isinstance(value.get('source_captions_checksum'), str) or
            value.get('content_checksum') != engine.content_checksum(value)):
        raise ValueError('Invalid emphasis identity')
    json.dumps(value, sort_keys=True, allow_nan=False)
    for decision in value.get('decisions', []):
        if not _number(decision.get('score')) or not 0 <= decision['score'] <= 1:
            raise ValueError('Invalid emphasis score')
        if decision.get('behavior') not in ('none', 'subtle', 'pop', 'hold', 'punch'):
            raise ValueError('Invalid emphasis behavior')
        if decision.get('strong') != (decision.get('behavior') in STRONG_BEHAVIORS):
            raise ValueError('Invalid strong-emphasis marker')
        if any(not _number(number) or not 0 <= number <= 1 for number in decision.get('signals', {}).values()):
            raise ValueError('Invalid emphasis signal')
    return value
