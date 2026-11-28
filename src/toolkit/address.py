"""Compare a ticket address with a dispatch address. Plain Python.

"normalized" (the default) ignores case, punctuation, spacing and the word swaps
listed in rules.yaml (matching.address_words, e.g. street -> st). Every other word
must match, so "1 Copperline Way" and "1 Copperline Way Loading Dock" are
different sites.
"""

import re

_PUNCTUATION = re.compile(r"[^\w\s]")


def normalize(address: str, words: dict[str, str]) -> str:
    text = _PUNCTUATION.sub(" ", address.lower())
    return " ".join(words.get(word, word) for word in text.split())


def same_address(a: str | None, b: str | None, mode: str, words: dict[str, str]) -> bool:
    """True if both addresses are present and count as the same site under the rules."""
    if not a or not b:
        return False
    if mode == "exact":
        return " ".join(a.lower().split()) == " ".join(b.lower().split())
    return normalize(a, words) == normalize(b, words)
