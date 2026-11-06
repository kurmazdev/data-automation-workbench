import io
import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from workbench.main import create_app

ROOT = Path(__file__).resolve().parents[2]


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = str(Path(self.directory.name) / "test.sqlite3")
        self.client = TestClient(create_app(self.path))

    def tearDown(self):
        self.client.close()
        self.directory.cleanup()

    def upload(self, name="messy_customers.csv"):
        content = (ROOT / "samples" / name).read_bytes()
        response = self.client.post("/api/datasets", files={"file": (name, content)})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_csv_and_xlsx_full_workflow_pagination_filters_export_and_resume(self):
        rules = json.loads((ROOT / "samples/customer_rules.json").read_text())
        for filename in ["messy_customers.csv", "messy_customers.xlsx"]:
            with self.subTest(filename=filename):
                dataset = self.upload(filename)
                preview = self.client.get(f"/api/datasets/{dataset['id']}?limit=2").json()
                self.assertEqual(preview["row_count"], 17)
                self.assertEqual(preview["rows"][0]["original"]["Customer ID"], "001234")
                response = self.client.post(f"/api/datasets/{dataset['id']}/runs", json=rules)
                self.assertEqual(response.status_code, 201, response.text)
                run = response.json()
                self.assertEqual(run["summary"]["accepted"] + run["summary"]["rejected"], 17)
                for status, expected in [
                    ("all", 17),
                    ("accepted", 8),
                    ("rejected", 9),
                    ("changed", run["summary"]["changed"]),
                ]:
                    page = self.client.get(f"/api/runs/{run['id']}?status={status}&limit=2").json()
                    self.assertEqual(page["filtered_count"], expected)
                    self.assertEqual(len(page["records"]), min(2, expected))
                rejected = self.client.get(f"/api/runs/{run['id']}?status=rejected&offset=8").json()
                self.assertEqual(len(rejected["records"]), 1)
                response = self.client.get(f"/api/runs/{run['id']}/export")
                self.assertEqual(response.status_code, 200)
                workbook = load_workbook(io.BytesIO(response.content))
                self.assertEqual(workbook.sheetnames, ["Summary", "Accepted", "Rejected", "Audit"])
                with TestClient(create_app(self.path)) as reopened:
                    self.assertEqual(reopened.get(f"/api/runs/{run['id']}").status_code, 200)
                    self.assertEqual(reopened.get("/api/runs").json()[0]["id"], run["id"])

    def test_invalid_files_and_configurations(self):
        for name, content in [
            ("empty.csv", b""),
            ("bad.xlsx", b"abc"),
            ("bad.csv", b"a,a\n1,2"),
            ("file.exe", b"abc"),
        ]:
            with self.subTest(name=name):
                response = self.client.post("/api/datasets", files={"file": (name, content)})
                self.assertEqual(response.status_code, 422)
                self.assertIsInstance(response.json()["detail"], str)
        dataset = self.upload()
        self.assertEqual(
            self.client.post(
                f"/api/datasets/{dataset['id']}/runs", json={"fields": []}
            ).status_code,
            422,
        )
        self.assertEqual(
            self.client.post(
                f"/api/datasets/{dataset['id']}/runs",
                json={"fields": [{"source": "absent", "target": "id"}]},
            ).status_code,
            422,
        )

    def test_missing_ids_and_bad_queries(self):
        for path in ["/api/datasets/missing", "/api/runs/missing", "/api/runs/missing/export"]:
            self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.client.get("/api/runs/missing?status=invalid").status_code, 422)
        self.assertEqual(self.client.get("/api/datasets/missing?offset=-1").status_code, 422)

    def test_health_and_sample_download(self):
        self.assertEqual(self.client.get("/api/health").json(), {"status": "ok"})
        response = self.client.get("/api/sample")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, (ROOT / "samples/messy_customers.csv").read_bytes())

    def test_sample_preset_is_valid_and_complete(self):
        from workbench.models import ProcessConfig

        expected = ProcessConfig.model_validate_json(
            (ROOT / "samples/customer_rules.json").read_text()
        ).model_dump()
        self.assertEqual(self.client.get("/api/sample/config").json(), expected)

    def test_search_matches_original_cleaned_and_reasons_before_paging(self):
        dataset = self.upload()
        rules = json.loads((ROOT / "samples/customer_rules.json").read_text())
        run = self.client.post(f"/api/datasets/{dataset['id']}/runs", json=rules).json()
        path = f"/api/runs/{run['id']}"
        for query, status, expected in [
            ("001234", "all", 2),
            ("001234", "rejected", 1),
            ("ACCOUNTS@NORTHSTAR", "accepted", 1),
            ("Duplicate key", "rejected", 1),
            ("not-present", "all", 0),
        ]:
            with self.subTest(query=query):
                response = self.client.get(
                    path, params={"q": query, "status": status, "limit": 1}
                ).json()
                self.assertEqual(response["filtered_count"], expected)
                self.assertEqual(len(response["records"]), min(expected, 1))
                self.assertEqual(response["summary"], run["summary"])
        self.assertEqual(self.client.get(path, params={"q": "x" * 201}).status_code, 422)

    def test_rerun_preserves_previous_configuration_and_outcomes(self):
        dataset = self.upload()
        rules = json.loads((ROOT / "samples/customer_rules.json").read_text())
        path = f"/api/datasets/{dataset['id']}/runs"
        first = self.client.post(path, json=rules).json()
        before = self.client.get(f"/api/runs/{first['id']}").json()
        rules["duplicate_policy"] = "keep_all"
        second = self.client.post(path, json=rules).json()
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(second["summary"]["accepted"], 9)
        self.assertEqual(before, self.client.get(f"/api/runs/{first['id']}").json())


if __name__ == "__main__":
    unittest.main()
