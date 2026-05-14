// =====================================================================
// VIRUS! — State → DOM rendering. Pure: no fetch calls here.
// =====================================================================

const ORGAN_ICON = {
  red: 'icon-heart',
  green: 'icon-stomach',
  blue: 'icon-brain',
  yellow: 'icon-bone',
  multi: 'icon-multi',
};

const TREATMENT_ICON = {
  transplant: 'icon-transplant',
  organ_thief: 'icon-thief',
  contagion: 'icon-contagion',
  latex_glove: 'icon-glove',
  medical_error: 'icon-error',
};

const TREATMENT_LABEL = {
  transplant: 'Transplant',
  organ_thief: 'Organ Thief',
  contagion: 'Contagion',
  latex_glove: 'Latex Glove',
  medical_error: 'Medical Error',
};

const COLOR_LABEL = {
  red: 'Red',
  green: 'Green',
  blue: 'Blue',
  yellow: 'Yellow',
  multi: 'Multi',
};

function iconForCard(card) {
  if (card.type === 'organ') return ORGAN_ICON[card.color] || 'icon-heart';
  if (card.type === 'virus') return 'icon-virus';
  if (card.type === 'medicine') return 'icon-pill';
  if (card.type === 'treatment') return TREATMENT_ICON[card.treatment] || 'icon-pill';
  return 'icon-heart';
}

function labelForCard(card) {
  if (card.type === 'organ') return 'Organ';
  if (card.type === 'virus') return 'Virus';
  if (card.type === 'medicine') return 'Medicine';
  if (card.type === 'treatment') return TREATMENT_LABEL[card.treatment] || 'Treatment';
  return '';
}

function bottomLabelForCard(card) {
  if (card.type === 'organ' || card.type === 'virus' || card.type === 'medicine') {
    return COLOR_LABEL[card.color] || labelForCard(card);
  }
  if (card.type === 'treatment') return TREATMENT_LABEL[card.treatment] || 'Treatment';
  return labelForCard(card);
}

function buildCard(card, opts = {}) {
  const el = document.createElement('div');
  el.className = 'card';
  if (opts.size === 'tiny') el.classList.add('tiny');
  else if (opts.size === 'small') el.classList.add('small');
  else if (opts.size === 'large') el.classList.add('large');
  el.dataset.cardId = card.id;
  el.dataset.type = card.type;
  el.dataset.color = card.color || '';
  if (card.treatment) el.dataset.treatment = card.treatment;

  const iconHref = iconForCard(card);

  const band = document.createElement('div');
  band.className = 'band';
  band.textContent = labelForCard(card);
  el.appendChild(band);

  // Inner art panel with central icon + corner marks (like real Virus! cards).
  const art = document.createElement('div');
  art.className = 'card-art';

  const cornerTL = document.createElement('span');
  cornerTL.className = 'corner tl';
  cornerTL.innerHTML = `<svg viewBox="0 0 64 64"><use xlink:href="#${iconHref}"/></svg>`;
  art.appendChild(cornerTL);

  const cornerBR = document.createElement('span');
  cornerBR.className = 'corner br';
  cornerBR.innerHTML = `<svg viewBox="0 0 64 64"><use xlink:href="#${iconHref}"/></svg>`;
  art.appendChild(cornerBR);

  const iconWrap = document.createElement('div');
  iconWrap.className = 'icon-wrap';
  iconWrap.innerHTML = `<svg viewBox="0 0 64 64"><use xlink:href="#${iconHref}"/></svg>`;
  art.appendChild(iconWrap);

  // Subtle gloss highlight overlay for the 3D look.
  const gloss = document.createElement('span');
  gloss.className = 'gloss';
  art.appendChild(gloss);

  el.appendChild(art);

  const label = document.createElement('div');
  label.className = 'label';
  label.textContent = bottomLabelForCard(card);
  el.appendChild(label);

  return el;
}

function buildOrgan(organObj, opts = {}) {
  const size = opts.size || 'normal';
  const wrap = document.createElement('div');
  wrap.className = 'organ';
  if (size === 'tiny') wrap.classList.add('small-stack');
  wrap.dataset.status = organObj.status;
  wrap.dataset.organId = organObj.card.id;

  const organCard = buildCard(organObj.card, { size: size === 'normal' ? null : size });
  organCard.classList.add('organ-card');
  wrap.appendChild(organCard);

  if (organObj.attached.length) {
    const att = document.createElement('div');
    att.className = 'attached-row';
    for (const c of organObj.attached) {
      const ac = buildCard(c, { size: size === 'normal' ? 'small' : 'tiny' });
      ac.classList.add('attached');
      att.appendChild(ac);
    }
    wrap.appendChild(att);
  }
  return wrap;
}

function renderBodyInto(targetEl, body, opts = {}) {
  targetEl.innerHTML = '';
  if (!body || body.length === 0) {
    const e = document.createElement('div');
    e.className = 'empty-body';
    e.textContent = opts.placeholder || '— no organs —';
    targetEl.appendChild(e);
    return;
  }
  for (const organ of body) {
    const el = buildOrgan(organ, opts);
    if (opts.phantomIds && opts.phantomIds.includes(organ.card.id)) {
      el.style.opacity = '0';
      el.style.transform = 'scale(0.6)';
      el.classList.add('phantom');
    }
    targetEl.appendChild(el);
  }
}

function renderHand(targetEl, hand, opts = {}) {
  targetEl.innerHTML = '';
  if (!hand || hand.length === 0) {
    const e = document.createElement('div');
    e.className = 'empty-body';
    e.textContent = '(no cards in hand — drawing soon)';
    targetEl.appendChild(e);
    return;
  }
  for (const c of hand) {
    const card = buildCard(c);
    card.classList.add('in-hand');
    if (opts.dealing) card.classList.add('dealing');
    if (opts.hiddenIds && opts.hiddenIds.includes(c.id)) card.style.visibility = 'hidden';
    targetEl.appendChild(card);
  }
}

function renderHandBack(targetEl, count) {
  targetEl.innerHTML = '';
  const max = Math.min(count, 5);
  for (let i = 0; i < max; i++) {
    const d = document.createElement('div');
    d.className = 'back';
    targetEl.appendChild(d);
  }
}

function renderOpponentSeat(seatEl, player, isCurrent, isThinking, phantomIds) {
  const op = seatEl.querySelector('.opponent');
  op.dataset.playerIdx = player.id;
  op.classList.toggle('is-current', isCurrent);
  op.classList.toggle('thinking', !!isThinking);

  const role = op.querySelector('.seat-name .role');
  const hcNum = op.querySelector('.seat-name .hand-count .hc-num');
  // We keep the bot's friendly persona name in the markup (Vex / Dr. Nova / Pixel)
  // and surface the backend's "Bot N" label as the role subtitle.
  if (role) role.textContent = player.name;
  if (hcNum) hcNum.textContent = player.hand_count;

  const bodyEl = op.querySelector('.body-row');
  // `small` size keeps opponent organ cards readable AND leaves room for
  // attached virus/medicine chips to remain visible below the organ.
  renderBodyInto(bodyEl, player.body, { size: 'small', phantomIds: phantomIds || [] });

  const back = op.querySelector('.hand-back');
  renderHandBack(back, player.hand_count);
}

function renderState(snapshot, opts = {}) {
  document.getElementById('deck-count').textContent = snapshot.deck_count;
  document.getElementById('discard-count').textContent = snapshot.discard_count;

  const turnBanner = document.getElementById('turn-banner');
  const cur = snapshot.players[snapshot.current];
  const isYourTurn = snapshot.current === 0;
  if (snapshot.winner !== null) {
    const winName = snapshot.players[snapshot.winner].name;
    turnBanner.textContent = `Game over — ${winName} wins!`;
  } else if (isYourTurn) {
    turnBanner.textContent = `Turn ${snapshot.turn_number} — Your turn`;
  } else {
    turnBanner.textContent = `Turn ${snapshot.turn_number} — ${cur.name}'s turn…`;
  }
  turnBanner.classList.toggle('your-turn', isYourTurn && snapshot.winner === null);

  const turnPill = document.getElementById('turn-pill');
  if (isYourTurn && snapshot.winner === null) {
    turnPill.textContent = 'Your turn';
    turnPill.classList.remove('waiting');
  } else if (snapshot.winner !== null) {
    turnPill.textContent = (snapshot.winner === 0) ? 'You won' : 'Game over';
    turnPill.classList.add('waiting');
  } else {
    turnPill.textContent = `${cur.name}'s turn…`;
    turnPill.classList.add('waiting');
  }

  // Seat mapping: players[1] = left, players[2] = top, players[3] = right
  const seatTop   = document.querySelector('.seat-top');
  const seatLeft  = document.querySelector('.seat-left');
  const seatRight = document.querySelector('.seat-right');
  const currentIdx = snapshot.current;
  const thinkingIdx = (opts.thinkingPlayer != null) ? opts.thinkingPlayer : null;
  const phantomIds = opts.phantomOrganIds || [];
  renderOpponentSeat(seatLeft,  snapshot.players[1], currentIdx === 1, thinkingIdx === 1, phantomIds);
  renderOpponentSeat(seatTop,   snapshot.players[2], currentIdx === 2, thinkingIdx === 2, phantomIds);
  renderOpponentSeat(seatRight, snapshot.players[3], currentIdx === 3, thinkingIdx === 3, phantomIds);

  // Player board
  const playerBoard = document.querySelector('.player-board');
  playerBoard.classList.toggle('is-current', isYourTurn && snapshot.winner === null);

  const you = snapshot.players[0];
  renderBodyInto(
    document.getElementById('your-body'),
    you.body,
    {
      placeholder: 'Play an organ card to begin building your body.',
      phantomIds: phantomIds,
    }
  );
  renderHand(
    document.getElementById('your-hand'),
    you.hand || [],
    {
      dealing: opts.dealing,
      hiddenIds: opts.hiddenHandIds || [],
    }
  );
}

// ---------- Log ----------
const LOG_LIMIT = 4;
function appendLogEvent(text, fresh = true) {
  const list = document.getElementById('log-list');
  const li = document.createElement('li');
  if (fresh) li.classList.add('new');
  li.textContent = text;
  list.appendChild(li);
  while (list.children.length > LOG_LIMIT) {
    list.removeChild(list.firstChild);
  }
  list.scrollTop = list.scrollHeight;
  if (fresh) setTimeout(() => li.classList.remove('new'), 1800);
}
