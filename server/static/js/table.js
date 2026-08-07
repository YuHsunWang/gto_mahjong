// Landscape four-seat table built as non-overlapping concentric CSS-grid bands.

import { tileBackEl, tileEl, countsToTiles, faceText } from './tiles.js';

const WINDS = ['東', '南', '西', '北'];
const SEAT_ROLES = { top: '對家', right: '下家', left: '上家' };

function riverEl(river = [], { position = 'bottom', highlightLast = false } = {}) {
  const el = document.createElement('div');
  el.className = `river river--${position}`;
  el.setAttribute('aria-label', `${position === 'bottom' ? '自家' : SEAT_ROLES[position]}牌河`);
  river.forEach((entry, index) => {
    const classes = entry.origin ? [entry.origin] : [];
    if (highlightLast && index === river.length - 1) classes.push('cut', 'landed');
    const tile = tileEl(entry.tile, { size: 'sm', classes });
    const ordinal = index + 1;
    tile.dataset.discardNumber = String(ordinal);
    tile.setAttribute('aria-label', `第${ordinal}張棄牌，${faceText(entry.tile)}`);
    el.append(tile);
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

function meldsEl(melds = [], details = [], ownerSeat, viewerSeat) {
  const el = document.createElement('div');
  el.className = 'seat-melds';
  melds.forEach((meld, index) => {
    const detail = details[index] || null;
    el.append(meldGroupEl(detail?.tiles || meld, detail, ownerSeat, viewerSeat, 'seat-meld'));
  });
  return el;
}

function identityEl(seat, {
  role = '', declared = false, isDealer = false, streak = 0, you = false,
  handCount = null, exposedTileCount = 0, score = null,
} = {}) {
  const identity = document.createElement('div');
  identity.className = 'seat-identity';
  const wind = document.createElement('b');
  wind.textContent = WINDS[seat] ?? '—';
  identity.append(wind);
  if (you || role) identity.append(document.createTextNode(` ${you ? '你' : role}`));
  if (isDealer) {
    const dealer = document.createElement('span');
    dealer.className = 'dealer-chip';
    dealer.textContent = streak ? `莊 · 連${streak}` : '莊';
    identity.append(dealer);
  }
  if (Number.isInteger(handCount)) {
    const count = document.createElement('span');
    count.textContent = `暗手 ${handCount}`;
    identity.append(count);
  }
  if (exposedTileCount) {
    const count = document.createElement('span');
    count.textContent = `明牌 ${exposedTileCount} 張`;
    identity.append(count);
  }
  if (declared) {
    const lamp = document.createElement('span');
    lamp.className = 'declared';
    lamp.textContent = '宣告';
    identity.append(lamp);
  }
  const scoreEl = document.createElement('span');
  scoreEl.className = 'seat-score';
  scoreEl.textContent = score === null || score === undefined ? '分數 —' : `分數 ${score}`;
  identity.append(scoreEl);
  return identity;
}

function concealedHandEl(count, orientation) {
  const hand = document.createElement('div');
  hand.className = `concealed-hand concealed-hand--${orientation}`;
  if (!Number.isInteger(count) || count < 0) {
    hand.classList.add('concealed-hand--unknown');
    hand.textContent = '暗手張數未提供';
    return hand;
  }
  hand.setAttribute('aria-label', `${count}張覆蓋牌`);
  for (let index = 0; index < count; index += 1) {
    hand.append(tileBackEl({ orientation, size: 'sm' }));
  }
  return hand;
}

function opponentSeatEl(positionName, opponent, viewerSeat, seatScores) {
  const section = document.createElement('section');
  section.className = `seat-band seat--${positionName}`;
  section.setAttribute('aria-label', `${SEAT_ROLES[positionName]}區域`);
  if (!opponent) {
    section.append(identityEl(0, { role: SEAT_ROLES[positionName] }));
    return section;
  }
  const meldTileCount = (opponent.meld_details || opponent.melds || [])
    .reduce((sum, meld) => sum + (meld.tiles || meld).length, 0);
  section.dataset.seat = String(opponent.seat);
  section.append(identityEl(opponent.seat, {
    role: SEAT_ROLES[positionName],
    declared: opponent.declared,
    isDealer: opponent.is_dealer,
    streak: opponent.dealer_streak,
    handCount: opponent.hand_count,
    exposedTileCount: meldTileCount,
    score: seatScores?.[opponent.seat],
  }));
  const orientation = positionName === 'top' ? 'portrait' : 'landscape';
  section.append(concealedHandEl(opponent.hand_count, orientation));
  if (opponent.melds?.length) {
    section.append(meldsEl(opponent.melds, opponent.meld_details, opponent.seat, viewerSeat));
  }
  return section;
}

function wallStackEl(tileCount) {
  const stack = document.createElement('div');
  stack.className = `wall-stack${tileCount === 1 ? ' wall-stack--half' : ''}`;
  stack.dataset.tiles = String(tileCount);
  stack.setAttribute('aria-label', tileCount === 1 ? '一墩剩一張' : '一墩兩張');
  for (let index = 0; index < tileCount; index += 1) {
    const tile = document.createElement('span');
    tile.className = 'wall-tile';
    tile.setAttribute('aria-hidden', 'true');
    stack.append(tile);
  }
  return stack;
}

function remainingWallStacks(wallRemaining) {
  if (!Number.isInteger(wallRemaining) || wallRemaining < 0) return null;
  const stacks = [];
  for (let remaining = wallRemaining; remaining > 0; remaining -= 2) {
    stacks.push(Math.min(2, remaining));
  }
  const sides = [[], [], [], []];
  stacks.forEach((tileCount, index) => sides[index % sides.length].push(tileCount));
  return sides;
}

function wallBandEl(positionName, stacks) {
  const band = document.createElement('div');
  band.className = `wall-band wall-band--${positionName}`;
  if (stacks === null) {
    band.classList.add('wall-band--unknown');
    band.textContent = '牌牆資料未提供';
    return band;
  }
  const tiles = stacks.reduce((sum, count) => sum + count, 0);
  band.dataset.stackCount = String(stacks.length);
  band.dataset.tileCount = String(tiles);
  band.setAttribute('aria-hidden', 'true');
  stacks.forEach((tileCount) => band.append(wallStackEl(tileCount)));
  return band;
}

function centerBox(position, { offeredTile = null } = {}) {
  const box = document.createElement('div');
  box.className = 'center-box';
  const stats = document.createElement('div');
  stats.className = 'center-stats';
  [
    [position.turn, '巡'],
    [position.wall_remaining, '餘牌'],
    [position.draws_remaining, '約摸'],
  ].forEach(([value, label]) => {
    const stat = document.createElement('span');
    const strong = document.createElement('strong');
    strong.textContent = Number.isFinite(value) ? String(value) : '—';
    const caption = document.createElement('small');
    caption.textContent = label;
    stat.append(strong, caption);
    stats.append(stat);
  });
  box.append(stats);
  if (position.dealer_streak) {
    const streak = document.createElement('div');
    streak.className = 'center-note';
    streak.textContent = `莊家連 ${position.dealer_streak} 拉 ${position.dealer_streak}`;
    box.append(streak);
  }
  if (offeredTile !== null) {
    const offered = document.createElement('div');
    offered.className = 'offered';
    const label = document.createElement('span');
    label.textContent = '可鳴';
    offered.append(label, tileEl(offeredTile, { size: 'sm', classes: ['drawn'] }));
    box.append(offered);
  }
  const noflower = document.createElement('div');
  noflower.className = 'noflower';
  noflower.textContent = '本桌無花牌';
  box.append(noflower);
  if (Number.isInteger(position.wall_remaining)) {
    const wallNote = document.createElement('div');
    wallNote.className = 'center-note';
    wallNote.textContent = '餘墩依總餘牌示意環繞';
    box.append(wallNote);
  }
  return box;
}

function coreEl(position, options) {
  const [right, top, left] = position.opponents || [];
  const core = document.createElement('div');
  core.className = 'table-core';
  core.append(
    riverEl(top?.river, { position: 'top' }),
    riverEl(left?.river, { position: 'left' }),
    centerBox(position, options),
    riverEl(right?.river, { position: 'right' }),
    riverEl(position.own_river, { position: 'bottom', highlightLast: options.ownRiverHighlight }),
  );
  return core;
}

function ownSeatEl(position, handOptions) {
  const section = document.createElement('section');
  section.className = 'seat-band seat--bottom';
  section.dataset.seat = String(position.seat);
  section.setAttribute('aria-label', '自家手牌區域');
  const concealedCount = Array.isArray(position.hand)
    ? position.hand.reduce((sum, count) => sum + count, 0)
    : null;
  const meldTileCount = (position.own_meld_details || position.own_melds || [])
    .reduce((sum, meld) => sum + (meld.tiles || meld).length, 0)
    + (position.own_kong_details || []).length * 4;
  section.append(identityEl(position.seat, {
    you: true,
    isDealer: position.is_dealer,
    streak: position.is_dealer ? position.dealer_streak : 0,
    handCount: concealedCount,
    exposedTileCount: meldTileCount,
    score: position.seat_scores?.[position.seat],
  }));
  section.append(handEl(position.hand, {
    drawnTile: position.drawn_tile,
    melds: position.own_melds,
    meldDetails: position.own_meld_details,
    kongDetails: position.own_kong_details,
    ownerSeat: position.seat,
    viewerSeat: position.seat,
    ...handOptions,
    embedded: true,
  }));
  return section;
}

// handOptions configures the live hand embedded in the bottom band.
export function feltEl(position, {
  offeredTile = null,
  ownRiverHighlight = false,
  handOptions = {},
} = {}) {
  const scroll = document.createElement('div');
  scroll.className = 'table-scroll';
  scroll.setAttribute('role', 'region');
  scroll.setAttribute('aria-label', '四人麻將牌桌');
  scroll.tabIndex = 0;

  const felt = document.createElement('div');
  felt.className = 'felt';
  const [right, top, left] = position.opponents || [];
  felt.append(
    opponentSeatEl('top', top, position.seat, position.seat_scores),
    opponentSeatEl('left', left, position.seat, position.seat_scores),
    opponentSeatEl('right', right, position.seat, position.seat_scores),
    ownSeatEl(position, handOptions),
  );

  const wallSides = remainingWallStacks(position.wall_remaining);
  felt.append(
    wallBandEl('top', wallSides?.[0] ?? wallSides),
    wallBandEl('right', wallSides?.[1] ?? wallSides),
    wallBandEl('bottom', wallSides?.[2] ?? wallSides),
    wallBandEl('left', wallSides?.[3] ?? wallSides),
    coreEl(position, { offeredTile, ownRiverHighlight }),
  );
  scroll.append(felt);
  return scroll;
}

// The live or standalone hand. marks supports cut, modelLeader and an array of
// indistinguishable tile indices; only one physical copy gets each marker.
export function handEl(handCounts, {
  drawnTile = null,
  onDiscard = null,
  marks = {},
  melds = [],
  meldDetails = [],
  kongDetails = [],
  ownerSeat = null,
  viewerSeat = ownerSeat,
  embedded = false,
} = {}) {
  const row = document.createElement('div');
  row.className = `handrow${embedded ? ' table-hand' : ''}`;
  const counts = [...handCounts];
  const hasDrawnTile = Number.isInteger(drawnTile) && counts[drawnTile] > 0;
  if (hasDrawnTile) counts[drawnTile] -= 1;
  const tiles = countsToTiles(counts);
  if (hasDrawnTile) tiles.push('gap', drawnTile);

  let lifted = null;
  let cutMarked = false;
  let leaderMarked = false;
  const indistinguishable = new Set(marks.indistinguishable || []);
  const indistinguishableMarked = new Set();
  const oneTap = localStorage.getItem('mj-onetap') === '1';

  tiles.forEach((tile, index) => {
    if (tile === 'gap') {
      const gap = document.createElement('div');
      gap.className = 'gap';
      gap.setAttribute('aria-hidden', 'true');
      row.append(gap);
      return;
    }
    const classes = [];
    const isDrawnSlot = hasDrawnTile && index === tiles.length - 1;
    if (isDrawnSlot) classes.push('drawn');
    if (marks.cut === tile && !cutMarked) {
      classes.push('cut');
      cutMarked = true;
    }
    if (marks.modelLeader === tile && !leaderMarked && marks.modelLeader !== null && marks.modelLeader !== undefined) {
      classes.push('model-leader-mark');
      leaderMarked = true;
    }
    if (indistinguishable.has(tile) && !indistinguishableMarked.has(tile)) {
      classes.push('indistinguishable-mark');
      indistinguishableMarked.add(tile);
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
