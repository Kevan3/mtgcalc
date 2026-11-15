"""Card-count optimizer (LLD §6.3, FR-50..FR-54, MATH §10).

Vocabulary used throughout:

* **point**: one assignment of counts to the variables, e.g. ``(24, 4)``.
* **cap**: the most cards the variables may use together (``OptimizeProblem.max_total``).
* **slice**: all points whose counts add up to one particular total.
* **monotone**: adding a copy of a variable (and removing a filler card) can never lower
  the probability. Decided syntactically by :func:`is_monotone` (MATH §10.2).

Optimality is reported as proven only for exhaustive searches and monotone bisection.
Monotonicity also shrinks the search: the best point then always uses the whole cap
(only one slice needs searching), and the best probability per slice rises with the
total (so ``min_total`` can binary-search the total).
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Literal

from mtgcalc.analysis.evaluation import exact_values
from mtgcalc.analysis.prepare import prepare
from mtgcalc.engine.base import DEFAULT_LIMIT
from mtgcalc.engine.select import native_available
from mtgcalc.errors import InfeasibleError, ValidationError
from mtgcalc.model.conditions import (
    And,
    Assignable,
    At,
    AtLeast,
    Between,
    Compare,
    Condition,
    Const,
    Implies,
    Not,
    Or,
    Query,
    walk,
)
from mtgcalc.model.deck import FILLER_NAME, Card, Category, Deck
from mtgcalc.model.game import GameConfig
from mtgcalc.model.mulligan import MulliganConfig
from mtgcalc.model.results import Counts, OptimizeResult
from mtgcalc.model.scenario import Scenario
from mtgcalc.model.selectors import matches

Objective = Literal["min_count", "max_probability", "min_total"]
Point = tuple[int, ...]
Evaluator = Callable[[Point], Fraction]


@dataclass(frozen=True, slots=True)
class Variable:
    """A category whose count the optimizer chooses, within ``lo..hi``."""

    name: str
    lo: int
    hi: int
    tags: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not 0 <= self.lo <= self.hi:
            raise ValidationError(f"variable[{self.name}]", "requires 0 <= lo <= hi")


@dataclass(frozen=True, slots=True)
class OptimizeProblem:
    """An optimization problem over category counts (FR-50..FR-52)."""

    deck_size: int
    variables: tuple[Variable, ...]
    query: Query
    fixed: tuple[tuple[str, Category], ...] = ()
    game: GameConfig = field(default_factory=GameConfig)
    mulligan: MulliganConfig | None = None
    objective: Objective = "max_probability"
    target: Fraction | None = None
    budget: int | None = None
    exhaustive_limit: int = 5000
    assume_monotone: bool | None = None
    workers: int | None = None

    def __post_init__(self) -> None:
        if not self.variables:
            raise ValidationError("optimize.variables", "at least one variable is required")
        names = [v.name for v in self.variables] + [n for n, _ in self.fixed]
        if len(set(names)) != len(names):
            raise ValidationError("optimize.variables", "category names must be unique")
        if self.objective in ("min_count", "min_total") and self.target is None:
            raise ValidationError("optimize.target", f"required for objective {self.objective}")
        if self.objective == "min_count" and len(self.variables) != 1:
            raise ValidationError("optimize.variables", "min_count takes exactly one variable")
        if self.query.given is not None:
            raise ValidationError("optimize.query", "conditional queries are not supported")
        if self.budget is not None and self.budget < 0:
            raise ValidationError("optimize.budget", "must be non-negative")
        if self.workers is not None and self.workers < 1:
            raise ValidationError("optimize.workers", "must be at least 1")

    @property
    def max_total(self) -> int:
        """The cap: most cards the variables may use together.

        It is the room left after the fixed categories, further limited by ``budget``.
        """
        room = self.deck_size - sum(c.count for _, c in self.fixed)
        return min(room, self.budget) if self.budget is not None else room


def build_deck(problem: OptimizeProblem, counts: tuple[int, ...]) -> Deck:
    """Abstract deck for one assignment of variable counts."""
    cats: dict[str, int | Category] = dict(problem.fixed)
    for v, c in zip(problem.variables, counts, strict=True):
        cats[v.name] = Category(c, v.tags)
    return Deck.from_counts(problem.deck_size, cats)


def is_monotone(problem: OptimizeProblem, var: Variable) -> bool:
    """Whether adding a copy of ``var`` can never lower P (sufficient test, MATH §10.2).

    True when every test that counts ``var``'s cards is an "at least" test (``>=``, ``>``,
    or an ``assign`` demand) that the condition wants to be true, no test counts the
    filler cards, and no mulligans are modelled. ``assume_monotone`` overrides.
    """
    if problem.assume_monotone is not None:
        return problem.assume_monotone
    if problem.mulligan is not None:
        return False
    var_card = Card(var.name, 1, frozenset({var.name}) | var.tags)
    filler = Card(FILLER_NAME, 1, frozenset({FILLER_NAME}))

    def reads(node: Condition) -> bool:
        if isinstance(node, Compare | Between):
            return matches(node.sel, var_card) or matches(node.sel, filler)
        if isinstance(node, Assignable):
            return any(matches(d.sel, var_card) or matches(d.sel, filler) for d in node.demands)
        return False

    def ok(c: Condition, positive: bool) -> bool:
        """Is ``c`` non-decreasing (positive) / non-increasing (negative) in ``var``?"""
        match c:
            case Compare() | Between():
                if matches(c.sel, filler):
                    return False
                if not matches(c.sel, var_card):
                    return True
                return positive and isinstance(c, Compare) and c.op in (">=", ">")
            case Assignable(demands):
                if any(matches(d.sel, filler) for d in demands):
                    return False
                return positive or not any(matches(d.sel, var_card) for d in demands)
            case And(items) | Or(items) | AtLeast(_, items):
                return all(ok(i, positive) for i in items)
            case Not(item):
                return ok(item, not positive)
            case Implies(a, b):  # a -> b  ==  (NOT a) OR b
                return ok(a, not positive) and ok(b, positive)
            case At(_, item):
                return ok(item, positive)
            case Const():
                return True
            case _:  # XOR, exactly-n: mixed polarity, so only safe if var/filler unread
                return not any(reads(n) for n in walk(c))

    return ok(problem.query.condition, True)


# ---------------------------------------------------------------------------------------
# Search space
# ---------------------------------------------------------------------------------------


def _points(vs: Sequence[Variable], cap: int, total: int | None = None) -> Iterator[Point]:
    """Points within the bounds with sum <= ``cap`` (and == ``total`` if given).

    Branches that cannot reach the required sum are pruned, so slices are enumerated
    without walking the whole grid.
    """
    n = len(vs)
    lo_rest = [sum(v.lo for v in vs[i:]) for i in range(n + 1)]
    hi_rest = [sum(v.hi for v in vs[i:]) for i in range(n + 1)]
    bound = cap if total is None else min(cap, total)  # largest allowed sum
    x = [0] * n

    def rec(i: int, used: int) -> Iterator[Point]:
        if i == n:
            yield tuple(x)
            return
        for c in range(vs[i].lo, vs[i].hi + 1):
            s = used + c
            if s + lo_rest[i + 1] > bound:
                break
            if total is not None and s + hi_rest[i + 1] < total:
                continue
            x[i] = c
            yield from rec(i + 1, s)

    yield from rec(0, 0)


def count_points(vs: Sequence[Variable], cap: int, total: int | None = None) -> int:
    """Number of points :func:`_points` yields, by dynamic programming over the sum."""
    ways = {0: 1}
    for v in vs:
        nxt: dict[int, int] = {}
        for s, w in ways.items():
            for c in range(v.lo, v.hi + 1):
                if s + c > cap:
                    break
                nxt[s + c] = nxt.get(s + c, 0) + w
        ways = nxt
    if total is not None:
        return ways.get(total, 0)
    return sum(ways.values())


# ---------------------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------------------


#: Below this many seconds per evaluation, handing work to threads costs more than it saves.
PARALLEL_MIN_SECONDS = 0.002


class MemoEvaluator:
    """Memoized P(point), with adaptive parallel batch evaluation.

    Threads only help when the engine releases the GIL (the native engine does) and each
    evaluation is slow enough to outweigh the hand-off cost. The evaluator therefore
    times its evaluations and only goes parallel when they average at least
    ``PARALLEL_MIN_SECONDS``. Use it as a context manager so the threads are shut down.
    """

    def __init__(self, fn: Evaluator, workers: int = 1) -> None:
        self._fn = fn
        self.workers = workers
        self.memo: dict[Point, Fraction] = {}
        self._pool: ThreadPoolExecutor | None = None  # created on first parallel batch
        self._seconds = 0.0
        self._timed = 0

    def __enter__(self) -> MemoEvaluator:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        """Shut down the worker threads (if any were started)."""
        if self._pool is not None:
            self._pool.shutdown()
            self._pool = None

    def _run(self, point: Point) -> tuple[Fraction, float]:
        start = time.perf_counter()
        value = self._fn(point)
        return value, time.perf_counter() - start

    def _record(self, point: Point, value: Fraction, seconds: float) -> None:
        self.memo[point] = value
        self._seconds += seconds
        self._timed += 1

    @property
    def parallel(self) -> bool:
        """Whether batches are currently worth spreading over threads."""
        return (
            self.workers > 1
            and self._timed > 0
            and self._seconds / self._timed >= PARALLEL_MIN_SECONDS
        )

    @property
    def batch(self) -> int:
        """A good batch size for callers that can stop early (1 when running serially)."""
        return self.workers if self.parallel else 1

    def __call__(self, point: Point) -> Fraction:
        if point not in self.memo:
            self._record(point, *self._run(point))
        return self.memo[point]

    def many(self, points: Sequence[Point]) -> list[Fraction]:
        """Evaluate several points, in parallel when that pays off."""
        todo = list(dict.fromkeys(p for p in points if p not in self.memo))
        if todo and self._timed == 0:  # measure one evaluation before deciding
            self(todo.pop(0))
        if self.parallel and len(todo) > 1:
            if self._pool is None:  # one pool per optimization: thread start-up is not free
                self._pool = ThreadPoolExecutor(max_workers=self.workers)
            for p, (value, seconds) in zip(todo, self._pool.map(self._run, todo), strict=True):
                self._record(p, value, seconds)
        else:
            for p in todo:
                self(p)
        return [self.memo[p] for p in points]


def _rank(point: Point, p: Fraction) -> tuple[Fraction, int, Point]:
    """Sort key for "best": higher P, then fewer cards, then smaller counts first."""
    return (p, -sum(point), tuple(-x for x in point))


# ---------------------------------------------------------------------------------------
# Objectives
# ---------------------------------------------------------------------------------------


def optimize(
    problem: OptimizeProblem,
    evaluate: Evaluator | None = None,
    *,
    limit: int = DEFAULT_LIMIT,
) -> OptimizeResult:
    """Solve ``problem``. ``evaluate`` may be injected (tests, custom engines)."""

    def default_eval(counts: Point) -> Fraction:
        scenario = Scenario(build_deck(problem, counts), problem.game, problem.mulligan)
        prep = prepare(scenario, {"p": problem.query.condition}, turn=problem.query.turn)
        return exact_values(prep, limit=limit)["p"]

    workers = problem.workers
    if workers is None:
        workers = (os.cpu_count() or 1) if evaluate is None and native_available() else 1
    if sum(v.lo for v in problem.variables) > problem.max_total:
        raise InfeasibleError("the variables' lower bounds already exceed the cap")

    with MemoEvaluator(evaluate or default_eval, workers) as f:
        if problem.objective == "min_count":
            best, proven = _min_count(problem, f)
        elif problem.objective == "max_probability":
            best, proven = _max_probability(problem, f)
        else:
            best, proven = _min_total(problem, f)

    names = [v.name for v in problem.variables]

    def labelled(c: Point) -> Counts:
        return tuple(zip(names, c, strict=True))

    ranked = sorted(f.memo.items(), key=lambda kv: _rank(*kv), reverse=True)[:20]
    return OptimizeResult(
        counts=labelled(best),
        probability=f(best),
        proven_optimal=proven,
        evaluations=len(f.memo),
        frontier=tuple((labelled(c), p) for c, p in ranked),
    )


def _all_monotone(problem: OptimizeProblem) -> bool:
    return all(is_monotone(problem, v) for v in problem.variables)


def _min_count(problem: OptimizeProblem, f: MemoEvaluator) -> tuple[Point, bool]:
    """Fewest copies of the single variable reaching the target (always proven)."""
    (var,) = problem.variables
    target = problem.target
    assert target is not None
    lo, hi = var.lo, min(var.hi, problem.max_total)
    if is_monotone(problem, var):
        if f((hi,)) < target:
            raise InfeasibleError(f"even {hi} copies reach only {float(f((hi,))):.2%}")
        while lo < hi:  # invariant: f(hi) >= target; find the smallest such count
            mid = (lo + hi) // 2
            if f((mid,)) >= target:
                hi = mid
            else:
                lo = mid + 1
        return (lo,), True
    c = lo
    while c <= hi:  # scan upward in batches (parallel if worthwhile), stop at the first hit
        chunk = [(x,) for x in range(c, min(c + f.batch, hi + 1))]
        for point, p in zip(chunk, f.many(chunk), strict=True):
            if p >= target:
                return point, True
        c += len(chunk)
    raise InfeasibleError("no count in the range reaches the target")


def _best_on(problem: OptimizeProblem, f: MemoEvaluator, total: int | None) -> tuple[Point, bool]:
    """Best point with sum <= cap (``total=None``) or sum == ``total``.

    Exhaustive (proven) when the candidates fit in ``exhaustive_limit``, otherwise a
    local search (heuristic).
    """
    vs, cap = problem.variables, problem.max_total
    n = count_points(vs, cap, total)
    if n == 0:
        raise InfeasibleError("no assignment satisfies the bounds")
    if n <= problem.exhaustive_limit:
        points = list(_points(vs, cap, total))
        values = f.many(points)
        best = max(zip(points, values, strict=True), key=lambda pv: _rank(*pv))
        return best[0], True
    return _local_search(problem, f, total), False


def _max_probability(problem: OptimizeProblem, f: MemoEvaluator) -> tuple[Point, bool]:
    """Highest P within the cap. Monotone problems only search the full-cap slice."""
    if _all_monotone(problem):
        full = min(problem.max_total, sum(v.hi for v in problem.variables))
        return _best_on(problem, f, full)
    return _best_on(problem, f, None)


def _min_total(problem: OptimizeProblem, f: MemoEvaluator) -> tuple[Point, bool]:
    """Smallest total whose best split reaches the target.

    With a monotone condition the best P per total rises with the total, so the total
    is binary-searched; otherwise totals are tried in increasing order.
    """
    target = problem.target
    assert target is not None
    lo = sum(v.lo for v in problem.variables)
    hi = min(problem.max_total, sum(v.hi for v in problem.variables))
    proven = True

    def best(total: int) -> Point:
        nonlocal proven
        point, exact = _best_on(problem, f, total)
        proven = proven and exact
        return point

    if _all_monotone(problem):
        top = best(hi)
        if f(top) < target:
            raise InfeasibleError(f"even a total of {hi} reaches only {float(f(top)):.2%}")
        answer = top
        while lo < hi:
            mid = (lo + hi) // 2
            point = best(mid)
            if f(point) >= target:
                hi, answer = mid, point
            else:
                lo = mid + 1
        return answer, proven
    for total in range(lo, hi + 1):
        point = best(total)
        if f(point) >= target:
            return point, proven
    raise InfeasibleError("no assignment within the bounds reaches the target")


def _bump(x: Sequence[int], i: int, delta: int = 1) -> Point:
    """``x`` with component ``i`` changed by ``delta``."""
    return (*x[:i], x[i] + delta, *x[i + 1 :])


def _local_search(problem: OptimizeProblem, f: MemoEvaluator, total: int | None) -> Point:
    """Heuristic for large spaces: greedy ascent from the lower bounds, then
    "move one card from variable j to variable i" steps until nothing improves."""
    vs = problem.variables
    cap = problem.max_total if total is None else total
    x: Point = tuple(v.lo for v in vs)
    while sum(x) < cap:  # greedy: add the single most valuable copy
        moves = [_bump(x, i) for i, v in enumerate(vs) if x[i] < v.hi]
        if not moves:
            break
        values = f.many(moves)
        nxt, value = max(zip(moves, values, strict=True), key=lambda mv: mv[1])
        if total is None and value <= f(x):
            break  # adding cards no longer helps
        x = nxt
    if total is not None and sum(x) != total:
        raise InfeasibleError(f"cannot reach a total of {total} within the bounds")
    while True:  # local moves keep the total fixed
        moves = [
            _bump(_bump(x, i), j, -1)
            for i in range(len(vs))
            for j in range(len(vs))
            if i != j and x[i] < vs[i].hi and x[j] > vs[j].lo
        ]
        if not moves:
            return x
        nxt, value = max(zip(moves, f.many(moves), strict=True), key=lambda mv: mv[1])
        if value <= f(x):
            return x
        x = nxt
