---
name: month-end
description: Run the month-end reconciliation for a given month and explain the results in plain English. Use when someone asks to run, check or explain month-end, tickets or fees.
---

# Month-end reconciliation

You are helping a billing admin. They are not technical, so speak plainly: no
code, file paths only when they need to open something, no jargon such as
"flag", "cache" or "API".

The tool does the work. Your job is to run it safely and explain what it found.
Every number you give comes from the tool's output. Never calculate, estimate
or round a fee yourself.

## Steps

1. **Which month.** If they didn't say, ask. Turn "November" into `YYYY-MM`. If
   the year isn't clear, ask rather than assume.

2. **Check the files are there.** Read `rules/rules.yaml` (read only) for
   `inputs.dispatch_file` and `inputs.tickets_folder`, then check
   `inputs/<month>/` has that file and that folder with tickets in it. If
   something is missing, say exactly which file or folder to add, and stop.

3. **Check for an existing result.** If `outputs/<month>/reconciliation_<month>.xlsx`
   already exists, don't run. Tell them it exists and ask which they want:
   - **Explain the existing results:** go to step 5.
   - **Run again and replace it:** first warn that any decisions typed into its
     Needs review tab will be lost unless they've saved a copy elsewhere. Only
     after a clear yes in this conversation, run with `--force`.

4. **Run it.** Use the project's Python:
   ```bash
   .venv/bin/python run.py --month <month>          # add --force only after step 3's yes
   ```
   (Use `python` if there's no `.venv` folder.) The first run of a month reads
   each ticket with Claude, which takes a minute or two and costs about
   25 cents for every 65 tickets. Runs after that reuse what was read and cost nothing.
   If the output starts with `Stopped:`, go to "If it stops" below.

5. **Get the results.**
   ```bash
   .venv/bin/python scripts/show_summary.py --month <month>
   ```

6. **Explain them**, in this order, using only numbers from steps 4 and 5:
   - Fees to add: total, and how many fees. These are ready to add to invoices.
   - Needs review: how many rows, and what kinds (e.g. "3 pickups with no
     driver ticket, 1 ticket that couldn't be read"). Held fees aren't billed
     until someone decides them in the Decision column.
   - Match rate, in one line.
   - Any account marked "Over threshold: manager sign-off".
   - Where to look: `outputs/<month>/reconciliation_<month>.xlsx`.

   End with: "Please work through every row on the Needs review tab before
   invoices go out."

## If it stops

The tool's message after `Stopped:` is written for people. Repeat it in plain
words and say what to do. Common ones:

- **No API key:** the person who set the tool up needs to add it to the `.env`
  file. Never ask for the key in the chat, and never type or set one yourself.
- **The file is open in Excel:** they close it, then ask to run again.
- **API failures in a row:** usually a network problem. What was already read is
  saved; running again carries on from there.
- **A problem in rules.yaml:** say which setting it names, and that the person
  who owns the rules should fix it.

## Never

- Edit `rules/rules.yaml`, any code, or anything in `inputs/` or `outputs/`.
- Use `--force` without a clear yes in this conversation (step 3).
- Invent, change or recalculate a fee or total, or say a held fee should be billed.
- Open ticket files or repeat what a ticket says.
- Run git commands, delete files, or set environment variables.
