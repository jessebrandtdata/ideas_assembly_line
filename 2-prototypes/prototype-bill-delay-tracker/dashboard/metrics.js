// Pure computations for the dashboard. No d3, no DOM, so node --test covers them.

const billKey = (r) => `${r.type}${r.number}`;

function median(sorted) {
  const n = sorted.length;
  if (n === 0) return null;
  return n % 2 ? sorted[(n - 1) / 2] : (sorted[n / 2 - 1] + sorted[n / 2]) / 2;
}

/** Header-row numbers over the records in view. lag* are null when nothing is summarized.
 *  waiting = distinct bills with a staged record and no summary in the set, so summarized + waiting === bills. */
export function headerMetrics(records) {
  const summarizedBills = new Set(records.filter((r) => r.lag_days !== null).map(billKey));
  const waitingBills = new Set(records.filter((r) => r.stage !== null && !summarizedBills.has(billKey(r))).map(billKey));
  const summarized = records.filter((r) => r.lag_days !== null);
  const lags = summarized.map((r) => r.lag_days).sort((a, b) => a - b);
  const withPages = records.filter((r) => r.pages !== null);
  return {
    bills: new Set(records.map(billKey)).size,
    summarized: summarizedBills.size,
    waiting: waitingBills.size,
    reported: new Set(records.filter((r) => r.stage === 'reported').map(billKey)).size,
    pagesTotal: withPages.reduce((s, r) => s + r.pages, 0),
    pagesCounted: withPages.length,
    versions: records.length,
    n: lags.length,
    lagMean: lags.length ? lags.reduce((a, b) => a + b, 0) / lags.length : null,
    lagMedian: median(lags),
    lagMax: lags.length ? lags[lags.length - 1] : null,
  };
}

/** Top of the histogram y scale: the tallest bin, or the waiting count when that bar is drawn and taller. One linear scale. */
export function histogramMax(bins, waiting = 0) {
  return Math.max(1, waiting, ...bins.map((b) => b.count));
}

/** Fixed-width bins of lag_days from 0 to the largest lag in view; no open-ended bin. */
export function binLags(records, width) {
  const lags = records.filter((r) => r.lag_days !== null).map((r) => r.lag_days);
  if (lags.length === 0) return [];
  const count = Math.floor(Math.max(0, ...lags) / width) + 1;
  const bins = Array.from({ length: count }, (_, i) => ({ from: i * width, to: (i + 1) * width, count: 0 }));
  for (const lag of lags) bins[Math.min(Math.max(0, Math.floor(lag / width)), count - 1)].count += 1;
  return bins;
}

/** Records in view. range is null or {from, to} as 'YYYY-MM' or null (open side); inclusive on the introduction month.
 *  A from later than to is treated as no range. */
export function filterRecords(records, { stage = 'all', type = 'all', range = null }) {
  const from = range?.from || null, to = range?.to || null;
  const ranged = !(from && to && from > to) && (from || to);
  return records.filter((r) => {
    if (stage !== 'all' && r.stage !== stage) return false;
    if (type !== 'all' && r.type !== type) return false;
    if (!ranged) return true;
    const month = r.text_date.slice(0, 7);
    return (!from || month >= from) && (!to || month <= to);
  });
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

/** Running page totals (summaries restricted to `stage` unless 'all'): pages of every text version issued, and pages of the staged versions whose summary has arrived. */
export function cumulativePages(records, stage = 'all') {
  const issued = [], summarized = [], missing = [];
  for (const r of records) {
    if (r.pages === null) missing.push(r.text_date);
    else {
      issued.push([r.text_date, r.pages]);
      if (r.stage !== null && r.summary_date !== null && (stage === 'all' || r.stage === stage)) summarized.push([r.summary_date, r.pages]);
    }
  }
  const dates = [...new Set([...issued.map((p) => p[0]), ...summarized.map((p) => p[0]), ...missing])].sort();
  const running = (pairs) => { const sorted = pairs.sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0)); let i = 0, sum = 0; return (d) => { while (i < sorted.length && sorted[i][0] <= d) sum += sorted[i++][1]; return sum; }; };
  const pi = running(issued), ps = running(summarized), pm = running(missing.map((d) => [d, 1]));
  return dates.map((date) => ({ date, pagesIssued: pi(date), pagesSummarized: ps(date), versionsWithoutPages: pm(date) }));
}
