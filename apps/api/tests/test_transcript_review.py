"""Phase 05 API regressions; tiny synthetic artifacts, no inference/network."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import wave
from unittest.mock import patch

from fastapi.testclient import TestClient
from app import media
from app.main import app
from python.common.jobs import JobManager
from python.media import normalization as n
from python.transcription import engine as e


class TranscriptReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(self.temp).resolve() / 'projects'
        with patch.object(n, 'require_tools'):
            self.project = n.create_project(self.root, 'test.mp4', 4)
        self.pid = self.project['project_id']
        self.path = self.root / self.pid
        (self.path / 'source/test.mp4').write_bytes(b'test')
        with wave.open(str(self.path / 'normalized/audio.wav'), 'wb') as stream:
            stream.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            stream.writeframes(b'\0\0' * 32000)
        (self.path / 'normalized/proxy.mp4').write_bytes(b'proxy')
        (self.path / 'normalized/metadata.json').write_text('{}')
        self.project.update(audio_status='available', outputs={p.name: n.checksum(p) for p in (self.path/'normalized').iterdir()})
        self.project['source']['sha256'] = n.checksum(self.path/'source/test.mp4')
        n.save_project(self.path, self.project, 'completed')
        self.raw = dict(schema_version=1, language='en', timing_quality='model_estimated_word_alignment',
                        source=dict(audio_checksum=self.project['outputs']['audio.wav'], source_checksum=self.project['source']['sha256']),
                        segments=[dict(start=i, end=i+1, text=f' word{i}', confidence=None,
                                       words=[dict(start=i, end=i+1, text=f' word{i}', confidence=.9)]) for i in range(2)])
        self.raw['content_checksum'] = e.content_checksum(self.raw)
        (self.path/'analysis').mkdir()
        self.raw_path = self.path/'analysis/transcript.json'
        n.atomic_json(self.raw_path, self.raw)
        self.before = self.raw_path.read_bytes()
        self.override_path = self.path/'overrides/user_transcript.json'
        self.jobs = JobManager(self.root)
        self.enterContext(patch.object(media, 'PROJECTS', self.root))
        self.enterContext(patch.object(media, 'MANAGER', self.jobs))
        self.client = self.enterContext(TestClient(app))
        self.url = f'/projects/{self.pid}/transcript'
        self.headers = {'X-Media-Import': '1'}
        self.identity = {'source_transcript_checksum': self.raw['content_checksum']}

    def edit(self, segment='0', text='Corrected नमस्ते 🌍', **kwargs):
        return self.client.put(self.url+'/overrides/'+segment, headers=self.headers,
                               json={**self.identity, 'text': text, **kwargs})

    def reset(self, segment=None, identity=None):
        endpoint = '/overrides/reset' if segment is None else f'/overrides/{segment}/reset'
        return self.client.post(self.url+endpoint, headers=self.headers, json=identity or self.identity)

    def test_cached_transcription_review_without_overrides(self):
        # Reproduce a genuine engine cache hit, not merely a fabricated job flag.
        model = Path(self.temp) / 'model'
        model.mkdir()
        for name in ('model.bin', 'config.json', 'tokenizer.json', 'vocabulary.txt'):
            (model / name).write_text('{}')
        self.raw.update(e.identity(self.project, model, e.provider.SETTINGS))
        self.raw['content_checksum'] = e.content_checksum(self.raw)
        n.atomic_json(self.raw_path, self.raw)
        before = self.raw_path.read_bytes()
        with patch.object(e, 'model_path', return_value=model), patch.object(
                e, 'run_worker', side_effect=AssertionError('Cache hit must not run inference')):
            response = self.client.post(f'/projects/{self.pid}/jobs',
                                        headers=self.headers, json={'stage': 'transcribe'})
            self.assertEqual(response.status_code, 202)
            self.jobs.thread.join(5)
            self.assertFalse(self.jobs.thread.is_alive())
        job = self.jobs.latest(self.pid)
        self.assertEqual(job['status'], 'succeeded')
        self.assertTrue(job['reused'])
        self.assertEqual(job['result_project_id'], self.pid)

        # Also protect resolution when a reused import points at this output project.
        with patch.object(n, 'require_tools'):
            reused = n.create_project(self.root, 'test.mp4', 4)
        reused['source']['sha256'] = self.project['source']['sha256']
        reused['reused_project_id'] = self.pid
        n.save_project(self.root / reused['project_id'], reused, 'reused')
        for requested_id in (self.pid, reused['project_id']):
            with self.subTest(requested_id=requested_id):
                self.assertFalse(self.override_path.parent.exists())
                response = self.client.get(f'/projects/{requested_id}/transcript/review')
                self.assertEqual(response.status_code, 200)
                value = response.json()
                self.assertEqual(value['project_id'], self.pid)
                self.assertEqual(value['override_state'], 'none')
                self.assertIsNone(value['override_message'])
                self.assertEqual(value['source_transcript_checksum'], self.raw['content_checksum'])
                self.assertEqual(value['segments'], [
                    {**segment, 'segment_id': str(index), 'raw_text': segment['text'], 'edited': False}
                    for index, segment in enumerate(self.raw['segments'])])
                self.assertFalse(self.override_path.parent.exists())
                self.assertFalse((self.root / reused['project_id'] / 'overrides').exists())
                self.assertEqual(self.raw_path.read_bytes(), before)
                self.assertEqual(self.client.get(self.url).json(), self.raw)

    def test_edit_immutable_raw_and_timing(self):
        response = self.edit()
        self.assertEqual(response.status_code, 200)
        value = response.json()
        self.assertTrue(value['segments'][0]['edited'])
        for raw, merged in zip(self.raw['segments'], value['segments']):
            for field in ('start', 'end', 'words', 'confidence'):
                self.assertEqual(raw[field], merged[field])
        self.assertEqual(self.raw_path.read_bytes(), self.before)
        self.assertEqual(self.client.get(self.url).json(), self.raw)
        self.assertEqual(e.read_transcript(self.root, self.project), self.raw)

    def test_minimal_override_and_api_reload(self):
        self.assertEqual(self.edit().status_code, 200)
        expected = dict(schema_version=1, project_id=self.pid, **self.identity, segments={'0': {'text': 'Corrected नमस्ते 🌍'}})
        self.assertEqual(json.loads(self.override_path.read_text()), expected)
        # A fresh HTTP client and manager need no in-memory overlay state.
        with patch.object(media, 'MANAGER', JobManager(self.root)):
            client = TestClient(app)
            self.addCleanup(client.close)
            value = client.get(self.url+'/review').json()
            self.assertEqual(value['segments'][0]['text'], expected['segments']['0']['text'])
        self.assertEqual(list(self.override_path.parent.glob('*.tmp')), [])

    def test_reset_segment_all_and_idempotence(self):
        self.edit(); self.edit('1', 'Second correction')
        value = self.reset('0').json()
        self.assertFalse(value['segments'][0]['edited'])
        self.assertTrue(value['segments'][1]['edited'])
        self.assertTrue(self.override_path.exists())
        self.assertEqual(self.reset().status_code, 200)
        self.assertFalse(self.override_path.exists())
        self.assertEqual(self.reset().status_code, 200)
        self.assertEqual([s['text'] for s in self.client.get(self.url+'/review').json()['segments']], [' word0', ' word1'])
        self.assertEqual(self.raw_path.read_bytes(), self.before)

    def test_same_as_raw_removes_override_and_empty_text_valid(self):
        self.assertEqual(self.edit(text='').status_code, 200)
        self.assertEqual(self.edit(text=' word0').status_code, 200)
        self.assertFalse(self.override_path.exists())

    def test_stale_override_detected_and_explicit_reset(self):
        self.edit()
        original_override = self.override_path.read_bytes()
        changed = copy.deepcopy(self.raw)
        changed['segments'] = changed['segments'][:1]
        changed['segments'][0]['text'] = 'new source text'
        changed['content_checksum'] = e.content_checksum(changed)
        n.atomic_json(self.raw_path, changed)
        value = self.client.get(self.url+'/review').json()
        self.assertEqual(value['override_state'], 'stale')
        self.assertFalse(value['segments'][0]['edited'])
        self.assertEqual(value['segments'][0]['text'], 'new source text')
        self.assertEqual(self.edit().status_code, 409)
        self.assertEqual(self.reset().status_code, 409)
        self.assertEqual(self.edit(source_transcript_checksum=changed['content_checksum']).status_code, 409)
        self.assertEqual(self.override_path.read_bytes(), original_override)
        self.assertEqual(self.reset(identity={'source_transcript_checksum': changed['content_checksum']}).status_code, 200)
        self.assertFalse(self.override_path.exists())
        self.assertEqual(self.client.get(self.url).json(), changed)

    def test_invalid_segment_checksum_and_request_schema(self):
        for segment in ('2', '-1', '00', 'abc', '9999999999999999999999'):
            self.assertEqual(self.edit(segment).status_code, 422)
        self.assertEqual(self.edit(source_transcript_checksum='a'*64).status_code, 409)
        for checksum in ('bad', 42, None):
            self.assertEqual(self.edit(source_transcript_checksum=checksum).status_code, 422)
        for text in (42, None, {}, 'x'*10001, 'a\0b'):
            self.assertEqual(self.edit(text=text).status_code, 422)
        self.assertEqual(self.edit(start=1).status_code, 422)
        self.assertFalse(self.override_path.exists())

    def test_invalid_utf8_and_surrogate_text_rejected(self):
        endpoint = self.url+'/overrides/0'
        headers = {**self.headers, 'Content-Type': 'application/json'}
        response = self.client.put(endpoint, headers=headers,
            content=json.dumps({**self.identity, 'text': chr(0xd800)}))
        self.assertEqual(response.status_code, 422)
        response = self.client.put(endpoint, headers=headers, content=b'\xff')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.override_path.exists())

    def test_malformed_override_returns_raw_and_can_reset(self):
        self.override_path.parent.mkdir()
        malformed = ['{broken', '[]', 'null', '{"schema_version": true}', '\ud800']
        good = dict(schema_version=1, project_id=self.pid, **self.identity, segments={'0': {'text': 'edit'}})
        for update in ({'schema_version': True}, {'project_id': 'other'}, {'segments': {'9': {'text': 'bad'}}},
                       {'segments': {'00': {'text': 'bad'}}}, {'segments': {'0': {'text': 9}}},
                       {'segments': {'0': {'text': '\ud800'}}}, {'extra': 1}):
            malformed.append(json.dumps({**good, **update}))
        for content in malformed:
            self.override_path.write_bytes(content.encode('utf-8', errors='surrogatepass'))
            response = self.client.get(self.url+'/review')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['override_state'], 'invalid')
            self.assertFalse(response.json()['segments'][0]['edited'])
            self.assertEqual(self.edit().status_code, 409)
            self.assertEqual(self.client.get(self.url).json(), self.raw)
            self.assertEqual(self.reset().status_code, 200)
            self.assertFalse(self.override_path.exists())

    def test_atomic_publication_and_failure_keep_old_file(self):
        self.edit()
        before = self.override_path.read_bytes()
        original_replace = Path.replace
        observed = []
        def replace(temp, destination):
            if destination == self.override_path:
                self.assertEqual(destination.read_bytes(), before)
                self.assertEqual(json.loads(temp.read_text())['segments']['0']['text'], 'Next')
                observed.append(temp)
            return original_replace(temp, destination)
        with patch.object(Path, 'replace', replace):
            self.assertEqual(self.edit(text='Next').status_code, 200)
        self.assertEqual(len(observed), 1)
        before = self.override_path.read_bytes()
        with patch.object(Path, 'replace', side_effect=OSError('disk failure')):
            self.assertEqual(self.edit(text='Lost').status_code, 500)
        self.assertEqual(self.override_path.read_bytes(), before)
        self.assertEqual(list(self.override_path.parent.glob('*.tmp')), [])
        self.assertEqual(self.raw_path.read_bytes(), self.before)

    def test_guard_missing_project_transcript_and_symlinks(self):
        payload = {**self.identity, 'text': 'no'}
        endpoint = self.url+'/overrides/0'
        self.assertEqual(self.client.put(endpoint, json=payload).status_code, 403)
        self.assertEqual(self.client.put(endpoint, json=payload, headers={**self.headers, 'Origin':'https://foreign.example'}).status_code, 403)
        for pid in ('bad', 'a'*32, '%2e%2e%2foutside'):
            self.assertEqual(self.client.get(f'/projects/{pid}/transcript/review').status_code, 404)
        outside = Path(self.temp)/'outside'; outside.mkdir()
        self.override_path.parent.symlink_to(outside, target_is_directory=True)
        self.assertEqual(self.edit().status_code, 400)
        self.assertEqual(list(outside.iterdir()), [])
        self.override_path.parent.unlink()
        self.raw_path.unlink()
        self.assertEqual(self.client.get(self.url+'/review').status_code, 404)
        self.assertEqual(self.edit().status_code, 404)

    def test_busy_operation_rejects_writes_without_mutation(self):
        self.jobs.reserve()
        try:
            self.assertEqual(self.edit().status_code, 409)
            self.assertEqual(self.reset().status_code, 409)
            self.assertEqual(self.client.get(self.url+'/review').status_code, 200)
        finally:
            self.jobs.release()
        self.assertFalse(self.override_path.exists())
        self.assertEqual(self.edit().status_code, 200)

    def test_reused_import_resolves_output_overrides(self):
        with patch.object(n, 'require_tools'):
            reused = n.create_project(self.root, 'test.mp4', 4)
        reused['source']['sha256'] = self.project['source']['sha256']
        reused['reused_project_id'] = self.pid
        n.save_project(self.root/reused['project_id'], reused, 'reused')
        self.url = f'/projects/{reused["project_id"]}/transcript'
        self.assertEqual(self.edit().json()['project_id'], self.pid)
        self.assertTrue(self.override_path.is_file())
        self.assertFalse((self.root/reused['project_id']/'overrides').exists())

    def test_empty_transcript_review(self):
        self.raw['segments'] = []
        self.raw['content_checksum'] = e.content_checksum(self.raw)
        n.atomic_json(self.raw_path, self.raw)
        response = self.client.get(self.url+'/review')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['segments'], [])
