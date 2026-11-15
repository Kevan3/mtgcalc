"""Condition AST and query (LLD §3.2, FR-25, FR-32..FR-35).

Conditions are immutable trees. Leaves (``Compare``, ``Between``, ``Assignable``) test the
number of seen cards matched by a selector; inner nodes combine them logically; ``At``
binds a subtree to a checkpoint (turn). The innermost ``At`` wins.

A small builder DSL is provided::

    (count(tag("land")) >= 3).at(3) & ~(count(card("Sol Ring")) >= 1)
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal, get_args

from mtgcalc.errors import ValidationError
from mtgcalc.model.selectors import SELECTOR_TYPES, Selector, Tag

Op = Literal["==", "!=", "<", "<=", ">", ">="]
OPS: tuple[str, ...] = get_args(Op)


class _ConditionOps:
    """Operator overloads shared by all condition nodes."""

    __slots__ = ()

    def __and__(self, other: Condition) -> And:
        return And(_flatten(And, self, other))

    def __or__(self, other: Condition) -> Or:
        return Or(_flatten(Or, self, other))

    def __xor__(self, other: Condition) -> Xor:
        return Xor(_as_cond(self), other)

    def __invert__(self) -> Not:
        return Not(_as_cond(self))

    def implies(self, other: Condition) -> Implies:
        """Logical implication ``self -> other``."""
        return Implies(_as_cond(self), other)

    def at(self, turn: int) -> At:
        """Bind this condition to the checkpoint "by turn ``turn``"."""
        return At(turn, _as_cond(self))


def _as_cond(x: object) -> Condition:
    if not isinstance(x, CONDITION_TYPES):
        raise ValidationError("condition", f"{x!r} is not a condition")
    return x


def _flatten(kind: type[And] | type[Or], a: object, b: object) -> tuple[Condition, ...]:
    out: list[Condition] = []
    for x in (a, b):
        if isinstance(x, kind):
            out.extend(x.items)
        else:
            out.append(_as_cond(x))
    return tuple(out)


def _check_sel(where: str, sel: object) -> None:
    if not isinstance(sel, SELECTOR_TYPES):
        raise ValidationError(where, f"{sel!r} is not a selector")


def _check_items(where: str, obj: object, items: tuple[Condition, ...], minimum: int) -> None:
    items = tuple(items)
    if len(items) < minimum:
        raise ValidationError(where, f"needs at least {minimum} operands")
    for it in items:
        _as_cond(it)
    object.__setattr__(obj, "items", items)


@dataclass(frozen=True, slots=True)
class Compare(_ConditionOps):
    """``count(sel) <op> value``."""

    sel: Selector
    op: Op
    value: int

    def __post_init__(self) -> None:
        _check_sel("compare.sel", self.sel)
        if self.op not in OPS:
            raise ValidationError("compare.op", f"must be one of {OPS}")
        if self.value < 0:
            raise ValidationError("compare.value", "must be non-negative")


@dataclass(frozen=True, slots=True)
class Between(_ConditionOps):
    """``lo <= count(sel) <= hi``."""

    sel: Selector
    lo: int
    hi: int

    def __post_init__(self) -> None:
        _check_sel("between.sel", self.sel)
        if not 0 <= self.lo <= self.hi:
            raise ValidationError("between", "requires 0 <= lo <= hi")


@dataclass(frozen=True, slots=True)
class And(_ConditionOps):
    """Conjunction of two or more conditions."""

    items: tuple[Condition, ...]

    def __post_init__(self) -> None:
        _check_items("and", self, self.items, 2)


@dataclass(frozen=True, slots=True)
class Or(_ConditionOps):
    """Disjunction of two or more conditions."""

    items: tuple[Condition, ...]

    def __post_init__(self) -> None:
        _check_items("or", self, self.items, 2)


@dataclass(frozen=True, slots=True)
class Xor(_ConditionOps):
    """Binary exclusive or (use ``Exactly(1, ...)`` for one-of-n)."""

    a: Condition
    b: Condition

    def __post_init__(self) -> None:
        _as_cond(self.a)
        _as_cond(self.b)


@dataclass(frozen=True, slots=True)
class Not(_ConditionOps):
    """Negation."""

    item: Condition

    def __post_init__(self) -> None:
        _as_cond(self.item)


@dataclass(frozen=True, slots=True)
class Implies(_ConditionOps):
    """Material implication ``a -> b`` ("if a then b")."""

    a: Condition
    b: Condition

    def __post_init__(self) -> None:
        _as_cond(self.a)
        _as_cond(self.b)


@dataclass(frozen=True, slots=True)
class AtLeast(_ConditionOps):
    """At least ``n`` of the items hold."""

    n: int
    items: tuple[Condition, ...]

    def __post_init__(self) -> None:
        if self.n < 0:
            raise ValidationError("atleast.n", "must be non-negative")
        _check_items("atleast", self, self.items, 1)


@dataclass(frozen=True, slots=True)
class Exactly(_ConditionOps):
    """Exactly ``n`` of the items hold."""

    n: int
    items: tuple[Condition, ...]

    def __post_init__(self) -> None:
        if self.n < 0:
            raise ValidationError("exactly.n", "must be non-negative")
        _check_items("exactly", self, self.items, 1)


@dataclass(frozen=True, slots=True)
class Demand:
    """One demand of an exclusive assignment: ``need`` distinct cards matching ``sel``."""

    sel: Selector
    need: int

    def __post_init__(self) -> None:
        _check_sel("demand.sel", self.sel)
        if self.need < 1:
            raise ValidationError("demand.need", "must be at least 1")


@dataclass(frozen=True, slots=True)
class Assignable(_ConditionOps):
    """All demands can be met simultaneously by *distinct* seen cards (FR-34, MATH §8)."""

    demands: tuple[Demand, ...]

    def __post_init__(self) -> None:
        demands = tuple(self.demands)
        if not demands:
            raise ValidationError("assignable", "needs at least one demand")
        for d in demands:
            if not isinstance(d, Demand):
                raise ValidationError("assignable", f"{d!r} is not a Demand")
        object.__setattr__(self, "demands", demands)


@dataclass(frozen=True, slots=True)
class At(_ConditionOps):
    """Evaluate ``item`` at checkpoint "by turn ``turn``" (turn 0 = opening hand)."""

    turn: int
    item: Condition

    def __post_init__(self) -> None:
        if self.turn < 0:
            raise ValidationError("at.turn", "must be non-negative")
        _as_cond(self.item)


@dataclass(frozen=True, slots=True)
class Const(_ConditionOps):
    """Constant truth value."""

    value: bool


Condition = (
    Compare | Between | And | Or | Xor | Not | Implies | AtLeast | Exactly | Assignable | At | Const
)
CONDITION_TYPES = (
    Compare,
    Between,
    And,
    Or,
    Xor,
    Not,
    Implies,
    AtLeast,
    Exactly,
    Assignable,
    At,
    Const,
)
LEAF_TYPES = (Compare, Between, Assignable)


@dataclass(frozen=True, slots=True)
class Query:
    """A probability question: P(condition) or P(condition | given) (FR-35).

    ``turn`` is the default checkpoint for leaves not inside an ``At``.
    """

    condition: Condition
    given: Condition | None = None
    turn: int = 0

    def __post_init__(self) -> None:
        _as_cond(self.condition)
        if self.given is not None:
            _as_cond(self.given)
        if self.turn < 0:
            raise ValidationError("query.turn", "must be non-negative")


@dataclass(frozen=True, slots=True)
class Count:
    """Builder for comparisons on ``count(sel)``; not itself a condition."""

    sel: Selector

    def __ge__(self, v: int) -> Compare:
        return Compare(self.sel, ">=", v)

    def __gt__(self, v: int) -> Compare:
        return Compare(self.sel, ">", v)

    def __le__(self, v: int) -> Compare:
        return Compare(self.sel, "<=", v)

    def __lt__(self, v: int) -> Compare:
        return Compare(self.sel, "<", v)

    def eq(self, v: int) -> Compare:
        """``count == v``."""
        return Compare(self.sel, "==", v)

    def ne(self, v: int) -> Compare:
        """``count != v``."""
        return Compare(self.sel, "!=", v)

    def between(self, lo: int, hi: int) -> Between:
        """``lo <= count <= hi``."""
        return Between(self.sel, lo, hi)


def count(sel: Selector | str) -> Count:
    """Start a comparison on the number of seen cards matching ``sel`` (strings are tags)."""
    return Count(Tag(sel) if isinstance(sel, str) else sel)


def children(c: Condition) -> tuple[Condition, ...]:
    """Direct sub-conditions of a node."""
    match c:
        case And(items) | Or(items) | AtLeast(_, items) | Exactly(_, items):
            return items
        case Xor(a, b) | Implies(a, b):
            return (a, b)
        case Not(item) | At(_, item):
            return (item,)
        case _:
            return ()


def walk(c: Condition) -> Iterator[Condition]:
    """Pre-order traversal of all nodes."""
    yield c
    for ch in children(c):
        yield from walk(ch)


def selectors_in(c: Condition) -> tuple[Selector, ...]:
    """Every selector referenced by leaves of ``c`` (with repetition, in order)."""
    out: list[Selector] = []
    for node in walk(c):
        match node:
            case Compare(sel, _, _) | Between(sel, _, _):
                out.append(sel)
            case Assignable(demands):
                out.extend(d.sel for d in demands)
            case _:
                pass
    return tuple(out)


def turns_in(c: Condition, default: int) -> frozenset[int]:
    """Checkpoint turns at which leaves of ``c`` are evaluated (binding-aware)."""
    out: set[int] = set()

    def rec(node: Condition, turn: int) -> None:
        if isinstance(node, At):
            rec(node.item, node.turn)
        elif isinstance(node, LEAF_TYPES):
            out.add(turn)
        else:
            for ch in children(node):
                rec(ch, turn)

    rec(c, default)
    return frozenset(out)
