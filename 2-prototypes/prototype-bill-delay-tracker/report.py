#!/usr/bin/env python3
"""Render stats.json + delays.csv + awaiting.csv into a single self-contained report.html.
Hand-rolled SVG, no dependencies, so the page can drop into the Astro site later."""
import argparse
import csv
import html
import json
from pathlib import Path

BLUE, GOLD, INK, MUTED = "#104378", "#eec05e", "#1f2933", "#6b7280"  # ctdc tokens


def esc(s):
    return html.escape(str(s))


def bar_chart(bins, title, color):
    w, h, pad, bar_w = 560, 220, 36, 56
    top = max((b["count"] for b in bins), default=1) or 1
    out = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{esc(title)}" style="max-width:100%;height:auto">']
    out.append(f'<text x="{pad}" y="18" font-size="14" font-weight="600" fill="{INK}">{esc(title)}</text>')
    for i, b in enumerate(bins):
        x = pad + i * (bar_w + 8)
        bh = round((h - 70) * b["count"] / top)
        y = h - 40 - bh
        label = f'{b["from"]}–{b["to"] - 1}' if b["to"] else f'{b["from"]}+'
        out.append(f'<rect x="{x}" y="{y}" width="{bar_w}" height="{bh}" fill="{color}" rx="3"/>')
        out.append(f'<text x="{x + bar_w / 2}" y="{y - 4}" font-size="12" text-anchor="middle" fill="{INK}">{b["count"]}</text>')
        out.append(f'<text x="{x + bar_w / 2}" y="{h - 22}" font-size="11" text-anchor="middle" fill="{MUTED}">{label}</text>')
    out.append(f'<text x="{w / 2}" y="{h - 6}" font-size="11" text-anchor="middle" fill="{MUTED}">days</text></svg>')
    return "".join(out)


def card(label, value, note=""):
    return (f'<div class="card"><div class="value">{esc(value)}</div><div class="label">{esc(label)}</div>'
            f'<div class="note">{esc(note)}</div></div>')


def table(rows, cols, limit=10):
    head = "".join(f"<th>{esc(c)}</th>" for c in cols)
    body = "".join("<tr>" + "".join(f"<td>{esc(r.get(c, ''))}</td>" for c in cols) + "</tr>" for r in rows[:limit])
    return f'<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", type=Path, default=Path(__file__).parent / "data")
    ap.add_argument("--out", type=Path, default=Path(__file__).parent / "report.html")
    a = ap.parse_args()
    st = json.loads((a.data_dir / "stats.json").read_text())
    with (a.data_dir / "delays.csv").open(newline="") as f:
        delays = list(csv.DictReader(f))
    with (a.data_dir / "awaiting.csv").open(newline="") as f:
        awaiting = list(csv.DictReader(f))
    for d in delays:
        d["bill"] = f'{d["bill_type"].upper()} {d["number"]}'
        d["delay_days"] = int(d["delay_days"])
    for r in awaiting:
        r["bill"] = f'{r["bill_type"].upper()} {r["number"]}'
    longest = sorted(delays, key=lambda d: -d["delay_days"])
    dd = st["delay_days"]
    pg = st["pages"]
    stage_rows = [{"stage": s, **v} for s, v in st["by_stage"].items()]

    parts = [f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Bill Delay Tracker</title>
<style>
body{{font-family:"Source Sans 3",system-ui,sans-serif;color:{INK};margin:0;padding:24px 16px;max-width:1040px;margin-inline:auto;background:#fff}}
h1{{margin:0 0 4px}} .eyebrow{{color:{MUTED};text-transform:uppercase;letter-spacing:.08em;font-size:12px;margin:0}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:20px 0}}
.card{{border:1px solid #e5e7eb;border-radius:8px;padding:14px}} .value{{font-size:28px;font-weight:700;color:{BLUE}}}
.label{{font-size:13px}} .note{{font-size:11px;color:{MUTED}}}
.charts{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}}
table{{border-collapse:collapse;width:100%;font-size:13px;margin:8px 0 24px}} th,td{{text-align:left;padding:6px 8px;border-bottom:1px solid #e5e7eb;vertical-align:top}}
th{{color:{MUTED};font-weight:600}} .caveats{{background:#fff8e6;border-left:4px solid {GOLD};padding:10px 14px;font-size:13px}}
footer{{color:{MUTED};font-size:12px;margin-top:24px}}
</style></head><body>
<p class="eyebrow">Congressional Tech · proposal IV.2 · prototype</p>
<h1>Bill Delay Tracker</h1>
<p>Lag between a bill text version appearing on GovInfo and its CRS summary on Congress.gov, {esc(st.get('congress') or '')}th Congress, as of {esc(st['as_of'])}.</p>
<div class="cards">
{card('bills with text', st['bills_with_text'], f"{st['text_versions']} text versions")}
{card('bills with a CRS summary', st['bills_summarized'], f"{st['summaries_collected']} summary versions collected")}
{card('introduced, awaiting summary', st['introduced_awaiting_summary'], 'no introduced-stage summary yet')}
{card('reported by committee', st['bills_reported_by_committee'], 'bills with an rh/rs text version')}
{card('median lag (days)', dd['median'] if dd['median'] is not None else '–', f"mean {dd['mean']}, max {dd['max']}, n={dd['n']}")}
{card('pages of bill text', f"{pg['total']:,}", f"{pg['versions_with_count']} of {pg['versions_total']} versions counted")}
</div>
<div class="charts">
{bar_chart(st['introduced_histogram'], 'Introduced text → introduced summary, lag in days', BLUE)}
{bar_chart(st['awaiting_histogram'], 'Introduced text still without a summary, age in days', GOLD)}
</div>
<h2>Lag by stage</h2>
{table(stage_rows, ['stage', 'n', 'mean', 'median', 'min', 'max'])}
<h2>Longest lags</h2>
{table(longest, ['bill', 'stage', 'text_date', 'summary_date', 'delay_days', 'pages', 'title'])}
<h2>Oldest bills still awaiting an introduced summary</h2>
{table(awaiting, ['bill', 'text_date', 'age_days', 'pages', 'title'])}
<div class="caveats"><strong>Read the numbers with these in mind</strong><ul>{''.join(f'<li>{esc(c)}</li>' for c in st['caveats'])}</ul></div>
<footer>Sources: GovInfo BILLS collection (text versions, page counts) and the Congress.gov API summaries endpoint. Computed {esc(st['computed_at'])}.</footer>
</body></html>"""]
    a.out.write_text("".join(parts))
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
