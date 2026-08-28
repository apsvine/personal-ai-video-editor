"""Pure, deterministic Phase 07 caption planning. No I/O or inferred alignment."""
import math
import unicodedata

from python.editing import cuts
from python.transcription import engine as e
from python.transcription.review import valid_text

SCHEMA = 1
PLANNER = 'genuine-word-captions-v1'
SETTINGS = dict(max_words=5, max_characters=42, pause_threshold=.5,
                minimum_duration=.7, maximum_duration=3.0, punctuation_break=True)


def settings_value(settings=None):
    value = dict(SETTINGS)
    if settings is not None:
        if not isinstance(settings, dict) or set(settings) - set(SETTINGS):
            raise ValueError('Unknown caption settings')
        value.update(settings)
    for key in ('max_words', 'max_characters'):
        if type(value[key]) is not int or not 1 <= value[key] <= (20 if key == 'max_words' else 200):
            raise ValueError('Invalid caption count limit')
    for key in ('pause_threshold', 'minimum_duration', 'maximum_duration'):
        if type(value[key]) not in (int, float) or not math.isfinite(value[key]) or not 0 < value[key] <= 60:
            raise ValueError('Invalid caption duration setting')
        value[key] = float(value[key])
    if value['minimum_duration'] > value['maximum_duration'] or type(value['punctuation_break']) is not bool:
        raise ValueError('Invalid caption settings')
    return value


def lexical(token):
    # Only edge punctuation and casing may differ. Internal spelling is not alignment.
    while token and unicodedata.category(token[0]).startswith('P'):
        token = token[1:]
    while token and unicodedata.category(token[-1]).startswith('P'):
        token = token[:-1]
    return token.casefold()


def punctuation(token, strong=False):
    token = token.rstrip('"\'”’)]}')
    return token.endswith(tuple('.!?。！？' if strong else '.,!?;:，。！？；：'))


def group_text(group):
    return ''.join(('' if i == 0 else word['joiner']) + word['text'] for i, word in enumerate(group))


def generate(project_id, raw, effective_texts, duration, removed, audio_offset=0, settings=None):
    """Inputs are raw Phase 04 data, one effective string per segment, accepted spans.

    Word references always point into raw.segments[].words[]. Original intervals
    are proxy seconds (raw audio seconds + the verified Phase 06 audio offset).
    """
    settings = settings_value(settings)
    timeline = cuts.mapping(duration, removed)  # shared validation/topology, not new mapping math
    if (type(audio_offset) not in (int, float) or not math.isfinite(audio_offset)
            or not 0 <= audio_offset < duration):
        raise ValueError('Invalid audio offset')
    if not isinstance(raw, dict) or type(raw.get('schema_version')) is not int:
        raise ValueError('Invalid raw transcript')
    e.validate(raw, duration)
    if raw.get('content_checksum') != e.content_checksum(raw):
        raise ValueError('Invalid raw transcript identity')
    if not isinstance(effective_texts, list) or len(effective_texts) != len(raw['segments']):
        raise ValueError('Effective text must match raw segments')
    for text in effective_texts:
        valid_text(text)
    key = dict(schema_version=SCHEMA, project_id=project_id, planner_version=PLANNER,
               raw_transcript_checksum=raw['content_checksum'],
               effective_transcript_checksum=e.content_checksum({'texts': effective_texts}),
               effective_cut_checksum=e.content_checksum({'source_duration': duration, 'removed': timeline['removed'],
                                                          'audio_offset': audio_offset}),
               settings=settings, source_duration=duration, audio_offset=audio_offset,
               removed=timeline['removed'])
    warnings, items = [], []

    def warn(kind, segment_id, message, word_index=None, caption_id=None):
        warnings.append(dict(type=kind, segment_id=segment_id, word_index=word_index,
                             caption_id=caption_id, message=message))

    def fits(group):
        return (len(group) <= settings['max_words']
                and len(group_text(group)) <= settings['max_characters']
                and group[-1]['original_end'] - group[0]['original_start'] <= settings['maximum_duration'])

    def compatible(left, right):
        a, b = left[-1], right[0]
        return (a['span'] == b['span'] and a['word_index'] + 1 == b['word_index']
                and b['original_start'] - a['original_end'] < settings['pause_threshold']
                and not (settings['punctuation_break'] and punctuation(a['text'], strong=True)))

    for index, (segment, text) in enumerate(zip(raw['segments'], effective_texts)):
        sid = str(index)
        tokens = text.split()
        words = segment['words']
        if not tokens:
            if words:
                warn('empty_text', sid, 'Empty effective text: this segment has no captions.')
            continue
        raw_tokens = [w['text'].strip() for w in words]
        exact_chunks = (' '.join(text.split()) == ' '.join(''.join(w['text'] for w in words).split())
                        and all(len(t.split()) == 1 and t for t in raw_tokens))
        if exact_chunks:
            # Some providers emit separately timed fragments (" first", "-year").
            # Exact reconstruction needs no inferred alignment; retain their joiners.
            tokens = raw_tokens
            joiners = [' ' if w['text'][0].isspace() else '' for w in words]
        elif (len(tokens) == len(words) and all(len(t.split()) == 1 and lexical(t) for t in raw_tokens)
              and [lexical(t) for t in tokens] == [lexical(t) for t in raw_tokens]):
            joiners = [' '] * len(words)
        else:
            warn('ambiguous_text_timing', sid,
                 'Effective text could not be mapped safely to authoritative word timing. Segment omitted.')
            continue
        safe = []
        for wi, (word, token, joiner) in enumerate(zip(words, tokens, joiners)):
            start, end = word['start'] + audio_offset, word['end'] + audio_offset
            if not 0 <= start <= end <= duration:
                raise ValueError('Word is outside the proxy timeline')
            if start == end:
                warn('zero_duration_word', sid, 'Zero-duration word omitted; no display interval can be inferred.', wi)
                continue
            span = next((i for i, s in enumerate(timeline['keep']) if s['start'] <= start < end <= s['end']), None)
            if span is None:
                warn('removed_word', sid, 'Word intersects an accepted removal and was omitted without clipping.', wi)
                continue
            entry = dict(segment_id=sid, word_index=wi, text=token, joiner=joiner,
                         original_start=start, original_end=end, span=span)
            safe.append(entry)
        # Keep exact no-space fragments together; a split must not manufacture a
        # partial lexical word. If any fragment is unsafe, omit its whole atom.
        atoms = []
        for word in safe:
            if atoms and not word['joiner'] and word['word_index'] == atoms[-1][-1]['word_index'] + 1:
                atoms[-1].append(word)
            else:
                atoms.append([word])
        groups = []
        for atom in atoms:
            first, last = atom[0], atom[-1]
            wi = first['word_index']
            following = last['word_index'] + 1
            if ((wi > 0 and not first['joiner']) or (following < len(words) and not joiners[following])
                    or first['span'] != last['span']):
                warn('unsafe_word_fragments', sid, 'Incomplete or cut-crossing word fragments omitted as a unit.', wi)
                continue
            if not fits(atom):
                warn('word_exceeds_limits', sid, 'Indivisible timed word exceeds maximum limits; omitted.', wi)
                continue
            if (not groups or not compatible(groups[-1], atom) or not fits(groups[-1] + atom)
                    or (settings['punctuation_break'] and punctuation(groups[-1][-1]['text']))):
                groups.append(atom)
            else:
                groups[-1].extend(atom)
        # Short groups try the following neighbor first, then the previous.
        # Soft punctuation may merge; sentence stops, pauses, omissions and cuts may not.
        pos = 0
        while pos < len(groups):
            group = groups[pos]
            if group[-1]['original_end'] - group[0]['original_start'] < settings['minimum_duration']:
                if pos + 1 < len(groups) and compatible(group, groups[pos + 1]) and fits(group + groups[pos + 1]):
                    groups[pos:pos + 2] = [group + groups[pos + 1]]
                    continue
                if pos and compatible(groups[pos - 1], group) and fits(groups[pos - 1] + group):
                    groups[pos - 1:pos + 1] = [groups[pos - 1] + group]
                    pos -= 1
                    continue
            pos += 1
        for group in groups:
            start, end = group[0]['original_start'], group[-1]['original_end']
            first = cuts.original_to_edited(duration, removed, start)
            last = cuts.original_to_edited(duration, removed, end)
            # A retained caption may END exactly where a removed half-open span starts.
            # The shared helper's splice_time is that endpoint, not retained speech.
            edited_end = last['splice_time'] if last['removed'] else last['edited_time']
            refs = [{k: v for k, v in word.items() if k != 'span'} for word in group]
            item = dict(original_start=start, original_end=end, edited_start=first['edited_time'],
                        edited_end=edited_end, text=group_text(group), words=refs,
                        layout='center', behavior='normal', emphasis=0.0)
            item['caption_id'] = 'caption-' + e.content_checksum({'identity': key, 'item': item})
            items.append(item)
            if end - start < settings['minimum_duration']:
                warn('minimum_duration_unmet', sid,
                     'Caption retains genuine timing below the minimum; no safe adjacent merge exists.',
                     caption_id=item['caption_id'])
    value = {**key, 'items': items, 'warnings': warnings}
    value['content_checksum'] = e.content_checksum(value)
    return value
