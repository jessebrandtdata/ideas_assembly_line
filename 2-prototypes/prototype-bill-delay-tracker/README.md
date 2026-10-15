# Bill Delay Tracker prototype

See [`../prototype-bill-delay-tracker.md`](../prototype-bill-delay-tracker.md) for what this is and how to run it.

`collect.py` → `data/*.csv` → `delays.py` → `data/stats.json` + `data/delays.json` → `report.py` → `report.html`, or `dashboard/` for the interactive view.
`tests/fixture/` runs the last two steps with no network.
`dashboard/index.html` is the interactive view of `data/delays.json`; serve the prototype folder (`python3 -m http.server`) and open `/dashboard/`. Page-wide filters sit in the top row: stage (default all stages), bill type, an introduced-from/to date range (two day-level date pickers bounded by the first and last text date in the data; empty = open side; inclusive, on the text version's issue date) and a "Clear date filters" button; a monthly stacked-share chart (summarized vs waiting, by month the text was issued; no lag-over-time lines, which right-censoring would make misleading) shades the months the range touches; beneath the histogram are its own controls, a bin-width slider (7 to 90 days) and a checkbox to include bills still waiting for a summary.
