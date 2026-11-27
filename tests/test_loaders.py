"""Dispatch loader, ticket discovery and Run log. Uses temp files, plus a row count on the sample inputs."""

from datetime import date
from pathlib import Path

import pytest

from toolkit.errors import ToolkitError
from toolkit.loaders import DISPATCH_COLUMNS, count_by, discover_tickets, load_dispatch
from toolkit.runlog import RunLog

ROOT = Path(__file__).resolve().parents[1]
NOV = (date(2026, 11, 1), date(2026, 11, 30))
EXTS = (".txt", ".pdf", ".png", ".jpg", ".jpeg")
HEADER = ",".join(DISPATCH_COLUMNS)


def csv(tmp_path: Path, *rows: str, header: str = HEADER) -> Path:
    path = tmp_path / "dispatch.csv"
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    return path


ROW = "P1,2026-11-03,1043,Test Co,1043-1,1 Test St,4yd bin,completed,"


# --- dispatch ---

def test_loads_rows_as_text_with_real_dates(tmp_path):
    result = load_dispatch(csv(tmp_path, ROW, "P2,2026-11-04,0099,Test Co,0099-1,2 Test St,4yd bin,completed,1 extra bin"), *NOV)
    assert len(result.rows) == 2
    assert result.rows.at[1, "account_id"] == "0099"           # leading zero kept
    assert result.rows.at[0, "date"] == date(2026, 11, 3)
    assert result.rows.at[0, "extras_recorded"] == ""
    assert result.rows.at[1, "extras_recorded"] == "1 extra bin"
    assert result.warnings == []


def test_crlf_bom_and_padded_values(tmp_path):
    path = tmp_path / "dispatch.csv"
    path.write_bytes(("﻿" + HEADER + "\r\n" + " P1 ,2026-11-03,1043,Test Co,1043-1,1 Test St,4yd bin,completed,\r\n").encode("utf-8"))
    result = load_dispatch(path, *NOV)
    assert list(result.rows.columns) == list(DISPATCH_COLUMNS)
    assert result.rows.at[0, "pickup_id"] == "P1"


def test_missing_columns_stop_the_run(tmp_path):
    header = HEADER.replace(",site_address", "").replace(",status", "")
    with pytest.raises(ToolkitError, match="site_address, status"):
        load_dispatch(csv(tmp_path, "x", header=header), *NOV)


def test_header_only_and_empty_file(tmp_path):
    with pytest.raises(ToolkitError, match="no pickup rows"):
        load_dispatch(csv(tmp_path), *NOV)
    empty = tmp_path / "empty.csv"
    empty.write_text("")
    with pytest.raises(ToolkitError, match="empty"):
        load_dispatch(empty, *NOV)


def test_odd_rows_are_kept_and_warned(tmp_path):
    result = load_dispatch(
        csv(
            tmp_path,
            ROW,
            ROW,                                                   # duplicate P1
            "P3,03/11/2026,1043,Test Co,1043-1,1 Test St,4yd bin,completed,",   # bad date
            "P4,2026-10-31,1043,Test Co,1043-1,1 Test St,4yd bin,completed,",   # outside month
            ",2026-11-05,,Test Co,1043-1,1 Test St,4yd bin,completed,",         # blank ids
        ),
        *NOV,
    )
    assert len(result.rows) == 5
    assert result.rows.at[2, "date"] is None
    text = "\n".join(result.warnings)
    assert "duplicate pickup_id(s): P1" in text
    assert "row 4 (P3)" in text and "not YYYY-MM-DD" in text
    assert "1 row(s) dated outside 2026-11, kept: P4" in text
    assert "row 6: blank pickup_id" in text and "row 6: blank account_id" in text


def test_warnings_never_contain_names_or_addresses(tmp_path):
    result = load_dispatch(csv(tmp_path, ROW, ROW, "P9,bad,1,Secret Name,1-1,99 Hidden Rd,x,completed,"), *NOV)
    text = "\n".join(result.warnings)
    assert "Secret Name" not in text and "Hidden Rd" not in text and "Test Co" not in text


def test_extra_columns_are_ignored_with_warning(tmp_path):
    result = load_dispatch(csv(tmp_path, ROW + ",x", header=HEADER + ",notes"), *NOV)
    assert list(result.rows.columns) == list(DISPATCH_COLUMNS)
    assert any("notes" in w for w in result.warnings)


@pytest.mark.parametrize("month, first, last, rows", [
    ("2026-10", date(2026, 10, 1), date(2026, 10, 31), 67),
    ("2026-11", date(2026, 11, 1), date(2026, 11, 30), 63),
])
def test_sample_inputs_load(month, first, last, rows):
    result = load_dispatch(ROOT / "inputs" / month / "dispatch_export.csv", first, last)
    assert len(result.rows) == rows


# --- tickets ---

def touch(folder: Path, name: str, text: str = "x") -> None:
    (folder / name).write_text(text)


def test_discovers_allowed_types_and_skips_the_rest(tmp_path):
    for name in ["b.txt", "a.PDF", "c.jpeg", "d.png", "notes.docx", ".DS_Store"]:
        touch(tmp_path, name)
    (tmp_path / "old").mkdir()
    found = discover_tickets(tmp_path, EXTS)
    assert [t.name for t in found.tickets] == ["a.PDF", "b.txt", "c.jpeg", "d.png"]
    assert count_by(t.kind for t in found.tickets) == {"image": 2, "pdf": 1, "text": 1}
    text = "\n".join(found.warnings)
    assert "notes.docx" in text and "subfolder 'old'" in text and "1 hidden/system file(s)" in text


def test_type_allowed_in_rules_but_no_reader(tmp_path):
    touch(tmp_path, "scan.tif")
    found = discover_tickets(tmp_path, EXTS + (".tif",))
    assert found.tickets == []
    assert any("no reader for .tif" in w for w in found.warnings)


def test_empty_ticket_kept_with_warning_and_empty_folder_warned(tmp_path):
    touch(tmp_path, "blank.txt", "")
    found = discover_tickets(tmp_path, EXTS)
    assert [t.name for t in found.tickets] == ["blank.txt"]
    assert any("is empty" in w for w in found.warnings)

    empty = tmp_path / "none"
    empty.mkdir()
    assert any("no ticket files" in w for w in discover_tickets(empty, EXTS).warnings)


# --- run log ---

def test_run_log_rows_and_warnings():
    log = RunLog()
    log.info("dispatch", "dispatch_export.csv", 67, "rows")
    log.warn_all("tickets", ["one", "two"])
    assert len(log.warnings) == 2
    assert log.rows()[0] == ("info", "dispatch", "dispatch_export.csv", "67", "rows")
    assert log.rows()[1] == ("warning", "tickets", "warning", "", "one")
