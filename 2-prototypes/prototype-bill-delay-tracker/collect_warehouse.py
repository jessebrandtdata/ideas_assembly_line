#!/usr/bin/env python3
"""Read bill text versions and CRS summaries from the spicy-regs warehouse, one folder per Congress.

The only collector: no API key, no per-bill API calls. The warehouse (Civic Tech DC's spicy-regs,
Parquet on data.spicygov.ai) reads GovInfo nightly and publishes immutable generations; this script
reads the current one and writes, for each Congress asked for, under <data-dir>/<congress>/:

  versions.csv   one row per bill text version  (bill_versions, titled from congress_bills, sized from
                 bill_sections: sections and characters; pages once the warehouse publishes a page count)
  summaries.csv  one row per CRS summary version (bill_publisher_summaries, revisions folded)
  warehouse.json which generation was read, and when it was published

--congress takes numbers, ranges (113-119), "current", "previous" or "all" (every Congress the
warehouse lists). Without it the script refreshes every Congress already under --data-dir plus the
current one, which is how a scheduled run moves on to a new Congress in January by itself. A
Congress the warehouse has no text versions for yet is skipped, and one already on disk is left as
it was rather than emptied.

Since its 2026-11-06 generation the warehouse keeps every dated revision of a summary as its
own row, so a summary's first publication is the earliest retained update_date. That is what
this script writes as last_summary_update_date, the column delays.py measures to; update_date
carries the latest revision, as the Congress.gov field did. Summaries first captured before that
generation carry only their latest revision, which for an old Congress can be a re-publication
years after the summary first appeared.

The warehouse has no page count and no GovInfo ingest date (2026-11-09). The proposal asks for pages,
so the page column is read from bill_versions as soon as it carries one; until then the dashboard
sizes bills in characters or sections, and lags start at the printed date.

Needs duckdb (`python3 -m pip install duckdb`): Parquet has no stdlib reader. Everything
else is stdlib. --source is the warehouse host or a local directory holding
publication.v2.json and the generation files, which is how the test runs offline.
"""
import argparse
import csv
import json
import sys
import urllib.request
from collections import defaultdict
from datetime import date
from pathlib import Path

from congress import BILL_TYPES, congress_dirs, parse_congresses

try:
    import duckdb
except ImportError:  # pragma: no cover - the message is the point
    sys.exit("collect_warehouse.py needs duckdb to read Parquet: python3 -m pip install duckdb")

SOURCE = "https://data.spicygov.ai"
POINTER = "publication.v2.json"
FAMILY = "bill-family"
UA = "bill-delay-tracker prototype (civic tech dc)"

VERSION_FIELDS = ["package_id", "congress", "bill_type", "number", "version", "date_issued", "title",
                  "pages", "sections", "characters"]
SUMMARY_FIELDS = ["congress", "bill_type", "number", "version_code", "action_desc", "action_date",
                  "update_date", "current_chapter", "last_summary_update_date"]


def write_csv(path, rows, fields):
    """Write beside the file and rename over it, so a stopped run never leaves a truncated file."""
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


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


def sql_list(values):
    """A SQL IN list of string literals. The values are Congress numbers and bill-type codes this
    script parsed itself, never free text."""
    return ", ".join(f"'{v}'" for v in values)


def warehouse_congresses(con, prefix):
    """Every Congress the generation has text versions for."""
    rows = con.execute(f"""
        SELECT DISTINCT split_part(bill_id, '-', 1) FROM read_parquet('{prefix}/bill_versions.parquet')
        WHERE package_id IS NOT NULL""").fetchall()
    return sorted(int(c) for (c,) in rows if c.isdigit())


def table_files(entry, prefix, name, congresses):
    """The Parquet files of one table, as a SQL list literal. A table the pointer lists as partitioned by Congress
    (bill_sections is, one member per Congress) is read from the members for the Congresses asked for only; any other
    table is the one file <prefix>/<name>. None when a partitioned table has no member for those Congresses."""
    members = (entry.get("tables") or {}).get(name, {}).get("members")
    if not members:
        return f"['{prefix}/{name}']"
    keys = [m["key"] for m in members if str(m.get("partition", {}).get("congress")) in {str(c) for c in congresses}]
    return "[" + ", ".join(f"'{prefix}/{k}'" for k in keys) + "]" if keys else None


def columns_of(con, files):
    return {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet({files})").fetchall()}


def versions_rows(con, prefix, entry, congresses, bill_types):
    """One row per GovInfo text package, for every Congress asked for. Rows without a package_id (public and private
    laws are listed, not printed) are not text versions and are skipped. The version code is the package id's suffix
    (ih, rh, eas2), the same spelling GovInfo uses, read off the id rather than the warehouse's slug. date_issued is the
    publisher's version date, the date printed on the bill (empty for a few hundred printings per Congress).

    Size of the printing, from the warehouse alone: sections and characters count and add up its rows in bill_sections
    (the parsed bill text; empty where the warehouse has not parsed that printing, most of the 108th Congress), and
    pages is bill_versions' own page count if the warehouse ever publishes one, empty until then."""
    versions_file = table_files(entry, prefix, "bill_versions.parquet", congresses)
    pages = "max(v.pages)" if "pages" in columns_of(con, versions_file) else "NULL"
    sections_files = table_files(entry, prefix, "bill_sections.parquet", congresses)
    sections = (f"""SELECT bill_id, printing_id, count(*) AS sections, sum(body_chars) AS characters
                    FROM read_parquet({sections_files}) GROUP BY ALL""" if sections_files
                else "SELECT NULL::VARCHAR AS bill_id, NULL::VARCHAR AS printing_id, NULL AS sections, NULL AS characters")
    rows = con.execute(f"""
        WITH v AS (
            SELECT *, split_part(bill_id, '-', 1) AS congress,
                   split_part(bill_id, '-', 2) AS bill_type,
                   split_part(bill_id, '-', 3) AS number
            FROM read_parquet({versions_file})
            WHERE package_id IS NOT NULL AND split_part(bill_id, '-', 1) IN ({sql_list(congresses)})
        ),
        b AS (
            SELECT bill_id, title FROM read_parquet({table_files(entry, prefix, "congress_bills.parquet", congresses)})
            WHERE split_part(bill_id, '-', 1) IN ({sql_list(congresses)})
        ),
        s AS ({sections})
        SELECT v.package_id, v.congress, v.bill_type, v.number, min(v.version_date) AS version_date,
               COALESCE(max(b.title), '') AS title, {pages} AS pages, max(s.sections) AS sections,
               max(s.characters) AS characters
        FROM v LEFT JOIN b USING (bill_id) LEFT JOIN s USING (bill_id, printing_id)
        WHERE v.bill_type IN ({sql_list(bill_types)})
        GROUP BY v.package_id, v.congress, v.bill_type, v.number
        ORDER BY v.congress, version_date DESC, v.package_id
    """).fetchall()
    out = []
    as_text = lambda n: "" if n is None else str(int(n))  # noqa: E731
    for package_id, congress, bill_type, number, version_date, title, pg, sec, chars in rows:
        suffix = package_id.split("-", 1)[1][len(congress) + len(bill_type) + len(number):]
        out.append({"package_id": package_id, "congress": congress, "bill_type": bill_type, "number": number,
                    "version": suffix, "date_issued": (version_date or "")[:10], "title": title,
                    "pages": as_text(pg), "sections": as_text(sec), "characters": as_text(chars)})
    return out


def summaries_rows(con, prefix, congresses, bill_types):
    """One row per CRS summary version, from the warehouse's retained revisions:
    last_summary_update_date is the earliest retained update_date (the first publication, what
    delays.py measures to) and update_date the latest (the current revision). action_date and
    action_desc are the publisher's for that summary version; a bill restating the same summary
    version under two action dates keeps both, as the warehouse does."""
    rows = con.execute(f"""
        SELECT split_part(bill_id, '-', 1) AS congress,
               split_part(bill_id, '-', 2) AS bill_type, split_part(bill_id, '-', 3) AS number,
               summary_version_code, action_desc, action_date,
               max(update_date) AS update_date, min(update_date) AS first_update_date
        FROM read_parquet('{prefix}/bill_publisher_summaries.parquet')
        WHERE split_part(bill_id, '-', 1) IN ({sql_list(congresses)})
          AND split_part(bill_id, '-', 2) IN ({sql_list(bill_types)})
        GROUP BY ALL
        ORDER BY congress, first_update_date DESC, bill_type, number, summary_version_code
    """).fetchall()
    return [{"congress": c, "bill_type": bt, "number": num, "version_code": code, "action_desc": desc or "",
             "action_date": action_date or "", "update_date": update_date or "", "current_chapter": "",
             "last_summary_update_date": first or ""}
            for c, bt, num, code, desc, action_date, update_date, first in rows]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--congress", help="numbers, ranges (113-119), current, previous or all; "
                                       "default: every Congress under --data-dir plus the current one")
    ap.add_argument("--bill-types", default="all",
                    help=f"comma-separated GovInfo bill types, or 'all' (default: {','.join(BILL_TYPES)})")
    ap.add_argument("--data-dir", type=Path, default=Path(__file__).parent / "data",
                    help="root folder; each Congress is written to <data-dir>/<congress>/")
    ap.add_argument("--source", default=SOURCE, help="warehouse host, or a local directory with publication.v2.json")
    a = ap.parse_args()
    bill_types = (list(BILL_TYPES) if a.bill_types == "all"
                  else [t.strip() for t in a.bill_types.split(",") if t.strip()])
    unknown = sorted(set(bill_types) - set(BILL_TYPES))
    if unknown:
        ap.error(f"unknown bill types: {', '.join(unknown)} (known: {', '.join(BILL_TYPES)})")
    today = date.today()

    pointer = read_pointer(a.source)
    prefix, entry = generation(pointer, a.source)
    print(f"warehouse: {FAMILY} generation published {entry.get('publishedAt', '?')} at {prefix}", file=sys.stderr)
    con = connect(a.source)
    try:
        if a.congress:
            available = warehouse_congresses(con, prefix) if "all" in a.congress.lower() else None
            try:
                congresses = parse_congresses(a.congress, today, available)
            except ValueError as e:
                ap.error(str(e))
        else:
            congresses = parse_congresses(",".join(["current", *map(str, congress_dirs(a.data_dir))]), today)
        names = [str(n) for n in congresses]
        versions = versions_rows(con, prefix, entry, names, bill_types)
        summaries = summaries_rows(con, prefix, names, bill_types)
    finally:
        con.close()

    by_congress = defaultdict(lambda: ([], []))
    for v in versions:
        by_congress[v["congress"]][0].append(v)
    for s in summaries:
        by_congress[s["congress"]][1].append(s)
    for congress in names:
        vs, ss = by_congress.get(congress, ([], []))
        out = a.data_dir / congress
        if not vs:
            kept = " (the folder on disk is left as it was)" if out.is_dir() else ""
            print(f"{congress}: the warehouse lists no text versions yet; skipped{kept}", file=sys.stderr)
            continue
        out.mkdir(parents=True, exist_ok=True)
        write_csv(out / "versions.csv", vs, VERSION_FIELDS)
        write_csv(out / "summaries.csv", ss, SUMMARY_FIELDS)
        revised = sum(1 for s in ss if s["update_date"] != s["last_summary_update_date"])
        (out / "warehouse.json").write_text(json.dumps({
            "source": a.source, "family": FAMILY, "prefix": entry.get("prefix"),
            "published_at": entry.get("publishedAt"), "artifact_digest": entry.get("artifactDigest"),
            "congress": congress, "bill_types": bill_types,
            "versions": len(vs), "summaries": len(ss), "summaries_with_retained_revisions": revised,
        }, indent=1) + "\n")
        print(f"{congress}: {len(vs)} text packages; {len(ss)} summaries "
              f"({revised} with an earlier retained revision)", file=sys.stderr)


if __name__ == "__main__":
    main()
