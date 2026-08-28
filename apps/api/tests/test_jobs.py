"""Persistent lifecycle, subprocess cancellation, API recovery and output safety."""
import json
import os
import signal
import time
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app import media
from python.common.jobs import JobManager
from python.media import normalization as n


class JobTests(unittest.TestCase):
    def setUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(self.temp).resolve() / 'projects'
        self.enterContext(patch.object(n, 'require_tools'))
        self.project = n.create_project(self.root, 'test.mp4', 4)
        self.pid = self.project['project_id']
        (self.root / self.pid / 'source/test.mp4').write_bytes(b'test')
        self.jobs = JobManager(self.root)
        self.addCleanup(self.jobs.close)

    def finish(self, manager=None):
        manager = manager or self.jobs
        manager.thread.join(5)
        self.assertFalse(manager.thread.is_alive())
        return manager.latest(self.pid)

    def success(self, root, project):
        return project

    def test_lifecycle_progress_atomic(self):
        states = []
        save = self.jobs.save
        def capture(job):
            save(job)
            states.append((job['status'], job['progress']))
            self.assertEqual(self.jobs.read(self.pid, job['job_id']), job)
        def run(root, project):
            n.checkpoint(-2)
            n.checkpoint(4)
            return project
        with patch.object(self.jobs, 'save', side_effect=capture):
            self.jobs.start(self.pid, runner=run)
            job = self.finish()
        self.assertEqual([states[0][0], states[1][0], job['status']], ['pending', 'running', 'succeeded'])
        self.assertTrue(all(0 <= v <= 1 for _, v in states))
        self.assertTrue(job['started_at'] and job['finished_at'])
        path = self.jobs.path(self.pid, job['job_id'])
        before = path.read_bytes()
        with self.assertRaises(ValueError):
            n.atomic_json(path, {'progress': float('nan')})
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(path.parent.glob('*.tmp')), [])

    def test_failure_details_and_retry(self):
        def fail(root, project):
            raise n.MediaError('test_failure', 'Readable failure')
        first = self.jobs.start(self.pid, runner=fail)
        failed = self.finish()
        self.assertEqual(failed['status'], 'failed')
        self.assertEqual(failed['error'], {'code': 'test_failure', 'message': 'Readable failure'})
        self.assertIn('Readable failure', (self.root / self.pid / failed['log_path']).read_text())
        with patch.object(n, 'normalize', side_effect=self.success):
            retry = self.jobs.retry(self.pid, first['job_id'])
            self.assertEqual(self.finish()['status'], 'succeeded')
        self.assertEqual(retry['retry_of'], first['job_id'])
        self.assertEqual(self.jobs.read(self.pid, first['job_id'])['status'], 'failed')
        with self.assertRaises(n.MediaError):
            self.jobs.retry(self.pid, retry['job_id'])

    def test_restart_api_and_retry(self):
        self.jobs.start(self.pid, runner=self.success)
        job = self.finish()
        for state in ('pending', 'running'):
            job.update(status=state, finished_at=None)
            self.jobs.save(job)
            restarted = JobManager(self.root)
            restarted.recover()
            self.assertEqual(restarted.read(self.pid, job['job_id'])['status'], 'interrupted')
        with patch.object(media, 'PROJECTS', self.root), patch.object(media, 'MANAGER', restarted):
            with TestClient(app) as client:
                url = f'/projects/{self.pid}/jobs/{job["job_id"]}'
                self.assertEqual(client.get(url).json()['status'], 'interrupted')
                self.assertEqual(client.post(url + '/retry').status_code, 403)
                with patch.object(n, 'normalize', side_effect=self.success):
                    self.assertEqual(client.post(url + '/retry', headers={'X-Media-Import': '1'}).status_code, 202)
                    self.assertEqual(self.finish(restarted)['status'], 'succeeded')

    def test_cancel_subprocess_and_retry(self):
        entered = threading.Event()
        processes = []
        popen = subprocess.Popen
        def spawn(*args, **kwargs):
            child = popen(*args, **kwargs)
            processes.append(child)
            entered.set()
            return child
        def run(root, project):
            n.run_tool([sys.executable, '-c', 'import time; time.sleep(30)'], self.root / self.pid / 'logs/media.log')
            return project
        with patch.object(n.subprocess, 'Popen', side_effect=spawn):
            job = self.jobs.start(self.pid, runner=run)
            self.assertTrue(entered.wait(2))
            self.jobs.cancel(self.pid, job['job_id'])
            self.assertEqual(self.finish()['status'], 'cancelled')
        self.assertIsNotNone(processes[0].poll())
        self.assertEqual(JobManager(self.root).read(self.pid, job['job_id'])['status'], 'cancelled')
        with patch.object(n, 'normalize', side_effect=self.success):
            self.jobs.retry(self.pid, job['job_id'])
            self.assertEqual(self.finish()['status'], 'succeeded')

    def test_single_heavy_job(self):
        entered, release = threading.Event(), threading.Event()
        def run(root, project):
            entered.set()
            release.wait(3)
            return project
        self.jobs.start(self.pid, runner=run)
        try:
            self.assertTrue(entered.wait(2))
            for manager in (self.jobs, JobManager(self.root)):
                with self.assertRaises(n.MediaError) as caught:
                    manager.start(self.pid, runner=self.success)
                self.assertEqual(caught.exception.code, 'job_busy')
        finally:
            release.set()
            self.finish()

    def test_previous_outputs_and_cache(self):
        from test_media import RAW
        def tool(command, log):
            if command[0] == 'ffprobe':
                return json.dumps(RAW)
            Path(command[-1]).write_bytes(b'output')
            return ''
        with patch.object(n, 'run_tool', side_effect=tool):
            result = n.normalize(self.root, self.project)
        directory = self.root / self.pid / 'normalized'
        outputs = {p.name: p.read_bytes() for p in directory.iterdir()}
        control = n.JobControl(0, lambda value: None)
        control.cancel.set()
        with n.job_context(control), self.assertRaises(n.MediaError):
            n.normalize(self.root, result)
        self.assertEqual(outputs, {p.name: p.read_bytes() for p in directory.iterdir()})
        with patch.object(n, 'run_tool') as mock:
            self.jobs.start(self.pid)
            self.assertEqual(self.finish()['status'], 'succeeded')
            mock.assert_not_called()

    def test_background_upload_busy_api(self):
        entered, release = threading.Event(), threading.Event()
        def run(root, project):
            entered.set()
            release.wait(3)
            return project
        with patch.object(media, 'PROJECTS', self.root), patch.object(media, 'MANAGER', self.jobs):
            with TestClient(app) as client, patch.object(n, 'normalize', side_effect=run):
                created = n.create_project(self.root, 'new.mp4', 4)
                unsupported = client.post(f'/projects/{self.pid}/jobs', json={'stage': 'plan'}, headers={'X-Media-Import': '1'})
                self.assertEqual(unsupported.status_code, 422)
                response = client.put(f'/projects/{created["project_id"]}/source?background=true', content=b'test',
                                      headers={'X-Media-Import': '1', 'Content-Type': 'application/octet-stream'})
                try:
                    self.assertEqual(response.status_code, 202)
                    self.assertTrue(entered.wait(2))
                    response = client.post(f'/projects/{self.pid}/jobs', headers={'X-Media-Import': '1'})
                    self.assertEqual(response.status_code, 409)
                    self.assertEqual(response.json()['error']['code'], 'job_busy')
                finally:
                    release.set()
                    self.jobs.thread.join(3)


    def test_hard_restart_orphan_lock_and_retry(self):
        marker = self.root.parent / 'child-pid'
        repo = Path(__file__).resolve().parents[3]
        child_code = f"import os,time; from pathlib import Path; Path({str(marker)!r}).write_text(str(os.getpid())); time.sleep(30)"
        code = f"""
import sys,time
from pathlib import Path
sys.path.insert(0, {str(repo)!r})
from python.common.jobs import JobManager
from python.media import normalization as n
root = Path({str(self.root)!r})
def run(root, project):
    n.run_tool([sys.executable, '-c', {child_code!r}], root / project['project_id'] / 'logs/media.log')
    return project
jobs = JobManager(root)
jobs.start({self.pid!r}, runner=run)
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
            restarted.recover()
            job = restarted.latest(self.pid)
            self.assertEqual(job['status'], 'interrupted')
            with self.assertRaises(n.MediaError) as caught:
                restarted.retry(self.pid, job['job_id'])
            self.assertEqual(caught.exception.code, 'job_busy')
            os.kill(child_pid, signal.SIGTERM)
            child_pid = None
            deadline = time.monotonic() + 3
            with patch.object(n, 'normalize', side_effect=self.success):
                while True:
                    try:
                        restarted.retry(self.pid, job['job_id'])
                        break
                    except n.MediaError as error:
                        if error.code != 'job_busy' or time.monotonic() >= deadline:
                            raise
                        time.sleep(0.01)
                self.assertEqual(self.finish(restarted)['status'], 'succeeded')
        finally:
            if parent.poll() is None:
                parent.kill()
            parent.communicate(timeout=3)
            if child_pid:
                os.kill(child_pid, signal.SIGTERM)

    def test_shutdown_interrupts_and_startup_excludes_second_backend(self):
        self.jobs.startup()
        second = JobManager(self.root)
        with self.assertRaises(BlockingIOError):
            second.startup()
        entered = threading.Event()
        def run(root, project):
            entered.set()
            while True:
                n.checkpoint(0.1)
                time.sleep(0.01)
        self.jobs.start(self.pid, runner=run)
        self.assertTrue(entered.wait(2))
        self.jobs.close()
        self.assertEqual(self.jobs.latest(self.pid)['status'], 'interrupted')
        second.startup()
        second.close()

    def test_cancel_normalization_cleans_partial_outputs(self):
        from test_media import RAW
        entered = threading.Event()
        def tool(command, log):
            if command[0] == 'ffprobe':
                return json.dumps(RAW)
            Path(command[-1]).write_bytes(b'partial')
            entered.set()
            while True:
                n.checkpoint(0.3)
                time.sleep(0.01)
        with patch.object(n, 'run_tool', side_effect=tool):
            job = self.jobs.start(self.pid)
            self.assertTrue(entered.wait(2))
            self.jobs.cancel(self.pid, job['job_id'])
            self.assertEqual(self.finish()['status'], 'cancelled')
        self.assertEqual(list((self.root / self.pid / 'normalized').iterdir()), [])
        self.assertEqual((self.root / self.pid / 'source/test.mp4').read_bytes(), b'test')
