import { test } from 'node:test';
import assert from 'node:assert/strict';
import { headerMetrics, binLags, filterRecords, monthlySeries, cumulativeSeries, cumulativePages, histogramMax, monthOptions } from './metrics.js';

const rec = (o) => ({ type: 'hr', number: '1', stage: 'introduced', text_date: '2025-01-10',
  summary_date: null, lag_days: null, pages: null, reported: false, title: 't', ...o });

test('headerMetrics counts bills, summarized, waiting, reported, pages', () => {
  const m = headerMetrics([
    rec({ number: '1', lag_days: 10, summary_date: '2025-01-20', pages: 5 }),
    rec({ number: '1', stage: 'reported', text_date: '2025-02-01' }),
    rec({ number: '2', lag_days: 30, summary_date: '2025-02-09', pages: null }),
    rec({ number: '3' }),
    rec({ number: '3', stage: null, pages: 7 }),
  ]);
  assert.equal(m.bills, 3);
  assert.equal(m.summarized, 2);
  assert.equal(m.waiting, 1);
  assert.equal(m.reported, 1);
  assert.equal(m.pagesTotal, 12);
  assert.equal(m.pagesCounted, 2);
  assert.equal(m.versions, 5);
  assert.equal(m.n, 2);
  assert.equal(m.lagMean, 20);
  assert.equal(m.lagMedian, 20);
  assert.equal(m.lagMax, 30);
});

test('headerMetrics median of odd count and null lags when nothing summarized', () => {
  const odd = headerMetrics([rec({ lag_days: 1 }), rec({ lag_days: 5 }), rec({ lag_days: 100 })]);
  assert.equal(odd.lagMedian, 5);
  const none = headerMetrics([rec(), rec({ number: '2' })]);
  assert.equal(none.n, 0);
  assert.equal(none.lagMean, null);
  assert.equal(none.lagMedian, null);
  assert.equal(none.lagMax, null);
  assert.equal(headerMetrics([]).bills, 0);
});

test('binLags puts lags in fixed-width bins from 0 to the max lag, waiting ignored', () => {
  const bins = binLags([rec({ lag_days: 0 }), rec({ lag_days: 29 }), rec({ lag_days: 30 }),
    rec({ lag_days: 100 }), rec()], 30);
  assert.deepEqual(bins, [
    { from: 0, to: 30, count: 2 },
    { from: 30, to: 60, count: 1 },
    { from: 60, to: 90, count: 0 },
    { from: 90, to: 120, count: 1 },
  ]);
});

test('binLags on empty input and on only-waiting input', () => {
  assert.deepEqual(binLags([], 30), []);
  assert.deepEqual(binLags([rec()], 30), []);
});

test('filterRecords by stage, type, and inclusive month range', () => {
  const rs = [
    rec({ number: '1', stage: 'introduced', type: 'hr', text_date: '2025-01-10' }),
    rec({ number: '2', stage: 'reported', type: 'hr', text_date: '2025-03-10' }),
    rec({ number: '3', stage: 'introduced', type: 's', text_date: '2025-06-30' }),
  ];
  assert.equal(filterRecords(rs, { stage: 'all', type: 'all', range: null }).length, 3);
  assert.deepEqual(filterRecords(rs, { stage: 'introduced', type: 'all', range: null }).map((r) => r.number), ['1', '3']);
  assert.deepEqual(filterRecords(rs, { stage: 'all', type: 's', range: null }).map((r) => r.number), ['3']);
  assert.deepEqual(filterRecords(rs, { stage: 'all', type: 'all', range: { from: '2025-03', to: '2025-06' } }).map((r) => r.number), ['2', '3']);
  assert.deepEqual(filterRecords(rs, { stage: 'all', type: 'all', range: { from: '2026-01', to: '2026-12' } }), []);
});

test('filterRecords honours from-only, to-only, both, and treats an inverted range as none', () => {
  const rs = ['2025-01-31', '2025-02-01', '2025-03-15', '2025-04-30'].map((d, i) => rec({ number: String(i), text_date: d }));
  const nums = (range) => filterRecords(rs, { range }).map((r) => r.number);
  assert.deepEqual(nums({ from: '2025-02', to: null }), ['1', '2', '3']);
  assert.deepEqual(nums({ from: null, to: '2025-03' }), ['0', '1', '2']);
  assert.deepEqual(nums({ from: '2025-02', to: '2025-03' }), ['1', '2']);
  assert.deepEqual(nums({ from: '2025-04', to: '2025-04' }), ['3']);
  assert.deepEqual(nums({ from: '2025-04', to: '2025-02' }), ['0', '1', '2', '3']);
  assert.deepEqual(nums({ from: null, to: null }), ['0', '1', '2', '3']);
});

test('monthlySeries groups by month of text_date with lag quantiles', () => {
  const s = monthlySeries([
    rec({ number: '1', text_date: '2025-01-03', lag_days: 10 }),
    rec({ number: '2', text_date: '2025-01-20', lag_days: 30 }),
    rec({ number: '3', text_date: '2025-01-25' }),
    rec({ number: '4', text_date: '2025-03-01' }),
    rec({ number: '5', stage: null, text_date: '2025-01-28', pages: 3 }), // later edition: never counted
  ]);
  assert.deepEqual(s, [
    { month: '2025-01', summarized: 2, waiting: 1, medianLag: 20, p90Lag: 30 },
    { month: '2025-03', summarized: 0, waiting: 1, medianLag: null, p90Lag: null },
  ]);
  assert.deepEqual(monthlySeries([]), []);
});

test('binLags at width 7 over lags up to 626 gives 90 fixed bins whose counts sum to n, no open bin', () => {
  const rs = [rec({ lag_days: 3 }), rec({ lag_days: 45 }), rec({ lag_days: 200 }), rec({ lag_days: 626 })];
  const bins = binLags(rs, 7);
  assert.equal(bins.length, 90);
  assert.ok(bins.every((b) => b.to === b.from + 7));
  assert.equal(bins.reduce((s, b) => s + b.count, 0), 4);
  for (const w of [30, 90]) assert.equal(binLags(rs, w).reduce((s, b) => s + b.count, 0), 4);
});

test('cumulativeSeries counts distinct bills with text and with a summary by date', () => {
  const s = cumulativeSeries([
    rec({ number: '1', text_date: '2025-01-03', summary_date: '2025-01-20', lag_days: 17 }),
    rec({ number: '2', text_date: '2025-01-03' }),
    rec({ number: '3', text_date: '2025-02-01', summary_date: '2025-02-01', lag_days: 0 }),
    rec({ number: '3', stage: null, text_date: '2025-03-01', pages: 4 }),
  ]);
  assert.deepEqual(s, [
    { date: '2025-01-03', withText: 2, summarized: 0 },
    { date: '2025-01-20', withText: 2, summarized: 1 },
    { date: '2025-02-01', withText: 3, summarized: 2 },
  ]);
  assert.deepEqual(cumulativeSeries([]), []);
});

test('cumulativePages sums pages issued and pages of summarized bills by date', () => {
  const s = cumulativePages([
    rec({ number: '1', text_date: '2025-01-03', summary_date: '2025-01-20', lag_days: 17, pages: 10 }),
    rec({ number: '2', text_date: '2025-01-03', pages: null }),
    rec({ number: '1', stage: null, text_date: '2025-02-01', pages: 12 }),
  ]);
  assert.deepEqual(s, [
    { date: '2025-01-03', pagesIssued: 10, pagesSummarized: 0, versionsWithoutPages: 1 },
    { date: '2025-01-20', pagesIssued: 10, pagesSummarized: 10, versionsWithoutPages: 1 },
    { date: '2025-02-01', pagesIssued: 22, pagesSummarized: 10, versionsWithoutPages: 1 },
  ]);
  assert.deepEqual(cumulativePages([]), []);
});

test('headerMetrics: summarized + waiting === bills; a bill summarized at one stage is not waiting at another', () => {
  const m = headerMetrics([
    rec({ number: '1', stage: 'introduced', lag_days: 10, summary_date: '2025-01-20' }),
    rec({ number: '1', stage: 'reported' }),
    rec({ number: '2' }),
    rec({ number: '2', stage: null, pages: 3 }),
  ]);
  assert.equal(m.bills, 2);
  assert.equal(m.summarized, 1);
  assert.equal(m.waiting, 1);
  assert.equal(m.summarized + m.waiting, m.bills);
});

test('binLags floors a negative lag into the first bin', () => {
  const bins = binLags([rec({ lag_days: -3 }), rec({ lag_days: 40 })], 30);
  assert.deepEqual(bins, [{ from: 0, to: 30, count: 1 }, { from: 30, to: 60, count: 1 }]);
});

test('cumulativePages follows the stage filter for summarized pages only', () => {
  const rs = [
    rec({ number: '1', stage: 'introduced', text_date: '2025-01-03', summary_date: '2025-01-20', lag_days: 17, pages: 10 }),
    rec({ number: '1', stage: 'reported', text_date: '2025-02-01', summary_date: '2025-02-10', lag_days: 9, pages: 5 }),
  ];
  const last = (st) => cumulativePages(rs, st).at(-1);
  assert.equal(last('all').pagesSummarized, 15);
  assert.equal(last('reported').pagesSummarized, 5);
  assert.equal(last('reported').pagesIssued, 15); // issued still counts the introduced-stage record
  assert.equal(last('passed').pagesSummarized, 0);
});

test('headerMetrics.reported counts distinct bills with a reported-stage record, even without an introduced record', () => {
  const rs = [
    rec({ number: '1', stage: 'reported', type: 'hr' }),
    rec({ number: '1', stage: 'reported', type: 'hr', text_date: '2025-03-01' }), // second edition, same bill
    rec({ number: '2', stage: 'introduced', reported: true }), // flag alone does not count
    rec({ number: '3', stage: 'reported', type: 's', text_date: '2025-05-01' }),
  ];
  assert.equal(headerMetrics(rs).reported, 2);
  const ranged = filterRecords(rs, { type: 'all', range: { from: '2025-04', to: '2025-06' } });
  assert.equal(headerMetrics(ranged).reported, 1);
});

test('histogramMax is one scale: the tallest bin, or the waiting count when that bar is drawn and taller', () => {
  const bins = binLags([rec({ lag_days: 5 }), rec({ lag_days: 6 }), rec({ lag_days: 40 })], 30);
  assert.equal(histogramMax(bins), 2);
  assert.equal(histogramMax(bins, 500), 500);
  assert.equal(histogramMax(bins, 1), 2);
  assert.equal(histogramMax([]), 1);
});

test('cumulativeSeries over a filtered subset ends at the headerMetrics of that subset', () => {
  const rs = [
    rec({ number: '1', text_date: '2025-04-02', lag_days: 10, summary_date: '2025-04-12' }),
    rec({ number: '2', text_date: '2025-05-02' }),
    rec({ number: '3', text_date: '2025-01-05', lag_days: 4, summary_date: '2025-01-09' }),
    rec({ number: '4', text_date: '2025-11-05' }),
  ];
  const subset = filterRecords(rs, { stage: 'introduced', type: 'all', range: { from: '2025-04', to: '2025-10' } });
  const m = headerMetrics(subset), end = cumulativeSeries(subset).at(-1);
  assert.equal(end.summarized, m.summarized);
  assert.equal(end.withText, m.summarized + m.waiting);
  assert.equal(end.withText, 2);
});

test('monthOptions lists the distinct months present, in order, labelled Mon YYYY', () => {
  const rs = [rec({ text_date: '2025-03-10' }), rec({ text_date: '2025-01-02' }), rec({ text_date: '2025-03-30' }), rec({ text_date: '2026-10-01' })];
  assert.deepEqual(monthOptions(rs), [
    { value: '2025-01', label: 'Jan 2025' }, { value: '2025-03', label: 'Mar 2025' }, { value: '2026-10', label: 'Oct 2026' }]);
  assert.deepEqual(monthOptions([]), []);
});
