import { test } from 'node:test';
import assert from 'node:assert/strict';
import { headerMetrics, binLags, filterRecords } from './metrics.js';

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
