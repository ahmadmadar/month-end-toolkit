"""extracted.json: reuse only when the file and settings are unchanged."""

import json
from pathlib import Path

from toolkit.cache import ExtractionCache
from toolkit.loaders import TicketFile
from toolkit.validate import TicketRecord

SETTINGS = {"model": "m", "effort": "low", "max_tokens": 4000, "prompt_version": "1", "run_month": "2026-11"}


def ticket(folder: Path, name: str, text: str) -> TicketFile:
    path = folder / name
    path.write_text(text)
    return TicketFile(name=name, path=path, kind="text", size_bytes=len(text))


def record(name: str) -> TicketRecord:
    return TicketRecord(source_file=name, account_id="1043", confidence="high")


def test_hit_after_put_and_reload(tmp_path):
    path = tmp_path / "out" / "extracted.json"
    t = ticket(tmp_path, "a.txt", "Acct 1043")
    ExtractionCache(path, SETTINGS).put(t, record("a.txt"))
    assert ExtractionCache(path, SETTINGS).get(t) == record("a.txt")


def test_miss_when_ticket_changes(tmp_path):
    path = tmp_path / "extracted.json"
    t = ticket(tmp_path, "a.txt", "Acct 1043")
    ExtractionCache(path, SETTINGS).put(t, record("a.txt"))
    t.path.write_text("Acct 1044")
    assert ExtractionCache(path, SETTINGS).get(t) is None


def test_miss_when_any_setting_changes(tmp_path):
    path = tmp_path / "extracted.json"
    t = ticket(tmp_path, "a.txt", "Acct 1043")
    ExtractionCache(path, SETTINGS).put(t, record("a.txt"))
    for key, value in [("model", "other"), ("effort", "high"), ("max_tokens", 8000), ("prompt_version", "2")]:
        assert ExtractionCache(path, {**SETTINGS, key: value}).get(t) is None


def test_prune_removes_tickets_no_longer_present(tmp_path):
    path = tmp_path / "extracted.json"
    cache = ExtractionCache(path, SETTINGS)
    a, b = ticket(tmp_path, "a.txt", "1"), ticket(tmp_path, "b.txt", "2")
    cache.put(a, record("a.txt"))
    cache.put(b, record("b.txt"))
    cache.save(keep={"a.txt"})
    assert set(json.loads(path.read_text())["entries"]) == {"a.txt"}


def test_unreadable_cache_is_moved_aside_with_warning(tmp_path):
    path = tmp_path / "extracted.json"
    path.write_text("{not json")
    cache = ExtractionCache(path, SETTINGS)
    assert cache.entries == {} and "could not be read" in cache.warning
    assert (tmp_path / "extracted.json.unreadable").exists() and not path.exists()
