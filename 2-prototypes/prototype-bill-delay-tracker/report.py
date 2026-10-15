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


MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def nice_ticks(vmax, target=5):
    """Round tick values up to a multiple of 1/2/5 x 10^k that covers vmax."""
    import math
    if vmax <= 0:
        return [0, 1]
    raw = vmax / target
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 5, 10) if m * mag >= raw)
    top = math.ceil(vmax / step) * step
    return [i * step for i in range(int(top / step) + 1)]


def timeseries_chart(monthly):
    """Two panels over month of introduction: share summarized vs still waiting,
    and median / 90th-percentile lag among the summarized."""
    w, left, right, gap = 920, 76, 16, 10
    n = max(len(monthly), 1)
    slot = (w - left - right) / n
    bw = slot - gap
    top_h, bot_h, top_y, bot_y = 150, 170, 52, 290
    h = bot_y + bot_h + 78
    lags = [m["p90_lag"] for m in monthly if m["p90_lag"] is not None] or [1]
    yticks = nice_ticks(max(lags))
    ymax = yticks[-1]
    out = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Lag by month of introduction" style="max-width:100%;height:auto">']
    out.append(f'<text x="{left}" y="18" font-size="14" font-weight="600" fill="{INK}">Bills by month of introduction: share with a CRS summary, and lag among those summarized</text>')

    def month_axis(y):
        for i, m in enumerate(monthly):
            x = left + i * slot + bw / 2
            yy, mm = m["month"].split("-")
            out.append(f'<text x="{x:.1f}" y="{y}" font-size="10" text-anchor="middle" fill="{MUTED}">{MONTHS[int(mm) - 1]}</text>')
            if mm == "01" or i == 0:
                out.append(f'<text x="{x:.1f}" y="{y + 12}" font-size="10" font-weight="600" text-anchor="middle" fill="{INK}">{yy}</text>')
        out.append(f'<text x="{left + (w - left - right) / 2:.1f}" y="{y + 28}" font-size="11" text-anchor="middle" fill="{INK}">Month the bill was introduced</text>')

    def y_title(label, y_mid):
        out.append(f'<text transform="translate(14,{y_mid:.1f}) rotate(-90)" font-size="11" text-anchor="middle" fill="{INK}">{label}</text>')

    # top panel: share summarized vs waiting
    for i, m in enumerate(monthly):
        x = left + i * slot
        tot = m["summarized"] + m["awaiting"] or 1
        sh = top_h * m["summarized"] / tot
        out.append(f'<rect x="{x:.1f}" y="{top_y + top_h - sh:.1f}" width="{bw:.1f}" height="{sh:.1f}" fill="{BLUE}"><title>{m["month"]}: {m["summarized"]} summarized, {m["awaiting"]} waiting</title></rect>')
        out.append(f'<rect x="{x:.1f}" y="{top_y:.1f}" width="{bw:.1f}" height="{top_h - sh:.1f}" fill="{GOLD}"><title>{m["month"]}: {m["awaiting"]} waiting</title></rect>')
    for frac in (0, 0.25, 0.5, 0.75, 1):
        y = top_y + top_h - top_h * frac
        out.append(f'<line x1="{left}" x2="{w - right}" y1="{y:.1f}" y2="{y:.1f}" stroke="#e5e7eb"/>')
        out.append(f'<text x="{left - 6}" y="{y + 4:.1f}" font-size="10" text-anchor="end" fill="{MUTED}">{int(frac * 100)}%</text>')
    y_title("Share of bills introduced that month", top_y + top_h / 2)
    out.append(f'<rect x="{left}" y="{top_y - 14}" width="10" height="10" fill="{BLUE}"/><text x="{left + 14}" y="{top_y - 5}" font-size="11" fill="{INK}">has introduced-stage CRS summary</text>')
    out.append(f'<rect x="{left + 215}" y="{top_y - 14}" width="10" height="10" fill="{GOLD}"/><text x="{left + 229}" y="{top_y - 5}" font-size="11" fill="{INK}">still waiting for one</text>')
    month_axis(top_y + top_h + 14)

    # bottom panel: lag lines
    def yy(v):
        return bot_y + bot_h - bot_h * v / ymax
    for v in yticks:
        out.append(f'<line x1="{left}" x2="{w - right}" y1="{yy(v):.1f}" y2="{yy(v):.1f}" stroke="#e5e7eb"/>')
        out.append(f'<text x="{left - 6}" y="{yy(v) + 4:.1f}" font-size="10" text-anchor="end" fill="{MUTED}">{int(v)}</text>')
    y_title("Days, introduced text to CRS summary", bot_y + bot_h / 2)
    for key, color, dash, label, lx in (("p90_lag", MUTED, ' stroke-dasharray="4 3"', "90th percentile", left + 100), ("median_lag", BLUE, "", "median", left)):
        pts = [(left + i * slot + bw / 2, yy(m[key])) for i, m in enumerate(monthly) if m[key] is not None]
        if pts:
            out.append(f'<polyline fill="none" stroke="{color}" stroke-width="2"{dash} points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in pts)}"/>')
            for (x, y), m in zip(pts, [m for m in monthly if m[key] is not None]):
                out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.5" fill="{color}"><title>{m["month"]}: {label} lag {m[key]:.0f} days (n={m["summarized"]} summarized)</title></circle>')
        out.append(f'<line x1="{lx}" x2="{lx + 18}" y1="{bot_y - 9}" y2="{bot_y - 9}" stroke="{color}" stroke-width="2"{dash}/><text x="{lx + 24}" y="{bot_y - 5}" font-size="11" fill="{INK}">{label}</text>')
    out.append(f'<text x="{left + 290}" y="{bot_y - 5}" font-size="11" fill="{MUTED}">lag among the bills summarized so far</text>')
    month_axis(bot_y + bot_h + 14)
    out.append(f'<text x="{left}" y="{h - 16}" font-size="11" fill="{MUTED}">Right-censored: in recent months only the bills already summarized count toward the lag lines, so they fall at the right edge.</text>')
    out.append(f'<text x="{left}" y="{h - 3}" font-size="11" fill="{MUTED}">The gold share above is the honest companion: those bills have no lag yet because they have no summary yet.</text>')
    out.append("</svg>")
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
<h2>Over time</h2>
{timeseries_chart(st.get('monthly_introduced', []))}
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
