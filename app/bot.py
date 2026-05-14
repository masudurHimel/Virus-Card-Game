"""Heuristic Hard-difficulty bot.

choose_action(state, bot_idx) -> (kind, payload)
    kind="play"    -> payload = {"card_id": str, "targets": dict}
    kind="discard" -> payload = {"card_ids": [str, ...]}

Scoring is read-only: we never apply moves during evaluation, only inspect
the proposed (card, target) against current state.
"""
from __future__ import annotations

import random
from typing import Dict, List, Optional, Tuple

from .actions import legal_play_targets
from .models import (
    Card,
    CardType,
    Color,
    GameState,
    Organ,
    OrganStatus,
    Player,
    TreatmentKind,
)

ALL_COLORS = {Color.RED, Color.GREEN, Color.BLUE, Color.YELLOW}


def _distinct_colors(player: Player, healthy_only: bool = True) -> set:
    cols = set()
    for o in player.body:
        if healthy_only and not o.is_healthy:
            continue
        cols.add(o.card.color)
    return cols


def _color_count_toward_win(player: Player) -> int:
    """How many of the 4 colors a player is on track to cover (healthy only)."""
    healthy = [o for o in player.body if o.is_healthy]
    fixed = {o.card.color for o in healthy if o.card.color != Color.MULTI}
    wilds = sum(1 for o in healthy if o.card.color == Color.MULTI)
    missing = ALL_COLORS - fixed
    return len(fixed) + min(wilds, len(missing))


def _threat_score(player: Player) -> int:
    return _color_count_toward_win(player)


def _leader_idx(state: GameState, exclude: int) -> Optional[int]:
    best_i, best_s = None, -1
    for i, p in enumerate(state.players):
        if i == exclude:
            continue
        s = _threat_score(p)
        if s > best_s:
            best_s, best_i = s, i
    return best_i


def _find_organ(player: Player, organ_id: str) -> Optional[Organ]:
    for o in player.body:
        if o.card.id == organ_id:
            return o
    return None


# ---------- scoring ----------

def _score_organ_play(state: GameState, bot_idx: int, card: Card) -> float:
    me = state.players[bot_idx]
    healthy = [o for o in me.body if o.is_healthy]
    fixed = {o.card.color for o in healthy if o.card.color != Color.MULTI}
    wilds_count = sum(1 for o in healthy if o.card.color == Color.MULTI)
    current_progress = _color_count_toward_win(me)

    # Estimate post-play progress
    if card.color == Color.MULTI:
        new_progress = min(4, current_progress + 1)
    elif card.color in fixed:
        return -30.0  # duplicate color — should not happen (filtered by legal)
    else:
        new_progress = min(4, current_progress + 1)

    if new_progress >= 4:
        return 9999.0  # winning move
    score = 50.0
    if new_progress == 3:
        score += 25  # one step from winning
    if card.color == Color.MULTI and wilds_count == 0 and len(fixed) < 4:
        score += 10  # wild gives flexibility
    return score


def _score_virus(state: GameState, bot_idx: int, card: Card, target: Dict) -> float:
    target_idx = target["player"]
    victim = state.players[target_idx]
    organ = _find_organ(victim, target["organ_id"])
    if organ is None:
        return -1000.0

    leader = _leader_idx(state, exclude=bot_idx)
    is_leader = target_idx == leader
    victim_progress = _color_count_toward_win(victim)

    base = 40.0
    if is_leader:
        base += 25
    if victim_progress >= 3:
        base += 30  # they're close to winning — must disrupt
    if organ.status == OrganStatus.INFECTED:
        base += 25  # destroys organ
    elif organ.status == OrganStatus.VACCINATED:
        base += 10  # strips vaccine
    if card.color == Color.MULTI:
        base -= 12  # save wilds when possible

    # Bonus if removing one of their distinct healthy colors
    if organ.is_healthy and organ.card.color in _distinct_colors(victim):
        base += 12
    return base


def _score_medicine(state: GameState, bot_idx: int, card: Card, target: Dict) -> float:
    me = state.players[bot_idx]
    organ = _find_organ(me, target["organ_id"])
    if organ is None:
        return -1000.0

    base = 0.0
    if organ.status == OrganStatus.INFECTED:
        base += 100  # cure
    elif organ.status == OrganStatus.VACCINATED:
        # Immunize — only valuable if this color is one we want to keep,
        # and especially valuable if it's likely to be attacked.
        base += 55
        # Higher value if we're close to winning with this organ
        progress = _color_count_toward_win(me)
        if progress >= 3:
            base += 25
    else:  # FREE
        # Vaccinating a free organ: useful but lower priority than other plays
        base += 18
        progress = _color_count_toward_win(me)
        if progress >= 3:
            base += 10

    if card.color == Color.MULTI:
        # Only use wild medicine when no colored option fits
        base -= 12
    return base


def _score_treatment(state: GameState, bot_idx: int, card: Card, target: Dict) -> float:
    me = state.players[bot_idx]
    kind = card.treatment

    if kind == TreatmentKind.TRANSPLANT:
        # Useful if it gives me a color I lack while taking from leader,
        # or breaks up a leader's win path.
        a = target["a"]
        b = target["b"]
        leader = _leader_idx(state, exclude=bot_idx)
        score = 25.0
        if a["player"] == bot_idx or b["player"] == bot_idx:
            score += 10
        if a["player"] == leader or b["player"] == leader:
            score += 30
        return score

    if kind == TreatmentKind.ORGAN_THIEF:
        victim_idx = target["player"]
        victim = state.players[victim_idx]
        organ = _find_organ(victim, target["organ_id"])
        leader = _leader_idx(state, exclude=bot_idx)
        if organ is None:
            return -1000
        score = 60.0
        if victim_idx == leader:
            score += 25
        # bonus if stolen color completes 4th color for me
        my_colors = _distinct_colors(me)
        if organ.card.color not in my_colors and len(my_colors) >= 3:
            score += 40  # this could win
        return score

    if kind == TreatmentKind.CONTAGION:
        # Count how many viruses on my infected organs would have valid destinations
        movable = 0
        for o in me.body:
            if o.status != OrganStatus.INFECTED:
                continue
            for v in o.attached:
                if v.type != CardType.VIRUS:
                    continue
                # Check at least one destination exists
                for i, p in enumerate(state.players):
                    if i == bot_idx:
                        continue
                    for dest in p.body:
                        if dest.status != OrganStatus.FREE:
                            continue
                        if dest.matches_color(v.color) or v.color == Color.MULTI:
                            movable += 1
                            break
                    else:
                        continue
                    break
        return 25.0 * movable

    if kind == TreatmentKind.LATEX_GLOVE:
        # Count opponents with strong hands
        full_hands = sum(1 for i, p in enumerate(state.players) if i != bot_idx and len(p.hand) >= 2)
        leader = _leader_idx(state, exclude=bot_idx)
        score = 25.0 + 12 * full_hands
        if leader is not None and len(state.players[leader].hand) >= 2:
            score += 15
        return score

    if kind == TreatmentKind.MEDICAL_ERROR:
        # Swap with strongest opponent if I'm weak.
        my_progress = _color_count_toward_win(me)
        target_idx = target["player"]
        their_progress = _color_count_toward_win(state.players[target_idx])
        diff = their_progress - my_progress
        if diff >= 2:
            return 110.0 + 20 * diff
        if diff == 1:
            return 35.0
        return -10.0

    return 0.0


def _score_action(state: GameState, bot_idx: int, card: Card, target: Dict) -> float:
    if card.type == CardType.ORGAN:
        return _score_organ_play(state, bot_idx, card)
    if card.type == CardType.VIRUS:
        return _score_virus(state, bot_idx, card, target)
    if card.type == CardType.MEDICINE:
        return _score_medicine(state, bot_idx, card, target)
    if card.type == CardType.TREATMENT:
        return _score_treatment(state, bot_idx, card, target)
    return 0.0


# ---------- top-level choice ----------

def choose_action(state: GameState, bot_idx: int) -> Tuple[str, Dict]:
    me = state.players[bot_idx]

    # Empty hand → must pass (e.g., after Latex Glove hit them).
    if not me.hand:
        return "pass", {}

    options: List[Tuple[float, str, Dict]] = []  # (score, kind, payload)

    for card in list(me.hand):
        for target in legal_play_targets(state, bot_idx, card):
            score = _score_action(state, bot_idx, card, target)
            options.append((score, "play", {"card_id": card.id, "targets": target}))

    # Discard fallback: each candidate is discarding one "worst" card.
    discard_score = _best_discard_score(state, bot_idx)
    options.append((discard_score, "discard", {"card_ids": [_worst_card(state, bot_idx).id]}))

    # Filter to actions with positive score above discard, otherwise discard.
    options.sort(key=lambda x: x[0], reverse=True)
    top = [o for o in options if o[0] >= options[0][0] - 5][:3]
    choice = random.choice(top)
    return choice[1], choice[2]


def _worst_card(state: GameState, bot_idx: int) -> Card:
    """Pick the lowest-value card from hand to discard."""
    me = state.players[bot_idx]
    # Prefer discarding: viruses with no legal target, duplicate-color organs,
    # then multicolor medicines, then medicines, then organs, then treatments.
    def card_value(c: Card) -> float:
        if not legal_play_targets(state, bot_idx, c):
            return -5.0
        if c.type == CardType.ORGAN:
            existing = {o.card.color for o in me.body if o.card.color != Color.MULTI}
            if c.color != Color.MULTI and c.color in existing:
                return -10.0
            return 8.0
        if c.type == CardType.VIRUS:
            return 6.0
        if c.type == CardType.MEDICINE:
            return 4.0 if c.color == Color.MULTI else 5.0
        if c.type == CardType.TREATMENT:
            return 10.0  # keep treatments
        return 0.0

    return min(me.hand, key=card_value)


def _best_discard_score(state: GameState, bot_idx: int) -> float:
    # Discarding is a small positive only when hand has dead cards.
    me = state.players[bot_idx]
    dead = sum(1 for c in me.hand if not legal_play_targets(state, bot_idx, c))
    return 10.0 if dead >= 2 else (5.0 if dead == 1 else 1.0)
