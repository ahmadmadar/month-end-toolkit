# Handover: Ridgeline Waste (fictional) month-end reconciliation

> Sample client and data are fictional. Names below are roles; fill in the people.

## What it does

Each month, the tool compares the dispatch system's list of scheduled pickups
with the drivers' tickets. It finds pickups with no ticket, tickets with no
pickup, duplicate tickets, address differences, pickups the driver says weren't
done, and extra bins or contamination on a ticket that dispatch didn't record.
It works out the fees from the price list in `rules/rules.yaml` and writes
everything to one Excel file. Fees it's sure of are listed to add to invoices;
anything uncertain goes to a review list for a person to decide. It never adds a
fee it isn't sure of.

On the two sample months it found every planted issue (14 of 14 each month) and
added no fee that isn't on a ticket:

| Month | Pickups | Tickets | Match rate | Fees to add | Fees held for review | Rows to review |
|---|---|---|---|---|---|---|
| 2026-10 | 67 | 67 | 95.5% | $645.00 | $200.00 | 11 |
| 2026-11 | 63 | 63 | 95.2% | $805.00 | $40.00 | 9 |

## How to run it each month

1. Put the dispatch export and the scanned tickets in `inputs/YYYY-MM/`:
   - `dispatch_export.csv`
   - a `tickets/` folder (text, PDF, PNG or JPG files, one per pickup)
2. Run `python run.py --month YYYY-MM`, or ask Claude: "run month-end for November".
3. Open `outputs/YYYY-MM/reconciliation_YYYY-MM.xlsx`.

The first run of a month reads each ticket with Claude: about two minutes and
about $0.25 for 65 tickets. Running the same month again reuses what was read
and costs nothing, unless a ticket file or the model settings change.

If that month's Excel file already exists, the tool stops rather than replace
it, so decisions typed into it aren't lost. Save a copy first if you need to run
it again, then run with `--force` (Claude will ask before doing this).

## What's in the Excel file

| Tab | What it's for |
|---|---|
| **Summary** | Match rate, fees to add, fees held, rows to review, findings by type, fees by account against the sign-off threshold |
| **Fees to add** | Fees the tool is sure of, each with its pickup and source ticket, and the total |
| **Needs review** | Everything a person must decide, with the reason in plain English. Pick or type a **Decision** for each row (Bill it / Don't bill / Fixed in dispatch / Ask driver) and add **Notes** |
| **Matched** | Pickups with a ticket and nothing to flag |
| **Run log** | Files read, counts, model used, warnings |

## What to check before invoicing

- Work every row on **Needs review** and fill in the Decision column. Held fees
  (for example a ticket that says "2 bags/bins", which may not be bins) are not
  on Fees to add and aren't billed until someone decides them.
- Add the amounts on **Fees to add** to the invoices.
- Invoices over $5,000 need manager sign-off. The Summary marks any account
  whose fees found alone are over that, but it doesn't know whole invoice
  totals, so check each invoice too.
- Read the **Run log** warnings (amber rows): for example dispatch rows dated
  outside the month, or files in the tickets folder that were skipped.

## Rules you can change

All in `rules/rules.yaml`. Change them there, never in the code. The rules owner
makes these changes.

| Setting | Now | What it does |
|---|---|---|
| `fees.extra_bin` | $40.00 | Price per extra bin |
| `fees.contamination` | $175.00 | Flat fee per contaminated pickup |
| `matching.date_tolerance_days` | 1 | How many days a ticket date may differ from dispatch |
| `matching.address_words` | street→st, avenue→ave, … | Words treated as the same when comparing addresses |
| `matching.contamination_recorded_words` | contam | If dispatch's extras note has this, contamination is already billed |
| `review.hold_fee_when_extras_note_contains` | bag | Extras wording that holds the fee for review |
| `review.approval_threshold_cad` | 5000 | Sign-off threshold shown on the Summary |
| `inputs.*` | | File and folder names, and which ticket file types are read |
| `model.*` | claude-sonnet-5-5, effort low | Which Claude model reads tickets. Changing it re-reads every ticket (about $0.25 per month) |

## What it doesn't do

- It never writes to QuickBooks or any accounting system, and never sends
  invoices or email. Fees are added to invoices by a person.
- It doesn't read decisions back: a Decision typed in one month's file isn't
  carried into the next month.
- It doesn't change dispatch records. "Fixed in dispatch" is done in the
  dispatch system by a person.
- No driver tablets and no web page: it's one command (or one request to Claude)
  on the computer that holds the files.

## Known limits

- The sample tickets are all text files. PDF and image tickets are supported
  and tested with stand-in files, but haven't been run on real scans yet. Check
  the first month with real PDFs or photos closely.
- A ticket too damaged to read isn't guessed onto a pickup. It shows as
  "Ticket needs a person to read it", and the pickup it belongs to shows as
  "No driver ticket", with a note linking the two.
- Dispatch column names are fixed (`pickup_id, date, account_id, customer_name,
  site_id, site_address, service, status, extras_recorded`). A new dispatch
  system with different columns needs a code change.

## Who owns it

- Day-to-day (runs it, works Needs review): Billing admin, [name]
- Rules changes (prices, fee types, tolerances): Operations manager, [name]
- If it breaks: Toolkit builder, [name / contact]

## Data and access

- Ticket contents are sent to Anthropic's Claude API to be read, using the
  toolkit's own API key (`TOOLKIT_ANTHROPIC_API_KEY` in the `.env` file on the
  computer that runs it). Nothing else leaves that computer.
- The dispatch export is read on the computer only and is never sent to Claude.
- The key is never written into the code or the Excel file. If it's missing, the
  tool stops before reading anything.
- Results stay in `outputs/YYYY-MM/`: the Excel file, plus `extracted.json`,
  which holds what was read from each ticket so re-runs don't pay again. Treat
  that folder like the tickets themselves.
- The screen output and the Run log hold counts and file names only, no ticket
  text, customer names or addresses.
- Claude (via the month-end Skill) can run the tool and read the Summary. It's
  told never to change the rules, the code or any file, and never to overwrite
  a month's Excel file without asking.
- The project's `.claude/settings.json` lets Claude run only two commands
  without asking: running a month and showing its results. Replacing an
  existing month's Excel file (`--force`) always asks, and so does anything else.

## 30-day check

- How many months and tickets ran through it, and by whom
  (so far: the two sample months, 130 tickets, run by the builder)
- Match rate and fees found against the target. Target: every real issue found,
  and no fee added that isn't on a ticket. Sample months: 14 of 14 issues found
  each month, no fee without a ticket
- How many Needs review rows were "Don't bill" (a sign the tool is too cautious
  or a rule needs changing)
- The next task worth automating, for example carrying Needs review decisions
  into the next month, or a check that each "Fixed in dispatch" decision was
  actually fixed
