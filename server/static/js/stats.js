// Client-side grade/outcome event history per mode and payout scheme.

import { currentScheme } from './scheme.js';

const KEY = 'mj-stats-v3';
const PREVIOUS_KEY = 'mj-stats-v2';
const LEGACY_KEY = 'mj-stats-v1';
const CAP = 500;
const VERDICTS = ['best', 'good', 'inaccuracy', 'mistake'];

function parsed(key) {
  try {
    return JSON.parse(localStorage.getItem(key)) || null;
  } catch {
    return null;
  }
}

function load() {
  return parsed(KEY) || parsed(PREVIOUS_KEY) || {};
}

function save(data) {
  localStorage.setItem(KEY, JSON.stringify(data));
}

function bucket(data, mode, schemeId) {
  if (!data[mode]) data[mode] = {};
  if (!data[mode][schemeId]) data[mode][schemeId] = [];
  return data[mode][schemeId];
}

function pairedChoiceIsUnresolved(grade) {
  if (grade.ranking_state === 'clear' || !grade.top1_vs_top2 || !grade.chosen) return false;
  const chosen = grade.chosen.discard;
  return chosen === grade.top1_vs_top2.top_discard
    || chosen === grade.top1_vs_top2.runner_up_discard;
}

// Accepts the full grade payload. The legacy scalar form remains valid for old
// callers, but cannot contribute a detailed quality category beyond best.
export function record(mode, gradeOrVerdict, evLossOrScheme, explicitSchemeId = currentScheme().key) {
  const fullGrade = typeof gradeOrVerdict === 'object' && gradeOrVerdict !== null;
  const grade = fullGrade ? gradeOrVerdict : {
    verdict: gradeOrVerdict,
    ev_loss: evLossOrScheme,
    ranking_state: 'clear',
  };
  const schemeId = fullGrade ? (evLossOrScheme || currentScheme().key) : explicitSchemeId;
  const rankingState = grade.ranking_state || 'clear';
  const loss = pairedChoiceIsUnresolved(grade) ? 0 : Number(grade.ev_loss) || 0;
  const event = {
    type: 'grade',
    t: Date.now(),
    v: grade.verdict,
    r: rankingState,
    l: Math.round(Math.max(0, loss) * 100) / 100,
    b: grade.verdict === 'best' && rankingState === 'clear' ? 1 : 0,
  };
  const data = load();
  const events = bucket(data, mode, schemeId);
  events.push(event);
  if (events.length > CAP) data[mode][schemeId] = events.slice(-CAP);
  save(data);
}

export function recordOutcome(mode, handId, schemeId = currentScheme().key) {
  const data = load();
  const events = bucket(data, mode, schemeId);
  if (events.some((event) => event.type === 'hand' && event.id === handId)) return;
  events.push({ type: 'hand', t: Date.now(), id: handId });
  if (events.length > CAP) data[mode][schemeId] = events.slice(-CAP);
  save(data);
}

function eventsFor(mode, schemeId = currentScheme().key) {
  return load()[mode]?.[schemeId] || [];
}

function isGrade(event) {
  return event.type === 'grade' || event.type === undefined;
}

export function summary(mode, schemeId = currentScheme().key) {
  const events = eventsFor(mode, schemeId);
  const grades = events.filter(isGrade);
  const counts = { best: 0, good: 0, inaccuracy: 0, mistake: 0 };
  let unresolved = 0;
  let legacy = 0;
  let loss = 0;
  grades.forEach((event) => {
    loss += Number(event.l) || 0;
    if (event.r && event.r !== 'clear') {
      unresolved += 1;
    } else if (VERDICTS.includes(event.v)) {
      counts[event.v] += 1;
    } else {
      legacy += 1;
    }
  });
  const separable = Object.values(counts).reduce((sum, count) => sum + count, 0);
  const qualityScore = separable
    ? Math.round((100 * (counts.best + counts.good)) / separable)
    : null;
  const hands = events.filter((event) => event.type === 'hand').length;
  return {
    decisions: grades.length,
    best: counts.best,
    loss,
    hands,
    unresolved,
    separable,
    qualityScore,
    avgLossPerHand: hands ? loss / hands : null,
    legacy,
    counts,
  };
}

// Rolling quality rate over separable, category-aware grade events.
export function accuracySeries(mode, windowSize = 10, span = 60, schemeId = currentScheme().key) {
  const events = eventsFor(mode, schemeId)
    .filter((event) => isGrade(event) && (!event.r || event.r === 'clear') && VERDICTS.includes(event.v))
    .slice(-span);
  if (events.length < 2) return [];
  return events.map((_event, index) => {
    const window = events.slice(Math.max(0, index - windowSize + 1), index + 1);
    return window.filter((event) => event.v === 'best' || event.v === 'good').length / window.length;
  });
}

export function hasLegacyStats() {
  return localStorage.getItem(LEGACY_KEY) !== null;
}

export function sparklineEl(points, width = 96, height = 26) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('width', width);
  svg.setAttribute('height', height);
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  if (points.length < 2) return svg;
  const step = width / (points.length - 1);
  const path = points
    .map((value, index) => `${index ? 'L' : 'M'}${(index * step).toFixed(1)},${(height - 3 - value * (height - 6)).toFixed(1)}`)
    .join(' ');
  const line = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  line.setAttribute('d', path);
  line.setAttribute('fill', 'none');
  line.setAttribute('stroke', 'var(--gold)');
  line.setAttribute('stroke-width', '1.5');
  svg.append(line);
  return svg;
}
