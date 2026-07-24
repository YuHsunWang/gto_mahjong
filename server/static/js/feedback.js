// Heuristic-EV feedback: verdict badge, ranked table, and scope disclosure.

import { faceText } from './tiles.js';

export const VERDICT_LABELS = { best: '模型最佳', good: '良好', inaccuracy: '小失誤', mistake: '失誤' };
const FOLD_PRINCIPLES = {
  genbutsu_first: '宣告對手現物優先',
  minimum_conditional_loss_each_turn: '每巡依新公開資訊重算條件損失',
  preserve_safe_inventory: '保留重複安全牌，供後續巡目使用',
};

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
  ['切牌', '淨EV', '95% CI', 'P(自摸)', '存活P(和)', 'P(流局)', 'E[和牌值]', 'E[放銃]'].forEach((label) => head.append(cell(label, 'th')));
  table.append(head);
  entries.filter((entry) => !entry.is_fold).forEach((entry) => {
    const row = document.createElement('tr');
    if (entry.discard === chosenTile) row.classList.add('chosen-row');
    if (entry.discard === bestTile) row.classList.add('best-row');
    row.append(cell(faceText(entry.discard)));
    row.append(cell(entry.net_ev.toFixed(1)));
    row.append(cell(entry.ci95 ? `[${entry.ci95[0].toFixed(1)}, ${entry.ci95[1].toFixed(1)}]` : '—'));
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

function defensePlanEl(entry) {
  const plan = entry?.action_plan;
  if (!plan) return null;
  const box = document.createElement('div');
  box.className = 'note defense-plan';
  const inventory = plan.safe_inventory.length
    ? plan.safe_inventory.map(faceText).join('、')
    : '目前無零風險庫存';
  const title = document.createElement('b');
  title.textContent = `多巡防守策略：第一張切 ${faceText(plan.first_discard)}（policy EV ${entry.net_ev.toFixed(1)}）`;
  const list = document.createElement('ul');
  plan.principles.forEach((principle) => {
    const item = document.createElement('li');
    item.textContent = FOLD_PRINCIPLES[principle] || principle;
    list.append(item);
  });
  const safe = document.createElement('div');
  safe.textContent = `安全牌庫存：${inventory}`;
  box.append(title, list, safe);
  return box;
}

export function evDetailsEl(entries, {
  chosenTile = null,
  bestTile = null,
  explain = null,
  open = false,
  topGap = null,
} = {}) {
  const details = document.createElement('details');
  details.className = 'evwrap';
  details.open = open;
  const summary = document.createElement('summary');
  summary.textContent = 'EV 排名表與說明';
  details.append(summary, evTableEl(entries, { chosenTile, bestTile }));
  const defense = defensePlanEl(entries.find((entry) => entry.is_fold));
  if (defense) details.append(defense);
  if (topGap) {
    const uncertainty = document.createElement('div');
    uncertainty.className = 'note';
    uncertainty.textContent = `前兩名 paired 差值 ${topGap.mean.toFixed(2)}，95% CI `
      + `[${topGap.ci95[0].toFixed(2)}, ${topGap.ci95[1].toFixed(2)}]；`
      + `${topGap.wording === 'clear' ? '差異達門檻' : '排名不確定／邊緣'}`;
    details.append(uncertainty);
  }
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

export function modelScopeEl(metadata = null) {
  const el = document.createElement('div');
  el.className = 'note model-scope';
  const calibration = metadata
    ? (metadata.fallback_used
      ? 'heuristic fallback（校準表缺失）'
      : `bot-domain calibration ${metadata.calibration_id}`)
    : 'bot-domain calibration（缺表時改用 heuristic fallback）';
  const scheme = metadata?.scheme
    ? `底${metadata.scheme.base_units}／台${metadata.scheme.tai_units}`
    : '目前底台設定';
  el.textContent = `模型範圍：${scheme}；進攻只估自摸的 Monte Carlo EV；`
    + `放銃與對手價值屬 heuristic EV；${calibration}，不代表真人牌局。`;
  return el;
}

export function scorebarEl(score) {
  const el = document.createElement('div');
  el.className = 'scorebar';
  const decisions = score.decisions || 0;
  const accuracy = decisions ? `${Math.round((100 * score.best) / decisions)}%` : '—';
  const average = decisions ? (score.loss / decisions).toFixed(2) : '—';
  el.innerHTML = `<span>手數 <b>${decisions}</b></span>`
    + `<span>模型最佳率 <b>${accuracy}</b></span>`
    + `<span>總EV損失 <b>${(score.loss || 0).toFixed(2)}</b> 分</span>`
    + `<span>每手均損 <b>${average}</b></span>`;
  return el;
}
