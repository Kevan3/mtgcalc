"""Compiled Boolean programs and leaf predicates (LLD §4.3, ADR-0006, MATH §7-§8).

A *program* is a flat postfix tuple of ints over predicate bits:

    BIT i | CONST b | NOT | AND n | OR n | XOR | IMPLIES | ATLEAST k n | EXACTLY k n

``run2`` evaluates in two-valued logic. ``run3`` evaluates in Kleene's strong three-valued
logic where unknown bits are ``None``; a decided result is guaranteed to equal the two-valued
result under every completion of the unknown bits (MATH §7.3).
"""

from __future__ import annotations

import operator
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from itertools import combinations
from typing import Literal

BIT, CONST, NOT, AND, OR, XOR, IMPLIES, ATLEAST, EXACTLY = range(9)
#: Number of operands following each opcode.
ARITY = {BIT: 1, CONST: 1, NOT: 0, AND: 1, OR: 1, XOR: 0, IMPLIES: 0, ATLEAST: 2, EXACTLY: 2}

Program = tuple[int, ...]
Mask = tuple[int, ...]
Demands = tuple[tuple[Mask, int], ...]

COMPARATORS: dict[str, Callable[[int, int], bool]] = {
    "==": operator.eq,
    "!=": operator.ne,
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
}


@dataclass(frozen=True, slots=True)
class Leaf:
    """A predicate on seen atom counts, evaluated at one checkpoint into one bit."""

    bit: int
    checkpoint: int
    kind: Literal["cmp", "between", "assign"]
    mask: Mask = ()
    op: str = ""
    value: int = 0
    lo: int = 0
    hi: int = 0
    demands: Demands = ()

    @property
    def atoms(self) -> frozenset[int]:
        """Every atom this leaf reads."""
        return frozenset(self.mask) | frozenset(i for m, _ in self.demands for i in m)


def eval_leaf(leaf: Leaf, seen: tuple[int, ...]) -> bool:
    """Evaluate a leaf predicate on a seen-count vector."""
    if leaf.kind == "assign":
        return hall_feasible(leaf.demands, seen)
    x = sum(seen[i] for i in leaf.mask)
    if leaf.kind == "between":
        return leaf.lo <= x <= leaf.hi
    return COMPARATORS[leaf.op](x, leaf.value)


def leaf_bits(leaves: tuple[Leaf, ...], seen: tuple[int, ...]) -> int:
    """Bitset of the leaves that hold on ``seen``."""
    bits = 0
    for leaf in leaves:
        if eval_leaf(leaf, seen):
            bits |= 1 << leaf.bit
    return bits


@lru_cache(maxsize=2**16)
def hall_feasible(demands: Demands, seen: tuple[int, ...]) -> bool:
    """Can distinct seen cards satisfy every ``(mask, need)`` demand? (Hall/Gale, MATH §8).

    Feasible iff for every non-empty subset S of demands, the total need of S is at most
    the number of seen cards in atoms adjacent to S.
    """
    for r in range(1, len(demands) + 1):
        for subset in combinations(demands, r):
            need = sum(n for _, n in subset)
            adjacent = {i for mask, _ in subset for i in mask}
            if need > sum(seen[i] for i in adjacent):
                return False
    return True


def run2(prog: Program, bits: int) -> bool:
    """Evaluate a program in two-valued logic."""
    stack: list[bool] = []
    pc = 0
    while pc < len(prog):
        op = prog[pc]
        if op == BIT:
            stack.append(bool(bits >> prog[pc + 1] & 1))
        elif op == CONST:
            stack.append(bool(prog[pc + 1]))
        elif op == NOT:
            stack.append(not stack.pop())
        elif op in (AND, OR):
            n = prog[pc + 1]
            args = stack[-n:]
            del stack[-n:]
            stack.append(all(args) if op == AND else any(args))
        elif op == XOR:
            b, a = stack.pop(), stack.pop()
            stack.append(a != b)
        elif op == IMPLIES:
            b, a = stack.pop(), stack.pop()
            stack.append((not a) or b)
        else:  # ATLEAST / EXACTLY
            k, n = prog[pc + 1], prog[pc + 2]
            t = sum(stack[-n:])
            del stack[-n:]
            stack.append(t >= k if op == ATLEAST else t == k)
        pc += 1 + ARITY[op]
    (result,) = stack
    return result


def run3(prog: Program, bits: int, known: int) -> bool | None:
    """Evaluate in Kleene strong three-valued logic.

    Bit ``i`` is unknown unless bit ``i`` of ``known`` is set.
    """
    stack: list[bool | None] = []
    pc = 0
    while pc < len(prog):
        op = prog[pc]
        if op == BIT:
            i = prog[pc + 1]
            stack.append(bool(bits >> i & 1) if known >> i & 1 else None)
        elif op == CONST:
            stack.append(bool(prog[pc + 1]))
        elif op == NOT:
            v = stack.pop()
            stack.append(None if v is None else not v)
        elif op in (AND, OR):
            n = prog[pc + 1]
            args = stack[-n:]
            del stack[-n:]
            dominant = op == OR  # value that decides the connective
            if any(a is dominant for a in args):
                stack.append(dominant)
            elif all(a is not None for a in args):
                stack.append(not dominant)
            else:
                stack.append(None)
        elif op == XOR:
            b, a = stack.pop(), stack.pop()
            stack.append(None if a is None or b is None else a != b)
        elif op == IMPLIES:
            b, a = stack.pop(), stack.pop()
            if a is False or b is True:
                stack.append(True)
            elif a is True and b is False:
                stack.append(False)
            else:
                stack.append(None)
        else:
            k, n = prog[pc + 1], prog[pc + 2]
            args = stack[-n:]
            del stack[-n:]
            t = sum(1 for a in args if a is True)
            u = sum(1 for a in args if a is None)
            if op == ATLEAST:
                stack.append(True if t >= k else False if t + u < k else None)
            else:
                stack.append(False if t > k or t + u < k else True if u == 0 else None)
        pc += 1 + ARITY[op]
    (result,) = stack
    return result


def conjoin_bit(prog: Program, bit: int) -> Program:
    """Program for ``prog AND BIT(bit)`` (postfix concatenation, ADR-0006)."""
    return (*prog, BIT, bit, AND, 2)
