"""Saved extraction results: outputs/YYYY-MM/extracted.json.

A saved answer is reused only when the ticket file's content and the extraction
settings (model, effort, max_tokens, prompt version, run month) are unchanged,
so re-runs don't re-bill. The file is rewritten after every new answer, so an
interrupted run keeps what it already paid for.
"""

import hashlib
import json
import os
from pathlib import Path

from toolkit.loaders import TicketFile
from toolkit.validate import TicketRecord

CACHE_FORMAT = 1


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ExtractionCache:
    def __init__(self, path: Path, settings: dict):
        self.path = path
        self.settings = settings
        self.entries: dict[str, dict] = {}
        self.warning: str | None = None
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("format") != CACHE_FORMAT or not isinstance(data.get("entries"), dict):
                raise ValueError("unexpected format")
            self.entries = data["entries"]
        except (ValueError, OSError):
            bad = self.path.with_name(self.path.name + ".unreadable")
            os.replace(self.path, bad)
            self.warning = f"{self.path.name} could not be read; moved to {bad.name} and all tickets will be read again."

    def get(self, ticket: TicketFile) -> TicketRecord | None:
        entry = self.entries.get(ticket.name)
        if not entry or entry.get("settings") != self.settings or entry.get("sha256") != file_hash(ticket.path):
            return None
        try:
            return TicketRecord.from_dict(entry["record"])
        except (KeyError, TypeError):
            return None

    def put(self, ticket: TicketFile, record: TicketRecord) -> None:
        self.entries[ticket.name] = {
            "sha256": file_hash(ticket.path),
            "settings": self.settings,
            "record": record.to_dict(),
        }
        self.save()

    def save(self, keep: set[str] | None = None) -> None:
        """Write the file. With `keep`, drop entries for tickets no longer in the folder."""
        if keep is not None:
            self.entries = {k: v for k, v in self.entries.items() if k in keep}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f".{self.path.name}.tmp")
        tmp.write_text(json.dumps({"format": CACHE_FORMAT, "entries": self.entries}, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)
