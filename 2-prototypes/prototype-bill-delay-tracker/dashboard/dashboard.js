// Classic script, not an ES module: the page must open from disk, and Chromium blocks module
// scripts on file:// pages. index.html loads metrics.js and ../data/congresses.js (the index of
// Congress folders) before this file; each Congress's own ../data/<n>/delays.js is added as a
// <script> tag when it is first picked, which file:// pages allow where fetch() is blocked.
'use strict';

const { headerMetrics, binLags, histogramMax, filterRecords, dateBounds, monthlySeries, cumulativeSeries, cumulativePages, longestLags, oldestWaiting, billLabel, billUrl, ordinal, exportName, toCsv, typeOptions, congressLabel, defaultCongress, congressSeries, mergeCongresses, allCongressesLabel } = window.BillDelayMetrics;

// The Congressional Tech site's coverage colors (apps/site Dashboard.tsx): "has it" is the primary
// blue, "missing it" is the gold. Here a bill that has its summary is blue, one still waiting is gold.
const BLUE = '#104378', GOLD = '#eec05e', INK = '#1b1b1b', MUTED = '#565c65';
let fmt; // assigned in main() once d3 is known to be loaded
const day = (v) => (v === null ? '–' : `${Math.round(v)}`);

let congress = ''; // the Congress in view, set by showCongress()
let asOf = ''; // that Congress's as_of date (ISO)

// The page measures the introduced stage only. CRS writes summaries for introduced versions alone in
// the 119th Congress (Congress.gov help, Bill Summaries, read 2026-10-16), and the introduced stage is
// the one every Congress has, so it is the stage that compares across Congresses; later-stage summaries
// stay in the data (delays.csv, stage column) and are counted in the caveat at the foot of the page.
// The proposal (IV.2) asks for no breakdown by stage.
const STAGE = 'introduced';
const state = { congresses: [], entry: null, congress: null, records: [], summaryBefore: {}, stage: STAGE, type: 'all',
  range: { from: null, to: null }, includeWaiting: true, width: 30 };

function card(label, value, note = '') {
  return `<div class="card"><div class="value">${value}</div><div class="label">${label}</div><div class="note">${note}</div></div>`;
}

function renderHeader(records, allEditions) {
  const m = headerMetrics(records);
  const r = headerMetrics(allEditions); // reported needs the reported-stage records, which the page otherwise ignores
  const pagesCard = m.pagesCounted
    ? card('pages of bill text', fmt(m.pagesTotal), `${fmt(m.pagesCounted)} of ${fmt(m.versions)} introduced versions counted`)
    : card('pages of bill text', '–', 'no page counts collected for this Congress');
  document.getElementById('cards').innerHTML = [
    pagesCard,
    card('bills summarized', fmt(m.summarized), `${fmt(m.waiting)} still waiting`),
    card('reported by committee', fmt(r.reported), 'bills with an rh/rs text version'),
    card('mean lag (days)', day(m.lagMean), `n=${fmt(m.n)}`),
    card('median lag (days)', day(m.lagMedian)),
    card('max lag (days)', day(m.lagMax)),
  ].join('');
}

function renderPreText() {
  const n = state.summaryBefore[STAGE] || 0;
  document.getElementById('pre-text').textContent = n
    ? `${fmt(n)} introduced summaries exist for bills whose introduced text GovInfo has not posted.` : '';
}

/** The foot-of-page caveat's counts: later-stage summaries the page leaves out, and introduced summaries in view dated
 *  after the Congress ended (re-publications or very late summaries, whose lag reads long), with that sentence hidden when
 *  there are none. */
function renderExceptions(records, introduced) {
  const n = records.filter((r) => r.stage !== null && r.stage !== STAGE && r.lag_days !== null).length;
  document.getElementById('exceptions').textContent = fmt(n);
  const ends = new Map(state.congresses.map((e) => [String(e.congress), e.end])); // each record against its own Congress
  const late = introduced.filter((r) => r.summary_date !== null && r.summary_date > ends.get(String(r.congress))).length;
  document.getElementById('after-end-count').textContent = fmt(late);
  document.getElementById('after-end').hidden = late === 0;
  const e = state.entry;
  document.getElementById('printed-fallback').hidden = !e.versions_without_ingest_date;
  document.getElementById('printed-fallback-count').textContent = fmt(e.versions_without_ingest_date || 0);
  document.getElementById('printed-fallback-total').textContent = fmt(e.text_versions || 0);
}

function renderHistogram(records, state) {
  const { width, includeWaiting } = state;
  const negative = records.filter((r) => r.lag_days !== null && r.lag_days < 0).length;
  const bins = binLags(records, width);
  const m = headerMetrics(records);
  const W = 920, H = 320, left = 56, right = 16, top = 36, bottom = 56;
  const fig = d3.select('#hist-chart').html('');
  if (bins.length === 0) {
    fig.append('p').attr('class', 'note').text('No summarized bills in this view.');
    return;
  }
  const svg = fig.append('svg').attr('viewBox', `0 0 ${W} ${H}`).attr('role', 'img')
    .attr('aria-label', 'Histogram of lag in days');
  svg.append('text').attr('x', left).attr('y', 13).attr('font-size', 14).attr('font-weight', 600).attr('fill', INK)
    .text(`Days from text on GovInfo to CRS summary, ${width}-day bins (n=${fmt(m.n)} summarized, ${fmt(m.waiting)} still waiting${negative ? `; ${fmt(negative)} dated before the text reached GovInfo, not binned` : ''})`);
  const x = d3.scaleBand().domain([...bins.map((_, i) => i), ...(includeWaiting ? ['waiting'] : [])]).range([left, W - right]).padding(0.12);
  const unit = 'bills';
  const y = d3.scaleLinear().domain([0, histogramMax(bins, includeWaiting ? m.waiting : 0)]).nice().range([H - bottom, top]);
  svg.append('g').attr('transform', `translate(${left},0)`).call(d3.axisLeft(y).ticks(6).tickFormat(fmt))
    .call((g) => g.select('.domain').remove()).selectAll('text').attr('fill', MUTED);
  const every = Math.max(1, Math.ceil(48 / x.step())); // at least ~48 px per x label
  const binLabel = (b) => `${b.from}–${b.to - 1}`;
  const axis = d3.axisBottom(x).tickFormat((i) => (i === 'waiting' ? 'waiting' : binLabel(bins[i])));
  svg.append('g').attr('transform', `translate(0,${H - bottom})`).call(axis)
    .call((g) => g.select('.domain').remove())
    .call((g) => g.selectAll('.tick').filter((i) => i !== 'waiting' && i % every !== 0).remove())
    .selectAll('text').attr('fill', MUTED).attr('font-size', 9);
  svg.append('text').attr('x', (left + W - right) / 2).attr('y', H - 14).attr('font-size', 11).attr('text-anchor', 'middle').attr('fill', INK)
    .text('lag in days');
  svg.append('text').attr('transform', `translate(14,${(top + H - bottom) / 2}) rotate(-90)`).attr('font-size', 11).attr('text-anchor', 'middle').attr('fill', INK)
    .text(unit);
  svg.append('g').selectAll('rect').data(bins).join('rect').attr('class', 'bin')
    .attr('x', (_, i) => x(i)).attr('y', (b) => y(b.count)).attr('width', x.bandwidth())
    .attr('height', (b) => y(0) - y(b.count)).attr('fill', BLUE).attr('rx', 2)
    .on('mousemove', (event, b) => {
      const share = m.n ? (b.count / m.n) : 0;
      d3.select('#tooltip').style('display', 'block').style('left', `${event.pageX + 12}px`).style('top', `${event.pageY - 10}px`)
        .text(`${binLabel(b)} days: ${fmt(b.count)} ${unit} (${d3.format('.1%')(share)} of summarized)`);
    })
    .on('mouseleave', () => d3.select('#tooltip').style('display', 'none'))
    .append('title').text((b) => `${binLabel(b)} days: ${fmt(b.count)} ${unit}`);
  if (x.bandwidth() >= 18) {
    svg.append('g').selectAll('text').data(bins).join('text').attr('class', 'bin-count')
      .attr('x', (_, i) => x(i) + x.bandwidth() / 2).attr('y', (b) => y(b.count) - 4)
      .attr('font-size', 11).attr('text-anchor', 'middle').attr('fill', INK).text((b) => (b.count ? fmt(b.count) : ''));
  }
  // the censoring, visible: one gold bar for what has no summary yet, on the same scale as the bins
  if (includeWaiting) {
    const waitText = `still waiting: ${fmt(m.waiting)}`;
    const wx = x('waiting');
    svg.append('rect').attr('id', 'waiting-bar').attr('x', wx).attr('y', y(m.waiting)).attr('width', x.bandwidth()).attr('height', y(0) - y(m.waiting))
      .attr('fill', GOLD).attr('rx', 2).on('mousemove', (event) => {
        d3.select('#tooltip').style('display', 'block').style('left', `${event.pageX + 12}px`).style('top', `${event.pageY - 10}px`).text(waitText);
      }).on('mouseleave', () => d3.select('#tooltip').style('display', 'none')).append('title').text(waitText);
    svg.append('text').attr('x', wx + x.bandwidth()).attr('y', y(m.waiting) - 4).attr('font-size', 11).attr('text-anchor', 'end').attr('fill', INK)
      .text(fmt(m.waiting));
  }
  // median and mean rules sit at their position inside the band scale
  const pos = (v) => { const i = Math.min(Math.floor(v / width), bins.length - 1); return x(i) + x.bandwidth() * Math.min(1, (v - i * width) / width); };
  for (const [v, label] of [[m.lagMedian, 'median'], [m.lagMean, 'mean']]) {
    svg.append('line').attr('x1', pos(v)).attr('x2', pos(v)).attr('y1', top - 6).attr('y2', H - bottom)
      .attr('stroke', INK).attr('stroke-width', 1.5).attr('stroke-dasharray', label === 'mean' ? '4 3' : null);
    const crowded = label === 'mean' && Math.abs(pos(m.lagMean) - pos(m.lagMedian)) < 60;
    svg.append('text').attr('x', pos(v) - 4).attr('y', crowded ? top + 4 : top - 10).attr('font-size', 11).attr('text-anchor', 'end').attr('fill', INK)
      .text(`${label} ${Math.round(v)}d`);
  }
}

function options(list, value) {
  return list.map(([v, text]) => `<option value="${esc(v)}"${v === value ? ' selected' : ''}>${esc(text)}</option>`).join('');
}

function select(id, label, list, value) {
  return `<label>${label}<select id="${id}">${options(list, value)}</select></label>`;
}

/** Point the per-Congress controls at the Congress in view: the bill types it has (keeping the current one when it has
 *  it), and date pickers bounded by its first and last text date, cleared when they fall outside. */
function refreshControls(state) {
  const el = document.getElementById('controls');
  const types = typeOptions(state.records);
  if (!types.some(([v]) => v === state.type)) state.type = 'all';
  el.querySelector('#type').innerHTML = options(types, state.type);
  const { min, max } = dateBounds(state.records);
  for (const input of [el.querySelector('#date-from'), el.querySelector('#date-to')]) {
    input.min = min || ''; input.max = max || '';
    if (input.value && (input.value < min || input.value > max)) input.value = '';
  }
  state.range = { from: el.querySelector('#date-from').value || null, to: el.querySelector('#date-to').value || null };
}

function renderControls(state) {
  const el = document.getElementById('controls');
  if (el.children.length) return; // built once; refreshControls() repoints it per Congress
  const dateInput = (id, label) => `<label>${label}<input type="date" id="${id}"></label>`;
  const usable = state.congresses.filter((e) => (e.comparison?.all?.introduced_bills ?? 0) > 0);
  const congresses = [...(usable.length > 1 ? [[ALL, allCongressesLabel(usable)]] : []),
    ...state.congresses.map((e) => [String(e.congress), congressLabel(e)])];
  el.innerHTML = select('congress', 'Congress', congresses, String(state.congress))
    + select('type', 'Bill type', [['all', 'All types']], state.type)
    + dateInput('date-from', 'Text posted from') + dateInput('date-to', 'to')
    + '<button id="clear-dates" type="button">Clear date filters</button>';
  const from = el.querySelector('#date-from'), to = el.querySelector('#date-to');
  el.querySelector('#congress').addEventListener('change', (e) => { showCongress(e.target.value).catch((err) => showError(err, true)); });
  el.querySelector('#type').addEventListener('change', (e) => { state.type = e.target.value; render(state); });
  const setRange = () => { state.range = { from: from.value || null, to: to.value || null }; render(state); };
  from.addEventListener('change', setRange);
  to.addEventListener('change', setRange);
  el.querySelector('#clear-dates').addEventListener('click', () => { from.value = ''; to.value = ''; setRange(); });
  const waiting = document.getElementById('include-waiting');
  waiting.checked = state.includeWaiting;
  waiting.addEventListener('change', (e) => { state.includeWaiting = e.target.checked; renderHistogram(currentRecords(state), state); });
  const slider = document.getElementById('bin-width'), label = document.getElementById('bin-width-label');
  slider.value = String(state.width);
  slider.addEventListener('input', () => {
    state.width = +slider.value;
    label.textContent = `${state.width}-day bins`;
    renderHistogram(currentRecords(state), state);
  });
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const monthLabel = (m) => MONTHS[+m.slice(5, 7) - 1];
const dayName = (d) => `${+d.slice(8, 10)} ${monthLabel(d)} ${d.slice(0, 4)}`;
/** The date range if it is a usable one (not inverted), else null. */
const activeRange = (r) => ((r.from || r.to) && !(r.from && r.to && r.from > r.to) ? r : null);
const rangeLabel = (r) => {
  const a = activeRange(r);
  if (!a) return state.congress === ALL ? 'All Congresses' : state.entry?.ended ? 'Whole Congress' : 'Congress to date';
  return a.from && a.to ? `${dayName(a.from)} – ${dayName(a.to)}` : a.from ? `from ${dayName(a.from)}` : `to ${dayName(a.to)}`;
};
const currentRecords = (state) => filterRecords(state.records, state);

function renderTimeseries(records, state) {
  const series = monthlySeries(records);
  const W = 920, left = 76, right = 16, topY = 40, topH = 170, H = topY + topH + 60;
  const fig = d3.select('#timeseries .chart').html('');
  if (series.length === 0) return;
  const svg = fig.append('svg').attr('viewBox', `0 0 ${W} ${H}`).attr('role', 'img').attr('aria-label', 'Share of bills with a CRS summary, by month the text was issued');
  svg.append('text').attr('x', left).attr('y', 18).attr('font-size', 14).attr('font-weight', 600).attr('fill', INK)
    .text('By month the text was issued: share with a CRS summary.');
  const x = d3.scaleBand().domain(series.map((s) => s.month)).range([left, W - right]).padding(0.18);
  const sel = activeRange(state.range);
  if (sel) { // shaded band behind everything: every month band the selected days touch (a partial month is shaded whole)
    const inside = series.filter((s) => (!sel.from || s.month >= sel.from.slice(0, 7)) && (!sel.to || s.month <= sel.to.slice(0, 7)));
    if (inside.length) {
      const x0 = x(inside[0].month) - x.step() * x.paddingInner() / 2, x1 = x(inside.at(-1).month) + x.bandwidth() + x.step() * x.paddingInner() / 2;
      svg.append('rect').attr('id', 'month-band').attr('x', x0).attr('y', topY).attr('width', x1 - x0).attr('height', topH + 34)
        .attr('fill', MUTED).attr('fill-opacity', 0.15);
    }
  }
  const monthAxis = (y) => {
    const g = svg.append('g');
    // month names only when each bar has room for one; years every nth year so labels never overlap (~32 px each)
    const showMonths = x.step() >= 18;
    const yearEvery = Math.max(1, Math.ceil(32 / (x.step() * 12)));
    for (const s of series) {
      const cx = x(s.month) + x.bandwidth() / 2;
      if (showMonths) g.append('text').attr('x', cx).attr('y', y).attr('font-size', 10).attr('text-anchor', 'middle').attr('fill', MUTED).text(monthLabel(s.month));
      const year = Number(s.month.slice(0, 4));
      const yearMark = (s.month.endsWith('-01') && year % yearEvery === 0) || (showMonths && s === series[0]);
      if (yearMark) g.append('text').attr('x', cx).attr('y', showMonths ? y + 12 : y + 6).attr('font-size', 10).attr('font-weight', 600).attr('text-anchor', 'middle').attr('fill', INK).text(year);
    }
    g.append('text').attr('x', (left + W - right) / 2).attr('y', y + 28).attr('font-size', 11).attr('text-anchor', 'middle').attr('fill', INK).text('Month the text version was issued');
  };
  // top: share
  const yShare = d3.scaleLinear().domain([0, 1]).range([topY + topH, topY]);
  svg.append('g').attr('transform', `translate(${left},0)`).call(d3.axisLeft(yShare).ticks(4).tickFormat(d3.format('.0%'))).call((g) => g.select('.domain').remove());
  svg.append('text').attr('transform', `translate(14,${topY + topH / 2}) rotate(-90)`).attr('font-size', 11).attr('text-anchor', 'middle').attr('fill', INK).text('Share of that month\'s bills');
  const legend = svg.append('g').attr('transform', `translate(${W - right - 190},6)`);
  for (const [i, [color, label]] of [[BLUE, 'has a summary'], [GOLD, 'still waiting']].entries()) {
    legend.append('rect').attr('x', i * 100).attr('y', 0).attr('width', 10).attr('height', 10).attr('rx', 2).attr('fill', color);
    legend.append('text').attr('x', i * 100 + 14).attr('y', 9).attr('font-size', 11).attr('fill', INK).text(label);
  }
  const bars = svg.append('g').selectAll('g').data(series).join('g');
  bars.append('rect').attr('x', (s) => x(s.month)).attr('width', x.bandwidth()).attr('fill', GOLD)
    .attr('y', topY).attr('height', (s) => yShare(1 - s.waiting / (s.summarized + s.waiting || 1)) - topY);
  bars.append('rect').attr('x', (s) => x(s.month)).attr('width', x.bandwidth()).attr('fill', BLUE)
    .attr('y', (s) => yShare(s.summarized / (s.summarized + s.waiting || 1))).attr('height', (s) => topY + topH - yShare(s.summarized / (s.summarized + s.waiting || 1)));
  bars.append('title').text((s) => `${s.month}: ${fmt(s.summarized)} summarized, ${fmt(s.waiting)} waiting`);
  monthAxis(topY + topH + 14);
}

/** Every Congress in the index side by side: the share of introduced bills with a CRS summary (top) and the median days
 *  from the printed date to the summary (bottom), for the bill type in view. The Congress in view is outlined. */
function renderByCongress(state) {
  const series = congressSeries(state.congresses, state.type);
  const fig = d3.select('#by-congress .chart').html('');
  if (series.length < 2) { // one Congress is not a comparison; the rest of the page already shows it
    fig.append('p').attr('class', 'note').text(series.length ? 'Collect more Congresses (collect_warehouse.py --congress all) to compare them here.' : '');
    return;
  }
  const W = 920, left = 76, right = 16, topY = 58, topH = 120, gap = 40, lowH = 130, H = topY + topH + gap + lowH + 44;
  const lowY = topY + topH + gap;
  const svg = fig.append('svg').attr('viewBox', `0 0 ${W} ${H}`).attr('role', 'img')
    .attr('aria-label', 'Share of introduced bills with a CRS summary and median lag, by Congress');
  svg.append('text').attr('x', left).attr('y', 18).attr('font-size', 14).attr('font-weight', 600).attr('fill', INK)
    .text('Introduced bills by Congress: share with a CRS summary, and median days to it.');
  svg.append('text').attr('x', left).attr('y', 36).attr('font-size', 12).attr('fill', MUTED)
    .text('Measured from the date printed on the bill in every Congress, so the Congresses line up. Follows the bill type filter, not the dates.');
  const x = d3.scaleBand().domain(series.map((s) => s.congress)).range([left, W - right]).padding(0.18);
  const yShare = d3.scaleLinear().domain([0, 1]).range([topY + topH, topY]);
  const yLag = d3.scaleLinear().domain([0, d3.max(series, (s) => s.median ?? 0) || 1]).nice().range([lowY + lowH, lowY]);
  svg.append('g').attr('transform', `translate(${left},0)`).call(d3.axisLeft(yShare).ticks(4).tickFormat(d3.format('.0%'))).call((g) => g.select('.domain').remove());
  svg.append('g').attr('transform', `translate(${left},0)`).call(d3.axisLeft(yLag).ticks(4).tickFormat(fmt)).call((g) => g.select('.domain').remove());
  svg.append('text').attr('transform', `translate(14,${topY + topH / 2}) rotate(-90)`).attr('font-size', 11).attr('text-anchor', 'middle').attr('fill', INK).text('share summarized');
  svg.append('text').attr('transform', `translate(14,${lowY + lowH / 2}) rotate(-90)`).attr('font-size', 11).attr('text-anchor', 'middle').attr('fill', INK).text('median days');
  const tip = (s) => `${ordinal(s.congress)} Congress${s.ended ? '' : ' (in session)'}: ${fmt(s.bills)} introduced, ${fmt(s.summarized)} summarized `
    + `(${d3.format('.0%')(s.share)}), median ${s.median === null ? '–' : Math.round(s.median)} days`
    + (s.afterEnd ? `; ${fmt(s.afterEnd)} summaries dated after the Congress ended` : '');
  const bars = svg.append('g').selectAll('g').data(series).join('g').attr('class', 'congress-bar');
  bars.append('rect').attr('x', (s) => x(s.congress)).attr('width', x.bandwidth()).attr('fill', GOLD)
    .attr('y', topY).attr('height', (s) => yShare(s.share) - topY);
  bars.append('rect').attr('x', (s) => x(s.congress)).attr('width', x.bandwidth()).attr('fill', BLUE)
    .attr('y', (s) => yShare(s.share)).attr('height', (s) => topY + topH - yShare(s.share));
  bars.filter((s) => s.median !== null).append('rect').attr('x', (s) => x(s.congress)).attr('width', x.bandwidth()).attr('fill', BLUE).attr('rx', 2)
    .attr('y', (s) => yLag(s.median)).attr('height', (s) => lowY + lowH - yLag(s.median));
  bars.filter((s) => s.median !== null).append('text').attr('x', (s) => x(s.congress) + x.bandwidth() / 2).attr('y', (s) => yLag(s.median) - 4)
    .attr('font-size', 11).attr('text-anchor', 'middle').attr('fill', INK).text((s) => Math.round(s.median));
  bars.append('text').attr('x', (s) => x(s.congress) + x.bandwidth() / 2).attr('y', lowY + lowH + 16)
    .attr('font-size', 11).attr('text-anchor', 'middle').attr('fill', INK)
    .attr('font-weight', (s) => (s.congress === String(state.congress) ? 700 : 400)).text((s) => ordinal(s.congress));
  bars.append('title').text(tip);
  bars.on('mousemove', (event, s) => {
    d3.select('#tooltip').style('display', 'block').style('left', `${event.pageX + 12}px`).style('top', `${event.pageY - 10}px`).text(tip(s));
  }).on('mouseleave', () => d3.select('#tooltip').style('display', 'none'));
  const cur = series.find((s) => s.congress === String(state.congress));
  if (cur) {
    svg.append('rect').attr('id', 'congress-current').attr('x', x(cur.congress) - 3).attr('y', topY - 4).attr('width', x.bandwidth() + 6)
      .attr('height', lowY + lowH - topY + 8).attr('fill', 'none').attr('stroke', INK).attr('stroke-width', 1.5).attr('rx', 3);
  }
  const legend = svg.append('g').attr('transform', `translate(${W - right - 190},${topY - 14})`);
  for (const [i, [color, label]] of [[BLUE, 'has a summary'], [GOLD, 'still waiting']].entries()) {
    legend.append('rect').attr('x', i * 100).attr('y', 0).attr('width', 10).attr('height', 10).attr('rx', 2).attr('fill', color);
    legend.append('text').attr('x', i * 100 + 14).attr('y', 9).attr('font-size', 11).attr('fill', INK).text(label);
  }
  svg.append('text').attr('x', (left + W - right) / 2).attr('y', H - 6).attr('font-size', 11).attr('text-anchor', 'middle').attr('fill', INK).text('Congress');
}

function renderCumulative(target, series, keys, labels, title, yLabel, note = '') {
  const W = 920, H = 300, left = 76, right = 16, top = note ? 52 : 36, bottom = 56;
  const fig = d3.select(target).html('');
  if (series.length === 0) return;
  const parse = d3.utcParse('%Y-%m-%d');
  const x = d3.scaleUtc().domain(d3.extent(series, (s) => parse(s.date))).range([left, W - right]);
  const y = d3.scaleLinear().domain([0, d3.max(series, (s) => s[keys[0]])]).nice().range([H - bottom, top]);
  const svg = fig.append('svg').attr('viewBox', `0 0 ${W} ${H}`).attr('role', 'img').attr('aria-label', title);
  svg.append('text').attr('x', left).attr('y', 18).attr('font-size', 14).attr('font-weight', 600).attr('fill', INK).text(title);
  if (note) svg.append('text').attr('x', left).attr('y', 36).attr('font-size', 12).attr('fill', MUTED).text(note);
  svg.append('g').attr('transform', `translate(${left},0)`).call(d3.axisLeft(y).ticks(5).tickFormat(fmt)).call((g) => g.select('.domain').remove());
  // two-monthly ticks across one Congress; over a longer span, whole years at a spacing that keeps ~10 labels
  const [d0, d1] = x.domain(), years = (d1 - d0) / (365.25 * 86400000);
  const ticks = years <= 3 ? [d3.utcMonth.every(2), d3.utcFormat('%b %Y')] : [d3.utcYear.every(Math.max(1, Math.ceil(years / 10))), d3.utcFormat('%Y')];
  svg.append('g').attr('transform', `translate(0,${H - bottom})`).call(d3.axisBottom(x).ticks(ticks[0]).tickFormat(ticks[1])).call((g) => g.select('.domain').remove());
  svg.append('text').attr('transform', `translate(14,${(top + H - bottom) / 2}) rotate(-90)`).attr('font-size', 11).attr('text-anchor', 'middle').attr('fill', INK).text(yLabel);
  const line = (key) => d3.line().curve(d3.curveStepAfter).x((s) => x(parse(s.date))).y((s) => y(s[key]));
  const gap = d3.area().curve(d3.curveStepAfter).x((s) => x(parse(s.date))).y0((s) => y(s[keys[1]])).y1((s) => y(s[keys[0]]));
  svg.append('path').datum(series).attr('d', gap).attr('fill', GOLD).attr('fill-opacity', 0.45);
  svg.append('path').datum(series).attr('d', line(keys[0])).attr('fill', 'none').attr('stroke', INK).attr('stroke-width', 2);
  svg.append('path').datum(series).attr('d', line(keys[1])).attr('fill', 'none').attr('stroke', BLUE).attr('stroke-width', 2);
  const last = series[series.length - 1];
  svg.append('text').attr('x', W - right).attr('y', y(last[keys[0]]) - 6).attr('font-size', 11).attr('text-anchor', 'end').attr('fill', INK).text(`${fmt(last[keys[0]])} ${labels[0]}`);
  svg.append('text').attr('x', W - right).attr('y', y(last[keys[1]]) - 6).attr('font-size', 11).attr('text-anchor', 'end').attr('fill', BLUE).text(`${fmt(last[keys[1]])} ${labels[1]}`);
}

// ---- exports -------------------------------------------------------------------------------------------------------
const FONT_STACK = '"Source Sans 3", system-ui, sans-serif';
const STYLE_PROPS = ['font-family', 'font-size', 'font-weight', 'fill', 'fill-opacity', 'stroke', 'stroke-width', 'stroke-opacity', 'stroke-dasharray', 'opacity', 'text-anchor'];

function download(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename; a.style.display = 'none';
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

/** Standalone copy of a figure's svg: computed styles inlined, xmlns, explicit size, white background, a white band above the title. */
function standaloneSvg(svg) {
  const vb = svg.viewBox.baseVal;
  const clone = svg.cloneNode(true);
  const src = [svg, ...svg.querySelectorAll('*')], dst = [clone, ...clone.querySelectorAll('*')];
  src.forEach((el, i) => {
    const cs = getComputedStyle(el);
    for (const p of STYLE_PROPS) {
      const v = p === 'font-family' ? FONT_STACK : cs.getPropertyValue(p);
      if (v) dst[i].style.setProperty(p, v);
    }
  });
  const dstTitle = clone.querySelector('text');
  // the fallback font is wider than the webfont: shrink only the exported title (never below 12 px) until it fits the canvas with a right margin
  if (dstTitle) {
    const ctx = document.createElement('canvas').getContext('2d');
    const base = parseFloat(dstTitle.style.getPropertyValue('font-size')) || 14;
    ctx.font = `${dstTitle.style.getPropertyValue('font-weight') || 600} ${base}px system-ui, sans-serif`;
    const room = vb.width - (+dstTitle.getAttribute('x') || 0) - 12;
    const fit = Math.floor(base * Math.min(1, room / ctx.measureText(dstTitle.textContent).width) * 10) / 10;
    dstTitle.style.setProperty('font-size', `${Math.max(12, fit)}px`);
  }
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
  clone.setAttribute('width', vb.width);
  // breathing room above the title: every title sits in the svg with its baseline 13-18 px down, so push the content down until ~20 px of white is above its cap height
  const TITLE_CAP = 10, TITLE_TOP_WHITE = 20;
  const pad = Math.max(0, Math.round(TITLE_TOP_WHITE - (+(dstTitle && dstTitle.getAttribute('y')) - TITLE_CAP)));
  const H = vb.height + pad;
  clone.setAttribute('height', H);
  clone.setAttribute('viewBox', `${vb.x} ${vb.y} ${vb.width} ${H}`);
  if (pad) {
    const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    g.setAttribute('transform', `translate(0,${pad})`);
    while (clone.firstChild) g.appendChild(clone.firstChild);
    clone.appendChild(g);
  }
  clone.removeAttribute('style');
  clone.style.fontFamily = FONT_STACK;
  const bg = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
  for (const [k, v] of [['x', vb.x], ['y', vb.y], ['width', vb.width], ['height', H], ['fill', '#ffffff']]) bg.setAttribute(k, v);
  clone.insertBefore(bg, clone.firstChild);
  return { text: new XMLSerializer().serializeToString(clone), width: vb.width, height: H };
}

const figureSvg = (figure) => document.querySelector(`#${figure} svg`);

function exportSvg(figure) {
  const svg = figureSvg(figure);
  if (!svg) return;
  download(new Blob([standaloneSvg(svg).text], { type: 'image/svg+xml;charset=utf-8' }), `${exportName(figure, state, asOf)}.svg`);
}

function exportPng(figure) {
  const svg = figureSvg(figure);
  if (!svg) return;
  const { text, width, height } = standaloneSvg(svg);
  const img = new Image();
  img.onload = () => {
    const canvas = document.createElement('canvas');
    canvas.width = width * 2; canvas.height = height * 2;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    canvas.toBlob((blob) => { if (blob) download(blob, `${exportName(figure, state, asOf)}.png`); }, 'image/png');
  };
  img.onerror = () => console.warn('PNG export failed: the svg did not load as an image');
  img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(text)}`;
}

const CSV_COLUMNS = ['bill', 'congress', 'type', 'number', 'text_date', 'printed_date', 'summary_date', 'days', 'pages', 'title', 'url'];
function exportCsv(which) {
  const records = currentRecords(state);
  const lags = which === 'longest-lags';
  const rows = (lags ? longestLags(records, Infinity) : oldestWaiting(records, asOf, Infinity)).map((r) => ({
    bill: billLabel(r.type, r.number), type: r.type, number: r.number, text_date: r.text_date, printed_date: r.printed_date,
    summary_date: lags ? r.summary_date : '', days: lags ? r.lag_days : r.days_waiting, pages: r.pages, title: r.title,
    congress: r.congress, url: billUrl(r.congress, r.type, r.number),
  }));
  const columns = lags ? CSV_COLUMNS : CSV_COLUMNS.filter((c) => c !== 'summary_date');
  download(new Blob([toCsv(rows, columns)], { type: 'text/csv;charset=utf-8' }), `${exportName(which, state, asOf)}.csv`);
}

function setupExports() {
  document.querySelectorAll('.export-row').forEach((row) => {
    const { figure, label } = row.dataset;
    for (const [kind, fn] of [['PNG', exportPng], ['SVG', exportSvg]]) {
      const b = document.createElement('button');
      b.type = 'button'; b.textContent = `Download ${kind}`; b.setAttribute('aria-label', `Download ${label} as ${kind}`);
      b.addEventListener('click', () => fn(figure));
      row.appendChild(b);
    }
  });
  document.querySelectorAll('button[data-csv]').forEach((b) => b.addEventListener('click', () => exportCsv(b.dataset.csv)));
}

const esc = (v) => String(v ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

// cols: [header, cell(row) -> html, class]
function renderTable(selector, rows, cols) {
  const host = document.querySelector(`${selector} .table-wrap`);
  if (rows.length === 0) { host.innerHTML = '<p class="note">No bills in this view.</p>'; return; }
  host.innerHTML = `<table><thead><tr>${cols.map(([h, , c]) => `<th class="${c}">${h}</th>`).join('')}</tr></thead><tbody>`
    + rows.map((r) => `<tr>${cols.map(([, f, c]) => `<td class="${c}">${f(r)}</td>`).join('')}</tr>`).join('') + '</tbody></table>';
}

// in the pooled view a bill number needs its Congress: H.R. 1 exists in every one
const billText = (r) => billLabel(r.type, r.number) + (state.congress === ALL ? ` (${ordinal(r.congress)})` : '');
const billCell = (r) => `<a href="${esc(billUrl(r.congress, r.type, r.number))}" target="_blank" rel="noopener">${esc(billText(r))}</a>`;

function renderLists(records) {
  const bill = ['Bill', billCell, 'nowrap'];
  const textDate = ['Posted on GovInfo', (r) => esc(r.text_date), 'nowrap'], pages = ['Pages', (r) => (r.pages == null ? '–' : fmt(r.pages)), 'num'];
  const title = ['Title', (r) => esc(r.title), 'title'];
  renderTable('#longest-lags', longestLags(records), [bill, textDate,
    ['Summary date', (r) => esc(r.summary_date), 'nowrap'], ['Days', (r) => fmt(r.lag_days), 'num'], pages, title]);
  renderTable('#oldest-waiting', oldestWaiting(records, asOf), [bill, textDate, ['Days waiting', (r) => fmt(r.days_waiting), 'num'], pages, title]);
}

function render(state) {
  renderControls(state);
  const unranged = filterRecords(state.records, { stage: STAGE, type: state.type, range: null });
  const records = filterRecords(state.records, state);
  const allEditions = filterRecords(state.records, { stage: 'all', type: state.type, range: state.range });
  renderHeader(records, allEditions);
  renderPreText();
  renderExceptions(allEditions, records);
  renderByCongress(state);
  renderLists(records);
  renderHistogram(records, state);
  renderTimeseries(unranged, state);
  const scope = rangeLabel(state.range);
  renderCumulative('#cumulative .chart', cumulativeSeries(records), ['withText', 'summarized'], ['with text', 'summarized'],
    `${scope}: bills with text issued, and bills with a CRS summary. The gap is the backlog.`, 'bills');
  const pagesSeries = cumulativePages(records);
  const uncounted = pagesSeries.length ? pagesSeries.at(-1).versionsWithoutPages : 0;
  renderCumulative('#cumulative-pages .chart', pagesSeries, ['pagesIssued', 'pagesSummarized'], ['pages issued', 'pages summarized'],
    `${scope}: pages of bill text issued, and pages covered by a CRS summary.`, 'pages',
    [uncounted ? `${fmt(uncounted)} versions not yet page-counted.` : '', 'Pages of introduced text versions.'].filter(Boolean).join(' '));
}

/** A Congress's document: already loaded, or added now as a <script> tag for ../data/<n>/delays.js, which puts it on
 *  window.BILL_DELAYS under its number. A tag rather than fetch() so the page still works opened from disk. */
function loadCongress(entry) {
  const key = String(entry.congress);
  const have = () => window.BILL_DELAYS?.[key];
  if (have()) return Promise.resolve(have());
  return new Promise((resolve, reject) => {
    const tag = document.createElement('script');
    tag.src = `../data/${entry.file}`;
    tag.onload = () => (have() ? resolve(have()) : reject(new Error(`${entry.file} did not define Congress ${key}`)));
    tag.onerror = () => reject(new Error(`data/${entry.file} not found`));
    document.head.appendChild(tag);
  });
}

const ALL = 'all'; // the picker's value for every Congress pooled

let showing = 0; // the latest showCongress() call; an earlier load that lands late is dropped
/** Show one Congress, or ALL of them pooled into one view. Records are tagged with their Congress so bills, links and
 *  exports stay per Congress when they are pooled. */
async function showCongress(n) {
  const ticket = ++showing;
  const pooled = String(n) === ALL;
  const entries = pooled ? state.congresses.filter((e) => (e.comparison?.all?.introduced_bills ?? 0) > 0)
    : state.congresses.filter((e) => String(e.congress) === String(n));
  if (entries.length === 0) throw new Error(`Congress ${n} is not in data/congresses.js`);
  const select = document.getElementById('congress');
  if (select) select.disabled = true;
  if (pooled) document.getElementById('subtitle').textContent = `Loading ${entries.length} Congresses…`;
  try {
    const docs = await Promise.all(entries.map(loadCongress));
    if (ticket !== showing) return;
    docs.forEach((doc, i) => { if (!Array.isArray(doc.records)) throw new Error(`${entries[i].file} has no records array`); });
    const sum = (key) => docs.reduce((s, d) => s + (d[key] || 0), 0);
    state.entry = pooled
      ? { congress: ALL, ended: entries.every((e) => e.ended), end: entries.map((e) => e.end).sort().at(-1),
        versions_without_ingest_date: entries.reduce((s, e) => s + (e.versions_without_ingest_date || 0), 0),
        text_versions: entries.reduce((s, e) => s + (e.text_versions || 0), 0) }
      : entries[0];
    state.congress = pooled ? ALL : String(entries[0].congress);
    state.records = mergeCongresses(entries.map((e, i) => [e.congress, docs[i]]));
    state.summaryBefore = {};
    for (const d of docs) for (const [k, v] of Object.entries(d.summary_before_text || {})) state.summaryBefore[k] = (state.summaryBefore[k] || 0) + v;
    congress = state.congress;
    asOf = docs.map((d) => d.as_of).sort().at(-1);
    const intro = sum('introduced_versions'), printedOnly = sum('introduced_without_ingest_date');
    const where = pooled ? 'these Congresses' : 'this Congress';
    const start = printedOnly === 0 ? 'the day the text reached GovInfo'
      : printedOnly === intro ? `the date printed on the bill (no GovInfo posting dates collected for ${where})`
        : `the day the text reached GovInfo, or the printed date for ${fmt(printedOnly)} of ${fmt(intro)} introduced versions`;
    const label = pooled ? allCongressesLabel(entries) : congressLabel(entries[0]);
    document.getElementById('subtitle').textContent =
      `Lag between a bill text version and its CRS summary on Congress.gov, ${label}, as of ${asOf}. Measured from ${start}.`;
    renderControls(state);
    refreshControls(state);
    render(state);
  } finally {
    if (select && ticket === showing) select.disabled = false;
  }
}

async function main() {
  try {
    if (typeof d3 === 'undefined') throw new Error('d3 failed to load');
    fmt = d3.format(',');
    // The index arrives as window.BILL_DELAY_CONGRESSES from ../data/congresses.js, which delays.py
    // writes next to congresses.json so the page can load it from disk (fetch() is blocked on file:// pages).
    const index = window.BILL_DELAY_CONGRESSES;
    if (!index) throw new Error('data/congresses.js not found');
    if (!Array.isArray(index.congresses)) throw new Error('congresses.js has no congresses list');
    state.congresses = index.congresses;
    const newest = defaultCongress(state.congresses);
    if (newest === null) throw new Error('no Congress in data/congresses.js has an introduced bill');
    // the page opens on every Congress pooled; with a single Congress in the data that is just that Congress
    const usable = state.congresses.filter((e) => (e.comparison?.all?.introduced_bills ?? 0) > 0);
    const first = usable.length > 1 ? ALL : newest;
    state.congress = String(first);
    setupExports();
    await showCongress(first);
  } catch (err) {
    showError(err, false);
  }
}

/** Empty the page and say what failed. keepControls leaves the Congress picker up so another Congress can be tried. */
function showError(err, keepControls) {
  if (!keepControls) document.getElementById('controls').innerHTML = '';
  document.querySelectorAll('figure .chart, #hist-chart, .table-wrap').forEach((f) => { f.innerHTML = ''; });
  document.getElementById('pre-text').textContent = '';
  const cards = document.getElementById('cards');
  cards.innerHTML = '';
  const p = document.createElement('p');
  p.className = 'error';
  p.textContent = `Could not load the data (${err.message}). Run delays.py first.`;
  cards.appendChild(p);
}

main();
