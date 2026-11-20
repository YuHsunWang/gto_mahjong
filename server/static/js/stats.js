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
  try {
    localStorage.setItem(KEY, JSON.stringify(data));
    return true;
  } catch {
    return false;
  }
}

function bucket(data, mode, schemeId) {
  if (!data[mode]) data[mode] = {};
  if (!data[mode][schemeId]) data[mode][schemeId] = [];
  return data[mode][schemeId];
}

// The one rule for "this pick is unranked": the ranking is not clear and the
// player's own choice is one of the actions the model cannot tell apart. A
// discard grade names that pair in top1_vs_top2; a call or kong grade lists
// the option indices (null = pass) in indistinguishable_indices.
export function choiceIsUnresolved(grade) {
  if (!grade || (grade.ranking_state || 'clear') === 'clear') return false;
  if (grade.kind === 'call' || grade.kind === 'kong') {
    return (grade.indistinguishable_indices || []).includes(grade.choice);
  }
  const gap = grade.top1_vs_top2;
  const chosen = grade.chosen?.discard;
  return Boolean(gap) && chosen !== undefined
    && (chosen === gap.top_discard || chosen === gap.runner_up_discard);
}

function gradeEvent(grade) {
  const tied = choiceIsUnresolved(grade);
  const loss = tied ? 0 : Number(grade.ev_loss) || 0;
  return {
    type: 'grade',
    t: Date.now(),
    v: grade.verdict,
    r: grade.ranking_state || 'clear',
    l: Math.round(Math.max(0, loss) * 100) / 100,
    b: grade.verdict === 'best' || tied ? 1 : 0,
  };
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
  const data = load();
  const events = bucket(data, mode, schemeId);
  events.push(gradeEvent(grade));
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
  return summarize(eventsFor(mode, schemeId));
}

// One finished hand's grade payloads. Each row of the hand review shows a
// pick as unranked only when it sits in the unresolved top pair, so only those
// leave the hand's quality score; every other pick counts by its verdict.
// ponytail: the stored totals above still drop every unresolved ranking (the
// docs/frontend-redesign.md §5 rule); issue #118 decides whether they follow.
export function handSummary(grades) {
  return summarize(grades.map((grade) => ({
    ...gradeEvent(grade),
    r: choiceIsUnresolved(grade) ? grade.ranking_state : 'clear',
  })));
}

function summarize(events) {
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
    best: counts.best + grades.filter((event) => event.r && event.r !== 'clear' && event.b === 1).length,
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

export function hasLegacyStats() {
  return localStorage.getItem(LEGACY_KEY) !== null;
}
