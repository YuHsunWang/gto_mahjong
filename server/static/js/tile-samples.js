// Table material studies use exactly the same SVG renderer as the live app.
import { TILE_THEMES, NUMERAL_FACES, HONOR_FACES, FLOWER_FACES, tileFaceSvg, flowerFaceSvg, tileBackSvg } from './tile-faces.js';

const FACES = [
  ...['wan', 'dot', 'bamboo'].flatMap((suit, offset) => Array.from({ length: 9 }, (_, i) =>
    [`${suit}${i + 1}`, `${NUMERAL_FACES[i + 1]}${'萬筒條'[offset]}`, offset * 9 + i])),
  ...HONOR_FACES.map((label, i) => [['east', 'south', 'west', 'north', 'white', 'green', 'red'][i], label, 27 + i]),
  ...FLOWER_FACES.map((label, i) => [['spring', 'summer', 'autumn', 'winter', 'plum', 'orchid', 'chrysanthemum', 'flowerBamboo'][i], `${label} ${i % 4 + 1}`, label]),
  ['back', '牌背', null],
];
const FACE_IDS = new Map(FACES.map(([id, , value]) => [id, value]));
function tile(id, t, landscape = false) {
  const value = FACE_IDS.get(id);
  const svg = id === 'back' ? tileBackSvg(landscape ? 'landscape' : 'portrait')
    : typeof value === 'number' ? tileFaceSvg(value) : flowerFaceSvg(value);
  const label = FACES.find(face => face[0] === id)[1];
  return `<span class="tile" data-tile="${id}" role="img" aria-label="${label}" title="${label}">${svg.outerHTML}</span>`;
}
const HAND = ['wan1', 'wan5', 'wan9', 'dot1', 'dot5', 'dot9', 'bamboo1', 'bamboo5', 'bamboo9', 'east', 'east', 'red', 'green', 'white', 'white', 'bamboo1'];
const RIVER = ['wan9', 'east', 'bamboo5', 'dot1', 'red', 'wan1', 'dot9', 'green', 'bamboo9', 'wan5', 'white', 'dot5'];

function renderTheme(t) {
  const section = document.createElement('section');
  section.className = `sample theme-${t.id}`;
  section.id = `sample-${t.id}`;
  section.dataset.tableTheme = t.id;
  section.setAttribute('aria-labelledby', `title-${t.id}`);
  const css = { page: t.page, ink: t.ink, muted: t.muted, line: t.line, rail: t.rail, 'rail-hi': t.railHi, 'table-ink': t.tableInk };
  Object.entries(css).forEach(([key, value]) => section.style.setProperty(`--${key}`, value));
  section.style.setProperty('--felt-surface', `radial-gradient(ellipse at 50% 30%, ${t.feltHi}, ${t.felt} 60%, ${t.feltLo})`);
  const backs = landscape => Array.from({ length: 16 }, () => tile('back', t, landscape)).join('');
  section.innerHTML = `
    <header class="sample-header"><div class="letter" aria-hidden="true">${t.id}</div><h2 id="title-${t.id}">${t.name}<span>${t.english}</span></h2><div class="palette" aria-label="桌面、牌面、牌背色票">${[t.felt, t.face, t.back].map(color => `<span class="swatch" style="--swatch:${color}"></span>`).join('')}</div></header>
    <div class="table-frame"><div class="table" aria-label="${t.name}桌面：十六張手牌、吃碰各一組、十二張捨牌、三家牌背">
      <div class="opponent opponent--top" aria-label="對家十六張牌背">${backs(false)}</div>
      <span class="seat-label seat-label--top">對家</span><span class="seat-label seat-label--left">上家</span><span class="seat-label seat-label--right">下家</span>
      <div class="opponent opponent--left" aria-label="上家十六張牌背">${backs(true)}</div>
      <div class="opponent opponent--right" aria-label="下家十六張牌背">${backs(true)}</div>
      <div class="river" aria-label="十二張捨牌">${RIVER.map(id => tile(id, t)).join('')}</div>
      <div class="table-mark"><strong>${t.id === 'D' ? '麻雀俱樂部' : '台灣十六張'}</strong><small>${t.id === 'D' ? 'THE LITTLE SPARROW CLUB' : 'TAIWANESE MAHJONG'}</small></div>
      <div class="melds" aria-label="明牌展示"><div class="meld" aria-label="吃：一筒二筒三筒">${['dot1', 'dot2', 'dot3'].map(id => tile(id, t)).join('')}<span class="meld-label">吃</span></div><div class="meld" aria-label="碰：三張東">${Array.from({ length: 3 }, () => tile('east', t)).join('')}<span class="meld-label">碰</span></div></div>
      <div class="hand" aria-label="自己的十六張手牌">${HAND.map(id => tile(id, t)).join('')}</div><span class="seat-label hand-label">自己的手牌</span>
    </div></div>
    <div class="sample-note"><span>${t.note}</span><span>${t.detail}</span></div>
    <div class="face-sheet" id="faces-${t.id}" aria-label="${t.name}放大牌面總覽"><div class="sheet-heading"><span>牌面細節 / TILE STUDIES</span><span>34 FACES + 8 FLOWERS + 1 BACK</span></div><div class="face-row">${FACES.map(([id, label]) => `<div class="face-item">${tile(id, t)}<span class="face-name">${label}</span></div>`).join('')}</div></div>`;
  return section;
}

const samples = document.querySelector('#samples');
samples.append(...TILE_THEMES.map(renderTheme));
document.querySelectorAll('[data-view]').forEach(button => {
  button.addEventListener('click', () => {
    samples.classList.toggle('is-expanded', button.dataset.view === 'expanded');
    document.querySelectorAll('[data-view]').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
  });
});
