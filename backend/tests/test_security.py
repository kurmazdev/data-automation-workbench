import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from workbench.main import create_app


class LocalBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.client = TestClient(create_app(str(Path(self.directory.name) / "test.sqlite3")))

    def tearDown(self):
        self.client.close()
        self.directory.cleanup()

    def test_foreign_host_cannot_read_local_data(self):
        response = self.client.get("/api/runs", headers={"Host": "foreign.example"})
        self.assertEqual(response.status_code, 403)

    def test_foreign_origin_cannot_upload(self):
        response = self.client.post(
            "/api/datasets",
            headers={"Origin": "https://foreign.example"},
            files={"file": ("sample.csv", b"id\n001\n")},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.get("/api/runs").json(), [])

    def test_same_origin_and_development_uploads_work(self):
        for origin in ("http://testserver", "http://127.0.0.1:5173"):
            response = self.client.post(
                "/api/datasets",
                headers={"Origin": origin},
                files={"file": ("sample.csv", b"id\n001\n")},
            )
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
