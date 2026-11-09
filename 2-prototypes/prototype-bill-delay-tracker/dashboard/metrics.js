// Pure computations behind the dashboard. No DOM, no d3.
//
// This file is a classic script, not an ES module, on purpose: the dashboard must open from disk
// (file://), and Chromium refuses to load module scripts from file:// pages. In the browser the
// functions are published on window.BillDelayMetrics (see the foot of the file); under Node the
// same object is module.exports, which is how metrics.test.mjs imports it. The whole file sits in
// one function so that, as a classic script, its helpers stay out of the page's global scope.
(() => {
  'use strict';

  const billKey = (r) => `${r.type}${r.number}`;

  function median(sorted) {
    const n = sorted.length;
    if (n === 0) return null;
    return n % 2 ? sorted[(n - 1) / 2] : (sorted[n / 2 - 1] + sorted[n / 2]) / 2;
  }

  /** Header-row numbers over the records in view. lag* are null when nothing is summarized.
   *  waiting = distinct bills with a staged record and no summary in the set, so summarized + waiting === bills. */
  function headerMetrics(records) {
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
  function histogramMax(bins, waiting = 0) {
    return Math.max(1, waiting, ...bins.map((b) => b.count));
  }

  /** Fixed-width bins of lag_days from 0 to the largest lag in view; no open-ended bin. A negative lag (a summary
   *  dated before its text reached GovInfo; a handful exist) is left out rather than folded into the first bin. */
  function binLags(records, width) {
    const lags = records.filter((r) => r.lag_days !== null && r.lag_days >= 0).map((r) => r.lag_days);
    if (lags.length === 0) return [];
    const count = Math.floor(Math.max(0, ...lags) / width) + 1;
    const bins = Array.from({ length: count }, (_, i) => ({ from: i * width, to: (i + 1) * width, count: 0 }));
    for (const lag of lags) bins[Math.min(Math.max(0, Math.floor(lag / width)), count - 1)].count += 1;
    return bins;
  }

  /** Records in view. range is null or {from, to} as ISO 'YYYY-MM-DD' or null (open side); inclusive of both days, compared on text_date.
   *  ISO dates sort as strings, so no Date objects. A from later than to is treated as no range. */
  function filterRecords(records, { stage = 'all', type = 'all', range = null }) {
    const from = range?.from || null, to = range?.to || null;
    const ranged = !(from && to && from > to) && (from || to);
    return records.filter((r) => {
      if (stage !== 'all' && r.stage !== stage) return false;
      if (type !== 'all' && r.type !== type) return false;
      if (!ranged) return true;
      return (!from || r.text_date >= from) && (!to || r.text_date <= to);
    });
  }

  /** Earliest and latest text_date in the records ({min, max}, ISO dates; both null when empty). Bounds the date inputs. */
  function dateBounds(records) {
    let min = null, max = null;
    for (const r of records) {
      if (min === null || r.text_date < min) min = r.text_date;
      if (max === null || r.text_date > max) max = r.text_date;
    }
    return { min, max };
  }

  /** Per month of text_date: how many got a summary and how many wait. */
  function monthlySeries(records) {
    const byMonth = new Map();
    for (const r of records) {
      if (r.stage === null) continue; // later editions never get a summary of their own
      const month = r.text_date.slice(0, 7);
      if (!byMonth.has(month)) byMonth.set(month, { summarized: 0, waiting: 0 });
      const m = byMonth.get(month);
      if (r.lag_days === null) m.waiting += 1; else m.summarized += 1;
    }
    return [...byMonth.keys()].sort().map((month) => ({ month, ...byMonth.get(month) }));
  }

  /** Running counts of distinct bills with any text and with any summary, by date. */
  function cumulativeSeries(records) {
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

  /** Running page totals over the given records (the caller scopes them to a stage, or passes every edition for 'all'): pages issued, and pages of the staged records whose summary has arrived. */
  function cumulativePages(records) {
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

  // Every measure type the GovInfo BILLS collection lists, in the order the page offers them (congress.py's BILL_TYPES).
  const BILL_TYPES = ['hr', 's', 'hjres', 'sjres', 'hconres', 'sconres', 'hres', 'sres'];
  const BILL_LABELS = { hr: 'H.R.', s: 'S.', hjres: 'H.J.Res.', sjres: 'S.J.Res.', hconres: 'H.Con.Res.', sconres: 'S.Con.Res.', hres: 'H.Res.', sres: 'S.Res.' };
  const BILL_SLUGS = { hr: 'house-bill', s: 'senate-bill', hjres: 'house-joint-resolution', sjres: 'senate-joint-resolution',
    hconres: 'house-concurrent-resolution', sconres: 'senate-concurrent-resolution', hres: 'house-resolution', sres: 'senate-resolution' };

  /** Bill-type filter options for the records in view: [value, label] pairs, 'all' first, then each type present in the
   *  known order, then any type the page has no label for, alphabetically. Read from the data, so a Congress with no
   *  concurrent resolutions offers none. */
  function typeOptions(records) {
    const present = new Set(records.map((r) => r.type));
    const known = BILL_TYPES.filter((t) => present.has(t));
    const other = [...present].filter((t) => !BILL_TYPES.includes(t)).sort();
    return [['all', 'All types'], ...[...known, ...other].map((t) => [t, BILL_LABELS[t] ?? String(t).toUpperCase()])];
  }

  /** "119th Congress (2025–2026)": the ordinal and the two calendar years it sits in (it ends on January 2 of the third). */
  function congressLabel(entry) {
    const first = Number(entry.start.slice(0, 4)), last = Number(entry.end.slice(0, 4)) - 1;
    return `${ordinal(entry.congress)} Congress (${first}–${last})`;
  }

  /** The Congress the page opens on: the newest one in the index that has an introduced bill. Null for an empty index. */
  function defaultCongress(entries) {
    const usable = entries.filter((e) => (e.comparison?.all?.introduced_bills ?? 0) > 0);
    if (usable.length === 0) return null;
    return usable.reduce((a, b) => (Number(b.congress) > Number(a.congress) ? b : a)).congress;
  }

  /** One point per Congress, oldest first, for the by-Congress chart: introduced bills of the given type, how many have a
   *  summary, how many wait, the median lag from the printed date, and the summaries dated after the Congress ended.
   *  A Congress with no bills of that type is left out. */
  function congressSeries(entries, type = 'all') {
    return entries
      .map((e) => ({ e, c: e.comparison?.[type] }))
      .filter(({ c }) => c && c.introduced_bills > 0)
      .sort((a, b) => Number(a.e.congress) - Number(b.e.congress))
      .map(({ e, c }) => ({
        congress: String(e.congress), ended: Boolean(e.ended), bills: c.introduced_bills, summarized: c.introduced_summarized,
        waiting: c.introduced_bills - c.introduced_summarized, share: c.introduced_summarized / c.introduced_bills,
        median: c.median_lag_printed, afterEnd: c.summaries_after_end,
      }));
  }

  /** "H.R. 360": the conventional abbreviation for the bill type, a space, the number. */
  function billLabel(type, number) {
    return `${BILL_LABELS[type] ?? String(type).toUpperCase()} ${number}`;
  }

  /** English ordinal: 119 -> "119th", 101 -> "101st", 112 -> "112th". */
  function ordinal(n) {
    const k = Number(n), mod100 = k % 100, mod10 = k % 10;
    const suffix = mod100 >= 11 && mod100 <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' }[mod10] ?? 'th');
    return `${k}${suffix}`;
  }

  /** congress.gov page for a bill; congress is the envelope's number (119 or "119"). */
  function billUrl(congress, type, number) {
    return `https://www.congress.gov/bill/${ordinal(congress)}-congress/${BILL_SLUGS[type]}/${number}`;
  }

  const byNumber = (a, b) => Number(a.number) - Number(b.number) || (a.type < b.type ? -1 : a.type > b.type ? 1 : 0);

  /** Top n records by lag_days descending among those with a summary; stage-less records excluded; ties by bill number ascending. */
  function longestLags(records, n = 10) {
    return records
      .filter((r) => r.stage != null && r.summary_date != null && r.lag_days != null)
      .sort((a, b) => b.lag_days - a.lag_days || byNumber(a, b))
      .slice(0, n);
  }

  const utcDays = (iso) => { const [y, m, d] = iso.split('-').map(Number); return Date.UTC(y, m - 1, d) / 86400000; };

  /** Top n records with no summary by whole days from text_date to asOf (ISO), descending, as copies carrying days_waiting; ties by bill number ascending. */
  function oldestWaiting(records, asOf, n = 10) {
    return records
      .filter((r) => r.stage != null && r.summary_date == null)
      .map((r) => ({ ...r, days_waiting: utcDays(asOf) - utcDays(r.text_date) }))
      .sort((a, b) => b.days_waiting - a.days_waiting || byNumber(a, b))
      .slice(0, n);
  }

  /** Download filename (no extension): bill-delay-<kind>[-<congress>]-<type>[-<from>_<to>]-<asOf>.
   *  The Congress part appears when the view names one. The range part appears only for a usable range (an inverted one
   *  is ignored, as in filterRecords); an open side reads "start"/"end". */
  function exportName(kind, { congress = null, type = 'all', range = null } = {}, asOf) {
    const from = range?.from || null, to = range?.to || null;
    const ranged = (from || to) && !(from && to && from > to);
    return ['bill-delay', kind, ...(congress ? [String(congress)] : []), type,
      ...(ranged ? [`${from || 'start'}_${to || 'end'}`] : []), asOf].join('-');
  }

  /** RFC 4180 CSV: header row of the column keys, then one row per record; fields with a comma, quote, CR or LF are quoted
   *  with embedded quotes doubled; null/undefined become empty; rows are joined by CRLF (no trailing newline). */
  function toCsv(rows, columns) {
    const cell = (v) => { const t = v == null ? '' : String(v); return /[",\r\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t; };
    return [columns, ...rows.map((r) => columns.map((c) => r[c]))].map((line) => line.map(cell).join(',')).join('\r\n');
  }

  // Dual export: CommonJS for `node --test`, a window global for the page (see the header comment).
  const api = { headerMetrics, histogramMax, binLags, filterRecords, dateBounds, monthlySeries, cumulativeSeries, cumulativePages, billLabel, ordinal, billUrl, longestLags, oldestWaiting, exportName, toCsv, typeOptions, congressLabel, defaultCongress, congressSeries };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else window.BillDelayMetrics = api;
})();
