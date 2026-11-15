//! Public entry points with exact big-integer fallback (ADR-0002, ADR-0009).
//!
//! Each function first computes with `u128` weights; if any operation would overflow it
//! repeats the computation with [`BigUint`]. Callers always get exact results and never
//! see [`Error::Overflow`].

use num_bigint::BigUint;

use crate::engine::{self, Options, Output, Query, Start};
use crate::error::{Error, Result};
use crate::mulligan::{self, DepthResult, HandValue};
use crate::policy::MulliganPlan;
use crate::weight::Weight;

/// Evaluates a query exactly (see [`engine::run`]).
///
/// # Errors
/// [`Error::Invalid`] for malformed input, [`Error::Limit`] when too many states are live.
pub fn run(q: &Query, start: Option<&Start>, opts: &Options) -> Result<Output<BigUint>> {
    match engine::run::<u128>(q, start, opts) {
        Err(Error::Overflow) => engine::run::<BigUint>(q, start, opts),
        other => other.map(|o| o.to_big()),
    }
}

/// Every mulligan depth, exactly (see [`mulligan::depths`]).
///
/// # Errors
/// As [`run`].
pub fn mulligan_depths(
    q: &Query,
    plan: &MulliganPlan,
    opts: &Options,
) -> Result<Vec<DepthResult<BigUint>>> {
    match mulligan::depths::<u128>(q, plan, opts) {
        Err(Error::Overflow) => mulligan::depths::<BigUint>(q, plan, opts),
        other => other.map(|depths| depths.iter().map(depth_to_big).collect()),
    }
}

/// Per-hand success values, exactly (see [`mulligan::hand_values`]).
///
/// # Errors
/// As [`run`].
pub fn hand_values(
    q: &Query,
    plan: &MulliganPlan,
    output: usize,
    opts: &Options,
) -> Result<Vec<Vec<HandValue<BigUint>>>> {
    match mulligan::hand_values::<u128>(q, plan, output, opts) {
        Err(Error::Overflow) => mulligan::hand_values::<BigUint>(q, plan, output, opts),
        other => other.map(|depths| {
            depths
                .iter()
                .map(|hands| hands.iter().map(hand_to_big).collect())
                .collect()
        }),
    }
}

fn depth_to_big<W: Weight>(d: &DepthResult<W>) -> DepthResult<BigUint> {
    DepthResult {
        keep_weight: d.keep_weight.to_big(),
        hands_total: d.hands_total.to_big(),
        outputs: d.outputs.iter().map(Weight::to_big).collect(),
        denominator: d.denominator.to_big(),
    }
}

fn hand_to_big<W: Weight>(h: &HandValue<W>) -> HandValue<BigUint> {
    HandValue {
        hand: h.hand.clone(),
        weight: h.weight.to_big(),
        success: h.success.to_big(),
        denominator: h.denominator.to_big(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::engine::tests::{single_atom, OPTS};

    /// The u128 path overflows here; the public API must still answer exactly and agree
    /// with a direct big-integer run.
    #[test]
    fn overflow_falls_back_to_big_integers() {
        let q = single_atom(
            250,
            100,
            7,
            std::iter::once(0).chain([10; 20]).collect(),
            50,
        );
        let out = run(&q, None, &OPTS).unwrap();
        assert_eq!(out, engine::run::<BigUint>(&q, None, &OPTS).unwrap());
    }

    #[test]
    fn small_queries_use_the_fast_path_and_agree() {
        let q = single_atom(60, 24, 7, vec![0, 1, 1], 3);
        let fast = run(&q, None, &OPTS).unwrap();
        assert_eq!(fast, engine::run::<BigUint>(&q, None, &OPTS).unwrap());
    }
}
