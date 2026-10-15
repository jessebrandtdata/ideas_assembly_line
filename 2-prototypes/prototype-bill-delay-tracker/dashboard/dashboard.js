import { headerMetrics, binLags, filterRecords, monthlySeries } from './metrics.js';

const BLUE = '#104378', RED = '#b2182b', INK = '#1f2933', MUTED = '#6b7280';
const fmt = d3.format(',');
const day = (v) => (v === null ? '–' : `${Math.round(v)}`);

const state = { records: [], stage: 'introduced', type: 'all', range: null, width: 30 };

function card(label, value, note = '') {
  return `<div class="card"><div class="value">${value}</div><div class="label">${label}</div><div class="note">${note}</div></div>`;
}

function renderHeader(records, allVersions) {
  const m = headerMetrics(records);
  const p = headerMetrics(allVersions); // pages count every edition, not only the staged one
  document.getElementById('cards').innerHTML = [
    card('pages of bill text', fmt(p.pagesTotal), `${fmt(p.pagesCounted)} of ${fmt(p.versions)} versions counted`),
    card('bills summarized', fmt(m.summarized), `${fmt(m.waiting)} still waiting`),
    card('reported by committee', fmt(m.reported), 'bills with an rh/rs text version'),
    card('mean lag (days)', day(m.lagMean), `n=${fmt(m.n)}`),
    card('median lag (days)', day(m.lagMedian)),
    card('max lag (days)', day(m.lagMax)),
  ].join('');
}

function renderHistogram(records, width, stage) {
  const bins = binLags(records, width);
  const m = headerMetrics(records);
  const W = 920, H = 320, left = 56, right = 16, top = 36, bottom = 56;
  const fig = d3.select('#histogram').html('');
  if (bins.length === 0) {
    fig.append('p').attr('class', 'note').text('No summarized bills in this view.');
    return;
  }
  const svg = fig.append('svg').attr('viewBox', `0 0 ${W} ${H}`).attr('role', 'img')
    .attr('aria-label', 'Histogram of lag in days');
  svg.append('text').attr('x', left).attr('y', 13).attr('font-size', 14).attr('font-weight', 600).attr('fill', INK)
    .text(`Days from text to CRS summary, ${width}-day bins (n=${fmt(m.n)} ${stage === 'all' ? 'summaries' : 'summarized'}; ${fmt(m.waiting)} still waiting, not shown)`);
  const x = d3.scaleBand().domain(bins.map((_, i) => i)).range([left, W - right]).padding(0.12);
  const y = d3.scaleLinear().domain([0, d3.max(bins, (b) => b.count)]).nice().range([H - bottom, top]);
  svg.append('g').attr('transform', `translate(${left},0)`).call(d3.axisLeft(y).ticks(5).tickFormat(fmt))
    .call((g) => g.select('.domain').remove()).selectAll('text').attr('fill', MUTED);
  svg.append('g').attr('transform', `translate(0,${H - bottom})`)
    .call(d3.axisBottom(x).tickFormat((i) => (bins[i].to === null ? `${bins[i].from}+` : `${bins[i].from}–${bins[i].to - 1}`)))
    .call((g) => g.select('.domain').remove()).selectAll('text').attr('fill', MUTED).attr('font-size', 9);
  svg.append('text').attr('x', (left + W - right) / 2).attr('y', H - 14).attr('font-size', 11).attr('text-anchor', 'middle').attr('fill', INK)
    .text('lag in days');
  svg.append('text').attr('transform', `translate(14,${(top + H - bottom) / 2}) rotate(-90)`).attr('font-size', 11).attr('text-anchor', 'middle').attr('fill', INK)
    .text('bills');
  svg.append('g').selectAll('rect').data(bins).join('rect')
    .attr('x', (_, i) => x(i)).attr('y', (b) => y(b.count)).attr('width', x.bandwidth())
    .attr('height', (b) => y(0) - y(b.count)).attr('fill', BLUE).attr('rx', 2)
    .on('mousemove', (event, b) => {
      const share = m.n ? (b.count / m.n) : 0;
      const range = b.to === null ? `${b.from}+ days` : `${b.from}–${b.to - 1} days`;
      d3.select('#tooltip').style('display', 'block').style('left', `${event.pageX + 12}px`).style('top', `${event.pageY - 10}px`)
        .text(`${range}: ${fmt(b.count)} bills (${d3.format('.1%')(share)} of summarized)`);
    })
    .on('mouseleave', () => d3.select('#tooltip').style('display', 'none'));
  svg.selectAll('rect').filter((b) => b && 'count' in b).append('title')
    .text((b) => `${b.to === null ? `${b.from}+` : `${b.from}–${b.to - 1}`} days: ${fmt(b.count)} bills`);
  svg.append('g').selectAll('text').data(bins).join('text')
    .attr('x', (_, i) => x(i) + x.bandwidth() / 2).attr('y', (b) => y(b.count) - 4)
    .attr('font-size', 11).attr('text-anchor', 'middle').attr('fill', INK).text((b) => (b.count ? fmt(b.count) : ''));
  // median and mean rules sit at their position inside the band scale
  const pos = (v) => { const i = Math.min(Math.floor(v / width), bins.length - 1); return x(i) + x.bandwidth() * Math.min(1, (v - i * width) / width); };
  for (const [v, label] of [[m.lagMedian, 'median'], [m.lagMean, 'mean']]) {
    svg.append('line').attr('x1', pos(v)).attr('x2', pos(v)).attr('y1', top - 6).attr('y2', H - bottom)
      .attr('stroke', RED).attr('stroke-width', 1.5).attr('stroke-dasharray', label === 'mean' ? '4 3' : null);
    const crowded = label === 'mean' && Math.abs(pos(m.lagMean) - pos(m.lagMedian)) < 60;
    svg.append('text').attr('x', pos(v) - 4).attr('y', crowded ? top + 4 : top - 10).attr('font-size', 11).attr('text-anchor', 'end').attr('fill', RED)
      .text(`${label} ${Math.round(v)}d`);
  }
}

const WIDTHS = [7, 30, 90];
const STAGES = [['introduced', 'Introduced'], ['reported', 'Reported by committee'], ['passed', 'Passed a chamber'], ['enrolled', 'Enrolled'], ['all', 'All stages']];
const TYPES = [['all', 'All bill types'], ['hr', 'H.R.'], ['s', 'S.'], ['hjres', 'H.J.Res.'], ['sjres', 'S.J.Res.']];

function select(id, label, options, value) {
  return `<label>${label}<select id="${id}">${options.map(([v, text]) =>
    `<option value="${v}"${v === value ? ' selected' : ''}>${text}</option>`).join('')}</select></label>`;
}

function renderControls(state) {
  const el = document.getElementById('controls');
  if (el.children.length) return; // built once; selects keep their own value
  el.innerHTML = select('stage', 'Stage', STAGES, state.stage) + select('type', 'Bill type', TYPES, state.type)
    + `<label>Bin width<span role="group" aria-label="Bin width">${WIDTHS.map((w) => `<button type="button" data-width="${w}" aria-pressed="${w === state.width}">${w} days</button>`).join('')}</span></label>`
    + '<button id="clear" type="button">Clear month selection</button>';
  el.querySelector('#stage').addEventListener('change', (e) => { state.stage = e.target.value; render(state); });
  el.querySelector('#type').addEventListener('change', (e) => { state.type = e.target.value; render(state); });
  el.querySelectorAll('[data-width]').forEach((b) => b.addEventListener('click', () => {
    state.width = +b.dataset.width;
    el.querySelectorAll('[data-width]').forEach((o) => o.setAttribute('aria-pressed', String(o === b)));
    render(state);
  }));
  el.querySelector('#clear').addEventListener('click', () => { state.range = null; render(state); });
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const monthLabel = (m) => MONTHS[+m.slice(5, 7) - 1];
const lastDay = (m) => { const [y, mo] = m.split('-').map(Number); return new Date(Date.UTC(y, mo, 0)).toISOString().slice(0, 10); };

function renderTimeseries(records, state) {
  const series = monthlySeries(records);
  const W = 920, left = 76, right = 16, topY = 52, topH = 150, botY = 290, botH = 170, H = botY + botH + 60;
  const fig = d3.select('#timeseries').html('');
  if (series.length === 0) return;
  const svg = fig.append('svg').attr('viewBox', `0 0 ${W} ${H}`).attr('role', 'img').attr('aria-label', 'Lag by month of introduction');
  svg.append('text').attr('x', left).attr('y', 18).attr('font-size', 14).attr('font-weight', 600).attr('fill', INK)
    .text('By month the text was issued: share with a CRS summary, and lag among those summarized. Drag to select months.');
  const x = d3.scaleBand().domain(series.map((s) => s.month)).range([left, W - right]).padding(0.18);
  const monthAxis = (y) => {
    const g = svg.append('g');
    for (const s of series) {
      const cx = x(s.month) + x.bandwidth() / 2;
      g.append('text').attr('x', cx).attr('y', y).attr('font-size', 10).attr('text-anchor', 'middle').attr('fill', MUTED).text(monthLabel(s.month));
      if (s.month.endsWith('-01') || s === series[0]) g.append('text').attr('x', cx).attr('y', y + 12).attr('font-size', 10).attr('font-weight', 600).attr('text-anchor', 'middle').attr('fill', INK).text(s.month.slice(0, 4));
    }
    g.append('text').attr('x', (left + W - right) / 2).attr('y', y + 28).attr('font-size', 11).attr('text-anchor', 'middle').attr('fill', INK).text('Month the text version was issued');
  };
  // top: share
  const yShare = d3.scaleLinear().domain([0, 1]).range([topY + topH, topY]);
  svg.append('g').attr('transform', `translate(${left},0)`).call(d3.axisLeft(yShare).ticks(4).tickFormat(d3.format('.0%'))).call((g) => g.select('.domain').remove());
  svg.append('text').attr('transform', `translate(14,${topY + topH / 2}) rotate(-90)`).attr('font-size', 11).attr('text-anchor', 'middle').attr('fill', INK).text('Share of that month\'s bills');
  const bars = svg.append('g').selectAll('g').data(series).join('g');
  bars.append('rect').attr('x', (s) => x(s.month)).attr('width', x.bandwidth()).attr('fill', RED)
    .attr('y', topY).attr('height', (s) => yShare(1 - s.waiting / (s.summarized + s.waiting || 1)) - topY);
  bars.append('rect').attr('x', (s) => x(s.month)).attr('width', x.bandwidth()).attr('fill', BLUE)
    .attr('y', (s) => yShare(s.summarized / (s.summarized + s.waiting || 1))).attr('height', (s) => topY + topH - yShare(s.summarized / (s.summarized + s.waiting || 1)));
  bars.append('title').text((s) => `${s.month}: ${fmt(s.summarized)} summarized, ${fmt(s.waiting)} waiting`);
  monthAxis(topY + topH + 14);
  // bottom: lag lines
  const yMax = d3.max(series, (s) => s.p90Lag ?? 0) || 1;
  const yLag = d3.scaleLinear().domain([0, yMax]).nice().range([botY + botH, botY]);
  svg.append('g').attr('transform', `translate(${left},0)`).call(d3.axisLeft(yLag).ticks(5)).call((g) => g.select('.domain').remove());
  svg.append('text').attr('transform', `translate(14,${botY + botH / 2}) rotate(-90)`).attr('font-size', 11).attr('text-anchor', 'middle').attr('fill', INK).text('Days, text to CRS summary');
  const line = (key) => d3.line().defined((s) => s[key] !== null).x((s) => x(s.month) + x.bandwidth() / 2).y((s) => yLag(s[key]));
  svg.append('path').datum(series).attr('d', line('p90Lag')).attr('fill', 'none').attr('stroke', MUTED).attr('stroke-width', 2).attr('stroke-dasharray', '4 3');
  svg.append('path').datum(series).attr('d', line('medianLag')).attr('fill', 'none').attr('stroke', BLUE).attr('stroke-width', 2);
  svg.append('text').attr('x', left).attr('y', botY - 6).attr('font-size', 11).attr('fill', INK).text('— median   ┄ 90th percentile   (lag among the bills summarized so far; recent months are right-censored)');
  monthAxis(botY + botH + 14);
  // brush over the whole height; snaps to month bands and sets state.range
  const brush = d3.brushX().extent([[left, topY], [W - right, botY + botH]]).on('end', ({ selection, sourceEvent }) => {
    if (!sourceEvent) return; // programmatic move, not the user
    if (!selection) { state.range = null; render(state); return; }
    const picked = series.filter((s) => x(s.month) + x.bandwidth() > selection[0] && x(s.month) < selection[1]).map((s) => s.month);
    if (picked.length === 0) { state.range = null; render(state); return; }
    state.range = [`${picked[0]}-01`, lastDay(picked[picked.length - 1])];
    render(state);
  });
  const g = svg.append('g').call(brush);
  if (state.range) {
    const from = series.findIndex((s) => `${s.month}-01` === state.range[0]);
    const to = series.findIndex((s) => lastDay(s.month) === state.range[1]);
    if (from >= 0 && to >= 0) g.call(brush.move, [x(series[from].month), x(series[to].month) + x.bandwidth()]);
  }
}

export function render(state) {
  renderControls(state);
  const records = filterRecords(state.records, state);
  renderHeader(records, filterRecords(state.records, { stage: 'all', type: state.type, range: state.range }));
  renderHistogram(records, state.width, state.stage);
  renderTimeseries(filterRecords(state.records, { stage: state.stage, type: state.type, range: null }), state);
}

async function main() {
  try {
    const res = await fetch('../data/delays.json');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const doc = await res.json();
    state.records = doc.records;
    document.getElementById('subtitle').textContent =
      `Lag between a bill text version on GovInfo and its CRS summary on Congress.gov, ${doc.congress}th Congress, as of ${doc.as_of}.`;
    render(state);
  } catch (err) {
    document.getElementById('cards').innerHTML = `<p class="error">Could not load data/delays.json (${err.message}). Run delays.py first.</p>`;
  }
}

main();
