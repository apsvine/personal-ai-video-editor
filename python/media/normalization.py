"""Phase 02 media artifacts. No queue, database, or editing behavior."""

from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import uuid

SCHEMA = 1
CONFIG = "h264-aac-720-fit-cfr30-mono16k-v1"
RESERVE = 256 * 1024 * 1024


class MediaError(Exception):
    def __init__(self, code, message, status=400, **details):
        super().__init__(message)
        self.code, self.message, self.status, self.details = code, message, status, details

    def result(self):
        return {"code": self.code, "message": self.message, **self.details}


def safe_path(root, *parts):
    """Never follow runtime symlinks, including existing ancestor directories."""
    root = Path(root).absolute()
    candidate = root.joinpath(*parts)
    if not candidate.is_relative_to(root) or any(p in ("..", ".") for p in parts):
        raise MediaError("unsafe_path", "Unsafe project path.")
    for path in (candidate, *candidate.parents):
        if path.is_symlink():
            raise MediaError("unsafe_path", "Runtime paths must not contain symlinks.")
    if candidate.resolve() != candidate:
        raise MediaError("unsafe_path", "Unsafe project path.")
    return candidate


def atomic_json(path, value):
    temp = path.with_name(path.name + ".tmp")
    try:
        with temp.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.write("\n")
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def checksum(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate_filename(filename):
    if (not filename or len(filename) > 240 or filename in (".", "..")
            or any(c in filename for c in '/\\\x00')
            or any(ord(c) < 32 for c in filename)):
        raise MediaError("invalid_filename", "Select a file with a safe filename (no path components).")
    if Path(filename).suffix.lower() not in (".mp4", ".mov"):
        raise MediaError("unsupported_input", "Phase 02 supports .mp4 and .mov video files only.")


def require_tools():
    missing = [name for name in ("ffmpeg", "ffprobe") if not shutil.which(name)]
    if missing:
        raise MediaError("missing_tools", "Install system FFmpeg and ffprobe, then restart the backend. Missing: "
                         + ", ".join(missing), 503)


def check_disk(root, source_size, duration=0, copying=True):
    # Copy + generous proxy allowance, PCM audio allowance, and a fixed reserve.
    required = source_size * (4 if copying else 3) + math.ceil(duration * 32000) + RESERVE
    available = shutil.disk_usage(root).free
    if available < required:
        raise MediaError("insufficient_disk", "Additional disk space is required before importing/converting media.",
                         507, available_bytes=available, source_size_bytes=source_size,
                         required_bytes=required)


def project_path(root, project_id):
    if not re.fullmatch(r"[a-f0-9]{32}", project_id):
        raise MediaError("invalid_project", "Invalid project ID.", 404)
    path = safe_path(root, project_id)
    if not path.is_dir():
        raise MediaError("not_found", "Project not found.", 404)
    return path


def read_project(root, project_id):
    path = project_path(root, project_id)
    return json.loads(safe_path(path, "project.json").read_text())


def save_project(path, project, status):
    project["normalization_status"] = status
    atomic_json(safe_path(path, "project.json"), project)


def create_project(root, filename, size, modified=None):
    validate_filename(filename)
    if size <= 0:
        raise MediaError("empty_input", "Select a non-empty video file.")
    require_tools()
    root = safe_path(root)
    root.mkdir(parents=True, exist_ok=True)
    check_disk(root, size)
    project_id = uuid.uuid4().hex
    path = safe_path(root, project_id)
    path.mkdir()
    for name in ("source", "normalized", "logs"):
        (path / name).mkdir()
    project = {"schema_version": SCHEMA, "project_id": project_id,
               "created_at": datetime.now(timezone.utc).isoformat(),
               "source": {"filename": filename, "size_bytes": size, "last_modified_ms": modified},
               "configuration": CONFIG}
    (path / "logs/media.log").write_text("Project created; awaiting source upload.\n")
    save_project(path, project, "awaiting_upload")
    return project


def run_tool(command, log):
    try:
        result = subprocess.run(command, capture_output=True, text=True, errors="replace",
                                timeout=3600, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        with log.open("a") as stream:
            stream.write(f"{command[0]}: {error}\n")
        raise MediaError("tool_failed", "Media tool could not complete. See logs/media.log.", 422) from error
    with log.open("a") as stream:
        stream.write(f"Command: {command!r}\n{result.stdout}\n{result.stderr}\n")
    if result.returncode:
        raise MediaError("invalid_media", "Media could not be decoded or converted. See logs/media.log.", 422)
    return result.stdout


def inspect(source, log):
    if not source.is_file() or source.is_symlink():
        raise MediaError("invalid_source", "Source must exist and be a regular file.")
    raw = run_tool(["ffprobe", "-v", "error", "-protocol_whitelist", "file",
                    "-format_whitelist", "mov", "-show_entries",
                    "format=duration:stream=index,codec_type,codec_name,width,height,avg_frame_rate,sample_rate,channels,duration:stream_tags=rotate:stream_side_data=rotation:stream_disposition=attached_pic",
                    "-of", "json", str(source)], log)
    try:
        data = json.loads(raw)
        video = next(s for s in data["streams"] if s.get("codec_type") == "video"
                     and not s.get("disposition", {}).get("attached_pic"))
        audio = next((s for s in data["streams"] if s.get("codec_type") == "audio"), None)
        duration = float(data.get("format", {}).get("duration") or video.get("duration", 0))
        fps = float(Fraction(video.get("avg_frame_rate", "0/1")))
        width, height = int(video["width"]), int(video["height"])
        if not math.isfinite(duration) or duration <= 0 or width <= 0 or height <= 0 or fps <= 0:
            raise ValueError("Invalid duration, frame rate, or dimensions")
        rotation = next((s["rotation"] for s in video.get("side_data_list", []) if "rotation" in s),
                        video.get("tags", {}).get("rotate", 0))
        return {"schema_version": SCHEMA, "duration_seconds": duration,
                "width": width, "height": height, "frame_rate": fps,
                "video_codec": video.get("codec_name"), "video_stream_index": video["index"],
                "rotation_degrees": float(rotation), "audio_codec": audio.get("codec_name") if audio else None,
                "audio_sample_rate": int(audio.get("sample_rate", 0)) if audio else None,
                "audio_channels": audio.get("channels") if audio else None,
                "audio_stream_index": audio["index"] if audio else None}
    except (KeyError, StopIteration, ValueError, TypeError, ZeroDivisionError) as error:
        raise MediaError("invalid_media", "Input does not contain a usable video stream.", 422) from error


def normalization_plan(source, normalized, metadata):
    # FFmpeg autorotation runs before scaling. A portrait fits 720x1280;
    # landscape fits 1280x720, with no upscaling and even H.264 dimensions.
    scale = ("scale=trunc(iw*sar/2)*2:ih,setsar=1,scale=w='if(gte(iw,ih),min(1280,iw),min(720,iw))':"
             "h='if(gte(iw,ih),min(720,ih),min(1280,ih))':"
             "force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1,fps=30")
    base = ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-nostdin", "-n",
            "-protocol_whitelist", "file", "-format_whitelist", "mov", "-i", str(source)]
    video = base + ["-map", f"0:{metadata['video_stream_index']}"]
    has_audio = metadata["audio_stream_index"] is not None
    if has_audio:
        video += ["-map", f"0:{metadata['audio_stream_index']}", "-c:a", "aac", "-b:a", "128k"]
    else:
        video += ["-an"]
    video += ["-vf", scale, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
              "-pix_fmt", "yuv420p", "-map_metadata", "-1", "-movflags", "+faststart",
              str(normalized / "proxy.tmp.mp4")]
    audio = (base + ["-map", f"0:{metadata['audio_stream_index']}", "-vn", "-ac", "1", "-ar", "16000",
                     "-c:a", "pcm_s16le", str(normalized / "audio.tmp.wav")] if has_audio else None)
    return video, audio


def find_cached(root, source_hash):
    for candidate in root.iterdir():
        try:
            project = read_project(root, candidate.name)
            if (project.get("normalization_status") != "completed" or project.get("configuration") != CONFIG
                    or project.get("schema_version") != SCHEMA or project["source"].get("sha256") != source_hash):
                continue
            expected = {"metadata.json", "proxy.mp4"}
            if project["audio_status"] == "available":
                expected.add("audio.wav")
            elif project["audio_status"] != "no_audio":
                continue
            if set(project["outputs"]) != expected:
                continue
            source = safe_path(candidate, "source", project["source"]["filename"])
            if not source.is_file() or checksum(source) != source_hash:
                continue
            for name in expected:
                output = safe_path(candidate, "normalized", name)
                if not output.is_file() or output.stat().st_size == 0 or checksum(output) != project["outputs"][name]:
                    break
            else:
                metadata = json.loads(safe_path(candidate, "normalized", "metadata.json").read_text())
                if metadata["schema_version"] == SCHEMA and metadata["source"]["sha256"] == source_hash:
                    return project
        except (MediaError, OSError, ValueError, KeyError, TypeError):
            continue
    return None


def normalize(root, project):
    path = project_path(root, project["project_id"])
    normalized = safe_path(path, "normalized")
    source = safe_path(path, "source", project["source"]["filename"])
    log = safe_path(path, "logs", "media.log")
    try:
        require_tools()
        save_project(path, project, "inspecting")
        project["source"]["sha256"] = checksum(source)
        cached = find_cached(root, project["source"]["sha256"])
        if cached:
            project["reused_project_id"] = cached["project_id"]
            save_project(path, project, "reused")
            return {**cached, "reused": True}
        metadata = inspect(source, log)
        metadata["source"] = project["source"]
        check_disk(root, project["source"]["size_bytes"], metadata["duration_seconds"], copying=False)
        proxy_command, audio_command = normalization_plan(source, normalized, metadata)
        save_project(path, project, "creating_proxy")
        run_tool(proxy_command, log)
        if audio_command:
            save_project(path, project, "extracting_audio")
            run_tool(audio_command, log)
        # Validate tools produced nonempty artifacts before publishing ANY final output.
        names = [("proxy.tmp.mp4", "proxy.mp4")]
        if audio_command:
            names.append(("audio.tmp.wav", "audio.wav"))
        for temporary, _ in names:
            output = safe_path(normalized, temporary)
            if not output.is_file() or output.stat().st_size == 0:
                raise MediaError("empty_output", "Conversion produced no usable output. See logs/media.log.", 422)
        metadata["audio_status"] = "available" if audio_command else "no_audio"
        for temporary, final in names:
            (normalized / temporary).replace(normalized / final)
        atomic_json(safe_path(normalized, "metadata.json"), metadata)
        project["audio_status"] = metadata["audio_status"]
        project["outputs"] = {name: checksum(normalized / name) for name in
                              ["metadata.json", *[final for _, final in names]]}
        save_project(path, project, "completed")
        return {**project, "reused": False}
    except Exception as error:
        # No completed output set survives a failed attempt. The source is retained.
        for name in ("proxy.mp4", "audio.wav", "metadata.json"):
            safe_path(normalized, name).unlink(missing_ok=True)
        failure = error if isinstance(error, MediaError) else MediaError(
            "normalization_failed", "Normalization failed. See logs/media.log.", 500)
        with log.open("a") as stream:
            stream.write(f"{type(error).__name__}: {error}\n")
        project["error"] = failure.result()
        save_project(path, project, "failed")
        raise failure from error
    finally:
        for name in ("proxy.tmp.mp4", "audio.tmp.wav", "metadata.json.tmp"):
            safe_path(normalized, name).unlink(missing_ok=True)
