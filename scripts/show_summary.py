"""Print a month's Summary tab, read-only. Used by the month-end Skill to explain results.

    python scripts/show_summary.py --month 2026-11

Reads outputs/<month>/reconciliation_<month>.xlsx and prints the Summary tab
(counts, totals, findings, fees by account) plus the Needs review row count per
issue. Never prints ticket text, site addresses or reasons.
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from openpyxl import load_workbook  # noqa: E402

from toolkit.config import load_rules  # noqa: E402
from toolkit.errors import ToolkitError  # noqa: E402
from toolkit.excel import MONEY  # noqa: E402
from toolkit.paths import month_paths  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print a month's Summary tab.")
    parser.add_argument("--month", required=True, help="YYYY-MM")
    args = parser.parse_args(argv)
    try:
        paths = month_paths(args.month, load_rules(ROOT / "rules" / "rules.yaml"), ROOT)
    except ToolkitError as exc:
        print(f"Stopped: {exc}", file=sys.stderr)
        return 1
    if not paths.workbook.exists():
        print(f"No results for {args.month} yet: {paths.workbook.relative_to(ROOT)} doesn't exist.", file=sys.stderr)
        return 1

    wb = load_workbook(paths.workbook, read_only=True)
    for row in wb["Summary"].iter_rows():
        cells = [c for c in row if c.value is not None]
        if not cells:
            print()
            continue
        print(" | ".join(f"${c.value:,.2f}" if c.number_format == MONEY else str(c.value) for c in cells))

    review = Counter(r[0] for r in wb["Needs review"].iter_rows(min_row=2, values_only=True)
                     if r[0] and r[0] != "Nothing to review this month.")
    print("\nNeeds review rows by issue")
    for issue, n in review.items():
        print(f"{issue} | {n}")
    if not review:
        print("None")
    return 0


if __name__ == "__main__":
    sys.exit(main())
