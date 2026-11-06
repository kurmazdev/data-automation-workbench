"""Excel export with literal strings, complete originals and a reproducible configuration."""

import io
import json
from itertools import chain
from typing import Any, Iterable, List

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


def export_workbook(run: dict) -> bytes:
    workbook = Workbook(write_only=True)
    alignment = Alignment(vertical="top", wrap_text=True)
    header_font = Font(color="FFFFFF", bold=True)
    header_fill = PatternFill("solid", fgColor="174D44")

    def add_sheet(name: str, headers: List[str], rows: Iterable[List[Any]]) -> None:
        sheet = workbook.create_sheet(name)
        sheet.freeze_panes = "A2"
        for index, header in enumerate(headers, 1):
            sheet.column_dimensions[get_column_letter(index)].width = min(
                55, max(18, len(header) + 4)
            )
        row_number = 0
        for row_number, row in enumerate(chain([headers], rows), start=1):
            cells = []
            for value in row:
                cell = WriteOnlyCell(sheet, value=value)
                # Force ALL exported strings to text: leading zeros and formula-like input are safe.
                if isinstance(cell.value, str):
                    cell.data_type = "s"
                    cell.number_format = "@"
                cell.alignment = alignment
                if row_number == 1:
                    cell.font = header_font
                    cell.fill = header_fill
                cells.append(cell)
            sheet.append(cells)
        sheet.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{row_number}"

    summary_rows = [
        ["Source file", run["filename"]],
        ["Run ID", run["id"]],
        ["Created (UTC)", run["created"]],
    ]
    summary_rows += [
        [key.replace("_", " ").title(), value] for key, value in run["summary"].items()
    ]
    summary_rows += [
        [
            "Changed definition",
            "Accepted records with at least one transformed value; subset of accepted.",
        ],
        ["Record numbers", "CSV logical record / XLSX worksheet row; header is record 1."],
        [
            "Value storage",
            "Cleaned values are text to preserve identifiers and decimal precision; blanks are empty cells.",
        ],
        [
            "Unmapped columns",
            "Excluded from cleaned fields; retained as original columns in both record sheets.",
        ],
        ["Duplicate policy", run["config"]["duplicate_policy"]],
    ]
    summary_rows += [["Source note", note] for note in run["source_notes"]]
    # One configuration row per field avoids Excel's per-cell 32,767 character limit.
    summary_rows += [
        ["Field configuration", json.dumps(field, ensure_ascii=False)]
        for field in run["config"]["fields"]
    ]
    summary_rows += [
        ["Duplicate keys", json.dumps(run["config"]["duplicate_keys"])],
        ["Null markers", json.dumps(run["config"]["null_markers"])],
    ]
    add_sheet("Summary", ["Item", "Value"], summary_rows)
    fields = [field["target"] for field in run["config"]["fields"]]
    columns = run["source_columns"]
    headers = (
        ["_source_record", "_changed", "_reasons"]
        + fields
        + [f"_original:{column}" for column in columns]
    )

    for status in ("accepted", "rejected"):
        rows = (
            [record["row"], "Yes" if record["changed"] else "No", " | ".join(record["reasons"])]
            + [record["cleaned"].get(field) for field in fields]
            + [record["original"][column] for column in columns]
            for record in run["records"]
            if record["status"] == status
        )
        add_sheet(status.title(), headers, rows)
    add_sheet(
        "Audit",
        ["Source record", "Destination field", "Action", "Before", "After", "Reason"],
        (
            [event[key] for key in ("row", "field", "action", "before", "after", "reason")]
            for event in run["audit"]
        ),
    )
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
