# Handover: [client] month-end reconciliation

## What it does
[One paragraph, plain English. What goes in, what comes out, what it saves.]

## How to run it each month
1. Put the dispatch export and scanned tickets in `inputs/YYYY-MM/`.
2. Run `python run.py --month YYYY-MM` (or ask Claude: "run month-end for November").
3. Open `outputs/YYYY-MM/reconciliation_YYYY-MM.xlsx`.

## What to check before invoicing
- Work every row on **Needs review** and fill in the Decision column.
- Add the amounts on **Fees to add** to the invoices.
- [Client approval rule, e.g. manager signs off invoices over $5,000.]

## What it doesn't do
[Out of scope: e.g. it never writes to QuickBooks or sends invoices.]

## Who owns it
- Day-to-day: [name]
- Rules changes (prices, fee types): [name]
- If it breaks: [name / contact]

## Data and access
[Where the data goes, which account runs it, what the tool can and can't reach.]

## 30-day check
- How many months / tickets ran through it, and by whom
- Match rate and fees found vs. the target
- The next task worth automating
