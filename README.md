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

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add TOOLKIT_ANTHROPIC_API_KEY
python scripts/make_sample_data.py   # creates inputs/2026-10 and 2026-11
```

## Status

Skeleton only. See `CLAUDE.md` for the spec and build order, and
`docs/delivery-log.md` for what was built and what broke.
