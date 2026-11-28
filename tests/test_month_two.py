"""The month-two test: both sample months produce the full workbook with no code edits.

Runs offline. extracted.json is filled from the ticket answers saved from the real
runs, and the Claude client fails the test if it's ever called.
"""

import json
import shutil
from datetime import date
from pathlib import Path

import pytest
from openpyxl import load_workbook

from toolkit.apikey import KEY_NAME
from toolkit.cache import ExtractionCache
from toolkit.config import load_rules
from toolkit.extract import Extractor
from toolkit.loaders import discover_tickets
from toolkit.paths import month_paths
from toolkit.pipeline import run
from toolkit.validate import TicketRecord

ROOT = Path(__file__).resolve().parents[1]
MONTHS = ["2026-10", "2026-11"]
TABS = ["Summary", "Fees to add", "Needs review", "Matched", "Run log"]


class NoCalls:
    """A Claude client that fails the test if the run tries to call it."""

    @property
    def messages(self):
        pytest.fail("The run called Claude; every ticket should have come from saved results.")


@pytest.fixture
def project(tmp_path, no_key) -> Path:
    if not all((ROOT / "inputs" / m).is_dir() for m in MONTHS):
        pytest.skip("sample inputs not generated; run scripts/make_sample_data.py")
    (tmp_path / "rules").mkdir()
    shutil.copy(ROOT / "rules" / "rules.yaml", tmp_path / "rules" / "rules.yaml")
    (tmp_path / ".env").write_text(f"{KEY_NAME}=fake-test-key\n")
    rules = load_rules(tmp_path / "rules" / "rules.yaml")
    for month in MONTHS:
        shutil.copytree(ROOT / "inputs" / month, tmp_path / "inputs" / month)
        paths = month_paths(month, rules, tmp_path)
        saved = {r["source_file"]: TicketRecord.from_dict(r) for r in
                 json.loads((ROOT / "tests" / "fixtures" / month / "extracted_records.json").read_text())}
        cache = ExtractionCache(paths.output_dir / "extracted.json",
                                Extractor(None, rules, paths.first_day, paths.last_day).settings)
        for t in discover_tickets(paths.tickets_dir, rules.inputs.ticket_extensions).tickets:
            cache.put(t, saved[t.name])
    return tmp_path


@pytest.mark.parametrize("month", MONTHS)
def test_month_runs_with_no_code_edits(project, month):
    result = run(month, project, client=NoCalls())
    assert result.stats.sent == 0 and result.stats.from_cache == result.tickets > 0

    wb = load_workbook(result.workbook)
    assert wb.sheetnames == TABS
    c = result.checks
    summary = {r[0]: r[1] for r in wb["Summary"].iter_rows(values_only=True) if r[0]}
    assert summary["Month"] == month
    assert summary["Fees to add"] == float(c.fees_added) > 0
    assert summary["Fees held for review"] == float(c.fees_held)
    assert summary["Match rate"].startswith(f"{c.match_rate}%")

    fee_rows = [r for r in wb["Fees to add"].iter_rows(min_row=2, values_only=True) if r[0]]
    assert len(fee_rows) == len(c.fees("add"))
    assert sum(r[8] for r in fee_rows) == pytest.approx(float(c.fees_added))
    review_rows = [r for r in wb["Needs review"].iter_rows(min_row=2, values_only=True) if r[0]]
    assert len(review_rows) == summary["Rows on Needs review"] > 0
    assert wb["Matched"].max_row - 1 == len(c.matched_clean)
    # every date in the month's tabs is in that month (nothing carried over from the other one)
    first = date.fromisoformat(f"{month}-01")
    dates = [r[4] for r in fee_rows] + [r[6] for r in review_rows]
    assert all(d is None or (d.year, d.month) == (first.year, first.month) for d in dates)


def test_both_months_in_one_project(project):
    """Same code, same rules, two months back to back: each writes its own workbook."""
    books = [run(m, project, client=NoCalls()).workbook for m in MONTHS]
    assert [b.name for b in books] == [f"reconciliation_{m}.xlsx" for m in MONTHS]
    assert all(b.exists() for b in books)
