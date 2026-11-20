// Hash router + mode home (W3). Screens own the #app root and re-render it.

import { drillScreen } from './quiz.js';
import { attackDefenseScreen } from './attack-defense.js';
import { trainerScreen } from './trainer.js';
import { analyzeScreen, scoreScreen } from './tools.js';
import { lessonsScreen } from './lessons.js';
import { summary, hasLegacyStats } from './stats.js';
import { tileEl } from './tiles.js';
import { schemeToggle } from './scheme.js';
import { modeCard, toolCard } from './lobby.js';

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

// Lobby order also defines the native keyboard focus order.
const MODES = [
  { hash: '#/trainer', chars: '整場', desc: '一局打到底，每一手都幫你評分。', statsKey: 'trainer' },
  { hash: '#/quiz', chars: '單手', desc: '只考最關鍵的那一手。', statsKey: 'quiz' },
  { hash: '#/endgame', chars: '殘局', desc: '牌快摸完了，要衝還是要守。', statsKey: 'endgame' },
  { hash: '#/attack-defense', chars: '攻守', desc: '同一手牌，先選進攻，再選防守。', statsKey: 'attack-defense' },
  { hash: '#/lessons', chars: '教學', desc: '牌效與攻守觀念，七堂短課。', statsKey: null },
];

function statsLine(statsKey) {
  let stats;
  try { stats = summary(statsKey, statsKey === 'attack-defense' ? 'drill' : undefined); }
  catch (_) { return '還沒練過'; }
  if (!stats.decisions) return '還沒練過';
  if (statsKey === 'attack-defense') return `已答 ${stats.decisions} 次選牌，正確率 ${stats.qualityScore}%`;
  return `已答 ${stats.decisions}，品質 ${stats.qualityScore === null ? '—' : `${stats.qualityScore}%`}`;
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
  modes.className = 'lobby-grid';
  modes.setAttribute('aria-label', '練習模式');
  MODES.forEach((mode, index) => modes.append(modeCard(mode, index, mode.statsKey ? statsLine(mode.statsKey) : null)));
  const tools = document.createElement('div');
  tools.className = 'lobby-tools';
  tools.append(
    toolCard('#/score', '算台', '這手牌胡了幾台', 'count'),
    toolCard('#/analyze', '打牌分析', '自己擺牌，看每張牌的分數', 'chart'),
  );
  modes.append(tools);
  lobby.append(heading, modes);

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

const TABLE_ROUTES = ['#/quiz', '#/endgame', '#/trainer', '#/attack-defense'];
const phonePortrait = matchMedia('(max-width: 700px) and (orientation: portrait)');
const phoneScreen = matchMedia('(pointer: coarse) and (max-width: 700px) and (orientation: portrait), (pointer: coarse) and (max-width: 1000px) and (max-height: 560px)');
const rotatePrompt = document.getElementById('rotate-prompt');
let previousFocus = null;

function updateRotationPrompt() {
  const blocked = phonePortrait.matches && !!app.querySelector('.felt');
  if (blocked === !rotatePrompt.hidden) return;
  rotatePrompt.hidden = !blocked;
  app.inert = blocked;
  document.body.classList.toggle('table-portrait', blocked);
  if (blocked) {
    previousFocus = document.activeElement;
    rotatePrompt.focus({preventScroll: true});
  } else if (previousFocus?.isConnected) {
    previousFocus.focus({preventScroll: true});
  }
}
new MutationObserver(updateRotationPrompt).observe(app, {childList: true, subtree: true});
phonePortrait.addEventListener('change', updateRotationPrompt);

let fullscreenGeneration = 0;

async function exitTableFullscreen() {
  fullscreenGeneration += 1;
  try { screen.orientation?.unlock?.(); } catch (_) {}
  try { if (document.fullscreenElement) await document.exitFullscreen(); } catch (_) {}
}

async function enterTableFullscreen() {
  if (!phoneScreen.matches) return;
  const generation = ++fullscreenGeneration;
  try {
    if (!document.fullscreenElement) await document.documentElement.requestFullscreen?.();
    // Leaving the route can overtake the fullscreen request.
    if (generation !== fullscreenGeneration) {
      if (!TABLE_ROUTES.includes(location.hash)) await exitTableFullscreen();
      return;
    }
    await screen.orientation?.lock?.('landscape');
  } catch (_) { /* iOS and denied fullscreen/lock keep the rotate prompt. */ }
}

// Fullscreen must start in the tap handler, before hashchange loses activation.
document.addEventListener('click', (event) => {
  const link = event.target.closest('a');
  if (link ? TABLE_ROUTES.includes(link.hash)
    : TABLE_ROUTES.includes(location.hash) && event.target.closest('#app button')) {
    void enterTableFullscreen();
  }
}, true);

function route() {
  const screen = window.location.hash.startsWith('#/lessons/')
    ? (root) => lessonsScreen(root, window.location.hash.slice('#/lessons/'.length))
    : ROUTES[window.location.hash] || homeScreen;
  app.classList.toggle('app--table', TABLE_ROUTES.includes(window.location.hash));
  app.classList.toggle('app--home', screen === homeScreen);
  if (!TABLE_ROUTES.includes(location.hash)) void exitTableFullscreen();
  app.replaceChildren();
  screen(app);
  updateRotationPrompt();
  window.scrollTo(0, 0);
}

window.addEventListener('hashchange', route);
route();
