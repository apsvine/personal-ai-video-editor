"""Local media import and persistent normalization job routes."""

import asyncio
import json
from pathlib import Path
import sys
import threading
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, model_validator
from starlette.concurrency import run_in_threadpool

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from python.media.normalization import (  # noqa: E402
    MediaError, check_disk, create_project, project_path, read_project,
    safe_path, save_project,
)

PROJECTS = ROOT / "runtime" / "projects"
router = APIRouter()
# Shared by the upload reservation and job runner; no queue.
IMPORT_LOCK = threading.Lock()
from python.common.jobs import JobManager
MANAGER = None


def manager():
    global MANAGER
    if MANAGER is None or MANAGER.root != PROJECTS:
        MANAGER = JobManager(PROJECTS, IMPORT_LOCK)
    return MANAGER


LOCAL_ORIGINS = {"http://127.0.0.1:5173", "http://localhost:5173"}


class JobRequest(BaseModel):
    stage: Literal["normalize", "transcribe", "analyze", "audio_features", "plan"] = "normalize"
    caption_settings: dict | None = None


class ImportRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=240)
    size_bytes: int = Field(gt=0, strict=True)
    last_modified_ms: int | None = Field(default=None, ge=0)


def guard_write(request):
    # Custom header forces a CORS preflight, preventing cross-site simple POSTs.
    if (request.headers.get("x-media-import") != "1"
            or request.headers.get("origin") not in LOCAL_ORIGINS | {None}):
        raise MediaError("forbidden_origin", "Import is allowed only from the local application.", 403)


@router.post("/projects", status_code=201)
def new_project(body: ImportRequest, request: Request):
    guard_write(request)
    return create_project(PROJECTS, body.filename, body.size_bytes, body.last_modified_ms)


@router.get("/projects/{project_id}")
def get_project(project_id: str):
    return read_project(PROJECTS, project_id)


@router.put("/projects/{project_id}/source")
async def upload_source(project_id: str, request: Request):
    guard_write(request)
    if request.headers.get("content-type", "").split(";")[0] != "application/octet-stream":
        raise MediaError("invalid_content_type", "Upload the video as application/octet-stream.", 415)
    jobs = manager()
    jobs.reserve()
    handed_off = False
    path = project = temporary = None
    try:
        project = read_project(PROJECTS, project_id)
        path = project_path(PROJECTS, project_id)
        if project["normalization_status"] != "awaiting_upload":
            raise MediaError("already_uploaded", "This project already has an upload. Start a new import.", 409)
        check_disk(PROJECTS, project["source"]["size_bytes"])
        temporary = safe_path(path, "source", "upload.tmp")
        source = safe_path(path, "source", project["source"]["filename"])
        save_project(path, project, "uploading")
        received = 0
        with temporary.open("xb") as stream:
            async for chunk in request.stream():
                received += len(chunk)
                if received > project["source"]["size_bytes"]:
                    raise MediaError("size_mismatch", "Upload exceeds the declared source size.")
                await run_in_threadpool(stream.write, chunk)
        if received != project["source"]["size_bytes"]:
            raise MediaError("size_mismatch", "Upload was incomplete. Select the file and try again.")
        temporary.replace(source)
        save_project(path, project, "uploaded")
        # The worker owns the reservation after start, including on start failure.
        handed_off = True
        job = jobs.start(project_id, reserved=True)
        if request.query_params.get("background") == "true":
            return JSONResponse(status_code=202, content=job)
        # Compatibility for Phase 02 clients; disconnect does not own the worker.
        while True:
            current = jobs.read(project_id, job["job_id"])
            if current["status"] not in ("pending", "running"):
                if current["status"] != "succeeded":
                    failure = current["error"]
                    raise MediaError(failure["code"], failure["message"], 422)
                return {**read_project(PROJECTS, current["result_project_id"]), "reused": current["reused"]}
            await asyncio.sleep(0.05)
    except (Exception, asyncio.CancelledError) as error:
        if project is not None and project.get("normalization_status") in ("uploading", "uploaded"):
            failure = error if isinstance(error, MediaError) else MediaError(
                "upload_failed", "Upload interrupted or could not be saved. Start a new import.")
            project["error"] = failure.result()
            save_project(path, project, "failed")
            safe_path(path, "logs", "media.log").write_text(f"{type(error).__name__}: {error}\n")
        if isinstance(error, (MediaError, asyncio.CancelledError)):
            raise
        raise MediaError("upload_failed", "Upload failed. See the project's logs/media.log.", 500) from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        if not handed_off:
            jobs.release()


def completed_asset(project_id, filename):
    project = read_project(PROJECTS, project_id)
    if project["normalization_status"] != "completed":
        raise MediaError("not_ready", "Normalized media is not ready.", 409)
    path = safe_path(project_path(PROJECTS, project_id), "normalized", filename)
    if not path.is_file():
        raise MediaError("asset_missing", "Normalized asset is unavailable; import the source again.", 404)
    return path


@router.get("/projects/{project_id}/metadata")
def metadata(project_id: str):
    return json.loads(completed_asset(project_id, "metadata.json").read_text())


@router.get("/projects/{project_id}/proxy")
def proxy(project_id: str):
    return FileResponse(completed_asset(project_id, "proxy.mp4"), media_type="video/mp4",
                        headers={"Cache-Control": "no-cache"})


@router.post("/projects/{project_id}/jobs", status_code=202)
def start_job(project_id: str, request: Request, body: JobRequest | None = None):
    guard_write(request)
    return manager().start(project_id, stage=body.stage if body else "normalize",
                           caption_settings=body.caption_settings if body else None)


@router.get("/projects/{project_id}/jobs/latest")
def latest_job(project_id: str):
    return manager().latest(project_id)


@router.get("/projects/{project_id}/jobs/{job_id}")
def get_job(project_id: str, job_id: str):
    return manager().read(project_id, job_id)


@router.post("/projects/{project_id}/jobs/{job_id}/cancel", status_code=202)
def cancel_job(project_id: str, job_id: str, request: Request):
    guard_write(request)
    return manager().cancel(project_id, job_id)


@router.post("/projects/{project_id}/jobs/{job_id}/retry", status_code=202)
def retry_job(project_id: str, job_id: str, request: Request):
    guard_write(request)
    return manager().retry(project_id, job_id)


@router.get("/projects/{project_id}/transcript")
def transcript(project_id: str):
    from python.transcription.engine import read_transcript
    return read_transcript(PROJECTS, read_project(PROJECTS, project_id))


class TranscriptIdentity(BaseModel):
    model_config = {'extra': 'forbid'}
    source_transcript_checksum: str = Field(strict=True, pattern=r'^[a-f0-9]{64}$')

    @model_validator(mode='before')
    @classmethod
    def require_utf8(cls, value):
        # Reject surrogates before Pydantic includes them in a validation error;
        # the framework's UTF-8 JSON error renderer cannot encode such inputs.
        try:
            json.dumps(value, ensure_ascii=False).encode('utf-8')
        except UnicodeError as error:
            raise MediaError('invalid_text', 'Use valid UTF-8 strings without unpaired surrogates.', 422) from error
        return value


class TranscriptEdit(TranscriptIdentity):
    text: str = Field(strict=True, max_length=10000)


@router.get('/projects/{project_id}/transcript/review')
def transcript_review(project_id: str):
    from python.transcription.review import get_review
    return get_review(PROJECTS, project_id)


def write_review(project_id, body, request, **kwargs):
    from python.transcription.review import change_review
    guard_write(request)
    jobs = manager()
    # Serialize edits/reset with each other AND raw transcript publication.
    jobs.reserve()
    try:
        return change_review(PROJECTS, project_id, body.source_transcript_checksum, **kwargs)
    finally:
        jobs.release()


@router.put('/projects/{project_id}/transcript/overrides/{segment_id}')
def edit_transcript(project_id: str, segment_id: str, body: TranscriptEdit, request: Request):
    return write_review(project_id, body, request, segment_id=segment_id, text=body.text)


@router.post('/projects/{project_id}/transcript/overrides/reset')
def reset_transcript(project_id: str, body: TranscriptIdentity, request: Request):
    return write_review(project_id, body, request, reset=True)


@router.post('/projects/{project_id}/transcript/overrides/{segment_id}/reset')
def reset_transcript_segment(project_id: str, segment_id: str, body: TranscriptIdentity, request: Request):
    return write_review(project_id, body, request, segment_id=segment_id, reset=True)


class CutIdentity(BaseModel):
    model_config = {'extra': 'forbid'}
    source_cuts_checksum: str = Field(strict=True, pattern=r'^[a-f0-9]{64}$')


class CutDecision(CutIdentity):
    action: Literal['accept', 'reject']


@router.get('/projects/{project_id}/cuts')
def get_cuts(project_id: str):
    from python.editing.cuts import read_cuts
    return read_cuts(PROJECTS, read_project(PROJECTS, project_id))


@router.get('/projects/{project_id}/captions')
def get_captions(project_id: str):
    from python.editing.caption_store import read_captions
    return read_captions(PROJECTS, read_project(PROJECTS, project_id))


@router.get('/projects/{project_id}/audio-features')
def get_audio_features(project_id: str):
    from python.audio_features.features import read_audio_features
    return read_audio_features(PROJECTS, read_project(PROJECTS, project_id))


@router.get('/projects/{project_id}/cuts/review')
def get_cut_review(project_id: str):
    from python.editing.cut_review import get_review
    return get_review(PROJECTS, project_id)


def write_cut_review(project_id, body, request, **kwargs):
    from python.editing.cut_review import change_review
    guard_write(request)
    jobs = manager()
    jobs.reserve()
    try:
        return change_review(PROJECTS, project_id, body.source_cuts_checksum, **kwargs)
    finally:
        jobs.release()


@router.put('/projects/{project_id}/cuts/overrides/{cut_id}')
def edit_cut(project_id: str, cut_id: str, body: CutDecision, request: Request):
    return write_cut_review(project_id, body, request, cut_id=cut_id, action=body.action)


@router.post('/projects/{project_id}/cuts/overrides/reset')
def reset_cuts(project_id: str, body: CutIdentity, request: Request):
    return write_cut_review(project_id, body, request, reset=True)


@router.post('/projects/{project_id}/cuts/overrides/{cut_id}/reset')
def reset_cut(project_id: str, cut_id: str, body: CutIdentity, request: Request):
    return write_cut_review(project_id, body, request, cut_id=cut_id, reset=True)
