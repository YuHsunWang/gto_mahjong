// Hash router + mode home (W3). Screens own the #app root and re-render it.

import { drillScreen } from './quiz.js';
import { trainerScreen } from './trainer.js';
import { analyzeScreen, scoreScreen } from './tools.js';
import { summary, accuracySeries, sparklineEl } from './stats.js';
import { tileEl } from './tiles.js';

const app = document.getElementById('app');

const MODES = [
  {
    hash: '#/trainer',
    name: '整場',
    en: 'Full hand',
    desc: '一局打到底：切牌、鳴牌、槓的每個決策都即時 EV 評分。',
    statsKey: 'trainer',
  },
  {
    hash: '#/quiz',
    name: '單手',
    en: 'Spot drill',
    desc: '種子產生的關鍵一手：切哪張？和 GTO 最佳解比對。',
    statsKey: 'quiz',
  },
  {
    hash: '#/endgame',
    name: '殘局',
    en: 'Endgame drill',
    desc: '牌牆將盡的高壓局面：推還是守？進攻／防守題自動標記。',
    statsKey: 'endgame',
  },
];

function modeCard(mode) {
  const card = document.createElement('a');
  card.className = 'card';
  card.href = mode.hash;
  const head = document.createElement('div');
  head.className = 'card-head';
  const name = document.createElement('span');
  name.className = 'card-name';
  name.textContent = mode.name;
  const en = document.createElement('span');
  en.className = 'card-en';
  en.textContent = mode.en;
  head.append(name, en);
  const desc = document.createElement('div');
  desc.className = 'card-desc';
  desc.textContent = mode.desc;
  card.append(head, desc);

  const stats = summary(mode.statsKey);
  const row = document.createElement('div');
  row.className = 'card-stats';
  if (stats.decisions) {
    const accuracy = Math.round((100 * stats.best) / stats.decisions);
    const average = (stats.loss / stats.decisions).toFixed(2);
    row.innerHTML = `<span>已答 <b>${stats.decisions}</b></span>`
      + `<span>最佳率 <b>${accuracy}%</b></span>`
      + `<span>均損 <b>${average}</b> 台</span>`;
    const spark = document.createElement('span');
    spark.className = 'spark';
    spark.append(sparklineEl(accuracySeries(mode.statsKey)));
    row.append(spark);
  } else {
    row.innerHTML = '<span>尚無紀錄 — 從這裡開始</span>';
  }
  card.append(row);
  return card;
}

function homeScreen(root) {
  const title = document.createElement('div');
  title.className = 'home-title';
  const crest = tileEl(33, { size: 'sm' }); // 中 — drawn, so it renders without emoji fonts
  crest.classList.add('crest');
  title.append(crest, document.createTextNode(' 台灣麻將教室'));
  const sub = document.createElement('div');
  sub.className = 'home-sub';
  sub.textContent = '16 張台灣麻將 · EV 決策訓練 · 本桌無花牌';
  root.append(title, sub);

  const cards = document.createElement('div');
  cards.className = 'cards';
  MODES.forEach((mode) => cards.append(modeCard(mode)));
  root.append(cards);

  const tools = document.createElement('div');
  tools.className = 'tools-row';
  [['#/analyze', '切牌分析', '任意局面 EV 排名'], ['#/score', '算台', '和牌台數計算']].forEach(([hash, name, desc]) => {
    const card = document.createElement('a');
    card.className = 'card';
    card.href = hash;
    card.innerHTML = `<div class="card-head"><span class="card-name">${name}</span></div>`
      + `<div class="card-desc">${desc}</div>`;
    tools.append(card);
  });
  root.append(tools);

  const setting = document.createElement('div');
  setting.className = 'setting-row';
  const label = document.createElement('label');
  label.className = 'check';
  const box = document.createElement('input');
  box.type = 'checkbox';
  box.checked = localStorage.getItem('mj-onetap') === '1';
  box.addEventListener('change', () => localStorage.setItem('mj-onetap', box.checked ? '1' : '0'));
  label.append(box, document.createTextNode('切牌免確認（一點即切）'));
  setting.append(label);
  root.append(setting);

  const footnote = document.createElement('div');
  footnote.className = 'footnote';
  footnote.textContent = '機率以機器人自我對局校準，不代表真人牌局；進攻 EV 僅計自摸。'
    + 'EV 為蒙地卡羅估計：貼著判定門檻的手會自動加碼精算，仍標「（邊緣）」者受殘餘取樣誤差影響。'
    + '本桌無花牌（花牌建模為獨立的未來里程碑）。';
  root.append(footnote);
}

const ROUTES = {
  '': homeScreen,
  '#/': homeScreen,
  '#/quiz': (root) => drillScreen(root, { apiBase: '/api/quiz', mode: 'quiz', title: '單手練習' }),
  '#/endgame': (root) => drillScreen(root, { apiBase: '/api/endgame', mode: 'endgame', title: '殘局練習' }),
  '#/trainer': trainerScreen,
  '#/analyze': analyzeScreen,
  '#/score': scoreScreen,
};

function route() {
  const screen = ROUTES[window.location.hash] || homeScreen;
  app.replaceChildren();
  screen(app);
  window.scrollTo(0, 0);
}

window.addEventListener('hashchange', route);
route();
