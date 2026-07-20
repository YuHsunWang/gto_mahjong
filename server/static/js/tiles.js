// Tile faces drawn as DOM elements from the current design (Noto Serif TC
// faces on bone), matching the engine's 0-33 tile indexing.

const NUMERALS = '一二三四五六七八九';
const SUIT_CHARS = '萬筒條';
const HONOR_FACES = ['東', '南', '西', '北', '白', '發', '中'];

const SUIT_COLORS = {
  0: ['var(--red)', 'var(--blue)'],   // 萬
  1: ['var(--blue)', 'var(--blue)'],  // 筒
  2: ['var(--green)', 'var(--green)'], // 條
};

const HONOR_COLORS = ['var(--wind)', 'var(--wind)', 'var(--wind)', 'var(--wind)', 'var(--bone-shadow)', 'var(--green)', 'var(--red)'];

export function faceText(tile) {
  if (tile < 27) return NUMERALS[tile % 9] + SUIT_CHARS[Math.floor(tile / 9)];
  return HONOR_FACES[tile - 27];
}

export function compactText(tile) {
  if (tile < 27) return `${(tile % 9) + 1}${'mps'[Math.floor(tile / 9)]}`;
  return `${tile - 26}z`;
}

// size: 'lg' | 'sm'; classes: extra class names; as: 'div' | 'button'
export function tileEl(tile, { size = 'lg', classes = [], as = 'div' } = {}) {
  const el = document.createElement(as);
  el.className = ['tile', size, ...classes].join(' ');
  el.title = faceText(tile);
  if (as === 'button') el.type = 'button';
  if (tile === 31) return el; // white dragon: blank face like the real tile
  if (tile < 27) {
    const [topColor, bottomColor] = SUIT_COLORS[Math.floor(tile / 9)];
    const top = document.createElement('span');
    top.style.color = topColor;
    top.textContent = NUMERALS[tile % 9];
    const bottom = document.createElement('span');
    bottom.style.color = bottomColor;
    bottom.textContent = SUIT_CHARS[Math.floor(tile / 9)];
    el.append(top, bottom);
  } else {
    const face = document.createElement('span');
    face.style.color = HONOR_COLORS[tile - 27];
    face.textContent = HONOR_FACES[tile - 27];
    el.append(face);
  }
  return el;
}

export function tileBackEl() {
  const el = document.createElement('div');
  el.className = 'tile-back';
  return el;
}

// Expand a 34-count array into a sorted list of tile indices.
export function countsToTiles(counts) {
  const tiles = [];
  counts.forEach((count, tile) => {
    for (let i = 0; i < count; i += 1) tiles.push(tile);
  });
  return tiles;
}

// Parse compact notation ("123m55z") into tile indices; returns null on junk.
// Client-side preview only — the server re-validates on submit.
export function parseCompact(text) {
  const tiles = [];
  const pattern = /(\d+)([mpsz])/g;
  const cleaned = text.trim();
  if (!cleaned) return [];
  let consumed = 0;
  let match;
  while ((match = pattern.exec(cleaned)) !== null) {
    consumed += match[0].length;
    const offset = { m: 0, p: 9, s: 18, z: 27 }[match[2]];
    for (const digit of match[1]) {
      const rank = Number(digit);
      if (rank < 1 || (match[2] === 'z' && rank > 7) || rank > 9) return null;
      tiles.push(offset + rank - 1);
    }
  }
  return consumed === cleaned.replace(/\s/g, '').length ? tiles : null;
}
