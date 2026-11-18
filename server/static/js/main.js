// Hash router + mode home (W3). Screens own the #app root and re-render it.

import { drillScreen } from './quiz.js';
import { attackDefenseScreen } from './attack-defense.js';
import { trainerScreen } from './trainer.js';
import { analyzeScreen, scoreScreen } from './tools.js';
import { lessonsScreen } from './lessons.js';
import { summary, hasLegacyStats } from './stats.js';
import { tileEl } from './tiles.js';
import { schemeToggle } from './scheme.js';

const app = document.getElementById('app');

function tableThemeControl() {
  const label = document.createElement('label');
  label.className = 'theme-control';
  label.append(document.createTextNode('牌桌風格'));
  const select = document.createElement('select');
  ['瓷白', '茶室', '夜藍', '聯名風'].forEach((name, index) => {
    select.add(new Option(name, 'ABCD'[index]));
  });
  select.value = document.documentElement.dataset.tableTheme || 'A';
  select.addEventListener('change', () => {
    let theme = select.value;
    try { localStorage.setItem('mj-table-theme', theme); }
    catch (_) { theme = 'A'; }
    document.documentElement.dataset.tableTheme = theme;
    select.value = theme;
  });
  label.append(select);
  return label;
}

// The 大廳 plaques: two stacked characters, first ink, second cinnabar.
const MODES = [
  { hash: '#/trainer', chars: '整場', desc: '一局打到底，每一手都幫你評分。', statsKey: 'trainer' },
  { hash: '#/quiz', chars: '單手', desc: '只考最關鍵的那一手。', statsKey: 'quiz' },
  { hash: '#/endgame', chars: '殘局', desc: '牌快摸完了，要衝還是要守。', statsKey: 'endgame' },
  { hash: '#/attack-defense', chars: '攻守', desc: '同一手牌，先選進攻，再選防守。', statsKey: 'attack-defense' },
  { hash: '#/lessons', chars: '教學', desc: '孤張、聽牌、吃碰取捨，四堂短課。', statsKey: null },
];

function statsLine(statsKey) {
  let stats;
  try { stats = summary(statsKey, statsKey === 'attack-defense' ? 'drill' : undefined); }
  catch (_) { return '還沒練過'; }
  if (!stats.decisions) return '還沒練過';
  if (statsKey === 'attack-defense') return `已答 ${stats.decisions} 次選牌，正確率 ${stats.qualityScore}%`;
  return `已答 ${stats.decisions}，品質 ${stats.qualityScore === null ? '—' : `${stats.qualityScore}%`}`;
}

function modeTile(mode, index) {
  const link = document.createElement('a');
  link.className = index === 0 ? 'mode mode--lead' : 'mode';
  link.href = mode.hash;
  const face = document.createElement('span');
  face.className = 'mode-face';
  face.setAttribute('role', 'img');
  face.setAttribute('aria-label', mode.chars);
  [...mode.chars].forEach((char) => {
    const span = document.createElement('span');
    span.textContent = char;
    face.append(span);
  });
  const text = document.createElement('span');
  text.className = 'mode-desc';
  const desc = document.createElement('span');
  desc.textContent = mode.desc;
  text.append(desc);
  if (mode.statsKey) {
    const stats = document.createElement('span');
    stats.textContent = statsLine(mode.statsKey);
    stats.className = stats.textContent === '還沒練過' ? 'mode-stats' : 'mode-stats played';
    text.append(stats);
  }
  link.append(face, text);
  return link;
}

function toolLink(hash, token, color, name, desc) {
  const link = document.createElement('a');
  link.className = 'tool-link';
  link.href = hash;
  const disc = document.createElement('span');
  disc.className = 'token';
  disc.setAttribute('aria-hidden', 'true');
  disc.style.setProperty('--token', color);
  disc.textContent = token;
  const text = document.createElement('span');
  const title = document.createElement('b');
  title.textContent = name;
  const sub = document.createElement('small');
  sub.textContent = desc;
  text.append(title, sub);
  link.append(disc, text);
  return link;
}

function homeScreen(root) {
  const bar = document.createElement('header');
  bar.className = 'topbar home-bar';
  const brand = document.createElement('div');
  brand.className = 'home-brand';
  const crest = tileEl(33, { size: 'sm' }); // 中 — drawn, so it renders without emoji fonts
  crest.classList.add('crest');
  const title = document.createElement('h1');
  title.textContent = '台灣麻將教室';
  brand.append(crest, title);

  const setting = document.createElement('div');
  setting.className = 'home-settings';
  // Other lobby preferences also read storage. A blocked store must still
  // leave the theme control usable with its default A.
  try { setting.append(schemeToggle(() => route())); } catch (_) {}
  setting.append(tableThemeControl());
  const label = document.createElement('label');
  label.className = 'check';
  const box = document.createElement('input');
  box.type = 'checkbox';
  try { box.checked = localStorage.getItem('mj-onetap') === '1'; } catch (_) {}
  box.addEventListener('change', () => {
    try { localStorage.setItem('mj-onetap', box.checked ? '1' : '0'); } catch (_) {}
  });
  label.append(box, document.createTextNode('打牌免確認（一點即切）'));
  setting.append(label);
  bar.append(brand, setting);

  const lobby = document.createElement('section');
  lobby.className = 'lobby';
  const heading = document.createElement('h2');
  heading.textContent = '今天練哪一種？';
  const modes = document.createElement('nav');
  modes.className = 'mode-tiles';
  modes.setAttribute('aria-label', '練習模式');
  MODES.forEach((mode, index) => modes.append(modeTile(mode, index)));
  const tools = document.createElement('div');
  tools.className = 'tool-links';
  tools.append(
    toolLink('#/score', '台', 'var(--tool-red)', '算台', '這手牌胡了幾台'),
    toolLink('#/analyze', '析', 'var(--tool-blue)', '打牌分析', '自己擺牌，看每張牌的分數'),
  );
  lobby.append(heading, modes, tools);

  const foot = document.createElement('footer');
  foot.className = 'shell-foot';
  const details = document.createElement('details');
  const summaryEl = document.createElement('summary');
  summaryEl.textContent = '分數是怎麼算的';
  const footnote = document.createElement('p');
  footnote.className = 'footnote';
  let legacyStats = false;
  try { legacyStats = hasLegacyStats(); } catch (_) {}
  footnote.textContent = '選項只依模型模擬到牌局結束的預期淨得分排序；P(胡牌)、P(流局)與胡牌值只作解讀。'
    + '校準資料只來自內建機器人，缺表時會明示改用簡化估計，不代表真人牌局。'
    + '預期淨得分來自反覆隨機模擬：貼著判定門檻的手會自動加碼精算，仍標「（邊緣）」者受殘餘取樣誤差影響。'
    + '本桌無花牌（花牌建模為獨立的未來里程碑）。'
    + (legacyStats ? ' 舊版未標底台的統計已保留為舊紀錄，未併入目前方案。' : '');
  details.append(summaryEl, footnote);
  foot.append(details);
  root.append(bar, lobby, foot);
}

const ROUTES = {
  '': homeScreen,
  '#/': homeScreen,
  '#/quiz': (root) => drillScreen(root, { apiBase: '/api/quiz', mode: 'quiz', title: '單手練習' }),
  '#/endgame': (root) => drillScreen(root, { apiBase: '/api/endgame', mode: 'endgame', title: '殘局練習' }),
  '#/trainer': trainerScreen,
  '#/attack-defense': attackDefenseScreen,
  '#/lessons': lessonsScreen,
  '#/analyze': analyzeScreen,
  '#/score': scoreScreen,
};

function route() {
  const screen = ROUTES[window.location.hash] || homeScreen;
  app.classList.toggle('app--table', ['#/quiz', '#/endgame', '#/trainer', '#/attack-defense'].includes(window.location.hash));
  app.classList.toggle('app--home', screen === homeScreen);
  app.replaceChildren();
  screen(app);
  window.scrollTo(0, 0);
}

window.addEventListener('hashchange', route);
route();
