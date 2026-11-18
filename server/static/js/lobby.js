// Owner-selected game cards from the completed lobby study.
const PATHS = {
  count: '<rect x="5" y="3" width="22" height="26" rx="4"/><path d="M10 9h12M10 15h2m8 0h2m-12 5h2m8 0h2m-12 5h2m8 0h2"/>',
  chart: '<path d="M5 4v23h23M11 22v-6m7 6V9m7 13V4"/>',
};
const chevron = '<svg class="lobby-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="m9 5 7 7-7 7" stroke-linecap="round" stroke-linejoin="round"/></svg>';
const icon = name => `<span class="lobby-icon"><svg viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${PATHS[name]}</svg></span>`;

// Original continuous round head/body silhouette, following the sparrow in
// tile-faces.js. Redrawn with existing table pigments only, in five scenes.
function illustration(scene) {
  const tile = (x, y, angle = 0) => `<g transform="translate(${x} ${y}) rotate(${angle} 10 14)"><rect x="0" y="2" width="21" height="29" rx="4" fill="var(--wood)"/><rect width="21" height="28" rx="4" fill="var(--lacquer)" stroke="var(--ink)" stroke-width="1.2"/><path d="M7 8h7v10H7zM10.5 5v16" fill="none" stroke="var(--tool-red)" stroke-width="1.3"/></g>`;
  const props = [
    `<path d="m46 96 49-19h82l39 19-38 23H87Z" fill="var(--felt-0)" stroke="var(--ink)" stroke-width="1.3"/>${tile(83, 79, -9)}${tile(108, 82)}${tile(133, 80, 7)}${tile(157, 77, 12)}`,
    `${tile(73, 80, -14)}${tile(98, 77)}${tile(124, 78, 12)}<path d="m166 74 5-11 5 11m-5-11v20" fill="none" stroke="var(--ink)" stroke-width="2"/>`,
    `<circle cx="75" cy="69" r="23" fill="var(--panel)" stroke="var(--ink)" stroke-width="1.5"/><path d="M75 54v15l10 6M68 40h14" fill="none" stroke="var(--ink)" stroke-width="2"/>${tile(102, 84, -7)}${tile(128, 84, 7)}`,
    `<path d="m76 52 21 8v17c0 14-15 25-21 27-6-2-21-13-21-27V60Z" fill="var(--panel)" stroke="var(--ink)" stroke-width="1.5"/><path d="m66 76 7 7 14-17" fill="none" stroke="var(--ink)" stroke-width="2"/>${tile(119, 84, -6)}${tile(145, 84, 8)}`,
    '<path d="M72 83q23-7 48 4 23-12 48-5v31q-26-6-48 3-24-10-48-3Z" fill="var(--panel)" stroke="var(--ink)" stroke-width="1.5"/><path d="M120 88v27M83 92l25 2m-25 7 25 2m25-9 23-3m-23 12 23-3" fill="none" stroke="var(--ink)" stroke-width="1.4"/>',
  ][scene];
  return `<div class="lobby-art" aria-hidden="true"><svg viewBox="0 0 270 135" fill="none" xmlns="http://www.w3.org/2000/svg">
    <ellipse cx="136" cy="118" rx="86" ry="7" fill="var(--wood)" opacity=".35"/>
    <circle cx="134" cy="64" r="49" fill="var(--panel)" opacity=".48"/>
    <g transform="translate(${scene === 2 || scene === 3 ? 102 : 75} -1)" stroke="var(--ink)" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
      <path d="m41 87-9 19 15-7 9 8 4-21" fill="var(--wood)"/>
      <path d="M49 24q24-2 29 22 14 16 4 36-10 17-32 16-24 0-32-19-9-19 6-34 2-20 20-21-5-6-1-6l10 7" fill="var(--wood-hi)"/>
      <path d="M27 39q18-24 45 1-13-5-21-2-12-5-24 1Z" fill="var(--wood)" stroke="none"/>
      <path d="M25 65q23-15 48 0 3 27-23 27-25-1-25-27Z" fill="var(--panel)" stroke="none"/>
      <path d="M23 66q14-7 19 9-9 7-18 1m50-10q-13-6-16 9 10 9 20 0" fill="var(--wood)"/>
      <path d="m44 51 11 4-10 6Z" fill="var(--gold)"/>
      <circle cx="34" cy="47" r="2.4" fill="var(--ink)" stroke="none"/><circle cx="65" cy="47" r="2.4" fill="var(--ink)" stroke="none"/>
      <path d="M45 66q5 4 10-1M37 97l-2 5m29-5 2 5"/>
    </g>${props}
    <g stroke="var(--ink)" stroke-width="1.4" stroke-linecap="round"><path d="M204 36v8m-4-4h8M58 36v5m-2.5-2.5h5"/><circle cx="213" cy="88" r="2"/></g>
  </svg></div>`;
}


export function modeCard(mode, index, progress) {
  const link = document.createElement('a');
  link.className = 'lobby-card';
  link.href = mode.hash;
  link.innerHTML = illustration(index);
  const copy = document.createElement('span');
  copy.className = 'lobby-card-copy';
  const name = document.createElement('span');
  name.className = 'lobby-name';
  name.textContent = mode.chars;
  name.insertAdjacentHTML('beforeend', chevron);
  const desc = document.createElement('span');
  desc.className = 'lobby-desc';
  desc.textContent = mode.desc;
  copy.append(name, desc);
  if (progress) {
    const stats = document.createElement('span');
    stats.className = progress === '還沒練過' ? 'lobby-progress' : 'lobby-progress played';
    stats.textContent = progress;
    copy.append(stats);
  }
  link.append(copy);
  return link;
}

export function toolCard(hash, name, desc, symbol) {
  const link = document.createElement('a');
  link.className = 'lobby-tool';
  link.href = hash;
  link.innerHTML = icon(symbol);
  const copy = document.createElement('span');
  copy.className = 'lobby-tool-copy';
  const title = document.createElement('strong');
  title.textContent = name;
  const sub = document.createElement('span');
  sub.className = 'lobby-desc';
  sub.textContent = desc;
  copy.append(title, sub);
  link.append(copy);
  link.insertAdjacentHTML('beforeend', chevron);
  return link;
}
