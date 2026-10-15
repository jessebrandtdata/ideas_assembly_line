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

/** Records in view. range is null or [fromISO, toISO], inclusive on text_date. */
export function filterRecords(records, { stage = 'all', type = 'all', range = null }) {
  return records.filter((r) =>
    (stage === 'all' || r.stage === stage) &&
    (type === 'all' || r.type === type) &&
    (range === null || (r.text_date >= range[0] && r.text_date <= range[1])));
}

/** Per month of text_date: how many got a summary, how many wait, and lag quantiles among the summarized. */
export function monthlySeries(records) {
  const byMonth = new Map();
  for (const r of records) {
    if (r.stage === null) continue; // later editions never get a summary of their own
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
