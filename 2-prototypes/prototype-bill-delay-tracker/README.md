# Bill Delay Tracker prototype

See [`../prototype-bill-delay-tracker.md`](../prototype-bill-delay-tracker.md) for what this is and how to run it.

`collect.py` → `data/*.csv` → `delays.py` → `data/stats.json` + `data/delays.json` → `report.py` → `report.html`, or `dashboard/` for the interactive view.
`tests/fixture/` runs the last two steps with no network.
`dashboard/index.html` is the interactive view of `data/delays.json`; serve the prototype folder (`python3 -m http.server`) and open `/dashboard/`. Page-wide filters sit in the top row: stage, bill type, an introduced-from/to month range (blank = open side), and a checkbox to include bills still waiting for a summary in the histogram; the histogram has a bin-width slider (7 to 90 days) beneath it.
