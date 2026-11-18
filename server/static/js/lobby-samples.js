// Isolated lobby study: no router, API requests, or localStorage writes.
// Copy matches main.js MODES/toolLink and the first-visit statsLine result.
const MODES = [
  { name: '整場', desc: '一局打到底，每一手都幫你評分。', route: 'trainer', icon: 'table' },
  { name: '單手', desc: '只考最關鍵的那一手。', route: 'quiz', icon: 'hand' },
  { name: '殘局', desc: '牌快摸完了，要衝還是要守。', route: 'endgame', icon: 'clock' },
  { name: '攻守', desc: '同一手牌，先選進攻，再選防守。', route: 'attack-defense', icon: 'shield' },
  { name: '教學', desc: '孤張、聽牌、吃碰取捨，四堂短課。', route: 'lessons', icon: 'book' },
];
const TOOLS = [
  { name: '算台', desc: '這手牌胡了幾台', route: 'score', icon: 'count' },
  { name: '打牌分析', desc: '自己擺牌，看每張牌的分數', route: 'analyze', icon: 'chart' },
];
const PATHS = {
  table: '<rect x="4" y="5" width="24" height="22" rx="5"/><path d="M9 11h14M9 21h14M11 5v4m10-4v4M11 23v4m10-4v4"/>',
  hand: '<rect x="10" y="4" width="15" height="22" rx="3"/><path d="m7 9-3 1 3 18a3 3 0 0 0 3 2l10-2M15 10h5m-5 5h5m-5 5h2"/>',
  clock: '<circle cx="16" cy="17" r="11"/><path d="M16 10v7l5 3M12 2h8m-4 0v4m10-1 3 3"/>',
  shield: '<path d="m16 3 11 4v9c0 6-6 10-11 13C11 26 5 22 5 16V7Zm0 0v26M10 13h6m0 5h6"/>',
  book: '<path d="M16 7C12 3 6 4 3 5v21c4-2 9-2 13 1 4-3 9-3 13-1V5c-3-1-9-2-13 2Zm0 0v20M7 11h5m-5 5h5m8-5h5m-5 5h5"/>',
  count: '<rect x="5" y="3" width="22" height="26" rx="4"/><path d="M10 9h12M10 15h2m8 0h2m-12 5h2m8 0h2m-12 5h2m8 0h2"/>',
  chart: '<path d="M5 4v23h23M11 22v-6m7 6V9m7 13V4"/>',
};
const chevron = '<svg class="study-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="m9 5 7 7-7 7" stroke-linecap="round" stroke-linejoin="round"/></svg>';
const icon = name => `<span class="study-icon"><svg viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${PATHS[name]}</svg></span>`;
const progress = mode => mode.route === 'lessons' ? '' : '<span class="study-progress">還沒練過</span>';
const href = mode => `./index.html#/${mode.route}`;

// Original continuous round head/body silhouette, following the sparrow in
// tile-faces.js. Redrawn with existing table pigments only, in five scenes.
function illustration(scene) {
  const tile = (x, y, angle = 0) => `<g transform="translate(${x} ${y}) rotate(${angle} 10 14)"><rect x="0" y="2" width="21" height="29" rx="4" fill="var(--wood)"/><rect width="21" height="28" rx="4" fill="var(--lacquer)" stroke="var(--ink)" stroke-width="1.2"/><path d="M7 8h7v10H7zM10.5 5v16" fill="none" stroke="var(--tool-red)" stroke-width="1.3"/></g>`;
  const props = [
    `<path d="m46 96 49-19h82l39 19-38 23H87Z" fill="var(--felt-0)" stroke="var(--ink)" stroke-width="1.3"/>${tile(83, 79, -9)}${tile(108, 82)}${tile(133, 80, 7)}${tile(157, 77, 12)}`,
    `${tile(73, 80, -14)}${tile(98, 77)}${tile(124, 78, 12)}<path d="m166 74 5-11 5 11m-5-11v20" fill="none" stroke="var(--ink)" stroke-width="2"/>`,
    `<circle cx="75" cy="69" r="23" fill="var(--panel)" stroke="var(--ink)" stroke-width="1.5"/><path d="M75 54v15l10 6M68 40h14" fill="none" stroke="var(--ink)" stroke-width="2"/>${tile(102, 84, -7)}${tile(128, 84, 7)}`,
    `<path d="m76 52 21 8v17c0 14-15 25-21 27-6-2-21-13-21-27V60Z" fill="var(--panel)" stroke="var(--ink)" stroke-width="1.5"/><path d="m66 76 7 7 14-17" fill="none" stroke="var(--ink)" stroke-width="2"/>${tile(119, 84, -6)}${tile(145, 84, 8)}`,
    '<path d="M72 83q23-7 48 4 23-12 48-5v31q-26-6-48 3-24-10-48-3Z" fill="var(--panel)" stroke="var(--ink)" stroke-width="1.5"/><path d="M120 88v27M83 92l25 2m-25 7 25 2m25-9 23-3m-23 12 23-3" fill="none" stroke="var(--ink)" stroke-width="1.4"/>',
  ][scene];
  return `<div class="study-art" aria-hidden="true"><svg viewBox="0 0 270 135" fill="none" xmlns="http://www.w3.org/2000/svg">
    <ellipse cx="136" cy="118" rx="86" ry="7" fill="var(--wood)" opacity=".35"/>
    <circle cx="134" cy="64" r="49" fill="var(--panel)" opacity=".48"/>
    <g transform="translate(${scene === 2 || scene === 3 ? 102 : 75} -1)" stroke="var(--ink)" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
      <path d="m41 87-9 19 15-7 9 8 4-21" fill="var(--wood)"/>
      <path d="M49 24q24-2 29 22 14 16 4 36-10 17-32 16-24 0-32-19-9-19 6-34 2-20 20-21-5-6-1-6l10 7" fill="var(--wood-hi)"/>
      <path d="M27 39q18-24 45 1-13-5-21-2-12-5-24 1Z" fill="var(--wood)" stroke="none"/>
      <path d="M25 65q23-15 48 0 3 27-23 27-25-1-25-27Z" fill="var(--panel)" stroke="none"/>
      <path d="M23 66q14-7 19 9-9 7-18 1m50-10q-13-6-16 9 10 9 20 0" fill="var(--wood)"/>
      <path d="m44 51 11 4-10 6Z" fill="var(--gold)"/>
      <circle cx="34" cy="47" r="2.4" fill="var(--ink)" stroke="none"/><circle cx="65" cy="47" r="2.4" fill="var(--ink)" stroke="none"/>
      <path d="M45 66q5 4 10-1M37 97l-2 5m29-5 2 5"/>
    </g>${props}
    <g stroke="var(--ink)" stroke-width="1.4" stroke-linecap="round"><path d="M204 36v8m-4-4h8M58 36v5m-2.5-2.5h5"/><circle cx="213" cy="88" r="2"/></g>
  </svg></div>`;
}

function card(mode, index, illustrated = false) {
  return `<a class="study-card" href="${href(mode)}">${illustrated ? illustration(index) : icon(mode.icon)}<span class="study-card-copy"><span class="study-name">${mode.name}${chevron}</span><span class="study-desc">${mode.desc}</span>${progress(mode)}</span></a>`;
}
function tool(mode) {
  return `<a class="study-tool" href="${href(mode)}">${icon(mode.icon)}<span class="study-tool-copy"><strong>${mode.name}</strong><span class="study-desc">${mode.desc}</span></span>${chevron}</a>`;
}
function row(mode, isTool = false) {
  return `<a class="study-row" href="${href(mode)}">${icon(mode.icon)}<span class="study-row-copy"><span class="study-name">${mode.name}</span><span class="study-desc">${mode.desc}</span></span>${isTool ? '' : progress(mode)}${chevron}</a>`;
}
function render(direction) {
  if (direction === '1') {
    return `<nav class="study-game-grid" aria-label="練習模式">${MODES.map((mode, i) => card(mode, i, true)).join('')}<div class="study-tools">${TOOLS.map(tool).join('')}</div></nav>`;
  }
  if (direction === '2') {
    const mode = MODES[0];
    return `<section class="study-hero" aria-labelledby="hero-name"><div><h3 id="hero-name">${mode.name}</h3><span class="study-desc">${mode.desc}</span><div class="study-hero-action"><a class="study-start" href="${href(mode)}">開始${chevron}</a>${progress(mode)}</div></div>${illustration(0)}</section><nav class="study-small-grid" aria-label="練習模式">${MODES.slice(1).map((mode, i) => card(mode, i)).join('')}</nav><nav class="study-quiet-tools" aria-label="工具">${TOOLS.map(tool).join('')}</nav>`;
  }
  return `<div class="study-list-wrap"><h3 class="study-group-title" id="practice-title">練習</h3><nav class="study-list" aria-labelledby="practice-title">${MODES.map(mode => row(mode)).join('')}</nav><h3 class="study-group-title" id="tools-title">工具</h3><nav class="study-list" aria-labelledby="tools-title">${TOOLS.map(mode => row(mode, true)).join('')}</nav></div>`;
}

const directionSelect = document.querySelector('#study-direction');
const themeSelect = document.querySelector('#study-theme');
document.querySelector('.study-controls').hidden = new URLSearchParams(location.search).get('mock') === '1';
function sync() {
  const match = location.hash.match(/^#([123])\/([ABCD])$/);
  const [, direction, theme] = match || [null, '1', 'A'];
  directionSelect.value = direction;
  themeSelect.value = theme;
  document.documentElement.dataset.tableTheme = theme;
  document.querySelector('#study-content').innerHTML = render(direction);
}
function update() {
  location.hash = `${directionSelect.value}/${themeSelect.value}`;
}
directionSelect.addEventListener('change', update);
themeSelect.addEventListener('change', update);
window.addEventListener('hashchange', sync);
sync();
