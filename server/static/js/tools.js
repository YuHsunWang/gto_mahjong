// 切牌分析 / 算台 — Streamlit-parity tools over /api/ev/rank and /api/score.

import { post, showError } from './api.js';
import { tileEl, parseCompact } from './tiles.js';
import { computingEl } from './table.js';
import { evTableEl, modelScopeEl } from './feedback.js';
import { schemeParams, schemeToggle } from './scheme.js';

function field(labelText, input, id) {
  const wrap = document.createElement('div');
  wrap.className = 'field';
  const label = document.createElement('label');
  label.textContent = labelText;
  label.htmlFor = id;
  input.id = id;
  wrap.append(label, input);
  return wrap;
}

function textInput(value = '') {
  const input = document.createElement('input');
  input.type = 'text';
  input.value = value;
  input.spellcheck = false;
  return input;
}

function numberInput(value, min, max) {
  const input = document.createElement('input');
  input.type = 'number';
  input.value = String(value);
  if (min !== undefined) input.min = String(min);
  if (max !== undefined) input.max = String(max);
  return input;
}

function previewStrip(input) {
  const strip = document.createElement('div');
  strip.className = 'tile-preview';
  const update = () => {
    strip.replaceChildren();
    const tiles = parseCompact(input.value);
    if (tiles) tiles.forEach((tile) => strip.append(tileEl(tile, { size: 'sm' })));
  };
  input.addEventListener('input', update);
  update();
  return strip;
}

function screenHeader(root, title) {
  const bar = document.createElement('div');
  bar.className = 'topbar';
  const back = document.createElement('a');
  back.className = 'back';
  back.href = '#/';
  back.textContent = '‹ 首頁';
  const heading = document.createElement('h1');
  heading.textContent = title;
  bar.append(back, heading);
  root.append(bar);
}

export function analyzeScreen(root) {
  screenHeader(root, '切牌分析');
  const hand = textInput('123m123p123s11122233z');
  const river = textInput('');
  const melds = textInput('');
  const declared = textInput('');
  const visible = textInput('');
  const sims = numberInput(400, 1);
  const seed = numberInput(7, 0);
  const turns = numberInput(0, 0);

  const form = document.createElement('div');
  form.append(field('手牌（17 張，例 123m45p…）', hand, 'an-hand'), previewStrip(hand));
  form.append(field('對手河（可用 * 摸切 / . 手切）', river, 'an-river'));
  form.append(field('對手副露（以 ; 分隔）', melds, 'an-melds'));
  form.append(field('宣告位置（河的索引，可留白）', declared, 'an-declared'));
  form.append(field('其他可見牌', visible, 'an-visible'));
  const advanced = document.createElement('div');
  advanced.className = 'field-row';
  advanced.append(field('摸牌回合（0=自動）', turns, 'an-turns'), field('模擬次數', sims, 'an-sims'), field('種子', seed, 'an-seed'));
  form.append(advanced);
  form.append(schemeToggle(() => {}));

  const controls = document.createElement('div');
  controls.className = 'controls';
  const run = document.createElement('button');
  run.className = 'btn primary';
  run.textContent = '分析 EV';
  controls.append(run);
  const output = document.createElement('div');
  root.append(form, controls, output);

  run.addEventListener('click', async () => {
    output.replaceChildren(computingEl('計算 EV 中…'));
    run.disabled = true;
    try {
      const body = await post('/api/ev/rank', {
        hand: hand.value.trim(),
        river: river.value.trim(),
        melds: melds.value.trim(),
        declared_at: declared.value.trim() === '' ? null : Number(declared.value),
        visible: visible.value.trim(),
        turns: Number(turns.value) || 0,
        sims: Number(sims.value) || 400,
        seed: Number(seed.value) || 0,
        ...schemeParams(),
      });
      output.replaceChildren();
      const caption = document.createElement('div');
      caption.className = 'note';
      caption.textContent = body.opponent
        ? `方案 ${body.scheme.id} · 剩餘摸牌回合 ${body.turns} · 對手聽牌估計 ${body.opponent.tenpai_estimate.toFixed(2)} · 棄和估計 ${body.opponent.fold_estimate.toFixed(2)}`
        : `方案 ${body.scheme.id} · 剩餘摸牌回合 ${body.turns} · 未提供對手狀態`;
      output.append(caption, modelScopeEl(body), evTableEl(body.entries));
    } catch (error) {
      output.replaceChildren();
      showError(error);
    }
    run.disabled = false;
  });
}

export function scoreScreen(root) {
  screenHeader(root, '算台');
  const hand = textInput('123m111555666777z22z');
  const winTile = textInput('2z');
  const melds = textInput('');
  const streak = numberInput(0, 0);

  const form = document.createElement('div');
  form.append(field('和牌手牌（含和的那張）', hand, 'sc-hand'), previewStrip(hand));
  const row = document.createElement('div');
  row.className = 'field-row';
  row.append(field('和牌', winTile, 'sc-win'), field('連莊次數', streak, 'sc-streak'));
  form.append(row);
  form.append(field('副露（以 ; 分隔，可留白）', melds, 'sc-melds'));

  const toggles = document.createElement('div');
  const flags = {};
  [['self_draw', '自摸'], ['dealer', '莊家'], ['migi', '宣告聽牌（migi）'], ['heavenly', '天胡'], ['earthly', '地胡']].forEach(([key, label]) => {
    const wrap = document.createElement('label');
    wrap.className = 'check';
    const box = document.createElement('input');
    box.type = 'checkbox';
    flags[key] = box;
    wrap.append(box, document.createTextNode(label));
    toggles.append(wrap);
  });
  form.append(toggles);

  const winds = document.createElement('div');
  winds.className = 'field-row';
  const windOptions = [['', '無'], ['1z', '東'], ['2z', '南'], ['3z', '西'], ['4z', '北']];
  const makeWind = () => {
    const select = document.createElement('select');
    windOptions.forEach(([value, label]) => {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = label;
      select.append(option);
    });
    return select;
  };
  const roundWind = makeWind();
  const seatWind = makeWind();
  winds.append(field('圈風', roundWind, 'sc-round'), field('門風', seatWind, 'sc-seat'));
  form.append(winds);
  form.append(schemeToggle(() => {}));

  const controls = document.createElement('div');
  controls.className = 'controls';
  const run = document.createElement('button');
  run.className = 'btn primary';
  run.textContent = '計算台數';
  controls.append(run);
  const output = document.createElement('div');
  root.append(form, controls, output);

  run.addEventListener('click', async () => {
    output.replaceChildren(computingEl('計算中…'));
    try {
      const body = await post('/api/score', {
        hand: hand.value.trim(),
        win_tile: winTile.value.trim(),
        melds: melds.value.trim(),
        self_draw: flags.self_draw.checked,
        dealer: flags.dealer.checked,
        dealer_streak: Number(streak.value) || 0,
        migi: flags.migi.checked,
        heavenly: flags.heavenly.checked,
        earthly: flags.earthly.checked,
        round_wind: roundWind.value || null,
        seat_wind: seatWind.value || null,
        ...schemeParams(),
      });
      output.replaceChildren();
      const wrap = document.createElement('div');
      wrap.className = 'evtable-wrap';
      const table = document.createElement('table');
      table.className = 'evtable';
      const head = document.createElement('tr');
      ['項目', '台'].forEach((label) => {
        const th = document.createElement('th');
        th.textContent = label;
        head.append(th);
      });
      table.append(head);
      body.items.forEach((item) => {
        const tr = document.createElement('tr');
        const name = document.createElement('td');
        name.textContent = item.name;
        const tai = document.createElement('td');
        tai.textContent = String(item.tai);
        tr.append(name, tai);
        table.append(tr);
      });
      wrap.append(table);
      const total = document.createElement('div');
      total.className = 'score-total';
      total.textContent = `總計 ${body.total_tai} 台（底 ${body.base_units} + 台 ${body.tai_units} × ${body.total_tai} = ${body.value_units} 籌碼單位；方案 ${body.scheme.id}）`;
      output.append(wrap, total);
    } catch (error) {
      output.replaceChildren();
      showError(error);
    }
  });
}
