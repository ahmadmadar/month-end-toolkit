"""Plain-Python loaders for the structured inputs: the dispatch CSV and the ticket file list.

Problems that stop the run raise ToolkitError. Problems the run can live with
are returned as warnings for the Run log. Warnings name files, row numbers and
pickup IDs only, never customer names, addresses or ticket text.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

from toolkit.errors import ToolkitError

# Fixed by the input contract in CLAUDE.md.
DISPATCH_COLUMNS = (
    "pickup_id",
    "date",
    "account_id",
    "customer_name",
    "site_id",
    "site_address",
    "service",
    "status",
    "extras_recorded",
)

# How each ticket file type will be read in session 2. A type listed in
# rules.yaml but missing here is skipped with a warning, not guessed at.
TICKET_KINDS = {
    ".txt": "text",
    ".pdf": "pdf",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
}


@dataclass
class DispatchResult:
    rows: pd.DataFrame          # all columns as text; "date" holds datetime.date or None
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TicketFile:
    name: str
    path: Path
    kind: str                   # "text" | "pdf" | "image"
    size_bytes: int


@dataclass
class TicketDiscovery:
    tickets: list[TicketFile]
    warnings: list[str] = field(default_factory=list)


def _csv_row(index: int) -> int:
    """Row number as a person sees it in Excel (header is row 1)."""
    return index + 2


def load_dispatch(path: Path, first_day: date, last_day: date) -> DispatchResult:
    """Read the dispatch export. Every row is kept; odd rows are reported as warnings."""
    try:
        df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    except pd.errors.EmptyDataError as exc:
        raise ToolkitError(f"{path.name} is empty.") from exc
    except (pd.errors.ParserError, UnicodeDecodeError) as exc:
        raise ToolkitError(f"{path.name} could not be read as a CSV: {exc}") from exc

    df.columns = [str(c).strip() for c in df.columns]
    missing = [c for c in DISPATCH_COLUMNS if c not in df.columns]
    if missing:
        raise ToolkitError(f"{path.name} is missing column(s): {', '.join(missing)}.")
    if df.empty:
        raise ToolkitError(f"{path.name} has a header but no pickup rows.")

    warnings: list[str] = []
    extra = [c for c in df.columns if c not in DISPATCH_COLUMNS]
    if extra:
        warnings.append(f"{path.name}: extra column(s) ignored: {', '.join(extra)}.")

    df = df[list(DISPATCH_COLUMNS)].apply(lambda col: col.str.strip())

    for col in ("pickup_id", "account_id"):
        blank = df.index[df[col] == ""]
        for i in blank:
            warnings.append(f"{path.name} row {_csv_row(i)}: blank {col}.")

    parsed = pd.to_datetime(df["date"], format="%Y-%m-%d", errors="coerce")
    for i in df.index[parsed.isna()]:
        warnings.append(
            f"{path.name} row {_csv_row(i)} ({df.at[i, 'pickup_id'] or 'no pickup_id'}): "
            f"date {df.at[i, 'date']!r} is not YYYY-MM-DD; row kept without a date."
        )
    df["date"] = [d.date() if not pd.isna(d) else None for d in parsed]

    outside = [
        i for i, d in zip(df.index, df["date"]) if d is not None and not first_day <= d <= last_day
    ]
    if outside:
        ids = ", ".join(df.at[i, "pickup_id"] or f"row {_csv_row(i)}" for i in outside)
        warnings.append(
            f"{path.name}: {len(outside)} row(s) dated outside {first_day:%Y-%m}, kept: {ids}."
        )

    ids = df.loc[df["pickup_id"] != "", "pickup_id"]
    dupes = sorted(ids[ids.duplicated()].unique())
    if dupes:
        warnings.append(f"{path.name}: duplicate pickup_id(s): {', '.join(dupes)}.")

    return DispatchResult(rows=df.reset_index(drop=True), warnings=warnings)


def discover_tickets(folder: Path, extensions: tuple[str, ...]) -> TicketDiscovery:
    """List ticket files in the folder (not subfolders) whose type is allowed in rules.yaml."""
    tickets: list[TicketFile] = []
    warnings: list[str] = []
    hidden = 0

    for path in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
        if path.name.startswith("."):
            hidden += 1
            continue
        if path.is_dir():
            warnings.append(f"tickets: subfolder '{path.name}' skipped (only files directly in the tickets folder are read).")
            continue
        ext = path.suffix.lower()
        if ext not in extensions:
            warnings.append(f"tickets: '{path.name}' skipped (file type not in rules.yaml ticket_extensions).")
            continue
        kind = TICKET_KINDS.get(ext)
        if kind is None:
            warnings.append(f"tickets: '{path.name}' skipped (the tool has no reader for {ext} files yet).")
            continue
        size = path.stat().st_size
        if size == 0:
            warnings.append(f"tickets: '{path.name}' is empty; it will need a human read.")
        tickets.append(TicketFile(name=path.name, path=path, kind=kind, size_bytes=size))

    if hidden:
        warnings.append(f"tickets: {hidden} hidden/system file(s) skipped.")
    if not tickets:
        warnings.append(f"tickets: no ticket files found in '{folder.name}'.")
    return TicketDiscovery(tickets=tickets, warnings=warnings)


def count_by(values) -> dict[str, int]:
    """Counts for the Run log, e.g. tickets per kind or pickups per status."""
    return dict(sorted(Counter(values).items()))
