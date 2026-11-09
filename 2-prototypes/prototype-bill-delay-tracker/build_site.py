#!/usr/bin/env python3
"""Assemble the static site the Pages workflow publishes: the dashboard and the data it reads.

  python3 build_site.py --out _site

copies dashboard/{index.html,dashboard.js,metrics.js} to <out>/dashboard/, and from data/ the
index (congresses.js, congresses.json) plus, for every Congress the index lists, its delays.js
(what the page loads), stats.json, delays.csv and awaiting.csv (the downloads), keeping the same
relative layout so the page's ../data/ paths resolve. <out>/index.html forwards to dashboard/.
Run delays.py first; a Congress the index lists without its delays.js is an error, not a gap.
Stdlib only. The bulk data is not committed to git: the daily workflow rebuilds it on each run.
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DASHBOARD_FILES = ("index.html", "dashboard.js", "metrics.js")
INDEX_FILES = ("congresses.js", "congresses.json")
CONGRESS_FILES = ("delays.js", "stats.json", "delays.csv", "awaiting.csv")
REDIRECT = """<!doctype html>
<meta charset="utf-8">
<title>Demo: Bill Delay Tracker</title>
<meta http-equiv="refresh" content="0; url=dashboard/">
<a href="dashboard/">Demo: Bill Delay Tracker</a>
"""


def build(data_dir, out):
    index_path = data_dir / "congresses.json"
    if not index_path.exists():
        raise SystemExit(f"{index_path} not found; run delays.py first")
    entries = json.loads(index_path.read_text())["congresses"]
    if not entries:
        raise SystemExit(f"{index_path} lists no Congress")
    if out.exists():
        shutil.rmtree(out)
    (out / "dashboard").mkdir(parents=True)
    for name in DASHBOARD_FILES:
        shutil.copy2(HERE / "dashboard" / name, out / "dashboard" / name)
    (out / "data").mkdir()
    for name in INDEX_FILES:
        shutil.copy2(data_dir / name, out / "data" / name)
    for e in entries:
        src, dst = data_dir / str(e["congress"]), out / "data" / str(e["congress"])
        dst.mkdir()
        for name in CONGRESS_FILES:
            if not (src / name).exists():
                raise SystemExit(f"{src / name} not found; run delays.py for Congress {e['congress']}")
            shutil.copy2(src / name, dst / name)
    (out / "index.html").write_text(REDIRECT)
    return len(entries)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", type=Path, default=HERE / "data")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    n = build(a.data_dir, a.out)
    size = sum(p.stat().st_size for p in a.out.rglob("*") if p.is_file())
    print(f"site: {n} Congresses, {size / 1e6:.1f} MB in {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
