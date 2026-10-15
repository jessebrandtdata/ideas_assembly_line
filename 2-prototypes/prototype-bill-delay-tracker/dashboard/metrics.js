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
