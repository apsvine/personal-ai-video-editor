"""Phase 02 tests; synthetic integration media is generated in a temporary folder."""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import wave

from fastapi.testclient import TestClient
from app.main import app
from app import media
from python.media import normalization as n

HEADERS = {"X-Media-Import": "1", "Content-Type": "application/octet-stream"}
RAW = {"format": {"duration": "1.2"}, "streams": [
    {"index": 0, "codec_type": "video", "codec_name": "h264", "width": 1920,
     "height": 1080, "avg_frame_rate": "30000/1001", "side_data_list": [{"rotation": 90}]},
    {"index": 1, "codec_type": "audio", "codec_name": "aac", "sample_rate": "48000", "channels": 2},
]}


class MediaTests(unittest.TestCase):
    def setUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(self.temp).resolve() / "projects"
        self.enterContext(patch.object(media, "PROJECTS", self.root))
        self.enterContext(patch.object(n, "require_tools"))
        self.client = self.enterContext(TestClient(app))

    def create(self, filename="video.mp4", data=b"test"):
        return n.create_project(self.root, filename, len(data), 123456)

    def source(self, project, data=b"test"):
        path = self.root / project["project_id"] / "source" / project["source"]["filename"]
        path.write_bytes(data)
        return path

    def fake_tool(self, command, log):
        if command[0] == "ffprobe":
            return json.dumps(RAW)
        Path(command[-1]).write_bytes(b"synthetic-output")
        return ""

    def test_project_creation(self):
        project = self.create()
        path = self.root / project["project_id"]
        self.assertRegex(project["project_id"], r"^[a-f0-9]{32}$")
        self.assertEqual(project["schema_version"], 1)
        self.assertEqual(project["source"]["last_modified_ms"], 123456)
        self.assertEqual(n.read_project(self.root, project["project_id"]), project)
        for name in ("source", "normalized", "logs"):
            self.assertTrue((path / name).is_dir())

    def test_unsupported_and_unsafe_names(self):
        for name in ("audio.wav", "../video.mp4", "/video.mp4", "C:\\video.mp4", "bad\x00.mp4"):
            with self.subTest(name=name), self.assertRaises(n.MediaError):
                self.create(name)
        self.assertFalse(self.root.exists())

    def test_safe_paths_and_symlinks(self):
        self.root.mkdir()
        (self.root / "link").symlink_to(Path(self.temp))
        for parts in (("..", "outside"), ("link", "file"), ("/tmp/escape",)):
            with self.assertRaises(n.MediaError):
                n.safe_path(self.root, *parts)
        with self.assertRaises(n.MediaError):
            n.project_path(self.root, "../bad")

    def test_disk_rejection_before_copy(self):
        with patch.object(n.shutil, "disk_usage", return_value=shutil._ntuple_diskusage(10, 9, 1)):
            with self.assertRaises(n.MediaError) as caught:
                self.create()
        self.assertEqual(caught.exception.code, "insufficient_disk")
        self.assertEqual(caught.exception.details["available_bytes"], 1)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_missing_tools(self):
        with patch.object(n.shutil, "which", return_value=None):
            with self.assertRaises(n.MediaError) as caught:
                _require_tools()
        self.assertEqual(caught.exception.code, "missing_tools")
        self.assertIn("ffprobe", caught.exception.message)

    def test_metadata_and_planning(self):
        project = self.create(); source = self.source(project)
        with patch.object(n, "run_tool", side_effect=self.fake_tool):
            metadata = n.inspect(source, self.root / "log")
        self.assertEqual(metadata["schema_version"], 1)
        self.assertEqual(metadata["rotation_degrees"], 90)
        self.assertAlmostEqual(metadata["frame_rate"], 29.97002997)
        self.assertEqual(metadata["audio_sample_rate"], 48000)
        video, audio = n.normalization_plan(source, self.root, metadata)
        self.assertEqual(video[video.index("-protocol_whitelist")+1], "file")
        self.assertEqual(video[video.index("-format_whitelist")+1], "mov")
        self.assertIn("libx264", video); self.assertIn("aac", video)
        self.assertIn("force_original_aspect_ratio=decrease", video[video.index("-vf")+1])
        self.assertIn("fps=30", video[video.index("-vf")+1])
        self.assertIn("16000", audio); self.assertIn("pcm_s16le", audio)
        self.assertTrue(video[-1].endswith("proxy.tmp.mp4"))

    def test_success_source_unchanged_and_cache(self):
        project = self.create(); source = self.source(project); before = source.read_bytes()
        with patch.object(n, "run_tool", side_effect=self.fake_tool) as tool:
            result = n.normalize(self.root, project)
            self.assertEqual(tool.call_count, 3)
            again = self.create(); self.source(again)
            cached = n.normalize(self.root, again)
            self.assertEqual(tool.call_count, 3)
        self.assertTrue(cached["reused"])
        self.assertEqual(cached["project_id"], result["project_id"])
        self.assertEqual(source.read_bytes(), before)
        self.assertIsNotNone(n.find_cached(self.root, n.checksum(source)))
        self.assertIsNone(n.find_cached(self.root, "different-source"))
        (source.parent.parent / "normalized/proxy.mp4").write_bytes(b"tampered")
        self.assertIsNone(n.find_cached(self.root, n.checksum(source)))

    def test_missing_output_invalidates_cache(self):
        project = self.create(); source = self.source(project)
        with patch.object(n, "run_tool", side_effect=self.fake_tool):
            n.normalize(self.root, project)
        (source.parent.parent / "normalized/audio.wav").unlink()
        self.assertIsNone(n.find_cached(self.root, n.checksum(source)))

    def test_no_audio_is_structured_success(self):
        project = self.create(); self.source(project)
        raw = {"format": RAW["format"], "streams": RAW["streams"][:1]}
        def tool(command, log):
            return json.dumps(raw) if command[0] == "ffprobe" else self.fake_tool(command, log)
        with patch.object(n, "run_tool", side_effect=tool):
            result = n.normalize(self.root, project)
        self.assertEqual(result["audio_status"], "no_audio")
        self.assertNotIn("audio.wav", result["outputs"])
        self.assertIsNotNone(n.find_cached(self.root, result["source"]["sha256"]))

    def test_conversion_failure_leaves_no_final_or_temp_outputs(self):
        project = self.create(); source = self.source(project)
        def tool(command, log):
            if command[-1].endswith("audio.tmp.wav"):
                Path(command[-1]).write_bytes(b"partial")
                raise n.MediaError("invalid_media", "Bad audio", 422)
            return self.fake_tool(command, log)
        with patch.object(n, "run_tool", side_effect=tool), self.assertRaises(n.MediaError):
            n.normalize(self.root, project)
        self.assertEqual(list((source.parent.parent / "normalized").iterdir()), [])
        self.assertEqual(source.read_bytes(), b"test")
        self.assertEqual(n.read_project(self.root, project["project_id"])["normalization_status"], "failed")
        self.assertTrue((source.parent.parent / "logs/media.log").is_file())

    def test_corrupt_probe_and_nonexistent_source(self):
        project = self.create(); source = self.source(project)
        with patch.object(n, "run_tool", return_value='{"streams": []}'), self.assertRaises(n.MediaError):
            n.normalize(self.root, project)
        with self.assertRaises(n.MediaError):
            n.inspect(self.root / "missing.mp4", self.root / "log")

    def test_tool_captures_logs_without_shell(self):
        self.root.mkdir()
        with patch.object(n.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "out", "decode failed")) as run:
            with self.assertRaises(n.MediaError):
                n.run_tool(["ffmpeg", "-version"], self.root / "media.log")
        self.assertTrue(run.call_args.kwargs["capture_output"])
        self.assertNotIn("shell", run.call_args.kwargs)
        self.assertIn("decode failed", (self.root / "media.log").read_text())

    def test_api_import_metadata_proxy_and_range(self):
        response = self.client.post("/projects", json={"filename": "test.mp4", "size_bytes": 4}, headers={"X-Media-Import": "1"})
        self.assertEqual(response.status_code, 201)
        project_id = response.json()["project_id"]
        with patch.object(n, "run_tool", side_effect=self.fake_tool):
            response = self.client.put(f"/projects/{project_id}/source", content=b"test", headers=HEADERS)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.get(f"/projects/{project_id}").json()["normalization_status"], "completed")
        self.assertEqual(self.client.get(f"/projects/{project_id}/metadata").status_code, 200)
        response = self.client.get(f"/projects/{project_id}/proxy", headers={"Range": "bytes=0-3"})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.content, b"synt")
        self.assertEqual(self.client.put(f"/projects/{project_id}/source", content=b"test", headers=HEADERS).status_code, 409)

    def test_api_incomplete_upload(self):
        project = self.create()
        response = self.client.put(f"/projects/{project['project_id']}/source", content=b"x", headers=HEADERS)
        self.assertEqual(response.status_code, 400)
        path = self.root / project["project_id"]
        self.assertEqual(list((path / "source").iterdir()), [])
        self.assertEqual(n.read_project(self.root, project["project_id"])["normalization_status"], "failed")

    def test_api_guard_and_validation(self):
        body = {"filename": "test.mp4", "size_bytes": 4}
        self.assertEqual(self.client.post("/projects", json=body).status_code, 403)
        self.assertEqual(self.client.post("/projects", json=body, headers={"X-Media-Import": "1", "Origin": "https://evil.example"}).status_code, 403)
        self.assertEqual(self.client.get("/projects/not-an-id").status_code, 404)
        for origin, code in (("http://127.0.0.1:5173", 200), ("https://evil.example", 400)):
            response = self.client.options("/projects", headers={"Origin": origin,
                "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type,x-media-import"})
            self.assertEqual(response.status_code, code)

    def test_upload_excess_and_busy(self):
        project = self.create()
        endpoint = f"/projects/{project['project_id']}/source"
        with media.IMPORT_LOCK:
            self.assertEqual(self.client.put(endpoint, content=b"test", headers=HEADERS).status_code, 409)
        response = self.client.put(endpoint, content=b"too much", headers=HEADERS)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(list((self.root / project["project_id"] / "source").iterdir()), [])

    def test_unfinished_assets_cannot_be_served(self):
        project = self.create()
        normalized = self.root / project["project_id"] / "normalized"
        (normalized / "proxy.mp4").write_bytes(b"left over from abrupt termination")
        self.assertEqual(self.client.get(f"/projects/{project['project_id']}/proxy").status_code, 409)
        self.assertIsNone(n.find_cached(self.root, "anything"))

    def test_json_publication_failure_removes_published_media(self):
        project = self.create(); source = self.source(project)
        atomic = n.atomic_json
        def fail_metadata(path, value):
            if path.name == "metadata.json":
                raise OSError("simulated full disk")
            atomic(path, value)
        with patch.object(n, "run_tool", side_effect=self.fake_tool), patch.object(n, "atomic_json", side_effect=fail_metadata):
            with self.assertRaises(n.MediaError):
                n.normalize(self.root, project)
        self.assertEqual(list((source.parent.parent / "normalized").iterdir()), [])
        self.assertEqual(source.read_bytes(), b"test")

    def test_changed_configuration_invalidates_cache(self):
        project = self.create(); source = self.source(project)
        with patch.object(n, "run_tool", side_effect=self.fake_tool):
            n.normalize(self.root, project)
        with patch.object(n, "CONFIG", "changed"):
            self.assertIsNone(n.find_cached(self.root, n.checksum(source)))

    def test_atomic_json_failure_preserves_previous_value(self):
        self.root.mkdir()
        path = self.root / "record.json"
        n.atomic_json(path, {"valid": True})
        with self.assertRaises(ValueError):
            n.atomic_json(path, {"bad": float("nan")})
        self.assertEqual(json.loads(path.read_text()), {"valid": True})
        self.assertFalse(path.with_name("record.json.tmp").exists())


# Capture the original before setUp replaces it.
_require_tools = n.require_tools

@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "system FFmpeg/ffprobe not installed")
class RealMediaTests(unittest.TestCase):
    def test_generated_portrait_clip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            original = root / "tiny.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=90x160:r=24:d=0.5",
                            "-f", "lavfi", "-i", "sine=frequency=440:duration=0.5", "-shortest", "-c:v", "libx264",
                            "-pix_fmt", "yuv420p", "-c:a", "aac", str(original)], check=True, capture_output=True)
            before = n.checksum(original)
            project = n.create_project(root / "projects", original.name, original.stat().st_size)
            source = root / "projects" / project["project_id"] / "source" / original.name
            shutil.copy2(original, source)
            result = n.normalize(root / "projects", project)
            self.assertEqual(n.checksum(original), before)
            normalized = source.parent.parent / "normalized"
            info = n.inspect(normalized / "proxy.mp4", source.parent.parent / "logs/media.log")
            self.assertLess(info["width"], info["height"])
            self.assertEqual(info["frame_rate"], 30)
            self.assertEqual(info["video_codec"], "h264")
            with wave.open(str(normalized / "audio.wav")) as audio:
                self.assertEqual((audio.getnchannels(), audio.getframerate(), audio.getsampwidth()), (1, 16000, 2))
            self.assertIsNotNone(n.find_cached(root / "projects", result["source"]["sha256"]))
