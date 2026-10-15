import { headerMetrics, binLags, filterRecords } from './metrics.js';

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

function renderHistogram(records, width) {
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
  svg.append('text').attr('x', left).attr('y', 18).attr('font-size', 14).attr('font-weight', 600).attr('fill', INK)
    .text(`Days from text to CRS summary, ${width}-day bins (n=${fmt(m.n)} summarized; ${fmt(m.waiting)} still waiting, not shown)`);
  const x = d3.scaleBand().domain(bins.map((_, i) => i)).range([left, W - right]).padding(0.12);
  const y = d3.scaleLinear().domain([0, d3.max(bins, (b) => b.count)]).nice().range([H - bottom, top]);
  svg.append('g').attr('transform', `translate(${left},0)`).call(d3.axisLeft(y).ticks(5).tickFormat(fmt))
    .call((g) => g.select('.domain').remove()).selectAll('text').attr('fill', MUTED);
  svg.append('g').attr('transform', `translate(0,${H - bottom})`)
    .call(d3.axisBottom(x).tickFormat((i) => (bins[i].to === null ? `${bins[i].from}+` : `${bins[i].from}`)))
    .call((g) => g.select('.domain').remove()).selectAll('text').attr('fill', MUTED);
  svg.append('text').attr('x', (left + W - right) / 2).attr('y', H - 14).attr('font-size', 11).attr('text-anchor', 'middle').attr('fill', INK)
    .text('lag in days (bin start)');
  svg.append('text').attr('transform', `translate(14,${(top + H - bottom) / 2}) rotate(-90)`).attr('font-size', 11).attr('text-anchor', 'middle').attr('fill', INK)
    .text('bills');
  svg.append('g').selectAll('rect').data(bins).join('rect')
    .attr('x', (_, i) => x(i)).attr('y', (b) => y(b.count)).attr('width', x.bandwidth())
    .attr('height', (b) => y(0) - y(b.count)).attr('fill', BLUE).attr('rx', 2);
  svg.append('g').selectAll('text').data(bins).join('text')
    .attr('x', (_, i) => x(i) + x.bandwidth() / 2).attr('y', (b) => y(b.count) - 4)
    .attr('font-size', 11).attr('text-anchor', 'middle').attr('fill', INK).text((b) => (b.count ? fmt(b.count) : ''));
  // median and mean rules sit at their position inside the band scale
  const pos = (v) => { const i = Math.min(Math.floor(v / width), bins.length - 1); return x(i) + x.bandwidth() * Math.min(1, (v - i * width) / width); };
  for (const [v, label] of [[m.lagMedian, 'median'], [m.lagMean, 'mean']]) {
    svg.append('line').attr('x1', pos(v)).attr('x2', pos(v)).attr('y1', top - 6).attr('y2', H - bottom)
      .attr('stroke', RED).attr('stroke-width', 1.5).attr('stroke-dasharray', label === 'mean' ? '4 3' : null);
    svg.append('text').attr('x', pos(v) + 4).attr('y', top + (label === 'mean' ? 26 : 12)).attr('font-size', 11).attr('fill', RED)
      .text(`${label} ${Math.round(v)}d`);
  }
}

const STAGES = [['introduced', 'Introduced'], ['reported', 'Reported by committee'], ['passed', 'Passed a chamber'], ['enrolled', 'Enrolled'], ['all', 'All stages']];
const TYPES = [['all', 'All bill types'], ['hr', 'H.R.'], ['s', 'S.'], ['hjres', 'H.J.Res.'], ['sjres', 'S.J.Res.']];

function select(id, label, options, value) {
  return `<label>${label}<select id="${id}">${options.map(([v, text]) =>
    `<option value="${v}"${v === value ? ' selected' : ''}>${text}</option>`).join('')}</select></label>`;
}

function renderControls(state) {
  const el = document.getElementById('controls');
  if (el.children.length) return; // built once; selects keep their own value
  el.innerHTML = select('stage', 'Stage', STAGES, state.stage) + select('type', 'Bill type', TYPES, state.type);
  el.querySelector('#stage').addEventListener('change', (e) => { state.stage = e.target.value; render(state); });
  el.querySelector('#type').addEventListener('change', (e) => { state.type = e.target.value; render(state); });
}

export function render(state) {
  renderControls(state);
  const records = filterRecords(state.records, state);
  renderHeader(records, filterRecords(state.records, { stage: 'all', type: state.type, range: state.range }));
  renderHistogram(records, state.width);
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
