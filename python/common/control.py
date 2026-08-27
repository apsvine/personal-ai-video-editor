"""Shared job cancellation context and bounded subprocess execution."""
import threading
import subprocess
import time
from pathlib import Path
from contextlib import contextmanager
from python.common.errors import MediaError

_CONTROL = threading.local()


class JobControl:
    def __init__(self, lock_fd, progress):
        self.lock_fd = lock_fd
        self.progress = progress
        self.cancel = threading.Event()
        self.shutdown = threading.Event()

    def check(self):
        if self.shutdown.is_set():
            raise MediaError("backend_interrupted", "Backend stopped before completion. Retry this job.", 409)
        if self.cancel.is_set():
            raise MediaError("cancelled", "Job was cancelled.", 409)


@contextmanager
def job_context(control):
    _CONTROL.value = control
    try:
        yield
    finally:
        del _CONTROL.value


def checkpoint(value):
    control = getattr(_CONTROL, "value", None)
    if control:
        control.check()
        control.progress(value)



def run_worker(command, log):
    control = getattr(_CONTROL, "value", None)
    if control is None:
        raise RuntimeError("Worker requires a managed job context")
    control.check()
    with log.open("a") as stream:
        with subprocess.Popen(command, stdout=stream, stderr=stream,
                              pass_fds=(control.lock_fd,), cwd=Path(__file__).resolve().parents[2]) as process:
            deadline = time.monotonic() + 3600
            try:
                while process.poll() is None:
                    control.check()
                    if time.monotonic() >= deadline:
                        raise MediaError("transcription_timeout", "Transcription exceeded one hour.", 422)
                    time.sleep(0.1)
                control.check()
                if process.returncode:
                    raise MediaError("transcription_failed", "Transcription worker failed. See the local transcription log.", 422)
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
