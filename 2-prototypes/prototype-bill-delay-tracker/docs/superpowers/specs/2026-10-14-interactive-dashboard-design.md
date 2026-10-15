# Bill Delay Tracker: interactive dashboard

Decided with the maintainer, 2026-10-14. Replaces the static Python-rendered
report as the prototype's presentation; the Python pipeline stays.

## Purpose

An oversight reader (CRS, Library of Congress, journalists) asks "how bad is the
summary backlog and is it getting worse?". The dashboard answers with the four
metrics proposal IV.2 names and the distribution behind them. Bill-level lookup
is a later affordance, not in this spec.

## Constraints

- Lives in the assembly-line fork as a Stage 2 prototype; a later port to the
  Congressional Tech Astro site is in mind, so: static files, data as JSON, no
  server, no build step.
- d3 v7 from cdnjs, pinned; used for scales, shapes, axes, bins, brush. If d3
  is dropped later, only the drawing functions change.
- No new data collection. The first interactive version runs on the 119th
  Congress snapshot already on disk.
- Colors: summarized blue `#104378`, waiting red `#b2182b`, Source Sans.
- Built as a ladder of commits on one branch; every rung is hand-over-able.

## Data contract

`delays.py` writes `data/delays.json` beside `stats.json`:

```json
{"as_of": "2026-10-14", "congress": "119",
 "records": [{"type": "hr", "number": "360", "stage": "introduced",
              "text_date": "2025-01-13", "summary_date": "2026-10-01",
              "lag_days": 626, "pages": 12, "title": "..."}]}
```

One record per bill-stage. Waiting records carry `summary_date: null` and
`lag_days: null`. `pages` is `null` when not looked up. The page derives
everything from `records`; `stats.json` stays for the Python report.

## Page

`dashboard/index.html` + `dashboard/dashboard.js` + `dashboard/metrics.js`.
Fetches `../data/delays.json` relative to the page. Opens from
`python3 -m http.server` in the prototype folder.

Header row, recomputed from the filtered records: pages processed (with "n of m
versions counted"), bills summarized, bills reported by committee (a bill with an
`rh` or `rs` text version), mean /
median / max lag in days.

## Histogram

Lag in days for filtered records that have a summary. Default filter: stage
introduced, all bill types. Bins 30 days, last bin open-ended. Vertical rules
for median and mean. Count label on each bar. One red bar at the right edge,
"still waiting, n", so the censoring is visible rather than hidden.

## Interaction ladder

1. data contract (`delays.json`, test)
2. histogram + header row (static page; minimal hand-over)
3. filters: stage and bill type `<select>`s; header and histogram re-render
4. timeseries by month introduced under the histogram; d3 brush selects a
   date range that filters header and histogram; clearing resets
5. polish: bin width 7 / 30 / 90, hover tooltip (bin range, count, share of
   filtered), keyboard-reachable controls

State is one object; `render(state)` redraws everything from it.

## Error handling

Missing or malformed JSON shows one message in the page; nothing partial.

## Testing

- `tests/test_delays_json.py` (stdlib unittest): the contract on the fixture
  (keys, null handling, record count equals delays + awaiting).
- `dashboard/metrics.test.mjs` (`node --test`): pure functions in `metrics.js`
  (binning, header metrics) without a browser.
- Headless-chromium screenshot per rung as the maintainer's visual check.
