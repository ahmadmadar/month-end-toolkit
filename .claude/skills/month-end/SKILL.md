---
name: month-end
description: Run the month-end reconciliation for a given month and explain the results in plain English. Use when someone asks to run, check or explain month-end, tickets or fees.
---

# Month-end reconciliation (stub: finish in build session 4)

1. Ask which month (YYYY-MM) if not given.
2. Check `inputs/<month>/` has the dispatch export and a tickets folder. If not, say what's missing.
3. Run `python run.py --month <month>`.
4. Report from the Summary tab: match rate, fees found ($), how many rows need review.
5. Remind the user that "Needs review" rows must be decided before invoices go out.

Never edit rules.yaml or invent a fee. If something fails, say what failed in plain English.
