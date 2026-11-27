"""Load and validate rules/rules.yaml.

Only structure is checked here (keys present, right types). Business meaning of
the matching and review settings is applied in later steps.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from toolkit.errors import ToolkitError


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
    review: dict[str, Any]
    model_name: str
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
        matching=dict(_section(data, "matching", path)),
        review=dict(_section(data, "review", path)),
        model_name=_text(model, "name", "model", path),
        model_max_tokens=max_tokens,
    )
