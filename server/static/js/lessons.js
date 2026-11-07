// 教學 — hand-written explanations from the shared lesson catalog.
// Efficiency lessons use /api/ukeire inline; danger lessons show public rivers
// and are checked against production grading offline.

import { get, post, showError } from './api.js';
import { tileEl, parseCompact, faceText } from './tiles.js';
import { computingEl } from './table.js';

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
  ['打牌', '向聽', '進張', '接受牌'].forEach((label) => {
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
        const result = await post('/api/ukeire', { hand: option.hand, melds_declared: option.melds_declared, visible: option.visible || '' });
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
  if (lesson.kind === 'danger') {
    if (lesson.own_melds?.length) {
      const melds = document.createElement('div');
      melds.className = 'note';
      melds.textContent = '你的副露';
      root.append(melds, tileRow(lesson.own_melds.join('')));
    }
    const context = document.createElement('div');
    context.className = 'note';
    context.textContent = `牌牆剩 ${lesson.wall_remaining} 張；你是${['東', '南', '西', '北'][lesson.seat]}家。牌河依出牌順序排列。`;
    root.append(context);
    const rivers = [{ seat: lesson.seat, river: lesson.own_river }, ...lesson.opponents];
    rivers.forEach((opponent) => {
      const river = document.createElement('section');
      river.className = 'lesson-river';
      const label = document.createElement('div');
      label.className = 'note';
      label.textContent = opponent.seat === lesson.seat ? '你的牌河'
        : `對手 ${opponent.seat}：${opponent.declared_at == null ? '未宣告' : `已宣告聽牌（第 ${opponent.declared_at + 1} 張棄牌）`}`;
      river.append(label, tileRow(opponent.river));
      root.append(river);
    });
  }

  const question = document.createElement('div');
  question.className = 'lesson-question';
  question.textContent = lesson.question;
  root.append(question);

  const answer = document.createElement('div');
  answer.className = 'lesson-answer';
  answer.textContent = lesson.answer;
  root.append(answer);

  if (lesson.kind !== 'danger') {
    const table = document.createElement('div');
    root.append(table);
    corroborate(lesson, table);

    const caption = document.createElement('div');
    caption.className = 'note';
    caption.textContent = '進張 = 目前還沒被看到、能讓向聽數前進的牌張數（純牌效，未計台數與危險）。';
    root.append(caption);
  }

  const points = document.createElement('div');
  points.className = 'lesson-points';
  lesson.points.forEach((text, index) => {
    const p = document.createElement('p');
    p.innerHTML = `<span class="lesson-point-n">${index + 1}</span>${text}`;
    points.append(p);
  });
  root.append(points);
}

export async function lessonsScreen(root, lessonId = null) {
  const hash = window.location.hash;
  let lessons;
  root.replaceChildren(computingEl('讀取教學中…'));
  try {
    lessons = await get('/api/lessons');
  } catch (error) {
    if (window.location.hash === hash) {
      root.replaceChildren();
      showError(error);
    }
    return;
  }
  if (window.location.hash !== hash) return;
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
    intro.textContent = '幾個基本牌效與攻守觀念；牌效題用進張數佐證，攻守題搭配對手牌河說明。看完可到「單手」練習實戰同類局面。';
    root.append(intro);

    const list = document.createElement('div');
    list.className = 'cards';
    lessons.forEach((lesson) => list.append(lessonCard(lesson, (l) => {
      window.location.hash = `#/lessons/${l.id}`;
    })));
    root.append(list);
  }
  const lesson = lessons.find((item) => item.id === lessonId);
  if (lesson) {
    root.replaceChildren();
    lessonScreen(root, lesson, () => { window.location.hash = '#/lessons'; });
  } else {
    showList();
  }
}
