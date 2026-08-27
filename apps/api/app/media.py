"""One-file local import API; processing belongs to the upload request."""

import asyncio
import json
from pathlib import Path
import sys
import threading

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from python.media.normalization import (  # noqa: E402
    MediaError, check_disk, create_project, normalize, project_path, read_project,
    safe_path, save_project,
)

PROJECTS = ROOT / "runtime" / "projects"
router = APIRouter()
# Only one active transfer/conversion per server process; no worker or job queue.
IMPORT_LOCK = threading.Lock()
LOCAL_ORIGINS = {"http://127.0.0.1:5173", "http://localhost:5173"}


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
    if not IMPORT_LOCK.acquire(blocking=False):
        raise MediaError("import_busy", "Another import is running. Wait for it to finish.", 409)
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
        return await run_in_threadpool(normalize, PROJECTS, project)
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
        IMPORT_LOCK.release()


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
