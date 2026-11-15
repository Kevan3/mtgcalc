"""mtgcalc: exact draw and mulligan probabilities for Magic: The Gathering decks.

Quick start::

    from mtgcalc import Deck, Scenario, GameConfig, probability

    deck = Deck.from_counts(60, {"land": 24, "bolt": 4})
    p = probability(Scenario(deck), "land >= 3 @T3 AND bolt >= 1 @T3")
    print(p.exact, p.value)

See ``docs/`` for requirements, design and the mathematical foundations.
"""

from mtgcalc.analysis.optimizer import OptimizeProblem, Variable
from mtgcalc.api import (
    distribution,
    format_condition,
    format_decklist,
    format_query,
    format_selector,
    hypergeom,
    mulligan_report,
    optimal_keep,
    optimize,
    parse_condition,
    parse_decklist,
    parse_query,
    parse_selector,
    probability,
    threshold_table,
    turn_table,
)
from mtgcalc.errors import (
    InfeasibleError,
    MtgCalcError,
    ParseError,
    StateSpaceTooLargeError,
    ValidationError,
)
from mtgcalc.model.conditions import (
    And,
    Assignable,
    At,
    AtLeast,
    Between,
    Compare,
    Const,
    Demand,
    Exactly,
    Implies,
    Not,
    Or,
    Query,
    Xor,
    count,
)
from mtgcalc.model.deck import Card, Category, Deck
from mtgcalc.model.game import GameConfig
from mtgcalc.model.mulligan import MulliganConfig, PriorityGroup
from mtgcalc.model.scenario import Scenario
from mtgcalc.model.selectors import (
    AllOf,
    AnyOf,
    CardName,
    Everything,
    NoneOf,
    Tag,
    all_of,
    any_of,
    card,
    everything,
    none_of,
    tag,
)

__version__ = "0.5.0"

__all__ = [
    "AllOf",
    "And",
    "AnyOf",
    "Assignable",
    "At",
    "AtLeast",
    "Between",
    "Card",
    "CardName",
    "Category",
    "Compare",
    "Const",
    "Deck",
    "Demand",
    "Everything",
    "Exactly",
    "GameConfig",
    "Implies",
    "InfeasibleError",
    "MtgCalcError",
    "MulliganConfig",
    "NoneOf",
    "Not",
    "OptimizeProblem",
    "Or",
    "ParseError",
    "PriorityGroup",
    "Query",
    "Scenario",
    "StateSpaceTooLargeError",
    "Tag",
    "ValidationError",
    "Variable",
    "Xor",
    "all_of",
    "any_of",
    "card",
    "count",
    "distribution",
    "everything",
    "format_condition",
    "format_decklist",
    "format_query",
    "format_selector",
    "hypergeom",
    "mulligan_report",
    "none_of",
    "optimal_keep",
    "optimize",
    "parse_condition",
    "parse_decklist",
    "parse_query",
    "parse_selector",
    "probability",
    "tag",
    "threshold_table",
    "turn_table",
]
