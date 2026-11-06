"""Rebuild the XLSX example from the CSV, preserving literal strings."""

import csv
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

root = Path(__file__).resolve().parents[1]
workbook = Workbook()
sheet = workbook.active
sheet.title = "Customers"
with (root / "samples/messy_customers.csv").open(newline="", encoding="utf-8") as source:
    for row in csv.reader(source):
        sheet.append(row)
        for cell in sheet[sheet.max_row]:
            cell.data_type = "s"
            cell.number_format = "@"
for cell in sheet[1]:
    cell.font = Font(color="FFFFFF", bold=True)
    cell.fill = PatternFill("solid", fgColor="174D44")
for column, width in zip("ABCDEFG", [18, 25, 34, 18, 20, 12, 65]):
    sheet.column_dimensions[column].width = width
sheet.freeze_panes = "A2"
workbook.save(root / "samples/messy_customers.xlsx")
print("Wrote samples/messy_customers.xlsx")
