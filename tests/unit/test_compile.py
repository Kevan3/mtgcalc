"""Unit tests: atomizer, schedule, logic, compiler, policy (LLD §4)."""

from __future__ import annotations

import itertools

import pytest
from hypothesis import given
from hypothesis import strategies as st

from mtgcalc import (
    Assignable,
    Card,
    Const,
    Deck,
    Demand,
    GameConfig,
    MulliganConfig,
    PriorityGroup,
    card,
    count,
    everything,
    none_of,
    tag,
)
from mtgcalc.compile.atomizer import atomize
from mtgcalc.compile.compiler import compile_predicate, compile_query
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
    conjoin_bit,
    hall_feasible,
    run2,
    run3,
)
from mtgcalc.compile.policy import ResolvedPolicy, bottom, lower_bounds, resolve_policy
from mtgcalc.compile.schedule import plan
from mtgcalc.errors import ValidationError

DECK = Deck(
    (
        Card("Forest", 30, frozenset({"land"})),
        Card("Dryad Arbor", 1, frozenset({"land", "creature"})),
        Card("Llanowar Elves", 4, frozenset({"creature", "ramp"})),
        Card("Rampant Growth", 4, frozenset({"ramp"})),
        Card("Filler", 21),
    )
)
LAND, RAMP, CREATURE = tag("land"), tag("ramp"), tag("creature")


# --- atomizer -------------------------------------------------------------------------
def test_overlapping_tags_become_disjoint_atoms() -> None:
    t = atomize(DECK, [LAND, RAMP])
    assert t.pool == 21 + 0  # filler only (Dryad Arbor is a land)
    assert sorted(t.counts) == [4 + 4, 31]
    assert sum(t.counts) + t.pool == DECK.size
    assert sum(t.counts[i] for i in t.mask(LAND)) == 31
    assert sum(t.counts[i] for i in t.mask(RAMP)) == 8


def test_three_way_overlap() -> None:
    t = atomize(DECK, [LAND, RAMP, CREATURE])
    by_names = {names: c for names, c in zip(t.names, t.counts, strict=True)}
    assert by_names[("Dryad Arbor",)] == 1
    assert by_names[("Llanowar Elves",)] == 4
    assert sum(t.counts[i] for i in t.mask(CREATURE)) == 5


def test_complement_selectors_track_pool_cards() -> None:
    t = atomize(DECK, [none_of("land", "ramp")])
    assert t.pool == 31 + 8 and t.counts == (21,)
    t2 = atomize(DECK, [everything()])
    assert t2.pool == 0 and t2.counts == (60,)


def test_atomize_rejects_unknown_card_and_unatomized_mask() -> None:
    with pytest.raises(ValidationError):
        atomize(DECK, [card("Black Lotus")])
    with pytest.raises(ValidationError):
        atomize(DECK, [LAND]).mask(RAMP)


def test_atomize_dedupes_selectors() -> None:
    assert atomize(DECK, [LAND, LAND]).selectors == (LAND,)


# --- schedule -------------------------------------------------------------------------
def test_plan_batches() -> None:
    bp = plan(GameConfig(on_play=True, extra_draws={3: 2}), [4, 2], 7)
    assert bp.checkpoints == (0, 2, 4)
    assert bp.batches == (0, 1, 4)  # turn 2: 1; turns 3-4: (1 + 2 extra) + 1
    assert [bp.cards_seen(j) for j in range(3)] == [7, 8, 12]
    assert bp.total_draws == 5


# --- logic ----------------------------------------------------------------------------
def _eval_all(prog: tuple[int, ...], n_bits: int) -> list[bool]:
    return [run2(prog, b) for b in range(1 << n_bits)]


def test_run2_opcodes() -> None:
    assert _eval_all((BIT, 0, BIT, 1, AND, 2), 2) == [False, False, False, True]
    assert _eval_all((BIT, 0, BIT, 1, OR, 2), 2) == [False, True, True, True]
    assert _eval_all((BIT, 0, BIT, 1, XOR), 2) == [False, True, True, False]
    assert _eval_all((BIT, 0, BIT, 1, IMPLIES), 2) == [True, False, True, True]
    assert _eval_all((BIT, 0, NOT), 1) == [True, False]
    assert _eval_all((BIT, 0, BIT, 1, BIT, 2, ATLEAST, 2, 3), 3) == [
        False,
        False,
        False,
        True,
        False,
        True,
        True,
        True,
    ]
    assert _eval_all((BIT, 0, BIT, 1, BIT, 2, EXACTLY, 1, 3), 3) == [
        False,
        True,
        True,
        False,
        True,
        False,
        False,
        False,
    ]
    assert run2((CONST, 1), 0) and not run2((CONST, 0), 0)
    assert conjoin_bit((CONST, 1), 0) == (CONST, 1, BIT, 0, AND, 2)


def _random_program(draw: st.DrawFn, depth: int, n_bits: int) -> tuple[int, ...]:
    if depth == 0 or draw(st.booleans()):
        if draw(st.integers(0, 5)) == 0:
            return (CONST, draw(st.integers(0, 1)))
        return (BIT, draw(st.integers(0, n_bits - 1)))
    op = draw(st.sampled_from([AND, OR, XOR, IMPLIES, NOT, ATLEAST, EXACTLY]))
    if op == NOT:
        return (*_random_program(draw, depth - 1, n_bits), NOT)
    if op in (XOR, IMPLIES):
        a = _random_program(draw, depth - 1, n_bits)
        b = _random_program(draw, depth - 1, n_bits)
        return (*a, *b, op)
    n = draw(st.integers(1, 3))
    parts = [x for _ in range(n) for x in _random_program(draw, depth - 1, n_bits)]
    if op in (AND, OR):
        return (*parts, op, n)
    return (*parts, op, draw(st.integers(0, n + 1)), n)


@st.composite
def programs(draw: st.DrawFn) -> tuple[tuple[int, ...], int, int]:
    n_bits = 4
    prog = _random_program(draw, 3, n_bits)
    return prog, draw(st.integers(0, 15)), draw(st.integers(0, 15))


@given(programs())
def test_run3_is_sound(case: tuple[tuple[int, ...], int, int]) -> None:
    """A decided three-valued result equals every two-valued completion (MATH §7.3)."""
    prog, bits, known = case
    verdict = run3(prog, bits, known)
    unknown = [i for i in range(4) if not known >> i & 1]
    completions = set()
    for fill in itertools.product([0, 1], repeat=len(unknown)):
        b = bits & known
        for i, v in zip(unknown, fill, strict=True):
            b |= v << i
        completions.add(run2(prog, b))
    if verdict is not None:
        assert completions == {verdict}
    if known == 0b1111:
        assert verdict == run2(prog, bits)


def test_run3_decides_early_when_possible() -> None:
    # (bit0 OR bit1) with bit0 known true -> True even though bit1 unknown
    assert run3((BIT, 0, BIT, 1, OR, 2), 0b01, 0b01) is True
    assert run3((BIT, 0, BIT, 1, AND, 2), 0b00, 0b01) is False
    assert run3((BIT, 0, BIT, 1, AND, 2), 0b01, 0b01) is None
    assert run3((BIT, 0, BIT, 1, IMPLIES), 0, 0b01) is True
    assert run3((BIT, 0, BIT, 1, ATLEAST, 1, 2), 0b01, 0b01) is True
    assert run3((BIT, 0, BIT, 1, EXACTLY, 0, 2), 0b01, 0b01) is False


def _brute_assign(demands: tuple[tuple[tuple[int, ...], int], ...], seen: tuple[int, ...]) -> bool:
    cards = [i for i, n in enumerate(seen) for _ in range(n)]
    slots = [mask for mask, need in demands for _ in range(need)]
    if len(slots) > len(cards):
        return False
    for chosen in itertools.permutations(range(len(cards)), len(slots)):
        if all(cards[c] in mask for c, mask in zip(chosen, slots, strict=True)):
            return True
    return False


@given(
    st.lists(
        st.tuples(
            st.lists(st.integers(0, 2), min_size=1, max_size=3, unique=True).map(
                lambda x: tuple(sorted(x))
            ),
            st.integers(1, 2),
        ),
        min_size=1,
        max_size=3,
    ).map(tuple),
    st.tuples(st.integers(0, 2), st.integers(0, 2), st.integers(0, 2)),
)
def test_hall_matches_brute_force_assignment(
    demands: tuple[tuple[tuple[int, ...], int], ...], seen: tuple[int, int, int]
) -> None:
    assert hall_feasible(demands, seen) == _brute_assign(demands, seen)


def test_hall_mdfc_example() -> None:
    """MATH §8: two lands + one MDFC (land/ramp) cannot give 3 lands AND 1 ramp."""
    # atoms: 0 = pure land, 1 = MDFC (land & ramp)
    assert not hall_feasible((((0, 1), 3), ((1,), 1)), (2, 1))
    assert hall_feasible((((0, 1), 2), ((1,), 1)), (2, 1))


# --- compiler ---------------------------------------------------------------------------
def test_leaf_dedupe_and_checkpoint_ordered_bits() -> None:
    a = count(LAND) >= 2
    cond = (a.at(3) & (count(RAMP) >= 1)) | a.at(3)
    cq = compile_query(DECK, GameConfig(), {"x": cond}, hand_size=7, turn=0)
    assert len(cq.leaves) == 2
    by_cp = [(leaf.checkpoint, leaf.bit) for leaf in cq.leaves]
    assert by_cp == sorted(by_cp)
    assert cq.leaves[0].checkpoint == 0  # ramp@T0 gets the lower bit
    assert cq.known_through(0) == 0b01 and cq.known_through(1) == 0b11


def test_innermost_at_wins() -> None:
    cond = ((count(LAND) >= 1).at(1)).at(5)
    cq = compile_query(DECK, GameConfig(), {"x": cond}, hand_size=7)
    assert cq.plan.checkpoints == (0, 1)


def test_retirement_plan() -> None:
    cond = (count(RAMP) >= 1).at(0) & (count(LAND) >= 3).at(3)
    cq = compile_query(DECK, GameConfig(), {"x": cond}, hand_size=7)
    land_atoms = set(cq.atoms.mask(LAND))
    ramp_only = set(cq.atoms.mask(RAMP)) - land_atoms
    assert set(cq.retire_after[0]) == ramp_only
    assert set(cq.retire_after[1]) == land_atoms


def test_draw_region_validation() -> None:
    small = Deck.from_counts(8, {"a": 2})
    with pytest.raises(ValidationError):
        compile_query(small, GameConfig(), {"x": (count("a") >= 1).at(3)}, hand_size=7)


def test_compile_predicate() -> None:
    atoms = atomize(DECK, [LAND, RAMP])
    leaves, prog = compile_predicate((count(LAND) >= 2) & ~(count(RAMP) >= 1), atoms)
    assert len(leaves) == 2 and prog[-2:] == (AND, 2)


# --- policy -----------------------------------------------------------------------------
def test_lower_bounds_polarity() -> None:
    cond = (
        (count(LAND) >= 2)
        & (count(RAMP) > 0)
        & ~(count(CREATURE) < 3)
        & ~(count(tag("x")) <= 1)
        & ~(count(tag("y")) >= 5)
        & count(tag("z")).between(2, 4)
        & Assignable((Demand(tag("w"), 2),))
        & (count(tag("e")).eq(1))
    )
    assert lower_bounds([cond]) == {
        LAND: 2,
        RAMP: 1,
        CREATURE: 3,
        tag("x"): 2,
        tag("z"): 2,
        tag("w"): 2,
        tag("e"): 1,
    }
    assert lower_bounds([(count(LAND) >= 1) ^ (count(RAMP) >= 1)]) == {}
    assert lower_bounds([(count(RAMP) >= 9).implies(count(LAND) >= 4)]) == {LAND: 4}


def test_resolve_policy_quotas() -> None:
    atoms = atomize(DECK, [LAND, RAMP, CREATURE])
    cfg = MulliganConfig(
        (PriorityGroup(LAND), PriorityGroup(RAMP, quota=1), PriorityGroup(CREATURE)),
        keep_rule=count(LAND) >= 2,
    )
    pol = resolve_policy(cfg, [count(LAND) >= 3], atoms)
    assert [q for _, q in pol.rules] == [3, 1, 7]


def test_bottom_order_pool_then_unprotected_then_release() -> None:
    # atoms: 0 = land, 1 = ramp; rules: land quota 2 (high), ramp quota 1 (low)
    pol = ResolvedPolicy((((0,), 2), ((1,), 1)))
    hand = (4, 2)  # + 1 pool card = 7
    assert bottom(pol, hand, 1, 1) == (0, 0)  # pool card first
    assert bottom(pol, hand, 1, 2) == (0, 1)  # then unprotected ramp (lower priority)
    assert bottom(pol, hand, 1, 4) == (2, 1)  # then unprotected lands
    assert bottom(pol, hand, 1, 5) == (2, 2)  # release lowest priority (ramp) first
    assert bottom(pol, hand, 1, 7) == (4, 2)


def test_bottom_unmatched_atoms_go_first() -> None:
    pol = ResolvedPolicy((((0,), 1),))
    assert bottom(pol, (2, 3), 0, 3) == (0, 3)


def test_bottom_multi_role_protected_first() -> None:
    # atom 0 = land only, atom 1 = land+ramp; rules: land quota 1, ramp quota 1
    pol = ResolvedPolicy((((0, 1), 1), ((1,), 1)))
    # protecting the MDFC for "land" also satisfies "ramp": keep the MDFC, bottom a land
    assert bottom(pol, (1, 1), 0, 1) == (1, 0)


def test_bottom_rejects_overdraw() -> None:
    with pytest.raises(ValidationError):
        bottom(ResolvedPolicy(()), (1,), 0, 2)


@given(
    st.tuples(st.integers(0, 3), st.integers(0, 3), st.integers(0, 3)),
    st.integers(0, 3),
    st.data(),
)
def test_bottom_conservation(hand: tuple[int, int, int], pool: int, data: st.DataObject) -> None:
    n = data.draw(st.integers(0, sum(hand) + pool))
    pol = ResolvedPolicy((((0, 1), data.draw(st.integers(0, 4))), ((2,), 1)))
    b = bottom(pol, hand, pool, n)
    assert all(0 <= x <= h for x, h in zip(b, hand, strict=True))
    assert n - pool <= sum(b) <= n


def test_keep_rule_constant() -> None:
    atoms = atomize(DECK, [LAND])
    leaves, prog = compile_predicate(Const(False), atoms)
    assert leaves == () and not run2(prog, 0)
