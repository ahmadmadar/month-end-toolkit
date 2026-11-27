"""Check what Claude extracted from one ticket. Plain Python, no API calls.

Every field is checked. A field that fails is emptied (never guessed), the
reason is added to `problems` in plain English, and the record's confidence is
forced to low so a person reads the ticket. Nothing here raises.
"""

import re
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any

CONFIDENCE_LEVELS = ("high", "medium", "low")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class TicketRecord:
    source_file: str                 # set by code, never by Claude
    account_id: str | None = None
    date: str | None = None          # YYYY-MM-DD
    date_raw: str | None = None      # the date as written on the ticket
    site_address: str | None = None
    extra_bins: int | None = None
    extras_note: str | None = None   # the extras wording as written, e.g. "2 bags/bins"
    contamination: bool | None = None
    contamination_note: str = ""
    serviced: bool | None = None
    confidence: str = "low"
    problems: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TicketRecord":
        return cls(**{k: data.get(k) for k in cls.__dataclass_fields__ if k in data})


def unreadable(source_file: str, reason: str) -> TicketRecord:
    """A record for a ticket that couldn't be read at all (empty file, API failure, refusal)."""
    return TicketRecord(source_file=source_file, confidence="low", problems=[reason])


def _optional_text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def validate_extraction(
    raw: Any, source_file: str, first_day: date, last_day: date, tolerance_days: int
) -> TicketRecord:
    """Turn Claude's raw answer into a checked TicketRecord."""
    if not isinstance(raw, dict):
        return unreadable(source_file, "Claude's answer was not a set of ticket fields.")

    rec = TicketRecord(source_file=source_file)
    problems = rec.problems

    # account_id: digits only, kept as text
    account = raw.get("account_id")
    if isinstance(account, int) and not isinstance(account, bool):
        account = str(account)
    if isinstance(account, str) and account.strip().isdigit():
        rec.account_id = account.strip()
    elif account in (None, ""):
        problems.append("No account number could be read.")
    else:
        problems.append("Account number is not all digits (possibly unreadable).")

    # date: real YYYY-MM-DD date; outside the month (plus tolerance) is suspicious
    rec.date_raw = _optional_text(raw.get("date_raw"))
    value = raw.get("date")
    if value in (None, ""):
        problems.append("Date is missing, unreadable or ambiguous.")
    elif not isinstance(value, str) or not _ISO_DATE.match(value):
        problems.append("Date was not given as YYYY-MM-DD.")
    else:
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            problems.append(f"Date {value} is not a real calendar date.")
        else:
            rec.date = value
            window = timedelta(days=tolerance_days)
            if not first_day - window <= parsed <= last_day + window:
                problems.append(f"Date {value} is outside {first_day:%Y-%m}.")

    # site_address
    rec.site_address = _optional_text(raw.get("site_address"))
    if rec.site_address is None:
        problems.append("No site address could be read.")

    # extra_bins: whole number, 0 or more
    bins = raw.get("extra_bins")
    rec.extras_note = _optional_text(raw.get("extras_note"))
    if isinstance(bins, int) and not isinstance(bins, bool) and bins >= 0:
        rec.extra_bins = bins
    elif bins is None:
        problems.append("Number of extra bins is unclear.")
    else:
        problems.append("Number of extra bins is not a whole number of 0 or more.")

    # contamination
    contamination = raw.get("contamination")
    if isinstance(contamination, bool):
        rec.contamination = contamination
    else:
        problems.append("Unclear whether the load was contaminated.")
    rec.contamination_note = _optional_text(raw.get("contamination_note")) or ""

    # serviced
    serviced = raw.get("serviced")
    if isinstance(serviced, bool):
        rec.serviced = serviced
    else:
        problems.append("Unclear whether the pickup was serviced.")

    # confidence: Claude's own rating, forced to low if anything failed above
    claimed = raw.get("confidence")
    if claimed not in CONFIDENCE_LEVELS:
        problems.append("Claude did not give a valid confidence rating.")
        claimed = "low"
    rec.confidence = "low" if problems else claimed
    return rec
