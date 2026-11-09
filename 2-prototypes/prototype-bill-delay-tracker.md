# Prototype: Bill Delay Tracker

**Builds on:** [idea-bill-delay-tracker.md](../1-ideas/idea-bill-delay-tracker.md)

## What this demonstrates

Python scripts collect bill text versions and CRS summaries (from Civic Tech DC's spicy-regs warehouse, or from the GovInfo and Congress.gov APIs), join them by bill and stage, and compute lag statistics; a d3 dashboard page, opened straight from disk, charts the result. The chain runs end to end on a bundled fixture without any API access.

## The fictionalized use case

The bundled fixture (`prototype-bill-delay-tracker/tests/fixture/119/`) is a four-row hand-made sample: two real-shaped text versions of one large bill, two introduced bills, and three summaries. It is illustrative only. Against the warehouse and the live APIs the scripts pull real public data for any Congress from the 108th on, but the prototype does not require that to be reviewed.

## What's in this prototype

Python 3.12; `collect_warehouse.py` needs `duckdb` to read Parquet, everything else is stdlib. In [`prototype-bill-delay-tracker/`](prototype-bill-delay-tracker/):

| Script | Does |
| --- | --- |
| `congress.py` | What the other scripts share: the eight measure types (bills, joint, concurrent and simple resolutions), the Congress in session on a date (every Congress since the 74th begins January 3 of an odd year), and the `--congress` option (numbers, ranges like `113-119`, `current`, `previous`, `all`). No script names a Congress number, so they move to the 120th on 2027-01-03 without an edit. |
| `collect_warehouse.py` | Reads the current bill-family generation of the spicy-regs warehouse (`data.spicygov.ai`, pointer `publication.v2.json`) into one folder per Congress, `data/<congress>/`: `bill_versions` joined to `congress_bills` for titles becomes `versions.csv`, and `bill_publisher_summaries`, which keeps every dated revision of a summary, becomes `summaries.csv` with the earliest retained revision as the publication date `delays.py` measures to. All eight measure types by default (`--bill-types` narrows it). Without `--congress` it refreshes every Congress already on disk plus the current one; `--congress all` reads every Congress the warehouse lists (the 108th on). A Congress with no text versions yet is skipped and a folder on disk is never emptied. No API key, no rate limit; `warehouse.json` records the generation read. |
| `collect.py` | The original API collectors, per Congress folder. Sweeps the GovInfo `BILLS` collection listing (one text version per row, 500 per request), fetches page counts from GovInfo package summaries and the ingest date from each version's MODS record (one call per version each, capped and cached), and sweeps `api.congress.gov/v3/summaries/{congress}/{type}` for summary versions. Defaults to the current and previous Congress, swept from the day each began; the caps are for the whole run, newest Congress first. Incremental and resumable: rows are saved as they land, through a rename so a stopped run never truncates the cache. |
| `delays.py` | For every `data/<congress>/` folder: maps text versions and summaries onto four stages (introduced, reported, passed, enrolled), takes the earliest of each per bill, measures lag from the day GovInfo took the text in (`ingest.csv`, or the date printed on the bill where no ingest date was collected; it rides along as `printed_date`) to the summary's first retained publication, and writes `delays.csv`, `awaiting.csv` (introduced bills with no introduced-stage summary), `stats.json` (counts, mean / median / max, per-stage stats, histograms, and a `comparison` block measured from the printed date in every Congress, per bill type) and `delays.json`, one record per staged text version, the dashboard's input. The same document is written again as `delays.js` so the dashboard can load it from disk, where browsers block `fetch()` of local files. Last it writes `data/congresses.json` and `.js`, the index of Congress folders the dashboard opens with. A version with no date at all is left out and counted. |
| `dashboard/` | The view of the data, `index.html` opened from disk or served. A Congress picker (every Congress in the index, opening on the newest one that has an introduced bill) loads that Congress's `delays.js` when it is picked. It measures the introduced stage only, the one CRS is summarizing in the 119th Congress and the one every Congress has; proposal IV.2 asks for no breakdown by stage, and the later-stage summaries are counted in the page's caveat and kept in the data. Header metrics (the proposal's four: pages, bills summarized, bills reported by committee, mean / median / max lag), a by-Congress chart (share of introduced bills summarized and median days from the printed date, every Congress side by side), lag histogram (bin-width slider, with or without bills still waiting), bill-type filter listing the types the Congress has, date-range filter, monthly summarized-vs-waiting shares, cumulative bills and cumulative pages (issued vs summarized), two top-10 tables, PNG / SVG / CSV exports. Hand-rolled d3 v7 (from cdnjs) in the Congressional Tech site's colors so it can move into the Astro site; pure computations in `metrics.js` under `node --test`. |
| `keys.py` | Key lookup in the same order as the Congressional Tech repo's `congress_shared.auth`: `--api-key`, `DATA_GOV_API_KEY`, `~/.data.gov.api.key`; falls back to `DEMO_KEY`. |

Real: the collectors, the join, the statistics, the dashboard. Faked: nothing, but the fixture is tiny and the live sweep is capped by default so it finishes on `DEMO_KEY`.

## How to run it

```
git clone https://github.com/CameronPeltz/ideas_assembly_line
cd ideas_assembly_line/2-prototypes/prototype-bill-delay-tracker

# 1. No API key needed: compute the bundled fixture and run the tests
python3 delays.py --data-dir tests/fixture --as-of 2026-10-14
node --test dashboard/metrics.test.mjs && python3 -m unittest discover -s tests

# 2. Live data from the warehouse (no key), then page counts and ingest dates from GovInfo
#    (free key from https://api.congress.gov/sign-up/, one key covers GovInfo too)
python3 -m pip install duckdb
python3 collect_warehouse.py --congress all     # every Congress the warehouse has; later runs need no flag
echo YOUR_KEY > ~/.data.gov.api.key
python3 collect.py --skip versions summaries --max-page-lookups 200 --max-ingest-lookups 200
python3 delays.py
# open dashboard/index.html in a browser (no server needed; or serve the folder and open /dashboard/)
python3 build_site.py --out _site   # optional: the same static site the Pages workflow publishes
```

## Data in git, data built

The bulk data is not committed. `collect_warehouse.py` and `delays.py` rebuild it in about a minute with no key, so git keeps only what is small or slow to rebuild: `data/congresses.json` and, per Congress, `stats.json` and `warehouse.json` (a dated snapshot of the numbers), plus the 119th Congress's `pages.csv` and `ingest.csv` (one GovInfo call per text version). `.gitignore` lists the rest. This follows the Congressional Tech repo, which keeps raw caches off `main` and builds its site's data in Actions.

`.github/workflows/bill-delay-tracker.yml` publishes the dashboard to GitHub Pages every day at 07:00 UTC (the warehouse publishes its nightly generation around 04:30 UTC), on demand, and on pushes to `main` that touch the prototype: it reads the warehouse, looks up GovInfo page counts and ingest dates for the Congress in session when the `DATA_GOV_API_KEY` secret is set (a GitHub cache carries them between runs, merged with the committed files and never replacing a row), runs `delays.py` and the tests, and deploys what `build_site.py` assembles. It commits nothing back. Repository settings it needs: Pages source "GitHub Actions"; on a fork, Actions enabled; the secret is optional (without it new versions are measured from the printed date and the page says how many).

`collect.py --help` lists the caps. Rerunning only fetches what is new; `collect_warehouse.py` rewrites its two files per Congress from the current generation each run. The same three commands with no `--congress` are the refresh: the warehouse step re-reads every Congress on disk plus the current one, `collect.py` looks up the current and previous Congress, `delays.py` rebuilds every folder. On 2027-01-03 that refresh starts a `data/120/` folder by itself, as soon as the warehouse lists a 120th Congress text version, and keeps finishing the 119th. The original all-API path (`python3 collect.py --congress 119 --max-version-pages 60 --max-summary-requests 60 ...`) still works.

## Live result, snapshot of 2026-10-15

`data/` in the prototype folder is a real run against the 119th Congress (collected 2026-10-15, ingest dates 2026-10-17; complete sweeps: 19,982 text versions from GovInfo, 5,337 CRS summary versions from Congress.gov, page counts and ingest dates for every version, 255,049 pages).

- 16,873 bills have text; 5,195 have at least one CRS summary; 11,989 introduced bills have no introduced-stage summary yet.
- Introduced text on GovInfo to introduced summary: n=4,779, median 85 days, mean 147.3 days, max 601 days (subject to the last-update caveat below). Measured from the printed date instead, as the first draft did, the median was 106 days: GovInfo posts an introduced bill a median 12 days after its printed date, 28 days at the 90th percentile.
- 6 introduced summaries are dated before their text reached GovInfo; the dashboard counts them and leaves them out of the histogram.
- 1,217 bills have a reported (rh/rs) text version. 511 later-stage summaries exist (337 reported, the rest passed and enrolled), the CRS exceptions; they stay in `delays.csv` and `delays.json` under their stage and the dashboard counts them in its caveat.
- Coverage by month of introduction: bills introduced in February 2025 are about 89% summarized, April 2025 40%, May 28%, and every month since about 10%. The 85-day median is the lag for the minority that got a summary at all; the monthly share chart shows the rest.

Regenerate with the two commands in "How to run it"; `collect.py` only fetches what is new.

## Across Congresses, snapshot of 2026-11-09

Built from the warehouse generation published 2026-11-08, all eight measure types; each Congress's committed `stats.json` holds these numbers. Introduced bills (every type), measured from the date printed on the bill to the summary, which is the one start every Congress has:

| Congress | introduced | summarized | median days |
| --- | --- | --- | --- |
| 108th (2003–2004) | 9,909 | 100% | 119 |
| 109th–113th (2005–2014) | 9,942 to 13,006 each | 100% | 29 to 37 |
| 114th (2015–2016) | 11,350 | 100% | 40 |
| 115th (2017–2018) | 12,869 | 99.9% | 132 |
| 116th (2019–2020) | 15,960 | 100% | 172 |
| 117th (2021–2022) | 17,090 | 99.95% | 103 |
| 118th (2023–2024) | 18,593 | 61% | 132 |
| 119th (2025–, in session) | 19,162 | 29% so far | 107 |

Through the 117th CRS summarized every introduced measure; the 118th left 39% without one, and the 119th is on the introduced-only policy. Part of the 108th's long median, and of the 115th to 117th's, may be the summary-date caveat below rather than a slow CRS: those Congresses carry 3,897, 3,586, 3,728 and 2,520 introduced summaries dated after the Congress ended, and the page counts them for the Congress in view. Only the 119th has GovInfo page counts and ingest dates so far (every one of its 23,215 text versions); the other Congresses are measured from the printed date and the page says so.

## Known limitations

- **CRS writes summaries for introduced versions only in the 119th Congress** ("CRS is not writing bill summaries for subsequent versions of measures as they move through the legislative process", Congress.gov help, Bill Summaries, read 2026-10-16). The dashboard measures the introduced stage only and says so; `delays.py` still maps the later stages, so the exceptions CRS did write are in the CSVs and JSON for anyone who wants them.
- The Congress.gov API exposes no first-publication date for a summary, only `lastSummaryUpdateDate`, so a summary CRS revised later overstates the lag; the warehouse path recovers the first publication for summaries captured since 2026-11-06 (see "Old Congresses' summary dates" below). The dashboard says so on the page. The README's "Which dates" section lists every date field both APIs offer and why these were picked; a daily collection that records when each text version and summary is first seen would replace both inferred dates with observed ones.
- The text date is the day GovInfo ingested the version (its MODS `dateIngested`, "the date the document was ingested into the GovInfo preservation repository"), days to weeks after the date printed on the bill; both are in the CSVs. GovInfo does not say an ingested package is public the same day, and the proposal's wording is publication on Congress.gov, for which the Congress.gov API has no per-version date. GovInfo's `lastModified` cannot stand in for it: a bulk reprocess in July 2026 reset it for most of the Congress.
- **Old Congresses' summary dates.** The warehouse has kept every revision of a summary since 2026-11-06; a summary first captured before that carries only its latest revision. For an ended Congress that is sometimes a re-publication years later (a 110th Congress introduced summary reads 2012), so its lag reads long. `stats.json` counts the introduced summaries dated after the Congress ended (`summaries_after_end`) and the page shows the count; they are not dropped, because a summary written after a Congress ends is also possible.
- **Old Congresses' ingest dates.** GovInfo's `dateIngested` for a bill printed before GovInfo's predecessor was migrated is the migration (a 110th Congress introduced bill reads 2010-09-21), not a posting date. `collect.py` looks up the current and previous Congress by default; looking up ingest dates for older Congresses spends API calls on dates that do not mean publication, so they are measured from the printed date. A 113th Congress bill's ingest date is 13 days after its printed date, so the switch is somewhere before that.
- `DEMO_KEY` is throttled to about 30 requests per hour per IP and the Congress.gov summaries list endpoint is slow (sometimes over a minute per page), so a full-Congress sweep needs a registered key and patience.
- Page counts cover only the versions looked up so far; the dashboard says how many versions are not yet counted.
- A daily Pages build, but no history of first-seen dates and no site integration. Those are the production tool.
