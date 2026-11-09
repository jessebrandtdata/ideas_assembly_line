# Prototype: Bill Delay Tracker

**Builds on:** [idea-bill-delay-tracker.md](../1-ideas/idea-bill-delay-tracker.md)

## What this demonstrates

Python scripts read bill text versions, their size and CRS summaries from Civic Tech DC's spicy-regs warehouse, join them by bill and stage, and compute lag statistics; a d3 dashboard page, opened straight from disk or published to GitHub Pages, charts the result. No API key and no per-bill API calls. The chain runs end to end on a bundled fixture without any network.

## The fictionalized use case

The bundled fixture (`prototype-bill-delay-tracker/tests/fixture/119/`) is a four-row hand-made sample: two real-shaped text versions of one large bill, two introduced bills, and three summaries. It is illustrative only. Against the warehouse the scripts pull real public data for every Congress from the 108th on, but the prototype does not require that to be reviewed.

## What's in this prototype

Python 3.12; `collect_warehouse.py` needs `duckdb` to read Parquet, everything else is stdlib. In [`prototype-bill-delay-tracker/`](prototype-bill-delay-tracker/):

| Script | Does |
| --- | --- |
| `congress.py` | What the other scripts share: the eight measure types (bills, joint, concurrent and simple resolutions), the Congress in session on a date (every Congress since the 74th begins January 3 of an odd year), and the `--congress` option (numbers, ranges like `113-119`, `current`, `previous`, `all`). No script names a Congress number, so they move to the 120th on 2027-01-03 without an edit. |
| `collect_warehouse.py` | Reads the current bill-family generation of the spicy-regs warehouse (`data.spicygov.ai`, pointer `publication.v2.json`) into one folder per Congress, `data/<congress>/`: `bill_versions` joined to `congress_bills` for titles and to `bill_sections` (the parsed bill text, one row per section) for each printing's size becomes `versions.csv` (columns `sections` and `characters`, and `pages` once the warehouse publishes a page count); `bill_publisher_summaries`, which keeps every dated revision of a summary, becomes `summaries.csv` with the earliest retained revision as the publication date `delays.py` measures to. All eight measure types by default (`--bill-types` narrows it). Without `--congress` it refreshes every Congress already on disk plus the current one; `--congress all` reads every Congress the warehouse lists (the 108th on). A Congress with no text versions yet is skipped and a folder on disk is never emptied. `warehouse.json` records the generation read. |
| `collect_govinfo.py` | Optional, off by default: the page counts proposal IV.2 asks for, which the warehouse does not have. One GovInfo call per printing fetches its MODS record, which carries the page count (`<extent>9 p.</extent>`) and GovInfo's ingest date, into `data/<congress>/govinfo.csv` (cached, resumable, newest printings first, `--max-lookups` per run, the current Congress by default). `delays.py` fills the pages column from it and the dashboard offers pages first wherever counts exist; a printing without one is unmeasured, never zero. The ingest date is kept for reference only. The 119th Congress's `govinfo.csv` is committed with all 23,215 of its printings, from lookups made between 2026-10-15 and 2026-11-09. |
| `keys.py` | API key lookup for `collect_govinfo.py`, in the order the Congressional Tech repo's `congress_shared.auth` uses: `--api-key`, `DATA_GOV_API_KEY`, `~/.data.gov.api.key`; falls back to `DEMO_KEY`. |
| `delays.py` | For every `data/<congress>/` folder: maps text versions and summaries onto four stages (introduced, reported, passed, enrolled), takes the earliest of each per bill, measures lag from the date printed on the introduced text to the bill's first CRS summary, whatever version it describes (a bill CRS never summarized as introduced, such as S. 1869 of the 115th, runs to its first later summary; `summary_stage` names that version), and writes `delays.csv`, `awaiting.csv` (bills with introduced text and no CRS summary at any stage), `stats.json` (counts, sizes, mean / median / max, per-stage stats, histograms, and a per-type `comparison` block) and `delays.json`, one record per text version, the dashboard's input. The same document is written again as `delays.js` so the dashboard can load it from disk, where browsers block `fetch()` of local files. Last it writes `data/congresses.json` and `.js`, the index of Congress folders the dashboard opens with. A version with no printed date, or one dated after the as-of date (the warehouse has a 109th Congress bill printed "2066-06-07"), is left out and counted. |
| `build_site.py` | Assembles the static site the Pages workflow publishes: the dashboard and the data files it reads, in the same relative layout. |
| `dashboard/` | The view of the data, `index.html` opened from disk or served. A Congress picker loads each Congress's `delays.js` when it is needed, with a loading banner (what is loading, how many files have arrived) while the figures below dim. It opens on the newest Congress that has an introduced bill, so the first load is one Congress's file; "All Congresses", every Congress in the index pooled into one view (each bill keeps its Congress in its key, label, link and CSV row), heads the list, followed by each Congress on its own. It measures the introduced stage only, the one CRS is summarizing in the 119th Congress and the one every Congress has; proposal IV.2 asks for no breakdown by stage, and the later-stage summaries are counted in the page's caveat and kept in the data. Header metrics (the proposal's four: size of bill text, bills summarized, bills reported by committee, mean / median / max lag), a "Bill size in" picker (characters or sections; pages appears when the data carries it), lag histogram, a by-Congress chart below it (share of introduced bills summarized and median days, the Congresses in view side by side; shown only when the data in view spans more than one Congress) (bin-width slider, with or without bills still waiting), bill-type filter listing the types the Congress has, printed-date range filter, monthly summarized-vs-waiting shares, cumulative bills and cumulative size (issued vs summarized), two top-10 tables, PNG / SVG / CSV exports. Hand-rolled d3 v7 (from cdnjs) in the Congressional Tech site's colors so it can move into the Astro site; pure computations in `metrics.js` under `node --test`. |

Real: the collector, the join, the statistics, the dashboard. Faked: nothing, but the fixture is tiny.

## How to run it

```
git clone https://github.com/CameronPeltz/ideas_assembly_line
cd ideas_assembly_line/2-prototypes/prototype-bill-delay-tracker

# 1. No network: compute the bundled fixture and run the tests
python3 delays.py --data-dir tests/fixture --as-of 2026-10-14
node --test dashboard/metrics.test.mjs && python3 -m unittest discover -s tests

# 2. Live data from the warehouse (no key; about two minutes, most of it reading section sizes)
python3 -m pip install duckdb
python3 collect_warehouse.py --congress all     # every Congress the warehouse has; later runs need no flag
python3 collect_govinfo.py --max-lookups 200   # optional: page counts for the current Congress (api.data.gov key)
python3 delays.py
# open dashboard/index.html in a browser (no server needed; or serve the folder and open /dashboard/)
python3 build_site.py --out _site   # optional: the same static site the Pages workflow publishes
```

The same two commands with no `--congress` are the refresh: the warehouse step re-reads every Congress on disk plus the current one, `delays.py` rebuilds every folder. On 2027-01-03 that refresh starts a `data/120/` folder by itself, as soon as the warehouse lists a 120th Congress text version, and keeps finishing the 119th.

## Data in git, data built

The bulk data is not committed. `collect_warehouse.py` and `delays.py` rebuild it with no key, so git keeps only a small dated snapshot: `data/congresses.json` and, per Congress, `stats.json` and `warehouse.json`. `.gitignore` lists the rest. This follows the Congressional Tech repo, which keeps raw caches off `main` and builds its site's data in Actions.

`.github/workflows/bill-delay-tracker.yml` publishes the dashboard to GitHub Pages every day at 07:00 UTC (the warehouse publishes its nightly generation around 04:30 UTC), on demand, and on pushes to `main` that touch the prototype: it reads the warehouse, runs `delays.py` and the tests, and deploys what `build_site.py` assembles. It commits nothing back and by default needs no secret. Repository settings it needs: Pages source "GitHub Actions"; on a fork, Actions enabled. To add page counts for new printings of the Congress in session, set the repository variable `GOVINFO_PAGES` to `true` and the secret `DATA_GOV_API_KEY`: the run then calls `collect_govinfo.py` (up to 2,000 lookups, carried between runs in an Actions cache on top of the committed `govinfo.csv`). Without them, the committed counts still show and newer printings are counted as without a page count.

## Live result, snapshot of 2026-10-15 (earlier method)

This first run measured differently and is kept as the record of it: it collected the 119th Congress from the GovInfo and Congress.gov APIs and started each lag at the day GovInfo took the text in (MODS `dateIngested`), with GovInfo page counts. Both took one API call per text version, and the prototype dropped them on 2026-11-09 for the warehouse alone.

- 16,873 bills had text; 5,195 had at least one CRS summary; 11,989 introduced bills had no introduced-stage summary yet; 255,049 pages over 19,982 text versions.
- Introduced text on GovInfo to introduced summary: n=4,779, median 85 days. Measured from the printed date instead, as the prototype does now, the median was 106 days: GovInfo posted an introduced bill a median 12 days after its printed date, 28 days at the 90th percentile.
- Coverage by month of introduction: bills introduced in February 2025 were about 89% summarized, April 2025 40%, May 28%, and every month since about 10%.

## Across Congresses, snapshot of 2026-11-09

Built from the warehouse generation published 2026-11-08, all eight measure types; each Congress's committed `stats.json` holds these numbers. Introduced bills (every type), measured from the date printed on the introduced text to the bill's first CRS summary, whatever version it describes:

| Congress | introduced | summarized | median days |
| --- | --- | --- | --- |
| 108th (2003–2004) | 9,909 | 100% | 116 |
| 109th–113th (2005–2014) | 9,942 to 13,006 each | 100% | 28 to 37 |
| 114th (2015–2016) | 11,350 | 100% | 40 |
| 115th (2017–2018) | 12,869 | 100% | 132 |
| 116th (2019–2020) | 15,960 | 100% | 172 |
| 117th (2021–2022) | 17,090 | 99.95% | 103 |
| 118th (2023–2024) | 18,593 | 61% | 133 |
| 119th (2025–, in session) | 19,162 | 31% so far | 115 |

Through the 117th CRS summarized every introduced measure; the 118th left 39% without one, and the 119th is on the introduced-only policy. Part of the 108th's long median, and of the 115th to 117th's, may be the summary-date caveat below rather than a slow CRS: those Congresses carry 3,524, 3,600, 3,725 and 2,520 first summaries dated after the Congress ended, and the page counts them for the Congress in view.

Size: the warehouse has parsed text, and so a section and character count, for about 99.8% of printings from the 110th Congress on, 69% of the 109th's and 11% of the 108th's; the page says how many versions in view have no parsed text.

## Known limitations

- **Pages.** Proposal IV.2 counts "the total number of pages in the bills processed". The warehouse publishes no page count (2026-11-09). GovInfo has it in each printing's MODS record (`<extent>9 p.</extent>`, the same record that carries `dateIngested`), one call per printing: `collect_govinfo.py` makes those calls when asked, and the 119th Congress's counts are committed, so the dashboard offers pages for it and characters or sections everywhere. Older Congresses have no page counts unless someone runs the lookups for them. Publishing the count on the warehouse's `bill_versions` would make the calls unnecessary: `collect_warehouse.py` reads a `pages` column when there is one.
- **CRS writes summaries for introduced versions only in the 119th Congress** ("CRS is not writing bill summaries for subsequent versions of measures as they move through the legislative process", Congress.gov help, Bill Summaries, read 2026-10-16). The dashboard measures the introduced stage only and says so; `delays.py` still maps the later stages, so the summaries CRS wrote for them are in the CSVs and JSON for anyone who wants them.
- **The text date is the printed date**, the publisher's version date, days to weeks before the text is readable online (the 2026-10-15 snapshot put GovInfo's posting a median 12 days later). Neither source states when the text appeared on Congress.gov, the proposal's wording. The warehouse's build receipts record when its reader first saw each printing (`observed_at`), but only on the receipts, and for printings older than the reader it is a backfill date (the 119th Congress's H.R. 1 as reported, printed 2025-05-20, reads 2026-09-26). The README's "Which dates" section lists every date field and why the printed date was picked.
- **Old Congresses' summary dates.** The warehouse has kept every revision of a summary since 2026-11-06; a summary first captured before that carries only its latest revision. For an ended Congress that is sometimes a re-publication years later (a 110th Congress introduced summary reads 2012), so its lag reads long. `stats.json` counts the introduced summaries dated after the Congress ended (`summaries_after_end`) and the page shows the count; they are not dropped, because a summary written after a Congress ends is also possible.
- A daily Pages build, but no history of first-seen dates and no site integration. Those are the production tool.
