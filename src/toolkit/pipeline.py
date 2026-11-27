"""One month's run, start to finish.

Session 1: key check, rules, paths, dispatch load, ticket discovery, Run log tab.
Extraction (session 2) and checks (session 3) slot in between discovery and writing.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from toolkit.apikey import load_api_key
from toolkit.config import load_rules
from toolkit.errors import ToolkitError
from toolkit.excel import write_workbook
from toolkit.loaders import count_by, discover_tickets, load_dispatch
from toolkit.paths import check_inputs_exist, month_paths
from toolkit.runlog import RunLog


@dataclass
class RunResult:
    workbook: Path
    dispatch_rows: int
    tickets: int
    runlog: RunLog


def run(month: str, root: Path, force: bool = False) -> RunResult:
    """Run one month. Raises ToolkitError with a plain-English message if the run can't go ahead."""
    log = RunLog()

    load_api_key(root / ".env")  # rule 5: fail at startup, before reading any input
    rules = load_rules(root / "rules" / "rules.yaml")
    paths = month_paths(month, rules, root)

    if paths.workbook.exists() and not force:
        raise ToolkitError(
            f"{paths.workbook.name} already exists. Decisions typed into it would be lost if it "
            f"were replaced. Move or rename it, or run again with --force to overwrite it."
        )
    check_inputs_exist(paths)

    log.info("start", "run started", log.started_at.strftime("%Y-%m-%d %H:%M:%S"))
    log.info("start", "month", month)
    log.info("start", "client", rules.client)
    log.info("start", "rules version", rules.version, rules.source_path.name)
    log.info("start", "API key", "present", "TOOLKIT_ANTHROPIC_API_KEY")
    log.info("start", "model", rules.model_name, "not called yet: ticket reading is added in build step 2")
    if force and paths.workbook.exists():
        log.warn("start", f"--force used: replacing the existing {paths.workbook.name}.")

    dispatch = load_dispatch(paths.dispatch_file, paths.first_day, paths.last_day)
    rows = dispatch.rows
    log.info("dispatch", paths.dispatch_file.name, len(rows), "pickup rows read")
    for status, n in count_by(rows["status"]).items():
        log.info("dispatch", f"status: {status or '(blank)'}", n)
    log.info("dispatch", "rows with extras_recorded", int((rows["extras_recorded"] != "").sum()))
    log.warn_all("dispatch", dispatch.warnings)

    found = discover_tickets(paths.tickets_dir, rules.inputs.ticket_extensions)
    log.info("tickets", f"{paths.tickets_dir.name}/", len(found.tickets), "ticket files found")
    for kind, n in count_by(t.kind for t in found.tickets).items():
        log.info("tickets", f"type: {kind}", n)
    log.warn_all("tickets", found.warnings)

    log.info("output", paths.workbook.name, "written", f"{len(log.warnings)} warning(s) in this log")
    log.info("output", "run finished", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    write_workbook(paths.workbook, log)

    return RunResult(
        workbook=paths.workbook,
        dispatch_rows=len(rows),
        tickets=len(found.tickets),
        runlog=log,
    )
