#!/usr/bin/env python3
"""Join text versions with CRS summaries and compute summary lag per bill and stage.

Reads versions.csv, pages.csv, summaries.csv from --data-dir; writes delays.csv,
awaiting.csv and stats.json there. Stdlib only.

Lag definition (the honest one the data allows): summary.update_date minus
version.date_issued, matched by stage (introduced / reported / passed / enrolled).
The API exposes no "first published" date for a summary, only its last update,
so a summary CRS revised later reads as a longer lag than the user actually
waited. date_issued is the date printed on the version, not the day GPO posted it.
"""
import argparse
import csv
import json
import statistics
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

VERSION_STAGE = {"ih": "introduced", "is": "introduced", "rh": "reported", "rs": "reported",
                 "eh": "passed", "es": "passed", "eah": "passed", "eas": "passed", "enr": "enrolled"}
STAGE_ORDER = ["introduced", "reported", "passed", "enrolled"]


def summary_stage(action_desc):
    d = action_desc.lower()
    if d.startswith("introduced"):
        return "introduced"
    if d.startswith("reported"):
        return "reported"
    if d.startswith("passed"):
        return "passed"
    if d.startswith("public law") or d.startswith("enrolled"):
        return "enrolled"
    return None


def read_csv(path):
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fields):
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def to_date(s):
    return date.fromisoformat(s[:10]) if s else None


def histogram(values, edges):
    """Counts per bin; the last bin is open-ended."""
    bins = []
    for i, lo in enumerate(edges):
        hi = edges[i + 1] if i + 1 < len(edges) else None
        n = sum(1 for v in values if v >= lo and (hi is None or v < hi))
        bins.append({"from": lo, "to": hi, "count": n})
    return bins


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", type=Path, default=Path(__file__).parent / "data")
    ap.add_argument("--as-of", default=date.today().isoformat(), help="date used for 'awaiting' ages")
    a = ap.parse_args()
    as_of = date.fromisoformat(a.as_of)

    versions = read_csv(a.data_dir / "versions.csv")
    pages = {r["package_id"]: int(r["pages"]) for r in read_csv(a.data_dir / "pages.csv") if r["pages"].isdigit()}
    summaries = read_csv(a.data_dir / "summaries.csv")

    # earliest text version per (bill, stage)
    text = {}
    bills_with_text = set()
    reported = set()
    for v in versions:
        bill = (v["bill_type"], v["number"])
        bills_with_text.add(bill)
        if v["version"] in ("rh", "rs"):
            reported.add(bill)
        stage = VERSION_STAGE.get(v["version"])
        if not stage:
            continue
        k = bill + (stage,)
        if k not in text or v["date_issued"] < text[k]["date_issued"]:
            text[k] = v

    # earliest summary update per (bill, stage)
    summ = {}
    bills_summarized = set()
    for s in summaries:
        stage = summary_stage(s["action_desc"])
        if not stage:
            continue
        bill = (s["bill_type"], s["number"])
        bills_summarized.add(bill)
        k = bill + (stage,)
        if k not in summ or s["update_date"] < summ[k]["update_date"]:
            summ[k] = s

    delays = []
    for k, v in sorted(text.items()):
        s = summ.get(k)
        if not s:
            continue
        td, sd = to_date(v["date_issued"]), to_date(s["update_date"])
        delays.append({"bill_type": k[0], "number": k[1], "stage": k[2], "package_id": v["package_id"],
                       "text_date": td.isoformat(), "summary_date": sd.isoformat(),
                       "delay_days": (sd - td).days, "pages": pages.get(v["package_id"], ""),
                       "title": v["title"]})
    write_csv(a.data_dir / "delays.csv", delays,
              ["bill_type", "number", "stage", "package_id", "text_date", "summary_date", "delay_days", "pages", "title"])

    awaiting = []
    for k, v in sorted(text.items()):
        if k[2] == "introduced" and k not in summ:
            td = to_date(v["date_issued"])
            awaiting.append({"bill_type": k[0], "number": k[1], "package_id": v["package_id"],
                             "text_date": td.isoformat(), "age_days": (as_of - td).days,
                             "pages": pages.get(v["package_id"], ""), "title": v["title"]})
    awaiting.sort(key=lambda r: -r["age_days"])
    write_csv(a.data_dir / "awaiting.csv", awaiting,
              ["bill_type", "number", "package_id", "text_date", "age_days", "pages", "title"])

    by_stage = defaultdict(list)
    for d in delays:
        by_stage[d["stage"]].append(d["delay_days"])
    stage_stats = {}
    for stage in STAGE_ORDER:
        xs = by_stage.get(stage, [])
        if xs:
            stage_stats[stage] = {"n": len(xs), "mean": round(statistics.mean(xs), 1),
                                  "median": statistics.median(xs), "max": max(xs), "min": min(xs)}
    all_delays = [d["delay_days"] for d in delays]
    intro = by_stage.get("introduced", [])
    known_pages = [pages[v["package_id"]] for v in versions if v["package_id"] in pages]
    stats = {
        "as_of": as_of.isoformat(),
        "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "congress": versions[0]["congress"] if versions else None,
        "bills_with_text": len(bills_with_text),
        "text_versions": len(versions),
        "bills_summarized": len(bills_summarized),
        "bills_reported_by_committee": len(reported),
        "introduced_with_summary": len(intro),
        "introduced_awaiting_summary": len(awaiting),
        "pages": {"versions_with_count": len(known_pages), "versions_total": len(versions),
                  "total": sum(known_pages), "mean": round(statistics.mean(known_pages), 1) if known_pages else None},
        "delay_days": {"n": len(all_delays), "mean": round(statistics.mean(all_delays), 1) if all_delays else None,
                       "median": statistics.median(all_delays) if all_delays else None,
                       "max": max(all_delays) if all_delays else None},
        "by_stage": stage_stats,
        "introduced_histogram": histogram(intro, [0, 7, 14, 30, 60, 90, 180, 365]),
        "awaiting_histogram": histogram([r["age_days"] for r in awaiting], [0, 7, 14, 30, 60, 90, 180, 365]),
        "summaries_collected": len(summaries),
        "caveats": [
            "delay = summary last-update date minus the date printed on the text version; the API has no first-published date for summaries, so revised summaries overstate the lag",
            "'awaiting' means no introduced-stage summary appears in the summaries collected so far; a partial summaries sweep inflates it",
            "page counts come from GovInfo package summaries, one call per version, and may cover only a sample",
        ],
    }
    (a.data_dir / "stats.json").write_text(json.dumps(stats, indent=1) + "\n")
    print(json.dumps({k: stats[k] for k in ("bills_with_text", "bills_summarized", "introduced_with_summary",
                                             "introduced_awaiting_summary", "delay_days", "by_stage")}, indent=1))


if __name__ == "__main__":
    main()
