// 底/台 payout scheme selector. The engine recomputes EV under the chosen
// scheme, so switching can change the recommended play (the teaching point).
// Persisted in localStorage; default 底3台1 (the house default the engine uses).

const KEY = 'mj-scheme';

export const SCHEMES = {
  '3/1': { key: '3/1', label: '底3台1', base_units: 3, tai_units: 1 },
  '5/2': { key: '5/2', label: '底5台2', base_units: 5, tai_units: 2 },
};

export function currentScheme() {
  return SCHEMES[localStorage.getItem(KEY)] || SCHEMES['3/1'];
}

export function setScheme(key) {
  if (SCHEMES[key]) localStorage.setItem(KEY, key);
}

// Spread into a grade/act/ev-rank request body.
export function schemeParams() {
  const scheme = currentScheme();
  return { base_units: scheme.base_units, tai_units: scheme.tai_units };
}

// A small segmented control. `onChange(newKey)` fires only on an actual switch.
export function schemeToggle(onChange) {
  const wrap = document.createElement('div');
  wrap.className = 'scheme-toggle';
  const caption = document.createElement('span');
  caption.className = 'scheme-caption';
  caption.textContent = '底台';
  wrap.append(caption);
  const active = currentScheme().key;
  Object.values(SCHEMES).forEach((scheme) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = scheme.label;
    if (scheme.key === active) button.classList.add('active');
    button.addEventListener('click', () => {
      if (scheme.key === currentScheme().key) return;
      setScheme(scheme.key);
      [...wrap.querySelectorAll('button')].forEach((b) => b.classList.toggle('active', b === button));
      onChange(scheme.key);
    });
    wrap.append(button);
  });
  return wrap;
}
