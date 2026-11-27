# Delivery log

What Claude did, what it got wrong, and what I decided. One entry per session.

| Date | Session | What Claude did | What it got wrong / what I caught | My decision |
|---|---|---|---|---|
| 2026-11-26 | 0: skeleton | Created repo structure, spec, rules file, sample-data generator | | Python + Excel output; AI only for reading tickets; matching is plain code |
| 2026-11-27 | 1: load + run | Built `run.py`, rules loading, month paths, key check, dispatch loader, ticket discovery and the Run log workbook. 41 tests pass. Both sample months run with no code changes (Oct: 67 pickups / 67 tickets; Nov: 63 / 63). | In the first draft, the key tests let a test key stay in the environment and leak into later tests, while every test still passed. Claude caught it by re-reading the code and fixed it with a fixture. Claude's first next-steps list said to run `git init`, which broke the rule that git work is mine; it was corrected after rereading CLAUDE.md. | Don't overwrite an existing workbook without `--force`. Ticket file types go in `rules.yaml`. Rows dated outside the month are kept with a warning. Dispatch column names stay fixed. |
