// 單手 (quiz) and 殘局 (endgame): one seeded position and one graded discard.

import { post, showError, randomSeed } from './api.js';
import { feltEl, computingEl, faceText } from './table.js';
import { reviewRailEl } from './feedback.js';
import { record, summary } from './stats.js';
import { schemeToggle, schemeParams } from './scheme.js';

const TAG_LABELS = { attack: '進攻題（推）', defense: '防守題（守）' };

export function drillScreen(root, { apiBase, mode, title }) {
  let seed = null;
  let position = null;
  let tag = null;
  let phase = 'idle'; // idle | generating | awaiting | grading | feedback
  let gradeResult = null;
  let chosenTile = null;
  let metadata = null;

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
      const body = await post(`${apiBase}/new`, { seed: requestedSeed, ...schemeParams() });
      position = body.position;
      metadata = body;
      seed = position.seed;
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
      metadata = body;
      record(mode, gradeResult, body.scheme.id);
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

  function hint(text) {
    const el = document.createElement('div');
    el.className = 'hand-hint';
    el.textContent = text;
    return el;
  }

  function workspace(board, grade = null) {
    const shell = document.createElement('div');
    shell.className = 'table-workspace';
    const session = summary(mode, metadata?.scheme?.id);
    shell.append(board, reviewRailEl({
      grade,
      session,
      chosenTile,
      metadata,
      primaryLabel: 'Questions',
      primaryValue: session.decisions,
      showHandLoss: false,
    }));
    return shell;
  }

  function render() {
    root.replaceChildren(header());

    if (phase === 'generating' || phase === 'idle') {
      root.append(computingEl('出題中…（在種子牌局中搜尋合格局面）'));
      return;
    }

    root.append(schemeToggle(() => generate(seed)));
    const board = document.createElement('section');
    board.className = 'table-board';

    if (phase === 'awaiting') {
      board.append(feltEl(position, {
        handOptions: { onDiscard: gradeTile },
      }));
      board.append(
        hint('點一張牌切出（再點一次確認；金框為剛摸入）'),
        controls(),
      );
      root.append(workspace(board));
      return;
    }

    if (phase === 'grading') {
      board.append(feltEl(position, {
        handOptions: { marks: { cut: chosenTile } },
      }));
      board.append(computingEl(`你打 ${faceText(chosenTile)}，計算 net EV 中…`));
      root.append(workspace(board));
      return;
    }

    if (phase === 'feedback' && gradeResult) {
      const state = gradeResult.ranking_state || 'clear';
      const topGap = gradeResult.top1_vs_top2;
      const indistinguishable = state === 'clear' || !topGap
        ? []
        : [topGap.top_discard, topGap.runner_up_discard];
      board.append(feltEl(position, {
        handOptions: {
          marks: {
            cut: chosenTile,
            modelLeader: state === 'clear' ? gradeResult.best.discard : null,
            indistinguishable,
          },
        },
      }));
      board.append(controls());
      root.append(workspace(board, gradeResult));
    }
  }

  generate(randomSeed());
}
