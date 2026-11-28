"""Load and validate rules/rules.yaml.

Only structure is checked here (keys present, right types). Business meaning of
the matching and review settings is applied in later steps.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from toolkit.errors import ToolkitError

EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
ADDRESS_MATCH_MODES = ("normalized", "exact")


@dataclass(frozen=True)
class InputsConfig:
    dispatch_file: str
    tickets_folder: str
    ticket_extensions: tuple[str, ...]  # lowercase, each starting with "."


@dataclass(frozen=True)
class Rules:
    source_path: Path
    version: str
    client: str
    inputs: InputsConfig
    fees: dict[str, float]
    matching: dict[str, Any]
    date_tolerance_days: int
    address_match: str                  # "normalized" | "exact"
    address_words: dict[str, str]       # lowercase word -> lowercase replacement
    review: dict[str, Any]
    model_name: str
    model_effort: str
    model_max_tokens: int


def _section(data: dict, name: str, path: Path) -> dict:
    value = data.get(name)
    if not isinstance(value, dict):
        raise ToolkitError(f"{path.name}: missing or invalid '{name}:' section.")
    return value


def _text(section: dict, key: str, where: str, path: Path) -> str:
    value = section.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolkitError(f"{path.name}: '{where}.{key}' must be a non-empty text value.")
    return value.strip()


def _extensions(raw: Any, path: Path) -> tuple[str, ...]:
    if not isinstance(raw, list) or not raw:
        raise ToolkitError(f"{path.name}: 'inputs.ticket_extensions' must be a non-empty list, e.g. [.txt, .pdf].")
    exts = []
    for item in raw:
        if not isinstance(item, str) or not item.startswith(".") or len(item) < 2:
            raise ToolkitError(f"{path.name}: ticket extension {item!r} must look like '.txt'.")
        exts.append(item.lower())
    return tuple(dict.fromkeys(exts))  # de-duplicate, keep order


def _fees(raw: dict, path: Path) -> dict[str, float]:
    fees = {}
    for name, amount in raw.items():
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount < 0:
            raise ToolkitError(f"{path.name}: fee '{name}' must be a number of 0 or more.")
        fees[str(name)] = float(amount)
    return fees


def _address_words(raw: Any, path: Path) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ToolkitError(f"{path.name}: 'matching.address_words' must be a list of word: replacement pairs.")
    words = {}
    for word, replacement in raw.items():
        if not isinstance(word, str) or not isinstance(replacement, str) or " " in word.strip() \
                or not word.strip() or not replacement.strip():
            raise ToolkitError(
                f"{path.name}: 'matching.address_words' entry {word!r}: {replacement!r} must be one word mapped to text."
            )
        words[word.strip().lower()] = replacement.strip().lower()
    return words


def load_rules(path: Path) -> Rules:
    """Read rules.yaml and return a validated Rules object. Raise ToolkitError on any problem."""
    if not path.is_file():
        raise ToolkitError(f"Rules file not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ToolkitError(f"{path.name} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ToolkitError(f"{path.name} is empty or not a set of key: value settings.")

    if data.get("version") is None:
        raise ToolkitError(f"{path.name}: missing 'version'.")
    client = data.get("client")
    if not isinstance(client, str) or not client.strip():
        raise ToolkitError(f"{path.name}: missing 'client'.")

    inputs = _section(data, "inputs", path)
    model = _section(data, "model", path)
    max_tokens = model.get("max_tokens")
    if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens <= 0:
        raise ToolkitError(f"{path.name}: 'model.max_tokens' must be a whole number above 0.")
    matching = _section(data, "matching", path)
    tolerance = matching.get("date_tolerance_days")
    if isinstance(tolerance, bool) or not isinstance(tolerance, int) or tolerance < 0:
        raise ToolkitError(f"{path.name}: 'matching.date_tolerance_days' must be a whole number of 0 or more.")
    address_match = matching.get("address_match", "normalized")
    if address_match not in ADDRESS_MATCH_MODES:
        raise ToolkitError(f"{path.name}: 'matching.address_match' must be one of {', '.join(ADDRESS_MATCH_MODES)}.")
    effort = model.get("effort")
    if effort not in EFFORT_LEVELS:
        raise ToolkitError(f"{path.name}: 'model.effort' must be one of {', '.join(EFFORT_LEVELS)}.")

    return Rules(
        source_path=path,
        version=str(data["version"]),
        client=client.strip(),
        inputs=InputsConfig(
            dispatch_file=_text(inputs, "dispatch_file", "inputs", path),
            tickets_folder=_text(inputs, "tickets_folder", "inputs", path),
            ticket_extensions=_extensions(inputs.get("ticket_extensions"), path),
        ),
        fees=_fees(_section(data, "fees", path), path),
        matching=dict(matching),
        date_tolerance_days=tolerance,
        address_match=address_match,
        address_words=_address_words(matching.get("address_words"), path),
        review=dict(_section(data, "review", path)),
        model_name=_text(model, "name", "model", path),
        model_effort=effort,
        model_max_tokens=max_tokens,
    )
