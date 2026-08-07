// Inline SVG tile components, preserving the engine's 0-33 tile contract.

import { HONOR_FACES, NUMERAL_FACES, tileBackSvg, tileFaceSvg } from './tile-faces.js';

const SUIT_CHARS = '萬筒條';

export function faceText(tile) {
  if (tile < 27) return NUMERAL_FACES[(tile % 9) + 1] + SUIT_CHARS[Math.floor(tile / 9)];
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
  el.setAttribute('aria-label', faceText(tile));
  if (as === 'button') {
    el.type = 'button';
  } else {
    el.setAttribute('role', 'img');
  }
  el.append(tileFaceSvg(tile));
  return el;
}

export function tileBackEl({ orientation = 'portrait', size = 'sm', classes = [] } = {}) {
  const el = document.createElement('div');
  el.className = ['tile', 'tile-back', size, orientation, ...classes].join(' ');
  el.setAttribute('role', 'img');
  el.setAttribute('aria-label', '覆蓋的牌');
  el.append(tileBackSvg(orientation));
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
