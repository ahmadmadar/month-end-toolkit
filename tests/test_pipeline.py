"""End-to-end run on a temp project folder with a fake Claude client. No API calls, no cost."""

import json
import shutil
from pathlib import Path

import pytest
from openpyxl import load_workbook

from toolkit import excel
from toolkit.apikey import KEY_NAME
from toolkit.errors import ToolkitError
from toolkit.loaders import DISPATCH_COLUMNS
from toolkit import pipeline
from toolkit.pipeline import MAX_FAILURES_IN_A_ROW

from test_extract import FakeClient, api_error, response

import anthropic

ROOT = Path(__file__).resolve().parents[1]
MONTH = "2026-11"


def run(month, root, force=False, client=None, progress=None):
    """pipeline.run with a fake client by default, so no test ever calls the API."""
    return pipeline.run(month, root, force=force, client=client or FakeClient(response()), progress=progress)


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
    assert wb.sheetnames == ["Summary", "Fees to add", "Needs review", "Matched", "Run log"]
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
    assert flat[("extract", "sent to Claude")] == "2"
    assert flat[("extract", "high confidence")] == "2"
    # t1/t2 both get the same fake answer (acct 1264), and the pickups are acct 1043: nothing matches
    assert flat[("match", "tickets unmatched")] == "2" and flat[("match", "tickets duplicate")] == "0"
    assert flat[("checks", "missing_ticket")] == "2"
    assert flat[("checks", "fees to add ($)")] == "0.00"
    assert flat[("checks", "match rate")] == "0.0%"
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
    real_replace = excel.os.replace

    def locked(src, dst):
        if str(dst).endswith(".xlsx"):
            raise PermissionError("locked")
        real_replace(src, dst)

    monkeypatch.setattr(excel.os, "replace", locked)
    with pytest.raises(ToolkitError, match="open in Excel"):
        run(MONTH, project)
    assert not list((project / "outputs" / MONTH).glob(".*.tmp"))


def test_missing_month_folder(project):
    with pytest.raises(ToolkitError, match="No input folder for 2026-12"):
        run("2026-12", project)


# --- ticket reading ---

def test_second_run_reuses_saved_answers(project):
    first = FakeClient(response())
    run(MONTH, project, client=first)
    second = FakeClient(response())
    result = run(MONTH, project, force=True, client=second)
    assert len(first.calls) == 2 and second.calls == []
    assert (result.stats.from_cache, result.stats.sent) == (2, 0)
    assert [r.source_file for r in result.records] == ["t1.txt", "t2.txt"]


def test_changed_ticket_is_read_again_and_removed_ticket_dropped(project):
    run(MONTH, project)
    tickets = project / "inputs" / MONTH / "tickets"
    (tickets / "t1.txt").write_text("ticket one, corrected")
    (tickets / "t2.txt").unlink()
    client = FakeClient(response())
    result = run(MONTH, project, force=True, client=client)
    assert len(client.calls) == 1 and result.stats.from_cache == 0
    saved = json.loads((project / "outputs" / MONTH / "extracted.json").read_text())
    assert set(saved["entries"]) == {"t1.txt"}


def test_failed_calls_are_not_saved_and_retry_next_run(project):
    down = FakeClient(api_error(anthropic.InternalServerError, 500))
    result = run(MONTH, project, client=down)
    assert result.stats.failed == 2
    assert all(r.confidence == "low" for r in result.records)
    assert sum("API error 500" in w.note for w in result.runlog.warnings) == 2
    up = FakeClient(response())
    result = run(MONTH, project, force=True, client=up)
    assert len(up.calls) == 2 and result.stats.failed == 0


def test_run_stops_after_failures_in_a_row_and_keeps_earlier_answers(project):
    tickets = project / "inputs" / MONTH / "tickets"
    for i in range(3, 9):
        (tickets / f"t{i}.txt").write_text(f"ticket {i}")

    class FailsAfterFirst(FakeClient):
        def create(self, **kwargs):
            if self.calls:
                self.result = api_error(anthropic.InternalServerError, 503)
            return super().create(**kwargs)

    client = FailsAfterFirst(response())
    with pytest.raises(ToolkitError, match=f"{MAX_FAILURES_IN_A_ROW} API failures in a row"):
        run(MONTH, project, client=client)
    assert len(client.calls) == 1 + MAX_FAILURES_IN_A_ROW
    saved = json.loads((project / "outputs" / MONTH / "extracted.json").read_text())
    assert list(saved["entries"]) == ["t1.txt"]
    assert not (project / "outputs" / MONTH / f"reconciliation_{MONTH}.xlsx").exists()


def test_existing_workbook_stops_before_any_api_call(project):
    run(MONTH, project)
    client = FakeClient(response())
    with pytest.raises(ToolkitError, match="--force"):
        run(MONTH, project, client=client)
    assert client.calls == []


def test_progress_reports_counts_only(project):
    seen = []
    run(MONTH, project, progress=lambda done, total: seen.append((done, total)))
    assert seen == [(1, 2), (2, 2)]
