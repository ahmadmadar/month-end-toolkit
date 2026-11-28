"""The five workbook tabs, written from a small made-up month. No API calls."""

from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import load_workbook

from toolkit.checks import run_checks
from toolkit.config import load_rules
from toolkit.excel import DECISIONS, WorkbookData, write_workbook
from toolkit.loaders import DISPATCH_COLUMNS
from toolkit.match import match_tickets, pickups_from
from toolkit.runlog import RunLog
from toolkit.validate import TicketRecord

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def rules():
    return load_rules(ROOT / "rules" / "rules.yaml")


def dispatch(*rows):
    df = pd.DataFrame([dict(zip(DISPATCH_COLUMNS, r)) for r in rows], columns=list(DISPATCH_COLUMNS))
    df["date"] = [date.fromisoformat(d) for d in df["date"]]
    return df


ROWS = dispatch(
    # pickup_id, date, account, customer, site_id, address, service, status, extras_recorded
    ("P1", "2026-11-03", "1043", "Test Co", "1043-1", "1 Test St", "4yd bin", "completed", ""),
    ("P2", "2026-11-04", "1043", "Test Co", "1043-1", "1 Test St", "4yd bin", "completed", ""),
    ("P3", "2026-11-05", "1077", "Other Co", "1077-1", "9 Side Rd", "8yd bin", "completed", ""),
    ("P4", "2026-11-06", "1077", "Other Co", "1077-1", "9 Side Rd", "8yd bin", "completed", ""),
)


def ticket(name, day, account="1043", address="1 Test St", **fields):
    base = dict(extra_bins=0, contamination=False, serviced=True, confidence="high")
    return TicketRecord(source_file=name, account_id=account, date=f"2026-11-{day:02d}", site_address=address,
                        **{**base, **fields})


RECORDS = [
    ticket("a.txt", 3, extra_bins=3, extras_note="3 extra bin(s)"),                  # fee added $120
    ticket("b.txt", 4, extra_bins=2, extras_note="extras: 2 bags/bins"),             # fee held $80
    ticket("c.txt", 5, account="1077", address="9 Side Rd"),                          # clean
]                                                                                     # P4: no ticket


def build(tmp_path, rules, records=RECORDS, rows=ROWS, threshold=5000.0):
    pickups = pickups_from(rows)
    checks = run_checks(pickups, records, match_tickets(records, pickups, rules), rules)
    log = RunLog(datetime(2026, 12, 1, 9, 30))
    log.info("start", "month", "2026-11")
    log.warn("tickets", "something to note")
    path = tmp_path / "out.xlsx"
    write_workbook(path, log, WorkbookData("2026-11", "Test Client", "1", "some-model", log.started_at,
                                           rows, len(records), checks, threshold))
    return load_workbook(path)


def values(ws, min_row=2):
    return [list(r) for r in ws.iter_rows(min_row=min_row, values_only=True)]


def summary(wb):
    return {r[0]: r[1] for r in wb["Summary"].iter_rows(values_only=True) if r[0]}


def test_tab_order(tmp_path, rules):
    assert build(tmp_path, rules).sheetnames == ["Summary", "Fees to add", "Needs review", "Matched", "Run log"]


def test_summary_numbers(tmp_path, rules):
    s = summary(build(tmp_path, rules))
    assert s["Client"] == "Test Client" and s["Month"] == "2026-11" and s["Rules version"] == "1"
    assert s["Run date"] == "2026-12-01 09:30"
    assert s["Fees to add"] == 120.0 and s["Fees held for review"] == 80.0
    assert s["Rows on Needs review"] == 2          # held fee + missing ticket; the added fee isn't here
    assert s["Match rate"].startswith("75.0% (3 of 4")
    assert s["Extra bins not billed"] == 2 and s["No driver ticket"] == 1 and s["Duplicate ticket"] == 0


def test_summary_marks_account_over_threshold(tmp_path, rules):
    ws = build(tmp_path, rules, threshold=100.0)["Summary"]
    rows = [r for r in ws.iter_rows(values_only=True) if r[0] == "1043"]
    assert rows == [("1043", "Test Co", 120.0, "Over threshold: manager sign-off")]
    ws = build(tmp_path, rules)["Summary"]
    assert [r[3] for r in ws.iter_rows(values_only=True) if r[0] == "1043"] == [None]


def test_fees_to_add_has_only_confident_fees_and_total(tmp_path, rules):
    ws = build(tmp_path, rules)["Fees to add"]
    header, *rows = values(ws, 1)
    assert header == ["Pickup", "Account", "Customer", "Site", "Date", "Fee type", "Qty", "Price", "Amount", "Source ticket"]
    assert rows[0][:4] == ["P1", "1043", "Test Co", "1 Test St"]
    assert rows[0][4].date() == date(2026, 11, 3)
    assert rows[0][5:] == ["Extra bins", 3, 40.0, 120.0, "a.txt"]
    assert ws.cell(2, 9).number_format == '"$"#,##0.00'
    assert [r[7:9] for r in rows if r[7] == "Total"] == [["Total", 120.0]]


def test_needs_review_rows_decision_list_and_order(tmp_path, rules):
    ws = build(tmp_path, rules)["Needs review"]
    header, *rows = values(ws, 1)
    assert header[-3:] == ["Held fee", "Decision", "Notes"]
    # spec order: missing_ticket before unbilled_extra
    assert [r[0] for r in rows] == ["No driver ticket", "Extra bins not billed"]
    missing, held = rows
    assert (missing[2], missing[4], missing[8]) == ("P4", "Other Co", None)
    assert held[8] == 80.0 and "may not be bins" in held[1]
    assert all(r[9] is None and r[10] is None for r in rows)    # Decision and Notes left blank
    dv = ws.data_validations.dataValidation[0]
    assert dv.formula1 == '"' + ",".join(DECISIONS) + '"' and dv.showErrorMessage is False
    assert str(dv.sqref) == "J2:J3"


def test_matched_has_clean_pickups_only(tmp_path, rules):
    rows = values(build(tmp_path, rules)["Matched"])
    assert [r[0] for r in rows] == ["P3"] and rows[0][-1] == "c.txt" and rows[0][5] == "8yd bin"


def test_run_log_tab_keeps_warning_highlight(tmp_path, rules):
    ws = build(tmp_path, rules)["Run log"]
    assert ws.cell(3, 1).value == "warning" and ws.cell(3, 1).fill.fgColor.rgb.endswith("FFF2CC")


def test_empty_month_says_so(tmp_path, rules):
    wb = build(tmp_path, rules, records=[ticket("c.txt", 5, account="1077", address="9 Side Rd")],
               rows=ROWS.iloc[2:3].reset_index(drop=True))
    assert wb["Fees to add"].cell(2, 1).value == "No fees to add this month."
    assert wb["Needs review"].cell(2, 1).value == "Nothing to review this month."
    assert summary(wb)["Fees to add"] == 0.0
