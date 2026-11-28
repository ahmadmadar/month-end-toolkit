"""Pair each ticket with at most one dispatch pickup. Plain Python, no API calls.

A pickup is a candidate for a ticket when the account is the same and the dates
are within matching.date_tolerance_days. Among a ticket's candidates, the best
are those whose address matches, then those with the closest date. A ticket only
ever takes one of its best candidates, so a second ticket for a pickup that's
already taken is a duplicate, not a match to some other pickup that day. It's
only a duplicate if it names the same site as that pickup (or as the ticket
using it); a ticket for another site with no free pickup is unmatched.

Tickets are assigned best-evidence first (address match, closest date, readable
before low confidence, then file name), so a clear ticket is never pushed off its
pickup by a weaker one. Between identical tickets, the first by file name wins.
File names are never used to decide what a ticket is.
"""

from dataclasses import dataclass
from datetime import date

import pandas as pd

from toolkit.address import same_address
from toolkit.config import Rules
from toolkit.validate import TicketRecord

MATCHED = "matched"
DUPLICATE = "duplicate"      # same site as a pickup already taken by another ticket
UNMATCHED = "unmatched"      # no free pickup for this account and site within the date tolerance
UNREADABLE = "unreadable"    # account or date couldn't be read, so it can't be matched


@dataclass(frozen=True)
class Pickup:
    pickup_id: str
    account_id: str
    date: date | None
    site_address: str
    status: str
    extras_recorded: str


@dataclass
class Match:
    source_file: str
    status: str
    pickup_id: str | None = None        # for a duplicate: the pickup it duplicates
    address_ok: bool | None = None
    date_diff_days: int | None = None
    duplicate_of: str | None = None     # source_file of the ticket used for that pickup


@dataclass
class MatchResult:
    matches: list[Match]                # one per ticket, in the order given
    ticket_for_pickup: dict[str, str]   # pickup_id -> source_file of the ticket used


def pickups_from(rows: pd.DataFrame) -> list[Pickup]:
    return [
        Pickup(
            pickup_id=r["pickup_id"],
            account_id=r["account_id"],
            date=r["date"],
            site_address=r["site_address"],
            status=r["status"],
            extras_recorded=r["extras_recorded"],
        )
        for r in rows.to_dict("records")
    ]


def match_tickets(records: list[TicketRecord], pickups: list[Pickup], rules: Rules) -> MatchResult:
    tolerance = rules.date_tolerance_days
    order = {r.source_file: i for i, r in enumerate(sorted(records, key=lambda r: r.source_file))}
    matches = {r.source_file: Match(r.source_file, UNMATCHED) for r in records}
    best: dict[str, list[tuple]] = {}   # source_file -> [(sort key, pickup, address_ok, date_diff)]

    for rec in records:
        ticket_date = _parse(rec.date)
        if not rec.account_id or ticket_date is None:
            matches[rec.source_file].status = UNREADABLE
            continue
        scored = []
        for i, p in enumerate(pickups):
            if p.account_id != rec.account_id or p.date is None:
                continue
            diff = abs((p.date - ticket_date).days)
            if diff > tolerance:
                continue
            ok = same_address(rec.site_address, p.site_address, rules.address_match, rules.address_words)
            key = (not ok, diff, rec.confidence == "low", order[rec.source_file], i)
            scored.append((key, p, ok, diff))
        if scored:
            top = min(s[0][:2] for s in scored)
            best[rec.source_file] = [s for s in scored if s[0][:2] == top]

    taken: dict[str, str] = {}
    assigned: set[str] = set()
    for key, p, ok, diff, name in sorted(
        (s[0], s[1], s[2], s[3], name) for name, group in best.items() for s in group
    ):
        if name in assigned or p.pickup_id in taken:
            continue
        taken[p.pickup_id] = name
        assigned.add(name)
        matches[name] = Match(name, MATCHED, p.pickup_id, ok, diff)

    # Left over: every best candidate is taken by another ticket. It's a duplicate only if it names the
    # same site as that pickup or as the ticket using it; otherwise it's a ticket with no pickup of its own.
    by_name = {r.source_file: r for r in records}
    for name, group in best.items():
        if name in assigned:
            continue
        rec = by_name[name]
        for _, p, ok, diff in group:
            holder = by_name[taken[p.pickup_id]]
            if ok or same_address(rec.site_address, holder.site_address, rules.address_match, rules.address_words):
                matches[name] = Match(name, DUPLICATE, p.pickup_id, ok, diff, duplicate_of=holder.source_file)
                break

    return MatchResult([matches[r.source_file] for r in records], taken)


def _parse(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None
