// Decision feedback: net-EV comparison, paired-ranking state, and session mix.

import { faceText, tileEl } from './tiles.js';

export const VERDICT_LABELS = {
  best: '模型領先',
  good: '正確',
  inaccuracy: '小失誤',
  mistake: '失誤',
};

const FOLD_PRINCIPLES = {
  genbutsu_first: '宣告對手現物優先',
  minimum_conditional_loss_each_turn: '每巡依新公開資訊重算條件損失',
  preserve_safe_inventory: '保留重複安全牌，供後續巡目使用',
};

function fixed(value, digits = 2) {
  return Number.isFinite(value) ? value.toFixed(digits) : '—';
}

function signed(value, digits = 2) {
  if (!Number.isFinite(value)) return '—';
  return `${value >= 0 ? '+' : ''}${value.toFixed(digits)}`;
}

function topPairContains(grade, tile) {
  const gap = grade?.top1_vs_top2;
  return gap && (tile === gap.top_discard || tile === gap.runner_up_discard);
}

export function verdictEl(verdict, marginal, evDelta, text, {
  rankingState = 'clear',
  chosenInTopPair = false,
} = {}) {
  const unresolvedChoice = rankingState !== 'clear' && chosenInTopPair;
  const visualState = unresolvedChoice ? 'unresolved' : verdict;
  const el = document.createElement('div');
  el.className = `verdict ${visualState}`;
  const badge = document.createElement('span');
  badge.className = 'badge';
  if (unresolvedChoice) {
    badge.textContent = rankingState === 'uncertain' ? '≈ 無法區分' : '≈ 差異很小';
  } else {
    badge.textContent = VERDICT_LABELS[verdict] || verdict;
    if (marginal && rankingState === 'clear') badge.textContent += '（邊緣）';
  }
  const body = document.createElement('span');
  body.className = 'text';
  body.textContent = text;
  const delta = document.createElement('span');
  delta.className = 'delta';
  delta.textContent = unresolvedChoice ? '不計排名獎懲' : `net EV 差 ${fixed(evDelta)}`;
  el.append(badge, body, delta);
  return el;
}

function cell(text, tag = 'td') {
  const el = document.createElement(tag);
  el.textContent = text;
  return el;
}

export function evTableEl(entries, {
  chosenTile = null,
  bestTile = null,
  rankingState = null,
  topGap = null,
} = {}) {
  const wrap = document.createElement('div');
  wrap.className = 'evtable-wrap';
  const table = document.createElement('table');
  table.className = 'evtable';
  const head = document.createElement('tr');
  ['打牌', '估計 net EV', '95% CI', 'P(自摸)', 'P(流局)', 'E[和牌值]', '樣本'].forEach((label) => head.append(cell(label, 'th')));
  table.append(head);
  const resolvedRankingState = rankingState || topGap?.wording || 'clear';
  entries.filter((entry) => !entry.is_fold).forEach((entry) => {
    const row = document.createElement('tr');
    const indistinguishable = resolvedRankingState !== 'clear'
      && topGap
      && (entry.discard === topGap.top_discard || entry.discard === topGap.runner_up_discard);
    if (entry.discard === chosenTile) row.classList.add('chosen-row');
    if (resolvedRankingState === 'clear' && entry.discard === bestTile) row.classList.add('model-leader-row');
    if (indistinguishable) row.classList.add('indistinguishable-row');
    row.append(cell(`${indistinguishable ? '≈ ' : ''}${faceText(entry.discard)}`));
    row.append(cell(fixed(entry.net_ev)));
    row.append(cell(entry.ci95 ? `[${fixed(entry.ci95[0])}, ${fixed(entry.ci95[1])}]` : '—'));
    row.append(cell(fixed(entry.p_win, 3)));
    row.append(cell(fixed(entry.p_draw, 3)));
    row.append(cell(entry.mean_win_value === null ? '—' : fixed(entry.mean_win_value)));
    row.append(cell(String(entry.sample_count ?? '—')));
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
  const title = document.createElement('b');
  title.textContent = `多巡防守策略：第一張切 ${faceText(plan.first_discard)}（policy net EV ${fixed(entry.net_ev)}）`;
  const list = document.createElement('ul');
  (plan.principles || []).forEach((principle) => {
    const item = document.createElement('li');
    item.textContent = FOLD_PRINCIPLES[principle] || principle;
    list.append(item);
  });
  const safe = document.createElement('div');
  const inventory = Array.isArray(plan.safe_inventory) ? plan.safe_inventory : [];
  safe.textContent = inventory.length
    ? `已宣告對手的安全牌庫存：${inventory.map(faceText).join('、')}`
    : '目前沒有可由宣告資訊確認的安全牌庫存。';
  box.append(title, list, safe);
  return box;
}

export function evDetailsEl(entries, {
  chosenTile = null,
  bestTile = null,
  explain = null,
  open = false,
  topGap = null,
  rankingState = null,
} = {}) {
  const details = document.createElement('details');
  details.className = 'evwrap';
  details.open = open;
  const summary = document.createElement('summary');
  summary.textContent = '估計值與抽樣證據';
  const resolvedRankingState = rankingState || topGap?.wording || 'clear';
  details.append(summary, evTableEl(entries, {
    chosenTile, bestTile, rankingState: resolvedRankingState, topGap,
  }));
  const defense = defensePlanEl(entries.find((entry) => entry.is_fold));
  if (defense) details.append(defense);
  if (topGap) {
    const interval = topGap.descriptive_interval95 ?? topGap.ci95 ?? null;
    const uncertainty = document.createElement('div');
    uncertainty.className = 'note';
    const stateText = {
      clear: '差異可解析',
      marginal: '差異很小',
      uncertain: '描述區間跨過 0，排名無法解析',
    }[resolvedRankingState] || '排名狀態未提供';
    uncertainty.textContent = `前兩選項 paired 差 ${signed(topGap.mean)}`
      + (interval ? `，描述區間 [${signed(interval[0])}, ${signed(interval[1])}]` : '')
      + `；${stateText}；樣本 ${topGap.n ?? '—'}。`;
    details.append(uncertainty);
    if (topGap.interval_note) {
      const caveat = document.createElement('div');
      caveat.className = 'note';
      caveat.textContent = topGap.interval_note;
      details.append(caveat);
    }
  }
  if (explain) {
    const pre = document.createElement('div');
    pre.className = 'explain';
    pre.textContent = explain;
    details.append(pre);
  }
  return details;
}

export function rankingBannerEl(grade) {
  const state = grade?.ranking_state || 'clear';
  if (state === 'clear') return null;
  const gap = grade.top1_vs_top2;
  const banner = document.createElement('div');
  banner.className = `ranking-banner ranking-banner--${state}`;
  const title = document.createElement('b');
  const first = gap && !gap.top_is_fold ? faceText(gap.top_discard) : '選項一';
  const second = gap && !gap.runner_up_is_fold ? faceText(gap.runner_up_discard) : '選項二';
  title.textContent = state === 'uncertain'
    ? `≈ 模型無法區分：${first}與${second}`
    : `≈ 差異很小：${first}與${second}`;
  const body = document.createElement('p');
  if (gap) {
    const interval = gap.descriptive_interval95 ?? gap.ci95 ?? null;
    body.textContent = `paired net EV 差 ${signed(gap.mean)}`
      + (interval ? `，描述區間 [${signed(interval[0])}, ${signed(interval[1])}]` : '')
      + (state === 'uncertain'
        ? '；區間跨過 0，目前模擬預算下視為同等可選。'
        : '；點估計有順序，但差異低於效果門檻。');
  } else {
    body.textContent = '引擎回報排名不可解析；目前模擬預算下不建立領先排序。';
  }
  banner.append(title, body);
  return banner;
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
  el.textContent = `模型範圍：${scheme}；所有選項只以 terminal-rollout net EV 比較；`
    + `P(自摸)、P(流局)與和牌值僅供解讀；${calibration}，不代表真人牌局。`;
  return el;
}

function qualityRow(label, count, className, unavailable = false) {
  const row = document.createElement('div');
  row.className = `quality-row${unavailable ? ' quality-row--unavailable' : ''}`;
  const swatch = document.createElement('span');
  swatch.className = `quality-swatch ${className}`;
  const name = document.createElement('b');
  name.textContent = label;
  const value = document.createElement('span');
  value.className = 'quality-count';
  value.textContent = unavailable ? '—' : String(count);
  row.append(swatch, name, value);
  return row;
}

function qualitySummaryEl(session, metadata, {
  primaryLabel = 'Hands',
  primaryValue = session.hands,
  showHandLoss = true,
} = {}) {
  const section = document.createElement('div');
  section.className = 'quality-summary';
  const headline = document.createElement('div');
  headline.className = 'quality-headline';
  const score = document.createElement('div');
  score.className = 'quality-score-card';
  const value = document.createElement('strong');
  value.textContent = session.qualityScore === null ? '—' : `${session.qualityScore}%`;
  const label = document.createElement('span');
  label.textContent = 'Quality score · 可解析決策';
  score.append(value, label);
  const minis = document.createElement('div');
  minis.className = 'quality-minis';
  [[primaryLabel, primaryValue], ['Moves', session.decisions]].forEach(([name, amount]) => {
    const card = document.createElement('div');
    const strong = document.createElement('strong');
    strong.textContent = String(amount);
    const small = document.createElement('span');
    small.textContent = name;
    card.append(strong, small);
    minis.append(card);
  });
  headline.append(score, minis);
  section.append(headline);

  const bar = document.createElement('div');
  bar.className = 'quality-bar';
  bar.setAttribute('role', 'img');
  bar.setAttribute('aria-label', '決策品質比例');
  [
    ['q-best', session.counts.best],
    ['q-correct', session.counts.good],
    ['q-inaccuracy', session.counts.inaccuracy],
    ['q-wrong', session.counts.mistake],
    ['q-unresolved', session.unresolved],
  ].forEach(([className, count]) => {
    if (!count) return;
    const segment = document.createElement('i');
    segment.className = className;
    segment.style.flex = String(count);
    bar.append(segment);
  });
  section.append(bar);
  section.append(
    qualityRow('Model leader', session.counts.best, 'q-best'),
    qualityRow('Correct move', session.counts.good, 'q-correct'),
    qualityRow('Inaccuracy', session.counts.inaccuracy, 'q-inaccuracy'),
    qualityRow('Wrong move', session.counts.mistake, 'q-wrong'),
    qualityRow('Unresolved ranking', session.unresolved, 'q-unresolved'),
    qualityRow('Blunder', 0, 'q-blunder', true),
  );
  const note = document.createElement('p');
  note.className = 'quality-note';
  note.textContent = `${session.unresolved} 次 unresolved 不進 Quality score 分母；Blunder 分級未由引擎提供。`;
  if (session.legacy) note.textContent += ` ${session.legacy} 筆舊紀錄缺少完整分類。`;
  section.append(note);

  if (showHandLoss) {
    const loss = document.createElement('div');
    loss.className = 'loss-card';
    const lossValue = document.createElement('strong');
    lossValue.textContent = session.avgLossPerHand === null ? '—' : fixed(session.avgLossPerHand);
    const lossText = document.createElement('span');
    lossText.textContent = session.hands
      ? `Avg net EV loss / completed hand · ${metadata?.scheme?.id || '目前方案'}`
      : '完成 trainer 一局後顯示 Avg net EV loss / hand';
    loss.append(lossValue, lossText);
    section.append(loss);
  }
  return section;
}

function currentEvidenceEl(grade) {
  if (!grade?.chosen) return null;
  const unresolvedTopPair = (grade.ranking_state || 'clear') !== 'clear'
    && topPairContains(grade, grade.chosen.discard);
  const evidence = document.createElement('div');
  evidence.className = 'current-evidence';
  [
    ['選擇估計 net EV', fixed(grade.chosen.net_ev)],
    ['與點估計領先值差', fixed(grade.ev_delta)],
    ['原始 EV loss', fixed(grade.ev_loss)],
    ['顯示名次', unresolvedTopPair ? '≈ 無法排序' : (grade.rank_position ? `#${grade.rank_position}` : '—')],
    ['精算模擬', String(grade.refined_sims ?? '—')],
  ].forEach(([name, value]) => {
    const item = document.createElement('div');
    const label = document.createElement('span');
    label.textContent = name;
    const strong = document.createElement('b');
    strong.textContent = value;
    item.append(label, strong);
    evidence.append(item);
  });
  return evidence;
}

function optionBand(gap) {
  if (gap <= 0) return ['q-best', '模型領先'];
  if (gap <= .3) return ['q-correct', '正確'];
  if (gap <= 1) return ['q-inaccuracy', '小失誤'];
  return ['q-wrong', '失誤'];
}

function optionGridEl(grade, chosenTile) {
  const section = document.createElement('div');
  section.className = 'option-surface';
  const grid = document.createElement('div');
  grid.className = 'option-grid';
  const detail = document.createElement('div');
  detail.className = 'option-detail';
  detail.setAttribute('aria-live', 'polite');
  const entries = (grade.ranked || []).filter((entry) => !entry.is_fold);
  const pointLeader = entries.length ? entries[0].net_ev : 0;
  const state = grade.ranking_state || 'clear';
  const topGap = grade.top1_vs_top2;

  function showDetail(entry, button) {
    grid.querySelectorAll('.option-cell').forEach((cellEl) => cellEl.classList.toggle('selected', cellEl === button));
    detail.replaceChildren();
    const lines = [
      ['選項', faceText(entry.discard)],
      ['估計 net EV', fixed(entry.net_ev)],
      ['與點估計領先值差', fixed(pointLeader - entry.net_ev)],
      ['P(自摸) / P(流局)', `${fixed(entry.p_win, 3)} / ${fixed(entry.p_draw, 3)}`],
      ['樣本', String(entry.sample_count ?? '—')],
    ];
    lines.forEach(([name, value]) => {
      const line = document.createElement('div');
      const label = document.createElement('span');
      label.textContent = name;
      const strong = document.createElement('b');
      strong.textContent = value;
      line.append(label, strong);
      detail.append(line);
    });
  }

  entries.forEach((entry, index) => {
    const gap = pointLeader - entry.net_ev;
    const unresolved = state !== 'clear' && topGap
      && (entry.discard === topGap.top_discard || entry.discard === topGap.runner_up_discard);
    const [bandClass, bandLabel] = unresolved
      ? ['q-unresolved', state === 'uncertain' ? '無法區分' : '差異很小']
      : optionBand(gap);
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `option-cell ${bandClass}${unresolved ? ' indistinguishable' : ''}`;
    if (entry.discard === chosenTile) button.classList.add('chosen');
    const rank = document.createElement('span');
    rank.className = 'option-rank';
    rank.textContent = unresolved ? '≈' : `#${index + 1}`;
    const tile = document.createElement('span');
    tile.className = 'option-tile';
    tile.append(tileEl(entry.discard, { size: 'sm' }));
    const ev = document.createElement('strong');
    ev.textContent = fixed(entry.net_ev);
    const label = document.createElement('span');
    label.className = 'option-band';
    label.textContent = bandLabel;
    button.append(rank, tile, ev, label);
    button.addEventListener('click', () => showDetail(entry, button));
    grid.append(button);
    if (index === 0) showDetail(entry, button);
  });
  section.append(grid, detail);
  return section;
}

export function reviewRailEl({
  grade = null,
  session,
  chosenTile = null,
  choiceText = null,
  metadata = null,
  primaryLabel = 'Hands',
  primaryValue = session.hands,
  showHandLoss = true,
} = {}) {
  const rail = document.createElement('aside');
  rail.className = 'review-rail';
  rail.setAttribute('aria-label', '決策回饋');
  const header = document.createElement('div');
  header.className = 'review-head';
  const heading = document.createElement('h2');
  heading.textContent = 'Session review';
  const tabs = document.createElement('div');
  tabs.className = 'review-tabs';
  tabs.setAttribute('role', 'tablist');
  const summaryTab = document.createElement('button');
  summaryTab.type = 'button';
  summaryTab.className = 'review-tab active';
  summaryTab.textContent = '摘要';
  summaryTab.setAttribute('role', 'tab');
  summaryTab.setAttribute('aria-selected', 'true');
  const optionsTab = document.createElement('button');
  optionsTab.type = 'button';
  optionsTab.className = 'review-tab';
  optionsTab.textContent = '選項格';
  optionsTab.setAttribute('role', 'tab');
  optionsTab.setAttribute('aria-selected', 'false');
  const hasOptions = Boolean(grade?.ranked?.length);
  optionsTab.disabled = !hasOptions;
  tabs.append(summaryTab, optionsTab);
  header.append(heading, tabs);
  rail.append(header);

  if (grade) {
    const effectiveChosen = chosenTile ?? grade.chosen?.discard ?? null;
    const chosenInTopPair = effectiveChosen !== null && topPairContains(grade, effectiveChosen);
    const current = document.createElement('div');
    current.className = 'current-decision';
    current.append(verdictEl(
      grade.verdict,
      grade.marginal,
      grade.ev_delta,
      choiceText || (effectiveChosen === null ? '本次選擇' : `你打 ${faceText(effectiveChosen)}`),
      { rankingState: grade.ranking_state || 'clear', chosenInTopPair },
    ));
    if ((grade.ranking_state || 'clear') === 'clear' && grade.best?.discard !== undefined) {
      current.append(bestLineEl(`模型領先選項：${faceText(grade.best.discard)}（估計 net EV ${fixed(grade.best.net_ev)}）`));
    }
    rail.append(current);
    const banner = rankingBannerEl(grade);
    if (banner) rail.append(banner);
  }

  const panels = document.createElement('div');
  panels.className = 'review-panels';
  const summaryPanel = document.createElement('section');
  summaryPanel.className = 'review-panel active';
  const currentEvidence = currentEvidenceEl(grade);
  if (currentEvidence) summaryPanel.append(currentEvidence);
  summaryPanel.append(qualitySummaryEl(session, metadata, {
    primaryLabel, primaryValue, showHandLoss,
  }), modelScopeEl(metadata));
  const optionsPanel = document.createElement('section');
  optionsPanel.className = 'review-panel';
  if (hasOptions) {
    optionsPanel.append(optionGridEl(grade, chosenTile));
    const entries = grade.defense_policy
      ? [...grade.ranked, grade.defense_policy]
      : grade.ranked;
    optionsPanel.append(evDetailsEl(entries, {
      chosenTile,
      bestTile: (grade.ranking_state || 'clear') === 'clear' ? grade.best?.discard : null,
      explain: grade.explain,
      topGap: grade.top1_vs_top2,
      rankingState: grade.ranking_state || 'clear',
    }));
  } else {
    const empty = document.createElement('p');
    empty.className = 'review-empty';
    empty.textContent = '完成打牌評分後顯示 net EV 選項格。';
    optionsPanel.append(empty);
  }
  panels.append(summaryPanel, optionsPanel);
  rail.append(panels);

  function select(panel) {
    const showOptions = panel === 'options' && hasOptions;
    summaryPanel.classList.toggle('active', !showOptions);
    optionsPanel.classList.toggle('active', showOptions);
    summaryTab.classList.toggle('active', !showOptions);
    optionsTab.classList.toggle('active', showOptions);
    summaryTab.setAttribute('aria-selected', String(!showOptions));
    optionsTab.setAttribute('aria-selected', String(showOptions));
  }
  summaryTab.addEventListener('click', () => select('summary'));
  optionsTab.addEventListener('click', () => select('options'));
  return rail;
}

export function scorebarEl(score) {
  const el = document.createElement('div');
  el.className = 'scorebar';
  el.innerHTML = `<span>本局已評決策 <b>${score.decisions || 0}</b></span>`
    + `<span>伺服器累計 net EV loss <b>${(score.loss || 0).toFixed(2)}</b></span>`;
  return el;
}
