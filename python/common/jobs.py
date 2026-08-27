"""Disk-backed, single-heavy-job orchestration (local POSIX runtime)."""
from datetime import datetime, timezone
import fcntl
import json
import math
import threading
import traceback
import uuid

from python.media import normalization as n
from python.transcription import engine as transcription
from python.common.control import JobControl, job_context

STAGES = ('normalize', 'transcribe', 'analyze', 'plan', 'render')
RETRYABLE = ('failed', 'interrupted', 'cancelled')


def now():
    return datetime.now(timezone.utc).isoformat()


class JobManager:
    def __init__(self, root, gate=None):
        self.root = root
        self.gate = gate or threading.Lock()
        self.mutex = threading.RLock()
        self.active = None
        self.thread = None
        self.lockfile = None
        self.server_lock = None

    def startup(self):
        n.safe_path(self.root.parent).mkdir(parents=True, exist_ok=True)
        self.server_lock = n.safe_path(self.root.parent, f'.{self.root.name}-backend.lock').open('a+')
        try:
            fcntl.flock(self.server_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.recover()
        except Exception:
            self.server_lock.close()
            self.server_lock = None
            raise

    def reserve(self):
        if not self.gate.acquire(False):
            raise n.MediaError('job_busy', 'Another heavy operation is active. Try again when it finishes.', 409)
        try:
            n.safe_path(self.root).mkdir(parents=True, exist_ok=True)
            self.lockfile = n.safe_path(self.root, '.heavy.lock').open('a+')
            fcntl.flock(self.lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception as error:
            if self.lockfile:
                self.lockfile.close()
                self.lockfile = None
            self.gate.release()
            if isinstance(error, BlockingIOError):
                raise n.MediaError('job_busy', 'A heavy process is still active. Try again shortly.', 409) from error
            raise

    def release(self):
        # Close, not LOCK_UN: a surviving child retains the lock after a hard kill.
        self.lockfile.close()
        self.lockfile = None
        self.gate.release()

    def path(self, project_id, job_id):
        if len(job_id) != 32 or any(c not in '0123456789abcdef' for c in job_id):
            raise n.MediaError('invalid_job', 'Invalid job ID.', 404)
        return n.safe_path(n.project_path(self.root, project_id), 'jobs', job_id + '.json')

    def read(self, project_id, job_id):
        try:
            return json.loads(self.path(project_id, job_id).read_text())
        except FileNotFoundError as error:
            raise n.MediaError('job_not_found', 'Job not found.', 404) from error

    def save(self, job):
        n.atomic_json(self.path(job['project_id'], job['job_id']), job)

    def latest(self, project_id):
        directory = n.safe_path(n.project_path(self.root, project_id), 'jobs')
        jobs = [self.read(project_id, p.stem) for p in directory.glob('*.json')]
        return max(jobs, key=lambda j: j['created_at']) if jobs else None

    def recover(self):
        if not self.root.exists():
            return
        for file in self.root.glob('*/jobs/*.json'):
            job = self.read(file.parent.parent.name, file.stem)
            if job['status'] in ('pending', 'running'):
                job.update(status='interrupted', finished_at=now(), error={
                    'code': 'backend_interrupted', 'message': 'Backend stopped before completion. Retry this job.'})
                self.save(job)

    def start(self, project_id, retry_of=None, reserved=False, runner=None, stage="normalize"):
        if stage not in ("normalize", "transcribe"):
            raise n.MediaError("unsupported_stage", "Only normalize and transcribe are supported.", 422)
        if not reserved:
            self.reserve()
        try:
            project = n.read_project(self.root, project_id)
            source = n.safe_path(n.project_path(self.root, project_id), 'source', project['source']['filename'])
            if not source.is_file() or source.stat().st_size != project['source']['size_bytes']:
                raise n.MediaError('source_not_ready', 'A complete source upload is required.', 409)
            if stage == 'transcribe':
                transcription.normalized_project(self.root, project)
            directory = n.safe_path(n.project_path(self.root, project_id), 'jobs')
            directory.mkdir(exist_ok=True)
            job = dict(schema_version=1, job_id=uuid.uuid4().hex, project_id=project_id,
                       stage=stage, status='pending', progress=0.0, created_at=now(),
                       started_at=None, finished_at=None, error=None, log_path=None,
                       retry_of=retry_of, result_project_id=None, reused=False)
            job['log_path'] = f"logs/job-{job['job_id']}.log"
            n.safe_path(n.project_path(self.root, project_id), 'logs', f"job-{job['job_id']}.log").touch()
            self.save(job)
            control = JobControl(self.lockfile.fileno(), lambda value: self.progress(job, value))
            with self.mutex:
                self.active = (job, control)
                self.thread = threading.Thread(target=self.execute, args=(job, control, runner), daemon=True)
                response = dict(job)
                self.thread.start()
            return response
        except Exception:
            self.release()
            raise

    def progress(self, job, value):
        if not math.isfinite(value):
            raise ValueError('Progress must be finite')
        with self.mutex:
            job['progress'] = max(0.0, min(1.0, float(value)))
            self.save(job)

    def execute(self, job, control, runner):
        try:
            with self.mutex:
                job.update(status='running', started_at=now())
                self.save(job)
            with job_context(control):
                control.check()
                result = (runner or (n.normalize if job["stage"] == "normalize" else transcription.transcribe))(self.root, n.read_project(self.root, job['project_id']))
            with self.mutex:
                # Publication is the success boundary; a late cancel must not undo it.
                job.update(status='succeeded', progress=1.0, result_project_id=result['project_id'],
                           reused=result.get('reused', False))
        except Exception as error:
            log = n.safe_path(n.project_path(self.root, job['project_id']), *job['log_path'].split('/'))
            with log.open('a') as stream:
                traceback.print_exc(file=stream)
                stream.write('\nDetailed tool output: logs/media.log or logs/transcription.log\n')
            with self.mutex:
                failure = error if isinstance(error, n.MediaError) else n.MediaError('job_failed', 'Job failed. See the local job log.')
                job.update(status=('cancelled' if failure.code == 'cancelled' else
                                   'interrupted' if failure.code == 'backend_interrupted' else 'failed'), error=failure.result())
        finally:
            with self.mutex:
                job['finished_at'] = now()
                try:
                    self.save(job)
                finally:
                    self.active = None
                    self.release()

    def cancel(self, project_id, job_id):
        with self.mutex:
            job = self.read(project_id, job_id)
            if self.active and self.active[0]['job_id'] == job_id:
                self.active[1].cancel.set()
                return job
            raise n.MediaError('job_not_active', 'This job is no longer running.', 409)

    def retry(self, project_id, job_id):
        job = self.read(project_id, job_id)
        if job['status'] not in RETRYABLE:
            raise n.MediaError('not_retryable', 'Only failed, interrupted or cancelled jobs can be retried.', 409)
        return self.start(project_id, retry_of=job_id, stage=job["stage"])

    def close(self):
        with self.mutex:
            if self.active:
                self.active[1].shutdown.set()
        if self.thread:
            self.thread.join()

        if self.server_lock:
            self.server_lock.close()
            self.server_lock = None
