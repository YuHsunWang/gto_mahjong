// Original lobby sparrow, shared so the coach keeps the same silhouette.
// Null preserves the lobby face; coach expressions are static SVG paths.
export function sparrowArt(expression = null) {
  const eyes = expression === 'happy'
    ? '<path d="M29 47q5-8 10 0m21 0q5-8 10 0" fill="none"/>'
    : expression === 'content'
      ? '<path d="M29 46q5 5 10 0m21 0q5 5 10 0" fill="none"/>'
      : '<circle cx="34" cy="47" r="2.4" fill="var(--ink)" stroke="none"/><circle cx="65" cy="47" r="2.4" fill="var(--ink)" stroke="none"/>';
  const mouth = {
    happy: '<path d="M43 64q7 5 14 0-2 12-8 9Z" fill="var(--ink)"/>',
    content: '<path d="M45 66q5 4 10-1" fill="none"/>',
    puzzled: '<path d="m29 40 9-2m23 1 8 3M47 67q4-2 8 0" fill="none"/>',
    frown: '<path d="m29 40 9 2m23 0 8-2M44 69q6-7 12 0" fill="none"/>',
  };
  const face = expression
    ? `<g>${eyes}${mouth[expression]}</g><path d="M37 97l-2 5m29-5 2 5"/>`
    : `      <circle cx="34" cy="47" r="2.4" fill="var(--ink)" stroke="none"/><circle cx="65" cy="47" r="2.4" fill="var(--ink)" stroke="none"/>
      <path d="M45 66q5 4 10-1M37 97l-2 5m29-5 2 5"/>`;
  return `
      <path d="m41 87-9 19 15-7 9 8 4-21" fill="var(--wood)"/>
      <path d="M49 24q24-2 29 22 14 16 4 36-10 17-32 16-24 0-32-19-9-19 6-34 2-20 20-21-5-6-1-6l10 7" fill="var(--wood-hi)"/>
      <path d="M27 39q18-24 45 1-13-5-21-2-12-5-24 1Z" fill="var(--wood)" stroke="none"/>
      <path d="M25 65q23-15 48 0 3 27-23 27-25-1-25-27Z" fill="var(--panel)" stroke="none"/>
      <path d="M23 66q14-7 19 9-9 7-18 1m50-10q-13-6-16 9 10 9 20 0" fill="var(--wood)"/>
      <path d="m44 51 11 4-10 6Z" fill="var(--gold)"/>

      ${face}`;
}

const EXPRESSIONS = {
  best: 'happy',
  good: 'content',
  inaccuracy: 'puzzled',
  mistake: 'frown',
};

// Decorative only: no text nodes, accessible label, or change to feedback copy.
export function withCoach(el, verdict = null) {
  const expression = EXPRESSIONS[verdict] || 'content';
  const avatar = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  avatar.classList.add('coach-avatar');
  avatar.dataset.expression = expression;
  avatar.setAttribute('viewBox', '0 10 100 105');
  avatar.setAttribute('aria-hidden', 'true');
  avatar.setAttribute('focusable', 'false');
  avatar.innerHTML = `<g fill="none" stroke="var(--ink)" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"${expression === 'puzzled' ? ' transform="rotate(-10 50 60)"' : ''}>${sparrowArt(expression)}</g>`.replace(/>\s+</g, '><').trim();
  el.classList.add('coach-verdict');
  el.prepend(avatar);
  return el;
}
