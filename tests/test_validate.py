"""Validation of extracted ticket fields. No API calls."""

from datetime import date

import pytest

from toolkit.validate import TicketRecord, unreadable, validate_extraction

NOV = (date(2026, 11, 1), date(2026, 11, 30))
GOOD = {
    "account_id": "1264",
    "date": "2026-11-24",
    "date_raw": "dt 24/11",
    "site_address": "14 Oak St",
    "extra_bins": 2,
    "extras_note": "extras: 2 bags/bins",
    "contamination": False,
    "contamination_note": None,
    "serviced": True,
    "confidence": "high",
}


def check(raw, tolerance=1):
    return validate_extraction(raw, "t.txt", *NOV, tolerance)


def test_good_answer_passes_unchanged():
    rec = check(GOOD)
    assert rec.problems == []
    assert rec.confidence == "high"
    assert (rec.account_id, rec.date, rec.extra_bins, rec.serviced) == ("1264", "2026-11-24", 2, True)
    assert rec.extras_note == "extras: 2 bags/bins"
    assert rec.contamination_note == ""
    assert rec.source_file == "t.txt"


def test_medium_confidence_kept_when_valid():
    assert check({**GOOD, "confidence": "medium"}).confidence == "medium"


def test_integer_account_is_accepted_as_text():
    assert check({**GOOD, "account_id": 1043}).account_id == "1043"


@pytest.mark.parametrize(
    "change, field, problem",
    [
        ({"account_id": "120?"}, "account_id", "not all digits"),
        ({"account_id": None}, "account_id", "No account number"),
        ({"date": None}, "date", "missing, unreadable or ambiguous"),
        ({"date": "24/11/2026"}, "date", "YYYY-MM-DD"),
        ({"date": "2026-02-30"}, "date", "not a real calendar date"),
        ({"site_address": "  "}, "site_address", "No site address"),
        ({"extra_bins": -1}, "extra_bins", "not a whole number"),
        ({"extra_bins": 1.5}, "extra_bins", "not a whole number"),
        ({"extra_bins": True}, "extra_bins", "not a whole number"),
        ({"extra_bins": None}, "extra_bins", "unclear"),
        ({"contamination": "yes"}, "contamination", "contaminated"),
        ({"serviced": None}, "serviced", "serviced"),
    ],
)
def test_bad_field_is_emptied_and_forces_low(change, field, problem):
    rec = check({**GOOD, **change})
    assert getattr(rec, field) is None
    assert rec.confidence == "low"
    assert any(problem in p for p in rec.problems)


def test_date_outside_month_is_kept_but_low():
    rec = check({**GOOD, "date": "2026-10-15"})
    assert rec.date == "2026-10-15"
    assert rec.confidence == "low"
    assert any("outside 2026-11" in p for p in rec.problems)


def test_date_within_tolerance_is_fine():
    assert check({**GOOD, "date": "2026-12-01"}, tolerance=1).problems == []
    assert check({**GOOD, "date": "2026-12-01"}, tolerance=0).confidence == "low"


def test_invalid_confidence_and_missing_fields():
    rec = check({**GOOD, "confidence": "very sure"})
    assert rec.confidence == "low"
    rec = check({"confidence": "high"})
    assert rec.confidence == "low" and len(rec.problems) == 6


@pytest.mark.parametrize("raw", [None, "text", ["list"], 42])
def test_non_dict_answer(raw):
    rec = check(raw)
    assert rec.confidence == "low" and rec.account_id is None and rec.problems


def test_round_trip_and_unreadable():
    rec = check(GOOD)
    assert TicketRecord.from_dict(rec.to_dict()) == rec
    bad = unreadable("x.txt", "Ticket file is empty.")
    assert bad.confidence == "low" and bad.problems == ["Ticket file is empty."]
