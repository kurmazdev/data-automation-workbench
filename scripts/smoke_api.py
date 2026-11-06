"""Exercise the HTTP workflow against a running local backend."""

import argparse
import io
import json
from pathlib import Path
from urllib.request import Request, urlopen
from uuid import uuid4

from openpyxl import load_workbook


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]

    def request(path: str, data=None, headers=None):
        with urlopen(
            Request(args.base_url + path, data=data, headers=headers or {}), timeout=60
        ) as response:
            return response.read()

    assert json.loads(request("/api/health"))["status"] == "ok"
    for extension in ("csv", "xlsx"):
        source = root / "samples" / f"messy_customers.{extension}"
        boundary = uuid4().hex
        body = (
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{source.name}"\r\n'
                "Content-Type: application/octet-stream\r\n\r\n"
            ).encode()
            + source.read_bytes()
            + f"\r\n--{boundary}--\r\n".encode()
        )
        dataset = json.loads(
            request(
                "/api/datasets", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"}
            )
        )
        preview = json.loads(request(f"/api/datasets/{dataset['id']}"))
        assert preview["rows"][0]["original"]["Customer ID"] == "001234"
        run = json.loads(
            request(
                f"/api/datasets/{dataset['id']}/runs",
                (root / "samples/customer_rules.json").read_bytes(),
                {"Content-Type": "application/json"},
            )
        )
        assert run["summary"]["total"] == 17
        assert run["summary"]["accepted"] == 8
        assert run["summary"]["rejected"] == 9
        rejected = json.loads(request(f"/api/runs/{run['id']}?status=rejected"))
        assert all(record["reasons"] for record in rejected["records"])
        workbook = load_workbook(io.BytesIO(request(f"/api/runs/{run['id']}/export")))
        assert workbook.sheetnames == ["Summary", "Accepted", "Rejected", "Audit"]
        assert workbook["Accepted"]["D2"].value == "001234"
        print(
            f"{source.name}: HTTP upload → preview → process → review → export passed. Run {run['id']}"
        )


if __name__ == "__main__":
    main()
