// GTO-Wizard-style feedback: verdict badge, ranked EV table, explain text.

import { faceText } from './tiles.js';

export const VERDICT_LABELS = { best: '最佳', good: '良好', inaccuracy: '小失誤', mistake: '失誤' };

export function verdictEl(verdict, marginal, evDelta, text) {
  const el = document.createElement('div');
  el.className = `verdict ${verdict}`;
  const badge = document.createElement('span');
  badge.className = 'badge';
  badge.textContent = VERDICT_LABELS[verdict] + (marginal ? '（邊緣）' : '');
  const body = document.createElement('span');
  body.className = 'text';
  body.textContent = text;
  const delta = document.createElement('span');
  delta.className = 'delta';
  delta.textContent = `EV 差 ${evDelta.toFixed(1)} 分`;
  el.append(badge, body, delta);
  return el;
}

function cell(text, tag = 'td') {
  const el = document.createElement(tag);
  el.textContent = text;
  return el;
}

// entries: W1 EV entry payloads; chosenTile/bestTile mark rows.
export function evTableEl(entries, { chosenTile = null, bestTile = null } = {}) {
  const wrap = document.createElement('div');
  wrap.className = 'evtable-wrap';
  const table = document.createElement('table');
  table.className = 'evtable';
  const head = document.createElement('tr');
  ['切牌', '淨EV', 'P(自摸)', '存活P(和)', 'P(流局)', 'E[和牌值]', 'E[放銃]'].forEach((label) => head.append(cell(label, 'th')));
  table.append(head);
  entries.forEach((entry) => {
    const row = document.createElement('tr');
    if (!entry.is_fold && entry.discard === chosenTile) row.classList.add('chosen-row');
    if (!entry.is_fold && entry.discard === bestTile) row.classList.add('best-row');
    row.append(cell(entry.is_fold ? '棄和' : faceText(entry.discard)));
    row.append(cell(entry.net_ev.toFixed(1)));
    row.append(cell(entry.p_win.toFixed(3)));
    row.append(cell(entry.survival_adjusted_p_win.toFixed(3)));
    row.append(cell(entry.p_draw.toFixed(3)));
    row.append(cell(entry.mean_win_value === null ? '-' : entry.mean_win_value.toFixed(1)));
    row.append(cell(entry.risk_ev.toFixed(1)));
    table.append(row);
  });
  wrap.append(table);
  return wrap;
}

export function evDetailsEl(entries, { chosenTile = null, bestTile = null, explain = null, open = false } = {}) {
  const details = document.createElement('details');
  details.className = 'evwrap';
  details.open = open;
  const summary = document.createElement('summary');
  summary.textContent = 'EV 排名表與說明';
  details.append(summary, evTableEl(entries, { chosenTile, bestTile }));
  if (explain) {
    const pre = document.createElement('div');
    pre.className = 'explain';
    pre.textContent = explain;
    details.append(pre);
  }
  return details;
}

export function bestLineEl(text) {
  const el = document.createElement('div');
  el.className = 'bestline';
  el.textContent = text;
  return el;
}

export function scorebarEl(score) {
  const el = document.createElement('div');
  el.className = 'scorebar';
  const decisions = score.decisions || 0;
  const accuracy = decisions ? `${Math.round((100 * score.best) / decisions)}%` : '—';
  const average = decisions ? (score.loss / decisions).toFixed(2) : '—';
  el.innerHTML = `<span>手數 <b>${decisions}</b></span>`
    + `<span>最佳率 <b>${accuracy}</b></span>`
    + `<span>總EV損失 <b>${(score.loss || 0).toFixed(2)}</b> 分</span>`
    + `<span>每手均損 <b>${average}</b></span>`;
  return el;
}
