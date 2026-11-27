# month-end-toolkit: build spec

A small, reusable tool that runs a monthly back-office reconciliation for a client
and writes the result to one Excel file. It must run on a NEW month with one
command and no code changes. That is the test on the Caddie round 2 call.

> Sample data is synthetic. "Ridgeline Waste" is a fictional client used for testing.

## Who uses it

- **Builder (me):** runs and changes it in Claude Code / VS Code.
- **Client team (non-technical, e.g. a billing admin):** drops the month's files in a
  folder, runs one command (or asks the Claude Skill), opens the Excel file, and works
  the "Needs review" tab before invoices go out.

## Non-negotiable rules

1. **One command per month:** `python run.py --month YYYY-MM`. Inputs are read from
   `inputs/YYYY-MM/`, output written to `outputs/YYYY-MM/reconciliation_YYYY-MM.xlsx`.
2. **Nothing hardcoded to a month, a customer, a price or a file name.** Prices, fee
   types and matching tolerances live in `rules/rules.yaml`.
3. **A person approves anything uncertain.** The tool never decides a fee or credit it
   is unsure about. Low-confidence extractions and mismatches go to "Needs review".
4. **AI only where it's needed.** Structured files (CSV/Excel) are parsed with plain
   Python. Claude is used only to read unstructured tickets (text, PDF, images) into
   fixed fields. Matching and fee math are deterministic code, so they can be tested.
5. **Secrets:** the API key is read from `.env` as `TOOLKIT_ANTHROPIC_API_KEY`
   (never `ANTHROPIC_API_KEY`, so Claude Code sessions can't bill to it). Never
   hardcode a key or a fallback key. Fail at startup if the key is missing.
6. **No client data leaves the run:** no logging of full ticket text to stdout; the
   run log records counts, file names and decisions only.
7. **Never read `tests/fixtures/`** from tool code. Those are answer keys for tests.

## Input contract (per month folder)

| File | Format | Meaning |
|---|---|---|
| `dispatch_export.csv` | CSV | Every scheduled pickup from the dispatch system (system of record for what was scheduled) |
| `tickets/` | `.txt`, `.pdf`, `.png`/`.jpg` | Driver tickets, one per pickup, messy and handwritten-style |

Dispatch columns: `pickup_id, date, account_id, customer_name, site_id, site_address,
service, status, extras_recorded`.

The loaders should not assume these exact file names forever: read file names from
`rules.yaml` (`inputs:` section) so a new client's files can be mapped without code changes.

## Extracted ticket fields (Claude output, JSON, validated)

`account_id, date (YYYY-MM-DD), site_address, extra_bins (int), contamination (bool),
contamination_note, serviced (bool), confidence (high|medium|low), source_file`

Validate every field. Anything that fails validation becomes a low-confidence row,
not a crash.

## Checks (deterministic, from rules.yaml)

| Check | Flag |
|---|---|
| Completed pickup with no ticket | `missing_ticket` |
| Ticket with no matching pickup (account + date within tolerance) | `unmatched_ticket` |
| Ticket address differs from dispatch site address | `address_mismatch` |
| Extra bins on ticket, not in dispatch `extras_recorded` | `unbilled_extra` (adds fee) |
| Contamination on ticket, not in dispatch | `unbilled_contamination` (adds fee) |
| Dispatch says completed, ticket says not serviced | `service_dispute` |
| Two tickets for the same pickup | `duplicate_ticket` |
| Extraction confidence low | `needs_human_read` |

## Excel output tabs

1. **Summary:** counts per flag, total fees found ($), match rate (%), run date, rules version.
2. **Fees to add:** account, site, date, fee type, amount, source ticket.
3. **Needs review:** every flagged row with the reason in plain English and a blank "Decision" column.
4. **Matched:** clean pickups.
5. **Run log:** files read, counts, model used, warnings.

## Build order (one Claude Code session each)

1. **Load + run command:** `run.py`, config loading, CSV loader, ticket file discovery,
   startup key check. Output: a stub Excel with the Run log tab.
2. **Extraction:** Claude call per ticket with a fixed JSON schema; validation; cache
   results to `outputs/YYYY-MM/extracted.json` so re-runs don't re-bill.
3. **Matching + checks:** all checks above, fee math from rules.yaml.
4. **Excel output + month-two test:** all tabs, formatting, then run on `2026-10` and
   `2026-11` with no code change. Add the Claude Skill wrapper.

After each session: update `docs/delivery-log.md` (what Claude did, what it got wrong,
what I decided).

## Tests

- `tests/test_checks.py`: run checks on fixture data and compare flags with
  `tests/fixtures/YYYY-MM/expected_issues.json`.
- Re-run test: both sample months produce an Excel file with no code edits.
- Target: every planted issue found; zero fees added that aren't on a ticket.

## Out of scope

QuickBooks or any accounting-system write, sending email, driver tablets, a web UI.
