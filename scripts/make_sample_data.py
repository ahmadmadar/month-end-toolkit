"""Generate synthetic sample data for two months, with planted issues.

Writes inputs/YYYY-MM/dispatch_export.csv and inputs/YYYY-MM/tickets/*.txt,
plus an answer key at tests/fixtures/YYYY-MM/expected_issues.json.
All data is fictional. Standard library only.
"""
import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CUSTOMERS = [
    ("1043", "Harbour Grill Group", ["112 Main St", "48 Lakeview Ave", "9 Station Rd"]),
    ("1077", "Northside Dental", ["301 Elm Street"]),
    ("1102", "Copperline Casino", ["1 Copperline Way", "1 Copperline Way Loading Dock"]),
    ("1150", "Prairie Foods Market", ["77 Granary Rd", "15 Mill Lane"]),
    ("1188", "Westgate Medical Clinic", ["220 Westgate Blvd"]),
    ("1201", "Summit Fitness", ["5 Ridge Ave", "640 Kingsway"]),
    ("1239", "Bluewater Hotel", ["88 Shore Dr"]),
    ("1264", "Oakridge School Board", ["14 Oak St", "92 Pine St", "3 Birch Cres"]),
]
SERVICES = ["4yd bin", "6yd bin", "8yd bin", "20yd roll-off"]
DRIVERS = ["DK", "MJ", "RS", "TL"]


def pickups_for_month(year, month, rng):
    rows = []
    n = 1
    for acct, name, sites in CUSTOMERS:
        for i, addr in enumerate(sites):
            weekday = rng.randint(0, 4)
            d = date(year, month, 1)
            while d.weekday() != weekday:
                d += timedelta(days=1)
            service = rng.choice(SERVICES)
            while d.month == month:
                rows.append({
                    "pickup_id": f"P{year}{month:02d}-{n:04d}",
                    "date": d.isoformat(),
                    "account_id": acct,
                    "customer_name": name,
                    "site_id": f"{acct}-{i + 1}",
                    "site_address": addr,
                    "service": service,
                    "status": "completed",
                    "extras_recorded": "",
                })
                n += 1
                d += timedelta(days=7)
    return rows


def ticket_text(p, rng, extra_bins=0, contamination=None, serviced=True,
                address=None, date_override=None, illegible=False):
    d = date.fromisoformat(date_override or p["date"])
    date_str = rng.choice([d.strftime("%b %d"), d.strftime("%d/%m"), d.strftime("%m-%d-%y"), d.strftime("%d %b")])
    addr = address or p["site_address"]
    addr = rng.choice([addr, addr.replace("Street", "St").replace("Avenue", "Ave"), addr.lower()])
    lines = [
        rng.choice(["RIDGELINE WASTE - DRIVER TICKET", "Ridgeline ticket", "TICKET"]),
        f"{rng.choice(['Acct', 'acct #', 'A/C'])} {p['account_id']}",
        f"{rng.choice(['Date', 'dt', ''])} {date_str}".strip(),
        f"{rng.choice(['Site', 'addr', 'loc'])}: {addr}",
        f"Unit: {p['service']}",
    ]
    if not serviced:
        lines.append(rng.choice(["NOT SERVICED - gate locked", "no access, bin blocked by car", "skip - closed"]))
    else:
        lines.append(rng.choice(["dumped ok", "serviced", "done"]))
    if extra_bins:
        lines.append(rng.choice([f"+{extra_bins} xtra bins", f"{extra_bins} extra bin(s) on side", f"extras: {extra_bins} bags/bins"]))
    if contamination:
        lines.append(rng.choice([f"CONTAM - {contamination}", f"contaminated: {contamination}", f"contam ({contamination}) photo taken"]))
    lines.append(f"Drv {rng.choice(DRIVERS)}")
    text = "\n".join(lines)
    if illegible:
        text = "".join(c if rng.random() > 0.45 else rng.choice("~#?.,") for c in text)
    return text + "\n"


def build_month(year, month, seed):
    rng = random.Random(seed)
    pickups = pickups_for_month(year, month, rng)
    tickets = {}   # filename -> text
    expected = []

    pool = pickups[:]
    rng.shuffle(pool)
    picks = iter(pool)

    def plant(kind, p, **detail):
        expected.append({"flag": kind, "pickup_id": p.get("pickup_id"), "account_id": p["account_id"],
                         "date": p["date"], **detail})

    special = {}
    for _ in range(4):
        p = next(picks); special[p["pickup_id"]] = ("extra", rng.randint(1, 3))
    for note in ["drywall", "paint cans", "construction debris"]:
        p = next(picks); special[p["pickup_id"]] = ("contam", note)
    for _ in range(2):
        p = next(picks); special[p["pickup_id"]] = ("missing", None)
    p = next(picks); special[p["pickup_id"]] = ("address", None)
    p = next(picks); special[p["pickup_id"]] = ("dispute", None)
    p = next(picks); special[p["pickup_id"]] = ("duplicate", None)
    p = next(picks); special[p["pickup_id"]] = ("illegible", None)
    p = next(picks); special[p["pickup_id"]] = ("already_billed", rng.randint(1, 2))

    for p in pickups:
        kind, val = special.get(p["pickup_id"], (None, None))
        fname = f"ticket_{p['pickup_id']}.txt"
        if kind == "missing":
            plant("missing_ticket", p)
            continue
        if kind == "extra":
            tickets[fname] = ticket_text(p, rng, extra_bins=val)
            plant("unbilled_extra", p, extra_bins=val)
        elif kind == "contam":
            tickets[fname] = ticket_text(p, rng, contamination=val)
            plant("unbilled_contamination", p, note=val)
        elif kind == "address":
            other = rng.choice([s for c in CUSTOMERS for s in c[2] if s != p["site_address"]])
            tickets[fname] = ticket_text(p, rng, address=other)
            plant("address_mismatch", p, ticket_address=other)
        elif kind == "dispute":
            tickets[fname] = ticket_text(p, rng, serviced=False)
            plant("service_dispute", p)
        elif kind == "duplicate":
            tickets[fname] = ticket_text(p, rng)
            tickets[f"ticket_{p['pickup_id']}_copy.txt"] = ticket_text(p, rng)
            plant("duplicate_ticket", p)
        elif kind == "illegible":
            tickets[fname] = ticket_text(p, rng, illegible=True)
            plant("needs_human_read", p)
        elif kind == "already_billed":
            p["extras_recorded"] = f"{val} extra bin"
            tickets[fname] = ticket_text(p, rng, extra_bins=val)   # no flag: already in dispatch
        else:
            tickets[fname] = ticket_text(p, rng)

    # One ticket with no scheduled pickup (unscheduled job)
    acct, name, sites = rng.choice(CUSTOMERS)
    ghost = {"pickup_id": None, "account_id": acct, "site_address": sites[0], "service": "6yd bin",
             "date": date(year, month, 26).isoformat()}
    tickets[f"ticket_unscheduled_{acct}.txt"] = ticket_text(ghost, rng)
    plant("unmatched_ticket", ghost)

    month_dir = ROOT / "inputs" / f"{year}-{month:02d}"
    tdir = month_dir / "tickets"
    tdir.mkdir(parents=True, exist_ok=True)
    with open(month_dir / "dispatch_export.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(pickups[0].keys()))
        w.writeheader(); w.writerows(pickups)
    for fname, text in tickets.items():
        (tdir / fname).write_text(text)

    fx = ROOT / "tests" / "fixtures" / f"{year}-{month:02d}"
    fx.mkdir(parents=True, exist_ok=True)
    (fx / "expected_issues.json").write_text(json.dumps(expected, indent=2))
    print(f"{year}-{month:02d}: {len(pickups)} pickups, {len(tickets)} tickets, {len(expected)} planted issues")


if __name__ == "__main__":
    build_month(2026, 10, seed=10)
    build_month(2026, 11, seed=11)
