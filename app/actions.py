"""Pure rule-enforcement functions. Each play_* mutates the GameState
and returns a human-readable event string. Targets are dicts:

    {"player": int, "organ_id": str | None}

Raises ValueError on illegal actions.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

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


# ---------- helpers ----------

def _find_card(player: Player, card_id: str) -> Card:
    for c in player.hand:
        if c.id == card_id:
            return c
    raise ValueError(f"card {card_id} not in player's hand")


def _find_organ(player: Player, organ_id: str) -> Organ:
    for o in player.body:
        if o.card.id == organ_id:
            return o
    raise ValueError(f"organ {organ_id} not on player's body")


def _remove_card_from_hand(player: Player, card_id: str) -> Card:
    for i, c in enumerate(player.hand):
        if c.id == card_id:
            return player.hand.pop(i)
    raise ValueError(f"card {card_id} not in hand")


def _player_name(state: GameState, idx: int) -> str:
    return state.players[idx].name


def _color_label(color: Optional[Color]) -> str:
    return color.value if color else ""


# ---------- legal-action enumeration (used by bot + frontend hints) ----------

def legal_play_targets(state: GameState, player_idx: int, card: Card) -> List[Dict]:
    """Return list of legal target dicts for the given card from this player.

    For cards that take no target, returns [{}]. Returns [] if card cannot be played.
    """
    me = state.players[player_idx]

    if card.type == CardType.ORGAN:
        # Can play if you don't already have an organ of this color (multicolor
        # organ is always allowed; you also can't play colored organ matching
        # an existing multicolor on body? Per rules: you can't have two organs
        # of the same color; multicolor counts as a color of your choice
        # implicitly — we forbid duplicates of the same fixed color).
        existing_colors = {o.card.color for o in me.body if o.card.color != Color.MULTI}
        if card.color != Color.MULTI and card.color in existing_colors:
            return []
        # You also can't have more than one multicolor organ.
        if card.color == Color.MULTI and any(o.card.color == Color.MULTI for o in me.body):
            return []
        return [{}]

    if card.type == CardType.VIRUS:
        targets = []
        for i, p in enumerate(state.players):
            if i == player_idx:
                continue
            for organ in p.body:
                if not organ.matches_color(card.color):
                    continue
                if organ.status == OrganStatus.IMMUNIZED:
                    continue
                targets.append({"player": i, "organ_id": organ.card.id})
        return targets

    if card.type == CardType.MEDICINE:
        targets = []
        # Medicine: own organs only (per Virus! rules)
        for organ in me.body:
            if not organ.matches_color(card.color):
                continue
            if organ.status == OrganStatus.IMMUNIZED:
                continue
            targets.append({"player": player_idx, "organ_id": organ.card.id})
        return targets

    if card.type == CardType.TREATMENT:
        return _legal_treatment_targets(state, player_idx, card)

    return []


def _legal_treatment_targets(state: GameState, player_idx: int, card: Card) -> List[Dict]:
    me = state.players[player_idx]
    kind = card.treatment

    if kind == TreatmentKind.TRANSPLANT:
        # Pick any two organs from two different players (one of which may be self).
        # We model it as {"a": {"player","organ_id"}, "b": {...}}.
        options: List[Dict] = []
        all_organs: List[Tuple[int, Organ]] = []
        for i, p in enumerate(state.players):
            for o in p.body:
                if o.status == OrganStatus.IMMUNIZED:
                    continue
                all_organs.append((i, o))
        for i, (pa, oa) in enumerate(all_organs):
            for pb, ob in all_organs[i + 1 :]:
                if pa == pb:
                    continue
                # After swap, neither receiving player must have a duplicate color.
                # Check: pa would receive ob's color; pb would receive oa's color.
                if _would_duplicate_color(state.players[pa], oa, ob):
                    continue
                if _would_duplicate_color(state.players[pb], ob, oa):
                    continue
                options.append(
                    {"a": {"player": pa, "organ_id": oa.card.id},
                     "b": {"player": pb, "organ_id": ob.card.id}}
                )
        return options

    if kind == TreatmentKind.ORGAN_THIEF:
        options = []
        my_colors = {o.card.color for o in me.body if o.card.color != Color.MULTI}
        for i, p in enumerate(state.players):
            if i == player_idx:
                continue
            for o in p.body:
                if o.status == OrganStatus.IMMUNIZED:
                    continue
                # Can't steal if it would dupe a color you already have
                if o.card.color != Color.MULTI and o.card.color in my_colors:
                    continue
                if o.card.color == Color.MULTI and any(
                    x.card.color == Color.MULTI for x in me.body
                ):
                    continue
                options.append({"player": i, "organ_id": o.card.id})
        return options

    if kind == TreatmentKind.CONTAGION:
        # Playable if you have at least one infected organ AND at least one
        # legal destination among opponents.
        for o in me.body:
            if o.status != OrganStatus.INFECTED:
                continue
            for i, p in enumerate(state.players):
                if i == player_idx:
                    continue
                for d in p.body:
                    if d.status != OrganStatus.FREE:
                        continue
                    # Find a virus on `o` that matches d's color.
                    for v in o.attached:
                        if v.type != CardType.VIRUS:
                            continue
                        if d.matches_color(v.color) or v.color == Color.MULTI:
                            return [{}]
        return []

    if kind == TreatmentKind.LATEX_GLOVE:
        return [{}]

    if kind == TreatmentKind.MEDICAL_ERROR:
        options = []
        for i, _p in enumerate(state.players):
            if i == player_idx:
                continue
            options.append({"player": i})
        return options

    return []


def _would_duplicate_color(player: Player, removing: Organ, receiving: Organ) -> bool:
    """After removing `removing` from player.body and adding `receiving`, would the
    player have two organs of the same fixed color (or two multicolor organs)?"""
    new_body = [o for o in player.body if o.card.id != removing.card.id] + [receiving]
    seen = []
    for o in new_body:
        for s in seen:
            if o.card.color == s and o.card.color == Color.MULTI:
                return True
            if o.card.color == s and o.card.color != Color.MULTI:
                return True
        seen.append(o.card.color)
    return False


# ---------- apply card plays ----------

def apply_play(
    state: GameState, player_idx: int, card_id: str, targets: Optional[Dict] = None
) -> List[str]:
    me = state.players[player_idx]
    card = _find_card(me, card_id)
    targets = targets or {}
    events: List[str] = []

    if card.type == CardType.ORGAN:
        events += _play_organ(state, player_idx, card)
    elif card.type == CardType.VIRUS:
        events += _play_virus(state, player_idx, card, targets)
    elif card.type == CardType.MEDICINE:
        events += _play_medicine(state, player_idx, card, targets)
    elif card.type == CardType.TREATMENT:
        events += _play_treatment(state, player_idx, card, targets)

    # Remove card from hand once it's been applied (organ stays on board;
    # virus/medicine end up attached to an organ; treatments + redirected
    # virus/medicine pairs are discarded inside the play_* functions).
    if card in me.hand:
        me.hand.remove(card)

    return events


def _play_organ(state: GameState, player_idx: int, card: Card) -> List[str]:
    me = state.players[player_idx]
    # Validate not duplicate
    existing = {o.card.color for o in me.body if o.card.color != Color.MULTI}
    if card.color != Color.MULTI and card.color in existing:
        raise ValueError("duplicate organ color")
    if card.color == Color.MULTI and any(o.card.color == Color.MULTI for o in me.body):
        raise ValueError("already have a multicolor organ")
    me.body.append(Organ(card=card))
    return [f"{me.name} placed a {_color_label(card.color)} organ."]


def _play_virus(state: GameState, player_idx: int, card: Card, targets: Dict) -> List[str]:
    target_player = state.players[targets["player"]]
    organ = _find_organ(target_player, targets["organ_id"])
    if not organ.matches_color(card.color):
        raise ValueError("virus color does not match organ")
    if organ.status == OrganStatus.IMMUNIZED:
        raise ValueError("organ is immunized")

    events: List[str] = []
    name_attacker = state.players[player_idx].name
    name_target = target_player.name

    if organ.status == OrganStatus.VACCINATED:
        # Virus on vaccinated organ removes the medicine, both go to discard.
        medicine = next(c for c in organ.attached if c.type == CardType.MEDICINE)
        organ.attached.remove(medicine)
        state.discard.append(medicine)
        state.discard.append(card)
        events.append(
            f"{name_attacker} hit {name_target}'s {_color_label(organ.card.color)} organ — vaccine removed."
        )
        return events

    if organ.status == OrganStatus.INFECTED:
        # Second virus destroys the organ — discard organ + both viruses.
        state.discard.extend(organ.attached)
        state.discard.append(organ.card)
        state.discard.append(card)
        target_player.body.remove(organ)
        events.append(
            f"{name_attacker} destroyed {name_target}'s {_color_label(organ.card.color)} organ!"
        )
        return events

    # Free organ → becomes infected.
    organ.attached.append(card)
    events.append(
        f"{name_attacker} infected {name_target}'s {_color_label(organ.card.color)} organ."
    )
    return events


def _play_medicine(state: GameState, player_idx: int, card: Card, targets: Dict) -> List[str]:
    target_player = state.players[targets["player"]]
    if targets["player"] != player_idx:
        raise ValueError("medicines can only be played on your own organs")
    organ = _find_organ(target_player, targets["organ_id"])
    if not organ.matches_color(card.color):
        raise ValueError("medicine color does not match organ")
    if organ.status == OrganStatus.IMMUNIZED:
        raise ValueError("organ already immunized")

    name = target_player.name
    label = _color_label(organ.card.color)

    if organ.status == OrganStatus.INFECTED:
        virus = next(c for c in organ.attached if c.type == CardType.VIRUS)
        organ.attached.remove(virus)
        state.discard.append(virus)
        state.discard.append(card)
        return [f"{name} cured the virus on their {label} organ."]

    if organ.status == OrganStatus.VACCINATED:
        organ.attached.append(card)
        return [f"{name} immunized their {label} organ!"]

    # Free organ → becomes vaccinated.
    organ.attached.append(card)
    return [f"{name} vaccinated their {label} organ."]


def _play_treatment(state: GameState, player_idx: int, card: Card, targets: Dict) -> List[str]:
    kind = card.treatment
    me = state.players[player_idx]
    state.discard.append(card)

    if kind == TreatmentKind.TRANSPLANT:
        return _treatment_transplant(state, player_idx, targets)
    if kind == TreatmentKind.ORGAN_THIEF:
        return _treatment_organ_thief(state, player_idx, targets)
    if kind == TreatmentKind.CONTAGION:
        return _treatment_contagion(state, player_idx)
    if kind == TreatmentKind.LATEX_GLOVE:
        return _treatment_latex_glove(state, player_idx)
    if kind == TreatmentKind.MEDICAL_ERROR:
        return _treatment_medical_error(state, player_idx, targets)
    return []


def _treatment_transplant(state: GameState, player_idx: int, targets: Dict) -> List[str]:
    a = targets["a"]
    b = targets["b"]
    pa = state.players[a["player"]]
    pb = state.players[b["player"]]
    oa = _find_organ(pa, a["organ_id"])
    ob = _find_organ(pb, b["organ_id"])
    if oa.status == OrganStatus.IMMUNIZED or ob.status == OrganStatus.IMMUNIZED:
        raise ValueError("cannot transplant an immunized organ")
    # Swap.
    pa.body.remove(oa)
    pb.body.remove(ob)
    pa.body.append(ob)
    pb.body.append(oa)
    return [f"{state.players[player_idx].name} swapped organs between {pa.name} and {pb.name}."]


def _treatment_organ_thief(state: GameState, player_idx: int, targets: Dict) -> List[str]:
    me = state.players[player_idx]
    victim = state.players[targets["player"]]
    organ = _find_organ(victim, targets["organ_id"])
    if organ.status == OrganStatus.IMMUNIZED:
        raise ValueError("organ immunized")
    # Validate not a duplicate for thief.
    my_colors = {o.card.color for o in me.body if o.card.color != Color.MULTI}
    if organ.card.color != Color.MULTI and organ.card.color in my_colors:
        raise ValueError("you already have an organ of that color")
    if organ.card.color == Color.MULTI and any(o.card.color == Color.MULTI for o in me.body):
        raise ValueError("you already have a multicolor organ")
    victim.body.remove(organ)
    me.body.append(organ)
    return [f"{me.name} stole {victim.name}'s {_color_label(organ.card.color)} organ!"]


def _treatment_contagion(state: GameState, player_idx: int) -> List[str]:
    """Move each virus on a player's infected organs to a matching free organ
    of any opponent (greedy assignment)."""
    me = state.players[player_idx]
    events: List[str] = []
    for organ in list(me.body):
        if organ.status != OrganStatus.INFECTED:
            continue
        for virus in list(organ.attached):
            if virus.type != CardType.VIRUS:
                continue
            # Find a destination.
            placed = False
            for i, p in enumerate(state.players):
                if i == player_idx:
                    continue
                for dest in p.body:
                    if dest.status != OrganStatus.FREE:
                        continue
                    if dest.matches_color(virus.color) or virus.color == Color.MULTI:
                        organ.attached.remove(virus)
                        dest.attached.append(virus)
                        events.append(
                            f"Contagion: virus moved from {me.name}'s organ to {p.name}'s {_color_label(dest.card.color)} organ."
                        )
                        placed = True
                        break
                if placed:
                    break
    if not events:
        events.append(f"{me.name} played Contagion (no viruses transferred).")
    return events


def _treatment_latex_glove(state: GameState, player_idx: int) -> List[str]:
    events: List[str] = []
    me = state.players[player_idx]
    for i, p in enumerate(state.players):
        if i == player_idx:
            continue
        if p.hand:
            state.discard.extend(p.hand)
            p.hand = []
        if i not in state.skip_draw:
            state.skip_draw.append(i)
    events.append(f"{me.name} played Latex Glove — everyone else discards hand & skips draw.")
    return events


def _treatment_medical_error(state: GameState, player_idx: int, targets: Dict) -> List[str]:
    me = state.players[player_idx]
    other = state.players[targets["player"]]
    me.body, other.body = other.body, me.body
    return [f"{me.name} swapped bodies with {other.name} (Medical Error)!"]


# ---------- discard ----------

def apply_discard(state: GameState, player_idx: int, card_ids: List[str]) -> List[str]:
    me = state.players[player_idx]
    if not (1 <= len(card_ids) <= 3):
        raise ValueError("must discard 1 to 3 cards")
    removed = []
    for cid in card_ids:
        c = _remove_card_from_hand(me, cid)
        state.discard.append(c)
        removed.append(c)
    return [f"{me.name} discarded {len(removed)} card(s)."]
