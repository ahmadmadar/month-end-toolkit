"""Write the reconciliation workbook.

Session 1 writes the Run log tab only. Later sessions add Summary, Fees to add,
Needs review and Matched.
"""

import os
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from toolkit.errors import ToolkitError
from toolkit.runlog import RunLog

_HEADER_FONT = Font(bold=True)
_HEADER_FILL = PatternFill("solid", fgColor="DDDDDD")
_WARNING_FILL = PatternFill("solid", fgColor="FFF2CC")
_WIDTHS = {"Level": 10, "Step": 12, "Item": 32, "Value": 28, "Note": 90}


def _add_run_log(wb: Workbook, runlog: RunLog) -> None:
    ws = wb.active
    ws.title = "Run log"
    ws.append(RunLog.COLUMNS)
    for cell in ws[1]:
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
    for row in runlog.rows():
        ws.append(row)
        if row[0] == "warning":
            for cell in ws[ws.max_row]:
                cell.fill = _WARNING_FILL
    for col, name in enumerate(RunLog.COLUMNS, start=1):
        ws.column_dimensions[ws.cell(1, col).column_letter].width = _WIDTHS[name]
    for row in ws.iter_rows(min_row=2):
        row[-1].alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions


def write_workbook(path: Path, runlog: RunLog) -> None:
    """Save the workbook. Writes to a temp file first so a failed save never leaves a half-written file."""
    wb = Workbook()
    _add_run_log(wb, runlog)

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        wb.save(tmp)
        os.replace(tmp, path)
    except PermissionError as exc:
        raise ToolkitError(
            f"Could not save {path.name}. If it is open in Excel, close it and run again."
        ) from exc
    finally:
        tmp.unlink(missing_ok=True)
