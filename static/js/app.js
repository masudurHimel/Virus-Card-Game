// =====================================================================
// VIRUS! — App controller: menu → table, fetches state, animates moves.
// =====================================================================

const ANIM_LAYER_ID = 'anim-layer';

const state = {
  gameId: null,
  snapshot: null,
  selectedCardIds: [],
  primaryCardId: null,
  legalTargets: null,
  cardType: null,
  busy: false,
};

const FLIGHT_MS = 520;        // standard card-flight duration
const FLIGHT_FAST_MS = 340;   // discard cascade duration
const THINK_MIN_MS = 1000;    // bot minimum think time
const THINK_MAX_MS = 2000;    // bot maximum think time

// ---------- helpers ----------

async function api(method, url, body) {
  const opts = { method, headers: {} };
  if (body) {
    opts.headers['content-type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(url, opts);
  if (!r.ok) {
    const t = await r.text();
    throw new Error(`${r.status} ${t}`);
  }
  return r.json();
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

function setHint(text, tone) {
  const el = document.getElementById('hint');
  el.textContent = text;
  el.classList.remove('warn', 'success');
  if (tone === 'warn') el.classList.add('warn');
  if (tone === 'success') el.classList.add('success');
}

function rectOf(selOrEl) {
  const el = (typeof selOrEl === 'string') ? document.querySelector(selOrEl) : selOrEl;
  return el ? el.getBoundingClientRect() : null;
}

function getOrganRect(playerIdx, organId) {
  if (playerIdx === 0) {
    return rectOf(`#your-body .organ[data-organ-id="${CSS.escape(organId)}"]`);
  }
  return rectOf(`.opponent[data-player-idx="${playerIdx}"] .organ[data-organ-id="${CSS.escape(organId)}"]`);
}

function getOrganEl(playerIdx, organId) {
  if (playerIdx === 0) {
    return document.querySelector(`#your-body .organ[data-organ-id="${CSS.escape(organId)}"]`);
  }
  return document.querySelector(`.opponent[data-player-idx="${playerIdx}"] .organ[data-organ-id="${CSS.escape(organId)}"]`);
}

function getPileRect(name) {
  return rectOf(`#${name}`);
}

function getActorHandRect(actorIdx, card) {
  if (actorIdx === 0 && card) {
    const el = document.querySelector(`#your-hand .card[data-card-id="${CSS.escape(card.id)}"]`);
    if (el) return [el.getBoundingClientRect(), el];
  }
  // Bot or fallback: use the hand-back area of that seat
  const back = document.querySelector(`.opponent[data-player-idx="${actorIdx}"] .hand-back`);
  if (back) {
    const r = back.getBoundingClientRect();
    // Center it
    return [r, null];
  }
  // last resort: center of viewport
  return [{ left: window.innerWidth / 2, top: window.innerHeight / 2, width: 80, height: 116, right: 0, bottom: 0 }, null];
}

// ---------- ghost card flight ----------

function createGhostCard(card, opts = {}) {
  const size = opts.size || 'large';
  const ghost = buildCard(card, { size });
  ghost.classList.add('ghost');
  if (opts.fast) ghost.classList.add('fast');
  return ghost;
}

function placeGhostAt(ghost, srcRect, size) {
  // Position the ghost's TOP-LEFT so the card center aligns with srcRect center.
  const w = size?.w || ghost.offsetWidth || 110;
  const h = size?.h || ghost.offsetHeight || 156;
  const cx = srcRect.left + srcRect.width / 2;
  const cy = srcRect.top + srcRect.height / 2;
  ghost.style.left = (cx - w / 2) + 'px';
  ghost.style.top  = (cy - h / 2) + 'px';
}

async function flyGhost(ghost, srcRect, dstRect, opts = {}) {
  const layer = document.getElementById(ANIM_LAYER_ID);
  layer.appendChild(ghost);
  // Force reflow then set initial position
  // For "large" ghost vs "small" ghost, sizes differ; let the layout compute.
  const tempStyle = window.getComputedStyle(ghost);
  // Use ghost actual size from offsetWidth (after attach)
  const w = ghost.offsetWidth;
  const h = ghost.offsetHeight;
  placeGhostAt(ghost, srcRect, { w, h });
  // Force reflow so transition triggers
  // eslint-disable-next-line no-unused-expressions
  ghost.offsetHeight;
  await sleep(20);

  // Compute end translation. We'll keep style.left/top fixed and use transform for transition.
  const startX = parseFloat(ghost.style.left);
  const startY = parseFloat(ghost.style.top);
  const endCx = dstRect.left + dstRect.width / 2;
  const endCy = dstRect.top + dstRect.height / 2;
  const dx = endCx - (startX + w / 2);
  const dy = endCy - (startY + h / 2);
  const rot = opts.rot ?? (Math.random() * 12 - 6);
  ghost.style.transform = `translate(${dx}px, ${dy}px) rotate(${rot}deg) scale(${opts.endScale ?? 0.92})`;

  const duration = opts.fast ? FLIGHT_FAST_MS : FLIGHT_MS;
  await sleep(duration);
}

async function vanishGhost(ghost) {
  ghost.style.transition = 'opacity 0.25s ease, transform 0.25s ease';
  ghost.style.opacity = '0';
  ghost.style.transform += ' scale(0.7)';
  await sleep(260);
  ghost.remove();
}

// ---------- snapshot diff ----------

function indexOrgans(snapshot) {
  const map = new Map();
  for (const p of snapshot.players) {
    for (const o of p.body) {
      map.set(o.card.id, { playerId: p.id, status: o.status, attachedIds: o.attached.map(c => c.id) });
    }
  }
  return map;
}

function diffSnapshots(before, after) {
  const b = indexOrgans(before);
  const a = indexOrgans(after);
  const destroyed = [], created = [], moved = [], statusChanged = [];
  for (const [id, info] of b) {
    if (!a.has(id)) destroyed.push({ organId: id, ...info });
    else {
      const ai = a.get(id);
      if (ai.playerId !== info.playerId) moved.push({ organId: id, from: info.playerId, to: ai.playerId });
      else if (ai.status !== info.status) statusChanged.push({ organId: id, playerId: ai.playerId, status: ai.status });
    }
  }
  for (const [id, info] of a) {
    if (!b.has(id)) created.push({ organId: id, playerId: info.playerId });
  }
  return { destroyed, created, moved, statusChanged };
}

// ---------- thinking indicator ----------

// The thinking bubble above each bot's avatar is purely CSS-driven from the
// `.opponent.thinking` class, so we only need to toggle that one class.
function showThinking(actorIdx) {
  const op = document.querySelector(`.opponent[data-player-idx="${actorIdx}"]`);
  if (op) op.classList.add('thinking');
}

function hideThinking(actorIdx) {
  const op = document.querySelector(`.opponent[data-player-idx="${actorIdx}"]`);
  if (op) op.classList.remove('thinking');
}

function hideAllThinking() {
  document.querySelectorAll('.opponent.thinking').forEach(op => op.classList.remove('thinking'));
}

// ---------- pile flash ----------
function flashPile(name) {
  const el = document.getElementById(name);
  if (!el) return;
  el.classList.remove('flash');
  // eslint-disable-next-line no-unused-expressions
  el.offsetWidth;
  el.classList.add('flash');
  setTimeout(() => el.classList.remove('flash'), 600);
}

// ---------- selection / buttons ----------

function clearSelection() {
  state.selectedCardIds = [];
  state.primaryCardId = null;
  state.legalTargets = null;
  state.cardType = null;
  document.querySelectorAll('.card.selected').forEach(c => c.classList.remove('selected'));
  clearTargetHighlights();
  refreshButtons();
}

function clearTargetHighlights() {
  document.querySelectorAll('.organ.target-valid, .opponent.target-valid').forEach(el => {
    el.classList.remove('target-valid');
  });
  // Listeners were attached with { once: true } so they auto-clear; but cloning is safer for changes mid-flight.
}

function refreshButtons() {
  const playBtn = document.getElementById('btn-play');
  const discardBtn = document.getElementById('btn-discard');
  const isMyTurn = state.snapshot && state.snapshot.current === 0 && state.snapshot.winner === null;

  if (!isMyTurn || state.busy) {
    playBtn.disabled = true;
    discardBtn.disabled = true;
    return;
  }
  discardBtn.disabled = !(state.selectedCardIds.length >= 1 && state.selectedCardIds.length <= 3);
  playBtn.disabled = !(
    state.primaryCardId &&
    state.legalTargets &&
    state.legalTargets.length > 0 &&
    isNoTargetCard(state.legalTargets)
  );
}

function isNoTargetCard(targets) {
  return targets.length === 1 && Object.keys(targets[0]).length === 0;
}

// ---------- menu / lifecycle ----------

document.getElementById('btn-start').addEventListener('click', startGame);
document.getElementById('btn-menu').addEventListener('click', backToMenu);
document.getElementById('btn-back-menu').addEventListener('click', backToMenu);
document.getElementById('btn-new2').addEventListener('click', startGame);

async function startGame() {
  document.getElementById('menu-screen').hidden = true;
  document.getElementById('table-room').hidden = false;
  document.getElementById('result-modal').classList.add('hidden');
  document.getElementById('confetti').hidden = true;
  document.getElementById('confetti').innerHTML = '';
  document.getElementById('log-list').innerHTML = '';
  await newGame();
}

function backToMenu() {
  document.getElementById('result-modal').classList.add('hidden');
  document.getElementById('table-room').hidden = true;
  document.getElementById('menu-screen').hidden = false;
  hideAllThinking();
  state.busy = false;
}

async function newGame() {
  state.busy = true;
  hideAllThinking();
  const data = await api('POST', '/api/new-game');
  state.gameId = data.snapshot.game_id;
  state.snapshot = data.snapshot;
  clearSelection();
  for (const e of data.events) appendLogEvent(e, false);

  // Render the dealt state without showing hand cards, then animate the deal.
  const allHandIds = state.snapshot.players[0].hand.map(c => c.id);
  renderState(state.snapshot, { hiddenHandIds: allHandIds });
  await animateInitialDeal(state.snapshot);
  renderState(state.snapshot);
  wireHandClicks();

  state.busy = false;
  setHint('Click a card to play, or select 1–3 to discard.');
  refreshButtons();
}

async function animateInitialDeal(snapshot) {
  const deckRect = getPileRect('deck');
  if (!deckRect) return;
  // Deal 3 rounds × 4 players, like a real shoe deal.
  const playersInOrder = [0, 1, 2, 3];
  const flights = [];
  for (let round = 0; round < 3; round++) {
    for (const pidx of playersInOrder) {
      const player = snapshot.players[pidx];
      const isHuman = pidx === 0;
      const cardData = isHuman ? player.hand[round] : null;
      const dest = isHuman
        ? rectOf(`#your-hand .card[data-card-id="${CSS.escape(cardData.id)}"]`)
        : rectOf(`.opponent[data-player-idx="${pidx}"] .hand-back`);
      if (!dest) continue;
      const ghost = cardData
        ? createGhostCard(cardData, { size: 'large', fast: true })
        : createGhostBack({ size: 'small' });
      const p = flyGhost(ghost, deckRect, dest, { fast: true, rot: Math.random() * 8 - 4, endScale: isHuman ? 1 : 0.55 })
        .then(() => {
          ghost.remove();
          if (isHuman) {
            const el = document.querySelector(`#your-hand .card[data-card-id="${CSS.escape(cardData.id)}"]`);
            if (el) el.style.visibility = '';
          }
        });
      flights.push(p);
      await sleep(115);
    }
  }
  await Promise.all(flights);
}

function createGhostBack(opts = {}) {
  const el = document.createElement('div');
  el.className = 'card card-back ghost';
  if (opts.fast !== false) el.classList.add('fast');
  if (opts.size === 'small') el.classList.add('small');
  if (opts.size === 'tiny')  el.classList.add('tiny');
  if (opts.size === 'large') el.classList.add('large');
  return el;
}

// ---------- hand click handling ----------

function wireHandClicks() {
  document.querySelectorAll('#your-hand .card.in-hand').forEach(cardEl => {
    // Clone to clear any prior listeners (defensive)
    const fresh = cardEl.cloneNode(true);
    cardEl.parentNode.replaceChild(fresh, cardEl);
    fresh.addEventListener('click', () => onHandCardClick(fresh));
  });
}

async function onHandCardClick(cardEl) {
  if (state.busy) return;
  if (!state.snapshot || state.snapshot.current !== 0 || state.snapshot.winner !== null) return;

  const cardId = cardEl.dataset.cardId;
  const already = state.selectedCardIds.includes(cardId);

  if (already) {
    state.selectedCardIds = state.selectedCardIds.filter(x => x !== cardId);
    cardEl.classList.remove('selected');
  } else {
    if (state.selectedCardIds.length >= 3) {
      setHint('Maximum 3 cards selected. Deselect one to add another, or click [Discard Selected].', 'warn');
      return;
    }
    state.selectedCardIds.push(cardId);
    cardEl.classList.add('selected');
  }

  state.primaryCardId = null;
  state.legalTargets = null;
  state.cardType = null;
  clearTargetHighlights();

  if (state.selectedCardIds.length === 1) {
    const onlyId = state.selectedCardIds[0];
    state.primaryCardId = onlyId;
    let data;
    try {
      data = await api('GET', `/api/legal/${state.gameId}/${onlyId}`);
    } catch (e) {
      setHint(`Error: ${e.message}`, 'warn');
      refreshButtons();
      return;
    }
    if (state.selectedCardIds.length !== 1 || state.selectedCardIds[0] !== onlyId) {
      refreshButtons();
      return;
    }
    state.legalTargets = data.targets;
    state.cardType = data.card_type;

    if (state.legalTargets.length === 0) {
      setHint('No legal target for this card — pick more cards to discard, or choose another.', 'warn');
    } else if (isNoTargetCard(state.legalTargets)) {
      setHint('Click [Play Card] to play it, or select more cards to discard instead.');
    } else {
      highlightTargets(state.legalTargets, state.cardType);
      setHint('Click a glowing target to play this card.');
    }
  } else if (state.selectedCardIds.length === 0) {
    setHint('Click a card to play, or select 1–3 to discard.');
  } else {
    setHint(`${state.selectedCardIds.length} cards selected. Click [Discard Selected].`);
  }

  refreshButtons();
}

function organSelector(playerIdx, organId) {
  if (playerIdx === 0) {
    return `#your-body .organ[data-organ-id="${CSS.escape(organId)}"]`;
  }
  return `.opponent[data-player-idx="${playerIdx}"] .organ[data-organ-id="${CSS.escape(organId)}"]`;
}

function highlightTargets(targets, cardType) {
  clearTargetHighlights();
  if (cardType === 'treatment') {
    handleTreatmentHighlight(targets);
    return;
  }
  for (const t of targets) {
    const el = document.querySelector(organSelector(t.player, t.organ_id));
    if (el) {
      el.classList.add('target-valid');
      el.addEventListener('click', () => playWithTarget(t), { once: true });
    }
  }
}

function handleTreatmentHighlight(targets) {
  const sample = targets[0];
  if (sample === undefined) return;
  if ('a' in sample && 'b' in sample) {
    setHint('Transplant: click first organ to swap, then the second.');
    transplantPicker(targets);
    return;
  }
  if ('player' in sample && !('organ_id' in sample)) {
    for (const t of targets) {
      const panel = document.querySelector(`.opponent[data-player-idx="${t.player}"]`);
      if (panel) {
        panel.classList.add('target-valid');
        panel.addEventListener('click', () => playWithTarget(t), { once: true });
      }
    }
    setHint('Medical Error: click an opponent panel to swap full bodies.');
    return;
  }
  if ('player' in sample && 'organ_id' in sample) {
    for (const t of targets) {
      const el = document.querySelector(organSelector(t.player, t.organ_id));
      if (el) {
        el.classList.add('target-valid');
        el.addEventListener('click', () => playWithTarget(t), { once: true });
      }
    }
    setHint('Organ Thief: click an opponent organ to steal.');
    return;
  }
}

function transplantPicker(targets) {
  const firstSet = new Map();
  for (const t of targets) {
    firstSet.set(`${t.a.player}|${t.a.organ_id}`, t.a);
    firstSet.set(`${t.b.player}|${t.b.organ_id}`, t.b);
  }
  for (const t of firstSet.values()) {
    const el = document.querySelector(organSelector(t.player, t.organ_id));
    if (!el) continue;
    el.classList.add('target-valid');
    el.addEventListener('click', () => {
      clearTargetHighlights();
      const validPairs = targets.filter(x =>
        (x.a.player === t.player && x.a.organ_id === t.organ_id) ||
        (x.b.player === t.player && x.b.organ_id === t.organ_id)
      );
      const bSet = new Map();
      for (const pair of validPairs) {
        const other = (pair.a.player === t.player && pair.a.organ_id === t.organ_id) ? pair.b : pair.a;
        bSet.set(`${other.player}|${other.organ_id}`, { pair, other });
      }
      for (const { pair, other } of bSet.values()) {
        const el2 = document.querySelector(organSelector(other.player, other.organ_id));
        if (!el2) continue;
        el2.classList.add('target-valid');
        el2.addEventListener('click', () => playWithTarget(pair), { once: true });
      }
      setHint('Transplant: now pick the second organ.');
    }, { once: true });
  }
}

async function playWithTarget(target) {
  if (!state.primaryCardId || state.busy) return;
  await sendPlay(state.primaryCardId, target);
}

document.getElementById('btn-play').addEventListener('click', async () => {
  if (!state.primaryCardId || state.busy) return;
  if (state.legalTargets && isNoTargetCard(state.legalTargets)) {
    await sendPlay(state.primaryCardId, {});
  }
});

document.getElementById('btn-discard').addEventListener('click', async () => {
  if (state.selectedCardIds.length < 1 || state.busy) return;
  await sendDiscard(state.selectedCardIds.slice(0, 3));
});

// ---------- send moves ----------

async function sendPlay(cardId, target) {
  state.busy = true; refreshButtons();
  clearSelection();
  try {
    const before = state.snapshot;
    const data = await api('POST', `/api/play/${state.gameId}`, { card_id: cardId, targets: target });
    await applyStepResponse(data, before);
    await runAutoLoop();
  } catch (e) {
    setHint(`Error: ${e.message}`, 'warn');
  }
  state.busy = false; refreshButtons();
}

async function sendDiscard(cardIds) {
  state.busy = true; refreshButtons();
  clearSelection();
  try {
    const before = state.snapshot;
    const data = await api('POST', `/api/discard/${state.gameId}`, { card_ids: cardIds });
    await applyStepResponse(data, before);
    await runAutoLoop();
  } catch (e) {
    setHint(`Error: ${e.message}`, 'warn');
  }
  state.busy = false; refreshButtons();
}

// ---------- the auto-step loop (drives bot turns between human turns) ----------

async function runAutoLoop() {
  // Repeatedly: if game ongoing AND not (human turn with cards), advance one step
  let guard = 0;
  while (true) {
    if (++guard > 200) break; // safety
    if (!state.snapshot || state.snapshot.winner !== null) break;
    const cur = state.snapshot.current;
    const me = state.snapshot.players[0];
    if (cur === 0 && me.hand && me.hand.length > 0) return; // human's turn, has cards

    if (cur === 0) {
      setHint('You have no cards — drawing fresh hand…');
      await sleep(700);
    } else {
      const bot = state.snapshot.players[cur];
      showThinking(cur);
      setHint(`${bot.name} is thinking…`);
      const delay = Math.floor(THINK_MIN_MS + Math.random() * (THINK_MAX_MS - THINK_MIN_MS));
      await sleep(delay);
      hideThinking(cur);
    }

    const before = state.snapshot;
    let data;
    try {
      data = await api('POST', `/api/auto-step/${state.gameId}`);
    } catch (e) {
      setHint(`Error: ${e.message}`, 'warn');
      return;
    }
    await applyStepResponse(data, before);
  }

  if (state.snapshot && state.snapshot.winner !== null) {
    showResult(state.snapshot);
  }
}

// ---------- apply step + animate ----------

async function applyStepResponse(data, before) {
  const step = data.step;
  const after = data.snapshot;

  if (!step) {
    state.snapshot = after;
    renderState(after);
    wireHandClicks();
    return;
  }

  // Log events
  for (const ev of (step.events || [])) {
    appendLogEvent(ev, true);
  }

  await animateStep(step, before, after);

  state.snapshot = after;
  renderState(after);

  // Post-step: animate the human's drawn cards from deck into hand slots.
  await animateHumanDraw(before, after);

  wireHandClicks();
}

async function animateHumanDraw(before, after) {
  const beforeHuman = before.players[0];
  const afterHuman = after.players[0];
  if (!afterHuman.hand || !beforeHuman.hand) return;
  const beforeIds = new Set(beforeHuman.hand.map(c => c.id));
  const newCards = afterHuman.hand.filter(c => !beforeIds.has(c.id));
  if (!newCards.length) return;
  const deckRect = getPileRect('deck');
  if (!deckRect) return;
  const flights = [];
  for (const c of newCards) {
    const realEl = document.querySelector(`#your-hand .card[data-card-id="${CSS.escape(c.id)}"]`);
    const dest = realEl ? realEl.getBoundingClientRect() : null;
    if (!dest) continue;
    if (realEl) realEl.style.visibility = 'hidden';
    const ghost = createGhostCard(c, { size: 'large', fast: true });
    const p = flyGhost(ghost, deckRect, dest, { fast: true, rot: Math.random() * 6 - 3, endScale: 1 })
      .then(() => {
        ghost.remove();
        if (realEl) realEl.style.visibility = '';
      });
    flights.push(p);
    await sleep(90);
  }
  await Promise.all(flights);
}

async function animateStep(step, before, after) {
  if (step.action === 'pass') {
    await sleep(160);
    return;
  }

  // Compute snapshot diff to know what visuals to do
  const diff = diffSnapshots(before, after);

  if (step.action === 'discard') {
    await animateDiscardSequence(step, before);
    return;
  }

  // action === 'play'
  const card = step.card;
  const targets = step.targets || {};

  // === PRE-ANIMATION PHASE: organ destruction on old DOM ===
  // Destruction happens AFTER ghost lands on the target organ.

  // Decide flight destination (in current/before DOM coords).
  // For ORGAN play, the destination is the future position — render after first.
  // Strategy:
  //   - For ORGAN: pre-render new state with phantom new organ; fly to its rect; reveal.
  //   - For others: capture target rect on OLD DOM; fly; then handle special cases.

  const isOrganPlay = card.type === 'organ';
  let srcRect, srcEl, dstRect;

  if (isOrganPlay) {
    [srcRect, srcEl] = getActorHandRect(step.actor, card);
    if (srcEl) srcEl.style.visibility = 'hidden';

    // Pre-render new state with the new organ phantom-hidden.
    renderState(after, { phantomOrganIds: [card.id] });
    // (Hand row was re-rendered; the hidden source no longer needed.)
    dstRect = getOrganRect(step.actor, card.id);
    if (!dstRect) dstRect = getPileRect('discard'); // shouldn't happen

    const ghost = createGhostCard(card);
    await flyGhost(ghost, srcRect, dstRect, { endScale: 1 });
    ghost.remove();

    // Reveal phantom
    const placed = getOrganEl(step.actor, card.id);
    if (placed) {
      placed.style.transition = 'opacity 0.25s ease, transform 0.35s cubic-bezier(0.2, 0.8, 0.2, 1)';
      placed.style.opacity = '1';
      placed.style.transform = 'scale(1)';
      placed.classList.remove('phantom');
      placed.classList.add('just-placed', 'playing');
      setTimeout(() => placed.classList.remove('just-placed', 'playing'), 800);
    }
    return;
  }

  // Non-organ play. Capture source on current (old) DOM.
  [srcRect, srcEl] = getActorHandRect(step.actor, card);
  if (srcEl) srcEl.style.visibility = 'hidden';

  // Determine destination on OLD DOM:
  // - virus/medicine: target organ if still present in after, else discard pile
  // - treatment: discard pile (the card itself always discards)
  let dstSelector = null;
  let willDestroy = null;  // organId to destroy after ghost lands
  let willPulseOrgan = null;

  if (card.type === 'virus' || card.type === 'medicine') {
    const t = targets;
    const orgEl = getOrganEl(t.player, t.organ_id);
    if (orgEl) {
      dstRect = orgEl.getBoundingClientRect();
      // Detect destruction (organ id missing in after)
      const beforeHas = before.players.some(p => p.body.some(o => o.card.id === t.organ_id));
      const afterHas = after.players.some(p => p.body.some(o => o.card.id === t.organ_id));
      if (beforeHas && !afterHas) willDestroy = t.organ_id;
      else willPulseOrgan = t.organ_id;
    } else {
      dstRect = getPileRect('discard');
    }
  } else if (card.type === 'treatment') {
    dstRect = getPileRect('discard');
  } else {
    dstRect = getPileRect('discard');
  }

  if (!dstRect) dstRect = { left: window.innerWidth/2 - 50, top: window.innerHeight/2 - 60, width: 100, height: 120 };

  // Fly ghost
  const ghost = createGhostCard(card);
  await flyGhost(ghost, srcRect, dstRect, { endScale: 0.94 });

  // Pulse target organ visually (on OLD DOM, before re-render)
  if (willPulseOrgan) {
    const el = getOrganEl(targets.player, willPulseOrgan);
    if (el) {
      el.classList.add('playing');
      setTimeout(() => el.classList.remove('playing'), 700);
    }
  }

  // Destruction animation on OLD DOM (ghost vanishes alongside)
  if (willDestroy) {
    const el = getOrganEl(targets.player, willDestroy);
    vanishGhost(ghost);
    if (el) {
      el.classList.add('destroying');
      await sleep(720);
    }
    flashPile('discard');
  } else if (card.type === 'treatment') {
    flashPile('discard');
    ghost.remove();
  } else {
    ghost.remove();
  }

  // Treatment-specific multi-effects (render new state, then post-effects)
  if (card.type === 'treatment') {
    await applyTreatmentEffects(card, step, before, after, diff);
  }
}

async function animateDiscardSequence(step, before) {
  const cards = step.cards || [];
  if (!cards.length) return;
  const pile = getPileRect('discard');
  if (!pile) return;

  const ghosts = [];
  for (let i = 0; i < cards.length; i++) {
    const c = cards[i];
    const [src, srcEl] = getActorHandRect(step.actor, c);
    if (srcEl) srcEl.style.visibility = 'hidden';
    const ghost = createGhostCard(c, { fast: true });
    ghosts.push({ ghost, src, c });
    // stagger
    flyGhost(ghost, src, pile, { fast: true, endScale: 0.85, rot: (Math.random() * 16 - 8) });
    await sleep(85);
  }
  await sleep(FLIGHT_FAST_MS);
  for (const g of ghosts) g.ghost.remove();
  flashPile('discard');
}

// Special handling for treatments that cause multi-piece visual changes.
async function applyTreatmentEffects(card, step, before, after, diff) {
  const kind = card.treatment;

  if (kind === 'transplant' || kind === 'organ_thief') {
    // One or two organs moved between players. Animate each moved organ.
    if (!diff.moved.length) return;
    const layer = document.getElementById(ANIM_LAYER_ID);
    const ghosts = [];
    for (const m of diff.moved) {
      const srcRect = getOrganRect(m.from, m.organId);
      // Pre-render to find dest rect:
      // We can't render here without disrupting other ghosts; capture from old DOM only
      // and then render once at the end. Use a snapshot diff trick: temporarily render
      // after-state with the moved organs phantom, capture their rect, then keep render.
      // Simpler: render new state first then use that for destination.
      ghosts.push({ srcRect, m });
    }
    // Render new state with all moved organs phantom-hidden
    const phantomIds = diff.moved.map(x => x.organId);
    renderState(after, { phantomOrganIds: phantomIds });
    for (const g of ghosts) {
      const dstRect = getOrganRect(g.m.to, g.m.organId);
      const after_org = after.players.find(p => p.id === g.m.to)?.body.find(o => o.card.id === g.m.organId);
      if (!dstRect || !after_org) continue;
      const ghost = buildOrgan(after_org, { size: 'tiny' });
      ghost.style.position = 'absolute';
      ghost.style.left = (g.srcRect.left + g.srcRect.width / 2 - 25) + 'px';
      ghost.style.top  = (g.srcRect.top  + g.srcRect.height / 2 - 36) + 'px';
      ghost.style.transition = 'transform 0.55s cubic-bezier(0.2, 0.8, 0.2, 1), opacity 0.5s ease';
      ghost.style.zIndex = '60';
      layer.appendChild(ghost);
      // eslint-disable-next-line no-unused-expressions
      ghost.offsetHeight;
      const dx = (dstRect.left + dstRect.width/2) - (g.srcRect.left + g.srcRect.width/2);
      const dy = (dstRect.top + dstRect.height/2) - (g.srcRect.top + g.srcRect.height/2);
      ghost.style.transform = `translate(${dx}px, ${dy}px)`;
    }
    await sleep(560);
    layer.querySelectorAll('.organ').forEach(el => el.remove());
    // Reveal destination
    for (const m of diff.moved) {
      const el = getOrganEl(m.to, m.organId);
      if (el) {
        el.classList.remove('phantom');
        el.style.opacity = '1';
        el.style.transform = 'scale(1)';
        el.classList.add('just-placed');
        setTimeout(() => el.classList.remove('just-placed'), 700);
      }
    }
    return;
  }

  if (kind === 'medical_error') {
    // Bodies swap entirely. Visually: flash both player boards, then rerender.
    const actorEl = step.actor === 0
      ? document.querySelector('.player-board')
      : document.querySelector(`.opponent[data-player-idx="${step.actor}"]`);
    const otherIdx = step.targets.player;
    const otherEl = otherIdx === 0
      ? document.querySelector('.player-board')
      : document.querySelector(`.opponent[data-player-idx="${otherIdx}"]`);
    if (actorEl) {
      actorEl.style.transition = 'transform 0.4s ease, filter 0.4s ease, box-shadow 0.4s ease';
      actorEl.style.transform = 'scale(0.96)';
      actorEl.style.filter = 'hue-rotate(40deg) brightness(1.18)';
      actorEl.style.boxShadow = '0 0 30px rgba(245,184,0,0.55)';
    }
    if (otherEl) {
      otherEl.style.transition = 'transform 0.4s ease, filter 0.4s ease, box-shadow 0.4s ease';
      otherEl.style.transform = 'scale(1.04)';
      otherEl.style.filter = 'hue-rotate(-40deg) brightness(1.18)';
      otherEl.style.boxShadow = '0 0 30px rgba(179,91,184,0.55)';
    }
    await sleep(450);
    if (actorEl) { actorEl.style.transform = ''; actorEl.style.filter = ''; actorEl.style.boxShadow = ''; }
    if (otherEl) { otherEl.style.transform = ''; otherEl.style.filter = ''; otherEl.style.boxShadow = ''; }
    return;
  }

  if (kind === 'latex_glove') {
    // Every non-actor player's hand cards fly to discard pile.
    const pile = getPileRect('discard');
    const layer = document.getElementById(ANIM_LAYER_ID);
    const promises = [];
    // Hide human's hand cards visually if human is a victim
    const humanCardsHidden = [];
    if (step.actor !== 0) {
      const humanCardEls = document.querySelectorAll('#your-hand .card.in-hand');
      humanCardEls.forEach(el => {
        humanCardsHidden.push(el);
        el.style.visibility = 'hidden';
      });
    }
    for (let pidx = 0; pidx <= 3; pidx++) {
      if (pidx === step.actor) continue;
      const before_p = before.players.find(p => p.id === pidx);
      const count = before_p ? before_p.hand_count : 0;
      if (!count) continue;
      let originRect;
      let cardData = null;
      if (pidx === 0) {
        originRect = rectOf('#your-hand');
        cardData = before_p.hand || null;
      } else {
        const back = document.querySelector(`.opponent[data-player-idx="${pidx}"] .hand-back`);
        originRect = back ? back.getBoundingClientRect() : null;
      }
      if (!originRect) continue;
      const flyCount = Math.min(count, 3);
      for (let i = 0; i < flyCount; i++) {
        const ghost = (cardData && cardData[i])
          ? createGhostCard(cardData[i], { size: pidx === 0 ? 'large' : 'small', fast: true })
          : createGhostBack({ size: 'small' });
        layer.appendChild(ghost);
        // Position around the origin rect
        const sx = originRect.left + originRect.width/2 + (i - (flyCount-1)/2) * (pidx === 0 ? 130 : 18);
        const sy = originRect.top + originRect.height/2;
        const w = ghost.offsetWidth || 64;
        const h = ghost.offsetHeight || 92;
        ghost.style.left = (sx - w/2) + 'px';
        ghost.style.top  = (sy - h/2) + 'px';
        // eslint-disable-next-line no-unused-expressions
        ghost.offsetHeight;
        await sleep(18);
        const dx = (pile.left + pile.width/2) - sx;
        const dy = (pile.top + pile.height/2) - sy;
        ghost.style.transform = `translate(${dx}px, ${dy}px) rotate(${Math.random()*40-20}deg) scale(0.5)`;
        promises.push(sleep(FLIGHT_FAST_MS).then(() => ghost.remove()));
        await sleep(70);
      }
    }
    await Promise.all(promises);
    flashPile('discard');
    // Don't need to un-hide human cards: re-render will replace the DOM
    return;
  }

  if (kind === 'contagion') {
    // Viruses moved from actor's infected organs to opponents' free organs.
    // Detect virus movements by comparing attached arrays across snapshots.
    const moves = detectVirusMovements(before, after, step.actor);
    if (!moves.length) return;
    const layer = document.getElementById(ANIM_LAYER_ID);
    for (const mv of moves) {
      const srcEl = getOrganEl(step.actor, mv.fromOrganId);
      const dstEl = getOrganEl(mv.toPlayer, mv.toOrganId);
      if (!srcEl || !dstEl) continue;
      const srcR = srcEl.getBoundingClientRect();
      const dstR = dstEl.getBoundingClientRect();
      const ghost = buildCard(mv.virusCard, { size: 'small' });
      ghost.classList.add('ghost', 'fast');
      ghost.style.left = (srcR.left + srcR.width/2 - 32) + 'px';
      ghost.style.top  = (srcR.top  + srcR.height/2 - 46) + 'px';
      layer.appendChild(ghost);
      // eslint-disable-next-line no-unused-expressions
      ghost.offsetHeight;
      await sleep(20);
      const dx = (dstR.left + dstR.width/2) - (srcR.left + srcR.width/2);
      const dy = (dstR.top + dstR.height/2) - (srcR.top + srcR.height/2);
      ghost.style.transform = `translate(${dx}px, ${dy}px) scale(0.9)`;
      await sleep(FLIGHT_FAST_MS);
      ghost.remove();
    }
    return;
  }
}

function detectVirusMovements(before, after, actorIdx) {
  // For each virus card id, find where it was attached before vs after.
  const beforePos = new Map();
  for (const p of before.players) {
    for (const o of p.body) {
      for (const c of o.attached) {
        if (c.type === 'virus') beforePos.set(c.id, { playerId: p.id, organId: o.card.id });
      }
    }
  }
  const afterPos = new Map();
  for (const p of after.players) {
    for (const o of p.body) {
      for (const c of o.attached) {
        if (c.type === 'virus') afterPos.set(c.id, { playerId: p.id, organId: o.card.id, card: c });
      }
    }
  }
  const moves = [];
  for (const [id, beforeP] of beforePos) {
    if (beforeP.playerId !== actorIdx) continue;
    const afterP = afterPos.get(id);
    if (!afterP) continue;
    if (afterP.playerId !== beforeP.playerId || afterP.organId !== beforeP.organId) {
      moves.push({
        virusCard: afterP.card,
        fromOrganId: beforeP.organId,
        toPlayer: afterP.playerId,
        toOrganId: afterP.organId,
      });
    }
  }
  return moves;
}

// ---------- result modal ----------

function showResult(snapshot) {
  hideAllThinking();
  const inner = document.getElementById('result-inner');
  const title = document.getElementById('result-title');
  const msg = document.getElementById('result-msg');
  inner.classList.remove('lose');
  if (snapshot.winner === 0) {
    title.textContent = '🎉 You Win!';
    msg.textContent = 'You completed 4 healthy organs in 4 distinct colors.';
    launchConfetti();
  } else {
    inner.classList.add('lose');
    const winner = snapshot.players[snapshot.winner];
    title.textContent = `${winner.name} Wins`;
    msg.textContent = 'Better luck next time — try again?';
  }
  document.getElementById('result-modal').classList.remove('hidden');
}

function launchConfetti() {
  const container = document.getElementById('confetti');
  container.hidden = false;
  container.innerHTML = '';
  const colors = ['#3aa55c', '#f5b800', '#3b82f6', '#d64545', '#b35bb8', '#46c06d'];
  const count = 70;
  for (let i = 0; i < count; i++) {
    const s = document.createElement('span');
    s.style.left = Math.random() * 100 + '%';
    s.style.background = colors[Math.floor(Math.random() * colors.length)];
    s.style.animationDuration = (2 + Math.random() * 2) + 's';
    s.style.animationDelay = (Math.random() * 1.2) + 's';
    s.style.transform = `rotate(${Math.random()*360}deg)`;
    container.appendChild(s);
  }
  setTimeout(() => { container.hidden = true; container.innerHTML = ''; }, 5000);
}
