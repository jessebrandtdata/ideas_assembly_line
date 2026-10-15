# Interactive Bill Delay Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the static Python-rendered report with a d3 dashboard (header metrics, lag histogram, filters, brushable timeseries) fed by a `delays.json` the Python pipeline writes.

**Architecture:** `delays.py` gains one output, `data/delays.json` (one record per bill-stage, waiting ones included). A static page `dashboard/index.html` loads it and renders everything client-side from one `state` object through one `render(state)`. Pure computations (filtering, header metrics, binning, monthly series) live in `dashboard/metrics.js`, an ES module tested with `node --test`; d3 is used only inside drawing functions in `dashboard/dashboard.js`.

**Tech Stack:** Python 3.12 stdlib (pipeline + unittest), d3 v7.9.0 from cdnjs, ES modules, Node 20+ `node --test`. No build step, no npm.

**Spec:** `docs/superpowers/specs/2026-10-14-interactive-dashboard-design.md` (paths in this plan are relative to `2-prototypes/prototype-bill-delay-tracker/`, the prototype folder; `cd` there first)

## Global Constraints

- Static files only: no server code, no build step, no `package.json`.
- d3 from `https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js`, pinned, loaded once as a classic script; nothing else external except Google Fonts for Source Sans 3.
- Colors: summarized blue `#104378`, waiting red `#b2182b`, ink `#1f2933`, muted `#6b7280`.
- Every rung is hand-over-able: each task ends in a commit that leaves the page working.
- No new data collection; the page runs on `data/delays.json` produced from what is on disk, and on the fixture.
- No person's name in source or docs.

## Review Focus

1. A stage/type filter that leaves zero summarized records: header shows `–` for mean/median/max and the histogram draws no bars and no NaN rules (Task 3 test `headerMetrics` on empty; Task 2 `binLags` on empty).
2. Records with `pages: null` must not poison the page total or the counted fraction (Task 2 test).
3. A brush range with no records inside it: same empty behavior as (1), and clearing the brush restores the full set (Task 4 test `filterRecords` with a range that excludes everything, and with `range: null`).
4. `delays.json` missing or not JSON: one visible message, no partial render (Task 2 error path, checked by hand against a renamed file).
5. Lags above the last open bin must all land in that bin, never be dropped (Task 2 test `binLags` with a lag far beyond `maxBins * width`).

---

### Task 1: `delays.json` data contract

**Files:**
- Modify: `delays.py` (after `awaiting.sort(...)`, before `by_stage = defaultdict(list)`)
- Create: `tests/test_delays_json.py`

**Interfaces:**
- Consumes: `text` (dict keyed `(bill_type, number, stage)` → version row), `summ` (same keys → summary row), `pages` (package_id → int), `reported` (set of `(bill_type, number)`), `to_date`, `a.data_dir`, `as_of`, `versions` — all already in `delays.py::main`.
- Produces: `data/delays.json`:
  ```json
  {"as_of": "2026-10-14", "congress": "119",
   "records": [{"type": "hr", "number": "1", "stage": "reported", "text_date": "2025-05-20",
                "summary_date": "2025-09-22", "lag_days": 125, "pages": 1118,
                "reported": true, "title": "One Big Beautiful Bill Act"}]}
  ```
  One record per **text version** (every row of `versions.csv`, 19,982 in the snapshot), not only stage-mapped ones: a version whose code has no stage (`rfs`, `pcs`, `rds`, `cps`, `rfh`, numbered variants) carries `stage: null`, `summary_date: null`, `lag_days: null` and still counts toward pages. A stage-mapped version that is not the earliest of its (bill, stage) also carries `stage: null` (the lag belongs to the earliest edition). Waiting: `summary_date: null`, `lag_days: null`. `pages: null` when not looked up. `reported` is bill-level (the bill has an `rh`/`rs` version). The envelope also carries `"summary_before_text": {"introduced": 41, "reported": 2}` — summaries with a stage whose bill has no text version at that stage (the inverse delay), counted by stage. `summary_stage` maps "House agreed to Senate amendment" to `passed`.

- [ ] **Step 1: Write the failing test**

`tests/test_delays_json.py`:
```python
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROTO = HERE.parent


class DelaysJson(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        for name in ("versions.csv", "pages.csv", "summaries.csv"):
            shutil.copy(HERE / "fixture" / name, cls.tmp / name)
        subprocess.run([sys.executable, str(PROTO / "delays.py"), "--data-dir", str(cls.tmp),
                        "--as-of", "2026-10-14"], check=True, capture_output=True)
        cls.doc = json.loads((cls.tmp / "delays.json").read_text())
        cls.records = cls.doc["records"]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_envelope(self):
        self.assertEqual(self.doc["as_of"], "2026-10-14")
        self.assertEqual(self.doc["congress"], "119")

    def test_one_record_per_version(self):
        # fixture: hr1 rh + eh, hr10786 ih, hr10779 ih, plus one unmapped rfs edition of hr1
        self.assertEqual(len(self.records), 5)
        keys = sorted((r["type"], r["number"], r["stage"] or "-") for r in self.records)
        self.assertEqual(keys, [("hr", "1", "-"), ("hr", "1", "passed"), ("hr", "1", "reported"),
                                ("hr", "10779", "introduced"), ("hr", "10786", "introduced")])

    def test_unmapped_version_keeps_pages_and_has_no_stage(self):
        r = next(r for r in self.records if r["stage"] is None)
        self.assertEqual(r["pages"], 900)
        self.assertIsNone(r["lag_days"])

    def test_summary_before_text_counted(self):
        # fixture summaries.csv has an Introduced summary for hr 99999, which has no text version
        self.assertEqual(self.doc["summary_before_text"], {"introduced": 1})

    def test_summarized_record(self):
        r = next(r for r in self.records if r["number"] == "1" and r["stage"] == "reported")
        self.assertEqual(r["text_date"], "2025-05-20")
        self.assertEqual(r["summary_date"], "2025-09-22")
        self.assertEqual(r["lag_days"], 125)
        self.assertEqual(r["pages"], 1118)
        self.assertTrue(r["reported"])
        self.assertEqual(r["title"], "One Big Beautiful Bill Act")

    def test_waiting_record_has_nulls(self):
        r = next(r for r in self.records if r["number"] == "10779")
        self.assertIsNone(r["summary_date"])
        self.assertIsNone(r["lag_days"])
        self.assertIsNone(r["pages"])
        self.assertFalse(r["reported"])

    def test_count_matches_csvs(self):
        import csv
        delays = list(csv.DictReader((self.tmp / "delays.csv").open()))
        awaiting = list(csv.DictReader((self.tmp / "awaiting.csv").open()))
        waiting = [r for r in self.records if r["lag_days"] is None]
        self.assertEqual(len([r for r in self.records if r["lag_days"] is not None]), len(delays))
        # awaiting.csv only lists the introduced stage; the json lists waiting at every stage
        self.assertGreaterEqual(len(waiting), len(awaiting))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Extend the fixture, run the test to verify it fails**

Append to `tests/fixture/versions.csv`:
```
BILLS-119hr1rfs,119,hr,1,rfs,2025-05-23,2026-07-10T18:21:49Z,One Big Beautiful Bill Act
```
Append to `tests/fixture/pages.csv`: `BILLS-119hr1rfs,900`
Append to `tests/fixture/summaries.csv`: `119,hr,99999,00,Introduced in House,2026-10-01,2026-10-13T15:00:00Z,,`

Run: `python3 -m unittest tests.test_delays_json -v`
Expected: FAIL in `setUpClass` with `FileNotFoundError: .../delays.json`

- [ ] **Step 3: Write the json output in `delays.py`**

Insert after `awaiting.sort(key=lambda r: -r["age_days"])` and its `write_csv(...)` call, before `by_stage = defaultdict(list)`:
```python
    # one record per text version for the dashboard. Only the earliest edition of a
    # (bill, stage) carries the stage and its lag; every other edition keeps its pages
    # under stage null so "pages processed" counts the whole Congress.
    earliest = {v["package_id"]: k for k, v in text.items()}
    records = []
    for v in sorted(versions, key=lambda v: (v["bill_type"], int(v["number"]), v["date_issued"])):
        k = earliest.get(v["package_id"])
        s = summ.get(k) if k else None
        td = to_date(v["date_issued"])
        sd = to_date(s["update_date"]) if s else None
        records.append({"type": v["bill_type"], "number": v["number"], "stage": k[2] if k else None,
                        "text_date": td.isoformat(),
                        "summary_date": sd.isoformat() if sd else None,
                        "lag_days": (sd - td).days if sd else None,
                        "pages": pages.get(v["package_id"]),
                        "reported": (v["bill_type"], v["number"]) in reported,
                        "title": v["title"]})
    before_text = Counter(k[2] for k in summ if k not in text)
    (a.data_dir / "delays.json").write_text(json.dumps(
        {"as_of": as_of.isoformat(), "congress": versions[0]["congress"] if versions else None,
         "summary_before_text": dict(sorted(before_text.items())), "records": records},
        separators=(",", ":")) + "\n")
```

Also at the top of `delays.py`: `from collections import Counter, defaultdict` (replace the existing `defaultdict` import), and in `summary_stage` add before the final `return None`:
```python
    if d.startswith("house agreed to senate amendment") or d.startswith("senate agreed to house amendment"):
        return "passed"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_delays_json -v`
Expected: 7 tests, OK

- [ ] **Step 5: Regenerate the real and fixture outputs, commit**

```bash
python3 delays.py > /dev/null && python3 delays.py --data-dir tests/fixture --as-of 2026-10-14 > /dev/null
python3 -c "import json; d=json.load(open('data/delays.json')); print(len(d['records']), 'records')"
git add delays.py tests/test_delays_json.py data/delays.json tests/fixture/delays.json
git commit -m "Bill Delay Tracker: delays.json, one record per bill-stage for the dashboard"
```
Expected print: `19982 records` (one per row of `data/versions.csv`).

---

### Task 2: Histogram page (minimal hand-over)

**Files:**
- Create: `dashboard/metrics.js`
- Create: `dashboard/metrics.test.mjs`
- Create: `dashboard/index.html`
- Create: `dashboard/dashboard.js`
- Modify: `README.md` (add the dashboard line)

**Interfaces:**
- Consumes: `data/delays.json` from Task 1.
- Produces, in `metrics.js` (ES module, no d3, no DOM):
  - `headerMetrics(records) → {bills, summarized, waiting, reported, pagesTotal, pagesCounted, versions, n, lagMean, lagMedian, lagMax}` — `lag*` are `null` when `n === 0`; `waiting` counts only records with a stage (`stage !== null`) and no lag, since unmapped editions never get a summary of their own.
  - `binLags(records, width, maxBins = 20) → [{from, to, count}]` — `to` is `null` on the last (open) bin; every lag ≥ `(maxBins-1)*width` lands there; empty input → `[]`.
  - `filterRecords(records, state)` is added in Task 3; `monthlySeries` in Task 4.
- Produces, in `dashboard.js`: `render(state)`; `state = {records, stage: 'introduced', type: 'all', range: null, width: 30}`.

- [ ] **Step 1: Write the failing metrics tests**

`dashboard/metrics.test.mjs`:
```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { headerMetrics, binLags } from './metrics.js';

const rec = (o) => ({ type: 'hr', number: '1', stage: 'introduced', text_date: '2025-01-10',
  summary_date: null, lag_days: null, pages: null, reported: false, title: 't', ...o });

test('headerMetrics counts bills, summarized, waiting, reported, pages', () => {
  const m = headerMetrics([
    rec({ number: '1', lag_days: 10, summary_date: '2025-01-20', pages: 5, reported: true }),
    rec({ number: '2', lag_days: 30, summary_date: '2025-02-09', pages: null }),
    rec({ number: '3' }),
    rec({ number: '3', stage: null, pages: 7 }),
  ]);
  assert.equal(m.bills, 3);
  assert.equal(m.summarized, 2);
  assert.equal(m.waiting, 1);
  assert.equal(m.reported, 1);
  assert.equal(m.pagesTotal, 12);
  assert.equal(m.pagesCounted, 2);
  assert.equal(m.versions, 4);
  assert.equal(m.n, 2);
  assert.equal(m.lagMean, 20);
  assert.equal(m.lagMedian, 20);
  assert.equal(m.lagMax, 30);
});

test('headerMetrics median of odd count and null lags when nothing summarized', () => {
  const odd = headerMetrics([rec({ lag_days: 1 }), rec({ lag_days: 5 }), rec({ lag_days: 100 })]);
  assert.equal(odd.lagMedian, 5);
  const none = headerMetrics([rec(), rec({ number: '2' })]);
  assert.equal(none.n, 0);
  assert.equal(none.lagMean, null);
  assert.equal(none.lagMedian, null);
  assert.equal(none.lagMax, null);
  assert.equal(headerMetrics([]).bills, 0);
});

test('binLags puts lags in fixed-width bins, last bin open, waiting ignored', () => {
  const bins = binLags([rec({ lag_days: 0 }), rec({ lag_days: 29 }), rec({ lag_days: 30 }),
    rec({ lag_days: 5000 }), rec()], 30, 4);
  assert.deepEqual(bins, [
    { from: 0, to: 30, count: 2 },
    { from: 30, to: 60, count: 1 },
    { from: 60, to: 90, count: 0 },
    { from: 90, to: null, count: 1 },
  ]);
});

test('binLags on empty input and on only-waiting input', () => {
  assert.deepEqual(binLags([], 30), []);
  assert.deepEqual(binLags([rec()], 30), []);
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node --test dashboard/metrics.test.mjs`
Expected: fails to load `./metrics.js` (ERR_MODULE_NOT_FOUND)

- [ ] **Step 3: Write `dashboard/metrics.js`**

```js
// Pure computations for the dashboard. No d3, no DOM, so node --test covers them.

const billKey = (r) => `${r.type}${r.number}`;

function median(sorted) {
  const n = sorted.length;
  if (n === 0) return null;
  return n % 2 ? sorted[(n - 1) / 2] : (sorted[n / 2 - 1] + sorted[n / 2]) / 2;
}

/** Header-row numbers over the records in view. lag* are null when nothing is summarized. */
export function headerMetrics(records) {
  const summarized = records.filter((r) => r.lag_days !== null);
  const lags = summarized.map((r) => r.lag_days).sort((a, b) => a - b);
  const withPages = records.filter((r) => r.pages !== null);
  return {
    bills: new Set(records.map(billKey)).size,
    summarized: new Set(summarized.map(billKey)).size,
    waiting: records.filter((r) => r.stage !== null && r.lag_days === null).length,
    reported: new Set(records.filter((r) => r.reported).map(billKey)).size,
    pagesTotal: withPages.reduce((s, r) => s + r.pages, 0),
    pagesCounted: withPages.length,
    versions: records.length,
    n: lags.length,
    lagMean: lags.length ? lags.reduce((a, b) => a + b, 0) / lags.length : null,
    lagMedian: median(lags),
    lagMax: lags.length ? lags[lags.length - 1] : null,
  };
}

/** Fixed-width bins of lag_days; the last bin is open-ended so nothing is dropped. */
export function binLags(records, width, maxBins = 20) {
  const lags = records.filter((r) => r.lag_days !== null).map((r) => r.lag_days);
  if (lags.length === 0) return [];
  const needed = Math.floor(Math.max(...lags) / width) + 1;
  const count = Math.min(needed, maxBins);
  const bins = Array.from({ length: count }, (_, i) => ({
    from: i * width, to: i === count - 1 && needed > count ? null : (i + 1) * width, count: 0,
  }));
  for (const lag of lags) bins[Math.min(Math.floor(lag / width), count - 1)].count += 1;
  if (needed > count) bins[count - 1].to = null;
  return bins;
}
```
Note on the last bin: when `needed <= maxBins` every bin is closed (`to` set), since nothing overflows. The test with `maxBins = 4` and a lag of 5000 forces the open bin.

- [ ] **Step 4: Run tests to verify they pass**

Run: `node --test dashboard/metrics.test.mjs`
Expected: 4 passed

- [ ] **Step 5: Write `dashboard/index.html`**

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Bill Delay Tracker</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;600;700&display=swap">
<style>
:root { --blue: #104378; --red: #b2182b; --ink: #1f2933; --muted: #6b7280; --line: #e5e7eb; }
body { font-family: "Source Sans 3", system-ui, sans-serif; color: var(--ink); margin: 0; padding: 24px 16px; max-width: 1040px; margin-inline: auto; background: #fff; }
h1 { margin: 0 0 4px; } .eyebrow { color: var(--muted); text-transform: uppercase; letter-spacing: .08em; font-size: 12px; margin: 0; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin: 20px 0; }
.card { border: 1px solid var(--line); border-radius: 8px; padding: 14px; }
.card .value { font-size: 28px; font-weight: 700; color: var(--blue); } .card .label { font-size: 13px; } .card .note { font-size: 11px; color: var(--muted); }
.controls { display: flex; flex-wrap: wrap; gap: 12px 20px; align-items: end; margin: 8px 0 16px; font-size: 13px; }
.controls label { display: flex; flex-direction: column; gap: 4px; } .controls select, .controls button { font: inherit; padding: 4px 8px; }
figure { margin: 0 0 24px; } figure svg { max-width: 100%; height: auto; display: block; }
.caveat { background: #fff8e6; border-left: 4px solid #eec05e; padding: 10px 14px; font-size: 13px; }
.error { color: var(--red); font-weight: 600; }
.tooltip { position: absolute; pointer-events: none; background: var(--ink); color: #fff; font-size: 12px; padding: 6px 8px; border-radius: 4px; display: none; }
</style>
</head>
<body>
<p class="eyebrow">Congressional Tech · proposal IV.2 · prototype</p>
<h1>Bill Delay Tracker</h1>
<p id="subtitle">Lag between a bill text version on GovInfo and its CRS summary on Congress.gov.</p>
<div id="controls" class="controls"></div>
<div id="cards" class="cards"></div>
<figure id="histogram"></figure>
<figure id="timeseries"></figure>
<div class="caveat">Lag is measured to the summary's last-update date, the only date the Congress.gov API exposes; a summary revised later reads slower than it was. The text date is the date printed on the version. "Waiting" means no summary at that stage appears in the data collected.</div>
<div id="tooltip" class="tooltip"></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js"></script>
<script type="module" src="dashboard.js"></script>
</body>
</html>
```

- [ ] **Step 6: Write `dashboard/dashboard.js` (header + histogram only)**

```js
import { headerMetrics, binLags } from './metrics.js';

const BLUE = '#104378', RED = '#b2182b', INK = '#1f2933', MUTED = '#6b7280';
const fmt = d3.format(',');
const day = (v) => (v === null ? '–' : `${Math.round(v)}`);

const state = { records: [], stage: 'introduced', type: 'all', range: null, width: 30 };

/** Records in view; filters arrive in later tasks. */
function inView(state) {
  return state.records.filter((r) => r.stage === state.stage);
}

function card(label, value, note = '') {
  return `<div class="card"><div class="value">${value}</div><div class="label">${label}</div><div class="note">${note}</div></div>`;
}

function renderHeader(records, allVersions) {
  const m = headerMetrics(records);
  const p = headerMetrics(allVersions); // pages count every edition, not only the staged one
  document.getElementById('cards').innerHTML = [
    card('pages of bill text', fmt(p.pagesTotal), `${fmt(p.pagesCounted)} of ${fmt(p.versions)} versions counted`),
    card('bills summarized', fmt(m.summarized), `${fmt(m.waiting)} still waiting`),
    card('reported by committee', fmt(m.reported), 'bills with an rh/rs text version'),
    card('mean lag (days)', day(m.lagMean), `n=${fmt(m.n)}`),
    card('median lag (days)', day(m.lagMedian)),
    card('max lag (days)', day(m.lagMax)),
  ].join('');
}

function renderHistogram(records, width) {
  const bins = binLags(records, width);
  const m = headerMetrics(records);
  const W = 920, H = 320, left = 56, right = 16, top = 36, bottom = 56;
  const fig = d3.select('#histogram').html('');
  if (bins.length === 0) {
    fig.append('p').attr('class', 'note').text('No summarized bills in this view.');
    return;
  }
  const svg = fig.append('svg').attr('viewBox', `0 0 ${W} ${H}`).attr('role', 'img')
    .attr('aria-label', 'Histogram of lag in days');
  svg.append('text').attr('x', left).attr('y', 18).attr('font-size', 14).attr('font-weight', 600).attr('fill', INK)
    .text(`Days from text to CRS summary, ${width}-day bins (n=${fmt(m.n)} summarized; ${fmt(m.waiting)} still waiting, not shown)`);
  const x = d3.scaleBand().domain(bins.map((_, i) => i)).range([left, W - right]).padding(0.12);
  const y = d3.scaleLinear().domain([0, d3.max(bins, (b) => b.count)]).nice().range([H - bottom, top]);
  svg.append('g').attr('transform', `translate(${left},0)`).call(d3.axisLeft(y).ticks(5).tickFormat(fmt))
    .call((g) => g.select('.domain').remove()).selectAll('text').attr('fill', MUTED);
  svg.append('g').attr('transform', `translate(0,${H - bottom})`)
    .call(d3.axisBottom(x).tickFormat((i) => (bins[i].to === null ? `${bins[i].from}+` : `${bins[i].from}`)))
    .call((g) => g.select('.domain').remove()).selectAll('text').attr('fill', MUTED);
  svg.append('text').attr('x', (left + W - right) / 2).attr('y', H - 14).attr('font-size', 11).attr('text-anchor', 'middle').attr('fill', INK)
    .text('lag in days (bin start)');
  svg.append('text').attr('transform', `translate(14,${(top + H - bottom) / 2}) rotate(-90)`).attr('font-size', 11).attr('text-anchor', 'middle').attr('fill', INK)
    .text('bills');
  svg.append('g').selectAll('rect').data(bins).join('rect')
    .attr('x', (_, i) => x(i)).attr('y', (b) => y(b.count)).attr('width', x.bandwidth())
    .attr('height', (b) => y(0) - y(b.count)).attr('fill', BLUE).attr('rx', 2);
  svg.append('g').selectAll('text').data(bins).join('text')
    .attr('x', (_, i) => x(i) + x.bandwidth() / 2).attr('y', (b) => y(b.count) - 4)
    .attr('font-size', 11).attr('text-anchor', 'middle').attr('fill', INK).text((b) => (b.count ? fmt(b.count) : ''));
  // median and mean rules sit at their position inside the band scale
  const pos = (v) => { const i = Math.min(Math.floor(v / width), bins.length - 1); return x(i) + x.bandwidth() * Math.min(1, (v - i * width) / width); };
  for (const [v, label] of [[m.lagMedian, 'median'], [m.lagMean, 'mean']]) {
    svg.append('line').attr('x1', pos(v)).attr('x2', pos(v)).attr('y1', top - 6).attr('y2', H - bottom)
      .attr('stroke', RED).attr('stroke-width', 1.5).attr('stroke-dasharray', label === 'mean' ? '4 3' : null);
    svg.append('text').attr('x', pos(v) + 4).attr('y', top + (label === 'mean' ? 26 : 12)).attr('font-size', 11).attr('fill', RED)
      .text(`${label} ${Math.round(v)}d`);
  }
}

export function render(state) {
  const records = inView(state);
  renderHeader(records, state.records);
  renderHistogram(records, state.width);
}

async function main() {
  try {
    const res = await fetch('../data/delays.json');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const doc = await res.json();
    state.records = doc.records;
    document.getElementById('subtitle').textContent =
      `Lag between a bill text version on GovInfo and its CRS summary on Congress.gov, ${doc.congress}th Congress, as of ${doc.as_of}.`;
    render(state);
  } catch (err) {
    document.getElementById('cards').innerHTML = `<p class="error">Could not load data/delays.json (${err.message}). Run delays.py first.</p>`;
  }
}

main();
```

- [ ] **Step 7: Check it in a browser, including the error path**

```bash
(python3 -m http.server 8655 --bind 127.0.0.1 > /dev/null 2>&1 &) ; sleep 1
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8655/dashboard/index.html
```
Expected: `200`. Open `http://127.0.0.1:8655/dashboard/` in a browser or with the headless-chromium screenshot recipe the session uses: six cards with numbers, one histogram with blue bars, red median and mean rules, axis titles. Then `mv data/delays.json data/delays.json.bak`, reload: one red sentence in the cards area, no histogram. `mv` it back. Kill the server: `fuser -k 8655/tcp`.

- [ ] **Step 8: README line and commit**

Append to `README.md`:
```
`dashboard/index.html` is the interactive view of `data/delays.json`; serve the prototype folder (`python3 -m http.server`) and open `/dashboard/`.
```
```bash
git add dashboard README.md
git commit -m "Bill Delay Tracker: d3 histogram page with the spec's header metrics"
```

---

### Task 3: Stage and bill-type filters

**Files:**
- Modify: `dashboard/metrics.js` (add `filterRecords`)
- Modify: `dashboard/metrics.test.mjs` (add tests)
- Modify: `dashboard/dashboard.js` (`inView` → `filterRecords`; controls)

**Interfaces:**
- Produces: `filterRecords(records, {stage, type, range}) → records` — `stage`/`type` are `'all'` or a value; `range` is `null` or `[fromISO, toISO]` inclusive on `text_date`.
- `render(state)` now reads `state.stage`, `state.type`, `state.range`.

- [ ] **Step 1: Write the failing tests**

Append to `dashboard/metrics.test.mjs` (add `filterRecords` to the import line):
```js
test('filterRecords by stage, type, and inclusive date range', () => {
  const rs = [
    rec({ number: '1', stage: 'introduced', type: 'hr', text_date: '2025-01-10' }),
    rec({ number: '2', stage: 'reported', type: 'hr', text_date: '2025-03-10' }),
    rec({ number: '3', stage: 'introduced', type: 's', text_date: '2025-06-30' }),
  ];
  assert.equal(filterRecords(rs, { stage: 'all', type: 'all', range: null }).length, 3);
  assert.deepEqual(filterRecords(rs, { stage: 'introduced', type: 'all', range: null }).map((r) => r.number), ['1', '3']);
  assert.deepEqual(filterRecords(rs, { stage: 'all', type: 's', range: null }).map((r) => r.number), ['3']);
  assert.deepEqual(filterRecords(rs, { stage: 'all', type: 'all', range: ['2025-03-10', '2025-06-30'] }).map((r) => r.number), ['2', '3']);
  assert.deepEqual(filterRecords(rs, { stage: 'all', type: 'all', range: ['2026-01-01', '2026-12-31'] }), []);
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node --test dashboard/metrics.test.mjs`
Expected: SyntaxError: `filterRecords` not exported

- [ ] **Step 3: Add `filterRecords` to `metrics.js`**

```js
/** Records in view. range is null or [fromISO, toISO], inclusive on text_date. */
export function filterRecords(records, { stage = 'all', type = 'all', range = null }) {
  return records.filter((r) =>
    (stage === 'all' || r.stage === stage) &&
    (type === 'all' || r.type === type) &&
    (range === null || (r.text_date >= range[0] && r.text_date <= range[1])));
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `node --test dashboard/metrics.test.mjs`
Expected: 5 passed

- [ ] **Step 5: Wire the controls in `dashboard.js`**

Replace the import line and `inView`:
```js
import { headerMetrics, binLags, filterRecords } from './metrics.js';
```
Delete the `inView` function. In `render`, replace `const records = inView(state);` with `const records = filterRecords(state.records, state);` and the header call with `renderHeader(records, filterRecords(state.records, { stage: 'all', type: state.type, range: state.range }));` so pages follow type and range but count every edition.

Add before `export function render`:
```js
const STAGES = [['introduced', 'Introduced'], ['reported', 'Reported by committee'], ['passed', 'Passed a chamber'], ['enrolled', 'Enrolled'], ['all', 'All stages']];
const TYPES = [['all', 'All bill types'], ['hr', 'H.R.'], ['s', 'S.'], ['hjres', 'H.J.Res.'], ['sjres', 'S.J.Res.']];

function select(id, label, options, value) {
  return `<label>${label}<select id="${id}">${options.map(([v, text]) =>
    `<option value="${v}"${v === value ? ' selected' : ''}>${text}</option>`).join('')}</select></label>`;
}

function renderControls(state) {
  const el = document.getElementById('controls');
  if (el.children.length) return; // built once; selects keep their own value
  el.innerHTML = select('stage', 'Stage', STAGES, state.stage) + select('type', 'Bill type', TYPES, state.type);
  el.querySelector('#stage').addEventListener('change', (e) => { state.stage = e.target.value; render(state); });
  el.querySelector('#type').addEventListener('change', (e) => { state.type = e.target.value; render(state); });
}
```
And at the top of `render(state)`: `renderControls(state);`.

- [ ] **Step 6: Check in a browser**

Serve as in Task 2 step 7. Change Stage to "Enrolled" and Bill type to "S.J.Res.": the cards and histogram follow; a combination with no summarized bills shows `–` in the lag cards and the "No summarized bills in this view." sentence, no console errors.

- [ ] **Step 7: Commit**

```bash
git add dashboard
git commit -m "Bill Delay Tracker: stage and bill-type filters drive header and histogram"
```

---

### Task 4: Timeseries by month introduced, with a brush

**Files:**
- Modify: `dashboard/metrics.js` (add `monthlySeries`)
- Modify: `dashboard/metrics.test.mjs`
- Modify: `dashboard/dashboard.js` (add `renderTimeseries`, brush → `state.range`)

**Interfaces:**
- Produces: `monthlySeries(records) → [{month: 'YYYY-MM', summarized, waiting, medianLag, p90Lag}]` sorted by month; `medianLag`/`p90Lag` are `null` when nothing in that month is summarized.
- The timeseries is computed from records filtered by stage and type only (never by `range`), so the brush shows the whole span while the header and histogram follow the brushed range.

- [ ] **Step 1: Write the failing test**

Append to `metrics.test.mjs` (add `monthlySeries` to the import):
```js
test('monthlySeries groups by month of text_date with lag quantiles', () => {
  const s = monthlySeries([
    rec({ number: '1', text_date: '2025-01-03', lag_days: 10 }),
    rec({ number: '2', text_date: '2025-01-20', lag_days: 30 }),
    rec({ number: '3', text_date: '2025-01-25' }),
    rec({ number: '4', text_date: '2025-03-01' }),
  ]);
  assert.deepEqual(s, [
    { month: '2025-01', summarized: 2, waiting: 1, medianLag: 20, p90Lag: 30 },
    { month: '2025-03', summarized: 0, waiting: 1, medianLag: null, p90Lag: null },
  ]);
  assert.deepEqual(monthlySeries([]), []);
});
```

- [ ] **Step 2: Run tests to verify it fails**

Run: `node --test dashboard/metrics.test.mjs`
Expected: SyntaxError: `monthlySeries` not exported

- [ ] **Step 3: Add `monthlySeries` to `metrics.js`**

```js
/** Per month of text_date: how many got a summary, how many wait, and lag quantiles among the summarized. */
export function monthlySeries(records) {
  const byMonth = new Map();
  for (const r of records) {
    const month = r.text_date.slice(0, 7);
    if (!byMonth.has(month)) byMonth.set(month, { lags: [], waiting: 0 });
    const m = byMonth.get(month);
    if (r.lag_days === null) m.waiting += 1; else m.lags.push(r.lag_days);
  }
  return [...byMonth.keys()].sort().map((month) => {
    const { lags, waiting } = byMonth.get(month);
    const sorted = lags.sort((a, b) => a - b);
    return {
      month, summarized: sorted.length, waiting,
      medianLag: median(sorted),
      p90Lag: sorted.length ? sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * 0.9))] : null,
    };
  });
}
```
(`median` already exists in the module.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `node --test dashboard/metrics.test.mjs`
Expected: 6 passed

- [ ] **Step 5: Draw the timeseries and brush in `dashboard.js`**

Import: `import { headerMetrics, binLags, filterRecords, monthlySeries } from './metrics.js';`

Add before `export function render`:
```js
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const monthLabel = (m) => MONTHS[+m.slice(5, 7) - 1];
const lastDay = (m) => { const [y, mo] = m.split('-').map(Number); return new Date(Date.UTC(y, mo, 0)).toISOString().slice(0, 10); };

function renderTimeseries(records, state) {
  const series = monthlySeries(records);
  const W = 920, left = 76, right = 16, topY = 52, topH = 150, botY = 290, botH = 170, H = botY + botH + 60;
  const fig = d3.select('#timeseries').html('');
  if (series.length === 0) return;
  const svg = fig.append('svg').attr('viewBox', `0 0 ${W} ${H}`).attr('role', 'img').attr('aria-label', 'Lag by month of introduction');
  svg.append('text').attr('x', left).attr('y', 18).attr('font-size', 14).attr('font-weight', 600).attr('fill', INK)
    .text('By month the text was issued: share with a CRS summary, and lag among those summarized. Drag to select months.');
  const x = d3.scaleBand().domain(series.map((s) => s.month)).range([left, W - right]).padding(0.18);
  const monthAxis = (y) => {
    const g = svg.append('g');
    for (const s of series) {
      const cx = x(s.month) + x.bandwidth() / 2;
      g.append('text').attr('x', cx).attr('y', y).attr('font-size', 10).attr('text-anchor', 'middle').attr('fill', MUTED).text(monthLabel(s.month));
      if (s.month.endsWith('-01') || s === series[0]) g.append('text').attr('x', cx).attr('y', y + 12).attr('font-size', 10).attr('font-weight', 600).attr('text-anchor', 'middle').attr('fill', INK).text(s.month.slice(0, 4));
    }
    g.append('text').attr('x', (left + W - right) / 2).attr('y', y + 28).attr('font-size', 11).attr('text-anchor', 'middle').attr('fill', INK).text('Month the text version was issued');
  };
  // top: share
  const yShare = d3.scaleLinear().domain([0, 1]).range([topY + topH, topY]);
  svg.append('g').attr('transform', `translate(${left},0)`).call(d3.axisLeft(yShare).ticks(4).tickFormat(d3.format('.0%'))).call((g) => g.select('.domain').remove());
  svg.append('text').attr('transform', `translate(14,${topY + topH / 2}) rotate(-90)`).attr('font-size', 11).attr('text-anchor', 'middle').attr('fill', INK).text('Share of that month\'s bills');
  const bars = svg.append('g').selectAll('g').data(series).join('g');
  bars.append('rect').attr('x', (s) => x(s.month)).attr('width', x.bandwidth()).attr('fill', RED)
    .attr('y', topY).attr('height', (s) => yShare(1 - s.waiting / (s.summarized + s.waiting || 1)) - topY);
  bars.append('rect').attr('x', (s) => x(s.month)).attr('width', x.bandwidth()).attr('fill', BLUE)
    .attr('y', (s) => yShare(s.summarized / (s.summarized + s.waiting || 1))).attr('height', (s) => topY + topH - yShare(s.summarized / (s.summarized + s.waiting || 1)));
  bars.append('title').text((s) => `${s.month}: ${fmt(s.summarized)} summarized, ${fmt(s.waiting)} waiting`);
  monthAxis(topY + topH + 14);
  // bottom: lag lines
  const yMax = d3.max(series, (s) => s.p90Lag ?? 0) || 1;
  const yLag = d3.scaleLinear().domain([0, yMax]).nice().range([botY + botH, botY]);
  svg.append('g').attr('transform', `translate(${left},0)`).call(d3.axisLeft(yLag).ticks(5)).call((g) => g.select('.domain').remove());
  svg.append('text').attr('transform', `translate(14,${botY + botH / 2}) rotate(-90)`).attr('font-size', 11).attr('text-anchor', 'middle').attr('fill', INK).text('Days, text to CRS summary');
  const line = (key) => d3.line().defined((s) => s[key] !== null).x((s) => x(s.month) + x.bandwidth() / 2).y((s) => yLag(s[key]));
  svg.append('path').datum(series).attr('d', line('p90Lag')).attr('fill', 'none').attr('stroke', MUTED).attr('stroke-width', 2).attr('stroke-dasharray', '4 3');
  svg.append('path').datum(series).attr('d', line('medianLag')).attr('fill', 'none').attr('stroke', BLUE).attr('stroke-width', 2);
  svg.append('text').attr('x', left).attr('y', botY - 6).attr('font-size', 11).attr('fill', INK).text('— median   ┄ 90th percentile   (lag among the bills summarized so far; recent months are right-censored)');
  monthAxis(botY + botH + 14);
  // brush over the whole height; snaps to month bands and sets state.range
  const brush = d3.brushX().extent([[left, topY], [W - right, botY + botH]]).on('end', ({ selection, sourceEvent }) => {
    if (!sourceEvent) return; // programmatic move, not the user
    if (!selection) { state.range = null; render(state); return; }
    const picked = series.filter((s) => x(s.month) + x.bandwidth() > selection[0] && x(s.month) < selection[1]).map((s) => s.month);
    if (picked.length === 0) { state.range = null; render(state); return; }
    state.range = [`${picked[0]}-01`, lastDay(picked[picked.length - 1])];
    render(state);
  });
  const g = svg.append('g').call(brush);
  if (state.range) {
    const from = series.findIndex((s) => `${s.month}-01` === state.range[0]);
    const to = series.findIndex((s) => lastDay(s.month) === state.range[1]);
    if (from >= 0 && to >= 0) g.call(brush.move, [x(series[from].month), x(series[to].month) + x.bandwidth()]);
  }
}
```
In `render(state)`, after `renderHistogram(...)`:
```js
  renderTimeseries(filterRecords(state.records, { stage: state.stage, type: state.type, range: null }), state);
```
Add a "Clear selection" button to `renderControls`: append `<button id="clear" type="button">Clear month selection</button>` to the innerHTML and `el.querySelector('#clear').addEventListener('click', () => { state.range = null; render(state); });`.

- [ ] **Step 6: Check in a browser**

Serve as before. Drag across three months on the timeseries: the brush snaps, the cards and histogram shrink to that range, the timeseries itself keeps the full span. Drag a range into months with no records (none exist in the snapshot; test by selecting a single month with only waiting bills, e.g. the latest): lag cards show `–`, histogram shows the empty sentence. Click "Clear month selection": everything returns. Change Stage with a brush active: the brush is redrawn in place.

- [ ] **Step 7: Commit**

```bash
git add dashboard
git commit -m "Bill Delay Tracker: brushable month timeseries filters the header and histogram"
```

---

### Task 5: Bin width, hover tooltip, keyboard reach

**Files:**
- Modify: `dashboard/dashboard.js`
- Modify: `dashboard/metrics.test.mjs` (bin-width test on 7 and 90)

**Interfaces:**
- `state.width ∈ {7, 30, 90}`; `binLags(records, state.width)` unchanged.

- [ ] **Step 1: Write the failing test (bin widths 7 and 90 cover the same lags)**

Append to `metrics.test.mjs`:
```js
test('binLags totals are width-invariant', () => {
  const rs = [rec({ lag_days: 3 }), rec({ lag_days: 45 }), rec({ lag_days: 200 }), rec({ lag_days: 800 })];
  const total = (w) => binLags(rs, w).reduce((s, b) => s + b.count, 0);
  assert.equal(total(7), 4);
  assert.equal(total(30), 4);
  assert.equal(total(90), 4);
  assert.equal(binLags(rs, 7).at(-1).to, null); // 800/7 > 20 bins → open last bin
});
```

- [ ] **Step 2: Run the test**

Run: `node --test dashboard/metrics.test.mjs`
Expected: 7 passed (this test passes against the Task 2 code; it pins the invariant the toggle relies on)

- [ ] **Step 3: Bin width toggle**

In `renderControls`, add after the selects:
```js
const WIDTHS = [7, 30, 90];
```
(at module level, next to `STAGES`), and in the innerHTML: `<label>Bin width<span role="group" aria-label="Bin width">${WIDTHS.map((w) => `<button type="button" data-width="${w}"${w === state.width ? ' aria-pressed="true"' : ''}>${w} days</button>`).join('')}</span></label>` and the handler:
```js
  el.querySelectorAll('[data-width]').forEach((b) => b.addEventListener('click', () => {
    state.width = +b.dataset.width;
    el.querySelectorAll('[data-width]').forEach((o) => o.toggleAttribute('aria-pressed', o === b));
    render(state);
  }));
```
Add a style in `index.html`: `.controls [aria-pressed="true"] { background: var(--blue); color: #fff; border-color: var(--blue); }`.

- [ ] **Step 4: Hover tooltip on histogram bars**

In `renderHistogram`, after the bars join, replace the `.attr('rx', 2);` ending with:
```js
    .attr('rx', 2)
    .on('mousemove', (event, b) => {
      const share = m.n ? (b.count / m.n) : 0;
      const range = b.to === null ? `${b.from}+ days` : `${b.from}–${b.to - 1} days`;
      d3.select('#tooltip').style('display', 'block').style('left', `${event.pageX + 12}px`).style('top', `${event.pageY - 10}px`)
        .text(`${range}: ${fmt(b.count)} bills (${d3.format('.1%')(share)} of summarized)`);
    })
    .on('mouseleave', () => d3.select('#tooltip').style('display', 'none'));
```
Also give each bar a `<title>` for keyboard and screen-reader users: `.append('title').text(...)` is not chainable on a rect selection that continues; instead add after the bars join:
```js
  svg.selectAll('rect').filter((b) => b && 'count' in b).append('title')
    .text((b) => `${b.to === null ? `${b.from}+` : `${b.from}–${b.to - 1}`} days: ${fmt(b.count)} bills`);
```

- [ ] **Step 5: Check in a browser**

Serve as before. Click "7 days": many narrow bins, last one `133+`-style open label; "90 days": few bins. Hover a bar: tooltip with range, count, share. Tab through the page: Stage, Bill type, the three width buttons and Clear are all reachable and operable by keyboard (Enter/Space on buttons, arrows on selects).

- [ ] **Step 6: Commit**

```bash
git add dashboard
git commit -m "Bill Delay Tracker: bin width toggle, hover tooltip, keyboard-reachable controls"
```

---

### Task 6: Prototype write-up and README reflect the dashboard

**Files:**
- Modify: `../prototype-bill-delay-tracker.md` ("What's in this prototype" table and "How to run it")
- Modify: `README.md`

- [ ] **Step 1: Add rows and run steps**

In `../prototype-bill-delay-tracker.md`, add to the table after the `report.py` row:
```
| `dashboard/` | Interactive view of `data/delays.json`: header metrics, lag histogram with bin-width toggle and hover, stage and bill-type filters, a brushable month timeseries. d3 v7 from cdnjs; pure computations in `metrics.js` under `node --test`. |
```
In "How to run it", after the `# open report.html` line of block 2, add:
```
# 3. Interactive dashboard (serves the prototype folder; open /dashboard/)
python3 -m http.server 8000
```
and after block 1's last line: `node --test dashboard/metrics.test.mjs && python3 -m unittest tests.test_delays_json`.

In `README.md`, replace the pipeline line with:
```
`collect.py` → `data/*.csv` → `delays.py` → `data/stats.json` + `data/delays.json` → `report.py` → `report.html`, or `dashboard/` for the interactive view.
```

- [ ] **Step 2: Run everything once**

```bash
node --test dashboard/metrics.test.mjs && python3 -m unittest tests.test_delays_json
```
Expected: 7 node tests pass, 5 unittest pass.

- [ ] **Step 3: Commit**

```bash
git add ../prototype-bill-delay-tracker.md README.md
git commit -m "Bill Delay Tracker: document the dashboard"
```

---

### Task 7: Cumulative bills with text vs bills summarized

**Files:**
- Modify: `dashboard/metrics.js` (add `cumulativeSeries`)
- Modify: `dashboard/metrics.test.mjs`
- Modify: `dashboard/dashboard.js` (add `renderCumulative`)
- Modify: `dashboard/index.html` (add `<figure id="cumulative"></figure>` after `#timeseries`)

**Interfaces:**
- Produces: `cumulativeSeries(records) → [{date: 'YYYY-MM-DD', withText, summarized}]` — one point per distinct date on which either count changes, sorted; `withText` counts distinct bills whose earliest `text_date` ≤ date, `summarized` counts distinct bills whose earliest `summary_date` ≤ date. Records with `stage: null` are ignored (they are later editions).
- Computed from records filtered by stage and type only (never range), like the timeseries.

- [ ] **Step 1: Write the failing test**

Append to `metrics.test.mjs` (add `cumulativeSeries` to the import):
```js
test('cumulativeSeries counts distinct bills with text and with a summary by date', () => {
  const s = cumulativeSeries([
    rec({ number: '1', text_date: '2025-01-03', summary_date: '2025-01-20', lag_days: 17 }),
    rec({ number: '2', text_date: '2025-01-03' }),
    rec({ number: '3', text_date: '2025-02-01', summary_date: '2025-02-01', lag_days: 0 }),
    rec({ number: '3', stage: null, text_date: '2025-03-01', pages: 4 }),
  ]);
  assert.deepEqual(s, [
    { date: '2025-01-03', withText: 2, summarized: 0 },
    { date: '2025-01-20', withText: 2, summarized: 1 },
    { date: '2025-02-01', withText: 3, summarized: 2 },
  ]);
  assert.deepEqual(cumulativeSeries([]), []);
});
```

- [ ] **Step 2: Run tests to verify it fails**

Run: `node --test dashboard/metrics.test.mjs`
Expected: SyntaxError: `cumulativeSeries` not exported

- [ ] **Step 3: Add `cumulativeSeries` to `metrics.js`**

```js
/** Running counts of distinct bills with any text and with any summary, by date. */
export function cumulativeSeries(records) {
  const firstText = new Map(), firstSummary = new Map();
  for (const r of records) {
    if (r.stage === null) continue;
    const k = billKey(r);
    if (!firstText.has(k) || r.text_date < firstText.get(k)) firstText.set(k, r.text_date);
    if (r.summary_date !== null && (!firstSummary.has(k) || r.summary_date < firstSummary.get(k))) firstSummary.set(k, r.summary_date);
  }
  const dates = [...new Set([...firstText.values(), ...firstSummary.values()])].sort();
  const textDates = [...firstText.values()].sort(), summaryDates = [...firstSummary.values()].sort();
  const countLE = (sorted, d) => { let lo = 0, hi = sorted.length; while (lo < hi) { const mid = (lo + hi) >> 1; if (sorted[mid] <= d) lo = mid + 1; else hi = mid; } return lo; };
  return dates.map((date) => ({ date, withText: countLE(textDates, date), summarized: countLE(summaryDates, date) }));
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `node --test dashboard/metrics.test.mjs`
Expected: 8 passed

- [ ] **Step 5: Draw it**

Import `cumulativeSeries`. Add before `export function render`:
```js
function renderCumulative(records) {
  const series = cumulativeSeries(records);
  const W = 920, H = 300, left = 76, right = 16, top = 36, bottom = 56;
  const fig = d3.select('#cumulative').html('');
  if (series.length === 0) return;
  const parse = d3.utcParse('%Y-%m-%d');
  const x = d3.scaleUtc().domain(d3.extent(series, (s) => parse(s.date))).range([left, W - right]);
  const y = d3.scaleLinear().domain([0, d3.max(series, (s) => s.withText)]).nice().range([H - bottom, top]);
  const svg = fig.append('svg').attr('viewBox', `0 0 ${W} ${H}`).attr('role', 'img').attr('aria-label', 'Cumulative bills with text and with a summary');
  svg.append('text').attr('x', left).attr('y', 18).attr('font-size', 14).attr('font-weight', 600).attr('fill', INK)
    .text('Congress to date: bills with text issued, and bills with a CRS summary. The gap is the backlog.');
  svg.append('g').attr('transform', `translate(${left},0)`).call(d3.axisLeft(y).ticks(5).tickFormat(fmt)).call((g) => g.select('.domain').remove());
  svg.append('g').attr('transform', `translate(0,${H - bottom})`).call(d3.axisBottom(x).ticks(d3.utcMonth.every(2)).tickFormat(d3.utcFormat('%b %Y'))).call((g) => g.select('.domain').remove());
  svg.append('text').attr('transform', `translate(14,${(top + H - bottom) / 2}) rotate(-90)`).attr('font-size', 11).attr('text-anchor', 'middle').attr('fill', INK).text('bills');
  const line = (key) => d3.line().curve(d3.curveStepAfter).x((s) => x(parse(s.date))).y((s) => y(s[key]));
  svg.append('path').datum(series).attr('d', line('withText')).attr('fill', 'none').attr('stroke', BLUE).attr('stroke-width', 2);
  svg.append('path').datum(series).attr('d', line('summarized')).attr('fill', 'none').attr('stroke', RED).attr('stroke-width', 2);
  const last = series[series.length - 1];
  svg.append('text').attr('x', W - right).attr('y', y(last.withText) - 6).attr('font-size', 11).attr('text-anchor', 'end').attr('fill', BLUE).text(`${fmt(last.withText)} with text`);
  svg.append('text').attr('x', W - right).attr('y', y(last.summarized) - 6).attr('font-size', 11).attr('text-anchor', 'end').attr('fill', RED).text(`${fmt(last.summarized)} summarized`);
}
```
In `render(state)` after the timeseries call:
```js
  renderCumulative(filterRecords(state.records, { stage: state.stage, type: state.type, range: null }));
```

- [ ] **Step 6: Check in a browser**

Serve as before. Two step lines rising left to right; blue above red; end labels match the "bills summarized" card plus its waiting count. Switch Stage to "Reported by committee": both lines shrink to that stage's bills.

- [ ] **Step 7: Commit**

```bash
git add dashboard
git commit -m "Bill Delay Tracker: cumulative bills with text vs summarized"
```

---

### Task 8: Cumulative pages of text vs pages summarized

**Files:**
- Modify: `dashboard/metrics.js` (add `cumulativePages`)
- Modify: `dashboard/metrics.test.mjs`
- Modify: `dashboard/dashboard.js` (generalize `renderCumulative` to take a series + labels; call it twice)
- Modify: `dashboard/index.html` (add `<figure id="cumulative-pages"></figure>` after `#cumulative`)

**Interfaces:**
- Produces: `cumulativePages(records) → [{date, pagesIssued, pagesSummarized, versionsWithoutPages}]` — `pagesIssued` sums `pages` over every version (any stage, including `null`) with `text_date` ≤ date; `pagesSummarized` sums `pages` of staged versions whose `summary_date` ≤ date; `versionsWithoutPages` is the running count of versions with `pages: null` so the chart can say how much is uncounted. One point per distinct date where either sum changes, sorted.

- [ ] **Step 1: Write the failing test**

Append to `metrics.test.mjs` (add `cumulativePages` to the import):
```js
test('cumulativePages sums pages issued and pages of summarized bills by date', () => {
  const s = cumulativePages([
    rec({ number: '1', text_date: '2025-01-03', summary_date: '2025-01-20', lag_days: 17, pages: 10 }),
    rec({ number: '2', text_date: '2025-01-03', pages: null }),
    rec({ number: '1', stage: null, text_date: '2025-02-01', pages: 12 }),
  ]);
  assert.deepEqual(s, [
    { date: '2025-01-03', pagesIssued: 10, pagesSummarized: 0, versionsWithoutPages: 1 },
    { date: '2025-01-20', pagesIssued: 10, pagesSummarized: 10, versionsWithoutPages: 1 },
    { date: '2025-02-01', pagesIssued: 22, pagesSummarized: 10, versionsWithoutPages: 1 },
  ]);
  assert.deepEqual(cumulativePages([]), []);
});
```

- [ ] **Step 2: Run tests to verify it fails**

Run: `node --test dashboard/metrics.test.mjs`
Expected: SyntaxError: `cumulativePages` not exported

- [ ] **Step 3: Add `cumulativePages` to `metrics.js`**

```js
/** Running page totals: pages of every text version issued, and pages of the staged versions whose summary has arrived. */
export function cumulativePages(records) {
  const issued = [], summarized = [], missing = [];
  for (const r of records) {
    if (r.pages === null) missing.push(r.text_date);
    else {
      issued.push([r.text_date, r.pages]);
      if (r.stage !== null && r.summary_date !== null) summarized.push([r.summary_date, r.pages]);
    }
  }
  const dates = [...new Set([...issued.map((p) => p[0]), ...summarized.map((p) => p[0]), ...missing])].sort();
  const running = (pairs) => { const sorted = pairs.sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0)); let i = 0, sum = 0; return (d) => { while (i < sorted.length && sorted[i][0] <= d) sum += sorted[i++][1]; return sum; }; };
  const pi = running(issued), ps = running(summarized), pm = running(missing.map((d) => [d, 1]));
  return dates.map((date) => ({ date, pagesIssued: pi(date), pagesSummarized: ps(date), versionsWithoutPages: pm(date) }));
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `node --test dashboard/metrics.test.mjs`
Expected: 9 passed

- [ ] **Step 5: Draw it by generalizing `renderCumulative`**

Change the Task 7 function's signature to `renderCumulative(target, series, keys, labels, title, yLabel)` where `keys = ['withText', 'summarized']` for bills and `['pagesIssued', 'pagesSummarized']` for pages, `labels` the two end-label suffixes, `target` the figure id. Replace the hard-coded `withText`/`summarized` with `keys[0]`/`keys[1]`, and the end labels with `labels[0]`/`labels[1]`. Call it twice from `render(state)`:
```js
  const unranged = filterRecords(state.records, { stage: state.stage, type: state.type, range: null });
  renderCumulative('#cumulative', cumulativeSeries(unranged), ['withText', 'summarized'], ['with text', 'summarized'],
    'Congress to date: bills with text issued, and bills with a CRS summary. The gap is the backlog.', 'bills');
  const allEditions = filterRecords(state.records, { stage: 'all', type: state.type, range: null });
  const pagesSeries = cumulativePages(allEditions);
  const uncounted = pagesSeries.length ? pagesSeries.at(-1).versionsWithoutPages : 0;
  renderCumulative('#cumulative-pages', pagesSeries, ['pagesIssued', 'pagesSummarized'], ['pages issued', 'pages summarized'],
    `Congress to date: pages of bill text issued, and pages covered by a CRS summary${uncounted ? ` (${fmt(uncounted)} versions not yet page-counted)` : ''}.`, 'pages');
```
Note the pages chart uses `stage: 'all'` so every edition's pages count, while the stage filter still governs which summaries count through `pagesSummarized`'s `stage !== null` check — document this in the chart title if the stage filter is not "all": append ` Summaries: ${state.stage} stage.` when `state.stage !== 'all'`.

- [ ] **Step 6: Check in a browser**

Serve as before. Two charts, same shape; the pages chart's title names how many versions are uncounted (600-ish before the full page sweep lands, 0 after). Blue above red in both.

- [ ] **Step 7: Commit**

```bash
git add dashboard
git commit -m "Bill Delay Tracker: cumulative pages issued vs pages summarized"
```
