"""Address comparison. No API calls."""

import pytest

from toolkit.address import normalize, same_address

WORDS = {"street": "st", "avenue": "ave", "road": "rd"}


def test_normalize():
    assert normalize("  301 Elm STREET. ", WORDS) == "301 elm st"
    assert normalize("12-B Shore Rd., Unit #3", WORDS) == "12 b shore rd unit 3"


@pytest.mark.parametrize(
    "a, b, same",
    [
        ("301 Elm St", "301 Elm Street", True),
        ("48 Lakeview Ave.", "48 lakeview avenue", True),
        ("1 Copperline Way", "1 Copperline Way Loading Dock", False),
        ("92 Pine St", "48 Lakeview Ave", False),
        ("14 Oak St", "41 Oak St", False),
        ("14 Oak St", None, False),
        ("", "", False),
    ],
)
def test_same_address_normalized(a, b, same):
    assert same_address(a, b, "normalized", WORDS) is same


def test_exact_mode_ignores_only_case_and_spacing():
    assert same_address("301  elm st", "301 Elm St", "exact", WORDS)
    assert not same_address("301 Elm St", "301 Elm Street", "exact", WORDS)
    assert not same_address("301 Elm St.", "301 Elm St", "exact", WORDS)
