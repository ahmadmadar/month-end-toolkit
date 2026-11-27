"""The Run log: what the run read, counted and decided.

Holds counts, file names and decisions only (CLAUDE.md rule 6). Never put
ticket text, customer names or addresses in here.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class LogEntry:
    level: str   # "info" | "warning"
    step: str    # e.g. "start", "dispatch", "tickets"
    item: str    # what the row is about, e.g. a file name or setting
    value: str   # the count or setting value
    note: str = ""


class RunLog:
    COLUMNS = ("Level", "Step", "Item", "Value", "Note")

    def __init__(self, started_at: datetime | None = None):
        self.started_at = started_at or datetime.now()
        self.entries: list[LogEntry] = []

    def info(self, step: str, item: str, value: object = "", note: str = "") -> None:
        self.entries.append(LogEntry("info", step, item, str(value), note))

    def warn(self, step: str, message: str) -> None:
        self.entries.append(LogEntry("warning", step, "warning", "", message))

    def warn_all(self, step: str, messages: list[str]) -> None:
        for message in messages:
            self.warn(step, message)

    @property
    def warnings(self) -> list[LogEntry]:
        return [e for e in self.entries if e.level == "warning"]

    def rows(self) -> list[tuple[str, str, str, str, str]]:
        return [(e.level, e.step, e.item, e.value, e.note) for e in self.entries]
