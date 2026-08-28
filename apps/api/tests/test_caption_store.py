"""Phase 07 API/cache/atomicity/job regressions using existing tiny fixtures."""
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch
import test_cut_review as fixtures
from python.common.control import checkpoint
from python.editing import caption_store as s, captions
from python.media import normalization as n
from python.transcription import engine as e


class CaptionStoreTests(unittest.TestCase):
    setUp = fixtures.CutReviewTests.setUp
    decide = fixtures.CutReviewTests.decide

    def generate(self, settings=None):
        return s.plan(self.root, self.project, settings)

    def read(self):
        return s.read_captions(self.root, self.project)

    def edit(self, text):
        return self.client.put(self.url + '/overrides/0', headers=self.headers,
            json={'source_transcript_checksum':self.raw['content_checksum'], 'text':text})

    def test_cache_and_pending_rejected_identity(self):
        self.assertFalse(self.generate()['reused'])
        before = self.read()
        self.assertTrue(self.generate()['reused'])
        self.assertEqual(self.decide('reject').status_code, 200)
        self.assertTrue(self.generate()['reused'])
        self.assertEqual(self.read(), before)
        self.assertEqual(before['items'][-1]['original_start'], before['items'][-1]['edited_start'])

    def test_accepted_invalidates(self):
        self.generate(); before = self.read()
        self.decide()
        with self.assertRaises(n.MediaError): self.read()
        self.assertFalse(self.generate()['reused'])
        after = self.read()
        self.assertNotEqual(before['effective_cut_checksum'], after['effective_cut_checksum'])
        self.assertAlmostEqual(after['items'][-1]['edited_start'], .7)
        self.assertEqual(after['items'][-1]['original_start'], 1.7)

    def test_correction_invalidates_and_no_fallback(self):
        self.generate(); before = self.read()
        self.assertEqual(self.edit('HELLO!').status_code, 200)
        with self.assertRaises(n.MediaError): self.read()
        self.assertFalse(self.generate()['reused'])
        after = self.read()
        self.assertNotEqual(before['effective_transcript_checksum'], after['effective_transcript_checksum'])
        self.assertEqual(after['items'][0]['text'], 'HELLO!')
        self.edit('many replacement words')
        self.generate()
        self.assertEqual([i['text'] for i in self.read()['items']], ['world'])
        self.assertEqual(self.read()['warnings'][0]['type'], 'ambiguous_text_timing')

    def test_settings_and_version_invalidate(self):
        self.generate(); old = self.read()
        self.assertFalse(self.generate({'max_words':2})['reused'])
        self.assertEqual(self.read()['settings']['max_words'], 2)
        with patch.object(captions, 'PLANNER', 'test-version'):
            self.assertFalse(self.generate()['reused'])
        self.assertNotEqual(old['content_checksum'], json.loads((self.path/'analysis/captions.json').read_text())['content_checksum'])

    def test_atomic_failure_and_immutability(self):
        self.decide()
        self.edit('HELLO')
        protected = [self.raw_path, self.override_path, self.cuts_path, self.decision_path,
                     self.path/'source/test.mp4', *list((self.path/'normalized').iterdir()), self.path/'project.json']
        before = {p:p.read_bytes() for p in protected}
        self.generate()
        output = self.path/'analysis/captions.json'
        previous = output.read_bytes()
        with patch.object(Path, 'replace', side_effect=OSError('full')):
            with self.assertRaises(n.MediaError): self.generate({'max_words':2})
        self.assertEqual(output.read_bytes(), previous)
        self.assertEqual(list(self.path.rglob('*.tmp')), [])
        for p, value in before.items(): self.assertEqual(p.read_bytes(), value)

    def test_failed_inputs_preserve_previous(self):
        self.generate()
        output = self.path/'analysis/captions.json'; old = output.read_bytes()
        for path in (self.raw_path, self.cuts_path):
            original = path.read_bytes()
            for bad in ('{}', '[]', 'null', '{bad'):
                path.write_text(bad)
                with self.assertRaises(n.MediaError): self.generate()
                self.assertEqual(output.read_bytes(), old)
            path.write_bytes(original)

    def test_invalid_overrides_fail_closed(self):
        self.generate()
        self.override_path.parent.mkdir(exist_ok=True)
        for path in (self.override_path, self.decision_path):
            path.write_text('{}')
            with self.assertRaises(n.MediaError): self.generate()
            with self.assertRaises(n.MediaError): self.read()
            path.unlink()

    def test_corrupt_caption_cache_rebuilt(self):
        self.generate(); expected = self.read()
        output = self.path/'analysis/captions.json'
        output.write_text('{}')
        with self.assertRaises(n.MediaError): self.read()
        self.assertFalse(self.generate()['reused'])
        self.assertEqual(self.read(), expected)

    def test_api_jobs_guards_settings_and_reuse(self):
        endpoint = f'/projects/{self.pid}/jobs'
        self.assertEqual(self.client.post(endpoint,json={'stage':'plan'}).status_code,403)
        self.assertEqual(self.client.post(endpoint,json={'stage':'plan'}, headers={**self.headers,'Origin':'https://foreign.test'}).status_code,403)
        for body in ({'stage':'plan','caption_settings':{'max_words':True}}, {'stage':'analyze','caption_settings':{}}, {'stage':'render'}):
            self.assertEqual(self.client.post(endpoint,headers=self.headers,json=body).status_code,422)
        for reused in (False, True):
            response = self.client.post(endpoint,headers=self.headers,json={'stage':'plan','caption_settings':{'max_words':2}})
            self.assertEqual(response.status_code,202)
            self.jobs.thread.join(5)
            job = self.jobs.latest(self.pid)
            self.assertEqual(job['status'],'succeeded')
            self.assertEqual(job['reused'],reused)
            self.assertEqual(job['caption_settings']['max_words'],2)
        response = self.client.get(f'/projects/{self.pid}/captions')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json(), self.read())

    def test_cancel_retry_preserves_settings_and_previous(self):
        self.generate()
        before = (self.path/'analysis/captions.json').read_bytes()
        entered, release = threading.Event(), threading.Event()
        original = s.expected
        def wait(*args):
            entered.set(); release.wait(5); checkpoint(.5)
            return original(*args)
        with patch.object(s,'expected',side_effect=wait):
            job = self.jobs.start(self.pid,stage='plan',caption_settings={'max_words':2})
            self.assertTrue(entered.wait(5))
            with self.assertRaises(n.MediaError): self.jobs.start(self.pid,stage='plan')
            self.jobs.cancel(self.pid,job['job_id']); release.set(); self.jobs.thread.join(5)
        self.assertEqual(self.jobs.read(self.pid,job['job_id'])['status'],'cancelled')
        self.assertEqual((self.path/'analysis/captions.json').read_bytes(),before)
        retried = self.jobs.retry(self.pid,job['job_id']); self.jobs.thread.join(5)
        self.assertEqual(retried['caption_settings']['max_words'],2)
        self.assertEqual(self.jobs.read(self.pid,retried['job_id'])['status'],'succeeded')
        self.assertEqual(self.read()['settings']['max_words'],2)

    def test_reused_import_reads_output_plan(self):
        self.generate()
        with patch.object(n,'require_tools'): reused = n.create_project(self.root,'test.mp4',4)
        reused['source']['sha256'] = self.project['source']['sha256']
        reused['reused_project_id'] = self.pid
        n.save_project(self.root/reused['project_id'],reused,'reused')
        self.assertEqual(s.read_captions(self.root,reused)['project_id'],self.pid)
        self.assertFalse((self.root/reused['project_id']/'analysis').exists())

    def test_checksum_rejects_python_boolean_number_equivalence(self):
        self.generate()
        output = self.path/'analysis/captions.json'
        saved = self.read()
        saved['items'][0]['emphasis'] = False
        n.atomic_json(output, saved)
        with self.assertRaises(n.MediaError): self.read()
        self.assertFalse(self.generate()['reused'])

    def test_recovered_plan_retry_keeps_settings(self):
        from python.common.jobs import JobManager
        job = self.jobs.start(self.pid,stage='plan',caption_settings={'max_words':2})
        self.jobs.thread.join(5)
        record = self.jobs.read(self.pid,job['job_id'])
        record['status'] = 'running'  # A record left behind after a process crash.
        self.jobs.save(record)
        recovery = JobManager(self.root)
        recovery.recover()
        self.assertEqual(recovery.read(self.pid,job['job_id'])['status'],'interrupted')
        retried = recovery.retry(self.pid,job['job_id'])
        recovery.thread.join(5)
        self.assertEqual(retried['stage'],'plan')
        self.assertEqual(retried['caption_settings']['max_words'],2)
        self.assertEqual(recovery.read(self.pid,retried['job_id'])['status'],'succeeded')
        recovery.close()
