"""The checks and fee math. No API calls.

Small made-up cases first, then each sample month compared with its answer key
(tests/fixtures/YYYY-MM/expected_issues.json), using the ticket answers saved
from the real runs (tests/fixtures/YYYY-MM/extracted_records.json).
"""

import json
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from toolkit.checks import (
    ADD, HELD, run_checks, recorded_extra_bins,
    ADDRESS_MISMATCH, DUPLICATE_TICKET, MISSING_TICKET, NEEDS_HUMAN_READ, SERVICE_DISPUTE,
    UNBILLED_CONTAMINATION, UNBILLED_EXTRA, UNMATCHED_TICKET,
)
from toolkit.config import load_rules
from toolkit.errors import ToolkitError
from toolkit.loaders import load_dispatch
from toolkit.match import Pickup, match_tickets, pickups_from
from toolkit.paths import month_paths
from toolkit.validate import TicketRecord

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def rules():
    return load_rules(ROOT / "rules" / "rules.yaml")   # extra_bin 40.00, contamination 175.00


def pickup(pid="P1", day=5, extras="", status="completed", address="1 Test St", account="1043"):
    return Pickup(pid, account, date(2026, 11, day), address, status, extras)


def ticket(name="t1.txt", day=5, **fields):
    base = dict(account_id="1043", date=f"2026-11-{day:02d}", site_address="1 Test St", extra_bins=0,
                contamination=False, serviced=True, confidence="high")
    return TicketRecord(source_file=name, **{**base, **fields})


def check(rules, pickups, records):
    return run_checks(pickups, records, match_tickets(records, pickups, rules), rules)


def flags(result):
    return sorted(i.flag for i in result.issues)


def only(result, flag):
    found = [i for i in result.issues if i.flag == flag]
    assert len(found) == 1, result.issues
    return found[0]


def test_clean_pickup(rules):
    r = check(rules, [pickup()], [ticket()])
    assert r.issues == [] and r.matched_clean == ["P1"]
    assert (r.match_rate, r.fees_added, r.fees_held) == (Decimal("100.0"), 0, 0)


def test_unbilled_extra_added_with_exact_cents(rules):
    r = check(rules, [pickup()], [ticket(extra_bins=3, extras_note="3 extra bin(s) on side")])
    i = only(r, UNBILLED_EXTRA)
    assert (i.fee_status, i.amount, i.fee_type) == (ADD, Decimal("120.00"), "extra_bin")
    assert "3 × $40.00 = $120.00" in i.reason
    assert r.fees_added == Decimal("120.00") and r.matched_clean == []


def test_extras_already_recorded_add_only_the_difference(rules):
    assert check(rules, [pickup(extras="2 extra bin")], [ticket(extra_bins=2)]).issues == []
    i = only(check(rules, [pickup(extras="1 extra bin")], [ticket(extra_bins=3)]), UNBILLED_EXTRA)
    assert i.amount == Decimal("80.00") and "recorded 1" in i.reason


def test_bags_wording_holds_the_fee(rules):
    i = only(check(rules, [pickup()], [ticket(extra_bins=2, extras_note="extras: 2 bags/bins")]), UNBILLED_EXTRA)
    assert (i.fee_status, i.amount) == (HELD, Decimal("80.00")) and "may not be bins" in i.reason


def test_bags_wording_already_recorded_adds_nothing(rules):
    r = check(rules, [pickup(extras="2 extra bin")], [ticket(extra_bins=2, extras_note="extras: 2 bags/bins")])
    assert r.issues == []


def test_unparseable_extras_recorded_holds_the_fee(rules):
    i = only(check(rules, [pickup(extras="see note")], [ticket(extra_bins=1)]), UNBILLED_EXTRA)
    assert i.fee_status == HELD and "no number" in i.reason


def test_contamination_added_unless_dispatch_mentions_it(rules):
    i = only(check(rules, [pickup()], [ticket(contamination=True, contamination_note="paint cans")]),
             UNBILLED_CONTAMINATION)
    assert (i.fee_status, i.amount) == (ADD, Decimal("175.00")) and "'paint cans'" in i.reason
    assert check(rules, [pickup(extras="Contam charged")], [ticket(contamination=True)]).issues == []


def test_medium_confidence_fees_are_added(rules):
    i = only(check(rules, [pickup()], [ticket(confidence="medium", extra_bins=1)]), UNBILLED_EXTRA)
    assert i.fee_status == ADD


def test_low_confidence_matched_ticket_holds_fees_and_needs_read(rules):
    r = check(rules, [pickup()], [ticket(confidence="low", contamination=True, problems=["Site address unclear."])])
    assert flags(r) == [NEEDS_HUMAN_READ, UNBILLED_CONTAMINATION]
    assert only(r, UNBILLED_CONTAMINATION).fee_status == HELD
    assert "Site address unclear." in only(r, NEEDS_HUMAN_READ).reason
    assert r.completed_matched == 1   # matched, so the pickup isn't missing a ticket


def test_low_confidence_setting_off_still_holds_fees(rules):
    r = check(replace(rules, low_confidence_to_review=False), [pickup()], [ticket(confidence="low", extra_bins=1)])
    assert flags(r) == [UNBILLED_EXTRA] and r.issues[0].fee_status == HELD


def test_not_serviced_is_a_dispute_and_holds_fees(rules):
    r = check(rules, [pickup()], [ticket(serviced=False, extra_bins=1)])
    assert flags(r) == [SERVICE_DISPUTE, UNBILLED_EXTRA]
    assert only(r, UNBILLED_EXTRA).fee_status == HELD


def test_not_serviced_on_pickup_not_marked_completed_is_no_dispute(rules):
    assert check(rules, [pickup(status="cancelled")], [ticket(serviced=False)]).issues == []


def test_address_mismatch(rules):
    i = only(check(rules, [pickup(address="48 Lakeview Ave")], [ticket(site_address="92 Pine St")]), ADDRESS_MISMATCH)
    assert "'92 Pine St'" in i.reason and "'48 Lakeview Ave'" in i.reason


def test_missing_and_unmatched(rules):
    r = check(rules, [pickup("P1", 5)], [ticket(day=20)])
    assert flags(r) == [MISSING_TICKET, UNMATCHED_TICKET]
    assert r.match_rate == Decimal("0.0")


def test_unreadable_ticket_flags_only_needs_read_and_is_mentioned_on_missing(rules):
    r = check(rules, [pickup()], [ticket(account_id=None, date=None, confidence="low")])
    assert flags(r) == [MISSING_TICKET, NEEDS_HUMAN_READ]
    assert "couldn't be read and may belong" in only(r, MISSING_TICKET).reason


def test_duplicate_takes_no_fees(rules):
    r = check(rules, [pickup()], [ticket("a.txt", extra_bins=1), ticket("b.txt", extra_bins=1)])
    assert flags(r) == [DUPLICATE_TICKET, UNBILLED_EXTRA]
    assert only(r, DUPLICATE_TICKET).source_file == "b.txt"
    assert r.fees_added == Decimal("40.00")


def test_disagreeing_duplicate_holds_the_pickup_fees(rules):
    r = check(rules, [pickup()], [ticket("a.txt", extra_bins=1), ticket("b.txt", extra_bins=3)])
    assert only(r, UNBILLED_EXTRA).fee_status == HELD
    assert "differs from the first on extra bins" in only(r, DUPLICATE_TICKET).reason
    assert r.fees_added == 0 and r.fees_held == Decimal("40.00")


def test_flag_counts_cover_every_flag(rules):
    r = check(rules, [pickup()], [ticket()])
    assert len(r.flag_counts) == 8 and sum(r.flag_counts.values()) == 0


def test_missing_fee_setting_stops_the_run(rules):
    with pytest.raises(ToolkitError, match="fees.contamination"):
        check(replace(rules, fees={"extra_bin": 40.0}), [pickup()], [ticket()])


@pytest.mark.parametrize("text, n", [("", 0), ("  ", 0), ("1 extra bin", 1), ("2 extra bin", 2), ("12 bins", 12),
                                     ("extra bin x2", None), ("see note", None)])
def test_recorded_extra_bins(text, n):
    assert recorded_extra_bins(text) == n


# --- sample months vs. answer key ---

@pytest.mark.parametrize("month", ["2026-10", "2026-11"])
def test_sample_month_matches_answer_key(rules, month):
    paths = month_paths(month, rules, ROOT)
    if not paths.dispatch_file.exists():
        pytest.skip(f"inputs/{month} not generated; run scripts/make_sample_data.py")
    fixtures = ROOT / "tests" / "fixtures" / month
    key = json.loads((fixtures / "expected_issues.json").read_text())
    records = [TicketRecord.from_dict(r) for r in json.loads((fixtures / "extracted_records.json").read_text())]
    pickups = pickups_from(load_dispatch(paths.dispatch_file, paths.first_day, paths.last_day).rows)
    result = check(rules, pickups, records)

    def ident(flag, pickup_id, account_id, day):
        return flag, pickup_id or ("ticket", account_id, day)

    expected = {ident(e["flag"], e["pickup_id"], e["account_id"], e["date"]) for e in key}
    found = [ident(i.flag, i.pickup_id, i.account_id, i.date) for i in result.issues]

    # Decision 3: a ticket too damaged to read isn't guessed onto a pickup. It's flagged on its own,
    # and the pickup it belongs to shows as missing a ticket (with a note saying so).
    unreadable = [i for i in result.issues if i.flag == NEEDS_HUMAN_READ and i.pickup_id is None and not i.account_id]
    for e in [e for e in key if e["flag"] == NEEDS_HUMAN_READ and e["pickup_id"]][: len(unreadable)]:
        expected.remove(ident(NEEDS_HUMAN_READ, e["pickup_id"], e["account_id"], e["date"]))
        expected |= {ident(NEEDS_HUMAN_READ, None, None, None), ident(MISSING_TICKET, e["pickup_id"], None, None)}

    assert len(found) == len(set(found)), "a flag was raised twice for the same pickup or ticket"
    assert set(found) == expected   # every planted issue found, and nothing else flagged

    by_pickup = {(i.flag, i.pickup_id): i for i in result.issues}
    for e in key:
        if e["flag"] == UNBILLED_EXTRA:
            assert by_pickup[(UNBILLED_EXTRA, e["pickup_id"])].amount == Decimal("40.00") * e["extra_bins"]
        if e["flag"] == UNBILLED_CONTAMINATION:
            i = by_pickup[(UNBILLED_CONTAMINATION, e["pickup_id"])]
            assert i.amount == Decimal("175.00") and e["note"] in i.reason
        if e["flag"] == ADDRESS_MISMATCH:
            assert e["ticket_address"] in by_pickup[(ADDRESS_MISMATCH, e["pickup_id"])].reason
    # zero fees that aren't on a ticket
    assert all(i.source_file for i in result.issues if i.amount is not None)
