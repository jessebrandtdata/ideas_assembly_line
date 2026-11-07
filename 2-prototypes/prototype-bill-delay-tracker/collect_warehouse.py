#!/usr/bin/env python3
"""Read bill text versions and CRS summaries from the spicy-regs warehouse for one Congress.

Replaces collect.py's two API sweeps (the GovInfo BILLS listing and the Congress.gov
/summaries list). The warehouse (Civic Tech DC's spicy-regs, Parquet on data.spicygov.ai)
reads GovInfo BILLSTATUS nightly and publishes immutable generations; this script reads the
current one and writes the same two files collect.py wrote, so delays.py runs unchanged:

  versions.csv   one row per bill text version  (bill_versions, titled from congress_bills)
  summaries.csv  one row per CRS summary version (bill_publisher_summaries, revisions folded)
  warehouse.json which generation was read, and when it was published

Since its 2026-11-06 generation the warehouse keeps every dated revision of a summary as its
own row, so a summary's first publication is the earliest retained update_date. That is what
this script writes as last_summary_update_date, the column delays.py measures to; update_date
carries the latest revision, as the Congress.gov field did.

Not here: pages.csv and ingest.csv. The warehouse has neither a page count nor GovInfo's
dateIngested, so those stay with collect.py (`collect.py --skip versions summaries`), which
fetches them once per new package_id and caches them.

Needs duckdb (`python3 -m pip install duckdb`): Parquet has no stdlib reader. Everything
else is stdlib. --source is the warehouse host or a local directory holding
publication.v2.json and the generation files, which is how the test runs offline.
"""
import argparse
import csv
import json
import sys
import urllib.request
from pathlib import Path

try:
    import duckdb
except ImportError:  # pragma: no cover - the message is the point
    sys.exit("collect_warehouse.py needs duckdb to read Parquet: python3 -m pip install duckdb")

SOURCE = "https://data.spicygov.ai"
POINTER = "publication.v2.json"
FAMILY = "bill-family"
BILL_TYPES = ["hr", "s", "hjres", "sjres"]
UA = "bill-delay-tracker prototype (civic tech dc)"

VERSION_FIELDS = ["package_id", "congress", "bill_type", "number", "version", "date_issued", "last_modified", "title"]
SUMMARY_FIELDS = ["congress", "bill_type", "number", "version_code", "action_desc", "action_date",
                  "update_date", "current_chapter", "last_summary_update_date"]


def write_csv(path, rows, fields):
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def is_url(source):
    return source.startswith("http://") or source.startswith("https://")


def read_pointer(source):
    """The publication index: a URL under the host, or a file in the local source directory."""
    if is_url(source):
        req = urllib.request.Request(f"{source.rstrip('/')}/{POINTER}", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    return json.loads((Path(source) / POINTER).read_text())


def generation(pointer, source):
    """(prefix of the current bill-family generation, its entry) with the prefix made absolute."""
    entry = pointer["families"][FAMILY]
    prefix = entry["prefix"].strip("/")
    base = source.rstrip("/") if is_url(source) else str(Path(source).resolve())
    return f"{base}/{prefix}", entry


def connect(source):
    con = duckdb.connect()
    if is_url(source):
        con.execute("INSTALL httpfs; LOAD httpfs;")
    return con


def versions_rows(con, prefix, congress, bill_types):
    """One row per GovInfo text package, in collect.py's shape. Rows without a package_id (public and
    private laws are listed, not printed) are not text versions and are skipped. The version code
    is the package id's suffix (ih, rh, eas2), the same spelling GovInfo uses, read off the id rather
    than the warehouse's slug so the two collectors agree. date_issued is the publisher's version
    date, the date printed on the bill; last_modified has no warehouse counterpart and is left empty."""
    types = ", ".join(f"'{t}'" for t in bill_types)
    rows = con.execute(f"""
        WITH v AS (
            SELECT bill_id, package_id, version_date,
                   split_part(bill_id, '-', 2) AS bill_type,
                   split_part(bill_id, '-', 3) AS number
            FROM read_parquet('{prefix}/bill_versions.parquet')
            WHERE package_id IS NOT NULL AND split_part(bill_id, '-', 1) = '{congress}'
        ),
        b AS (
            SELECT bill_id, title FROM read_parquet('{prefix}/congress_bills.parquet')
            WHERE split_part(bill_id, '-', 1) = '{congress}'
        )
        SELECT DISTINCT v.package_id, v.bill_type, v.number, v.version_date, COALESCE(b.title, '') AS title
        FROM v LEFT JOIN b USING (bill_id)
        WHERE v.bill_type IN ({types})
        ORDER BY v.version_date DESC, v.package_id
    """).fetchall()
    out = []
    for package_id, bill_type, number, version_date, title in rows:
        suffix = package_id.split("-", 1)[1][3 + len(bill_type) + len(number):]
        out.append({"package_id": package_id, "congress": congress, "bill_type": bill_type, "number": number,
                    "version": suffix, "date_issued": (version_date or "")[:10], "last_modified": "",
                    "title": title})
    return out


def summaries_rows(con, prefix, congress, bill_types):
    """One row per CRS summary version, in collect.py's shape, from the warehouse's retained revisions:
    last_summary_update_date is the earliest retained update_date (the first publication, what
    delays.py measures to) and update_date the latest (the current revision). action_date and
    action_desc are the publisher's for that summary version; a bill restating the same summary
    version under two action dates keeps both, as the warehouse does."""
    types = ", ".join(f"'{t}'" for t in bill_types)
    rows = con.execute(f"""
        SELECT split_part(bill_id, '-', 2) AS bill_type, split_part(bill_id, '-', 3) AS number,
               summary_version_code, action_desc, action_date,
               max(update_date) AS update_date, min(update_date) AS first_update_date
        FROM read_parquet('{prefix}/bill_publisher_summaries.parquet')
        WHERE split_part(bill_id, '-', 1) = '{congress}' AND split_part(bill_id, '-', 2) IN ({types})
        GROUP BY ALL
        ORDER BY first_update_date DESC, bill_type, number, summary_version_code
    """).fetchall()
    return [{"congress": congress, "bill_type": bt, "number": num, "version_code": code, "action_desc": desc or "",
             "action_date": action_date or "", "update_date": update_date or "", "current_chapter": "",
             "last_summary_update_date": first or ""}
            for bt, num, code, desc, action_date, update_date, first in rows]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--congress", default="119")
    ap.add_argument("--bill-types", default=",".join(BILL_TYPES),
                    help="comma-separated GovInfo bill types, or 'all' for every type the warehouse lists")
    ap.add_argument("--data-dir", type=Path, default=Path(__file__).parent / "data")
    ap.add_argument("--source", default=SOURCE, help="warehouse host, or a local directory with publication.v2.json")
    a = ap.parse_args()
    bill_types = (["hr", "s", "hjres", "sjres", "hres", "sres", "hconres", "sconres"] if a.bill_types == "all"
                  else [t.strip() for t in a.bill_types.split(",") if t.strip()])
    a.data_dir.mkdir(parents=True, exist_ok=True)

    pointer = read_pointer(a.source)
    prefix, entry = generation(pointer, a.source)
    print(f"warehouse: {FAMILY} generation published {entry.get('publishedAt', '?')} at {prefix}", file=sys.stderr)
    con = connect(a.source)
    try:
        versions = versions_rows(con, prefix, a.congress, bill_types)
        summaries = summaries_rows(con, prefix, a.congress, bill_types)
    finally:
        con.close()
    write_csv(a.data_dir / "versions.csv", versions, VERSION_FIELDS)
    write_csv(a.data_dir / "summaries.csv", summaries, SUMMARY_FIELDS)
    revised = sum(1 for s in summaries if s["update_date"] != s["last_summary_update_date"])
    (a.data_dir / "warehouse.json").write_text(json.dumps({
        "source": a.source, "family": FAMILY, "prefix": entry.get("prefix"),
        "published_at": entry.get("publishedAt"), "artifact_digest": entry.get("artifactDigest"),
        "congress": a.congress, "bill_types": bill_types,
        "versions": len(versions), "summaries": len(summaries), "summaries_with_retained_revisions": revised,
    }, indent=1) + "\n")
    print(f"versions: {len(versions)} text packages; summaries: {len(summaries)} "
          f"({revised} with an earlier retained revision)", file=sys.stderr)


if __name__ == "__main__":
    main()
