"""The month's checks and fee math. Plain Python, no API calls.

Takes the dispatch pickups, the ticket records and the matches, and returns one
Issue per finding. A fee is either added (goes to "Fees to add") or held (shown
in "Needs review" with its amount, never added). The tool holds a fee whenever
it isn't sure (CLAUDE.md rule 3):

- the ticket is low confidence
- the extras wording contains a word from review.hold_fee_when_extras_note_contains
- a second copy of the ticket disagrees on extras, contamination or service
- dispatch's extras_recorded has text but no number to compare with
- the ticket says the pickup was not serviced

Prices come from rules.yaml (fees.extra_bin, fees.contamination). Amounts use
Decimal so cents are exact.
"""

import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from toolkit.config import Rules
from toolkit.errors import ToolkitError
from toolkit.match import DUPLICATE, MATCHED, UNMATCHED, UNREADABLE, Match, MatchResult, Pickup
from toolkit.validate import TicketRecord

MISSING_TICKET = "missing_ticket"
UNMATCHED_TICKET = "unmatched_ticket"
ADDRESS_MISMATCH = "address_mismatch"
UNBILLED_EXTRA = "unbilled_extra"
UNBILLED_CONTAMINATION = "unbilled_contamination"
SERVICE_DISPUTE = "service_dispute"
DUPLICATE_TICKET = "duplicate_ticket"
NEEDS_HUMAN_READ = "needs_human_read"
FLAGS = (
    MISSING_TICKET, UNMATCHED_TICKET, ADDRESS_MISMATCH, UNBILLED_EXTRA,
    UNBILLED_CONTAMINATION, SERVICE_DISPUTE, DUPLICATE_TICKET, NEEDS_HUMAN_READ,
)

ADD = "add"
HELD = "held"
FEE_EXTRA_BIN = "extra_bin"
FEE_CONTAMINATION = "contamination"
CENT = Decimal("0.01")
_LEADING_NUMBER = re.compile(r"^\s*(\d+)")


@dataclass
class Issue:
    flag: str
    reason: str                       # plain English, for the Needs review tab
    pickup_id: str | None = None
    account_id: str | None = None
    date: str | None = None           # YYYY-MM-DD
    site_address: str | None = None
    source_file: str | None = None
    fee_type: str | None = None
    amount: Decimal | None = None
    fee_status: str | None = None     # ADD | HELD | None


@dataclass
class CheckResult:
    issues: list[Issue]
    matched_clean: list[str]          # pickup_ids with a matched ticket and no issue
    completed: int
    completed_matched: int
    fees_added: Decimal = Decimal("0.00")
    fees_held: Decimal = Decimal("0.00")
    flag_counts: dict[str, int] = field(default_factory=dict)

    @property
    def match_rate(self) -> Decimal | None:
        """Completed pickups with a matched ticket, as a percentage (one decimal)."""
        if not self.completed:
            return None
        return (Decimal(100 * self.completed_matched) / self.completed).quantize(Decimal("0.1"), ROUND_HALF_UP)

    def fees(self, status: str) -> list[Issue]:
        return [i for i in self.issues if i.fee_status == status]


def money(value: float | Decimal) -> Decimal:
    return Decimal(str(value)).quantize(CENT, ROUND_HALF_UP)


def recorded_extra_bins(text: str) -> int | None:
    """Extra bins already in dispatch: 0 if blank, the leading number if there is one, else None (unclear)."""
    if not text.strip():
        return 0
    found = _LEADING_NUMBER.match(text)
    return int(found.group(1)) if found else None


def _has_word(text: str | None, words: tuple[str, ...]) -> bool:
    lowered = (text or "").lower()
    return any(w in lowered for w in words)


def _completed(p: Pickup) -> bool:
    return p.status.strip().lower() == "completed"


def run_checks(
    pickups: list[Pickup], records: list[TicketRecord], matched: MatchResult, rules: Rules
) -> CheckResult:
    for fee in (FEE_EXTRA_BIN, FEE_CONTAMINATION):
        if fee not in rules.fees:
            raise ToolkitError(f"{rules.source_path.name}: 'fees.{fee}' is missing.")
    bin_fee = money(rules.fees[FEE_EXTRA_BIN])
    contamination_fee = money(rules.fees[FEE_CONTAMINATION])

    pickup_by_id = {p.pickup_id: p for p in pickups}
    record_by_name = {r.source_file: r for r in records}
    issues: list[Issue] = []

    def issue(flag: str, reason: str, rec: TicketRecord | None = None, p: Pickup | None = None, **fee) -> None:
        issues.append(Issue(
            flag=flag,
            reason=reason,
            pickup_id=p.pickup_id if p else None,
            account_id=p.account_id if p else (rec.account_id if rec else None),
            date=p.date.isoformat() if p and p.date else (rec.date if rec else None),
            site_address=p.site_address if p else (rec.site_address if rec else None),
            source_file=rec.source_file if rec else None,
            **fee,
        ))

    # Copies that disagree with the ticket used for their pickup: that pickup's fees are held.
    copy_differs: dict[str, str] = {}       # source_file of a copy -> fields it differs on
    disputed_by_copy: dict[str, str] = {}   # pickup_id -> why its fees are held
    for m in matched.matches:
        if m.status == DUPLICATE:
            diff = _differences(record_by_name[m.source_file], record_by_name[m.duplicate_of])
            if diff:
                copy_differs[m.source_file] = diff
                disputed_by_copy[m.pickup_id] = f"another copy of the ticket ({m.source_file}) differs on {diff}"

    unreadable = sum(m.status == UNREADABLE for m in matched.matches)

    for m in matched.matches:
        rec = record_by_name[m.source_file]
        low = rec.confidence == "low"
        if m.status == UNREADABLE:
            issue(NEEDS_HUMAN_READ, _read_reason(rec, "It can't be matched to a pickup until a person reads it."), rec)
            continue
        if m.status == UNMATCHED:
            issue(UNMATCHED_TICKET,
                  f"No scheduled pickup for account {rec.account_id} at this site within "
                  f"{rules.date_tolerance_days} day(s) of {rec.date}. Check whether the work was scheduled.", rec)
            if low:
                issue(NEEDS_HUMAN_READ, _read_reason(rec), rec)
            continue
        p = pickup_by_id[m.pickup_id]
        if m.status == DUPLICATE:
            reason = f"Second ticket for pickup {p.pickup_id} (the first is {m.duplicate_of}). No fees are taken from it."
            if m.source_file in copy_differs:
                reason += f" It differs from the first on {copy_differs[m.source_file]}, so this pickup's fees are held."
            issue(DUPLICATE_TICKET, reason, rec, p)
            continue

        assert m.status == MATCHED
        if low and rules.low_confidence_to_review:
            issue(NEEDS_HUMAN_READ, _read_reason(rec, "Any fee from this ticket is held until it's checked."), rec, p)
        if m.address_ok is False:
            issue(ADDRESS_MISMATCH,
                  f"Ticket address '{rec.site_address or '(none)'}' differs from the dispatch site "
                  f"'{p.site_address}'.", rec, p)
        not_serviced = rec.serviced is False
        if not_serviced and _completed(p):
            issue(SERVICE_DISPUTE, "Dispatch says completed, but the ticket says the pickup was not serviced.", rec, p)

        holds = []
        if low:
            holds.append("the ticket is low confidence")
        if not_serviced:
            holds.append("the ticket also says the pickup was not serviced")
        if m.pickup_id in disputed_by_copy:
            holds.append(disputed_by_copy[m.pickup_id])

        # Extra bins
        bins = rec.extra_bins or 0
        recorded = recorded_extra_bins(p.extras_recorded)
        extra_holds = list(holds)
        if _has_word(rec.extras_note, rules.hold_fee_words):
            extra_holds.append(f"the ticket says '{rec.extras_note}', which may not be bins")
        if recorded is None and bins:
            extra_holds.append(f"dispatch extras_recorded '{p.extras_recorded}' has no number to compare with")
            unbilled = bins
        else:
            unbilled = bins - (recorded or 0)
        if unbilled > 0:
            amount = bin_fee * unbilled
            reason = (f"Ticket shows {bins} extra bin(s); dispatch recorded "
                      f"{'an unclear amount' if recorded is None else recorded}. "
                      f"{unbilled} × ${bin_fee} = ${amount}.")
            issue(UNBILLED_EXTRA, _with_holds(reason, extra_holds), rec, p,
                  fee_type=FEE_EXTRA_BIN, amount=amount, fee_status=HELD if extra_holds else ADD)

        # Contamination
        if rec.contamination and not _has_word(p.extras_recorded, rules.contamination_recorded_words):
            what = f": '{rec.contamination_note}'" if rec.contamination_note else ""
            reason = f"Ticket notes contamination{what}. Dispatch has no contamination charge. Flat fee ${contamination_fee}."
            issue(UNBILLED_CONTAMINATION, _with_holds(reason, holds), rec, p,
                  fee_type=FEE_CONTAMINATION, amount=contamination_fee, fee_status=HELD if holds else ADD)

    for p in pickups:
        if _completed(p) and p.pickup_id not in matched.ticket_for_pickup:
            reason = "Dispatch shows this pickup as completed, but no driver ticket was found."
            if unreadable == 1:
                reason += " One ticket this month couldn't be read and may belong to this pickup."
            elif unreadable:
                reason += f" {unreadable} tickets this month couldn't be read; one of them may belong to this pickup."
            issue(MISSING_TICKET, reason, p=p)

    with_issue = {i.pickup_id for i in issues if i.pickup_id}
    completed = [p for p in pickups if _completed(p)]
    return CheckResult(
        issues=issues,
        matched_clean=[pid for pid in matched.ticket_for_pickup if pid not in with_issue],
        completed=len(completed),
        completed_matched=sum(p.pickup_id in matched.ticket_for_pickup for p in completed),
        fees_added=sum((i.amount for i in issues if i.fee_status == ADD), Decimal("0.00")),
        fees_held=sum((i.amount for i in issues if i.fee_status == HELD), Decimal("0.00")),
        flag_counts={flag: sum(i.flag == flag for i in issues) for flag in FLAGS},
    )


def _differences(a: TicketRecord, b: TicketRecord) -> str:
    names = {"extra_bins": "extra bins", "contamination": "contamination", "serviced": "whether it was serviced"}
    return ", ".join(label for f, label in names.items() if getattr(a, f) != getattr(b, f))


def _read_reason(rec: TicketRecord, then: str = "") -> str:
    problems = " ".join(rec.problems) if rec.problems else "Claude marked it low confidence."
    return f"Ticket needs a person to read it: {problems} {then}".strip()


def _with_holds(reason: str, holds: list[str]) -> str:
    if not holds:
        return reason
    return f"{reason} Fee held for review: {'; '.join(holds)}."
