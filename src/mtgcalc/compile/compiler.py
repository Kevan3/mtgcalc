"""Condition compiler (LLD §4.4).

Turns condition ASTs into (a) deduplicated *leaves* that the engine evaluates into
predicate bits at their checkpoints and (b) one postfix program per named output.
Bits are numbered in checkpoint order so every bit of checkpoint ``j`` is known once
the engine has processed checkpoint ``j`` (needed for early resolution, MATH §5.3).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from mtgcalc.compile.atomizer import AtomTable, atomize
from mtgcalc.compile.logic import (
    AND,
    ATLEAST,
    BIT,
    CONST,
    EXACTLY,
    IMPLIES,
    NOT,
    OR,
    XOR,
    Demands,
    Leaf,
    Mask,
    Program,
)
from mtgcalc.compile.schedule import BatchPlan, plan
from mtgcalc.errors import ValidationError
from mtgcalc.model.conditions import (
    And,
    Assignable,
    At,
    AtLeast,
    Between,
    Compare,
    Condition,
    Const,
    Exactly,
    Implies,
    Not,
    Or,
    Xor,
    selectors_in,
    turns_in,
)
from mtgcalc.model.deck import Deck
from mtgcalc.model.game import GameConfig
from mtgcalc.model.selectors import Selector


@dataclass(frozen=True, slots=True)
class LeafSpec:
    """A leaf before bit assignment; equal specs share one bit (deduplication)."""

    turn: int
    kind: Literal["cmp", "between", "assign"]
    mask: Mask = ()
    op: str = ""
    value: int = 0
    lo: int = 0
    hi: int = 0
    demands: Demands = ()

    def to_leaf(self, bit: int, checkpoint: int) -> Leaf:
        """Materialize with an assigned bit and checkpoint index."""
        return Leaf(
            bit,
            checkpoint,
            self.kind,
            self.mask,
            self.op,
            self.value,
            self.lo,
            self.hi,
            self.demands,
        )


@dataclass(frozen=True, slots=True)
class CompiledQuery:
    """Everything the engines need to evaluate a set of outputs on a scenario."""

    atoms: AtomTable
    plan: BatchPlan
    leaves: tuple[Leaf, ...]
    outputs: tuple[tuple[str, Program], ...]
    observers: tuple[tuple[int, tuple[int, ...]], ...]
    retire_after: tuple[tuple[int, ...], ...]
    reserved_bits: int

    def leaves_at(self, j: int) -> tuple[Leaf, ...]:
        """Leaves evaluated at checkpoint index ``j``."""
        return tuple(leaf for leaf in self.leaves if leaf.checkpoint == j)

    def known_through(self, j: int) -> int:
        """Bitmask of bits known after processing checkpoint index ``j``."""
        n = self.reserved_bits + sum(1 for leaf in self.leaves if leaf.checkpoint <= j)
        return (1 << n) - 1

    def output(self, name: str) -> Program:
        """Program of a named output."""
        return dict(self.outputs)[name]


def _leaf_key(node: Condition, turn: int, atoms: AtomTable) -> LeafSpec:
    match node:
        case Compare(sel, op, value):
            return LeafSpec(turn, "cmp", atoms.mask(sel), op, value)
        case Between(sel, lo, hi):
            return LeafSpec(turn, "between", atoms.mask(sel), lo=lo, hi=hi)
        case Assignable(demands):
            dem = tuple((atoms.mask(d.sel), d.need) for d in demands)
            return LeafSpec(turn, "assign", demands=dem)
    raise TypeError(f"not a leaf: {node!r}")  # pragma: no cover


def _emit(
    node: Condition, turn: int, atoms: AtomTable, bit_of: Callable[[LeafSpec], int], out: list[int]
) -> None:
    """Append the postfix program for ``node`` to ``out``."""
    match node:
        case Compare() | Between() | Assignable():
            out += (BIT, bit_of(_leaf_key(node, turn, atoms)))
        case At(t, item):
            _emit(item, t, atoms, bit_of, out)
        case Const(value):
            out += (CONST, int(value))
        case Not(item):
            _emit(item, turn, atoms, bit_of, out)
            out.append(NOT)
        case And(items) | Or(items):
            for it in items:
                _emit(it, turn, atoms, bit_of, out)
            out += (AND if isinstance(node, And) else OR, len(items))
        case Xor(a, b) | Implies(a, b):
            _emit(a, turn, atoms, bit_of, out)
            _emit(b, turn, atoms, bit_of, out)
            out.append(XOR if isinstance(node, Xor) else IMPLIES)
        case AtLeast(n, items) | Exactly(n, items):
            for it in items:
                _emit(it, turn, atoms, bit_of, out)
            out += (ATLEAST if isinstance(node, AtLeast) else EXACTLY, n, len(items))
        case _:  # pragma: no cover
            raise TypeError(f"not a condition: {node!r}")


def compile_query(
    deck: Deck,
    game: GameConfig,
    outputs: Mapping[str, Condition],
    *,
    hand_size: int,
    turn: int = 0,
    observe: Sequence[tuple[int, Selector]] = (),
    extra_selectors: Sequence[Selector] = (),
    reserved_bits: int = 0,
    draw_region: int | None = None,
) -> CompiledQuery:
    """Compile named output conditions for one scenario.

    Args:
        hand_size: Cards in hand before the first draw (kept hand, or the 7 drawn when
            mulligans are modelled; see ``draw_region``).
        turn: Default checkpoint for leaves not under an ``At``.
        observe: ``(turn, selector)`` pairs whose count distribution should be recorded.
        extra_selectors: Selectors to atomize even if no output uses them (keep rule,
            priority groups).
        reserved_bits: Number of low bits reserved for externally set flags.
        draw_region: Maximum number of cards that may be taken from the library
            (defaults to the library size).
    """
    sels: list[Selector] = []
    for cond in outputs.values():
        sels.extend(selectors_in(cond))
    sels.extend(s for _, s in observe)
    sels.extend(extra_selectors)
    atoms = atomize(deck, sels)

    turns: set[int] = {turn, *(t for t, _ in observe)}
    for cond in outputs.values():
        turns |= turns_in(cond, turn)
    bp = plan(game, turns, hand_size)
    region = deck.size if draw_region is None else draw_region
    if hand_size + bp.total_draws > region:
        raise ValidationError(
            "game",
            f"{hand_size} cards in hand plus {bp.total_draws} draws exceed the "
            f"{region} cards available",
        )

    # Pass 1: discover leaves (in order) with their checkpoint turns.
    discovered: dict[LeafSpec, int] = {}

    def discover(key: LeafSpec) -> int:
        discovered.setdefault(key, len(discovered))
        return 0

    for cond in outputs.values():
        _emit(cond, turn, atoms, discover, [])

    # Bits in checkpoint order, then discovery order.
    ordered = sorted(discovered, key=lambda k: (bp.index(k.turn), discovered[k]))
    bits = {key: reserved_bits + i for i, key in enumerate(ordered)}
    leaves = tuple(k.to_leaf(bits[k], bp.index(k.turn)) for k in ordered)

    # Pass 2: emit programs.
    programs: list[tuple[str, Program]] = []
    for name, cond in outputs.items():
        out: list[int] = []
        _emit(cond, turn, atoms, bits.__getitem__, out)
        programs.append((name, tuple(out)))

    observers = tuple((bp.index(t), atoms.mask(s)) for t, s in observe)

    # Atom retirement plan (MATH §5.3): retire atoms no later checkpoint reads.
    retire: list[tuple[int, ...]] = []
    retired: set[int] = set()
    for j in range(len(bp.checkpoints)):
        needed: set[int] = set()
        for leaf in leaves:
            if leaf.checkpoint > j:
                needed |= leaf.atoms
        for idx, mask in observers:
            if idx > j:
                needed |= set(mask)
        now = tuple(i for i in range(atoms.size) if i not in needed and i not in retired)
        retired |= set(now)
        retire.append(now)

    return CompiledQuery(
        atoms=atoms,
        plan=bp,
        leaves=leaves,
        outputs=tuple(programs),
        observers=observers,
        retire_after=tuple(retire),
        reserved_bits=reserved_bits,
    )


def compile_predicate(cond: Condition, atoms: AtomTable) -> tuple[tuple[Leaf, ...], Program]:
    """Compile a single-checkpoint condition (e.g. a keep rule) on an existing atom table.

    All leaves are evaluated on one count vector; bits start at 0.
    """
    keys: dict[LeafSpec, int] = {}

    def bit_of(key: LeafSpec) -> int:
        return keys.setdefault(key, len(keys))

    out: list[int] = []
    _emit(cond, 0, atoms, bit_of, out)
    leaves = tuple(k.to_leaf(b, 0) for k, b in keys.items())
    return leaves, tuple(out)
