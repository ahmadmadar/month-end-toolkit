"""Run the month-end reconciliation for one month.

    python run.py --month 2026-11

Reads inputs/<month>/, writes outputs/<month>/reconciliation_<month>.xlsx.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from toolkit.errors import ToolkitError  # noqa: E402
from toolkit.pipeline import run  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the month-end reconciliation for one month.")
    parser.add_argument("--month", required=True, help="month to run, as YYYY-MM (e.g. 2026-11)")
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite this month's existing Excel file (decisions typed into it are lost)",
    )
    args = parser.parse_args(argv)

    try:
        result = run(args.month, ROOT, force=args.force)
    except ToolkitError as exc:
        print(f"Stopped: {exc}", file=sys.stderr)
        return 1

    warnings = len(result.runlog.warnings)
    print(f"Month {args.month}: {result.dispatch_rows} pickups, {result.tickets} ticket files, {warnings} warning(s).")
    print(f"Wrote {result.workbook.relative_to(ROOT)}")
    if warnings:
        print("See the Run log tab for the warnings.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
