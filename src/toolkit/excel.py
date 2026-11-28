"""Write the reconciliation workbook: Summary, Fees to add, Needs review, Matched, Run log.

Every number comes from the run (CheckResult); nothing is calculated in Excel
formulas, so totals can't silently change when someone edits a row. Customer
names and addresses appear in the client-facing tabs only, never in the Run log.
"""

import os
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.worksheet import Worksheet

from toolkit.checks import (
    ADD, FEE_CONTAMINATION, FEE_EXTRA_BIN, FLAGS, HELD, CheckResult, Issue, money,
)
from toolkit.errors import ToolkitError
from toolkit.runlog import RunLog

FLAG_LABELS = {
    "missing_ticket": "No driver ticket",
    "unmatched_ticket": "Ticket with no scheduled pickup",
    "address_mismatch": "Address differs from dispatch",
    "unbilled_extra": "Extra bins not billed",
    "unbilled_contamination": "Contamination not billed",
    "service_dispute": "Ticket says not serviced",
    "duplicate_ticket": "Duplicate ticket",
    "needs_human_read": "Ticket needs a person to read it",
}
FEE_LABELS = {FEE_EXTRA_BIN: "Extra bins", FEE_CONTAMINATION: "Contamination"}
DECISIONS = ("Bill it", "Don't bill", "Fixed in dispatch", "Ask driver")

MONEY = '"$"#,##0.00'
DATE = "yyyy-mm-dd"
_BOLD = Font(bold=True)
_TITLE = Font(bold=True, size=14)
_HEADER_FILL = PatternFill("solid", fgColor="DDDDDD")
_WARNING_FILL = PatternFill("solid", fgColor="FFF2CC")
_DECISION_FILL = PatternFill("solid", fgColor="E2EFDA")
_WRAP = Alignment(wrap_text=True, vertical="top")
_TOP = Alignment(vertical="top")


@dataclass
class WorkbookData:
    """Everything the client-facing tabs need, all from one run."""
    month: str
    client: str
    rules_version: str
    model: str
    run_at: datetime
    dispatch_rows: pd.DataFrame       # for customer names and services
    tickets: int
    checks: CheckResult
    approval_threshold: float | None


# --- shared helpers ---

def _table(ws: Worksheet, start_row: int, columns: list[tuple[str, int]], rows: list[list]) -> None:
    """Header + rows from start_row, with widths, money/date formats, wrapping, frozen header and filter."""
    for col, (name, width) in enumerate(columns, start=1):
        cell = ws.cell(start_row, col, name)
        cell.font, cell.fill = _BOLD, _HEADER_FILL
        ws.column_dimensions[cell.column_letter].width = width
    for r, values in enumerate(rows, start=start_row + 1):
        for c, value in enumerate(values, start=1):
            cell = ws.cell(r, c, float(value) if isinstance(value, Decimal) else value)
            if isinstance(value, Decimal):
                cell.number_format = MONEY
            elif isinstance(value, date):
                cell.number_format = DATE
            cell.alignment = _WRAP if isinstance(value, str) and len(value) > 40 else _TOP
    ws.freeze_panes = ws.cell(start_row + 1, 1)
    last_col = ws.cell(start_row, len(columns)).column_letter
    ws.auto_filter.ref = f"A{start_row}:{last_col}{start_row + max(len(rows), 1)}"


def _as_date(value: str | date | None) -> date | str:
    if isinstance(value, date) or value is None:
        return value or ""
    try:
        return date.fromisoformat(value)
    except ValueError:
        return value


def _lookups(rows: pd.DataFrame) -> tuple[dict[str, dict], dict[str, str]]:
    by_pickup = {r["pickup_id"]: r for r in rows.to_dict("records")}
    customer_by_account: dict[str, str] = {}
    for r in by_pickup.values():
        customer_by_account.setdefault(r["account_id"], r["customer_name"])
    return by_pickup, customer_by_account


def _sort_key(issue: Issue) -> tuple:
    return FLAGS.index(issue.flag), issue.date or "", issue.pickup_id or "", issue.source_file or ""


# --- tabs ---

def _add_summary(ws: Worksheet, data: WorkbookData, needs_review: int) -> None:
    c = data.checks
    ws.title = "Summary"
    ws["A1"] = f"Month-end reconciliation: {data.month}"
    ws["A1"].font = _TITLE
    rate = "n/a" if c.match_rate is None else f"{c.match_rate}%"
    facts = [
        ("Client", data.client),
        ("Month", data.month),
        ("Run date", data.run_at.strftime("%Y-%m-%d %H:%M")),
        ("Rules version", data.rules_version),
        ("Model used to read tickets", data.model),
        ("Pickups in dispatch", len(data.dispatch_rows)),
        ("Ticket files read", data.tickets),
        ("Match rate", f"{rate} ({c.completed_matched} of {c.completed} completed pickups have a ticket)"),
        ("Fees to add", c.fees_added),
        ("Fees held for review", c.fees_held),
        ("Rows on Needs review", needs_review),
        ("Clean pickups (Matched tab)", len(c.matched_clean)),
    ]
    for i, (label, value) in enumerate(facts, start=3):
        ws.cell(i, 1, label).font = _BOLD
        cell = ws.cell(i, 2, float(value) if isinstance(value, Decimal) else value)
        cell.alignment = Alignment(horizontal="left")
        if isinstance(value, Decimal):
            cell.number_format = MONEY
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 26
    ws.column_dimensions["C"].width = 22
    ws.column_dimensions["D"].width = 30

    row = 3 + len(facts) + 1
    ws.cell(row, 1, "Findings").font = _TITLE
    row += 1
    for col, name in enumerate(("Issue", "Count", "Fees to add", "Fees held"), start=1):
        cell = ws.cell(row, col, name)
        cell.font, cell.fill = _BOLD, _HEADER_FILL
    for flag in FLAGS:
        row += 1
        added = sum((i.amount for i in c.issues if i.flag == flag and i.fee_status == ADD), Decimal("0.00"))
        held = sum((i.amount for i in c.issues if i.flag == flag and i.fee_status == HELD), Decimal("0.00"))
        ws.cell(row, 1, FLAG_LABELS[flag])
        ws.cell(row, 2, c.flag_counts[flag])
        for col, amount in ((3, added), (4, held)):
            if amount:
                ws.cell(row, col, float(amount)).number_format = MONEY

    row += 2
    ws.cell(row, 1, "Fees to add by account").font = _TITLE
    row += 1
    threshold = data.approval_threshold
    if threshold is not None:
        ws.cell(row, 1, f"Rule: invoices over ${money(threshold):,} need manager sign-off. The tool only knows the "
                        f"fees below, not whole invoice totals, so check each invoice too.")
        ws.cell(row, 1).alignment = _WRAP
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
        ws.row_dimensions[row].height = 30
        row += 1
    for col, name in enumerate(("Account", "Customer", "Fees to add", "Sign-off"), start=1):
        cell = ws.cell(row, col, name)
        cell.font, cell.fill = _BOLD, _HEADER_FILL
    _, customers = _lookups(data.dispatch_rows)
    totals: dict[str, Decimal] = {}
    for i in c.fees(ADD):
        totals[i.account_id] = totals.get(i.account_id, Decimal("0.00")) + i.amount
    if not totals:
        ws.cell(row + 1, 1, "No fees to add this month.")
    for account in sorted(totals):
        row += 1
        ws.cell(row, 1, account)
        ws.cell(row, 2, customers.get(account, ""))
        ws.cell(row, 3, float(totals[account])).number_format = MONEY
        if threshold is not None and totals[account] > money(threshold):
            ws.cell(row, 4, "Over threshold: manager sign-off").fill = _WARNING_FILL


def _add_fees(ws: Worksheet, data: WorkbookData) -> None:
    by_pickup, _ = _lookups(data.dispatch_rows)
    fees = sorted(data.checks.fees(ADD), key=_sort_key)
    rows = [
        [i.pickup_id, i.account_id, by_pickup.get(i.pickup_id, {}).get("customer_name", ""), i.site_address,
         _as_date(i.date), FEE_LABELS.get(i.fee_type, i.fee_type), i.quantity, i.unit_price, i.amount, i.source_file]
        for i in fees
    ]
    _table(ws, 1, [("Pickup", 14), ("Account", 10), ("Customer", 24), ("Site", 28), ("Date", 12),
                   ("Fee type", 15), ("Qty", 6), ("Price", 11), ("Amount", 12), ("Source ticket", 32)], rows)
    total_row = len(rows) + 3
    if not rows:
        ws.cell(2, 1, "No fees to add this month.")
    ws.cell(total_row, 8, "Total").font = _BOLD
    total = ws.cell(total_row, 9, float(data.checks.fees_added))
    total.font, total.number_format = _BOLD, MONEY


def _add_needs_review(ws: Worksheet, data: WorkbookData, issues: list[Issue]) -> None:
    by_pickup, customers = _lookups(data.dispatch_rows)
    rows = []
    for i in issues:
        customer = by_pickup[i.pickup_id]["customer_name"] if i.pickup_id in by_pickup else customers.get(i.account_id, "")
        rows.append([
            FLAG_LABELS[i.flag], i.reason, i.pickup_id or "", i.account_id or "", customer, i.site_address or "",
            _as_date(i.date), i.source_file or "", i.amount if i.fee_status == HELD else "", "", "",
        ])
    columns = [("Issue", 26), ("Reason", 70), ("Pickup", 14), ("Account", 10), ("Customer", 24), ("Site", 26),
               ("Date", 12), ("Source ticket", 30), ("Held fee", 11), ("Decision", 18), ("Notes", 30)]
    _table(ws, 1, columns, rows)
    if not rows:
        ws.cell(2, 1, "Nothing to review this month.")
        return
    decision_col = ws.cell(1, 10).column_letter
    for r in range(2, len(rows) + 2):
        ws.cell(r, 10).fill = _DECISION_FILL
        ws.cell(r, 11).fill = _DECISION_FILL
    # A list to pick from, but anything typed is accepted.
    dv = DataValidation(type="list", formula1='"' + ",".join(DECISIONS) + '"', allow_blank=True,
                        showErrorMessage=False)
    dv.add(f"{decision_col}2:{decision_col}{len(rows) + 1}")
    ws.add_data_validation(dv)


def _add_matched(ws: Worksheet, data: WorkbookData) -> None:
    by_pickup, _ = _lookups(data.dispatch_rows)
    clean = sorted(data.checks.matched_clean, key=lambda pid: (by_pickup[pid]["date"] or date.min, pid))
    rows = [
        [pid, _as_date(by_pickup[pid]["date"]), by_pickup[pid]["account_id"], by_pickup[pid]["customer_name"],
         by_pickup[pid]["site_address"], by_pickup[pid]["service"], data.checks.ticket_for_pickup[pid]]
        for pid in clean
    ]
    _table(ws, 1, [("Pickup", 14), ("Date", 12), ("Account", 10), ("Customer", 24), ("Site", 28),
                   ("Service", 16), ("Source ticket", 32)], rows)
    if not rows:
        ws.cell(2, 1, "No clean pickups this month.")


def _add_run_log(ws: Worksheet, runlog: RunLog) -> None:
    ws.title = "Run log"
    widths = {"Level": 10, "Step": 12, "Item": 32, "Value": 28, "Note": 90}
    _table(ws, 1, [(name, widths[name]) for name in RunLog.COLUMNS], [list(r) for r in runlog.rows()])
    for r, row in enumerate(runlog.rows(), start=2):
        if row[0] == "warning":
            for cell in ws[r]:
                cell.fill = _WARNING_FILL


def needs_review_issues(checks: CheckResult) -> list[Issue]:
    """Everything a person must decide: every flag except fees added with confidence (those are on Fees to add)."""
    return sorted((i for i in checks.issues if i.fee_status != ADD), key=_sort_key)


def write_workbook(path: Path, runlog: RunLog, data: WorkbookData) -> None:
    """Save the workbook. Writes to a temp file first so a failed save never leaves a half-written file."""
    review = needs_review_issues(data.checks)
    wb = Workbook()
    _add_summary(wb.active, data, len(review))
    _add_fees(wb.create_sheet("Fees to add"), data)
    _add_needs_review(wb.create_sheet("Needs review"), data, review)
    _add_matched(wb.create_sheet("Matched"), data)
    _add_run_log(wb.create_sheet("Run log"), runlog)

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
