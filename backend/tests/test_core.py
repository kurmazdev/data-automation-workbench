import io
import json
import tempfile
import unittest
import zipfile
import re
import csv
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from pydantic import ValidationError

from workbench.engine import process
from workbench.export import export_workbook
from workbench.ingest import InputError, parse_file
from workbench.models import FieldRule, ProcessConfig
from workbench.storage import Store

ROOT = Path(__file__).resolve().parents[2]


def config(**kwargs):
    return ProcessConfig(
        fields=[
            FieldRule(source="id", target="id", required=True),
            FieldRule(source="value", target="value"),
        ],
        **kwargs,
    )


def csv_data(text):
    return parse_file("test.csv", text.encode())


def xlsx_bytes(rows, setup=None):
    workbook = Workbook()
    for row in rows:
        workbook.active.append(row)
    if setup:
        setup(workbook.active)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def rewrite_sheet(content, change):
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(content)) as source, zipfile.ZipFile(
        output, "w"
    ) as destination:
        for entry in source.infolist():
            data = source.read(entry.filename)
            if entry.filename == "xl/worksheets/sheet1.xml":
                data = change(data.decode()).encode()
            destination.writestr(entry, data)
    return output.getvalue()


class IngestionTests(unittest.TestCase):
    def test_understated_xlsx_dimensions_do_not_hide_records_or_formulas(self):
        original = xlsx_bytes([["id", "value"], ["001", 0], ["002", "=1+1"]])
        content = rewrite_sheet(
            original, lambda xml: re.sub(r'<dimension ref="[^"]+"', '<dimension ref="A1:A1"', xml)
        )
        dataset = parse_file("dimensions.xlsx", content)
        self.assertEqual(dataset["columns"], ["id", "value"])
        self.assertEqual(len(dataset["rows"]), 2)
        self.assertEqual(dataset["rows"][0]["original"]["value"], "0")
        self.assertTrue(dataset["rows"][1]["issues"])

    def test_xlsx_sparse_coordinates_and_missing_headers_are_rejected(self):
        for content in [
            rewrite_sheet(
                xlsx_bytes([["id"], ["001"]]),
                lambda xml: xml.replace('r="2"', 'r="1000000"').replace('r="A2"', 'r="A1000000"'),
            ),
            rewrite_sheet(
                xlsx_bytes([["id"], ["001"]]), lambda xml: xml.replace('r="A2"', 'r="XFD2"')
            ),
            xlsx_bytes([["id"], ["001", "no header"]]),
        ]:
            with self.subTest(size=len(content)), self.assertRaises(InputError):
                parse_file("invalid.xlsx", content)

    def test_xlsx_short_rows_are_padded_without_losing_blanks(self):
        dataset = parse_file("short.xlsx", xlsx_bytes([["id", "value"], ["001"], ["002", 0]]))
        self.assertEqual(dataset["rows"][0]["original"], {"id": "001", "value": ""})

    def test_invalid_file_names_fail_before_storage_or_export(self):
        for name in ["bad\x01.csv", "a" * 256 + ".csv"]:
            with self.subTest(name=repr(name)), self.assertRaises(InputError):
                parse_file(name, b"id,value\n001,0")

    def test_xlsx_literal_formula_like_text_is_not_executed_or_rejected(self):
        def literal(sheet):
            sheet["B2"].data_type = "s"

        dataset = parse_file(
            "literal.xlsx", xlsx_bytes([["id", "value"], ["001", "=1+1"]], literal)
        )
        result = process(dataset, config())
        self.assertEqual(result["summary"]["accepted"], 1)
        self.assertEqual(result["records"][0]["original"]["value"], "=1+1")

    def test_csv_preserves_zeros_blank_whitespace_and_multiline(self):
        data = csv_data('id,value\n001234,0\n001235,\n001236," a\nb "\n\n')
        self.assertEqual(
            [row["original"]["id"] for row in data["rows"]], ["001234", "001235", "001236", ""]
        )
        self.assertEqual(data["rows"][0]["original"]["value"], "0")
        self.assertEqual(data["rows"][2]["original"]["value"], " a\nb ")
        self.assertEqual(data["rows"][3]["row"], 5)  # logical CSV record, not physical line

    def test_bom_and_explicit_delimiter(self):
        data = parse_file("test.CSV", "\ufeffid;value\n001;0\n".encode(), ";")
        self.assertEqual(data["columns"], ["id", "value"])
        self.assertEqual(data["rows"][0]["original"]["id"], "001")

    def test_bad_csv_is_actionable(self):
        examples = [
            b"",
            b"id,value\n",
            b"id,id\n1,2",
            b"id,\n1,2",
            b'id,value\n1,"unclosed',
            b"id,value\n1,2,3",
            b"id,value\n1",
            b"id,value\n1,\xff",
            b"id,value\n1,\x01",
            b"id,value\n1,\x00",
        ]
        for content in examples:
            with self.subTest(content=content), self.assertRaises(InputError):
                parse_file("bad.csv", content)

    def test_empty_and_bad_xlsx(self):
        for content in [b"not a zip", xlsx_bytes([]), xlsx_bytes([["id"]])]:
            with self.subTest(content=content[:10]), self.assertRaises(InputError):
                parse_file("bad.xlsx", content)

    def test_file_limits_and_extensions(self):
        for filename, content in [
            ("test.xls", b"abc"),
            ("large.csv", b"x" * (10 * 1024 * 1024 + 1)),
            ("rows.csv", b"id\n" + b"x\n" * 10001),
            ("cell.csv", b"id\n" + b"x" * 10001),
            (
                "columns.csv",
                (
                    ",".join(str(i) for i in range(101)) + "\n" + ",".join("x" for _ in range(101))
                ).encode(),
            ),
        ]:
            with self.subTest(filename=filename), self.assertRaises(InputError):
                parse_file(filename, content)

    def test_cell_budget(self):
        content = (
            ",".join(f"c{i}" for i in range(100))
            + "\n"
            + (",".join("x" for _ in range(100)) + "\n") * 2001
        ).encode()
        with self.assertRaisesRegex(InputError, "200,000-cell"):
            parse_file("budget.csv", content)

    def test_xlsx_preserves_text_zero_masks_and_zero(self):
        def setup(sheet):
            sheet["A3"].number_format = "000000"

        data = parse_file(
            "test.xlsx", xlsx_bytes([["id", "value"], ["001234", 0], [1235, None]], setup)
        )
        self.assertEqual(data["rows"][0]["original"], {"id": "001234", "value": "0"})
        self.assertEqual(data["rows"][1]["original"], {"id": "001235", "value": ""})

    def test_xlsx_formulas_errors_reject_even_unmapped(self):
        data = parse_file(
            "test.xlsx", xlsx_bytes([["id", "value"], ["001", "=1+1"], ["002", "#DIV/0!"]])
        )
        result = process(data, ProcessConfig(fields=[FieldRule(source="id", target="id")]))
        self.assertEqual(result["summary"]["rejected"], 2)
        self.assertTrue(
            all("formula or spreadsheet error" in row["reasons"][0] for row in result["records"])
        )

    def test_xlsx_typed_dates_are_explicit_and_times_are_not_truncated(self):
        data = parse_file(
            "dates.xlsx",
            xlsx_bytes(
                [["id", "value"], ["1", datetime(2026, 4, 3)], ["2", datetime(2026, 4, 3, 14, 30)]]
            ),
        )
        rules = config()
        rules.fields[1].kind = "date"
        result = process(data, rules)
        self.assertEqual(result["records"][0]["cleaned"]["value"], "2026-04-03")
        self.assertIn("Excel date at midnight", result["records"][0]["events"][0]["reason"])
        self.assertEqual(result["records"][1]["status"], "rejected")
        self.assertIn("14:30", result["records"][1]["original"]["value"])

    def test_xlsx_formula_headers_rejected(self):
        with self.assertRaisesRegex(InputError, "headers cannot contain formulas"):
            parse_file("headers.xlsx", xlsx_bytes([["=1+1"], ["001"]]))

    def test_expanded_archive_limit(self):
        import zipfile

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("large.xml", b"0" * (50 * 1024 * 1024 + 1))
        with self.assertRaisesRegex(InputError, "expanded workbook"):
            parse_file("large.xlsx", buffer.getvalue())


class ProcessingTests(unittest.TestCase):
    def test_typed_excel_small_numbers_expand_with_audit_but_csv_exponents_reject(self):
        rules = config()
        rules.fields[1].kind = "decimal"
        dataset = parse_file(
            "numbers.xlsx", xlsx_bytes([["id", "value"], ["001", 0.0000001], ["002", 1e20]])
        )
        result = process(dataset, rules)
        self.assertEqual(result["summary"]["accepted"], 2)
        self.assertEqual(result["records"][0]["cleaned"]["value"], "0.0000001")
        self.assertIn("typed Excel number", result["records"][0]["events"][0]["reason"])
        self.assertEqual(process(csv_data("id,value\n001,1e-07"), rules)["summary"]["rejected"], 1)

    def test_zero_and_blank_are_distinct(self):
        rules = config()
        rules.fields[1].kind = "decimal"
        result = process(csv_data("id,value\n001,0\n002,\n003,N/A"), rules)
        self.assertEqual([row["cleaned"]["value"] for row in result["records"]], ["0", None, "N/A"])
        self.assertEqual(result["records"][2]["status"], "rejected")

    def test_null_markers_are_explicit_case_sensitive(self):
        result = process(
            csv_data("id,value\n001,N/A\n002,n/a\n003,0"), config(null_markers=["N/A"])
        )
        self.assertEqual([row["cleaned"]["value"] for row in result["records"]], [None, "n/a", "0"])
        self.assertEqual(result["records"][0]["events"][0]["after"], None)

    def test_each_transform_has_a_reason_and_original(self):
        rules = config()
        rules.fields[1].collapse_spaces = True
        rules.fields[1].casing = "upper"
        result = process(csv_data('id,value\n001,"  Acme   Co  "'), rules)
        record = result["records"][0]
        self.assertEqual(record["original"]["value"], "  Acme   Co  ")
        self.assertEqual(record["cleaned"]["value"], "ACME CO")
        self.assertEqual(len(record["events"]), 3)
        self.assertTrue(
            all(event["reason"] and event["before"] != event["after"] for event in record["events"])
        )

    def test_no_operations_means_no_hidden_trim(self):
        rules = config()
        rules.fields[1].trim = False
        record = process(csv_data('id,value\n001,"  exact  "'), rules)["records"][0]
        self.assertEqual(record["cleaned"]["value"], "  exact  ")
        self.assertFalse(record["changed"])

    def test_dates_never_guess_and_validate_calendar(self):
        rules = config()
        rules.fields[1].kind = "date"
        result = process(
            csv_data("id,value\n1,04/03/2026\n2,2026-02-30\n3,2026-04-03\n4,2026-4-3"), rules
        )
        self.assertEqual(result["summary"]["accepted"], 1)
        rules.fields[1].date_format = "%d/%m/%Y"
        record = process(csv_data("id,value\n1,04/03/2026"), rules)["records"][0]
        self.assertEqual(record["cleaned"]["value"], "2026-03-04")
        self.assertIn("DD/MM/YYYY", record["events"][0]["reason"])

    def test_decimals_are_lossless_and_strict(self):
        rules = config()
        rules.fields[1].kind = "decimal"
        data = csv_data(
            'id,value\n1,12345678901234567890.123456789\n2,0\n3,NaN\n4,1e4\n5,"1,234"\n6,$10\n7,.25\n8,-0.50'
        )
        result = process(data, rules)
        self.assertEqual(result["summary"]["accepted"], 4)
        self.assertEqual(result["records"][0]["cleaned"]["value"], "12345678901234567890.123456789")
        self.assertEqual(result["records"][6]["cleaned"]["value"], "0.25")

    def test_email_and_required_values(self):
        rules = config(null_markers=["NULL"])
        rules.fields[1].kind = "email"
        rules.fields[1].required = True
        result = process(
            csv_data("id,value\n1,hello@example.com\n2,bad address\n3,\n4,NULL"), rules
        )
        self.assertEqual(result["summary"]["rejected"], 3)
        self.assertTrue(all(row["reasons"] for row in result["records"][1:]))

    def test_duplicate_policies_and_invalid_first(self):
        data = csv_data("id,value\n001,bad\n001,a@example.com\n001,b@example.com")
        rules = config(duplicate_keys=["id"], duplicate_policy="reject_later")
        rules.fields[1].kind = "email"
        result = process(data, rules)
        self.assertEqual(
            [row["status"] for row in result["records"]], ["rejected", "accepted", "rejected"]
        )
        self.assertIn("source record 3", result["records"][2]["reasons"][0])
        rules.duplicate_policy = "keep_all"
        result = process(data, rules)
        self.assertEqual(result["summary"]["accepted"], 2)
        self.assertEqual(result["records"][2]["events"][0]["action"], "duplicate_kept")

    def test_composite_keys_and_blank_keys(self):
        rules = config(duplicate_keys=["id", "value"], duplicate_policy="reject_later")
        result = process(csv_data("id,value\n1,a\n1,b\n1,a\n2,\n2,"), rules)
        self.assertEqual(result["summary"]["rejected"], 1)

    def test_all_blank_records_rejected_and_nothing_dropped(self):
        data = csv_data("id,value\n,\n\n1,0")
        result = process(data, ProcessConfig(fields=[FieldRule(source="value", target="value")]))
        self.assertEqual(result["summary"]["total"], 3)
        self.assertEqual(result["summary"]["rejected"], 2)
        self.assertEqual(len(result["records"]), len(data["rows"]))

    def test_configuration_rejects_invalid_mappings(self):
        bad = [
            {"fields": []},
            {"fields": [{"source": "id", "target": "_source_record"}]},
            {"fields": [{"source": "id", "target": "bad\x01field"}]},
            {"fields": [{"source": "id", "target": "bad\ud800field"}]},
            {"fields": [{"source": "id", "target": "  "}]},
            {"fields": [{"source": "id", "target": "a"}, {"source": "id", "target": "b"}]},
            {"fields": [{"source": "id", "target": "a"}, {"source": "value", "target": "a"}]},
            {"fields": [{"source": "id", "target": "id"}], "duplicate_keys": ["missing"]},
            {"fields": [{"source": "id", "target": "id"}], "duplicate_policy": "reject_later"},
        ]
        for payload in bad:
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                ProcessConfig.model_validate(payload)
        with self.assertRaisesRegex(ValueError, "do not exist"):
            process(csv_data("other,value\n1,2"), config())

    def test_repeatable_run_does_not_mutate_source(self):
        data = csv_data('id,value\n001," Acme "')
        before = json.dumps(data)
        first = process(data, config())
        self.assertEqual(first, process(data, config()))
        self.assertEqual(before, json.dumps(data))


class ExportAndStorageTests(unittest.TestCase):
    def test_formula_injection_prefixes_remain_literal_in_all_export_sheets(self):
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer)
        writer.writerow(["id", "value"])
        payloads = [
            '=HYPERLINK("https://example.com","click")',
            "+SUM(A1:A2)",
            "-1+2",
            "@SUM(A1:A2)",
            "\t=1+1",
        ]
        for index, value in enumerate(payloads):
            writer.writerow([str(index).zfill(6), value])
        dataset = csv_data(buffer.getvalue())
        rules = config()
        result = process(dataset, rules)
        run = {
            **self.sample_run(),
            **result,
            "source_columns": dataset["columns"],
            "config": rules.model_dump(),
        }
        workbook = load_workbook(io.BytesIO(export_workbook(run)))
        self.assertFalse(
            any(
                cell.data_type == "f" or cell.hyperlink
                for sheet in workbook
                for row in sheet
                for cell in row
            )
        )
        self.assertEqual([workbook["Accepted"].cell(row, 7).value for row in range(2, 7)], payloads)
        self.assertEqual(workbook["Audit"].freeze_panes, "A2")

    def test_empty_record_sheets_have_headers_and_filters(self):
        for status in ["accepted", "rejected"]:
            run = self.sample_run()
            run["records"] = [record for record in run["records"] if record["status"] != status]
            workbook = load_workbook(io.BytesIO(export_workbook(run)))
            self.assertEqual(workbook[status.title()].max_row, 1)
            self.assertEqual(workbook[status.title()].freeze_panes, "A2")
            self.assertTrue(workbook[status.title()].auto_filter.ref)

    def sample_run(self):
        data = parse_file(
            "messy_customers.csv", (ROOT / "samples/messy_customers.csv").read_bytes()
        )
        rules = ProcessConfig.model_validate_json(
            (ROOT / "samples/customer_rules.json").read_text()
        )
        return {
            **process(data, rules),
            "filename": data["filename"],
            "config": rules.model_dump(),
            "id": "sample",
            "created": "2026-01-01T00:00:00+00:00",
            "source_columns": data["columns"],
            "source_notes": data["notes"],
        }

    def test_sample_complete_accounting(self):
        run = self.sample_run()
        self.assertEqual(run["summary"]["total"], 17)
        self.assertEqual(run["summary"]["accepted"], 8)
        self.assertEqual(run["summary"]["rejected"], 9)
        self.assertTrue(
            all(record["reasons"] for record in run["records"] if record["status"] == "rejected")
        )
        self.assertTrue(all(record["events"] for record in run["records"]))

    def test_export_sheets_counts_originals_and_formula_safety(self):
        run = self.sample_run()
        workbook = load_workbook(io.BytesIO(export_workbook(run)))
        self.assertEqual(workbook.sheetnames, ["Summary", "Accepted", "Rejected", "Audit"])
        self.assertEqual(workbook["Accepted"].max_row, 9)
        self.assertEqual(workbook["Rejected"].max_row, 10)
        self.assertEqual(workbook["Audit"].max_row, run["summary"]["audit_events"] + 1)
        self.assertEqual(workbook["Accepted"]["D2"].value, "001234")
        self.assertEqual(workbook["Accepted"]["G2"].value, "0")
        self.assertIn("_original:Customer ID", [cell.value for cell in workbook["Accepted"][1]])
        self.assertFalse(
            any(cell.data_type == "f" for sheet in workbook for row in sheet for cell in row)
        )
        self.assertTrue(
            any(cell.value == "=SUM(A1:A2)" for row in workbook["Accepted"] for cell in row)
        )

    def test_export_long_originals_do_not_truncate(self):
        run = self.sample_run()
        run["records"][0]["original"]["Notes"] = "x" * 10_000
        workbook = load_workbook(io.BytesIO(export_workbook(run)))
        self.assertEqual(workbook["Accepted"].cell(2, 17).value, "x" * 10_000)

    def test_storage_persists_between_instances(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.sqlite3"
            store = Store(path)
            saved = store.save("run", self.sample_run())
            reopened = Store(path)
            self.assertEqual(reopened.get("run", saved["id"]), saved)
            self.assertEqual(reopened.history()[0]["id"], saved["id"])
            self.assertIsNone(reopened.get("dataset", saved["id"]))

    def test_many_rejection_reasons_export_without_truncation(self):
        headers = [f"source{i}" for i in range(100)]
        rules = ProcessConfig(
            fields=[
                FieldRule(source=header, target=f"field{i}".ljust(80, "x"), kind="decimal")
                for i, header in enumerate(headers)
            ]
        )
        dataset = parse_file("errors.xlsx", xlsx_bytes([headers, ["=1+1"] * 100]))
        run = {
            **process(dataset, rules),
            "filename": "errors.xlsx",
            "config": rules.model_dump(),
            "id": "test",
            "created": "2026-01-01",
            "source_columns": headers,
            "source_notes": [],
        }
        workbook = load_workbook(io.BytesIO(export_workbook(run)))
        self.assertEqual(workbook["Rejected"]["C2"].value, " | ".join(run["records"][0]["reasons"]))
        self.assertEqual(workbook["Audit"].max_row, 201)

    def test_xlsx_sample_matches_csv(self):
        csv_source = parse_file("sample.csv", (ROOT / "samples/messy_customers.csv").read_bytes())
        xlsx_source = parse_file(
            "sample.xlsx", (ROOT / "samples/messy_customers.xlsx").read_bytes()
        )
        self.assertEqual(csv_source["rows"], xlsx_source["rows"])


if __name__ == "__main__":
    unittest.main()
