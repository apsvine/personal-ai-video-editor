"""Pure Phase 07 safety and deterministic grouping; synthetic text/times only."""
import copy
import unittest
from unittest.mock import patch
from python.editing import captions as c, cuts
from python.transcription import engine as e


def transcript(text='one two three four', starts=None, length=.3):
    tokens = text.split()
    starts = starts if starts is not None else [i * .4 for i in range(len(tokens))]
    words = [dict(text=t, start=s, end=s + length, confidence=.9) for t, s in zip(tokens, starts)]
    raw = dict(schema_version=1, language='en', timing_quality='model_estimated_word_alignment',
               segments=[dict(text=text, start=words[0]['start'], end=words[-1]['end'], confidence=None, words=words)] if words else [])
    raw['content_checksum'] = e.content_checksum(raw)
    return raw


class CaptionTests(unittest.TestCase):
    def plan(self, text='one two three four', starts=None, length=.3, corrected=None, removed=None, **settings):
        raw = transcript(text, starts, length)
        return c.generate('a' * 32, raw, [corrected if corrected is not None else text] if text else [],
                          20, removed or [], settings=settings)

    def test_punctuation(self):
        p = self.plan('one two. three four', minimum_duration=.1)
        self.assertEqual([i['text'] for i in p['items']], ['one two.', 'three four'])

    def test_punctuation_preference_off(self):
        self.assertEqual(len(self.plan('one. two', punctuation_break=False)['items']), 1)

    def test_pause(self):
        self.assertEqual([i['text'] for i in self.plan('one two three', [0, .4, 2])['items']], ['one two', 'three'])

    def test_max_words(self):
        self.assertEqual([i['text'] for i in self.plan(max_words=2)['items']], ['one two', 'three four'])

    def test_max_characters(self):
        self.assertTrue(all(len(i['text']) <= 7 for i in self.plan(max_characters=7)['items']))
        self.assertEqual(len(self.plan(max_characters=7)['items']), 3)

    def test_minimum_merge_soft_boundary(self):
        p = self.plan('one, two three', [0, .2, .4], .2)
        self.assertEqual([i['text'] for i in p['items']], ['one, two three'])
        self.assertAlmostEqual(p['items'][0]['original_end'], .6)

    def test_minimum_warning_no_extension(self):
        p = self.plan('one. two', [0, 2], .2)
        self.assertEqual(len(p['items']), 2)
        self.assertEqual([i['original_end'] for i in p['items']], [.2, 2.2])
        self.assertEqual([w['type'] for w in p['warnings']], ['minimum_duration_unmet'] * 2)

    def test_minimum_never_crosses_sentence(self):
        self.assertEqual(len(self.plan('one. two', [0, .2], .2)['items']), 2)

    def test_maximum_duration(self):
        p = self.plan(starts=[0, .4, .8, 1.2], maximum_duration=.75, minimum_duration=.1)
        self.assertEqual(len(p['items']), 2)
        self.assertTrue(all(i['original_end'] - i['original_start'] <= .75 for i in p['items']))

    def test_indivisible_word_omitted(self):
        for p in (self.plan('lengthy', max_characters=2), self.plan('one', length=4)):
            self.assertFalse(p['items'])
            self.assertEqual(p['warnings'][0]['type'], 'word_exceeds_limits')

    def test_determinism_and_ids(self):
        a, b = self.plan(), self.plan()
        self.assertEqual(a, b)
        self.assertEqual(len({i['caption_id'] for i in a['items']}), len(a['items']))
        self.assertNotEqual(a['items'][0]['caption_id'], self.plan(corrected='ONE TWO THREE FOUR')['items'][0]['caption_id'])

    def test_empty_transcript(self):
        p = self.plan('')
        self.assertEqual(p['items'], [])
        self.assertEqual(p['warnings'], [])

    def test_missing_word_timing_fails(self):
        raw = transcript()
        del raw['segments'][0]['words'][0]['start']
        raw['content_checksum'] = e.content_checksum(raw)
        with self.assertRaises((ValueError, KeyError)):
            c.generate('p', raw, ['one two three four'], 20, [])

    def test_wordless_speech_fails(self):
        raw = transcript()
        raw['segments'][0]['words'] = []
        raw['content_checksum'] = e.content_checksum(raw)
        with self.assertRaises(ValueError):
            c.generate('p', raw, ['one two three four'], 20, [])

    def test_corrected_case_punctuation_whitespace(self):
        p = self.plan('binary search', corrected='  BINARY   SEARCH! ')
        self.assertEqual(p['items'][0]['text'], 'BINARY SEARCH!')
        self.assertEqual([w['word_index'] for w in p['items'][0]['words']], [0, 1])
        self.assertEqual(p['items'][0]['original_end'], .7)

    def test_ambiguous_no_raw_fallback(self):
        for correction in ('one new two three four', 'four three two one', 'different words here now', 'won two three four'):
            p = self.plan(corrected=correction)
            self.assertFalse(p['items'])
            self.assertEqual(p['warnings'][0]['type'], 'ambiguous_text_timing')

    def test_empty_correction(self):
        self.assertFalse(self.plan(corrected='')['items'])

    def test_identity_timing(self):
        for i in self.plan()['items']:
            self.assertEqual((i['original_start'], i['original_end']), (i['edited_start'], i['edited_end']))

    def test_before_after_multiple_cuts(self):
        p = self.plan('one two three', [0, 4, 8], removed=[dict(start=1,end=3), dict(start=5,end=7)])
        self.assertEqual([i['edited_start'] for i in p['items']], [0, 2, 4])

    def test_group_splits_at_cut(self):
        p = self.plan('one two', [0, .4], .2, removed=[dict(start=.2, end=.4)], pause_threshold=2)
        self.assertEqual(len(p['items']), 2)
        self.assertEqual(p['items'][0]['edited_end'], .2)
        self.assertEqual(p['items'][1]['edited_start'], .2)

    def test_intersecting_word_omitted_not_clipped(self):
        p = self.plan('one two three', [0, .4, .8], .3, removed=[dict(start=.5,end=.6)])
        self.assertEqual([i['text'] for i in p['items']], ['one', 'three'])
        self.assertIn('removed_word', [w['type'] for w in p['warnings']])
        self.assertEqual(p['items'][1]['original_start'], .8)

    def test_no_caption_overlaps_removals(self):
        for a, b in ((0,.1),(.3,.4),(.35,.65),(.4,.9),(0,20)):
            p = self.plan(removed=[dict(start=a,end=b)])
            for i in p['items']:
                self.assertFalse(i['original_start'] < b and i['original_end'] > a)

    def test_shared_mapping_used(self):
        with patch.object(cuts, 'original_to_edited', wraps=cuts.original_to_edited) as mapper:
            p = self.plan()
        self.assertEqual(mapper.call_count, len(p['items']) * 2)

    def test_audio_offset(self):
        raw = transcript('one')
        p = c.generate('p', raw, ['one'], 20, [], audio_offset=1)
        self.assertEqual(p['items'][0]['original_start'], 1)
        self.assertEqual(p['items'][0]['original_end'], 1.3)

    def test_zero_duration_no_fabrication(self):
        p = self.plan('one two', [0,.4], 0)
        self.assertFalse(p['items'])
        self.assertEqual([w['type'] for w in p['warnings']], ['zero_duration_word'] * 2)

    def test_malformed_cuts(self):
        for removed in ([dict(start=1,end=0)], [dict(start=float('nan'),end=2)], [dict(start=1,end=30)],
                        [dict(start=1,end=3),dict(start=2,end=4)], [dict(start=True,end=2)]):
            with self.assertRaises(ValueError):
                self.plan(removed=removed)

    def test_malformed_transcript_and_settings(self):
        for raw in (None, [], {}, {**transcript(), 'content_checksum':'bad'}):
            with self.assertRaises(ValueError):
                c.generate('p', raw, [], 20, [])
        for settings in ({'max_words':True}, {'maximum_duration':float('inf')}, {'minimum_duration':4},
                         {'extra':1}, {'punctuation_break':1}, {'max_characters':0}):
            with self.assertRaises(ValueError):
                self.plan(**settings)

    def test_inputs_unchanged(self):
        raw = transcript()
        before = copy.deepcopy(raw)
        removed = [dict(start=2,end=3)]
        c.generate('p', raw, [raw['segments'][0]['text']], 20, removed)
        self.assertEqual(raw, before)
        self.assertEqual(removed, [dict(start=2,end=3)])

    def test_exact_raw_fragments_reconstruct_without_inferred_timing(self):
        raw = transcript('first -year student')
        raw['segments'][0]['text'] = 'first-year student'
        for word, text in zip(raw['segments'][0]['words'], [' first', '-year', ' student']):
            word['text'] = text
        raw['content_checksum'] = e.content_checksum(raw)
        p = c.generate('p', raw, ['first-year student'], 20, [], settings={'max_words':2})
        self.assertEqual([i['text'] for i in p['items']], ['first-year', 'student'])
        self.assertEqual([w['word_index'] for w in p['items'][0]['words']], [0,1])
        p = c.generate('p', raw, ['first-year student'], 20, [dict(start=.5,end=.6)])
        self.assertEqual([i['text'] for i in p['items']], ['student'])
