"""Which Congress a date falls in, the bill types, and the --congress option shared by the scripts.

Nothing here names a particular Congress: the current one is computed from the date, so the
scripts move to the 120th on 2027-01-03 without an edit. Since the Twentieth Amendment (the 74th
Congress, 1935) every Congress begins on January 3 of an odd year, which is the only rule used.
Stdlib only.
"""
from datetime import date
from pathlib import Path

# Every type GovInfo's BILLS collection and the Congress.gov API list, bills first, then joint,
# concurrent and simple resolutions. The order is the order the dashboard offers them in.
BILL_TYPES = ("hr", "s", "hjres", "sjres", "hconres", "sconres", "hres", "sres")

FIRST_JANUARY_THIRD = 74  # the first Congress that began on January 3 (1935)


def congress_start(n):
    """First day of the nth Congress: January 3 of 1789 + 2(n-1)."""
    n = int(n)
    if n < FIRST_JANUARY_THIRD:
        raise ValueError(f"the {n}th Congress began before the January 3 rule (74th Congress, 1935)")
    return date(1789 + 2 * (n - 1), 1, 3)


def congress_end(n):
    """Last day of the nth Congress, the day before the next one begins."""
    return date.fromordinal(congress_start(int(n) + 1).toordinal() - 1)


def congress_on(day):
    """The Congress in session on a date. January 1 and 2 of an odd year still belong to the outgoing one."""
    year = day.year if (day.month, day.day) >= (1, 3) else day.year - 1
    n = (year - 1789) // 2 + 1
    if n < FIRST_JANUARY_THIRD:
        raise ValueError(f"{day} is before the January 3 rule (74th Congress, 1935)")
    return n


def congress_dirs(root):
    """Congress numbers that already have a data folder under root (folders named by number)."""
    root = Path(root)
    if not root.is_dir():
        return []
    return sorted(int(p.name) for p in root.iterdir() if p.is_dir() and p.name.isdigit())


def parse_congresses(spec, today, available=None):
    """The Congress numbers a --congress value names, newest first.

    spec is a comma-separated list of: a number (119), a range (113-119), "current" (the Congress in
    session on today), "previous" (the one before it), or "all" (every Congress in available, which the
    caller must supply; the API collector has no listing to supply it from)."""
    current = congress_on(today)
    out = set()
    for token in (t.strip().lower() for t in str(spec).split(",")):
        if not token:
            continue
        if token == "current":
            out.add(current)
        elif token == "previous":
            out.add(current - 1)
        elif token == "all":
            if available is None:
                raise ValueError("'all' needs a source that lists its Congresses")
            out.update(int(n) for n in available)
        elif "-" in token:
            lo, hi = (int(x) for x in token.split("-", 1))
            if lo > hi:
                raise ValueError(f"range {token} runs backwards")
            out.update(range(lo, hi + 1))
        elif token.isdigit():
            out.add(int(token))
        else:
            raise ValueError(f"not a Congress: {token!r}")
    if not out:
        raise ValueError("no Congress named")
    for n in out:
        congress_start(n)  # rejects numbers before the 74th
    return sorted(out, reverse=True)
