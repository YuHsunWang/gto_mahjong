// 整場 (trainer): play a full hand with per-decision EV feedback and a
// persistent scorecard. Sessions live server-side; the session id is kept in
// sessionStorage so a page reload resumes the same hand.

import { post, get, showError, randomSeed } from './api.js';
import { feltEl, handEl, computingEl, faceText } from './table.js';
import { verdictEl, evDetailsEl, bestLineEl, scorebarEl } from './feedback.js';
import { record } from './stats.js';

const SESSION_KEY = 'mj-trainer-sid';
const SEAT_LABELS = { 0: '莊家（你自己做莊）', 1: '莊的下家', 2: '莊的對家', 3: '莊的上家' };

function callLabel(option) {
  return (option.kind === 'pon' ? '碰' : '吃');
}

function kongLabel(option) {
  return (option.kind === 'concealed' ? '暗槓 ' : '加槓 ') + faceText(option.tile);
}

export function trainerScreen(root) {
  let state = null; // last server session payload
  let phase = 'boot'; // boot | setup | awaiting | acting | feedback
  let frozen = null; // decision being shown during acting/feedback
  let feedback = null;

  function header() {
    const bar = document.createElement('div');
    bar.className = 'topbar';
    const back = document.createElement('a');
    back.className = 'back';
    back.href = '#/';
    back.textContent = '‹ 首頁';
    const heading = document.createElement('h1');
    heading.textContent = '整場實戰';
    const tag = document.createElement('span');
    tag.className = 'mode-tag';
    tag.textContent = state ? `種子 ${state.seed} · ${SEAT_LABELS[state.human_seat]}` : '';
    bar.append(back, heading, tag);
    return bar;
  }

  async function start(seed, humanSeat, dealerStreak) {
    phase = 'boot';
    render();
    try {
      state = await post('/api/trainer/new', { seed, human_seat: humanSeat, dealer_streak: dealerStreak });
      sessionStorage.setItem(SESSION_KEY, state.session_id);
      frozen = null;
      feedback = null;
      phase = 'awaiting';
    } catch (error) {
      showError(error);
      phase = 'setup';
    }
    render();
  }

  async function resume() {
    const sessionId = sessionStorage.getItem(SESSION_KEY);
    if (!sessionId) {
      phase = 'setup';
      render();
      return;
    }
    try {
      state = await get(`/api/trainer/${sessionId}`);
      phase = 'awaiting';
    } catch {
      sessionStorage.removeItem(SESSION_KEY);
      phase = 'setup';
    }
    render();
  }

  async function act(move, computingText) {
    frozen = state.decision;
    phase = 'acting';
    render(computingText);
    try {
      state = await post(`/api/trainer/${state.session_id}/act`, { step: state.step, ...move });
      feedback = state.feedback;
      record('trainer', feedback.verdict, feedback.ev_loss);
      phase = 'feedback';
    } catch (error) {
      showError(error);
      if (error.status === 409) {
        // stale step (e.g. double-tap or another tab advanced): resync
        await resume();
        return;
      }
      phase = 'awaiting';
      frozen = null;
    }
    render();
  }

  function advance() {
    frozen = null;
    feedback = null;
    phase = 'awaiting';
    render();
  }

  function setupScreen() {
    const wrap = document.createElement('div');
    const seedField = document.createElement('div');
    seedField.className = 'field';
    seedField.innerHTML = '<label for="tr-seed">種子</label>';
    const seedInput = document.createElement('input');
    seedInput.type = 'number';
    seedInput.id = 'tr-seed';
    seedInput.value = String(randomSeed());
    seedField.append(seedInput);

    const row = document.createElement('div');
    row.className = 'field-row';
    const seatField = document.createElement('div');
    seatField.className = 'field';
    seatField.innerHTML = '<label for="tr-seat">你的座位</label>';
    const seatSelect = document.createElement('select');
    seatSelect.id = 'tr-seat';
    Object.entries(SEAT_LABELS).forEach(([value, label]) => {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = label;
      seatSelect.append(option);
    });
    seatField.append(seatSelect);
    const streakField = document.createElement('div');
    streakField.className = 'field';
    streakField.innerHTML = '<label for="tr-streak">初始連莊數</label>';
    const streakInput = document.createElement('input');
    streakInput.type = 'number';
    streakInput.id = 'tr-streak';
    streakInput.min = '0';
    streakInput.max = '8';
    streakInput.value = '0';
    streakField.append(streakInput);
    row.append(seatField, streakField);

    const note = document.createElement('div');
    note.className = 'note';
    note.textContent = '每手切牌、可鳴牌與可宣告的暗槓／加槓都會即時 EV 回饋並計分。本桌無花牌。';

    const controls = document.createElement('div');
    controls.className = 'controls';
    const startButton = document.createElement('button');
    startButton.className = 'btn primary';
    startButton.textContent = '開始新局';
    startButton.addEventListener('click', () => {
      start(Number(seedInput.value) || randomSeed(), Number(seatSelect.value), Number(streakInput.value) || 0);
    });
    controls.append(startButton);

    wrap.append(seedField, row, note, controls);
    return wrap;
  }

  function optionButtons(decision) {
    const bar = document.createElement('div');
    bar.className = 'callbar';
    const isCall = decision.type === 'call';
    decision.options.forEach((option, index) => {
      const button = document.createElement('button');
      button.className = 'call-btn';
      const name = document.createElement('span');
      name.textContent = isCall ? callLabel(option) : kongLabel(option);
      button.append(name);
      if (isCall) {
        const preview = document.createElement('span');
        preview.className = 'preview';
        option.meld.forEach((tile) => {
          const mini = document.createElement('span');
          mini.className = 'tile sm';
          mini.textContent = faceText(tile);
          preview.append(mini);
        });
        button.append(preview);
      }
      button.addEventListener('click', () => act(
        { action: decision.type, option: index },
        isCall ? '計算鳴牌 EV 中…' : '計算槓的 EV 中…',
      ));
      bar.append(button);
    });
    const pass = document.createElement('button');
    pass.className = 'call-btn pass';
    pass.textContent = isCall ? '過（不鳴）' : '不槓';
    pass.addEventListener('click', () => act(
      { action: decision.type, option: null },
      isCall ? '計算鳴牌 EV 中…' : '計算槓的 EV 中…',
    ));
    bar.append(pass);
    return bar;
  }

  function optionEvRows(decision) {
    const isCall = decision.type === 'call';
    const rows = [{ label: isCall ? '過（不鳴）' : '不槓', ev: feedback.pass_ev, index: null }];
    decision.options.forEach((option, index) => {
      rows.push({
        label: isCall ? `${callLabel(option)} ${option.meld.map(faceText).join('')}` : kongLabel(option),
        ev: feedback.option_evs[index],
        index,
      });
    });
    const wrap = document.createElement('div');
    wrap.className = 'evtable-wrap';
    const table = document.createElement('table');
    table.className = 'evtable';
    const head = document.createElement('tr');
    ['選項', 'EV（台）'].forEach((label) => {
      const th = document.createElement('th');
      th.textContent = label;
      head.append(th);
    });
    table.append(head);
    rows.forEach((row) => {
      const tr = document.createElement('tr');
      if (row.index === feedback.choice) tr.classList.add('chosen-row');
      if (row.index === feedback.best_index) tr.classList.add('best-row');
      const name = document.createElement('td');
      name.textContent = row.label;
      const ev = document.createElement('td');
      ev.textContent = row.ev.toFixed(1);
      tr.append(name, ev);
      table.append(tr);
    });
    wrap.append(table);
    return wrap;
  }

  function outcomeScreen(decision) {
    const wrap = document.createElement('div');
    wrap.className = 'outcome';
    const headline = document.createElement('div');
    headline.className = 'headline';
    headline.textContent = decision.headline;
    const delta = document.createElement('div');
    delta.className = `delta ${decision.point_delta > 0 ? 'win' : decision.point_delta < 0 ? 'lose' : ''}`;
    const streakIn = decision.dealer_streak_in ? `（連莊 ${decision.dealer_streak_in}）` : '';
    delta.textContent = `你的收支 ${decision.point_delta > 0 ? '+' : ''}${decision.point_delta} 台單位 · ${decision.turns} 手${streakIn}`;
    wrap.append(headline, delta);

    const next = document.createElement('div');
    next.className = 'nexthand';
    if (decision.next_human_seat !== state.human_seat) {
      next.textContent = `莊家易主，換座位 — 下局你是${SEAT_LABELS[decision.next_human_seat]}`;
    } else if (decision.next_dealer_streak) {
      next.textContent = `莊家連莊 — 下局連 ${decision.next_dealer_streak} 拉 ${decision.next_dealer_streak}，對莊防守要更緊`;
    } else {
      next.textContent = '下局莊家連莊數歸零';
    }
    wrap.append(next);

    const controls = document.createElement('div');
    controls.className = 'controls';
    const again = document.createElement('button');
    again.className = 'btn primary';
    again.textContent = '再來一局';
    again.addEventListener('click', () => start(state.seed + 1, decision.next_human_seat, decision.next_dealer_streak));
    const quit = document.createElement('button');
    quit.className = 'btn';
    quit.textContent = '結束';
    quit.addEventListener('click', () => {
      sessionStorage.removeItem(SESSION_KEY);
      window.location.hash = '#/';
    });
    controls.append(again, quit);
    wrap.append(controls);
    return wrap;
  }

  function decisionScreen(decision) {
    const fragment = document.createDocumentFragment();
    if (decision.type === 'discard') {
      fragment.append(feltEl(decision.position));
      const hint = document.createElement('div');
      hint.className = 'hand-hint';
      hint.textContent = '點一張牌切出（再點一次確認；金框為剛摸入）';
      fragment.append(hint, handEl(decision.position.hand, {
        drawnTile: decision.position.drawn_tile,
        onDiscard: (tile) => act({ action: 'discard', tile }, `你切 ${faceText(tile)}，計算 EV 中…`),
      }));
    } else if (decision.type === 'kong') {
      fragment.append(feltEl(decision.position));
      const hint = document.createElement('div');
      hint.className = 'hand-hint';
      hint.textContent = '剛摸入的牌可形成不惡化向聽的槓 — 要宣告嗎？';
      fragment.append(hint, handEl(decision.position.hand, { drawnTile: decision.position.drawn_tile }));
      fragment.append(optionButtons(decision));
    } else if (decision.type === 'call') {
      fragment.append(feltEl(decision.position, { offeredTile: decision.offered_tile }));
      const hint = document.createElement('div');
      hint.className = 'hand-hint';
      hint.textContent = `對手 ${decision.discarder} 打出 ${faceText(decision.offered_tile)} — 要鳴牌嗎？`;
      fragment.append(hint, handEl(decision.position.hand));
      fragment.append(optionButtons(decision));
    }
    return fragment;
  }

  function feedbackScreen() {
    const fragment = document.createDocumentFragment();
    const decision = frozen;
    fragment.append(feltEl(decision.position, {
      offeredTile: decision.type === 'call' ? decision.offered_tile : null,
    }));

    if (feedback.kind === 'discard') {
      const bestTile = feedback.best.discard;
      const showBest = feedback.ev_delta > 0 && bestTile !== feedback.chosen_tile;
      fragment.append(handEl(decision.position.hand, {
        drawnTile: decision.position.drawn_tile,
        marks: { cut: feedback.chosen_tile, best: showBest ? bestTile : null },
      }));
      fragment.append(verdictEl(feedback.verdict, feedback.marginal, feedback.ev_delta, `你切 ${faceText(feedback.chosen_tile)}`));
      if (showBest) fragment.append(bestLineEl(`最佳切牌：${faceText(bestTile)}（淨 EV ${feedback.best.net_ev.toFixed(1)}，綠框標示）`));
      fragment.append(evDetailsEl(feedback.ranked, {
        chosenTile: feedback.chosen_tile,
        bestTile,
        explain: feedback.explain,
      }));
    } else {
      const isCall = feedback.kind === 'call';
      const chosenLabel = feedback.choice === null
        ? (isCall ? '過（不鳴）' : '不槓')
        : (isCall
          ? `${callLabel(decision.options[feedback.choice])} ${decision.options[feedback.choice].meld.map(faceText).join('')}`
          : kongLabel(decision.options[feedback.choice]));
      fragment.append(handEl(decision.position.hand, {
        drawnTile: isCall ? null : decision.position.drawn_tile,
      }));
      fragment.append(verdictEl(feedback.verdict, feedback.marginal, feedback.ev_delta, `你選擇：${chosenLabel}`));
      const bestLabel = feedback.best_index === null
        ? (isCall ? '過（不鳴）' : '不槓')
        : (isCall
          ? `${callLabel(decision.options[feedback.best_index])} ${decision.options[feedback.best_index].meld.map(faceText).join('')}`
          : kongLabel(decision.options[feedback.best_index]));
      fragment.append(bestLineEl(`最佳：${bestLabel}，EV ${feedback.best_ev.toFixed(1)} 台`));
      fragment.append(optionEvRows(decision));
    }

    const controls = document.createElement('div');
    controls.className = 'controls';
    const next = document.createElement('button');
    next.className = 'btn primary';
    next.textContent = state.decision.type === 'outcome' ? '看結果 ▶' : '下一手 ▶';
    next.addEventListener('click', advance);
    controls.append(next);
    fragment.append(controls);
    return fragment;
  }

  function render(computingText) {
    root.replaceChildren(header());
    if (phase === 'boot') {
      root.append(computingEl('載入中…'));
      return;
    }
    if (phase === 'setup') {
      root.append(setupScreen());
      return;
    }
    root.append(scorebarEl(state.scorecard));
    if (phase === 'acting') {
      const decision = frozen;
      root.append(feltEl(decision.position, {
        offeredTile: decision.type === 'call' ? decision.offered_tile : null,
      }));
      root.append(handEl(decision.position.hand, {
        drawnTile: decision.type === 'call' ? null : decision.position.drawn_tile,
      }));
      root.append(computingEl(computingText || '計算 EV 中…'));
      return;
    }
    if (phase === 'feedback') {
      root.append(feedbackScreen());
      return;
    }
    // awaiting: render the server's current decision (or the outcome)
    if (state.decision.type === 'outcome') {
      root.append(outcomeScreen(state.decision));
    } else {
      root.append(decisionScreen(state.decision));
    }
  }

  resume();
}
