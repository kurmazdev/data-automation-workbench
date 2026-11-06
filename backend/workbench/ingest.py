"""Bounded, loss-aware parsing. No type inference for CSV values."""

import csv
import io
import re
import zipfile
import posixpath
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Dict

from openpyxl import load_workbook
from openpyxl.utils.cell import column_index_from_string
from defusedxml import ElementTree as XML

MAX_BYTES = 10 * 1024 * 1024
MAX_ROWS = 10_000
MAX_COLUMNS = 100
MAX_CELL_LENGTH = 10_000
MAX_CELLS = 200_000
INVALID_XML_TEXT = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


class InputError(ValueError):
    """An actionable file validation failure."""


def _string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    return str(value)


def _check_worksheet_bounds(archive: zipfile.ZipFile) -> None:
    """Check stored coordinates, not just the workbook's sometimes incorrect dimensions.

    This bounded XML pass prevents an understated dimension from hiding data,
    and oversized sparse coordinates from allocating millions of empty cells.
    """
    namespace = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with archive.open("xl/workbook.xml") as source:
        workbook = XML.parse(source).getroot()
    with archive.open("xl/_rels/workbook.xml.rels") as source:
        relationships = {item.get("Id"): item for item in XML.parse(source).getroot()}
    for sheet in workbook.findall("s:sheets/s:sheet", namespace):
        relation = relationships.get(
            sheet.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        )
        if relation is not None and relation.get("Type", "").endswith("/worksheet"):
            break
    else:
        raise InputError("The workbook contains no data worksheets.")
    target = relation.get("Target", "")
    part = posixpath.normpath(
        target.lstrip("/") if target.startswith("/") else posixpath.join("xl", target)
    )
    current_row, current_column, width = 0, 0, 0
    with archive.open(part) as source:
        for event, element in XML.iterparse(source, events=("start", "end")):
            tag = element.tag.rsplit("}", 1)[-1]
            if event == "start" and tag == "row":
                number = int(element.get("r", current_row + 1))
                if number <= current_row:
                    raise InputError(
                        "Worksheet rows are out of order. Re-save the workbook and retry."
                    )
                current_row, current_column = number, 0
                if current_row > MAX_ROWS + 1:
                    raise InputError(
                        "The worksheet exceeds the 10,000 data-row limit (including blank rows)."
                    )
            elif event == "start" and tag == "c":
                reference = element.get("r")
                if reference:
                    match = re.fullmatch(r"([A-Z]+)([1-9][0-9]*)", reference)
                    if not match or int(match[2]) != current_row:
                        raise InputError(
                            "Invalid worksheet cell coordinates. Re-save the workbook and retry."
                        )
                    column = column_index_from_string(match[1])
                else:
                    column = current_column + 1
                if column <= current_column:
                    raise InputError(
                        "Worksheet cells are out of order. Re-save the workbook and retry."
                    )
                current_column, width = column, max(width, column)
                if width > MAX_COLUMNS:
                    raise InputError(
                        "The worksheet exceeds the 100-column limit (including formatted cells)."
                    )
            if max(0, current_row - 1) * width > MAX_CELLS:
                raise InputError(
                    "The file exceeds the 200,000-cell limit. Split it into smaller files."
                )
            if event == "end":
                element.clear()


def parse_file(filename: str, content: bytes, delimiter: str = ",") -> Dict[str, Any]:
    if not content:
        raise InputError("The file is empty. Add column headers and at least one data row.")
    if len(content) > MAX_BYTES:
        raise InputError("File exceeds the 10 MB upload limit.")
    extension = Path(filename).suffix.lower()
    if len(Path(filename).name) > 255:
        raise InputError("File names must be at most 255 characters.")
    if INVALID_XML_TEXT.search(Path(filename).name):
        raise InputError(
            "The file name contains unsupported control characters. Rename it and retry."
        )
    notes = []
    raw_rows = []
    sheet_name = None
    if extension == ".csv":
        if delimiter not in (",", ";", "\t"):
            raise InputError("Choose comma, semicolon, or tab as the delimiter.")
        try:
            decoded = content.decode("utf-8-sig")
            if "\x00" in decoded:
                raise InputError("CSV contains null bytes. Save it as a UTF-8 CSV and retry.")
            reader = csv.reader(io.StringIO(decoded, newline=""), delimiter=delimiter, strict=True)
            headers = next(reader, [])
            for index, row in enumerate(reader, start=2):
                if len(raw_rows) >= MAX_ROWS:
                    raise InputError("The file exceeds the 10,000 data-row limit.")
                # A physical blank CSV record is still a record, never discarded.
                if not row:
                    row = [""] * len(headers)
                if len(row) != len(headers):
                    raise InputError(
                        f"CSV record {index} has {len(row)} values; expected {len(headers)}. Fix the delimiter or quoting."
                    )
                raw_rows.append({"row": index, "values": row, "issues": []})
        except UnicodeDecodeError as exc:
            raise InputError("CSV must use UTF-8 encoding. Re-save it as CSV UTF-8.") from exc
        except csv.Error as exc:
            raise InputError(f"Malformed CSV: {exc}.") from exc
    elif extension == ".xlsx":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                if sum(item.file_size for item in archive.infolist()) > 50 * 1024 * 1024:
                    raise InputError("The expanded workbook exceeds the 50 MB safety limit.")
                _check_worksheet_bounds(archive)
            workbook = load_workbook(
                io.BytesIO(content), read_only=True, data_only=False, keep_links=False
            )
            try:
                sheet = workbook.worksheets[0]
                sheet_name = sheet.title
                notes.append(
                    f"Read first worksheet: {sheet.title}. Other worksheets are not included."
                )
                notes.append(
                    "Numeric cells are read as stored; only simple zero masks such as 000000 restore display padding. Zeros or precision already lost in the source cannot be recovered."
                )
                if sheet.max_column and sheet.max_column > MAX_COLUMNS:
                    raise InputError(
                        "The worksheet exceeds the 100-column limit (including formatted cells)."
                    )
                if sheet.max_row and sheet.max_row > MAX_ROWS + 1:
                    raise InputError(
                        "The worksheet exceeds the 10,000 data-row limit (including formatted rows)."
                    )
                # Some producers write A1:A1 even when other rows/columns exist.
                # Stored coordinates have already been checked independently.
                sheet.reset_dimensions()
                rows = sheet.iter_rows()
                header_cells = next(rows, [])
                if any(cell.data_type in ("f", "e") for cell in header_cells):
                    raise InputError(
                        "Column headers cannot contain formulas or spreadsheet errors."
                    )
                headers = [_string(cell.value) for cell in header_cells]
                for index, cells in enumerate(rows, start=2):
                    if len(raw_rows) >= MAX_ROWS:
                        raise InputError("The worksheet exceeds the 10,000 data-row limit.")
                    values, issues, excel_dates, excel_numbers = [], [], {}, {}
                    if len(cells) > len(headers):
                        raise InputError(
                            "A data column has no header. Add a name for every column in the first worksheet row."
                        )
                    for column_index, cell in enumerate(cells):
                        value = _string(cell.value)
                        if cell.data_type in ("f", "e"):
                            issues.append(
                                f"{cell.coordinate}: formula or spreadsheet error; replace it with a verified value."
                            )
                        if cell.data_type == "n" and isinstance(cell.value, (int, float)):
                            excel_numbers[headers[column_index]] = value
                        if cell.data_type == "d" and isinstance(cell.value, (date, datetime)):
                            if not isinstance(cell.value, datetime) or cell.value.time() == time(0):
                                excel_dates[headers[column_index]] = (
                                    cell.value.date().isoformat()
                                    if isinstance(cell.value, datetime)
                                    else cell.value.isoformat()
                                )
                        # Excel numeric cells with a simple zero mask have an explicit displayed identifier.
                        if (
                            cell.data_type == "n"
                            and isinstance(cell.value, int)
                            and re.fullmatch(r"0{2,}", cell.number_format)
                        ):
                            value = ("-" if cell.value < 0 else "") + str(abs(cell.value)).zfill(
                                len(cell.number_format)
                            )
                        values.append(value)
                    values.extend([""] * (len(headers) - len(values)))
                    record = {"row": index, "values": values, "issues": issues}
                    if excel_dates:
                        record["excel_dates"] = excel_dates
                    if excel_numbers:
                        record["excel_numbers"] = excel_numbers
                    raw_rows.append(record)
            finally:
                workbook.close()
        except InputError:
            raise
        except Exception as exc:
            raise InputError(
                "Cannot read this XLSX workbook. It may be damaged, encrypted, or not a valid XLSX file."
            ) from exc
    else:
        raise InputError("Unsupported file type. Upload a .csv or .xlsx file.")
    if not headers or not any(headers):
        raise InputError("No column headers found. The first row must contain column names.")
    if len(headers) > MAX_COLUMNS:
        raise InputError("The file exceeds the 100-column limit.")
    if any(not header.strip() for header in headers):
        raise InputError("Every column needs a nonblank header.")
    if len(set(headers)) != len(headers):
        raise InputError("Duplicate column headers found. Give each source column a unique name.")
    if not raw_rows:
        raise InputError("The file contains headers but no data rows.")
    if len(raw_rows) * len(headers) > MAX_CELLS:
        raise InputError("The file exceeds the 200,000-cell limit. Split it into smaller files.")
    if any(len(header) > 200 for header in headers):
        raise InputError("Column headers must be at most 200 characters.")
    for row in raw_rows:
        if any(len(value) > MAX_CELL_LENGTH for value in row["values"]):
            raise InputError(f"Record {row['row']} contains a value longer than 10,000 characters.")
        row["original"] = dict(zip(headers, row.pop("values")))
    if any(
        INVALID_XML_TEXT.search(value)
        for value in headers + [value for row in raw_rows for value in row["original"].values()]
    ):
        raise InputError(
            "The file contains control characters that Excel cannot store. Remove them and retry."
        )
    return {
        "filename": Path(filename).name,
        "columns": headers,
        "rows": raw_rows,
        "notes": notes,
        "sheet": sheet_name,
    }
