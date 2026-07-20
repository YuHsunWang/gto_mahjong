// Tile faces drawn as SVG from extracted Noto Serif TC outlines and pip layouts,
// matching the engine's 0-33 tile indexing.

import { TILE_GLYPHS } from './tile-faces.js';

const NUMERALS = '一二三四五六七八九';
const SUIT_CHARS = '萬筒條';
const HONOR_FACES = ['東', '南', '西', '北', '白', '發', '中'];

const HONOR_COLORS = ['var(--wind)', 'var(--wind)', 'var(--wind)', 'var(--wind)', null, 'var(--green)', 'var(--red)'];

const SVG_NS = 'http://www.w3.org/2000/svg';

// 筒 pip layouts: [x, y, r] per dot on a 30×42 face.
const DOT_LAYOUTS = [
  [[15, 21, 9.5]],
  [[15, 11, 5.5], [15, 31, 5.5]],
  [[7.5, 9, 4.5], [15, 21, 4.5], [22.5, 33, 4.5]],
  [[9, 11, 4.5], [21, 11, 4.5], [9, 31, 4.5], [21, 31, 4.5]],
  [[8, 10, 4], [22, 10, 4], [15, 21, 4], [8, 32, 4], [22, 32, 4]],
  [[9, 9, 3.4], [21, 9, 3.4], [9, 21, 3.4], [21, 21, 3.4], [9, 33, 3.4], [21, 33, 3.4]],
  [[6, 7, 3.2], [15, 10, 3.2], [24, 13, 3.2], [9, 25, 3.2], [21, 25, 3.2], [9, 35, 3.2], [21, 35, 3.2]],
  [[9, 7, 3.2], [21, 7, 3.2], [9, 16, 3.2], [21, 16, 3.2], [9, 25, 3.2], [21, 25, 3.2], [9, 34, 3.2], [21, 34, 3.2]],
  [[7.5, 9, 3.2], [15, 9, 3.2], [22.5, 9, 3.2], [7.5, 21, 3.2], [15, 21, 3.2], [22.5, 21, 3.2], [7.5, 33, 3.2], [15, 33, 3.2], [22.5, 33, 3.2]],
];

// 條 stick layouts: [x, y, h] per bamboo stick (centre + height).
const STICK_LAYOUTS = [
  [[15, 21, 18]],
  [[15, 11, 10], [15, 31, 10]],
  [[15, 10, 10], [9, 32, 10], [21, 32, 10]],
  [[9, 11, 10], [21, 11, 10], [9, 31, 10], [21, 31, 10]],
  [[9, 11, 10], [21, 11, 10], [15, 21, 10], [9, 31, 10], [21, 31, 10]],
  [[7.5, 11, 10], [15, 11, 10], [22.5, 11, 10], [7.5, 31, 10], [15, 31, 10], [22.5, 31, 10]],
  [[15, 8, 9], [7.5, 21, 9], [15, 21, 9], [22.5, 21, 9], [7.5, 34, 9], [15, 34, 9], [22.5, 34, 9]],
  [[6, 11, 10], [12, 11, 10], [18, 11, 10], [24, 11, 10], [6, 31, 10], [12, 31, 10], [18, 31, 10], [24, 31, 10]],
  [[7.5, 9, 9], [15, 9, 9], [22.5, 9, 9], [7.5, 21, 9], [15, 21, 9], [22.5, 21, 9], [7.5, 33, 9], [15, 33, 9], [22.5, 33, 9]],
];

function suitFaceSvg(suit, rank) {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('viewBox', '0 0 30 42');
  svg.classList.add('face');
  const layout = (suit === 1 ? DOT_LAYOUTS : STICK_LAYOUTS)[rank - 1];
  const centreIndex = rank === 5 ? layout.findIndex(([x, y]) => x === 15 && y === 21) : -1;
  layout.forEach(([x, y, size], index) => {
    // The centre pip of a 5 is red, as on real tiles.
    const fill = index === centreIndex ? 'var(--red)' : (suit === 1 ? 'var(--blue)' : 'var(--green)');
    if (suit === 1) {
      const dot = document.createElementNS(SVG_NS, 'circle');
      dot.setAttribute('cx', x);
      dot.setAttribute('cy', y);
      dot.setAttribute('r', size);
      dot.setAttribute('fill', fill);
      if (rank === 1) {
        dot.setAttribute('stroke', 'var(--wind)');
        dot.setAttribute('stroke-width', '2');
        dot.setAttribute('fill', 'var(--blue)');
      }
      svg.append(dot);
    } else {
      const stick = document.createElementNS(SVG_NS, 'rect');
      stick.setAttribute('x', x - 1.7);
      stick.setAttribute('y', y - size / 2);
      stick.setAttribute('width', 3.4);
      stick.setAttribute('height', size);
      stick.setAttribute('rx', 1.6);
      stick.setAttribute('fill', fill);
      svg.append(stick);
      // bamboo node notch
      const node = document.createElementNS(SVG_NS, 'rect');
      node.setAttribute('x', x - 2.3);
      node.setAttribute('y', y - 0.9);
      node.setAttribute('width', 4.6);
      node.setAttribute('height', 1.8);
      node.setAttribute('rx', 0.9);
      node.setAttribute('fill', fill);
      svg.append(node);
    }
  });
  return svg;
}

function glyphPath(svg, glyph, fill, transform = null) {
  const path = document.createElementNS(SVG_NS, 'path');
  path.setAttribute('d', TILE_GLYPHS[glyph].path);
  path.setAttribute('fill', fill);
  if (transform) path.setAttribute('transform', transform);
  svg.append(path);
}

function honorFaceSvg(glyph, fill) {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('viewBox', '0 0 1000 1200');
  svg.classList.add('face');
  glyphPath(svg, glyph, fill, 'translate(0 100)');
  return svg;
}

function manFaceSvg(rank) {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('viewBox', '0 0 1000 1600');
  svg.classList.add('face');
  glyphPath(svg, NUMERALS[rank - 1], 'var(--red)', 'translate(100 40) scale(.8)');
  glyphPath(svg, SUIT_CHARS[0], 'var(--blue)', 'translate(100 760) scale(.8)');
  return svg;
}

function whiteDragonFaceSvg() {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('viewBox', '0 0 30 42');
  svg.classList.add('face');
  const frame = document.createElementNS(SVG_NS, 'rect');
  frame.setAttribute('x', '4.5');
  frame.setAttribute('y', '5');
  frame.setAttribute('width', '21');
  frame.setAttribute('height', '32');
  frame.setAttribute('rx', '2.5');
  frame.setAttribute('fill', 'none');
  frame.setAttribute('stroke', 'var(--blue)');
  frame.setAttribute('stroke-width', '1.25');
  svg.append(frame);
  return svg;
}

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
  if (tile === 31) {
    el.append(whiteDragonFaceSvg());
    return el;
  }
  if (tile < 27) {
    const suit = Math.floor(tile / 9);
    const rank = (tile % 9) + 1;
    el.append(suit === 0 ? manFaceSvg(rank) : suitFaceSvg(suit, rank));
  } else {
    el.append(honorFaceSvg(HONOR_FACES[tile - 27], HONOR_COLORS[tile - 27]));
  }
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
