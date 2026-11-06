"""Exercise both sample formats through parsing, rules, persistence and Excel export."""

import argparse
import io
import json
from pathlib import Path

from openpyxl import load_workbook

from workbench.engine import process
from workbench.export import export_workbook
from workbench.ingest import parse_file
from workbench.models import ProcessConfig
from workbench.storage import Store


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="data/sample-cleaned.xlsx")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    rules = ProcessConfig.model_validate_json((root / "samples/customer_rules.json").read_text())
    store = Store()
    summaries = []
    for extension in ("csv", "xlsx"):
        source = root / "samples" / f"messy_customers.{extension}"
        dataset = store.save("dataset", parse_file(source.name, source.read_bytes()))
        run = store.save(
            "run",
            {
                **process(dataset, rules),
                "dataset_id": dataset["id"],
                "filename": source.name,
                "config": rules.model_dump(),
                "source_columns": dataset["columns"],
                "source_notes": dataset["notes"],
            },
        )
        content = export_workbook(run)
        workbook = load_workbook(io.BytesIO(content))
        assert workbook.sheetnames == ["Summary", "Accepted", "Rejected", "Audit"]
        assert run["summary"]["total"] == 17
        assert run["summary"]["accepted"] == 8
        assert run["summary"]["rejected"] == 9
        assert workbook["Accepted"]["D2"].value == "001234"
        assert workbook["Accepted"]["G2"].value == "0"
        assert workbook["Accepted"]["G3"].value is None
        assert workbook["Accepted"].max_row + workbook["Rejected"].max_row - 2 == 17
        assert not any(cell.data_type == "f" for sheet in workbook for row in sheet for cell in row)
        summaries.append(run["summary"])
        print(f"{source.name}: {json.dumps(run['summary'])}")
        if extension == "csv":
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(content)
            print(f"Workbook: {output.resolve()}")
    assert summaries[0] == summaries[1]
    print("Both formats verified; all source records accounted for.")


if __name__ == "__main__":
    main()
