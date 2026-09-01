"""Phase 08A deterministic PCM feature, cache, API and immutability tests."""
from array import array
import copy
import json
import math
from pathlib import Path
import unittest
from unittest.mock import patch
import wave

import test_transcript_review as fixtures
from python.audio_features import features as f
from python.media import normalization as n
from python.transcription import engine as e


class AudioFeatureTests(unittest.TestCase):
    setUp = fixtures.TranscriptReviewTests.setUp

    def configure(self, words, amplitudes=None, frames=32000):
        amplitudes = amplitudes or [(0, frames, 1000)]
        samples = array('h', [0]) * frames
        for first, last, value in amplitudes:
            for index in range(max(0, first), min(frames, last)):
                samples[index] = value
        with wave.open(str(self.path/'normalized/audio.wav'), 'wb') as stream:
            stream.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            stream.writeframes(samples.tobytes())
        self.project['outputs']['audio.wav'] = n.checksum(self.path/'normalized/audio.wav')
        self.raw['source']['audio_checksum'] = self.project['outputs']['audio.wav']
        self.raw['segments'] = [dict(start=0, end=frames/16000, text=' words', confidence=None, words=words)]
        self.raw['content_checksum'] = e.content_checksum(self.raw)
        n.atomic_json(self.raw_path, self.raw)
        n.save_project(self.path, self.project, 'completed')

    def analyze(self):
        return f.analyze(self.root, self.project)

    def read(self):
        return f.read_audio_features(self.root, self.project)

    @staticmethod
    def word(start, end, text='word'):
        return dict(start=start, end=end, text=text, confidence=.9)

    def test_constant_amplitude_exact_rms_and_boundaries(self):
        self.configure([self.word(0, .25), self.word(1.75, 2)], [(0, 32000, 8192)])
        self.analyze(); value = self.read()
        self.assertAlmostEqual(value['words'][0]['features']['rms'], .25)
        self.assertAlmostEqual(value['words'][1]['features']['rms'], .25)
        self.assertEqual(value['words'][0]['features']['pause_before'], None)
        self.assertEqual(value['words'][-1]['features']['pause_after'], None)
        self.assertEqual(value['normalization']['valid_word_count'], 2)

    def test_louder_quieter_and_quiet_project_relative_normalization(self):
        words = [self.word(0, .5, 'quiet'), self.word(.5, 1, 'loud')]
        self.configure(words, [(0, 8000, 2), (8000, 16000, 8)])
        self.analyze(); value = self.read(); quiet, loud = [w['features'] for w in value['words']]
        self.assertLess(quiet['rms'], loud['rms'])
        self.assertEqual(quiet['normalized_energy'], 0)
        self.assertEqual(loud['normalized_energy'], 1)
        self.assertLess(quiet['relative_energy_db'], 0)
        self.assertGreater(loud['relative_energy_db'], 0)

    def test_zero_near_zero_equal_and_clipped_audio_are_finite(self):
        words = [self.word(0, .25), self.word(.25, .5)]
        for amplitude, expected in ((0, 0), (1, .5), (32767, .5), (-32768, .5)):
            with self.subTest(amplitude=amplitude):
                self.configure(words, [(0, 8000, amplitude)])
                self.analyze(); value = self.read()
                self.assertTrue(all(math.isfinite(x) for w in value['words'] for x in w['features'].values() if x is not None))
                self.assertTrue(all(w['features']['normalized_energy'] == expected for w in value['words']))
                self.assertTrue(all(0 <= w['features']['normalized_energy'] <= 1 for w in value['words']))
                self.assertEqual(any(w['validity']['clipped_samples'] for w in value['words']), abs(amplitude) >= 32767)
                self.assertNotIn('NaN', json.dumps(value)); self.assertNotIn('Infinity', json.dumps(value))

    def test_very_short_word_duration_and_relative_duration(self):
        words = [self.word(0, .000001, 'tiny'), self.word(.1, .3, 'normal'), self.word(.4, 1.2, 'held')]
        self.configure(words)
        self.analyze(); value = self.read(); result = [w['features'] for w in value['words']]
        self.assertAlmostEqual(result[0]['duration'], .000001)
        self.assertGreater(result[2]['relative_duration'], result[1]['relative_duration'])
        self.assertLessEqual(result[2]['relative_duration'], f.SETTINGS['relative_duration_cap'])

    def test_pause_before_after_overlap_and_tolerance(self):
        words = [self.word(0, .2, 'a'), self.word(.5, .8, 'b'), self.word(.7995, 1, 'c'), self.word(.9, 1.2, 'd')]
        self.configure(words)
        self.analyze(); value = self.read(); got = [w['features'] for w in value['words']]
        self.assertAlmostEqual(got[0]['pause_after'], .3)
        self.assertAlmostEqual(got[1]['pause_before'], .3)
        self.assertEqual(got[2]['pause_before'], 0)
        self.assertEqual(got[2]['pause_after'], 0)
        self.assertEqual([w['type'] for w in value['warnings']].count('overlapping_word_timing'), 1)

    def test_missing_invalid_word_timing_is_explicit_and_partial(self):
        words = [self.word(0, .2), {'text':'missing','confidence':None}, self.word(.4, .6)]
        self.configure(words)
        self.analyze(); value = self.read()
        self.assertEqual(len(value['words']), 3)
        self.assertFalse(value['words'][1]['validity']['timing_valid'])
        self.assertIsNone(value['words'][1]['features'])
        self.assertEqual(value['normalization']['valid_word_count'], 2)
        self.assertEqual(value['warnings'][0]['type'], 'invalid_word_timing')

    def test_empty_and_single_word_transcripts(self):
        self.configure([]); self.analyze(); empty = self.read()
        self.assertEqual(empty['words'], []); self.assertIsNone(empty['normalization']['project_duration_median'])
        self.configure([self.word(.1, .4)]); self.analyze(); one = self.read()['words'][0]['features']
        self.assertEqual(one['relative_duration'], 1); self.assertEqual(one['relative_energy_db'], 0)
        self.assertIsNone(one['pause_before']); self.assertIsNone(one['pause_after'])

    def test_determinism_stable_ids_and_cache(self):
        self.configure([self.word(0, .2), self.word(.3, .6)])
        self.assertFalse(self.analyze()['reused']); first = self.read(); before = (self.path/'analysis/audio_features.json').read_bytes()
        self.assertTrue(self.analyze()['reused']); second = self.read()
        self.assertEqual(first, second); self.assertEqual(before, (self.path/'analysis/audio_features.json').read_bytes())
        self.assertEqual([w['word_id'] for w in first['words']], [w['word_id'] for w in second['words']])

    def test_cache_invalidates_audio_timing_transcript_and_settings_not_other_phases(self):
        self.configure([self.word(0, .2), self.word(.3, .6)]); self.analyze(); original = self.read()
        # Phase 05/06/07 state is outside identity.
        (self.path/'overrides').mkdir(exist_ok=True)
        for relative in ('overrides/user_transcript.json','overrides/user_cuts.json','analysis/cuts.json','analysis/captions.json'):
            (self.path/relative).write_text('{}')
        self.assertTrue(self.analyze()['reused'])
        self.configure([self.word(0, .25), self.word(.3, .6)])
        self.assertFalse(self.analyze()['reused']); self.assertNotEqual(original['source']['timing_checksum'], self.read()['source']['timing_checksum'])
        changed = dict(f.SETTINGS); changed['local_window_words'] = 4
        with patch.object(f, 'SETTINGS', changed): self.assertFalse(self.analyze()['reused'])
        self.configure([self.word(0, .25), self.word(.3, .6)], [(0, 32000, 2000)])
        self.assertFalse(self.analyze()['reused'])

    def test_atomic_failure_preserves_previous_and_all_inputs(self):
        self.configure([self.word(0, .2)]); self.analyze()
        output = self.path/'analysis/audio_features.json'; previous = output.read_bytes()
        protected = [self.path/'source/test.mp4', self.path/'normalized/proxy.mp4', self.path/'normalized/audio.wav',
                     self.raw_path, self.path/'project.json']
        (self.path/'overrides').mkdir(exist_ok=True)
        for relative in ('overrides/user_transcript.json','overrides/user_cuts.json','analysis/cuts.json','analysis/captions.json'):
            path = self.path/relative; path.write_text('{}'); protected.append(path)
        before = {path:path.read_bytes() for path in protected}
        changed = dict(f.SETTINGS); changed['local_window_words'] = 4
        with patch.object(f, 'SETTINGS', changed), patch.object(Path, 'replace', side_effect=OSError('full')):
            with self.assertRaises(n.MediaError): self.analyze()
        self.assertEqual(output.read_bytes(), previous); self.assertEqual(list(self.path.rglob('*.tmp')), [])
        for path, data in before.items(): self.assertEqual(path.read_bytes(), data)

    def test_corrupt_or_failed_input_preserves_previous(self):
        self.configure([self.word(0, .2)]); self.analyze(); output = self.path/'analysis/audio_features.json'; old = output.read_bytes()
        for path in (self.raw_path, self.path/'normalized/audio.wav'):
            before = path.read_bytes(); path.write_bytes(b'bad')
            with self.assertRaises(n.MediaError): self.analyze()
            self.assertEqual(output.read_bytes(), old); path.write_bytes(before)

    def test_api_job_read_retry_and_reused_import(self):
        self.configure([self.word(0, .2)])
        endpoint = f'/projects/{self.pid}/jobs'
        response = self.client.post(endpoint, headers=self.headers, json={'stage':'audio_features'})
        self.assertEqual(response.status_code, 202); self.jobs.thread.join(5)
        job = self.jobs.latest(self.pid); self.assertEqual(job['status'], 'succeeded'); self.assertFalse(job['reused'])
        self.assertEqual(self.client.get(f'/projects/{self.pid}/audio-features').json(), self.read())
        response = self.client.post(endpoint, headers=self.headers, json={'stage':'audio_features'})
        self.jobs.thread.join(5); self.assertTrue(self.jobs.read(self.pid, response.json()['job_id'])['reused'])
        failed = self.jobs.read(self.pid, response.json()['job_id']); failed['status'] = 'failed'; self.jobs.save(failed)
        retry = self.jobs.retry(self.pid, failed['job_id']); self.jobs.thread.join(5)
        self.assertEqual(retry['stage'], 'audio_features')
        with patch.object(n, 'require_tools'): reused = n.create_project(self.root, 'test.mp4', 4)
        reused['source']['sha256'] = self.project['source']['sha256']; reused['reused_project_id'] = self.pid
        n.save_project(self.root/reused['project_id'], reused, 'reused')
        self.assertEqual(f.read_audio_features(self.root, reused)['project_id'], self.pid)


if __name__ == '__main__':
    unittest.main()
