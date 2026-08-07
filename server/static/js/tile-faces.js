// Original inline SVG tile artwork for the 0-33 engine index contract.
// Faces use only geometry and local system-font glyphs; no remote assets.

const SVG_NS = 'http://www.w3.org/2000/svg';

export const FACE_TOKENS = Object.freeze({
  ink: 'var(--tile-ink, #1d2430)',
  red: 'var(--cinnabar, #c2352f)',
  blue: 'var(--tile-blue, #28599c)',
  green: 'var(--tile-green, #1f7a52)',
  bone: 'var(--bone, #fffdf2)',
  boneEdge: 'var(--bone-edge, #d5cdb8)',
  tileSide: 'var(--tile-side, #b9ad95)',
  tileFoot: 'var(--tile-foot, #a2957c)',
  back: 'var(--tile-back, #2f7f63)',
  backEdge: 'var(--tile-back-edge, #1d5442)',
  backHighlight: 'var(--tile-back-highlight, #43a07f)',
});

export const NUMERAL_FACES = ['', '一', '二', '三', '四', '五', '六', '七', '八', '九'];
export const HONOR_FACES = ['東', '南', '西', '北', '白', '發', '中'];

// [x, y, radius] in the shared 48 x 66 portrait viewBox.
export const DOT_LAYOUTS = Object.freeze({
  1: [[24, 30, 8]],
  2: [[24, 21, 5], [24, 40, 5]],
  3: [[16, 18, 4], [24, 30, 4], [32, 42, 4]],
  4: [[16, 20, 4], [32, 20, 4], [16, 40, 4], [32, 40, 4]],
  5: [[15, 18, 3.8], [33, 18, 3.8], [24, 30, 4.2], [15, 42, 3.8], [33, 42, 3.8]],
  6: [[16, 17, 3.5], [32, 17, 3.5], [16, 30, 3.5], [32, 30, 3.5], [16, 43, 3.5], [32, 43, 3.5]],
  7: [[14, 16, 3.2], [24, 16, 3.2], [34, 16, 3.2], [17, 29, 3.2], [31, 29, 3.2], [17, 42, 3.2], [31, 42, 3.2]],
  8: [[16, 14, 3.1], [32, 14, 3.1], [16, 25, 3.1], [32, 25, 3.1], [16, 36, 3.1], [32, 36, 3.1], [16, 47, 3.1], [32, 47, 3.1]],
  9: [[14, 16, 3], [24, 16, 3], [34, 16, 3], [14, 30, 3], [24, 30, 3], [34, 30, 3], [14, 44, 3], [24, 44, 3], [34, 44, 3]],
});

// Bamboo uses the same rank layouts, rendered as leaf-and-stalk motifs.
export const BAMBOO_LAYOUTS = DOT_LAYOUTS;

function svgEl(name, attrs = {}) {
  const node = document.createElementNS(SVG_NS, name);
  Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
  return node;
}

function tileSvg(width, height, className) {
  const svg = svgEl('svg', {
    viewBox: `0 0 ${width} ${height}`,
    class: className,
    'aria-hidden': 'true',
    focusable: 'false',
  });
  return svg;
}

function appendBody(svg) {
  svg.append(
    svgEl('rect', { x: 3, y: 5, width: 42, height: 57, rx: 5, fill: FACE_TOKENS.tileSide }),
    svgEl('path', { d: 'M4 53h40v5a4 4 0 0 1-4 4H8a4 4 0 0 1-4-4z', fill: FACE_TOKENS.tileFoot }),
    svgEl('rect', { x: 3, y: 2, width: 42, height: 56, rx: 5, fill: FACE_TOKENS.bone, stroke: FACE_TOKENS.boneEdge }),
    svgEl('path', { d: 'M7 6h34', stroke: '#fff', 'stroke-width': 2, 'stroke-linecap': 'round', opacity: .75 }),
  );
}

function appendText(svg, { x, y, size, fill, content }) {
  const text = svgEl('text', {
    x,
    y,
    fill,
    'text-anchor': 'middle',
    'font-size': size,
    'font-weight': 800,
    'font-family': '"PMingLiU", "MingLiU", "Microsoft JhengHei", serif',
  });
  text.textContent = content;
  svg.append(text);
}

function appendPip(svg, x, y, radius, color, redCentre = false) {
  svg.append(
    svgEl('circle', { cx: x, cy: y, r: radius + 1.2, fill: 'none', stroke: color, 'stroke-width': 1.2 }),
    svgEl('circle', { cx: x, cy: y, r: radius * .45, fill: redCentre ? FACE_TOKENS.red : color }),
  );
}

function appendBamboo(svg, x, y, radius, color) {
  svg.append(
    svgEl('path', {
      d: `M${x} ${y - radius - 1}q4 3 0 ${radius + 1}q-4-3 0-${radius + 1}`,
      fill: color,
    }),
    svgEl('rect', { x: x - 1.2, y: y - 1, width: 2.4, height: radius + 3, rx: 1.2, fill: color }),
  );
}

function appendFace(svg, tile) {
  if (tile < 27) {
    const suit = Math.floor(tile / 9);
    const rank = (tile % 9) + 1;
    if (suit === 0) {
      appendText(svg, { x: 24, y: 27, size: 23, fill: FACE_TOKENS.ink, content: NUMERAL_FACES[rank] });
      appendText(svg, { x: 24, y: 51, size: 22, fill: FACE_TOKENS.red, content: '萬' });
      return;
    }
    const layout = suit === 1 ? DOT_LAYOUTS[rank] : BAMBOO_LAYOUTS[rank];
    layout.forEach(([x, y, radius], index) => {
      if (suit === 1) {
        appendPip(svg, x, y, radius, FACE_TOKENS.blue, rank === 5 && index === 2);
      } else {
        appendBamboo(svg, x, y, radius, rank === 5 && index === 2 ? FACE_TOKENS.red : FACE_TOKENS.green);
      }
    });
    return;
  }

  if (tile === 31) {
    svg.append(
      svgEl('rect', { x: 11, y: 12, width: 26, height: 36, rx: 3, fill: 'none', stroke: FACE_TOKENS.blue, 'stroke-width': 2 }),
      svgEl('rect', { x: 15, y: 16, width: 18, height: 28, rx: 2, fill: 'none', stroke: FACE_TOKENS.blue, 'stroke-width': 1, opacity: .6 }),
    );
    return;
  }

  const honor = HONOR_FACES[tile - 27];
  const color = tile === 33 ? FACE_TOKENS.red : tile === 32 ? FACE_TOKENS.green : FACE_TOKENS.blue;
  appendText(svg, { x: 24, y: 43, size: 29, fill: color, content: honor });
}

export function tileFaceSvg(tile) {
  const svg = tileSvg(48, 66, 'tile-art tile-face-art');
  appendBody(svg);
  appendFace(svg, tile);
  return svg;
}

// A landscape back gets its own 66 x 48 geometry. It is not a rotated or
// compressed portrait tile, so side-seat backs retain their proportions.
export function tileBackSvg(orientation = 'portrait') {
  const landscape = orientation === 'landscape';
  const width = landscape ? 66 : 48;
  const height = landscape ? 48 : 66;
  const svg = tileSvg(width, height, 'tile-art tile-back-art');
  svg.append(
    svgEl('rect', { x: 2, y: 2, width: width - 4, height: height - 4, rx: 5, fill: FACE_TOKENS.back, stroke: FACE_TOKENS.backEdge }),
    svgEl('rect', { x: 6, y: 6, width: width - 12, height: height - 12, rx: 3, fill: 'none', stroke: FACE_TOKENS.backHighlight, 'stroke-width': 1.4, opacity: .85 }),
    svgEl('path', {
      d: `M${width / 2} ${height * .32}l${width * .13} ${height * .18}l-${width * .13} ${height * .18}l-${width * .13}-${height * .18}z`,
      fill: FACE_TOKENS.backHighlight,
      opacity: .7,
    }),
  );
  return svg;
}
