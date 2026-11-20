// 整場 (trainer): play a full hand with per-decision EV feedback and a
// persistent scorecard. Sessions live server-side; the session id is kept in
// sessionStorage so a page reload resumes the same hand.

import { post, get, showError, randomSeed } from './api.js';
import { tileEl, tileBackEl } from './tiles.js';
import { feltEl, handEl, computingEl, faceText } from './table.js';
import { reviewRailEl, tileScores, gradeVerdictEl, VERDICT_LABELS } from './feedback.js';
import { record, recordOutcome, summary, handSummary } from './stats.js';
import { schemeToggle, schemeParams } from './scheme.js';

const SESSION_KEY = 'mj-trainer-sid';
const HISTORY_KEY = 'mj-trainer-history';
const SEAT_LABELS = { 0: '莊家（你自己做莊）', 1: '莊的下家', 2: '莊的對家', 3: '莊的上家' };

function callLabel(option) {
  return (option.kind === 'pon' ? '碰' : '吃');
}

function kongLabel(option) {
  return (option.kind === 'concealed' ? '暗槓 ' : '加槓 ') + faceText(option.tile);
}

function choiceTextFor(decision, feedback) {
  if (feedback.kind === 'discard') return `你打 ${faceText(feedback.chosen_tile)}`;
  const isCall = feedback.kind === 'call';
  if (feedback.choice === null) return `你選擇：${isCall ? '過（不鳴）' : '不槓'}`;
  const option = decision.options[feedback.choice];
  return `你選擇：${isCall ? `${callLabel(option)} ${option.meld.map(faceText).join('')}` : kongLabel(option)}`;
}

// The serif character standing in for a move that discarded no tile.
function tokenFor(decision, feedback) {
  if (feedback.choice === null) return '過';
  return feedback.kind === 'call' ? callLabel(decision.options[feedback.choice]) : '槓';
}

// Same branch order as the server's TrainerOutcome.headline, shortened.
function outcomeTitle(decision) {
  if (decision.outcome === 'draw') return '流局';
  if (decision.human_won) return decision.outcome === 'tsumo' ? '自摸' : '胡牌';
  if (decision.human_dealt_in) return decision.robbed_kong ? '被搶槓' : '放槍';
  return decision.outcome === 'tsumo' ? '對手自摸' : '別家胡牌';
}

export function trainerScreen(root) {
  let state = null; // last server session payload
  let phase = 'boot'; // boot | setup | awaiting | acting | feedback | review
  let frozen = null; // decision being shown during acting/feedback/review
  let feedback = null;
  let history = []; // this hand's graded decisions: { decision, feedback }
  let reviewIndex = null;

  // Kept beside the session id so a reload on the result screen keeps the review.
  function saveHistory() {
    try {
      sessionStorage.setItem(HISTORY_KEY, JSON.stringify({ id: state.session_id, items: history }));
    } catch {
      // The review is a convenience; a full or blocked store must not stop play.
    }
  }

  function loadHistory(sessionId) {
    try {
      const saved = JSON.parse(sessionStorage.getItem(HISTORY_KEY));
      return saved?.id === sessionId ? saved.items : [];
    } catch {
      return [];
    }
  }

  function header() {
    const bar = document.createElement('div');
    bar.className = 'topbar';
    const back = document.createElement('a');
    back.className = 'back';
    back.href = '#/';
    back.textContent = '‹ 大廳';
    const heading = document.createElement('h1');
    heading.textContent = '整場實戰';
    bar.append(back, heading);
    if (phase === 'setup') {
      bar.append(schemeToggle(() => {}));
      return bar;
    }
    const tag = document.createElement('span');
    tag.className = 'mode-tag';
    tag.textContent = state ? `種子 ${state.seed} · ${SEAT_LABELS[state.human_seat]}` : '';
    bar.append(tag);
    return bar;
  }

  async function start(seed, humanSeat, dealerStreak) {
    phase = 'boot';
    render();
    try {
      state = await post('/api/trainer/new', {
        seed, human_seat: humanSeat, dealer_streak: dealerStreak, ...schemeParams(),
      });
      sessionStorage.setItem(SESSION_KEY, state.session_id);
      history = [];
      saveHistory();
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
      history = loadHistory(state.session_id);
      if (state.decision.type === 'outcome') {
        recordOutcome('trainer', state.session_id, state.scheme.id);
      }
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
      state = await post(`/api/trainer/${state.session_id}/act`, {
        step: state.step, ...move, ...schemeParams(state.scheme.id),
      });
      feedback = state.feedback;
      record('trainer', feedback, state.scheme.id);
      history.push({ decision: frozen, feedback });
      saveHistory();
      if (state.decision.type === 'outcome') {
        recordOutcome('trainer', state.session_id, state.scheme.id);
      }
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

  function review(index) {
    ({ decision: frozen, feedback } = history[index]);
    reviewIndex = index;
    phase = 'review';
    render();
    window.scrollTo(0, 0);
  }

  function handReviewEl() {
    if (!history.length) return null; // hand started before this tab kept a record
    const section = document.createElement('section');
    section.className = 'hand-review';
    section.setAttribute('aria-labelledby', 'hand-review-title');
    const title = document.createElement('h2');
    title.id = 'hand-review-title';
    title.textContent = '這一局的牌譜';
    const hand = handSummary(history.map((item) => item.feedback));

    const stat = (name, value) => {
      const strong = document.createElement('strong');
      strong.dataset.stat = name;
      strong.textContent = String(value);
      return strong;
    };
    const summaryLine = document.createElement('p');
    summaryLine.className = 'hand-review-summary';
    summaryLine.append(
      '你做了 ', stat('decisions', hand.decisions), ' 個決定。',
      stat('separable', hand.separable), ' 個排名分得出來，其中 ',
      stat('leading', hand.counts.best + hand.counts.good), ' 個是模型領先或正確，品質 ',
      stat('score', hand.qualityScore === null ? '—' : `${hand.qualityScore}%`), '。整局一共少拿 ',
      stat('loss', hand.loss.toFixed(2)), ' 分。',
    );

    const tally = document.createElement('ul');
    tally.className = 'hand-tally';
    tally.setAttribute('aria-label', '各種評等的次數');
    [
      ['best', VERDICT_LABELS.best, hand.counts.best],
      ['good', VERDICT_LABELS.good, hand.counts.good],
      ['inaccuracy', VERDICT_LABELS.inaccuracy, hand.counts.inaccuracy],
      ['mistake', VERDICT_LABELS.mistake, hand.counts.mistake],
      ['unresolved', '≈ 無法區分', hand.unresolved],
    ].forEach(([key, label, count]) => {
      const item = document.createElement('li');
      item.dataset.verdict = key;
      const number = document.createElement('span');
      number.className = `tally-count ${key}`;
      number.textContent = String(count);
      item.append(number, label);
      tally.append(item);
    });

    const hint = document.createElement('p');
    hint.className = 'quality-note';
    hint.textContent = '照打出的順序排，一排六手。點一手看當時的完整解說。';

    const river = document.createElement('ol');
    river.className = 'hand-river';
    history.forEach(({ decision, feedback: grade }, index) => {
      // The verdict line the player saw decides the pill, so an unresolved
      // top-pair pick shows here exactly as it did live.
      const seen = gradeVerdictEl(grade, '');
      const verdict = seen.classList[1];
      const unresolved = verdict === 'unresolved';
      const label = VERDICT_LABELS[grade.verdict] || grade.verdict;
      const button = document.createElement('button');
      button.type = 'button';
      button.className = `river-move ${verdict}`;
      button.dataset.review = String(index);
      button.setAttribute('aria-label', `第 ${index + 1} 手，${choiceTextFor(decision, grade)}，${
        unresolved ? seen.querySelector('.badge').textContent.replace('≈ ', '') : label}`);
      const number = document.createElement('span');
      number.className = 'river-n';
      number.textContent = String(index + 1);
      let face;
      if (grade.kind === 'discard') {
        face = tileEl(grade.chosen_tile, { size: 'sm' });
        face.dataset.tile = String(grade.chosen_tile);
      } else {
        face = document.createElement('span');
        face.className = 'river-token';
        face.textContent = tokenFor(decision, grade);
      }
      face.setAttribute('aria-hidden', 'true');
      const pill = document.createElement('span');
      pill.textContent = unresolved ? '≈' : label;
      // A four-character label breaks 2 + 2 on the narrowest phones.
      pill.className = `river-pill ${verdict}${pill.textContent.length > 3 ? ' long' : ''}`;
      button.append(number, face, pill);
      button.addEventListener('click', () => review(index));
      const cell = document.createElement('li');
      cell.append(button);
      river.append(cell);
    });
    section.append(title, summaryLine, tally, hint, river);
    return section;
  }

  function workspace(board, grade = null, choiceText = null) {
    const shell = document.createElement('div');
    shell.className = 'table-workspace';
    shell.append(board, reviewRailEl({
      grade,
      session: summary('trainer', state?.scheme?.id),
      chosenTile: grade?.chosen_tile ?? grade?.chosen?.discard ?? null,
      choiceText,
      metadata: state,
    }));
    return shell;
  }

  function setupScreen() {
    const wrap = document.createElement('section');
    wrap.className = 'deal';
    const title = document.createElement('h2');
    title.textContent = '這一局誰做莊？';

    // Seats in play order from you (counter-clockwise): you, 下家, 對家, 上家.
    // When seat d deals, you sit (4 - d) % 4 after the dealer, which is the
    // human_seat value the old select sent (0 莊家, 1 莊的下家, 2 對家, 3 上家).
    let dealer = 0;
    let streak = 0;
    const grid = document.createElement('div');
    grid.className = 'seat-grid';
    grid.setAttribute('role', 'group');
    grid.setAttribute('aria-label', '誰做莊');
    const seats = ['你', '下家', '對家', '上家'].map((name, index) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = `seat-pick seat-pick--${index}`;
      button.dataset.seat = String(index);
      button.setAttribute('aria-label', `${name}做莊`);
      const wind = document.createElement('span');
      wind.className = 'seat-pick-wind';
      const label = document.createElement('span');
      label.textContent = name;
      const chip = document.createElement('span');
      chip.className = 'seat-pick-chip';
      chip.setAttribute('aria-hidden', 'true');
      chip.textContent = '莊';
      button.append(wind, label, chip);
      button.addEventListener('click', () => { dealer = index; paintSeats(); });
      return button;
    });
    function paintSeats() {
      seats.forEach((button, index) => {
        button.setAttribute('aria-pressed', String(index === dealer));
        button.querySelector('.seat-pick-wind').textContent = '東南西北'[(index - dealer + 4) % 4];
      });
    }
    paintSeats();

    const centre = document.createElement('div');
    centre.className = 'seat-centre';
    const seedLabel = document.createElement('label');
    seedLabel.htmlFor = 'tr-seed';
    seedLabel.textContent = '這副牌的編號';
    const seedInput = document.createElement('input');
    seedInput.type = 'number';
    seedInput.id = 'tr-seed';
    seedInput.value = String(randomSeed());
    const shuffle = document.createElement('button');
    shuffle.type = 'button';
    shuffle.className = 'pill-btn';
    shuffle.textContent = '換一副';
    shuffle.addEventListener('click', () => { seedInput.value = String(randomSeed()); });
    centre.append(seedLabel, seedInput, shuffle);
    grid.append(seats[2], seats[3], centre, seats[1], seats[0]);

    const actions = document.createElement('div');
    actions.className = 'deal-actions';
    const stepper = document.createElement('div');
    stepper.className = 'stepper';
    stepper.setAttribute('role', 'group');
    stepper.setAttribute('aria-label', '已經連莊次數');
    const value = document.createElement('output');
    value.id = 'tr-streak';
    value.setAttribute('aria-live', 'polite');
    const less = document.createElement('button');
    const more = document.createElement('button');
    function paintStreak() {
      value.textContent = String(streak);
      less.setAttribute('aria-disabled', String(streak === 0));
      more.setAttribute('aria-disabled', String(streak === 8));
    }
    [[less, '−', '少一次', -1], [more, '+', '多一次', 1]].forEach(([button, text, name, step]) => {
      button.type = 'button';
      button.className = 'step-btn';
      button.textContent = text;
      button.setAttribute('aria-label', name);
      button.addEventListener('click', () => { streak = Math.min(8, Math.max(0, streak + step)); paintStreak(); });
    });
    paintStreak();
    const before = document.createElement('span');
    before.textContent = '已經連莊';
    const after = document.createElement('span');
    after.textContent = '次';
    stepper.append(before, less, value, more, after);

    const startButton = document.createElement('button');
    startButton.className = 'btn primary slab';
    startButton.textContent = '開始新局';
    startButton.addEventListener('click', () => {
      start(Number(seedInput.value) || randomSeed(), (4 - dealer) % 4, streak);
    });
    actions.append(stepper, startButton);

    const note = document.createElement('div');
    note.className = 'note';
    note.textContent = '每手打牌、可鳴牌與可宣告的暗槓／加槓都會即時 EV 回饋並計分。本桌無花牌。';

    const wall = document.createElement('div');
    wall.className = 'deal-wall';
    wall.setAttribute('aria-hidden', 'true');
    for (let i = 0; i < 16; i += 1) wall.append(tileBackEl());

    wrap.append(title, grid, actions, note, wall);
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
        option.meld.forEach((tile) => preview.append(tileEl(tile, { size: 'sm' })));
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
    ['選項', '預期淨得分'].forEach((label) => {
      const th = document.createElement('th');
      th.textContent = label;
      head.append(th);
    });
    table.append(head);
    rows.forEach((row) => {
      const tr = document.createElement('tr');
      if (row.index === feedback.choice) tr.classList.add('chosen-row');
      const indistinguishable = feedback.indistinguishable_indices?.includes(row.index);
      if (indistinguishable) tr.classList.add('indistinguishable-row');
      if (!feedback.ranking_uncertain && row.index === feedback.best_index) tr.classList.add('model-leader-row');
      const name = document.createElement('td');
      name.textContent = `${indistinguishable ? '≈ ' : ''}${row.label}`;
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
    const head = document.createElement('div');
    head.className = 'outcome-head';
    const headline = document.createElement('h2');
    headline.className = 'headline';
    headline.textContent = outcomeTitle(decision);
    const points = decision.point_delta;
    const delta = document.createElement('span');
    delta.className = `delta ${points > 0 ? 'win' : points < 0 ? 'lose' : ''}`;
    delta.textContent = `你這一局 ${points > 0 ? '+' : points < 0 ? '−' : ''}${Math.abs(points)} 分`;
    head.append(headline, delta);

    // Seats named from the player's chair: play order runs 你, 下家, 對家, 上家.
    const seatName = (seat) => ['你', '下家', '對家', '上家'][(seat - state.human_seat + 4) % 4];
    const story = document.createElement('p');
    story.className = 'outcome-line';
    if (decision.winner == null) {
      story.textContent = '這一局沒有人胡牌。';
    } else if (decision.winning_tile == null) {
      story.textContent = `${seatName(decision.winner)}胡牌。`;
    } else if (decision.outcome === 'tsumo') {
      story.textContent = `${seatName(decision.winner)}自摸，胡的是${faceText(decision.winning_tile)}。`;
    } else {
      story.textContent = `${seatName(decision.winner)}胡牌，胡的是${seatName(decision.discarder)}${
        decision.robbed_kong ? '加槓' : '打'}的${faceText(decision.winning_tile)}。`;
    }
    wrap.append(head, story);

    const facts = [];
    if (decision.winner_hand && decision.score) {
      wrap.append(handEl(decision.winner_hand, {
        drawnTile: decision.winning_tile,
        melds: decision.winner_melds,
        meldDetails: decision.winner_meld_details,
        kongDetails: decision.winner_kong_details,
        ownerSeat: decision.winner,
        viewerSeat: state.human_seat,
      }));
      const items = decision.score.items.map((item) => {
        const name = item.name.match(/（([^）]+)）|\(([^)]+)\)/);
        return `${name ? name[1] || name[2] : item.name} ${item.tai} 台`;
      });
      facts.push(`這手牌${items.length ? `有${items.join('、')}，合計` : ''} ${decision.score.total_tai} 台，牌值 ${decision.score.value} 分。`);
    }
    if (decision.dealer_streak_in) facts.push(`這一局是連莊 ${decision.dealer_streak_in}。`);
    if (decision.next_human_seat !== state.human_seat) {
      facts.push(`莊家換人，下一局你是${SEAT_LABELS[decision.next_human_seat]}。`);
    } else if (decision.next_dealer_streak) {
      facts.push(`莊家連莊，下一局連 ${decision.next_dealer_streak} 拉 ${decision.next_dealer_streak}，對莊防守要更緊。`);
    } else {
      facts.push('下一局莊家連莊數歸零。');
    }
    const next = document.createElement('p');
    next.className = 'nexthand';
    next.textContent = facts.join('');
    wrap.append(next);

    const controls = document.createElement('div');
    controls.className = 'controls';
    const again = document.createElement('button');
    again.className = 'btn primary slab';
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
    const board = document.createElement('section');
    board.className = 'table-board';
    const hint = document.createElement('div');
    hint.className = 'hand-hint';
    if (decision.type === 'discard') {
      hint.textContent = '點一張牌切出（再點一次確認；金框為剛摸入）';
      board.append(feltEl(decision.position, {
        handOptions: {
          onDiscard: (tile) => act({ action: 'discard', tile }, `你打 ${faceText(tile)}，計算 net EV 中…`),
        },
      }), hint);
    } else if (decision.type === 'kong') {
      hint.textContent = '剛摸入的牌可形成不惡化向聽的槓 — 要宣告嗎？';
      board.append(feltEl(decision.position), hint, optionButtons(decision));
    } else if (decision.type === 'call') {
      hint.textContent = `對手 ${decision.discarder} 打出 ${faceText(decision.offered_tile)} — 要鳴牌嗎？`;
      board.append(feltEl(decision.position, {
        offeredTile: decision.offered_tile,
        handOptions: { drawnTile: null },
      }), hint, optionButtons(decision));
    }
    return workspace(board);
  }

  function feedbackScreen() {
    const decision = frozen;
    const board = document.createElement('section');
    board.className = 'table-board';
    let choiceText = choiceTextFor(decision, feedback);
    if (phase === 'review') choiceText = `第 ${reviewIndex + 1} 手，${choiceText}`;

    if (feedback.kind === 'discard') {
      const state = feedback.ranking_state || 'clear';
      const topGap = feedback.top1_vs_top2;
      board.append(feltEl(decision.position, {
        handOptions: {
          marks: {
            cut: feedback.chosen_tile,
            modelLeader: state === 'clear' ? feedback.best.discard : null,
            indistinguishable: state === 'clear' || !topGap
              ? []
              : [topGap.top_discard, topGap.runner_up_discard],
            scores: tileScores(feedback, feedback.chosen_tile),
          },
        },
      }));
    } else {
      const isCall = feedback.kind === 'call';
      board.append(feltEl(decision.position, {
        offeredTile: isCall ? decision.offered_tile : null,
        handOptions: { drawnTile: isCall ? null : decision.position.drawn_tile },
      }), optionEvRows(decision));
    }

    const controls = document.createElement('div');
    controls.className = 'controls';
    const next = document.createElement('button');
    next.className = 'btn primary';
    if (phase === 'review') next.textContent = '‹ 回結果';
    else next.textContent = state.decision.type === 'outcome' ? '看結果 ▶' : '下一手 ▶';
    next.addEventListener('click', advance);
    controls.append(next);
    board.append(controls);
    return workspace(board, feedback, choiceText);
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
    if (state.migi_declared) {
      const notice = document.createElement('div');
      notice.className = 'note';
      notice.setAttribute('role', 'status');
      notice.textContent = '已自動宣告聽牌（之後自動摸切）';
      root.append(notice);
    }
    if (phase === 'acting') {
      const decision = frozen;
      const board = document.createElement('section');
      board.className = 'table-board';
      board.append(feltEl(decision.position, {
        offeredTile: decision.type === 'call' ? decision.offered_tile : null,
        handOptions: { drawnTile: decision.type === 'call' ? null : decision.position.drawn_tile },
      }), computingEl(computingText || '計算 net EV 中…'));
      root.append(workspace(board));
      return;
    }
    if (phase === 'feedback' || phase === 'review') {
      root.append(feedbackScreen());
      return;
    }
    // awaiting: render the server's current decision (or the outcome)
    if (state.decision.type === 'outcome') {
      root.append(outcomeScreen(state.decision));
      const handReview = handReviewEl();
      if (handReview) root.append(handReview);
      if (reviewIndex !== null) root.querySelector(`[data-review="${reviewIndex}"]`)?.focus();
      reviewIndex = null;
    } else {
      root.append(decisionScreen(state.decision));
    }
  }

  resume();
}
