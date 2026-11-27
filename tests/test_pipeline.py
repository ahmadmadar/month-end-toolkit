"""End-to-end run on a temp project folder: key check order, --force, locked file, Run log tab."""

import shutil
from pathlib import Path

import pytest
from openpyxl import load_workbook

from toolkit import excel
from toolkit.apikey import KEY_NAME
from toolkit.errors import ToolkitError
from toolkit.loaders import DISPATCH_COLUMNS
from toolkit.pipeline import run

ROOT = Path(__file__).resolve().parents[1]
MONTH = "2026-11"


@pytest.fixture
def project(tmp_path, no_key) -> Path:
    """A minimal project: the repo's rules.yaml, a .env with a fake key, 2 pickups, 2 tickets."""
    (tmp_path / "rules").mkdir()
    shutil.copy(ROOT / "rules" / "rules.yaml", tmp_path / "rules" / "rules.yaml")
    (tmp_path / ".env").write_text(f"{KEY_NAME}=fake-test-key\n")
    month_dir = tmp_path / "inputs" / MONTH
    (month_dir / "tickets").mkdir(parents=True)
    (month_dir / "dispatch_export.csv").write_text(
        ",".join(DISPATCH_COLUMNS) + "\n"
        "P1,2026-11-03,1043,Test Co,1043-1,1 Test St,4yd bin,completed,\n"
        "P2,2026-11-04,1043,Test Co,1043-1,1 Test St,4yd bin,completed,1 extra bin\n"
    )
    (month_dir / "tickets" / "t1.txt").write_text("ticket one")
    (month_dir / "tickets" / "t2.txt").write_text("ticket two")
    return tmp_path


def run_log_rows(path: Path) -> list[tuple]:
    wb = load_workbook(path)
    assert wb.sheetnames == ["Run log"]
    return list(wb["Run log"].iter_rows(values_only=True))


def test_run_writes_run_log_tab(project):
    result = run(MONTH, project)
    assert result.workbook == project / "outputs" / MONTH / f"reconciliation_{MONTH}.xlsx"
    assert (result.dispatch_rows, result.tickets) == (2, 2)
    rows = run_log_rows(result.workbook)
    assert rows[0] == ("Level", "Step", "Item", "Value", "Note")
    flat = {(r[1], r[2]): r[3] for r in rows[1:]}
    assert flat[("dispatch", "dispatch_export.csv")] == "2"
    assert flat[("dispatch", "rows with extras_recorded")] == "1"
    assert flat[("tickets", "tickets/")] == "2"
    assert flat[("start", "API key")] == "present"
    assert not list(result.workbook.parent.glob(".*.tmp"))


def test_run_log_holds_no_ticket_text_key_or_addresses(project):
    result = run(MONTH, project)
    text = " ".join(str(c) for r in run_log_rows(result.workbook) for c in r if c)
    for secret in ["ticket one", "fake-test-key", "1 Test St", "Test Co"]:
        assert secret not in text


def test_missing_key_stops_before_inputs_are_checked(project):
    (project / ".env").unlink()
    shutil.rmtree(project / "inputs")
    with pytest.raises(ToolkitError, match=KEY_NAME):
        run(MONTH, project)


def test_existing_output_needs_force(project):
    first = run(MONTH, project)
    with pytest.raises(ToolkitError, match="--force"):
        run(MONTH, project)
    second = run(MONTH, project, force=True)
    assert second.workbook == first.workbook
    assert any("--force used" in w.note for w in second.runlog.warnings)


def test_locked_output_gives_plain_message_and_no_temp_file(project, monkeypatch):
    def locked(*_):
        raise PermissionError("locked")

    monkeypatch.setattr(excel.os, "replace", locked)
    with pytest.raises(ToolkitError, match="open in Excel"):
        run(MONTH, project)
    assert not list((project / "outputs" / MONTH).glob(".*.tmp"))


def test_missing_month_folder(project):
    with pytest.raises(ToolkitError, match="No input folder for 2026-12"):
        run("2026-12", project)
