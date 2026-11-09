#!/usr/bin/env python3
"""Collect bill text versions (GovInfo) and CRS summaries (Congress.gov), one folder per Congress.

Writes, under --data-dir/<congress>/ (default ./data/<congress>/):
  versions.csv   one row per bill text version  (GovInfo BILLS collection listing)
  pages.csv      page count per text version    (GovInfo package summary, one call each)
  ingest.csv     day GovInfo took each version in (GovInfo MODS dateIngested, one call each)
  summaries.csv  one row per CRS summary version (Congress.gov /summaries list)

--congress takes numbers, ranges (113-119), "current" or "previous", and defaults to the current
and previous Congress, worked out from today's date: in January the new Congress starts filling
while the old one finishes. The --max-* caps are for the whole run, spent on the newest Congress
first. Every collector is incremental and resumable: rows already on disk are kept and only new
ones are fetched. Stdlib only. DEMO_KEY works but is slow and capped (~30 requests/hour), so the
--max-* knobs default low; raise them with a real key.

GovInfo's dateIngested is the day a package entered the current repository. For bills printed
before GovInfo's predecessor migrated (a 110th Congress introduced bill reads 2010-09-21) that is
the migration, not the day the text went public, so collecting ingest dates for old Congresses
measures nothing; delays.py falls back to the printed date where no ingest date was collected.
"""
import argparse
import concurrent.futures
import csv
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

from congress import BILL_TYPES, congress_start, parse_congresses
from keys import load_key

GOVINFO = "https://api.govinfo.gov"
CONGRESS = "https://api.congress.gov/v3"
UA = "bill-delay-tracker prototype (civic tech dc)"


def get_json(url, key, timeout=90, retries=3):
    sep = "&" if "?" in url else "?"
    full = f"{url}{sep}api_key={key}"
    for attempt in range(retries):
        try:
            req = urllib.request.Request(full, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
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


def get_text(url, key, timeout=90, retries=3):
    """Like get_json for a text or XML body (GovInfo MODS)."""
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


def read_csv(path):
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fields):
    """Write beside the file and rename over it, so a run stopped mid-write leaves the old file whole
    instead of a truncated cache (which the next run would read as rows still to fetch)."""
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def parse_package_id(pid):
    """BILLS-119hr10786ih -> ('119','hr','10786','ih')."""
    body = pid.split("-", 1)[1]
    k = 0
    while k < len(body) and body[k].isdigit():
        k += 1
    congress, rest = body[:k], body[k:]
    i = 0
    while i < len(rest) and rest[i].isalpha():
        i += 1
    bill_type = rest[:i]
    j = i
    while j < len(rest) and rest[j].isdigit():
        j += 1
    return congress, bill_type, rest[i:j], rest[j:]


VERSION_FIELDS = ["package_id", "congress", "bill_type", "number", "version", "date_issued", "last_modified", "title"]


def collect_versions(data_dir, key, congress, since, max_requests):
    path = data_dir / "versions.csv"
    rows = read_csv(path)
    seen = {r["package_id"] for r in rows}
    url = (f"{GOVINFO}/collections/BILLS/{since}T00:00:00Z?offsetMark=*&pageSize=500"
           f"&congress={congress}")
    n = 0
    while url and n < max_requests:
        n += 1
        page = get_json(url, key, timeout=120)
        if page is None:
            break
        pkgs = page.get("packages", [])
        new = 0
        for p in pkgs:
            pid = p["packageId"]
            if pid in seen:
                continue
            c, bt, num, ver = parse_package_id(pid)
            if bt not in BILL_TYPES:
                continue
            rows.append({"package_id": pid, "congress": c, "bill_type": bt, "number": num, "version": ver,
                         "date_issued": p.get("dateIssued", ""), "last_modified": p.get("lastModified", ""),
                         "title": p.get("title", "")})
            seen.add(pid)
            new += 1
        print(f"versions: page {n}, {len(pkgs)} packages, {new} new (total {len(rows)})", file=sys.stderr)
        write_csv(path, rows, VERSION_FIELDS)
        url = page.get("nextPage")
        if url and "api_key=" in url:
            url = url.split("api_key=")[0].rstrip("&?")
    return rows, n


def collect_pages(data_dir, key, versions, max_requests):
    path = data_dir / "pages.csv"
    rows = read_csv(path)
    have = {r["package_id"] for r in rows}
    todo = [v for v in versions if v["package_id"] not in have]
    # newest first so a capped run covers the live end of the Congress
    todo.sort(key=lambda v: v["date_issued"], reverse=True)
    for i, v in enumerate(todo[:max_requests], 1):
        s = get_json(f"{GOVINFO}/packages/{v['package_id']}/summary", key)
        pages = (s or {}).get("pages", "")
        rows.append({"package_id": v["package_id"], "pages": pages})
        if i % 100 == 0:  # resumable without rewriting the whole file after every call
            write_csv(path, rows, ["package_id", "pages"])
    print(f"pages: {min(len(todo), max_requests)} fetched, {len(todo) - min(len(todo), max_requests)} still missing",
          file=sys.stderr)
    write_csv(path, rows, ["package_id", "pages"])
    return rows, min(len(todo), max_requests)


INGEST_FIELDS = ["package_id", "date_ingested"]


def collect_ingest(data_dir, key, versions, max_requests, workers=4):
    """GovInfo's dateIssued is the date printed on the bill (for an introduced bill, the day it was
    introduced), not the day the text appeared on GovInfo. The MODS record carries dateIngested, the
    day GovInfo took the package in, and that is the publication date the lag should start from.
    One MODS call per version, newest first, written to ingest.csv as it lands; resumable."""
    path = data_dir / "ingest.csv"
    rows = read_csv(path)
    have = {r["package_id"] for r in rows}
    todo = [v for v in versions if v["package_id"] not in have]
    todo.sort(key=lambda v: v["date_issued"], reverse=True)
    todo = todo[:max_requests]

    def fetch(v):
        x = get_text(f"{GOVINFO}/packages/{v['package_id']}/mods", key)
        m = re.search(r"<dateIngested[^>]*>([^<]+)</dateIngested>", x or "")
        return {"package_id": v["package_id"], "date_ingested": m.group(1).strip()[:10] if m else ""}

    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for row in pool.map(fetch, todo):
            rows.append(row)
            done += 1
            if done % 200 == 0 or done == len(todo):
                write_csv(path, rows, INGEST_FIELDS)
                print(f"ingest: {done}/{len(todo)} fetched, {sum(1 for r in rows if not r['date_ingested'])} without a date",
                      file=sys.stderr)
    write_csv(path, rows, INGEST_FIELDS)
    print(f"ingest: {len(todo)} fetched, {len(versions) - len(rows)} still missing", file=sys.stderr)
    return rows, len(todo)


SUMMARY_FIELDS = ["congress", "bill_type", "number", "version_code", "action_desc", "action_date",
                  "update_date", "current_chapter", "last_summary_update_date"]


def collect_summaries(data_dir, key, congress, since, max_requests, page_size):
    """Sweep /summaries/{congress}/{type} newest-first. Resumable: rows on disk are a
    newest-first prefix of the API's list, so after re-reading the first page (which
    catches summaries added since) a page with nothing new jumps to the end of the prefix."""
    path = data_dir / "summaries.csv"
    rows = read_csv(path)
    seen = {(r["bill_type"], r["number"], r["version_code"]) for r in rows}
    n = 0
    for bt in BILL_TYPES:
        offset = 0
        known = sum(1 for r in rows if r["bill_type"] == bt)
        while n < max_requests:
            n += 1
            q = urllib.parse.urlencode({"format": "json", "limit": page_size, "offset": offset,
                                        "sort": "updateDate desc", "fromDateTime": f"{since}T00:00:00Z"})
            page = get_json(f"{CONGRESS}/summaries/{congress}/{bt}?{q}", key, timeout=120, retries=2)
            if page is None:
                break
            items = page.get("summaries", [])
            new = 0
            for s in items:
                b = s.get("bill", {})
                k = (b.get("type", "").lower(), str(b.get("number", "")), s.get("versionCode", ""))
                if k in seen:
                    continue
                rows.append({"congress": str(b.get("congress", congress)), "bill_type": k[0], "number": k[1],
                             "version_code": k[2], "action_desc": s.get("actionDesc", ""),
                             "action_date": s.get("actionDate", ""), "update_date": s.get("updateDate", ""),
                             "current_chapter": s.get("currentChapter", ""),
                             "last_summary_update_date": s.get("lastSummaryUpdateDate", "")})
                seen.add(k)
                new += 1
            total = (page or {}).get("pagination", {}).get("count", "?")
            print(f"summaries/{bt}: offset {offset}, {len(items)} items, {new} new, api total {total}", file=sys.stderr)
            write_csv(path, rows, SUMMARY_FIELDS)
            known += new
            if len(items) < page_size:
                break
            offset = known if new == 0 and known > offset + page_size else offset + page_size
    return rows, n


def merge_cache(src_dir, dst_dir, name, fields):
    """Add to dst_dir/name every row of src_dir/name whose package_id it lacks; existing rows are kept as they are.
    A no-op when either folder is None or the source file does not exist."""
    if src_dir is None or dst_dir is None or not (src_dir / name).exists():
        return 0
    dst = read_csv(dst_dir / name)
    have = {r["package_id"] for r in dst}
    new = [r for r in read_csv(src_dir / name) if r["package_id"] not in have]
    if new or not (dst_dir / name).exists():
        dst_dir.mkdir(parents=True, exist_ok=True)
        write_csv(dst_dir / name, dst + [{k: r.get(k, "") for k in fields} for r in new], fields)
    return len(new)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--congress", default="current,previous",
                    help="numbers, ranges (113-119), current or previous (default: current,previous)")
    ap.add_argument("--since", help="earliest lastModified / updateDate to sweep (default: the day each Congress began)")
    ap.add_argument("--data-dir", type=Path, default=Path(__file__).parent / "data",
                    help="root folder; each Congress is read from and written to <data-dir>/<congress>/")
    ap.add_argument("--api-key")
    ap.add_argument("--max-version-pages", type=int, default=3, help="GovInfo listing pages of 500")
    ap.add_argument("--max-page-lookups", type=int, default=20, help="GovInfo per-version page-count calls")
    ap.add_argument("--max-ingest-lookups", type=int, default=20, help="GovInfo per-version MODS calls (dateIngested)")
    ap.add_argument("--max-summary-requests", type=int, default=4, help="Congress.gov summary list pages")
    ap.add_argument("--summary-page-size", type=int, default=250)
    ap.add_argument("--skip", nargs="*", default=[], choices=["versions", "pages", "ingest", "summaries"])
    ap.add_argument("--cache-dir", type=Path,
                    help="a second home for pages.csv and ingest.csv (<cache-dir>/<congress>/), merged both ways: "
                         "rows found there are added before the lookups and every row is written back after, so a "
                         "CI cache carries lookups between runs without ever replacing rows already in --data-dir")
    a = ap.parse_args()
    try:
        congresses = parse_congresses(a.congress, date.today())
    except ValueError as e:
        ap.error(str(e))
    key = load_key(a.api_key)
    print(f"key: {'DEMO_KEY (slow, capped)' if key == 'DEMO_KEY' else 'real key'}", file=sys.stderr)
    # one budget per knob for the whole run, spent newest Congress first
    left = {"versions": a.max_version_pages, "pages": a.max_page_lookups, "ingest": a.max_ingest_lookups,
            "summaries": a.max_summary_requests}
    for congress in congresses:
        data_dir = a.data_dir / str(congress)
        since = a.since or congress_start(congress).isoformat()
        print(f"congress {congress} (since {since})", file=sys.stderr)
        versions = read_csv(data_dir / "versions.csv")
        if "versions" not in a.skip and left["versions"] > 0:
            data_dir.mkdir(parents=True, exist_ok=True)
            versions, used = collect_versions(data_dir, key, congress, since, left["versions"])
            left["versions"] -= used
        if not versions:
            print(f"  no text versions for Congress {congress} on disk; nothing to look up", file=sys.stderr)
            continue
        cache_dir = a.cache_dir / str(congress) if a.cache_dir else None
        if "pages" not in a.skip:
            merge_cache(cache_dir, data_dir, "pages.csv", ["package_id", "pages"])
            left["pages"] -= collect_pages(data_dir, key, versions, left["pages"])[1]
            merge_cache(data_dir, cache_dir, "pages.csv", ["package_id", "pages"])
        if "ingest" not in a.skip:
            merge_cache(cache_dir, data_dir, "ingest.csv", INGEST_FIELDS)
            left["ingest"] -= collect_ingest(data_dir, key, versions, left["ingest"])[1]
            merge_cache(data_dir, cache_dir, "ingest.csv", INGEST_FIELDS)
        if "summaries" not in a.skip and left["summaries"] > 0:
            left["summaries"] -= collect_summaries(data_dir, key, congress, since, left["summaries"],
                                                   a.summary_page_size)[1]


if __name__ == "__main__":
    main()
