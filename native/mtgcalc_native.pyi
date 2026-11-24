"""Type stubs for the native exact engine (Rust, see native/src/python.rs).

Flat tuple formats are produced by ``mtgcalc.engine.native`` (``_flatten``,
``_flatten_plan``); every function releases the GIL while computing.
"""

__version__: str
#: Unicode version of the text-normalization tables (Python's ``unicodedata`` at generation).
UNICODE_VERSION: str

class StateLimitExceeded(Exception):
    """More live states than the limit; ``args[0]`` is the state count."""

# (bit, checkpoint, kind, mask, op, value, lo, hi, demands)
_Leaf = tuple[int, int, int, list[int], int, int, int, int, list[tuple[list[int], int]]]
# (deck_size, counts, pool, hand_size, batches, leaves, outputs, observers, retire_after,
#  reserved_bits)
_Query = tuple[
    int,
    list[int],
    int,
    int,
    list[int],
    list[_Leaf],
    list[list[int]],
    list[tuple[int, list[int]]],
    list[list[int]],
    int,
]
# (priority rules, keep leaves, keep program, bottoms per depth, draw size)
_Plan = tuple[list[tuple[list[int], int]], list[_Leaf], list[int], list[int], int]
# (limit, early_resolution, retirement)
_Options = tuple[int, bool, bool]
_Init = tuple[list[tuple[list[int], list[int], int, int]], int, int]

def run(
    query: _Query, init: _Init | None, options: _Options
) -> tuple[list[int], int, list[tuple[int, list[int], int]], int]:
    """``(outputs, denominator, snapshots, peak)``."""

def mulligan(
    query: _Query, plan: _Plan, options: _Options
) -> list[tuple[int, int, list[int], int]]:
    """Per depth: ``(keep_weight, hands_total, outputs, denominator)``."""

def hand_values(
    query: _Query, plan: _Plan, output: int, options: _Options
) -> list[list[tuple[list[int], int, int, int]]]:
    """Per depth, per drawn hand: ``(hand, weight, success, denominator)``."""

def probability_json(request: str) -> str:
    """A ``Probability`` / ``ConditionalResult`` / ``Error`` as JSON (ADR-0013 §3)."""

def normalize_text(text: str) -> str:
    """``" ".join(text.split()).casefold()``, as the Rust core computes it."""

def parse_deck_json(text: str) -> str:
    """``to_dict(parse_decklist(text))`` or an error object, as JSON (ADR-0013 §2)."""

def parse_rule_json(text: str, turn: int) -> str:
    """``to_dict(parse_query(text, turn))`` or an error object, as JSON."""

def format_rule_json(query: str) -> str:
    """``{"type": "Rule", "text": format_query(q)}`` for a ``to_dict`` query, as JSON."""
