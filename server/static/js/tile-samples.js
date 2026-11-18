// Standalone material study. No imports, live-app hooks, fonts, or image assets.
// Every main glyph is a hand-authored path, not an outline from a font.
// Only the small flower corner labels use local CJK Kai/serif fallbacks.
const CJK_SERIF = "'BiauKai', 'DFKai-SB', 'KaiTi', 'Noto Serif TC', 'PMingLiU', 'MingLiU', serif";

const THEMES = [
  { id: 'A', name: '瓷白', english: 'Porcelain', page: '#F3F5F7', felt: '#CCDCE5', feltHi: '#DDE8EE', feltLo: '#B8CAD5', rail: '#A9BBC8', railHi: '#D4DFE7', ink: '#203344', muted: '#475d6b', line: '#ccd7df', tableInk: '#425664', face: '#fbfaf2', edge: '#cfcabc', side: '#c8c2b1', foot: '#ada694', red: '#b72e2b', blue: '#254e83', green: '#176543', back: '#15583f', backEdge: '#0d3c2c', backHi: '#377b5f', note: '藍灰毛氈 · 象牙白牌 · 深綠牌背', detail: '沿用目前瓷白桌面色票' },
  { id: 'B', name: '茶室', english: 'Tea room', page: '#F7F2E8', felt: '#DDD5C4', feltHi: '#e9e2d3', feltLo: '#d0c6b2', rail: '#DFC6A6', railHi: '#efddc6', ink: '#4a4034', muted: '#6e5d49', line: '#dfd4c1', tableInk: '#655746', face: '#fff5df', edge: '#d5c6a8', side: '#d3c4a7', foot: '#b7a387', red: '#a73032', blue: '#334b70', green: '#38613f', back: '#802f45', backEdge: '#542334', backHi: '#ae5b6c', note: '米色織蓆 · 奶油牌 · 酒紅牌背', detail: '淡木色桌框與細緻交織紋理' },
  { id: 'C', name: '夜藍', english: 'Night blue', page: '#111e32', felt: '#203b60', feltHi: '#2a4a72', feltLo: '#172d4c', rail: '#0f2038', railHi: '#3e5471', ink: '#edf3ff', muted: '#b5c7df', line: '#3b506c', tableInk: '#c0d0e6', face: '#ffffff', edge: '#cbd5e2', side: '#c4cede', foot: '#9aaac2', red: '#bb2f3d', blue: '#204e9b', green: '#136447', back: '#2861b0', backEdge: '#173c77', backHi: '#6792d2', note: '深海軍藍毛氈 · 純白牌 · 藍色牌背', detail: '俐落的行動牌桌質感' },
  { id: 'D', name: '聯名風', english: 'Sparrow club', page: '#fff4f4', felt: '#f5dfe4', feltHi: '#fae9ed', feltLo: '#eed2da', rail: '#dba8b8', railHi: '#f5d6df', ink: '#673e50', muted: '#805465', line: '#e6c8d2', tableInk: '#875366', face: '#ffffff', edge: '#e1d7df', side: '#e3dce5', foot: '#c4b4c6', red: '#da385c', blue: '#428ac1', green: '#369866', back: '#bd6e9c', backEdge: '#935278', backHi: '#e8adce', note: '淡粉彩點 · 亮白牌 · 糖果粉牌背', detail: '原創圓麻雀與彩色花草刻線' },
];

// Normalized 100 × 100 pen strokes, deliberately cut like engraved tile marks.
const GLYPHS = {
  '一': 'M12 53 Q48 50 88 49',
  '五': 'M18 14 L83 14 M50 15 L39 83 M20 44 L71 44 L67 83 M11 85 L90 85',
  '九': 'M16 37 L64 34 L59 77 Q57 88 70 88 L87 87 L91 72 M42 12 Q47 71 13 92',
  '萬': 'M11 15 L90 15 M32 6 L32 27 M69 6 L69 27 M24 33 L77 33 L77 58 L24 58 Z M25 45 L76 45 M50 32 L50 80 M15 72 L86 72 L86 94 L74 91 M33 82 L66 80 L61 74',
  '東': 'M10 16 L90 16 M23 30 L78 30 L78 60 L23 60 Z M24 45 L77 45 M50 6 L50 94 M48 60 Q32 81 9 87 M53 61 Q69 79 91 85',
  '中': 'M15 27 L85 27 L85 67 L15 67 Z M50 7 L50 94',
  '發': 'M16 10 L37 10 Q29 34 9 43 M12 23 L24 29 M54 8 Q68 31 91 38 M69 10 L59 21 M85 20 L73 29 M20 48 L43 48 L42 61 L20 61 L18 72 L43 72 Q43 92 28 92 L18 89 M61 44 L78 44 L78 58 L89 58 M60 45 L60 57 L52 64 M55 69 L84 69 Q77 87 54 94 M59 71 Q71 87 91 93',
};

function path(d, color, width = 7) {
  return `<path d="${d}" fill="none" stroke="${color}" stroke-width="${width}" stroke-linecap="round" stroke-linejoin="round"/>`;
}

function glyph(name, color, x, y, width, height) {
  return `<g transform="translate(${x} ${y}) scale(${width / 100} ${height / 100})">${path(GLYPHS[name], color)}</g>`;
}

function engraved(art) {
  // A narrow lip below the pigment gives the impression of a recessed cut.
  return `<g transform="translate(0 .65)" opacity=".7" stroke="#fff" stroke-width="1.1">${art}</g>${art}`;
}

function shell(t, art, label, landscape = false, back = false) {
  const w = landscape ? 132 : 96;
  const h = landscape ? 96 : 132;
  const face = back ? t.back : t.face;
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" role="img" aria-label="${label}">
    <rect x="3" y="7" width="${w - 6}" height="${h - 9}" rx="10" fill="${t.side}"/>
    <path d="M4 ${h - 20}H${w - 4}v8q0 8-8 8H12q-8 0-8-8Z" fill="${t.foot}"/>
    <rect x="3" y="2" width="${w - 6}" height="${h - 12}" rx="9" fill="${face}" stroke="${back ? t.backEdge : t.edge}" stroke-width="1.3"/>
    <path d="M13 6H${w - 13}Q${w - 7} 6 ${w - 7} 13" fill="none" stroke="${back ? t.backHi : '#fff'}" stroke-width="2.5" opacity=".9"/>
    ${art}
    ${t.id === 'D' && !back ? '<path d="M9 14v87" stroke="#fff" stroke-width="3" opacity=".85"/>' : ''}
  </svg>`;
}

function wan(t, number) {
  return shell(t, engraved(glyph(number, t.id === 'D' ? '#6276b8' : '#202d40', 20, 13, 56, 38) + glyph('萬', t.red, 21, 59, 54, 49)), `${number}萬`);
}
function faceWan1(t) { return wan(t, '一'); }
function faceWan5(t) { return wan(t, '五'); }
function faceWan9(t) { return wan(t, '九'); }

function pip(x, y, r, color) {
  return `<g fill="none" stroke="${color}"><circle cx="${x}" cy="${y}" r="${r}" stroke-width="2.5"/><circle cx="${x}" cy="${y}" r="${r - 4}" stroke-width="1.5"/><circle cx="${x}" cy="${y}" r="2" fill="${color}" stroke="none"/></g>`;
}

function faceDot1(t) {
  let rosette = pip(48, 61, 28, t.blue) + pip(48, 61, 13, t.red);
  for (let i = 0; i < 12; i++) {
    const a = i * Math.PI / 6;
    rosette += path(`M${48 + Math.cos(a) * 19} ${61 + Math.sin(a) * 19}l${Math.cos(a) * 5} ${Math.sin(a) * 5}`, t.blue, 2.2);
  }
  return shell(t, engraved(rosette), '一筒');
}
function faceDot2(t) { return shell(t, engraved(pip(48, 34, 15, t.blue) + pip(48, 88, 15, t.blue)), '二筒'); }
function faceDot3(t) { return shell(t, engraved(pip(28, 29, 12, t.blue) + pip(48, 61, 12, t.red) + pip(68, 93, 12, t.blue)), '三筒'); }
function faceDot5(t) {
  return shell(t, engraved([[25, 30], [71, 30], [25, 92], [71, 92]].map(([x, y]) => pip(x, y, 12, t.blue)).join('') + pip(48, 61, 13, t.red)), '五筒');
}
function faceDot9(t) {
  return shell(t, engraved([28, 61, 94].map((y, row) => [24, 48, 72].map(x => pip(x, y, 9, row === 1 ? t.red : t.blue)).join('')).join('')), '九筒');
}

function bamboo(x, y, length, color) {
  return `<g transform="translate(${x} ${y})" stroke="${color}" stroke-linejoin="round">
    <path d="M-3 ${-length / 2}Q0 ${-length / 2 - 3} 3 ${-length / 2}L2 ${length / 2}Q0 ${length / 2 + 3}-2 ${length / 2}Z" fill="${color}" stroke-width="1"/>
    <path d="M-5 ${-length / 2 + 2}h10M-4 0h8M-5 ${length / 2 - 2}h10" fill="none" stroke-width="2.5" stroke-linecap="round"/>
    <path d="M-.8 ${-length / 2 + 6}v${length / 2 - 10}M-.8 4v${length / 2 - 10}" stroke="#fff" stroke-width=".8" opacity=".65"/>
  </g>`;
}

// Original sparrow: one continuous round head/body, short pointed beak,
// oval wings and three tail feathers. No ears, whiskers, bow, or cat features.
function sparrow(t, whiteDragon = false) {
  const outline = whiteDragon ? t.blue : '#946c57';
  const body = whiteDragon ? '#f2f7ff' : '#d9b594';
  return `<g stroke="${outline}" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round">
    <path d="M39 89L32 108L46 101L53 110L58 92" fill="${whiteDragon ? '#bdd9ef' : '#9c6c51'}"/>
    <path d="M51 25Q74 22 77 48Q89 60 80 81Q72 99 48 97Q24 96 18 77Q10 59 24 45Q25 27 44 25Q39 20 43 19Q51 20 54 25" fill="${body}"/>
    <path d="M27 38Q33 23 51 26Q68 24 73 41Q61 34 52 38Q39 32 27 38Z" fill="${whiteDragon ? '#dbeaf8' : '#a8795d'}" stroke="none"/>
    <path d="M25 61Q48 48 70 61Q78 86 52 91Q29 91 25 61" fill="${whiteDragon ? '#fff' : '#fff5e4'}" stroke="none"/>
    <path d="M24 65Q38 60 42 72Q36 81 23 77M71 65Q61 63 59 74Q68 83 77 76" fill="${whiteDragon ? '#c4e0f3' : '#ad7e5d'}"/>
    <path d="M43 51L54 55L45 60Z" fill="#ecb04b" stroke="#bb8438" stroke-width="1.5"/>
    ${whiteDragon ? '' : '<path d="M43 63Q49 67 55 62Q54 73 48 71Z" fill="#79513f" stroke="none"/>'}
    <circle cx="34" cy="47" r="2.6" fill="#3b3e48" stroke="none"/><circle cx="64" cy="47" r="2.6" fill="#3b3e48" stroke="none"/>
    <path d="M37 96L35 101M64 95L66 101" stroke="#bb8438"/>
    ${t.id === 'D' ? '<ellipse cx="28" cy="57" rx="4" ry="2.5" fill="#ec9da8" stroke="none"/><ellipse cx="69" cy="57" rx="4" ry="2.5" fill="#ec9da8" stroke="none"/>' : ''}
  </g>`;
}

function faceBamboo1(t) {
  const traditionalBird = `<g stroke-linecap="round" stroke-linejoin="round">
    ${path('M21 104Q37 87 43 72M27 109L48 77', t.green, 3)}
    <path d="M32 71Q18 48 38 38Q38 19 56 20Q72 21 70 37L82 41L69 46Q70 65 59 77Q42 87 32 71Z" fill="${t.green}"/>
    <path d="M40 42Q61 46 58 68Q44 73 34 59" fill="${t.blue}" stroke="${t.face}" stroke-width="1.3"/>
    <path d="M42 48L54 58M39 55L50 65" stroke="${t.face}" stroke-width="1.4"/>
    <path d="M55 21Q65 22 68 33L54 32Z" fill="${t.red}"/><circle cx="61" cy="33" r="2" fill="${t.face}"/>
    ${path('M47 78L47 89L38 91M58 76L61 87L69 88M21 110Q40 104 75 108', t.red, 2.4)}
    ${path('M70 106L73 95L79 91', t.green, 2)}
  </g>`;
  return shell(t, engraved(t.id === 'D' ? sparrow(t) : traditionalBird), '一條');
}
function faceBamboo5(t) {
  return shell(t, engraved([[25, 34], [71, 34], [25, 89], [71, 89]].map(([x, y]) => bamboo(x, y, 32, t.green)).join('') + bamboo(48, 61, 32, t.red)), '五條');
}
function faceBamboo9(t) {
  return shell(t, engraved([26, 61, 96].map(y => [23, 48, 73].map((x, column) => bamboo(x, y, 24, column === 1 ? t.red : t.green)).join('')).join('')), '九條');
}
function faceEast(t) { return shell(t, engraved(glyph('東', t.blue, 15, 23, 66, 76)), '東'); }
function faceRed(t) { return shell(t, engraved(glyph('中', t.red, 17, 22, 62, 78)), '中'); }
function faceGreen(t) { return shell(t, engraved(glyph('發', t.green, 15, 22, 66, 78)), '發'); }
function faceWhite(t) {
  const frame = `<g fill="none" stroke="${t.blue}"><rect x="23" y="22" width="50" height="77" rx="2" stroke-width="3"/><rect x="28" y="27" width="40" height="67" rx="1" stroke-width="1.3"/>${path('M23 35L29 41M23 79L29 85M67 35L73 41M67 79L73 85', t.blue, 2)}</g>`;
  return shell(t, engraved(t.id === 'D' ? sparrow(t, true) : frame), '白');
}

function flowerLabel(name, number, color) {
  return `<text x="14" y="25" fill="${color}" font-family="${CJK_SERIF}" font-size="17" font-weight="600">${name}</text><text x="76" y="24" text-anchor="middle" fill="${color}" font-family="Georgia, serif" font-size="15">${number}</text>`;
}
function facePlum(t) {
  const blossom = (x, y, size) => `<g transform="translate(${x} ${y}) scale(${size})" fill="${t.id === 'D' ? 'none' : '#f8e7df'}" stroke="${t.red}" stroke-width="2">${[0, 72, 144, 216, 288].map(angle => `<ellipse cx="0" cy="-8" rx="5" ry="7" transform="rotate(${angle})"/>`).join('')}<circle r="3" fill="#d0a34c" stroke="none"/></g>`;
  return shell(t, flowerLabel('梅', 1, t.red) + engraved(path('M28 104Q48 79 46 45M40 83L68 62M37 88L24 69', t.id === 'D' ? '#b28b78' : '#79523c', 2.3) + blossom(45, 49, 1) + blossom(66, 68, .85) + blossom(25, 72, .7) + path('M38 98Q56 85 65 88Q51 101 38 98', t.green, 1.7)), '梅 1');
}
function faceOrchid(t) {
  const color = t.id === 'D' ? '#9874bc' : t.blue;
  const art = path('M41 105Q35 80 29 63Q53 76 48 105M47 105Q70 72 76 83Q63 101 47 105M43 103Q45 78 55 61', t.green, 2.2) + `<g transform="translate(55 54)" fill="none" stroke="${color}" stroke-width="2.1"><path d="M0 0Q-20-21-22-8Q-20 1 0 0Q-6-26 5-24Q16-17 0 0Q27-16 28-3Q19 8 0 0Q18 20 6 21Q-4 16 0 0Q-22 20-23 8Q-17 0 0 0Z"/><path d="M-5 1Q1-7 7 2L1 9Z" fill="#e9be67" stroke="#c79840" stroke-width="1.4"/></g>`;
  return shell(t, flowerLabel('蘭', 2, color) + engraved(art), '蘭 2');
}

function faceBack(t, landscape = false) {
  const w = landscape ? 132 : 96;
  const h = landscape ? 96 : 132;
  const motif = t.id === 'D'
    ? `<g transform="translate(${w / 2 - 11} ${h / 2 - 12})" fill="#fff0f6" opacity=".85"><path d="M9 2Q21 0 20 11L25 14L20 16Q22 25 11 25Q1 25 1 17Q0 10 6 8Q4 4 9 2ZM5 22L1 29L11 25Z"/></g>`
    : `<rect x="11" y="10" width="${w - 22}" height="${h - 29}" rx="5" fill="none" stroke="${t.backHi}" stroke-width="1.3" opacity=".75"/>`;
  return shell(t, motif, '牌背', landscape, true);
}

const FACES = [
  ['wan1', '一萬', faceWan1], ['wan5', '五萬', faceWan5], ['wan9', '九萬', faceWan9],
  ['dot1', '一筒', faceDot1], ['dot5', '五筒', faceDot5], ['dot9', '九筒', faceDot9],
  ['bamboo1', '一條', faceBamboo1], ['bamboo5', '五條', faceBamboo5], ['bamboo9', '九條', faceBamboo9],
  ['east', '東', faceEast], ['red', '中', faceRed], ['green', '發', faceGreen], ['white', '白', faceWhite],
  ['plum', '梅 1', facePlum], ['orchid', '蘭 2', faceOrchid], ['back', '牌背', faceBack],
];
const FACE_FUNCTIONS = Object.fromEntries([...FACES.map(([id, , fn]) => [id, fn]), ['dot2', faceDot2], ['dot3', faceDot3]]);
function tile(id, t, landscape = false) { return `<span class="tile" data-tile="${id}">${FACE_FUNCTIONS[id](t, landscape)}</span>`; }
const HAND = ['wan1', 'wan5', 'wan9', 'dot1', 'dot5', 'dot9', 'bamboo1', 'bamboo5', 'bamboo9', 'east', 'east', 'red', 'green', 'white', 'white', 'bamboo1'];
const RIVER = ['wan9', 'east', 'bamboo5', 'dot1', 'red', 'wan1', 'dot9', 'green', 'bamboo9', 'wan5', 'white', 'dot5'];

function renderTheme(t) {
  const section = document.createElement('section');
  section.className = `sample theme-${t.id}`;
  section.id = `sample-${t.id}`;
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
    <div class="face-sheet" id="faces-${t.id}" aria-label="${t.name}放大牌面總覽"><div class="sheet-heading"><span>牌面細節 / TILE STUDIES</span><span>15 FACES + 1 BACK</span></div><div class="face-row">${FACES.map(([id, label]) => `<div class="face-item">${tile(id, t)}<span class="face-name">${label}</span></div>`).join('')}</div></div>`;
  return section;
}

const samples = document.querySelector('#samples');
samples.append(...THEMES.map(renderTheme));
document.querySelectorAll('[data-view]').forEach(button => {
  button.addEventListener('click', () => {
    samples.classList.toggle('is-expanded', button.dataset.view === 'expanded');
    document.querySelectorAll('[data-view]').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
  });
});
