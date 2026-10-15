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
- d3 v7 from cdnjs, pinned; used for scales, shapes, axes. If d3
  is dropped later, only the drawing functions change.
- No new data collection. The first interactive version runs on the 119th
  Congress snapshot already on disk.
- Colors: summarized blue `#104378`, waiting red `#b2182b`, Source Sans.
- Built as a ladder of commits on one branch; every rung is hand-over-able.

## Data contract

`delays.py` writes `data/delays.json` beside `stats.json`:

```json
{"as_of": "2026-10-14", "congress": "119",
 "summary_before_text": {"introduced": 41, "reported": 2},
 "records": [{"type": "hr", "number": "360", "stage": "introduced",
              "text_date": "2025-01-13", "summary_date": "2026-10-01",
              "lag_days": 626, "pages": 12, "reported": false, "title": "..."}]}
```

One record per text version. `stage` is `introduced`, `reported`, `passed` or
`enrolled` for the earliest edition mapped to that stage and `null` for unmapped
editions and for later editions of an already-staged stage; `null`-stage records
carry `pages` only and never a summary. `reported` is true when the bill has an
`rh` or `rs` text version. Waiting records carry `summary_date: null` and
`lag_days: null`. `pages` is `null` when not looked up.
`summary_before_text` counts summaries, by stage, whose bill has no text version at
that stage in GovInfo. The page derives everything from `records`; `stats.json`
stays for the Python report.

## Page

`dashboard/index.html` + `dashboard/dashboard.js` + `dashboard/metrics.js`.
Fetches `../data/delays.json` relative to the page. Opens from
`python3 -m http.server` in the prototype folder.

Header row, recomputed from the filtered records: pages processed (with "n of m
versions counted"), bills summarized, bills reported by committee (distinct bills with a reported-stage record under the type
filter and month range, ignoring the stage select), mean /
median / max lag in days.

## Histogram

Lag in days for filtered records that have a summary. Default filter: all
stages, all bill types (with all stages the bars count staged text versions with a summary, one per bill per stage; with one stage they count bills). Fixed-width bins from 0 to the largest lag in view (30 days
by default, no open-ended last bin). Vertical rules for median and mean. Count label on each
bar when the bar is wide enough; x labels are thinned to about 48 px apart. One red bar at the
right edge, "still waiting", on the same linear scale as the bins, so the censoring is visible
and the chart is to scale. The checkbox "Include bills still waiting for a summary", in the
histogram's control strip beside the bin-width slider (it applies to the histogram only; on by default), draws that bar; off, the bar goes and the scale falls to the tallest bin. The
title names both counts either way. The strip under the chart holds the slider (7 to 90 days), which sets the bin width, then the checkbox; both re-render the histogram only.

## Interaction ladder

1. data contract (`delays.json`, test)
2. histogram + header row (static page; minimal hand-over)
3. filters: stage (default "All stages", listed first) and bill type `<select>`s; header and histogram re-render
4. timeseries by month introduced under the histogram; the month range is set in
   the top controls row (Introduced from / to, two `<select>`s listing the months present in the data,
   "Jan 2025" to the last month, in order; a blank first option = open side; "Clear date filters"
   resets both; from after to = no range). Tab order: stage, type, from, to, clear, then the
   histogram's slider and checkbox) and filters every card and chart; the chart shades the selected months
5. polish: bin width slider, hover tooltip (bin range, count, share of
   filtered), keyboard-reachable controls
6. cumulative bills with text vs bills with a CRS summary (the gap is the backlog)
   Charts 6 and 7 use the same type filter and month range as the cards; titles read "Congress to date", or name the range ("Jul 2025 – Feb 2026", "from Jul 2025", "to Feb 2026").
7. cumulative pages of text issued vs pages covered by a summary (follows the stage filter)

State is one object; `render(state)` redraws everything from it.

## Error handling

Missing or malformed JSON shows one message in the page; nothing partial.

## Testing

- `tests/test_delays_json.py` (stdlib unittest): the contract on the fixture
  (keys, null handling, record count equals the number of text versions).
- `dashboard/metrics.test.mjs` (`node --test`): pure functions in `metrics.js`
  (binning, header metrics) without a browser.
- Headless-chromium screenshot per rung as the maintainer's visual check.
