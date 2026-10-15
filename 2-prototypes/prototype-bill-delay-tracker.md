# Prototype: Bill Delay Tracker

**Builds on:** [idea-bill-delay-tracker.md](../1-ideas/idea-bill-delay-tracker.md)

## What this demonstrates

Three stdlib-only Python scripts collect bill text versions from GovInfo and CRS summaries from the Congress.gov API, join them by bill and stage, compute lag statistics, and render a self-contained HTML report with charts. The chain runs end to end on a bundled fixture without any API access.

## The fictionalized use case

The bundled fixture (`prototype-bill-delay-tracker/tests/fixture/`) is a four-row hand-made sample: two real-shaped text versions of one large bill, two introduced bills, and three summaries. It is illustrative only. Against live APIs the scripts pull real public data for the 119th Congress, but the prototype does not require that to be reviewed.

## What's in this prototype

Python 3.12, no dependencies. In [`prototype-bill-delay-tracker/`](prototype-bill-delay-tracker/):

| Script | Does |
| --- | --- |
| `collect.py` | Sweeps the GovInfo `BILLS` collection listing (one text version per row, 500 per request), fetches page counts from GovInfo package summaries (one call per version, capped and cached), and sweeps `api.congress.gov/v3/summaries/{congress}/{type}` for summary versions. Incremental and resumable: every page is saved as it lands. |
| `delays.py` | Maps text versions and summaries onto four stages (introduced, reported, passed, enrolled), takes the earliest of each per bill, writes `delays.csv`, `awaiting.csv` (introduced bills with no introduced-stage summary) and `stats.json` (counts, mean / median / max, per-stage stats, histograms). |
| `report.py` | Renders `stats.json` into `report.html`: stat cards, two SVG histograms, lag by stage, longest lags, oldest bills still waiting. Hand-rolled SVG in the Congressional Tech site's colors so it can move into the Astro site. |
| `keys.py` | Key lookup in the same order as the Congressional Tech repo's `congress_shared.auth`: `--api-key`, `DATA_GOV_API_KEY`, `~/.data.gov.api.key`; falls back to `DEMO_KEY`. |

Real: the collectors, the join, the statistics, the report. Faked: nothing, but the fixture is tiny and the live sweep is capped by default so it finishes on `DEMO_KEY`.

## How to run it

```
git clone https://github.com/CameronPeltz/ideas_assembly_line
cd ideas_assembly_line/2-prototypes/prototype-bill-delay-tracker

# 1. No API key needed: compute and render the bundled fixture
python3 delays.py --data-dir tests/fixture --as-of 2026-10-14
python3 report.py --data-dir tests/fixture --out tests/fixture/report.html
# open tests/fixture/report.html

# 2. Live data (free key from https://api.congress.gov/sign-up/, one key covers GovInfo too)
echo YOUR_KEY > ~/.data.gov.api.key
python3 collect.py --congress 119 --max-version-pages 60 --max-page-lookups 200 --max-summary-requests 60
python3 delays.py
python3 report.py
# open report.html
```

`collect.py --help` lists the caps. Rerunning only fetches what is new.

## Known limitations

- Lag is measured to the summary's **last update** date, the only date the Congress.gov API exposes, so a summary CRS revised later overstates the lag. The report says so on the page.
- The text version date is the date printed on the version, not the moment GovInfo posted it.
- `DEMO_KEY` is throttled to about 30 requests per hour per IP and the Congress.gov summaries list endpoint is slow (sometimes over a minute per page), so a full-Congress sweep needs a registered key and patience.
- Page counts cover only the versions looked up so far; the report shows the coverage fraction.
- No daily refresh job, no history, no site integration. Those are the production tool.
