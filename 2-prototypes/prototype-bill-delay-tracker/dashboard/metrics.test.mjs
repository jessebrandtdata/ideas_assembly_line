import { test } from 'node:test';
import assert from 'node:assert/strict';
import { headerMetrics, binLags, filterRecords, monthlySeries, cumulativeSeries, cumulativePages, clampRange } from './metrics.js';

const rec = (o) => ({ type: 'hr', number: '1', stage: 'introduced', text_date: '2025-01-10',
  summary_date: null, lag_days: null, pages: null, reported: false, title: 't', ...o });

test('headerMetrics counts bills, summarized, waiting, reported, pages', () => {
  const m = headerMetrics([
    rec({ number: '1', lag_days: 10, summary_date: '2025-01-20', pages: 5, reported: true }),
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
  assert.equal(m.versions, 4);
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

test('binLags puts lags in fixed-width bins, last bin open, waiting ignored', () => {
  const bins = binLags([rec({ lag_days: 0 }), rec({ lag_days: 29 }), rec({ lag_days: 30 }),
    rec({ lag_days: 5000 }), rec()], 30, 4);
  assert.deepEqual(bins, [
    { from: 0, to: 30, count: 2 },
    { from: 30, to: 60, count: 1 },
    { from: 60, to: 90, count: 0 },
    { from: 90, to: null, count: 1 },
  ]);
});

test('binLags on empty input and on only-waiting input', () => {
  assert.deepEqual(binLags([], 30), []);
  assert.deepEqual(binLags([rec()], 30), []);
});

test('filterRecords by stage, type, and inclusive date range', () => {
  const rs = [
    rec({ number: '1', stage: 'introduced', type: 'hr', text_date: '2025-01-10' }),
    rec({ number: '2', stage: 'reported', type: 'hr', text_date: '2025-03-10' }),
    rec({ number: '3', stage: 'introduced', type: 's', text_date: '2025-06-30' }),
  ];
  assert.equal(filterRecords(rs, { stage: 'all', type: 'all', range: null }).length, 3);
  assert.deepEqual(filterRecords(rs, { stage: 'introduced', type: 'all', range: null }).map((r) => r.number), ['1', '3']);
  assert.deepEqual(filterRecords(rs, { stage: 'all', type: 's', range: null }).map((r) => r.number), ['3']);
  assert.deepEqual(filterRecords(rs, { stage: 'all', type: 'all', range: ['2025-03-10', '2025-06-30'] }).map((r) => r.number), ['2', '3']);
  assert.deepEqual(filterRecords(rs, { stage: 'all', type: 'all', range: ['2026-01-01', '2026-12-31'] }), []);
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

test('binLags totals are width-invariant', () => {
  const rs = [rec({ lag_days: 3 }), rec({ lag_days: 45 }), rec({ lag_days: 200 }), rec({ lag_days: 800 })];
  const total = (w) => binLags(rs, w).reduce((s, b) => s + b.count, 0);
  assert.equal(total(7), 4);
  assert.equal(total(30), 4);
  assert.equal(total(90), 4);
  assert.equal(binLags(rs, 7).at(-1).to, null); // 800/7 > 20 bins → open last bin
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

test('clampRange: unchanged, clamped at one end, cleared', () => {
  const months = ['2025-02', '2025-03', '2025-04'];
  assert.deepEqual(clampRange(['2025-02-01', '2025-04-30'], months), ['2025-02-01', '2025-04-30']);
  assert.deepEqual(clampRange(['2025-01-01', '2025-03-31'], months), ['2025-02-01', '2025-03-31']);
  assert.equal(clampRange(['2026-01-01', '2026-02-28'], months), null);
  assert.equal(clampRange(null, months), null);
});
