"""Generate the synthetic date-cell fixture; not an original client workbook."""

from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font

workbook = Workbook()
sheet = workbook.active
sheet.title = "Synthetic IP dates"
sheet.append(["Trademark", "Application Date", "Renewal Due Date", "Applicant", "Class",
              "Jurisdiction", "Office"])
sheet.append(["Synthetic native Excel date preview", datetime(2026, 1, 31),
              datetime(2035, 3, 31), "Synthetic source owner", "9, 36", "IN", "IP India"])
for cell in sheet[1]:
    cell.font = Font(bold=True)
for address in ("B2", "C2"):
    sheet[address].number_format = "yyyy-mm-dd"
for column in "ABCDEFG":
    sheet.column_dimensions[column].width = 28
sheet.column_dimensions["A"].width = 44
sheet.freeze_panes = "A2"
workbook.save(Path(__file__).with_suffix(".xlsx"))
workbook.close()
