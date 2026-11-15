"""Unit tests: exact engine, estimate, Monte Carlo (LLD §5)."""

from __future__ import annotations

from fractions import Fraction

import pytest

from mtgcalc import And, Const, Deck, GameConfig, count, tag
from mtgcalc.compile.compiler import compile_query
from mtgcalc.engine.exact import ExactEngine, default_initial_states
from mtgcalc.engine.montecarlo import simulate
from mtgcalc.errors import StateSpaceTooLargeError, ValidationError
from mtgcalc.math.comb import binom

DECK = Deck.from_counts(40, {"land": 17, "ramp": 3})


def _cq(cond, turn: int = 0, **kw):  # type: ignore[no-untyped-def]
    return compile_query(DECK, GameConfig(), {"x": cond}, hand_size=7, turn=turn, **kw)


def test_default_initial_states_sum_to_denominator() -> None:
    init = default_initial_states(_cq(count("land") >= 1))
    assert sum(init.states.values()) == init.denominator == binom(40, 7)


def test_single_checkpoint_equals_closed_form() -> None:
    res = ExactEngine().run(_cq(count("land") >= 3, turn=3))
    expected = sum(binom(17, k) * binom(23, 9 - k) for k in range(3, 10))
    assert Fraction(res.outputs["x"], res.denominator) == Fraction(expected, binom(40, 9))


def test_observer_snapshot_is_pmf() -> None:
    cq = compile_query(DECK, GameConfig(), {}, hand_size=7, observe=[(2, tag("land"))])
    res = ExactEngine().run(cq)
    nums, den = res.snapshots[(1, cq.atoms.mask(tag("land")))]
    assert sum(nums) == den
    assert nums[2] * binom(40, 8) == binom(17, 2) * binom(23, 6) * den


@pytest.mark.parametrize("early", [True, False])
@pytest.mark.parametrize("retire", [True, False])
def test_optimizations_do_not_change_results(early: bool, retire: bool) -> None:
    cond = ((count("land") >= 2).at(0) | (count("ramp") >= 1).at(2)) & (count("land") >= 4).at(4)
    base = ExactEngine(early_resolution=False, retirement=False).run(_cq(cond))
    res = ExactEngine(early_resolution=early, retirement=retire).run(_cq(cond))
    assert Fraction(res.outputs["x"], res.denominator) == Fraction(
        base.outputs["x"], base.denominator
    )


def test_early_resolution_reduces_states() -> None:
    cond = (count("land") >= 1).at(0) | (count("land") >= 5).at(6)
    slow = ExactEngine(early_resolution=False, retirement=False).run(_cq(cond))
    fast = ExactEngine().run(_cq(cond))
    assert fast.peak_states <= slow.peak_states


def test_state_limit_raises() -> None:
    with pytest.raises(StateSpaceTooLargeError) as e:
        ExactEngine().run(_cq((count("land") >= 1).at(5) & (count("ramp") >= 1)), limit=3)
    assert e.value.limit == 3


def test_engine_rejects_overdraw_initial_state() -> None:
    from mtgcalc.engine.base import InitialStates

    cq = _cq((count("land") >= 1).at(3))
    with pytest.raises(ValidationError):
        ExactEngine().run(cq, InitialStates({}, 1, 39))


def test_initial_states_respect_the_limit() -> None:
    with pytest.raises(StateSpaceTooLargeError):
        ExactEngine().run(_cq(count("land") >= 1), limit=1)


def test_monte_carlo_is_seeded_and_deterministic() -> None:
    cq = _cq(count("land") >= 3, turn=2)
    a = simulate(cq, trials=500, seed=7)
    b = simulate(cq, trials=500, seed=7)
    assert a == b
    assert a[1] == 500


def test_monte_carlo_trivial_queries_exact() -> None:
    cq = compile_query(DECK, GameConfig(), {"t": Const(True), "f": Const(False)}, hand_size=7)
    hits, n = simulate(cq, trials=200, seed=1)
    assert hits == {"t": 200, "f": 0} and n == 200


def test_monte_carlo_rejects_zero_trials() -> None:
    with pytest.raises(ValidationError):
        simulate(_cq(Const(True)), trials=0)


def test_native_adapter_flatten_and_support() -> None:
    from mtgcalc.engine.native import MAX_BITS, _flatten, supported

    cq = _cq((count("land") >= 2).at(0) & (count("ramp") >= 1).at(2))
    flat = _flatten(cq)
    assert flat[0] == 40 and flat[3] == 7 and len(flat) == 10
    assert flat[5][0][2] == 0 and flat[5][0][4] == 5  # kind cmp, op ">="
    assert supported(cq)
    many = _cq(And(tuple((count("land") >= k).at(k % 4) for k in range(MAX_BITS + 1))))
    assert not supported(many)


def test_engine_selection_respects_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from mtgcalc.engine import select

    monkeypatch.setenv("MTGCALC_ENGINE", "python")
    assert not select.native_available()
    assert isinstance(select.default_engine(), ExactEngine)
