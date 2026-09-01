"""Phase 08B pure policy, distribution, cache, atomicity, API and immutability tests."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_caption_store as caption_fixtures
from python.audio_features import features
from python.editing import caption_store
from python.emphasis import policy, store
from python.media import normalization as n
from python.transcription import engine


PID = 'a' * 32


def artifacts(values, groups=None):
    groups = groups or [[i] for i in range(len(values))]
    words = []
    for i, value in enumerate(values):
        start = float(i * 2)
        words.append({'word_id': f'word-{i:064x}', 'segment_id': '0', 'word_index': i, 'text': f'w{i}',
                      'start': start, 'end': start + .3, 'features': {
                          'normalized_energy': value.get('energy', .2), 'relative_energy_db': value.get('relative', 0),
                          'relative_duration': value.get('duration', 1), 'pause_before': value.get('before', 0),
                          'pause_after': value.get('after', 0), 'rms': .1, 'energy_dbfs': -20,
                          'duration': .3},
                      'validity': {'feature_valid': value.get('valid', True)}})
    audio = {'schema_version': 1, 'project_id': PID, 'source': {'transcript_checksum': 'b' * 64},
             'words': words, 'content_checksum': ''}
    audio['content_checksum'] = engine.content_checksum(audio)
    items = []
    for ci, indices in enumerate(groups):
        refs = [{'segment_id': '0', 'word_index': i, 'text': f'w{i}', 'original_start': words[i]['start'],
                 'original_end': words[i]['end']} for i in indices]
        items.append({'caption_id': f'caption-{ci:064x}', 'words': refs})
    captions = {'schema_version': 1, 'project_id': PID, 'raw_transcript_checksum': 'b' * 64,
                'audio_offset': 0.0, 'items': items, 'content_checksum': ''}
    captions['content_checksum'] = engine.content_checksum(captions)
    return captions, audio


class PolicyTests(unittest.TestCase):
    def generate(self, values, groups=None, settings=None):
        captions, audio = artifacts(values, groups)
        return policy.generate(PID, captions, audio, settings)

    def test_score_bounds_zero_strong_duration_pause_and_combination(self):
        cases = [
            ({'energy': 0, 'relative': -20, 'duration': 1}, 'none'),
            ({'energy': 1, 'relative': 6, 'duration': 1}, 'subtle'),
            ({'energy': 1, 'relative': 6, 'duration': 1, 'before': .75}, 'pop'),
            ({'energy': .6, 'relative': 3, 'duration': 4, 'before': .75}, 'hold'),
            ({'energy': .4, 'relative': 0, 'duration': 1, 'before': 2}, 'subtle'),
            ({'energy': 1, 'relative': 6, 'duration': 4, 'before': 2}, 'punch'),
        ]
        for item, behavior in cases:
            with self.subTest(item=item):
                got = self.generate([item])['decisions'][0]
                self.assertTrue(0 <= got['score'] <= 1)
                self.assertEqual(got['behavior'], behavior)

    def test_formula_exact_and_quiet_relative_variation(self):
        score, signals = policy.score_features({'normalized_energy': .8, 'relative_energy_db': 3,
            'relative_duration': 1.75, 'pause_before': .375, 'pause_after': 0})
        self.assertAlmostEqual(signals['energy'], .68)
        self.assertEqual(signals['pause'], .5); self.assertEqual(signals['duration'], .5)
        self.assertAlmostEqual(score, .59)
        quiet = self.generate([{'energy': .1, 'relative': 0}, {'energy': .4, 'relative': 5}])
        self.assertLess(quiet['decisions'][0]['score'], quiet['decisions'][1]['score'])
        self.assertFalse(any(item['strong'] for item in quiet['decisions']))

    def test_behavior_boundaries_and_explicit_priority(self):
        settings = policy.settings_value()
        low = {'energy': 0, 'pause': 0, 'duration': 0}
        self.assertEqual(policy._candidate_behavior(.349999, low, settings), 'none')
        self.assertEqual(policy._candidate_behavior(.35, low, settings), 'subtle')
        self.assertEqual(policy._candidate_behavior(.62, low, settings), 'subtle')
        self.assertEqual(policy._candidate_behavior(.719999, {'energy': 1, 'pause': 1, 'duration': 1}, settings), 'subtle')
        self.assertEqual(policy._candidate_behavior(.72, {'energy': .75, 'pause': 0, 'duration': 0}, settings), 'pop')
        self.assertEqual(policy._candidate_behavior(.72, {'energy': .75, 'pause': 0, 'duration': .75}, settings), 'hold')
        self.assertEqual(policy._candidate_behavior(.85, {'energy': .75, 'pause': .65, 'duration': .75}, settings), 'punch')

    def test_determinism_ids_ties_no_nan_or_randomness(self):
        values = [{'energy': .8, 'relative': 4}, {'energy': .8, 'relative': 4}]
        a = self.generate(values, [[0, 1]]); b = self.generate(values, [[0, 1]])
        self.assertEqual(a, b); self.assertEqual(a['caption_aggregates'][0]['source_word_id'], a['decisions'][0]['source_word_id'])
        self.assertEqual(len({x['decision_id'] for x in a['decisions']}), 2)
        self.assertNotIn('NaN', json.dumps(a)); self.assertNotIn('Infinity', json.dumps(a))

    def test_missing_invalid_mismatch_and_no_linkable_caption_warn(self):
        captions, audio = artifacts([{'valid': False}])
        got = policy.generate(PID, captions, audio); self.assertFalse(got['decisions']); self.assertEqual(got['warnings'][0]['type'], 'invalid_feature_record')
        audio['words'] = []; audio['content_checksum'] = engine.content_checksum(audio)
        got = policy.generate(PID, captions, audio); self.assertEqual(got['warnings'][0]['type'], 'missing_feature_record')
        captions, audio = artifacts([{}]); audio['words'][0]['start'] = 99; audio['content_checksum'] = engine.content_checksum(audio)
        got = policy.generate(PID, captions, audio); self.assertEqual(got['warnings'][0]['type'], 'timing_identity_mismatch')

    def test_multiple_source_words_selects_one_and_ordinary_is_restrained(self):
        values = [{'energy': .2} for _ in range(20)]
        got = self.generate(values, [list(range(5)), list(range(5, 10)), list(range(10, 15)), list(range(15, 20))])
        self.assertEqual(len(got['decisions']), 20); self.assertEqual(len(got['caption_aggregates']), 4)
        self.assertEqual(got['summary']['strong_count'], 0)

    def test_unreferenced_cut_or_ambiguous_words_are_never_resurrected(self):
        captions, audio = artifacts([{'energy': 1, 'relative': 6, 'before': 1}])
        captions['items'] = []  # Phase 07 omitted the unsafe source word.
        captions['content_checksum'] = engine.content_checksum(captions)
        got = policy.generate(PID, captions, audio)
        self.assertEqual(got['decisions'], []); self.assertEqual(got['summary']['eligible_caption_count'], 0)
        self.assertEqual(got['summary']['eligible_word_count'], 0)

    def test_cooldown_rate_limit_separation_and_minority(self):
        values = [{'energy': 1, 'relative': 6, 'before': .75} for _ in range(8)]
        captions, audio = artifacts(values)
        # Default two-second spacing: cooldown passes, rolling rate limit retains only two per eight seconds.
        got = policy.generate(PID, captions, audio)
        self.assertEqual(got['summary']['strong_count'], 4)
        self.assertEqual(got['summary']['rate_limited_count'], 4)
        self.assertLess(got['summary']['strong_count'], len(got['caption_aggregates']))
        # Close the second word to prove the independent cooldown.
        captions, audio = artifacts(values[:2]); audio['words'][1]['start'] = .8; audio['words'][1]['end'] = 1.1
        captions['items'][1]['words'][0].update(original_start=.8, original_end=1.1)
        audio['content_checksum'] = engine.content_checksum(audio); captions['content_checksum'] = engine.content_checksum(captions)
        close = policy.generate(PID, captions, audio)
        self.assertEqual(close['summary']['cooldown_suppressed_count'], 1)
        self.assertEqual(close['decisions'][1]['behavior'], 'subtle')
        self.assertEqual(close['decisions'][1]['suppression'], 'cooldown_suppressed')
        raw_score, _ = policy.score_features(audio['words'][1]['features'])
        self.assertEqual(close['decisions'][1]['score'], raw_score)
        far = self.generate(values[:2]); self.assertEqual(far['summary']['strong_count'], 2)

    def test_candidate_order_is_source_time_then_caption_then_word(self):
        values = [{'energy': 1, 'relative': 6, 'before': .75} for _ in range(2)]
        captions, audio = artifacts(values)
        # Reverse caption order while keeping source times 0 then 2. Chronological policy must still approve time 0 first.
        captions['items'].reverse(); captions['content_checksum'] = engine.content_checksum(captions)
        got = policy.generate(PID, captions, audio, {'cooldown_seconds': 3})
        early = next(item for item in got['decisions'] if item['original_start'] == 0)
        late = next(item for item in got['decisions'] if item['original_start'] == 2)
        self.assertTrue(early['strong']); self.assertEqual(late['suppression'], 'cooldown_suppressed')

    def test_reactive_off_is_phase07_equivalent_nonreactive(self):
        captions, audio = artifacts([{'energy': 1, 'relative': 6}])
        before = copy.deepcopy(captions)
        got = policy.generate(PID, captions, audio, {'reactive_enabled': False})
        self.assertEqual(got['decisions'], []); self.assertEqual(got['caption_aggregates'], [])
        self.assertEqual(captions, before); self.assertEqual(got['summary']['strong_count'], 0)
        self.assertEqual(got['summary']['behavior_counts'], {name: 0 for name in ('none','subtle','pop','hold','punch')})

    def test_identity_invalidates_every_cache_dimension(self):
        captions, audio = artifacts([{}]); base = policy.generate(PID, captions, audio)
        audio['content_checksum'] = 'c' * 64
        self.assertNotEqual(base['content_checksum'], policy.generate(PID, captions, audio)['content_checksum'])
        captions['content_checksum'] = 'd' * 64
        self.assertNotEqual(base['content_checksum'], policy.generate(PID, captions, audio)['content_checksum'])
        self.assertNotEqual(base['content_checksum'], policy.generate(PID, captions, audio, {'cooldown_seconds': 2})['content_checksum'])
        with patch.object(policy, 'POLICY_VERSION', 'test-policy'):
            self.assertNotEqual(base['content_checksum'], policy.generate(PID, captions, audio)['content_checksum'])


class EmphasisStoreTests(unittest.TestCase):
    setUp = caption_fixtures.CaptionStoreTests.setUp

    def prepare(self):
        caption_store.plan(self.root, self.project)
        features.analyze(self.root, self.project)

    def test_cache_api_job_retry_off_and_immutability(self):
        self.prepare()
        protected = [self.path/'analysis/captions.json', self.path/'analysis/audio_features.json', self.raw_path,
                     self.cuts_path, self.path/'project.json', self.path/'normalized/audio.wav']
        before = {path: path.read_bytes() for path in protected}
        self.assertFalse(store.analyze(self.root, self.project)['reused'])
        self.assertTrue(store.analyze(self.root, self.project)['reused'])
        endpoint = f'/projects/{self.pid}/jobs'
        response = self.client.post(endpoint, headers=self.headers,
            json={'stage':'emphasis', 'emphasis_settings':{'reactive_enabled':False}})
        self.assertEqual(response.status_code, 202); self.jobs.thread.join(5)
        job = self.jobs.read(self.pid, response.json()['job_id'])
        self.assertEqual(job['status'], 'succeeded'); self.assertFalse(store.read_emphasis(self.root, self.project)['settings']['reactive_enabled'])
        self.assertEqual(self.client.get(f'/projects/{self.pid}/emphasis').status_code, 200)
        job['status'] = 'failed'; self.jobs.save(job)
        retry = self.jobs.retry(self.pid, job['job_id']); self.jobs.thread.join(5)
        self.assertFalse(retry['emphasis_settings']['reactive_enabled'])
        for path, data in before.items(): self.assertEqual(path.read_bytes(), data)

    def test_cache_invalidation_atomic_failure_and_failed_inputs_preserve_old(self):
        self.prepare(); store.analyze(self.root, self.project)
        output = self.path/'analysis/emphasis.json'; old = output.read_bytes()
        self.assertFalse(store.analyze(self.root, self.project, {'cooldown_seconds': 2})['reused'])
        changed = output.read_bytes(); self.assertNotEqual(old, changed)
        with patch.object(Path, 'replace', side_effect=OSError('disk full')):
            with self.assertRaises(n.MediaError): store.analyze(self.root, self.project, {'cooldown_seconds': 3})
        self.assertEqual(output.read_bytes(), changed); self.assertEqual(list(self.path.rglob('*.tmp')), [])
        for input_path in (self.path/'analysis/captions.json', self.path/'analysis/audio_features.json'):
            data = input_path.read_bytes(); input_path.write_text('{}')
            with self.assertRaises(n.MediaError): store.analyze(self.root, self.project)
            self.assertEqual(output.read_bytes(), changed); input_path.write_bytes(data)

    def test_settings_guards(self):
        endpoint = f'/projects/{self.pid}/jobs'
        for body in ({'stage':'emphasis','emphasis_settings':{'reactive_enabled':1}},
                     {'stage':'plan','emphasis_settings':{}}, {'stage':'emphasis','caption_settings':{}}):
            self.assertEqual(self.client.post(endpoint, headers=self.headers, json=body).status_code, 422)


if __name__ == '__main__':
    unittest.main()
