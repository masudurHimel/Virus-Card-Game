from __future__ import annotations

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class Color(str, Enum):
    RED = "red"
    GREEN = "green"
    BLUE = "blue"
    YELLOW = "yellow"
    MULTI = "multi"


class CardType(str, Enum):
    ORGAN = "organ"
    VIRUS = "virus"
    MEDICINE = "medicine"
    TREATMENT = "treatment"


class TreatmentKind(str, Enum):
    TRANSPLANT = "transplant"
    ORGAN_THIEF = "organ_thief"
    CONTAGION = "contagion"
    LATEX_GLOVE = "latex_glove"
    MEDICAL_ERROR = "medical_error"


class OrganStatus(str, Enum):
    FREE = "free"
    VACCINATED = "vaccinated"
    IMMUNIZED = "immunized"
    INFECTED = "infected"


class Card(BaseModel):
    id: str
    type: CardType
    color: Optional[Color] = None
    treatment: Optional[TreatmentKind] = None


class Organ(BaseModel):
    """A played organ on a player's body, with any attached medicine/virus cards."""

    card: Card
    attached: List[Card] = Field(default_factory=list)

    @property
    def status(self) -> OrganStatus:
        viruses = [c for c in self.attached if c.type == CardType.VIRUS]
        medicines = [c for c in self.attached if c.type == CardType.MEDICINE]
        if len(medicines) >= 2:
            return OrganStatus.IMMUNIZED
        if len(viruses) >= 1 and len(medicines) == 0:
            return OrganStatus.INFECTED
        if len(medicines) == 1 and len(viruses) == 0:
            return OrganStatus.VACCINATED
        return OrganStatus.FREE

    @property
    def is_healthy(self) -> bool:
        return self.status != OrganStatus.INFECTED

    def matches_color(self, color: Color) -> bool:
        return (
            color == Color.MULTI
            or self.card.color == Color.MULTI
            or self.card.color == color
        )


class Player(BaseModel):
    id: int
    name: str
    is_bot: bool
    hand: List[Card] = Field(default_factory=list)
    body: List[Organ] = Field(default_factory=list)

    def distinct_healthy_colors(self) -> set:
        colors = set()
        for organ in self.body:
            if organ.is_healthy:
                colors.add(organ.card.color)
        return colors

    def has_won(self) -> bool:
        healthy = [o for o in self.body if o.is_healthy]
        if len(healthy) < 4:
            return False
        # Need 4 organs covering 4 distinct colors. Multicolor organ counts
        # as any color not already represented.
        fixed = {o.card.color for o in healthy if o.card.color != Color.MULTI}
        wilds = sum(1 for o in healthy if o.card.color == Color.MULTI)
        all_colors = {Color.RED, Color.GREEN, Color.BLUE, Color.YELLOW}
        missing = all_colors - fixed
        return len(fixed) + min(wilds, len(missing)) >= 4 or len(fixed) >= 4


class GameState(BaseModel):
    game_id: str
    players: List[Player]
    deck: List[Card] = Field(default_factory=list)
    discard: List[Card] = Field(default_factory=list)
    current: int = 0
    skip_draw: List[int] = Field(default_factory=list)  # player ids who skip their next draw
    winner: Optional[int] = None
    turn_number: int = 1
