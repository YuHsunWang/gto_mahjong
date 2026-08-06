// The felt: four rivers converging on the centre box, Mahjong-Soul style.
// Renders a W1 position payload; the interactive hand is rendered separately.

import { tileEl, countsToTiles, faceText } from './tiles.js';

const WINDS = ['東', '南', '西', '北'];

function riverEl(river, { highlightLast = false } = {}) {
  const el = document.createElement('div');
  el.className = 'river';
  river.forEach((entry, index) => {
    const classes = [entry.origin];
    if (highlightLast && index === river.length - 1) classes.push('cut', 'landed');
    el.append(tileEl(entry.tile, { size: 'sm', classes }));
  });
  return el;
}

function seatPoint(seat, viewerSeat) {
  const points = [[0, 1], [1, 0], [0, -1], [-1, 0]];
  return points[(seat - viewerSeat + 4) % 4];
}

function provenanceArrow(ownerSeat, sourceSeat, viewerSeat) {
  const [ownerX, ownerY] = seatPoint(ownerSeat, viewerSeat);
  const [sourceX, sourceY] = seatPoint(sourceSeat, viewerSeat);
  const direction = `${Math.sign(sourceX - ownerX)},${Math.sign(sourceY - ownerY)}`;
  return {
    '-1,-1': '↖', '0,-1': '↑', '1,-1': '↗',
    '-1,0': '←', '1,0': '→',
    '-1,1': '↙', '0,1': '↓', '1,1': '↘',
  }[direction] || '•';
}

function provenanceEl(detail, ownerSeat, viewerSeat) {
  if (!detail || detail.called_from_seat === null || detail.called_from_discard_number === null) return null;
  const sourceSeat = detail.called_from_seat;
  const number = detail.called_from_discard_number;
  const accessible = `${WINDS[sourceSeat]}家第${number}張棄牌所鳴`;
  const label = document.createElement('span');
  label.className = 'meld-provenance';
  label.setAttribute('aria-label', accessible);
  label.title = accessible;
  const arrow = document.createElement('span');
  arrow.setAttribute('aria-hidden', 'true');
  arrow.textContent = provenanceArrow(ownerSeat, sourceSeat, viewerSeat);
  label.append(arrow, document.createTextNode(` ${number}`));
  return label;
}

function meldGroupEl(tiles, detail, ownerSeat, viewerSeat, className) {
  const group = document.createElement('div');
  group.className = className;
  const provenance = provenanceEl(detail, ownerSeat, viewerSeat);
  if (provenance) group.append(provenance);
  tiles.forEach((tile) => group.append(tileEl(tile, { size: 'sm' })));
  return group;
}

function meldsEl(melds, details = [], ownerSeat, viewerSeat) {
  const el = document.createElement('div');
  el.className = 'opp-melds';
  melds.forEach((meld, index) => {
    const detail = details[index] || null;
    el.append(meldGroupEl(detail?.tiles || meld, detail, ownerSeat, viewerSeat, 'opp-meld'));
  });
  return el;
}

function seatLamp(seat, { declared = false, isDealer = false, streak = 0, tenpai = null, fold = null, you = false, pos = '', handCount = null } = {}) {
  const el = document.createElement('div');
  el.className = `seat-lamp ${pos}`;
  const wind = document.createElement('span');
  wind.className = 'wind';
  wind.textContent = WINDS[seat] + (isDealer ? '莊' : '') + (streak ? `連${streak}` : '');
  el.append(wind);
  if (you) {
    const label = document.createElement('span');
    label.textContent = '你';
    el.append(label);
  }
  if (handCount !== null) {
    const count = document.createElement('span');
    count.className = 'handcount';
    count.textContent = `手牌${handCount}`;
    el.append(count);
  }
  if (declared) {
    const lamp = document.createElement('span');
    lamp.className = 'declared';
    lamp.textContent = '宣告';
    el.append(lamp);
  }
  if (tenpai !== null) {
    const est = document.createElement('span');
    est.textContent = `聽${tenpai.toFixed(2)}/棄${fold.toFixed(2)}`;
    el.append(est);
  }
  return el;
}

function opponentZone(cssClass, opponent, viewerSeat) {
  // No hidden-hand rack: the centre box already reports the wall count, and
  // concealed hands carry no information worth pixels (user call, 2026-07-20).
  const zone = document.createElement('div');
  zone.className = `zone ${cssClass}`;
  if (!opponent) return zone;
  if (opponent.melds.length) {
    zone.append(meldsEl(opponent.melds, opponent.meld_details, opponent.seat, viewerSeat));
  }
  zone.append(riverEl(opponent.river));
  return zone;
}

function centerBox(position, { offeredTile = null } = {}) {
  const box = document.createElement('div');
  box.className = 'center-box';
  const turn = document.createElement('div');
  turn.className = 'turn';
  turn.textContent = `第 ${position.turn} 巡`;
  const wall = document.createElement('div');
  wall.className = 'sub';
  wall.textContent = `牆剩 ${position.wall_remaining} 張 · 約再摸 ${position.draws_remaining} 巡`;
  box.append(turn, wall);
  if (position.dealer_streak) {
    const streak = document.createElement('div');
    streak.className = 'sub';
    streak.textContent = `莊家連 ${position.dealer_streak} 拉 ${position.dealer_streak}`;
    box.append(streak);
  }
  if (offeredTile !== null) {
    const offered = document.createElement('div');
    offered.className = 'offered';
    const label = document.createElement('div');
    label.className = 'sub';
    label.textContent = '可鳴';
    offered.append(label, tileEl(offeredTile, { size: 'sm', classes: ['drawn'] }));
    box.append(offered);
  }
  const noflower = document.createElement('div');
  noflower.className = 'noflower';
  noflower.textContent = '本桌無花牌';
  box.append(noflower);
  return box;
}

// ownRiverHighlight: mark the last own-river tile as the just-cut discard.
export function feltEl(position, { offeredTile = null, ownRiverHighlight = false } = {}) {
  const felt = document.createElement('div');
  felt.className = 'felt';
  const [right, top, left] = position.opponents; // engine order: 下家, 對家, 上家
  felt.append(opponentZone('top', top, position.seat));
  felt.append(opponentZone('left', left, position.seat));
  felt.append(centerBox(position, { offeredTile }));
  felt.append(opponentZone('right', right, position.seat));

  // Own melds live beside the hand tray, not on the felt (user call, 2026-07-20).
  const bottom = document.createElement('div');
  bottom.className = 'zone bottom';
  bottom.append(riverEl(position.own_river, { highlightLast: ownRiverHighlight }));
  felt.append(bottom);

  // Upright corner lamps, outside the rotated zones.
  const lampFor = (opponent, pos) => seatLamp(opponent.seat, {
    declared: opponent.declared,
    isDealer: opponent.is_dealer,
    streak: opponent.dealer_streak,
    tenpai: opponent.tenpai_estimate,
    fold: opponent.fold_estimate,
    handCount: opponent.hand_count,
    pos,
  });
  if (top) felt.append(lampFor(top, 'pos-top'));
  if (right) felt.append(lampFor(right, 'pos-right'));
  if (left) felt.append(lampFor(left, 'pos-left'));
  felt.append(seatLamp(position.seat, {
    isDealer: position.is_dealer,
    streak: position.is_dealer ? position.dealer_streak : 0,
    you: true,
    pos: 'pos-self',
  }));
  return felt;
}

// The interactive hand tray. states:
//   onDiscard: enable tap-to-discard (confirm-tap unless the one-tap setting is on)
//   drawnTile: separated with a gap + gold frame
//   marks: {cut: tile, best: tile} for the feedback state
export function handEl(handCounts, {
  drawnTile = null,
  onDiscard = null,
  marks = {},
  melds = [],
  meldDetails = [],
  kongDetails = [],
  ownerSeat = null,
  viewerSeat = ownerSeat,
} = {}) {
  const row = document.createElement('div');
  row.className = 'handrow';
  const counts = [...handCounts];
  if (drawnTile !== null && counts[drawnTile] > 0) counts[drawnTile] -= 1;
  const tiles = countsToTiles(counts);
  if (drawnTile !== null) tiles.push('gap', drawnTile);

  let lifted = null;
  let cutMarked = false;
  let bestMarked = false;
  const oneTap = localStorage.getItem('mj-onetap') === '1';

  tiles.forEach((tile, index) => {
    if (tile === 'gap') {
      const gap = document.createElement('div');
      gap.className = 'gap';
      row.append(gap);
      return;
    }
    const classes = [];
    const isDrawnSlot = drawnTile !== null && index === tiles.length - 1;
    if (isDrawnSlot) classes.push('drawn');
    if (marks.cut === tile && !cutMarked) {
      classes.push('cut');
      cutMarked = true;
    }
    if (marks.best === tile && !bestMarked && marks.best !== null && marks.best !== undefined) {
      classes.push('best-mark');
      bestMarked = true;
    }
    const el = tileEl(tile, { size: 'lg', classes, as: onDiscard ? 'button' : 'div' });
    el.dataset.tile = String(tile);
    if (onDiscard) {
      el.addEventListener('click', () => {
        if (oneTap || lifted === el) {
          onDiscard(tile);
          return;
        }
        if (lifted) lifted.classList.remove('lifted');
        lifted = el;
        el.classList.add('lifted');
      });
    }
    row.append(el);
  });

  // Declared melds (吃/碰/槓) sit apart at the right edge of the tray.
  if (melds.length || kongDetails.length) {
    const rack = document.createElement('div');
    rack.className = 'hand-melds';
    melds.forEach((meld, index) => {
      const detail = meldDetails[index] || null;
      rack.append(meldGroupEl(
        detail?.tiles || meld, detail, ownerSeat, viewerSeat, 'hand-meld',
      ));
    });
    kongDetails.forEach((detail) => {
      rack.append(meldGroupEl(
        Array(4).fill(detail.tile), detail, ownerSeat, viewerSeat, 'hand-meld hand-kong',
      ));
    });
    row.append(rack);
  }
  return row;
}

export function computingEl(text) {
  const el = document.createElement('div');
  el.className = 'computing';
  const spinner = document.createElement('div');
  spinner.className = 'spin';
  const label = document.createElement('span');
  label.textContent = text;
  el.append(spinner, label);
  return el;
}

export { faceText };
