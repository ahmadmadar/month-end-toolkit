"""Month parsing and the input/output paths for one run.

File and folder names come from rules.yaml, never from code.
"""

import calendar
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from toolkit.config import Rules
from toolkit.errors import ToolkitError

_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


@dataclass(frozen=True)
class MonthPaths:
    month: str            # "YYYY-MM"
    first_day: date
    last_day: date
    input_dir: Path
    dispatch_file: Path
    tickets_dir: Path
    output_dir: Path
    workbook: Path


def parse_month(month: str) -> tuple[date, date]:
    """Return (first_day, last_day) for a 'YYYY-MM' string. Raise ToolkitError if it isn't one."""
    match = _MONTH_RE.match(month or "")
    if not match:
        raise ToolkitError(f"Month must look like 2026-11 (YYYY-MM), got {month!r}.")
    year, mon = int(match.group(1)), int(match.group(2))
    if not 1 <= mon <= 12:
        raise ToolkitError(f"Month must be between 01 and 12, got {month!r}.")
    return date(year, mon, 1), date(year, mon, calendar.monthrange(year, mon)[1])


def month_paths(month: str, rules: Rules, root: Path) -> MonthPaths:
    """Build every path for the run. Does not check that anything exists."""
    first_day, last_day = parse_month(month)
    input_dir = root / "inputs" / month
    output_dir = root / "outputs" / month
    return MonthPaths(
        month=month,
        first_day=first_day,
        last_day=last_day,
        input_dir=input_dir,
        dispatch_file=input_dir / rules.inputs.dispatch_file,
        tickets_dir=input_dir / rules.inputs.tickets_folder,
        output_dir=output_dir,
        workbook=output_dir / f"reconciliation_{month}.xlsx",
    )


def check_inputs_exist(paths: MonthPaths) -> None:
    """Raise ToolkitError naming the first missing input."""
    if not paths.input_dir.is_dir():
        raise ToolkitError(f"No input folder for {paths.month}. Expected: {paths.input_dir}")
    if not paths.dispatch_file.is_file():
        raise ToolkitError(f"Dispatch file not found: {paths.dispatch_file}")
    if not paths.tickets_dir.is_dir():
        raise ToolkitError(f"Tickets folder not found: {paths.tickets_dir}")
