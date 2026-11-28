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
from toolkit.excel import needs_review_issues  # noqa: E402
from toolkit.pipeline import run  # noqa: E402


def show_progress(done: int, total: int) -> None:
    """Counts only: ticket text never goes to the screen (rule 6)."""
    print(f"\rReading tickets: {done}/{total}", end="\n" if done == total else "", flush=True)


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
        result = run(args.month, ROOT, force=args.force, progress=show_progress)
    except ToolkitError as exc:
        print(f"\nStopped: {exc}", file=sys.stderr)
        return 1

    warnings = len(result.runlog.warnings)
    s = result.stats
    low = sum(r.confidence == "low" for r in result.records)
    print(f"Month {args.month}: {result.dispatch_rows} pickups, {result.tickets} ticket files, {warnings} warning(s).")
    print(f"Tickets: {s.from_cache} from saved results, {s.sent} sent to Claude, {s.failed} failed, {low} low confidence.")
    c = result.checks
    flagged = sum(c.flag_counts.values())
    print(f"Checks: {flagged} flag(s), ${c.fees_added:.2f} in fees to add, ${c.fees_held:.2f} held for review, "
          f"match rate {'n/a' if c.match_rate is None else f'{c.match_rate}%'}.")
    print(f"Needs review: {len(needs_review_issues(c))} row(s) to decide before invoices go out.")
    print(f"Wrote {result.workbook.relative_to(ROOT)}")
    if warnings:
        print("See the Run log tab for the warnings.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
