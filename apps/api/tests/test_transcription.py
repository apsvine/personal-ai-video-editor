"""Phase 04 tests use fake providers and synthetic PCM; no model inference/network."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import wave
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient
from app.main import app
from app import media
from python.common.jobs import JobManager
from python.media import normalization as n
from python.transcription import engine as e, provider


class TranscriptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(self.temp).resolve() / 'projects'
        with patch.object(n, 'require_tools'):
            self.project = n.create_project(self.root, 'test.mp4', 4)
        self.pid = self.project['project_id']
        self.path = self.root / self.pid
        (self.path / 'source/test.mp4').write_bytes(b'test')
        with wave.open(str(self.path / 'normalized/audio.wav'), 'wb') as wav:
            wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            wav.writeframes(b'\0\0' * 32000)
        (self.path / 'normalized/proxy.mp4').write_bytes(b'proxy')
        (self.path / 'normalized/metadata.json').write_text('{}')
        self.project.update(audio_status='available', outputs={p.name:n.checksum(p) for p in (self.path/'normalized').iterdir()})
        self.project['source']['sha256'] = n.checksum(self.path/'source/test.mp4')
        n.save_project(self.path, self.project, 'completed')
        self.model = Path(self.temp) / 'model'; self.model.mkdir()
        for name in ('model.bin', 'config.json', 'tokenizer.json', 'vocabulary.txt'):
            (self.model/name).write_text('{}')
        self.payload = dict(language='en', timing_quality='model_estimated_word_alignment', segments=[
            dict(start=0., end=1., text=' Hello', confidence=None, words=[dict(text=' Hello', start=0., end=1., confidence=.9)])])
        self.fake = Mock(side_effect=lambda *args: copy.deepcopy(self.payload))
        self.enterContext(patch.object(e, 'model_path', return_value=self.model))

    def run_transcript(self, **kwargs):
        return e.transcribe(self.root, self.project, runner=self.fake, **kwargs)

    def test_schema_cache_and_no_normalization(self):
        with patch.object(n, 'normalize', side_effect=AssertionError('must not normalize')):
            self.assertFalse(self.run_transcript()['reused'])
            self.assertTrue(self.run_transcript()['reused'])
        self.assertEqual(self.fake.call_count, 1)
        value = e.read_transcript(self.root, self.project)
        self.assertEqual(value['schema_version'], 1)
        self.assertEqual(value['provider']['version'], '1.2.1')
        self.assertEqual(value['segments'][0]['confidence'], None)
        self.assertTrue((self.path/'analysis/transcript.json').is_file())
        self.assertFalse((self.path/'transcription').exists())

    def test_identity_changes_and_corrupt_cache(self):
        self.run_transcript()
        self.run_transcript(settings={**provider.SETTINGS, 'beam_size': 1})
        (self.model/'model.bin').write_text('different weights')
        self.run_transcript()
        (self.path/'analysis/transcript.json').write_text('{}')
        self.run_transcript()
        self.assertEqual(self.fake.call_count, 4)

    def test_failure_and_atomic_failure_preserve_transcript(self):
        self.run_transcript()
        path = self.path/'analysis/transcript.json'; before = path.read_bytes()
        self.fake.side_effect = RuntimeError('provider crash')
        with self.assertRaises(RuntimeError):
            self.run_transcript(settings={**provider.SETTINGS, 'beam_size': 1})
        self.assertEqual(path.read_bytes(), before)
        self.fake.side_effect = lambda *a: copy.deepcopy(self.payload)
        with patch.object(n, 'atomic_json', side_effect=OSError('disk full')), self.assertRaises(OSError):
            self.run_transcript(settings={**provider.SETTINGS, 'beam_size': 1})
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list((self.path/'analysis').glob('*.tmp')), [])

    def test_missing_model_and_audio(self):
        with self.assertRaises(n.MediaError) as caught:
            self.run_transcript(model=self.model/'missing')
        self.assertEqual(caught.exception.code, 'model_not_installed')
        self.fake.assert_not_called()
        (self.path/'normalized/audio.wav').write_bytes(b'corrupt')
        with self.assertRaises(n.MediaError) as caught:
            self.run_transcript()
        self.assertEqual(caught.exception.code, 'normalization_not_ready')

    def test_no_audio_and_unfinished(self):
        self.project.update(audio_status='no_audio')
        del self.project['outputs']['audio.wav']
        with self.assertRaises(n.MediaError) as caught:
            self.run_transcript()
        self.assertEqual(caught.exception.code, 'no_audio')
        self.project['normalization_status'] = 'extracting_audio'
        with self.assertRaises(n.MediaError):
            self.run_transcript()

    def test_empty_speech_is_valid(self):
        self.payload['segments'] = []
        self.run_transcript()
        self.assertEqual(e.read_transcript(self.root, self.project)['segments'], [])

    def test_invalid_timing_preserves_previous(self):
        self.run_transcript()
        before = (self.path/'analysis/transcript.json').read_bytes()
        for invalid in (-1, float('nan'), 5, True):
            self.payload['segments'][0]['words'][0]['end'] = invalid
            with self.assertRaises(ValueError):
                self.run_transcript(settings={**provider.SETTINGS, 'beam_size': 1})
        self.assertEqual((self.path/'analysis/transcript.json').read_bytes(), before)

    def test_reused_project(self):
        with patch.object(n, 'require_tools'):
            reused = n.create_project(self.root, 'other.mp4', 4)
        reused.update(normalization_status='reused', reused_project_id=self.pid)
        reused['source']['sha256'] = self.project['source']['sha256']
        result = e.transcribe(self.root, reused, runner=self.fake)
        self.assertEqual(result['project_id'], self.pid)
        self.assertEqual(e.read_transcript(self.root, reused)['language'], 'en')

    def test_api_jobs_retry_and_recovery(self):
        jobs = JobManager(self.root)
        self.addCleanup(jobs.close)
        headers = {'X-Media-Import': '1'}
        url = f'/projects/{self.pid}'
        original = e.transcribe
        def execute(root, project):
            return original(root, project, runner=self.fake)
        with patch.object(media, 'PROJECTS', self.root), patch.object(media, 'MANAGER', jobs), TestClient(app) as client:
            self.assertEqual(client.post(url+'/jobs', json={'stage':'transcribe'}).status_code, 403)
            with patch.object(e, 'transcribe', side_effect=n.MediaError('fake_failure', 'Failed')):
                response = client.post(url+'/jobs', json={'stage':'transcribe'}, headers=headers)
                self.assertEqual(response.status_code, 202)
                jobs.thread.join(5)
            job = jobs.latest(self.pid)
            self.assertEqual(job['status'], 'failed')
            with patch.object(e, 'transcribe', side_effect=execute):
                retry = client.post(url+f'/jobs/{job["job_id"]}/retry', headers=headers).json()
                jobs.thread.join(5)
            self.assertEqual(retry['stage'], 'transcribe')
            self.assertEqual(retry['retry_of'], job['job_id'])
            self.assertEqual(jobs.latest(self.pid)['status'], 'succeeded')
            self.assertEqual(client.get(url+'/transcript').json()['language'], 'en')
            current = jobs.latest(self.pid); current['status'] = 'running'; jobs.save(current)
            jobs.recover()
            self.assertEqual(jobs.latest(self.pid)['status'], 'interrupted')

    def test_worker_failure_is_structured_without_loading_model(self):
        jobs = JobManager(self.root); self.addCleanup(jobs.close)
        def worker(command, log):
            request = json.loads(Path(command[-1]).read_text())
            Path(request['output']).write_text(json.dumps({'error':{'code':'provider_not_installed','message':'Install provider'}}))
        with patch.object(e, 'run_worker', side_effect=worker):
            jobs.start(self.pid, stage='transcribe'); jobs.thread.join(5)
        self.assertEqual(jobs.latest(self.pid)['error']['code'], 'provider_not_installed')

    def test_offline_adapter_arguments_and_values(self):
        import sys
        from types import SimpleNamespace
        word = SimpleNamespace(word='Hello', start=0., end=1., probability=.8)
        segment = SimpleNamespace(start=0., end=1., text='Hello', words=[word])
        model = Mock(); model.transcribe.return_value = (iter([segment]), SimpleNamespace(language='en'))
        constructor = Mock(return_value=model)
        with patch.dict(sys.modules, {'faster_whisper': SimpleNamespace(WhisperModel=constructor)}), patch('importlib.metadata.version', return_value='1.2.1'):
            value = provider.transcribe(self.path/'normalized/audio.wav', self.model, provider.SETTINGS)
        self.assertTrue(constructor.call_args.kwargs['local_files_only'])
        self.assertEqual(constructor.call_args.args, (str(self.model),))
        self.assertEqual(constructor.call_args.kwargs['device'], 'cpu')
        self.assertTrue(model.transcribe.call_args.kwargs['word_timestamps'])
        self.assertIsNone(value['segments'][0]['confidence'])
        self.assertEqual(value['segments'][0]['words'][0]['confidence'], .8)

    def test_real_worker_cancel_shutdown_and_exclusion(self):
        import sys
        import threading
        import subprocess
        from python.common import control
        self.run_transcript()
        before = (self.path/'analysis/transcript.json').read_bytes()
        for shutdown in (False, True):
            jobs = JobManager(self.root); self.addCleanup(jobs.close)
            entered = threading.Event(); children = []
            popen = subprocess.Popen
            def spawn(*args, **kwargs):
                child = popen(*args, **kwargs); children.append(child); entered.set(); return child
            def run(root, project):
                control.run_worker([sys.executable, '-c', 'import time; time.sleep(30)'], self.path/'logs/transcription.log')
                return project
            with patch.object(control.subprocess, 'Popen', side_effect=spawn):
                job = jobs.start(self.pid, stage='transcribe', runner=run)
                self.assertTrue(entered.wait(2))
                with self.assertRaises(n.MediaError) as caught:
                    JobManager(self.root).start(self.pid, stage='transcribe')
                self.assertEqual(caught.exception.code, 'job_busy')
                if shutdown:
                    jobs.close()
                else:
                    jobs.cancel(self.pid, job['job_id']); jobs.thread.join(5)
            self.assertFalse(jobs.thread.is_alive())
            self.assertIsNotNone(children[0].poll())
            self.assertEqual(jobs.latest(self.pid)['status'], 'interrupted' if shutdown else 'cancelled')
            self.assertEqual((self.path/'analysis/transcript.json').read_bytes(), before)

    def test_well_formed_corruption_is_not_reused(self):
        self.run_transcript()
        path = self.path/'analysis/transcript.json'
        value = json.loads(path.read_text()); value['segments'][0]['text'] = 'corrupt'
        path.write_text(json.dumps(value))
        self.assertFalse(self.run_transcript()['reused'])
        self.assertEqual(self.fake.call_count, 2)

    def test_cli_uses_manager_and_preserves_stage(self):
        import importlib.util
        import sys
        spec = importlib.util.spec_from_file_location('debug_cli', Path(__file__).resolve().parents[3]/'scripts/transcribe_project.py')
        cli = importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)
        jobs = Mock(); jobs.start.return_value = {'job_id': 'test'}; jobs.read.return_value = {'status': 'succeeded'}
        with patch.object(cli, 'JobManager', return_value=jobs), patch.object(sys, 'argv', ['transcribe_project.py', self.pid]), patch('builtins.print'):
            self.assertEqual(cli.main(), 0)
        jobs.start.assert_called_once_with(self.pid, stage='transcribe')
        jobs.startup.assert_called_once(); jobs.close.assert_called_once()

    def test_transcription_hard_restart_orphan_lock_and_retry(self):
        import os, signal, subprocess, sys, time
        marker = self.root.parent / 'child-pid'
        repo = Path(__file__).resolve().parents[3]
        child_code = f"import os,time; from pathlib import Path; Path({str(marker)!r}).write_text(str(os.getpid())); time.sleep(30)"
        code = f"""
import sys,time
from pathlib import Path
sys.path.insert(0, {str(repo)!r})
from python.common.jobs import JobManager
from python.common.control import run_worker
from python.media import normalization as n
root = Path({str(self.root)!r})
def run(root, project):
    run_worker([sys.executable, '-c', {child_code!r}], root / project['project_id'] / 'logs/media.log')
    return project
jobs = JobManager(root)
jobs.start({self.pid!r}, runner=run, stage='transcribe')
time.sleep(30)
"""
        parent = subprocess.Popen([sys.executable, '-c', code], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        child_pid = None
        try:
            deadline = time.monotonic() + 4
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(marker.exists())
            child_pid = int(marker.read_text())
            parent.kill()
            parent.communicate(timeout=3)
            restarted = JobManager(self.root)
            self.addCleanup(restarted.close)
            restarted.recover()
            job = restarted.latest(self.pid)
            self.assertEqual(job['status'], 'interrupted')
            with self.assertRaises(n.MediaError) as caught:
                restarted.retry(self.pid, job['job_id'])
            self.assertEqual(caught.exception.code, 'job_busy')
            os.kill(child_pid, signal.SIGTERM)
            child_pid = None
            deadline = time.monotonic() + 3
            with patch.object(e, 'transcribe', side_effect=lambda root, project: project):
                while True:
                    try:
                        restarted.retry(self.pid, job['job_id'])
                        break
                    except n.MediaError as error:
                        if error.code != 'job_busy' or time.monotonic() >= deadline:
                            raise
                        time.sleep(0.01)
                restarted.thread.join(5)
                self.assertFalse(restarted.thread.is_alive())
                self.assertEqual(restarted.latest(self.pid)['status'], 'succeeded')
        finally:
            if parent.poll() is None:
                parent.kill()
            parent.communicate(timeout=3)
            if child_pid:
                os.kill(child_pid, signal.SIGTERM)


    def test_real_worker_entrypoint_missing_model_no_inference(self):
        import subprocess, sys
        request = Path(self.temp)/'request.json'
        output = Path(self.temp)/'result.json'
        request.write_text(json.dumps(dict(audio=str(self.path/'normalized/audio.wav'), model=str(self.model/'absent'), settings=provider.SETTINGS, output=str(output))))
        repo = Path(__file__).resolve().parents[3]
        result = subprocess.run([sys.executable, '-m', 'python.transcription.worker', str(request)], cwd=repo, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(output.read_text())['error']['code'], 'model_not_installed')

    def test_aligned_word_segment_envelope_atomic_publication(self):
        duration = 22.4801875
        audio = self.path/'normalized/audio.wav'
        with wave.open(str(audio), 'wb') as wav:
            wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            wav.writeframes(b'\0\0' * round(duration * 16000))
        self.project['outputs']['audio.wav'] = n.checksum(audio)
        n.save_project(self.path, self.project, 'completed')
        for start, end in ((15.779999999999998, 16.08), (21.2, 21.5)):
            with self.subTest(start=start, end=end):
                word = dict(text=' word', start=start, end=end, confidence=.9)
                self.payload['segments'] = [dict(start=15.92, end=21.36, text=' word', confidence=None, words=[word])]
                original = copy.deepcopy(self.payload)
                self.run_transcript(settings={**provider.SETTINGS, 'beam_size': 1 if start < 16 else 5})
                value = e.read_transcript(self.root, self.project)
                segment = value['segments'][0]
                self.assertEqual(segment['start'], min(15.92, start))
                self.assertEqual(segment['end'], max(21.36, end))
                self.assertEqual(segment['words'], [word])
                self.assertEqual(self.payload, original)
                e.validate(value, duration)
                self.assertEqual(list((self.path/'analysis').glob('*.tmp')), [])

    def test_envelope_does_not_repair_invalid_word_timing(self):
        self.run_transcript()
        path = self.path/'analysis/transcript.json'
        before = path.read_bytes()
        cases = [((-0.01, .2),), ((1.9, 2.1),), ((.8, .3),),
                 ((.5, .8), (.2, .4)), ((float('nan'), .5),), ((0., float('inf')),)]
        for intervals in cases:
            with self.subTest(intervals=intervals):
                self.payload['segments'][0]['words'] = [dict(text=' word', start=a, end=b, confidence=None) for a, b in intervals]
                with self.assertRaises(ValueError):
                    self.run_transcript(settings={**provider.SETTINGS, 'beam_size': 1})
                self.assertEqual(path.read_bytes(), before)

    def test_envelope_preserves_segment_order_and_wordless_rules(self):
        value = dict(schema_version=1, language='en', timing_quality='model_estimated_word_alignment',
                     segments=[dict(start=.5, end=1., text='', confidence=None, words=[])])
        self.assertEqual(e.segment_envelopes(value), value)
        e.validate(e.segment_envelopes(value), 2.)
        value['segments'][0]['text'] = 'speech without alignment'
        with self.assertRaises(ValueError):
            e.validate(e.segment_envelopes(value), 2.)
        first = copy.deepcopy(self.payload['segments'][0])
        second = dict(start=1., end=1.5, text='word', confidence=None,
                      words=[dict(start=.9, end=1.2, text='word', confidence=None)])
        value['segments'] = [first, second]
        with self.assertRaises(ValueError):
            e.validate(e.segment_envelopes(value), 2.)
        first['start'], first['end'] = 1., .5
        with self.assertRaises(ValueError):
            e.segment_envelopes(value)
