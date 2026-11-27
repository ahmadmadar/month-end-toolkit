"""One month's run, start to finish.

Key check, rules, paths, dispatch load, ticket discovery, ticket reading
(Claude, cached in extracted.json), Run log tab. Checks (session 3) slot in
between ticket reading and writing.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import anthropic

from toolkit.apikey import load_api_key
from toolkit.cache import ExtractionCache
from toolkit.config import load_rules
from toolkit.errors import ToolkitError
from toolkit.excel import write_workbook
from toolkit.extract import Extractor
from toolkit.loaders import TicketFile, count_by, discover_tickets, load_dispatch
from toolkit.paths import check_inputs_exist, month_paths
from toolkit.runlog import RunLog
from toolkit.validate import TicketRecord

# Stop the run if this many API calls fail in a row: something is wrong (network, outage, quota)
# and carrying on would only mark every remaining ticket as failed.
MAX_FAILURES_IN_A_ROW = 5

Progress = Callable[[int, int], None]  # (tickets done, tickets total); counts only, never ticket text


@dataclass
class ReadStats:
    from_cache: int = 0
    sent: int = 0
    not_sent: int = 0
    failed: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class RunResult:
    workbook: Path
    dispatch_rows: int
    tickets: int
    runlog: RunLog
    records: list[TicketRecord] = field(default_factory=list)
    stats: ReadStats = field(default_factory=ReadStats)


def read_tickets(
    tickets: list[TicketFile],
    extractor: Extractor,
    cache: ExtractionCache,
    log: RunLog,
    progress: Progress | None = None,
) -> tuple[list[TicketRecord], ReadStats]:
    """Read every ticket: saved answer if unchanged, otherwise one Claude call. Returns one record per ticket."""
    stats = ReadStats()
    records: list[TicketRecord] = []
    in_a_row = 0
    for i, ticket in enumerate(tickets, start=1):
        record = cache.get(ticket)
        if record is not None:
            stats.from_cache += 1
        else:
            outcome = extractor.extract(ticket)
            record = outcome.record
            stats.input_tokens += outcome.input_tokens
            stats.output_tokens += outcome.output_tokens
            if outcome.called_api:
                stats.sent += 1
            else:
                stats.not_sent += 1
            if outcome.cacheable:
                cache.put(ticket, record)
            if outcome.note:
                log.warn("extract", f"{ticket.name}: {outcome.note}.")
            if outcome.failed:
                stats.failed += 1
                in_a_row += 1
                if in_a_row >= MAX_FAILURES_IN_A_ROW:
                    raise ToolkitError(
                        f"Stopped after {in_a_row} API failures in a row (last: {outcome.note}). "
                        f"{stats.sent - stats.failed} new answer(s) were saved; run again to continue "
                        f"from where it stopped."
                    )
            else:
                in_a_row = 0
        records.append(record)
        if progress:
            progress(i, len(tickets))
    cache.save(keep={t.name for t in tickets})
    return records, stats


def run(
    month: str,
    root: Path,
    force: bool = False,
    client=None,
    progress: Progress | None = None,
) -> RunResult:
    """Run one month. Raises ToolkitError with a plain-English message if the run can't go ahead.

    `client` is for tests (a fake Claude client); normally it's built from the toolkit key.
    """
    log = RunLog()

    key = load_api_key(root / ".env")  # rule 5: fail at startup, before reading any input
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
    log.info("start", "model", rules.model_name, f"effort {rules.model_effort}, max_tokens {rules.model_max_tokens}")
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

    if client is None:
        # api_key is passed explicitly so ANTHROPIC_API_KEY in the environment is never used (rule 5).
        client = anthropic.Anthropic(api_key=key, max_retries=3, timeout=120)
    extractor = Extractor(client, rules, paths.first_day, paths.last_day)
    cache = ExtractionCache(paths.output_dir / "extracted.json", extractor.settings)
    if cache.warning:
        log.warn("extract", cache.warning)
    records, stats = read_tickets(found.tickets, extractor, cache, log, progress)
    log.info("extract", "from saved results", stats.from_cache, "extracted.json; no API call")
    log.info("extract", "sent to Claude", stats.sent)
    log.info("extract", "not sent", stats.not_sent, "empty or too large; marked low confidence")
    log.info("extract", "API calls failed", stats.failed, "run again to retry these")
    log.info("extract", "low confidence", sum(r.confidence == "low" for r in records), "will go to Needs review")
    log.info("extract", "medium confidence", sum(r.confidence == "medium" for r in records))
    log.info("extract", "high confidence", sum(r.confidence == "high" for r in records))
    log.info("extract", "tokens in / out", f"{stats.input_tokens} / {stats.output_tokens}", "this run only")

    log.info("output", paths.workbook.name, "written", f"{len(log.warnings)} warning(s) in this log")
    log.info("output", "run finished", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    write_workbook(paths.workbook, log)

    return RunResult(
        workbook=paths.workbook,
        dispatch_rows=len(rows),
        tickets=len(found.tickets),
        runlog=log,
        records=records,
        stats=stats,
    )
