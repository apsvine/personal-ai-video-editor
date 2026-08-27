"""Run from apps/api with: python -m unittest discover -s tests -v."""

import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from app import media

from fastapi.testclient import TestClient
from app.main import app


class HealthTest(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.object(media, 'PROJECTS', Path(directory).resolve() / 'projects'))
        self.client = self.enterContext(TestClient(app))

    def test_health(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/json")
        self.assertEqual(response.json(), {
            "status": "ok", "service": "personal-ai-video-editor-api",
        })

    def test_local_origins_allowed(self):
        for origin in ("http://127.0.0.1:5173", "http://localhost:5173"):
            with self.subTest(origin=origin):
                response = self.client.get("/health", headers={"Origin": origin})
                self.assertEqual(response.headers["access-control-allow-origin"], origin)
                self.assertNotIn("access-control-allow-credentials", response.headers)

    def test_nonlocal_origin_not_allowed(self):
        response = self.client.get("/health", headers={"Origin": "https://example.com"})
        self.assertNotIn("access-control-allow-origin", response.headers)

    def test_post_not_allowed(self):
        self.assertEqual(self.client.post("/health").status_code, 405)


if __name__ == "__main__":
    unittest.main()
