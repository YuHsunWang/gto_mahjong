// Two choices from one unchanged public snapshot; stats count individual taps.

import { post, showError, randomSeed } from './api.js';
import { feltEl, computingEl, faceText } from './table.js';
import { record, summary } from './stats.js';

const MODE = 'attack-defense';
const STATS_SCHEME = 'drill'; // No payout-dependent grading in this mode.
const WINDS = ['東', '南', '西', '北'];

function textEl(tag, text, className = '') {
  const el = document.createElement(tag);
  el.className = className;
  el.textContent = text;
  return el;
}

export function attackDefenseScreen(root) {
  let seeds = null;
  let position = null;
  let attackTile = null;
  let result = null;
  let phase = 'idle';
  let requestId = 0;
  // Any hash change replaces this screen instance, so its pending responses must be dropped
  // even if the user comes back to #/attack-defense before they resolve.
  window.addEventListener('hashchange', () => { requestId += 1; }, { once: true });

  function active(id) {
    return id === requestId;
  }

  async function generate(requested = { game_seed: randomSeed(), selection_seed: randomSeed() }) {
    const id = ++requestId;
    phase = 'generating';
    position = null;
    attackTile = null;
    result = null;
    render();
    try {
      const body = await post('/api/attack-defense/new', requested);
      if (!active(id)) return;
      seeds = { game_seed: body.game_seed, selection_seed: body.selection_seed };
      position = body.position;
      phase = 'attack';
    } catch (error) {
      if (!active(id)) return;
      showError(error);
      phase = 'idle';
    }
    render();
  }

  async function pick(tile) {
    if (phase === 'attack') {
      attackTile = tile;
      phase = 'defense';
      render();
      return;
    }
    if (phase !== 'defense') return;
    const id = ++requestId;
    phase = 'grading';
    render();
    try {
      const body = await post('/api/attack-defense/grade', {
        ...seeds, attack_tile: attackTile, defense_tile: tile,
      });
      if (!active(id)) return;
      result = body.grade;
      for (const tap of [result.attack, result.defense]) {
        record(MODE, { verdict: tap.correct ? 'best' : 'mistake' }, STATS_SCHEME);
      }
      phase = 'feedback';
    } catch (error) {
      if (!active(id)) return;
      showError(error);
      phase = 'defense';
    }
    render();
  }

  function controls() {
    const row = textEl('div', '', 'controls');
    const next = textEl('button', phase === 'feedback' ? '下一題 ▶' : '換一題', 'btn primary');
    next.addEventListener('click', () => generate());
    row.append(next);
    if (phase === 'defense') {
      const reset = textEl('button', '重選攻擊牌', 'btn');
      reset.addEventListener('click', () => { attackTile = null; phase = 'attack'; render(); });
      row.append(reset);
    }
    if (phase === 'feedback') {
      const retry = textEl('button', '重出這題', 'btn');
      retry.addEventListener('click', () => generate(seeds));
      row.append(retry);
    }
    return row;
  }

  function feedback() {
    const rail = textEl('aside', '', 'review-rail attack-defense-feedback');
    rail.setAttribute('aria-live', 'polite');
    const stats = summary(MODE, STATS_SCHEME);
    rail.append(textEl('h2', result ? '作答結果' : '攻守各選一張'));
    rail.append(textEl('p', `已答 ${stats.decisions} 次選牌 · 正確率 ${stats.qualityScore ?? '—'}%`));
    if (!result) {
      rail.append(textEl('p', '先選攻擊牌，再選防守牌；兩次都從原手牌選，可以選同一張。'));
      rail.append(textEl('p', '攻擊：先比向聽數，再比進張數。防守：選本手風險最低的牌；同分都算對。'));
      return rail;
    }
    for (const [key, label] of [['attack', '攻擊牌'], ['defense', '防守牌']]) {
      const tap = result[key];
      const line = `${tap.correct ? '✓' : '✗'} ${label}：${faceText(tap.tile)}`;
      rail.append(textEl('p', line + (tap.correct ? '' : `；正確牌：${tap.correct_tiles.map(faceText).join('、')}`)));
    }
    rail.append(
      textEl('p', `攻擊進張數：你選的 ${result.attack.ukeire} 張／最佳攻擊牌 ${result.attack.best_ukeire} 張`),
      textEl('p', `防守牌風險：${result.defense.risk_level}；攻擊牌風險：${result.attack.risk_level}`),
      textEl('p', '安全／普通／危險是本手可打牌的相對排名，同分同級；並非放槍機率。'),
    );
    if (result.shared_tiles.length) {
      rail.append(textEl('p', `這張攻守都對：${result.shared_tiles.map(faceText).join('、')}`));
    }
    rail.append(
      textEl('h3', result.recommendation.verdict),
      textEl('p', `這個局面建議打：${faceText(result.recommendation.tile)}`),
      textEl('p', '出牌建議依四家全攻的牌局研究；風險模型來自內建機器人，未經真人牌局校準。'),
    );
    return rail;
  }

  function render() {
    const header = textEl('div', '', 'topbar');
    const back = textEl('a', '‹ 首頁', 'back');
    back.href = '#/';
    header.append(back, textEl('h1', '攻守練習'));
    root.replaceChildren(header);
    if (!position) {
      if (phase === 'generating') root.append(computingEl('出題中…'));
      else root.append(controls());
      return;
    }
    const board = textEl('section', '', 'table-board');
    const choosing = phase === 'attack' || phase === 'defense';
    const felt = feltEl(position, {
      handOptions: { onDiscard: choosing ? pick : null },
    });
    // This drill always uses one click per choice, independent of discard
    // confirmation settings. Capture before the shared hand's discard handler.
    if (choosing) {
      felt.addEventListener('click', (event) => {
        const tile = event.target.closest('.handrow button.tile');
        if (!tile) return;
        event.stopImmediatePropagation();
        pick(Number(tile.dataset.tile));
      }, true);
    }
    // The shared table accepts four-tile meld details. Add explicit kong labels
    // here without changing the renderer used by the other modes.
    for (const opponent of position.opponents) {
      const groups = felt.querySelectorAll(`[data-seat="${opponent.seat}"] .seat-meld`);
      opponent.meld_details.forEach((detail, index) => {
        if (detail.kind === 'kong') groups[index].append(textEl('small', detail.concealed ? '暗槓' : '明槓'));
      });
    }
    felt.querySelectorAll('.hand-kong').forEach((group, index) => {
      group.append(textEl('small', position.own_kong_details[index].concealed ? '暗槓' : '明槓'));
    });
    // Preserve the existing colored river marks and name them accessibly.
    felt.querySelectorAll('.river .tile').forEach((tile) => {
      const origin = tile.classList.contains('tsumogiri') ? '摸切' : '手切';
      tile.setAttribute('aria-label', `${tile.getAttribute('aria-label')}，${origin}`);
      tile.title += ` ${origin}`;
    });
    board.append(felt);
    const prompt = phase === 'attack' ? '① 點一張攻擊牌'
      : phase === 'defense' ? `攻擊牌已選 ${faceText(attackTile)}；② 點一張防守牌`
        : phase === 'grading' ? '評分中…' : '攻擊、防守已分別評分';
    const hint = textEl('p', prompt, 'hand-hint');
    hint.setAttribute('role', 'status');
    board.append(hint, textEl('p', `你坐${WINDS[position.seat]}家 · 莊家${WINDS[position.dealer_seat]}家 · 金框為摸入牌 · 紅線摸切／藍線手切`, 'hand-hint'));
    board.append(controls());
    const workspace = textEl('div', '', 'table-workspace');
    workspace.append(board, feedback());
    root.append(workspace);
  }

  generate();
}
