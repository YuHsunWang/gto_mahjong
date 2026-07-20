// 教學 — curated classic shapes with hand-written explanations, each backed by
// the engine's tile-acceptance (進張) via /api/ukeire. Efficiency lessons are
// deterministic and fast (no Monte Carlo), so the corroboration renders inline.

import { post, showError } from './api.js';
import { tileEl, parseCompact, faceText } from './tiles.js';
import { computingEl } from './table.js';

// recommend / highlight tiles are compact strings (e.g. '9m'); the screen maps
// them to tile indices with parseCompact and highlights the matching row.
const LESSONS = [
  {
    id: 'lone-terminal',
    title: '孤張進聽',
    subtitle: '單張終端牌 vs 聽牌',
    hand: '119m456m123p789p456s78s',
    question: '這手 17 張，先打哪張？',
    answer: '打 九萬 —— 唯一能直接聽牌的切法。',
    kind: 'discard',
    recommend: '9m',
    points: [
      '九萬是一張孤立的終端牌：它左右都沒有能連成順子的鄰牌，留著只是等自己再抽一張九萬湊對，機率低。',
      '把九萬切掉後，一萬對子＋其餘四組搭子剛好成聽；切任何中張都會拆掉現成的面子，退回一向聽。',
      '基本原則：當某張牌對向聽數毫無貢獻、切了又能進聽時，先走它。下面的引擎表可以看到只有打九萬向聽變 0。',
    ],
  },
  {
    id: 'widest-wait',
    title: '同聽選寬待',
    subtitle: '都能聽，聽面愈寬愈好',
    hand: '234m678m345p678p234s5s9s',
    question: '這手已可聽牌，打哪張聽得最寬？',
    answer: '打 九條 —— 聽面最寬（6 張），比打五條／二條（各 3 張）多一倍。',
    kind: 'discard',
    recommend: '9s',
    points: [
      '手上五條、九條都是浮牌，切哪張都能聽，差別只在「聽哪些牌、有幾張」。',
      '留下五條當單騎、切掉九條，聽的張數最多；反過來留九條就窄。同樣是聽牌，寬的聽面胡牌機率明顯較高。',
      '基本原則：聽牌時不要只看「有沒有聽」，要比「聽面寬窄」。引擎表的進張數就是還沒被看到的可胡張數。',
    ],
  },
  {
    id: 'rush-vs-wide',
    title: '別為窄聽拆寬型',
    subtitle: '急聽 vs 保留寬一向聽',
    hand: '147m456m789m234p567p99p',
    question: '一四七萬這種三面浮張，該搶聽還是留寬？',
    answer: '通常留寬 —— 打四萬（或九筒）保住 30 張的一向聽，勝過打一萬搶只有 4 張的窄聽。',
    kind: 'discard',
    recommend: '4m',
    points: [
      '打一萬確實能馬上聽牌，但只聽 4 張（四萬／九筒），胡牌機率很低。',
      '打四萬或九筒仍是一向聽，卻保有 30 張進張——多數情況下這種「寬一向聽」的期望胡牌率高於「窄聽」。',
      '例外：牌局尾聲、或對手明顯已聽時，搶一個能胡的窄聽有時才對。這題教的是「不要反射性搶聽」，先看聽面寬窄與剩餘巡數。',
    ],
  },
  {
    id: 'pon-vs-concealed',
    title: '吃碰的門清取捨',
    subtitle: '4555678 條，別人打五條要碰嗎？',
    hand: '4555678s123m789m22p1z',
    question: '對手打出五條，用手上兩張五條碰成刻子嗎？',
    answer: '通常不碰 —— 碰只多 3 張進張，卻失去門清（少一台）與自摸機會。',
    kind: 'compare',
    options: [
      { label: '不碰（留門清）', hand: '4555678s123m789m22p1z', melds_declared: 0 },
      { label: '碰五條後棄一張', hand: '4678s123m789m22p1z', melds_declared: 1 },
    ],
    points: [
      '碰掉五條會把 555 固定成刻子，剩下的四六七八條仍能組順子，進張從 24 張小升到 27 張——純速度只差一點點。',
      '但碰牌會攤開手牌：失去「門清」一台，也失去自摸的額外台，之後被迫棄牌還多一分放槍風險。',
      '基本原則：鳴牌前先問「這一鳴換到多少速度／台數？值不值得丟掉門清？」這裡速度只多 3 張，通常不划算——除非你本來就沒有門清、或急需搶速。',
    ],
  },
];

function lessonCard(lesson, onOpen) {
  const card = document.createElement('button');
  card.type = 'button';
  card.className = 'lesson-card';
  card.innerHTML = `<div class="card-head"><span class="card-name">${lesson.title}</span></div>`
    + `<div class="card-desc">${lesson.subtitle}</div>`;
  card.addEventListener('click', () => onOpen(lesson));
  return card;
}

function tileRow(hand) {
  const row = document.createElement('div');
  row.className = 'lesson-tiles';
  parseCompact(hand).forEach((tile) => row.append(tileEl(tile, { size: 'lg' })));
  return row;
}

function discardTable(discards, recommendTile) {
  const wrap = document.createElement('div');
  wrap.className = 'evtable-wrap';
  const table = document.createElement('table');
  table.className = 'evtable';
  const head = document.createElement('tr');
  ['切牌', '向聽', '進張', '接受牌'].forEach((label) => {
    const th = document.createElement('th');
    th.textContent = label;
    head.append(th);
  });
  table.append(head);
  // Engine order is best-first (shanten asc, ukeire desc); show the top rows.
  discards.slice(0, 6).forEach((entry) => {
    const tr = document.createElement('tr');
    if (entry.discard === recommendTile) tr.classList.add('best-row');
    const cut = document.createElement('td');
    cut.textContent = faceText(entry.discard);
    const shanten = document.createElement('td');
    shanten.textContent = String(entry.shanten_after);
    const total = document.createElement('td');
    total.textContent = String(entry.total);
    const tiles = document.createElement('td');
    tiles.textContent = entry.ukeire.map((u) => faceText(u.tile)).join(' ') || '—';
    tr.append(cut, shanten, total, tiles);
    table.append(tr);
  });
  wrap.append(table);
  return wrap;
}

function compareTable(rows) {
  const wrap = document.createElement('div');
  wrap.className = 'evtable-wrap';
  const table = document.createElement('table');
  table.className = 'evtable';
  const head = document.createElement('tr');
  ['選擇', '向聽', '進張', '接受牌'].forEach((label) => {
    const th = document.createElement('th');
    th.textContent = label;
    head.append(th);
  });
  table.append(head);
  rows.forEach((row) => {
    const tr = document.createElement('tr');
    const label = document.createElement('td');
    label.textContent = row.label;
    const shanten = document.createElement('td');
    shanten.textContent = String(row.result.shanten);
    const total = document.createElement('td');
    total.textContent = String(row.result.total);
    const tiles = document.createElement('td');
    tiles.textContent = row.result.ukeire.map((u) => faceText(u.tile)).join(' ') || '—';
    tr.append(label, shanten, total, tiles);
    table.append(tr);
  });
  wrap.append(table);
  return wrap;
}

async function corroborate(lesson, mount) {
  mount.replaceChildren(computingEl('引擎計算進張中…'));
  try {
    if (lesson.kind === 'discard') {
      const body = await post('/api/ukeire', { hand: lesson.hand });
      const recommend = lesson.recommend ? parseCompact(lesson.recommend)[0] : null;
      mount.replaceChildren(discardTable(body.discards, recommend));
    } else {
      const rows = [];
      for (const option of lesson.options) {
        const result = await post('/api/ukeire', { hand: option.hand, melds_declared: option.melds_declared });
        rows.push({ label: option.label, result });
      }
      mount.replaceChildren(compareTable(rows));
    }
  } catch (error) {
    mount.replaceChildren();
    showError(error);
  }
}

function lessonScreen(root, lesson, backToList) {
  const bar = document.createElement('div');
  bar.className = 'topbar';
  const back = document.createElement('button');
  back.type = 'button';
  back.className = 'back';
  back.textContent = '‹ 教學';
  back.addEventListener('click', backToList);
  const heading = document.createElement('h1');
  heading.textContent = lesson.title;
  bar.append(back, heading);
  root.append(bar);

  root.append(tileRow(lesson.hand));

  const question = document.createElement('div');
  question.className = 'lesson-question';
  question.textContent = lesson.question;
  root.append(question);

  const answer = document.createElement('div');
  answer.className = 'lesson-answer';
  answer.textContent = lesson.answer;
  root.append(answer);

  const table = document.createElement('div');
  root.append(table);
  corroborate(lesson, table);

  const caption = document.createElement('div');
  caption.className = 'note';
  caption.textContent = '進張 = 目前還沒被看到、能讓向聽數前進的牌張數（純牌效，未計台數與危險）。';
  root.append(caption);

  const points = document.createElement('div');
  points.className = 'lesson-points';
  lesson.points.forEach((text, index) => {
    const p = document.createElement('p');
    p.innerHTML = `<span class="lesson-point-n">${index + 1}</span>${text}`;
    points.append(p);
  });
  root.append(points);
}

export function lessonsScreen(root) {
  function showList() {
    root.replaceChildren();
    const bar = document.createElement('div');
    bar.className = 'topbar';
    const back = document.createElement('a');
    back.className = 'back';
    back.href = '#/';
    back.textContent = '‹ 首頁';
    const heading = document.createElement('h1');
    heading.textContent = '教學';
    bar.append(back, heading);
    root.append(bar);

    const intro = document.createElement('div');
    intro.className = 'note';
    intro.textContent = '幾個基本牌效觀念，每題都用引擎的進張數佐證。看完可到「單手」練習實戰同類局面。';
    root.append(intro);

    const list = document.createElement('div');
    list.className = 'cards';
    LESSONS.forEach((lesson) => list.append(lessonCard(lesson, (l) => {
      root.replaceChildren();
      lessonScreen(root, l, showList);
      window.scrollTo(0, 0);
    })));
    root.append(list);
  }
  showList();
}
