"""Ticket-to-pickup matching on small made-up cases. No API calls."""

from datetime import date
from pathlib import Path

import pytest

from toolkit.config import load_rules
from toolkit.match import DUPLICATE, MATCHED, UNMATCHED, UNREADABLE, Pickup, match_tickets
from toolkit.validate import TicketRecord

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def rules():
    return load_rules(ROOT / "rules" / "rules.yaml")   # date_tolerance_days: 1


def pickup(pid, day, address="1 Test St", account="1043"):
    return Pickup(pid, account, date(2026, 11, day), address, "completed", "")


def ticket(name, day, address="1 Test St", account="1043", confidence="high"):
    return TicketRecord(source_file=name, account_id=account, date=f"2026-11-{day:02d}",
                        site_address=address, confidence=confidence)


def by_name(result):
    return {m.source_file: m for m in result.matches}


def test_simple_match_and_tolerance(rules):
    result = match_tickets(
        [ticket("a.txt", 3), ticket("b.txt", 11), ticket("c.txt", 20)],
        [pickup("P1", 3), pickup("P2", 10), pickup("P3", 22)],
        rules,
    )
    m = by_name(result)
    assert (m["a.txt"].status, m["a.txt"].pickup_id, m["a.txt"].date_diff_days) == (MATCHED, "P1", 0)
    assert (m["b.txt"].status, m["b.txt"].pickup_id, m["b.txt"].date_diff_days) == (MATCHED, "P2", 1)
    assert m["c.txt"].status == UNMATCHED          # 2 days off, tolerance is 1
    assert result.ticket_for_pickup == {"P1": "a.txt", "P2": "b.txt"}


def test_account_must_match(rules):
    m = by_name(match_tickets([ticket("a.txt", 3, account="1102")], [pickup("P1", 3)], rules))
    assert m["a.txt"].status == UNMATCHED


def test_address_picks_between_two_sites_same_day(rules):
    pickups = [pickup("P1", 5, "1 Copperline Way"), pickup("P2", 5, "1 Copperline Way Loading Dock")]
    m = by_name(match_tickets(
        [ticket("a.txt", 5, "1 copperline way loading dock"), ticket("b.txt", 5, "1 Copperline Way")],
        pickups, rules,
    ))
    assert (m["a.txt"].pickup_id, m["a.txt"].address_ok) == ("P2", True)
    assert (m["b.txt"].pickup_id, m["b.txt"].address_ok) == ("P1", True)


def test_address_mismatch_still_matches_on_account_and_date(rules):
    m = by_name(match_tickets([ticket("a.txt", 5, "92 Pine St")], [pickup("P1", 5, "48 Lakeview Ave")], rules))
    assert (m["a.txt"].status, m["a.txt"].pickup_id, m["a.txt"].address_ok) == (MATCHED, "P1", False)


def test_clear_ticket_is_not_pushed_off_its_pickup(rules):
    # z.txt names site A; a.txt names neither site and sorts first. a.txt must take B, not A.
    pickups = [pickup("PA", 5, "1 Site A"), pickup("PB", 5, "2 Site B")]
    m = by_name(match_tickets([ticket("a.txt", 5, "9 Elsewhere"), ticket("z.txt", 5, "1 Site A")], pickups, rules))
    assert m["z.txt"].pickup_id == "PA" and m["a.txt"].pickup_id == "PB"


def test_second_ticket_for_a_pickup_is_a_duplicate_not_a_match_elsewhere(rules):
    # Same account has another site that day; the copy must not be matched to it.
    pickups = [pickup("PA", 5, "1 Site A"), pickup("PB", 5, "2 Site B")]
    m = by_name(match_tickets(
        [ticket("t_copy.txt", 5, "1 Site A"), ticket("t.txt", 5, "1 Site A")], pickups, rules,
    ))
    # identical tickets: the first by file name is used ("t.txt" sorts before "t_copy.txt")
    assert (m["t.txt"].status, m["t.txt"].pickup_id) == (MATCHED, "PA")
    assert (m["t_copy.txt"].status, m["t_copy.txt"].pickup_id, m["t_copy.txt"].duplicate_of) == (DUPLICATE, "PA", "t.txt")


def test_ticket_for_other_site_is_unmatched_not_duplicate(rules):
    # Only pickup nearby is taken and at another site: this is a ticket with no pickup.
    m = by_name(match_tickets(
        [ticket("a.txt", 5, "1 Site A"), ticket("x.txt", 6, "7 Other Rd")], [pickup("PA", 5, "1 Site A")], rules,
    ))
    assert m["a.txt"].status == MATCHED and m["x.txt"].status == UNMATCHED


def test_copies_with_same_wrong_address_are_still_duplicates(rules):
    m = by_name(match_tickets(
        [ticket("t.txt", 5, "92 Pine St"), ticket("t2.txt", 5, "92 pine street")],
        [pickup("PA", 5, "48 Lakeview Ave")], rules,
    ))
    assert (m["t.txt"].status, m["t.txt"].address_ok) == (MATCHED, False)
    assert (m["t2.txt"].status, m["t2.txt"].duplicate_of) == (DUPLICATE, "t.txt")


def test_exact_date_beats_off_by_one(rules):
    m = by_name(match_tickets([ticket("a.txt", 5)], [pickup("P4", 4), pickup("P5", 5), pickup("P6", 6)], rules))
    assert m["a.txt"].pickup_id == "P5"


def test_low_confidence_ticket_loses_tie_to_readable_one(rules):
    m = by_name(match_tickets(
        [ticket("a.txt", 5, confidence="low"), ticket("b.txt", 5)], [pickup("P1", 5)], rules,
    ))
    assert m["b.txt"].status == MATCHED and m["a.txt"].status == DUPLICATE


@pytest.mark.parametrize("change", [{"account_id": None}, {"date": None}, {"date": "not a date"}])
def test_ticket_without_account_or_date_is_unreadable(rules, change):
    rec = ticket("a.txt", 5, confidence="low")
    for k, v in change.items():
        setattr(rec, k, v)
    assert by_name(match_tickets([rec], [pickup("P1", 5)], rules))["a.txt"].status == UNREADABLE


def test_pickup_without_date_is_never_a_candidate(rules):
    undated = Pickup("P1", "1043", None, "1 Test St", "completed", "")
    assert by_name(match_tickets([ticket("a.txt", 5)], [undated], rules))["a.txt"].status == UNMATCHED


def test_results_keep_ticket_order(rules):
    recs = [ticket("b.txt", 5), ticket("a.txt", 6)]
    result = match_tickets(recs, [pickup("P1", 5), pickup("P2", 6)], rules)
    assert [m.source_file for m in result.matches] == ["b.txt", "a.txt"]
