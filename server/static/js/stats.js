// Client-side answer history per mode (localStorage; docs/ui-plan.md W3).

const KEY = 'mj-stats-v1';
const CAP = 500;

function load() {
  try {
    return JSON.parse(localStorage.getItem(KEY)) || {};
  } catch {
    return {};
  }
}

function save(data) {
  localStorage.setItem(KEY, JSON.stringify(data));
}

// One graded decision: verdict + non-negative EV loss.
export function record(mode, verdict, evLoss) {
  const data = load();
  if (!data[mode]) data[mode] = [];
  data[mode].push({ t: Date.now(), b: verdict === 'best' ? 1 : 0, l: Math.round(evLoss * 100) / 100 });
  if (data[mode].length > CAP) data[mode] = data[mode].slice(-CAP);
  save(data);
}

export function summary(mode) {
  const events = load()[mode] || [];
  const decisions = events.length;
  const best = events.reduce((sum, event) => sum + event.b, 0);
  const loss = events.reduce((sum, event) => sum + event.l, 0);
  return { decisions, best, loss };
}

// Rolling best-rate (window 10) over the last 60 answers, as points 0..1.
export function accuracySeries(mode, windowSize = 10, span = 60) {
  const events = (load()[mode] || []).slice(-span);
  if (events.length < 2) return [];
  const points = [];
  for (let i = 0; i < events.length; i += 1) {
    const window = events.slice(Math.max(0, i - windowSize + 1), i + 1);
    points.push(window.reduce((sum, event) => sum + event.b, 0) / window.length);
  }
  return points;
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
