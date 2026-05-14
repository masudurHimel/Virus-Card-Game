from __future__ import annotations

import random
import uuid
from typing import List, Tuple

from .models import Card, CardType, Color, TreatmentKind

COLORS = [Color.RED, Color.GREEN, Color.BLUE, Color.YELLOW]


def _cid() -> str:
    return uuid.uuid4().hex[:8]


def build_deck() -> List[Card]:
    """68 cards: 21 organs, 17 viruses, 20 medicines, 10 treatments."""
    cards: List[Card] = []

    # 5 organs per colored color + 1 multicolor wild = 21
    for color in COLORS:
        for _ in range(5):
            cards.append(Card(id=_cid(), type=CardType.ORGAN, color=color))
    cards.append(Card(id=_cid(), type=CardType.ORGAN, color=Color.MULTI))

    # 4 viruses per colored color + 1 multicolor = 17
    for color in COLORS:
        for _ in range(4):
            cards.append(Card(id=_cid(), type=CardType.VIRUS, color=color))
    cards.append(Card(id=_cid(), type=CardType.VIRUS, color=Color.MULTI))

    # 4 medicines per colored color + 4 multicolor = 20
    for color in COLORS:
        for _ in range(4):
            cards.append(Card(id=_cid(), type=CardType.MEDICINE, color=color))
    for _ in range(4):
        cards.append(Card(id=_cid(), type=CardType.MEDICINE, color=Color.MULTI))

    # 2 of each treatment = 10
    for kind in TreatmentKind:
        for _ in range(2):
            cards.append(Card(id=_cid(), type=CardType.TREATMENT, treatment=kind))

    return cards


def shuffle(deck: List[Card], rng: random.Random | None = None) -> None:
    (rng or random).shuffle(deck)


def draw(deck: List[Card], discard: List[Card], n: int) -> Tuple[List[Card], List[Card], List[Card]]:
    """Draw n cards. Returns (drawn, deck, discard). Reshuffles discard if needed."""
    drawn: List[Card] = []
    for _ in range(n):
        if not deck:
            if not discard:
                break
            deck = list(discard)
            discard = []
            random.shuffle(deck)
        drawn.append(deck.pop())
    return drawn, deck, discard
