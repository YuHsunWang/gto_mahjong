// 單手 (quiz) and 殘局 (endgame) drills: one seeded position, one graded
// discard, GTO-Wizard feedback. Both modes share this screen; they differ in
// API prefix and the endgame push/fold tag.

import { post, showError, randomSeed } from './api.js';
import { feltEl, handEl, computingEl, faceText } from './table.js';
import { verdictEl, evDetailsEl, bestLineEl, VERDICT_LABELS } from './feedback.js';
import { record } from './stats.js';
import { schemeToggle, schemeParams } from './scheme.js';

const TAG_LABELS = { attack: '進攻題（推）', defense: '防守題（守）' };

export function drillScreen(root, { apiBase, mode, title }) {
  let seed = null;
  let position = null;
  let tag = null;
  let phase = 'idle'; // idle | generating | awaiting | grading | feedback
  let gradeResult = null;
  let chosenTile = null;

  function header() {
    const bar = document.createElement('div');
    bar.className = 'topbar';
    const back = document.createElement('a');
    back.className = 'back';
    back.href = '#/';
    back.textContent = '‹ 首頁';
    const heading = document.createElement('h1');
    heading.textContent = title;
    if (tag) {
      const chip = document.createElement('span');
      chip.className = `tag-chip ${tag}`;
      chip.textContent = TAG_LABELS[tag];
      heading.append(chip);
    }
    const seedTag = document.createElement('span');
    seedTag.className = 'mode-tag';
    seedTag.textContent = seed === null ? '…' : `種子 ${seed}`;
    bar.append(back, heading, seedTag);
    return bar;
  }

  async function generate(requestedSeed) {
    phase = 'generating';
    seed = requestedSeed;
    position = null;
    tag = null;
    gradeResult = null;
    chosenTile = null;
    render();
    try {
      const body = await post(`${apiBase}/new`, { seed: requestedSeed });
      position = body.position;
      seed = position.seed; // the generator may advance past the requested seed
      tag = body.tag || null;
      phase = 'awaiting';
    } catch (error) {
      showError(error);
      phase = 'idle';
    }
    render();
  }

  async function gradeTile(tile) {
    phase = 'grading';
    chosenTile = tile;
    render();
    try {
      const body = await post(`${apiBase}/grade`, { seed, tile, ...schemeParams() });
      gradeResult = body.grade;
      record(mode, gradeResult.verdict, gradeResult.ev_loss);
      phase = 'feedback';
    } catch (error) {
      showError(error);
      phase = 'awaiting';
    }
    render();
  }

  function controls() {
    const row = document.createElement('div');
    row.className = 'controls';
    const next = document.createElement('button');
    next.className = 'btn primary';
    next.textContent = phase === 'feedback' ? '下一題 ▶' : '換一題';
    next.addEventListener('click', () => generate(seed === null ? randomSeed() : seed + 1));
    row.append(next);
    if (phase === 'feedback') {
      const retry = document.createElement('button');
      retry.className = 'btn';
      retry.textContent = '重出這題';
      retry.addEventListener('click', () => generate(seed));
      row.append(retry);
    }
    return row;
  }

  function render() {
    root.replaceChildren(header());

    if (phase === 'generating' || phase === 'idle') {
      root.append(computingEl('出題中…（在種子牌局中搜尋合格局面）'));
      return;
    }

    const inFeedback = phase === 'feedback';
    root.append(feltEl(position));

    // Switching the 底/台 scheme re-grades the same tile, so you see how the
    // verdict/EV move under a different payout convention on the same position.
    root.append(schemeToggle(() => {
      if (phase === 'feedback' && chosenTile !== null) gradeTile(chosenTile);
    }));

    if (phase === 'awaiting') {
      const hint = document.createElement('div');
      hint.className = 'hand-hint';
      hint.textContent = '點一張牌切出（再點一次確認；金框為剛摸入）';
      root.append(hint, handEl(position.hand, { drawnTile: position.drawn_tile, onDiscard: gradeTile, melds: position.own_melds }));
      root.append(controls());
      return;
    }

    if (phase === 'grading') {
      root.append(handEl(position.hand, { drawnTile: position.drawn_tile, marks: { cut: chosenTile }, melds: position.own_melds }));
      root.append(computingEl(`你切 ${faceText(chosenTile)}，計算 EV 中…`));
      return;
    }

    if (inFeedback && gradeResult) {
      const bestTile = gradeResult.best.discard;
      const showBest = gradeResult.ev_delta > 0 && bestTile !== chosenTile;
      root.append(handEl(position.hand, {
        drawnTile: position.drawn_tile,
        marks: { cut: chosenTile, best: showBest ? bestTile : null },
        melds: position.own_melds,
      }));
      root.append(verdictEl(gradeResult.verdict, gradeResult.marginal, gradeResult.ev_delta, `你切 ${faceText(chosenTile)}`));
      if (showBest) {
        root.append(bestLineEl(`最佳切牌：${faceText(bestTile)}（淨 EV ${gradeResult.best.net_ev.toFixed(1)}，綠框標示）`));
      } else {
        root.append(bestLineEl(`判定 ${VERDICT_LABELS[gradeResult.verdict]} — 你的選擇就是（或不遜於）最佳解`));
      }
      root.append(evDetailsEl(gradeResult.ranked, {
        chosenTile,
        bestTile,
        explain: gradeResult.explain,
        open: true,
      }));
      root.append(controls());
    }
  }

  generate(randomSeed());
}
