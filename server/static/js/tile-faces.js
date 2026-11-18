// Approved porcelain study artwork, shared by the app and full sample sheets.
// Engine indices stay 0–33; flowers use a separate, sample-only API.
const CJK_SERIF = "'BiauKai', 'DFKai-SB', 'KaiTi', 'Noto Serif TC', 'PMingLiU', 'MingLiU', serif";
export const NUMERAL_FACES = ['', '一', '二', '三', '四', '五', '六', '七', '八', '九'];
export const HONOR_FACES = ['東', '南', '西', '北', '白', '發', '中'];

export const TILE_THEMES = [
  { id: 'A', name: '瓷白', english: 'Porcelain', page: '#F3F5F7', felt: '#CCDCE5', feltHi: '#DDE8EE', feltLo: '#B8CAD5', rail: '#A9BBC8', railHi: '#D4DFE7', ink: '#203344', muted: '#475d6b', line: '#ccd7df', tableInk: '#425664', face: '#fbfaf2', edge: '#cfcabc', side: '#c8c2b1', foot: '#ada694', red: '#b72e2b', blue: '#254e83', green: '#176543', back: '#15583f', backEdge: '#0d3c2c', backHi: '#377b5f', note: '藍灰毛氈 · 象牙白牌 · 深綠牌背', detail: '沿用目前瓷白桌面色票' },
  { id: 'B', name: '茶室', english: 'Tea room', page: '#F7F2E8', felt: '#DDD5C4', feltHi: '#e9e2d3', feltLo: '#d0c6b2', rail: '#DFC6A6', railHi: '#efddc6', ink: '#4a4034', muted: '#6e5d49', line: '#dfd4c1', tableInk: '#655746', face: '#fff5df', edge: '#d5c6a8', side: '#d3c4a7', foot: '#b7a387', red: '#a73032', blue: '#334b70', green: '#38613f', back: '#802f45', backEdge: '#542334', backHi: '#ae5b6c', note: '米色織蓆 · 奶油牌 · 酒紅牌背', detail: '淡木色桌框與細緻交織紋理' },
  { id: 'C', name: '夜藍', english: 'Night blue', page: '#111e32', felt: '#203b60', feltHi: '#2a4a72', feltLo: '#172d4c', rail: '#0f2038', railHi: '#3e5471', ink: '#edf3ff', muted: '#b5c7df', line: '#3b506c', tableInk: '#c0d0e6', face: '#ffffff', edge: '#cbd5e2', side: '#c4cede', foot: '#9aaac2', red: '#bb2f3d', blue: '#204e9b', green: '#136447', back: '#2861b0', backEdge: '#173c77', backHi: '#6792d2', note: '深海軍藍毛氈 · 純白牌 · 藍色牌背', detail: '俐落的行動牌桌質感' },
  { id: 'D', name: '聯名風', english: 'Sparrow club', page: '#fff4f4', felt: '#f5dfe4', feltHi: '#fae9ed', feltLo: '#eed2da', rail: '#dba8b8', railHi: '#f5d6df', ink: '#673e50', muted: '#805465', line: '#e6c8d2', tableInk: '#875366', face: '#ffffff', edge: '#e1d7df', side: '#e3dce5', foot: '#c4b4c6', red: '#da385c', blue: '#428ac1', green: '#369866', back: '#bd6e9c', backEdge: '#935278', backHi: '#e8adce', note: '淡粉彩點 · 亮白牌 · 糖果粉牌背', detail: '原創圓麻雀與彩色花草刻線' },
];

// Only tile variables are installed here. Table palettes remain the app's concern.
// A is the default; setting data-table-theme on <html> updates existing SVGs.
if (!document.documentElement.hasAttribute('data-table-theme')) {
  document.documentElement.dataset.tableTheme = 'A';
}
const themeStyle = document.createElement('style');
themeStyle.dataset.tileThemes = '';
themeStyle.textContent = TILE_THEMES.map(t => {
  const colors = {
    bone: t.face, 'bone-edge': t.edge, 'tile-side': t.side, 'tile-foot': t.foot,
    'tile-ink': t.id === 'D' ? '#6276b8' : '#202d40', cinnabar: t.red,
    'tile-blue': t.blue, 'tile-green': t.green, 'tile-back': t.back,
    'tile-back-edge': t.backEdge, 'tile-back-highlight': t.backHi,
    'tile-blossom': t.id === 'D' ? 'none' : '#f8e7df',
    'tile-branch': t.id === 'D' ? '#b28b78' : '#79523c',
    'tile-orchid': t.id === 'D' ? '#9874bc' : t.blue,
    'tile-traditional-display': t.id === 'D' ? 'none' : 'inline',
    'tile-club-display': t.id === 'D' ? 'inline' : 'none',
  };
  const selector = `${t.id === 'A' ? ':root, ' : ''}[data-table-theme="${t.id}"]`;
  return `${selector} {${Object.entries(colors).map(([key, value]) => `--${key}:${value};`).join('')}}`;
}).join('\n');
document.head.append(themeStyle);

const PIGMENT = Object.freeze({
  face: 'var(--bone)', edge: 'var(--bone-edge)', side: 'var(--tile-side)',
  foot: 'var(--tile-foot)', ink: 'var(--tile-ink)', red: 'var(--cinnabar)',
  blue: 'var(--tile-blue)', green: 'var(--tile-green)', back: 'var(--tile-back)',
  backEdge: 'var(--tile-back-edge)', backHi: 'var(--tile-back-highlight)',
  blossom: 'var(--tile-blossom)', branch: 'var(--tile-branch)', orchid: 'var(--tile-orchid)',
});

function variants(traditional, club) {
  return `<g style="display:var(--tile-traditional-display)">${traditional}</g><g style="display:var(--tile-club-display)">${club}</g>`;
}

// Normalized 100 × 100 pen strokes, deliberately cut like engraved tile marks.
const GLYPHS = {
  '一': 'M12 53 Q48 50 88 49',
  '二': 'M18 30L82 28 M10 76L90 74',
  '三': 'M18 16L83 15 M25 48L76 47 M10 84L90 82',
  '四': 'M13 17H87V86H13Z M37 18Q39 55 21 61 M61 18V55Q61 63 72 61L83 59',
  '六': 'M45 7L55 20 M12 35L88 34 M35 52Q29 75 12 89 M65 52L88 88',
  '七': 'M10 43L89 32 M45 8L43 79Q42 90 57 90L83 88L88 73',
  '八': 'M35 20Q30 65 9 89 M63 17Q66 61 91 88',
  '五': 'M18 14 L83 14 M50 15 L39 83 M20 44 L71 44 L67 83 M11 85 L90 85',
  '九': 'M16 37 L64 34 L59 77 Q57 88 70 88 L87 87 L91 72 M42 12 Q47 71 13 92',
  '萬': 'M11 15 L90 15 M32 6 L32 27 M69 6 L69 27 M24 33 L77 33 L77 58 L24 58 Z M25 45 L76 45 M50 32 L50 80 M15 72 L15 96 M15 72 L86 72 L86 94 L74 91 M33 82 L66 80 L61 74',
  '東': 'M10 16 L90 16 M23 30 L78 30 L78 60 L23 60 Z M24 45 L77 45 M50 6 L50 94 M48 60 Q32 81 9 87 M53 61 Q69 79 91 85',
  '南': 'M9 20H91 M50 6V34 M17 95V35H83V94L72 91 M33 44L39 54 M66 44L60 54 M29 60H71 M28 76H72 M50 56V92',
  '西': 'M9 14H91 M16 34H84V89H16Z M39 15V41Q39 61 25 66 M61 15V57Q61 63 72 62L81 59 M17 77H83',
  '北': 'M35 8V87 M10 35H35 M8 84L35 72 M62 8V79Q62 91 76 89L90 87L93 72 M63 45L86 27',
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
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" class="tile-art ${back ? 'tile-back-art' : 'tile-face-art'}" aria-hidden="true" focusable="false">
    <rect x="3" y="7" width="${w - 6}" height="${h - 9}" rx="10" fill="${t.side}"/>
    <path d="M4 ${h - 20}H${w - 4}v8q0 8-8 8H12q-8 0-8-8Z" fill="${t.foot}"/>
    <rect x="3" y="2" width="${w - 6}" height="${h - 12}" rx="9" fill="${face}" stroke="${back ? t.backEdge : t.edge}" stroke-width="1.3"/>
    <path d="M13 6H${w - 13}Q${w - 7} 6 ${w - 7} 13" fill="none" stroke="${back ? t.backHi : '#fff'}" stroke-width="2.5" opacity=".9"/>
    ${art}
    ${!back ? '<path style="display:var(--tile-club-display)" d="M9 14v87" stroke="#fff" stroke-width="3" opacity=".85"/>' : ''}
  </svg>`;
}

function wan(t, number) {
  return shell(t, engraved(glyph(number, t.ink, 20, 13, 56, 38) + glyph('萬', t.red, 21, 59, 54, 49)), `${number}萬`);
}
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
function sparrow(t) {
  const outline = '#946c57';
  const body = '#d9b594';
  return `<g stroke="${outline}" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round">
    <path d="M39 89L32 108L46 101L53 110L58 92" fill="${'#9c6c51'}"/>
    <path d="M51 25Q74 22 77 48Q89 60 80 81Q72 99 48 97Q24 96 18 77Q10 59 24 45Q25 27 44 25Q39 20 43 19Q51 20 54 25" fill="${body}"/>
    <path d="M27 38Q33 23 51 26Q68 24 73 41Q61 34 52 38Q39 32 27 38Z" fill="${'#a8795d'}" stroke="none"/>
    <path d="M25 61Q48 48 70 61Q78 86 52 91Q29 91 25 61" fill="${'#fff5e4'}" stroke="none"/>
    <path d="M24 65Q38 60 42 72Q36 81 23 77M71 65Q61 63 59 74Q68 83 77 76" fill="${'#ad7e5d'}"/>
    <path d="M43 51L54 55L45 60Z" fill="#ecb04b" stroke="#bb8438" stroke-width="1.5"/>
    <path d="M43 63Q49 67 55 62Q54 73 48 71Z" fill="#79513f" stroke="none"/>
    <circle cx="34" cy="47" r="2.6" fill="#3b3e48" stroke="none"/><circle cx="64" cy="47" r="2.6" fill="#3b3e48" stroke="none"/>
    <path d="M37 96L35 101M64 95L66 101" stroke="#bb8438"/>
    <ellipse cx="28" cy="57" rx="4" ry="2.5" fill="#ec9da8" stroke="none"/><ellipse cx="69" cy="57" rx="4" ry="2.5" fill="#ec9da8" stroke="none"/>
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
  return shell(t, engraved(variants(traditionalBird, sparrow(t))), '一條');
}
function faceBamboo5(t) {
  return shell(t, engraved([[25, 34], [71, 34], [25, 89], [71, 89]].map(([x, y]) => bamboo(x, y, 32, t.green)).join('') + bamboo(48, 61, 32, t.red)), '五條');
}
function faceBamboo9(t) {
  return shell(t, engraved([26, 61, 96].map(y => [23, 48, 73].map((x, column) => bamboo(x, y, 24, column === 1 ? t.red : t.green)).join('')).join('')), '九條');
}
function faceRed(t) { return shell(t, engraved(glyph('中', t.red, 17, 22, 62, 78)), '中'); }
function faceGreen(t) { return shell(t, engraved(glyph('發', t.green, 15, 22, 66, 78)), '發'); }
function faceWhite(t) {
  const frame = `<g fill="none" stroke="${t.blue}"><rect x="23" y="22" width="50" height="77" rx="2" stroke-width="3"/><rect x="28" y="27" width="40" height="67" rx="1" stroke-width="1.3"/>${path('M23 35L29 41M23 79L29 85M67 35L73 41M67 79L73 85', t.blue, 2)}</g>`;
  return shell(t, engraved(frame), '白');
}

function flowerLabel(name, number, color) {
  return `<text x="14" y="25" fill="${color}" font-family="${CJK_SERIF}" font-size="17" font-weight="600">${name}</text><text x="76" y="24" text-anchor="middle" fill="${color}" font-family="Georgia, serif" font-size="15">${number}</text>`;
}
function facePlum(t) {
  const blossom = (x, y, size) => `<g transform="translate(${x} ${y}) scale(${size})" fill="${t.blossom}" stroke="${t.red}" stroke-width="2">${[0, 72, 144, 216, 288].map(angle => `<ellipse cx="0" cy="-8" rx="5" ry="7" transform="rotate(${angle})"/>`).join('')}<circle r="3" fill="#d0a34c" stroke="none"/></g>`;
  return shell(t, flowerLabel('梅', 1, t.red) + engraved(path('M28 104Q48 79 46 45M40 83L68 62M37 88L24 69', t.branch, 2.3) + blossom(45, 49, 1) + blossom(66, 68, .85) + blossom(25, 72, .7) + path('M38 98Q56 85 65 88Q51 101 38 98', t.green, 1.7)), '梅 1');
}
function faceOrchid(t) {
  const color = t.orchid;
  const art = path('M41 105Q35 80 29 63Q53 76 48 105M47 105Q70 72 76 83Q63 101 47 105M43 103Q45 78 55 61', t.green, 2.2) + `<g transform="translate(55 54)" fill="none" stroke="${color}" stroke-width="2.1"><path d="M0 0Q-20-21-22-8Q-20 1 0 0Q-6-26 5-24Q16-17 0 0Q27-16 28-3Q19 8 0 0Q18 20 6 21Q-4 16 0 0Q-22 20-23 8Q-17 0 0 0Z"/><path d="M-5 1Q1-7 7 2L1 9Z" fill="#e9be67" stroke="#c79840" stroke-width="1.4"/></g>`;
  return shell(t, flowerLabel('蘭', 2, color) + engraved(art), '蘭 2');
}

function faceBack(t, landscape = false) {
  const w = landscape ? 132 : 96;
  const h = landscape ? 96 : 132;
  const club = `<g transform="translate(${w / 2 - 11} ${h / 2 - 12})" fill="#fff0f6" opacity=".85"><path d="M9 2Q21 0 20 11L25 14L20 16Q22 25 11 25Q1 25 1 17Q0 10 6 8Q4 4 9 2ZM5 22L1 29L11 25Z"/></g>`;
  const traditional = `<rect x="11" y="10" width="${w - 22}" height="${h - 29}" rx="5" fill="none" stroke="${t.backHi}" stroke-width="1.3" opacity=".75"/>`;
  return shell(t, variants(traditional, club), '牌背', landscape, true);
}

// Portrait coordinates preserve the approved 1/5/9 artwork. Other ranks use
// conventional real-tile arrangements, with enough space between engraved cuts.
export const DOT_LAYOUTS = Object.freeze({
  2: [[48, 34], [48, 88]],
  3: [[28, 29], [48, 61], [68, 93]],
  4: [[25, 30], [71, 30], [25, 92], [71, 92]],
  5: [[25, 30], [71, 30], [48, 61], [25, 92], [71, 92]],
  6: [[27, 28], [69, 28], [27, 61], [69, 61], [27, 94], [69, 94]],
  7: [[25, 22], [48, 37], [71, 52], [27, 77], [69, 77], [27, 102], [69, 102]],
  8: [22, 48, 74, 100].flatMap(y => [[27, y], [69, y]]),
  9: [28, 61, 94].flatMap(y => [24, 48, 72].map(x => [x, y])),
});
export const BAMBOO_LAYOUTS = Object.freeze({
  2: [[48, 34], [48, 89]],
  3: [[48, 30], [25, 89], [71, 89]],
  4: [[25, 34], [71, 34], [25, 89], [71, 89]],
  5: [[25, 34], [71, 34], [48, 61], [25, 89], [71, 89]],
  6: [26, 61, 96].flatMap(y => [27, 69].map(x => [x, y])),
  7: [[48, 23], ...[57, 96].flatMap(y => [23, 48, 73].map(x => [x, y]))],
  8: [35, 89].flatMap(y => [22, 39, 57, 74].map((x, i) => [x, y, i % 2 ? -18 : 18])),
  9: [26, 61, 96].flatMap(y => [23, 48, 73].map(x => [x, y])),
});

function dots(t, rank) {
  if (rank === 1) return faceDot1(t);
  if (rank === 2) return faceDot2(t);
  if (rank === 3) return faceDot3(t);
  if (rank === 5) return faceDot5(t);
  if (rank === 9) return faceDot9(t);
  const radius = rank >= 7 ? 9 : rank === 6 ? 11 : 12;
  return shell(t, engraved(DOT_LAYOUTS[rank].map(([x, y], i) =>
    pip(x, y, radius, rank === 7 && i >= 3 ? t.red : t.blue)).join('')), `${NUMERAL_FACES[rank]}筒`);
}
function sticks(t, rank) {
  if (rank === 1) return faceBamboo1(t);
  if (rank === 5) return faceBamboo5(t);
  if (rank === 9) return faceBamboo9(t);
  const length = rank >= 6 ? 24 : 32;
  return shell(t, engraved(BAMBOO_LAYOUTS[rank].map(([x, y, angle = 0], i) =>
    `<g transform="rotate(${angle} ${x} ${y})">${bamboo(x, y, length, rank === 7 && i === 0 ? t.red : t.green)}</g>`).join('')), `${NUMERAL_FACES[rank]}條`);
}

export const FLOWER_FACES = ['春', '夏', '秋', '冬', '梅', '蘭', '菊', '竹'];
function flower(t, name) {
  if (name === '梅') return facePlum(t);
  if (name === '蘭') return faceOrchid(t);
  let art;
  const color = ['夏', '秋', '菊'].includes(name) ? t.red : t.green;
  if (name === '春') {
    art = path('M47 108Q50 80 46 42 M47 77Q23 80 23 56Q46 53 47 77 M48 63Q69 65 74 42Q50 40 48 63 M46 96Q65 96 75 78Q54 76 46 96', t.green, 2.4);
  } else if (name === '夏') {
    art = path('M48 105V77 M48 80Q23 77 19 55Q33 54 48 70Q39 49 48 37Q60 49 48 70Q63 53 78 55Q74 77 48 80Z', t.red, 2.2)
      + path('M21 103Q39 86 78 100Q58 112 21 103Z M48 104L68 100', t.green, 2);
  } else if (name === '秋') {
    art = path('M47 108L50 67 M50 91L25 77L32 69L18 56L38 59L39 41L50 53L64 34L65 58L82 53L74 70L81 76L50 91Z M50 88L50 58 M50 81L34 68 M50 76L67 64', t.red, 2.2);
  } else if (name === '冬') {
    art = path('M42 108L54 47 M47 90L23 71 M49 80L75 62 M52 63L34 49', t.branch, 2.4)
      + [ [23, 68], [73, 60], [35, 46], [55, 43] ].map(([x,y]) => path(`M${x-12} ${y+6}L${x} ${y-7}L${x+12} ${y+6} M${x-11} ${y+1}L${x+11} ${y+1} M${x} ${y-7}V${y+8}`, t.green, 1.8)).join('');
  } else if (name === '菊') {
    art = path('M46 107L50 67 M48 91Q24 76 23 89Q30 101 46 99 M47 101Q65 80 76 88Q68 102 47 101', t.green, 2)
      + `<g transform="translate(50 56)" fill="none" stroke="${t.red}" stroke-width="1.7">${Array.from({length: 12}, (_, i) => `<ellipse cx="0" cy="-12" rx="4" ry="13" transform="rotate(${i * 30})"/>`).join('')}<circle r="6" fill="#e9be67"/></g>`;
  } else {
    art = bamboo(42, 76, 62, t.green) + bamboo(64, 82, 46, t.green)
      + path('M42 67Q22 40 20 58Q26 70 42 67 M43 53Q57 32 66 39Q59 54 43 53 M64 85Q77 61 82 69Q81 85 64 85 M41 94Q24 78 20 86Q27 99 41 94', t.green, 2);
  }
  const number = FLOWER_FACES.indexOf(name) % 4 + 1;
  return shell(t, flowerLabel(name, number, color) + engraved(art), `${name} ${number}`);
}

function svgNode(markup) {
  const template = document.createElement('template');
  template.innerHTML = markup.trim();
  return template.content.firstElementChild;
}

export function tileFaceSvg(tile) {
  if (!Number.isInteger(tile) || tile < 0 || tile > 33) throw new RangeError('Tile index must be 0–33');
  const t = PIGMENT;
  if (tile < 9) return svgNode(wan(t, NUMERAL_FACES[tile + 1]));
  if (tile < 18) return svgNode(dots(t, tile - 8));
  if (tile < 27) return svgNode(sticks(t, tile - 17));
  if (tile === 31) return svgNode(faceWhite(t));
  if (tile === 32) return svgNode(faceGreen(t));
  if (tile === 33) return svgNode(faceRed(t));
  return svgNode(shell(t, engraved(glyph(HONOR_FACES[tile - 27], t.blue, 15, 23, 66, 76)), HONOR_FACES[tile - 27]));
}

export function flowerFaceSvg(name) {
  if (!FLOWER_FACES.includes(name)) throw new RangeError('Unknown flower');
  return svgNode(flower(PIGMENT, name));
}

// Landscape backs have native geometry, preserving existing side-seat orientation.
export function tileBackSvg(orientation = 'portrait') {
  return svgNode(faceBack(PIGMENT, orientation === 'landscape'));
}
