# month-end-toolkit

A reusable month-end reconciliation tool. It reads a month's dispatch export and
driver tickets, finds unbilled fees and mismatches, and writes one Excel file a
billing team can work from. A person approves anything uncertain.

> **Synthetic data.** "Ridgeline Waste" and all sample data are fictional.

## Run a month

```bash
python run.py --month 2026-11
```

Inputs: `inputs/2026-11/`. Output: `outputs/2026-11/reconciliation_2026-11.xlsx`.

If that Excel file already exists, the run stops so decisions typed into it aren't
lost. Move or rename the file, or add `--force` to overwrite it.

The Excel file has five tabs:

| Tab | What it's for |
|---|---|
| **Summary** | Match rate, fees to add, fees held, rows to review, findings by issue, fees by account against the sign-off threshold |
| **Fees to add** | Fees the tool is sure of, with the source ticket for each |
| **Needs review** | Everything a person must decide, with the reason and a **Decision** column. Work every row before invoices go out |
| **Matched** | Pickups with a ticket and nothing to flag |
| **Run log** | Files read, counts, model used, warnings |

Prices, tolerances and review rules live in `rules/rules.yaml`. Change them
there, never in the code.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add TOOLKIT_ANTHROPIC_API_KEY
python scripts/make_sample_data.py   # creates inputs/2026-10 and 2026-11
```

## Tests

```bash
pytest
```

No test calls the API. `tests/test_month_two.py` runs both sample months end to
end from saved ticket answers and fails if Claude is called;
`tests/test_checks.py` compares each month's findings with its answer key.

## Status

| Build step | State |
|---|---|
| 1. Load + run command | Done (2026-11-27) |
| 2. Ticket extraction (Claude) | Done (2026-11-27) |
| 3. Matching + checks | Done (2026-11-27) |
| 4. Full Excel output + month-two test | In progress: tabs and month-two test done; Skill and handover next |

**What works today:** `python run.py --month YYYY-MM` checks the API key, reads
`rules/rules.yaml`, loads the dispatch export, finds the ticket files, reads each
ticket with Claude into fixed fields, checks every field, matches tickets to
pickups, runs all eight checks with fees from `rules.yaml`, and writes the Excel
file with all five tabs. Uncertain fees are held for review, never added. Both
sample months (`2026-10`, `2026-11`) produce the full workbook with no code
changes and find every planted issue in the answer keys.

Ticket answers are saved in `outputs/YYYY-MM/extracted.json`. A re-run reuses
them and makes no API calls unless a ticket file or the model settings in
`rules.yaml` change. Changing `model:` settings re-reads every ticket (about
$0.25 per sample month).

**Not yet:** the Claude Skill wrapper (`.claude/skills/month-end/`) is still a
stub, and the handover document isn't written.

See `CLAUDE.md` for the spec and build order, and `docs/delivery-log.md` for what
was built and what broke.
