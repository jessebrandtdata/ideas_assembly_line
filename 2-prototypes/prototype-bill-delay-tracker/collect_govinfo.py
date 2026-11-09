#!/usr/bin/env python3
"""Optional: page counts (and GovInfo ingest dates) for bill text versions, one GovInfo call per printing.

Proposal IV.2 counts "the total number of pages in the bills processed". The spicy-regs warehouse has
no page count (2026-11-09), so this script asks GovInfo for each printing's MODS record, which carries
both the page count (<extent>9 p.</extent>) and the day GovInfo took the text in (<dateIngested>). It
is off by default: collect_warehouse.py and delays.py run without it, and the dashboard then sizes
bills in characters or sections. Run it, or switch it on in the Pages workflow, to bring pages back;
delays.py reads the counts and the dashboard offers pages first wherever they exist. Bills with no
looked-up count are left out of page totals and counted as unmeasured, never shown as zero pages.

Writes <data-dir>/<congress>/govinfo.csv (package_id, pages, date_ingested), cached and resumable: only
printings not in it are looked up, newest first, and the --max-lookups cap is for the whole run, spent
on the newest Congress first. --cache-dir names a second home for the same file (a CI cache), merged
both ways and never replacing a row. The ingest date is kept for reference; lags start at the printed
date. For bills printed before GovInfo's predecessor was migrated the ingest date is the migration
(a 110th Congress bill reads 2010-09-21), not a posting date.

A free api.data.gov key (https://api.congress.gov/sign-up/) works for GovInfo; keys.py finds it.
DEMO_KEY works but allows about 30 requests an hour. Stdlib only.
"""
import argparse
import concurrent.futures
import csv
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

from congress import parse_congresses
from keys import load_key

GOVINFO = "https://api.govinfo.gov"
UA = "bill-delay-tracker prototype (civic tech dc)"
FIELDS = ["package_id", "pages", "date_ingested"]
SAVE_EVERY = 100


def get_text(url, key, timeout=90, retries=3):
    """The body of a GovInfo URL as text; None for a 404 or after the retries."""
    sep = "&" if "?" in url else "?"
    full = f"{url}{sep}api_key={key}"
    for attempt in range(retries):
        try:
            req = urllib.request.Request(full, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 30 * (attempt + 1)
                print(f"  429 rate limited, sleeping {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            if e.code == 404:
                return None
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            print(f"  retry {attempt + 1}/{retries} after {e}", file=sys.stderr)
            time.sleep(5)
    print(f"  gave up on {url}", file=sys.stderr)
    return None


def parse_mods(xml):
    """(pages, date_ingested) from a MODS record, each '' when absent. Pages is the number in
    <extent>N p.</extent>; the ingest date is the day part of <dateIngested>."""
    pages = re.search(r"<extent>\s*(\d+)\s*p\.?\s*</extent>", xml or "")
    ingested = re.search(r"<dateIngested[^>]*>\s*([^<]+?)\s*</dateIngested>", xml or "")
    return (pages.group(1) if pages else ""), (ingested.group(1)[:10] if ingested else "")


def read_csv(path):
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fields):
    """Write beside the file and rename over it, so a run stopped mid-write leaves the old file whole."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows({k: r.get(k, "") for k in fields} for r in rows)
    tmp.replace(path)


def merge_cache(src, dst):
    """Add to the file dst every row of the file src whose package_id it lacks; rows already in dst are kept as they
    are. A no-op when either path is None or src does not exist. Returns the number of rows added."""
    if src is None or dst is None or not src.exists():
        return 0
    rows = read_csv(dst)
    have = {r["package_id"] for r in rows}
    new = [r for r in read_csv(src) if r["package_id"] not in have]
    if new or not dst.exists():
        write_csv(dst, rows + new, FIELDS)
    return len(new)


def look_up(path, key, versions, budget, workers=4):
    """MODS lookups for the versions not yet in path, newest printing first, at most budget of them. Returns the
    number of calls made."""
    rows = read_csv(path)
    have = {r["package_id"] for r in rows}
    todo = sorted((v for v in versions if v["package_id"] not in have), key=lambda v: v["date_issued"], reverse=True)
    todo = todo[:max(0, budget)]

    def fetch(v):
        pages, ingested = parse_mods(get_text(f"{GOVINFO}/packages/{v['package_id']}/mods", key))
        return {"package_id": v["package_id"], "pages": pages, "date_ingested": ingested}

    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for row in pool.map(fetch, todo):
            rows.append(row)
            done += 1
            if done % SAVE_EVERY == 0:
                write_csv(path, rows, FIELDS)
                print(f"  {done}/{len(todo)} looked up", file=sys.stderr)
    write_csv(path, rows, FIELDS)
    missing = len({v["package_id"] for v in versions} - {r["package_id"] for r in rows})
    print(f"  {len(todo)} looked up, {missing} printings still without a lookup", file=sys.stderr)
    return len(todo)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--congress", default="current", help="numbers, ranges (113-119), current or previous (default: current)")
    ap.add_argument("--data-dir", type=Path, default=Path(__file__).parent / "data",
                    help="root folder; reads <data-dir>/<congress>/versions.csv, writes govinfo.csv beside it")
    ap.add_argument("--max-lookups", type=int, default=200, help="GovInfo calls for the whole run (default 200)")
    ap.add_argument("--cache-dir", type=Path, help="a second home for govinfo.csv (<cache-dir>/<congress>/), merged both ways")
    ap.add_argument("--api-key")
    a = ap.parse_args()
    try:
        congresses = parse_congresses(a.congress, date.today())
    except ValueError as e:
        ap.error(str(e))
    key = load_key(a.api_key)
    print(f"key: {'DEMO_KEY (slow, capped)' if key == 'DEMO_KEY' else 'real key'}", file=sys.stderr)
    left = a.max_lookups
    for congress in congresses:
        data_dir = a.data_dir / str(congress)
        versions = read_csv(data_dir / "versions.csv")
        if not versions:
            print(f"congress {congress}: no versions.csv; run collect_warehouse.py first", file=sys.stderr)
            continue
        path = data_dir / "govinfo.csv"
        cached = a.cache_dir / str(congress) / "govinfo.csv" if a.cache_dir else None
        merge_cache(cached, path)
        print(f"congress {congress}:", file=sys.stderr)
        left -= look_up(path, key, versions, left)
        merge_cache(path, cached)


if __name__ == "__main__":
    main()
