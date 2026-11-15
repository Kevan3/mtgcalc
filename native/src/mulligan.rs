//! Mulligan enumeration (LLD §5.6, MATH §9).
//!
//! A port of `mtgcalc.engine.mulligan` (the Python reference): for each depth, every
//! 7-card draw composition is enumerated, the bottom policy and keep rule are applied,
//! and the DP of [`crate::engine`] is seeded with `(kept, bottomed, keep bit)` states.
//! Everything happens in one call, so Python is only involved at the start and the end.

use rustc_hash::FxHashMap;

use crate::binom::Binom;
use crate::engine::{binom_for, dp, insert, transitions, Dist, Key, Options, Query};
use crate::error::{invalid, Result};
use crate::policy::MulliganPlan;
use crate::weight::{add, Weight};

/// Predicate bit set when a hand was kept (must match `mtgcalc.compile.policy.KEEP_BIT`).
pub const KEEP_BIT: u32 = 0;

/// Results for one depth: P(keep) = `keep_weight / hands_total`; output `o` =
/// `outputs[o] / denominator`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DepthResult<W> {
    /// Weight of the drawn hands the keep rule accepts (all of them at the last depth).
    pub keep_weight: W,
    /// Weight of all drawn hands, `C(N, draw)`.
    pub hands_total: W,
    /// Numerator per output.
    pub outputs: Vec<W>,
    /// Shared denominator of `outputs`.
    pub denominator: W,
}

/// One drawn-hand composition at one depth: P(drawing it) = `weight / C(N, draw)`;
/// P(success | keep it) = `success / denominator`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HandValue<W> {
    /// Atom counts of the 7 drawn cards (before bottoming).
    pub hand: Vec<u16>,
    /// Number of 7-card subsets with this composition.
    pub weight: W,
    /// Success numerator if this hand is kept.
    pub success: W,
    /// Success denominator.
    pub denominator: W,
}

/// A drawn hand after bottoming at one depth.
struct Drawn<W> {
    hand: Vec<u16>,
    kept: Vec<u16>,
    bottomed: Vec<u16>,
    weight: W,
}

/// Every drawn-hand composition at `depth`, with what the policy keeps.
fn drawn_hands<W: Weight>(
    q: &Query,
    plan: &MulliganPlan,
    binom: &Binom<W>,
    depth: usize,
) -> Result<Vec<Drawn<W>>> {
    transitions(binom, &q.counts, q.pool, plan.draw)?
        .into_iter()
        .map(|(hand, weight)| {
            let tracked: u32 = hand.iter().map(|&h| u32::from(h)).sum();
            let bottomed = plan
                .policy
                .bottom(&hand, plan.draw - tracked, plan.bottoms[depth])?;
            let kept = hand.iter().zip(&bottomed).map(|(h, b)| h - b).collect();
            Ok(Drawn {
                hand,
                kept,
                bottomed,
                weight,
            })
        })
        .collect()
}

fn key(kept: &[u16], bottomed: &[u16], bits: u64) -> Key {
    Key {
        counts: kept.iter().chain(bottomed).copied().collect(),
        bits,
    }
}

fn check(q: &Query, plan: &MulliganPlan) -> Result<()> {
    q.validate()?;
    plan.validate(q.counts.len())?;
    if q.hand_size != plan.draw {
        return Err(invalid("a mulligan query must start from the full draw"));
    }
    #[allow(clippy::absurd_extreme_comparisons)] // KEEP_BIT is 0 today; keep the general form
    if q.reserved_bits <= KEEP_BIT {
        return Err(invalid("a mulligan query must reserve the keep bit"));
    }
    Ok(())
}

/// Keep weight and every output, per depth `0..=M` (MATH §9.3).
///
/// # Errors
/// As [`crate::engine::run`].
pub fn depths<W: Weight>(
    q: &Query,
    plan: &MulliganPlan,
    opts: &Options,
) -> Result<Vec<DepthResult<W>>> {
    check(q, plan)?;
    let binom = binom_for::<W>(q, plan.draw);
    let hands_total = binom.get(q.deck_size, plan.draw)?;
    (0..=plan.max_depth())
        .map(|m| {
            let mut dist: Dist<W> = Dist::default();
            let mut keep_weight = W::zero();
            for d in drawn_hands(q, plan, &binom, m)? {
                let keep = m == plan.max_depth() || plan.keeps(&d.kept);
                let bits = if keep { 1u64 << KEEP_BIT } else { 0 };
                if keep {
                    keep_weight = add(&keep_weight, &d.weight)?;
                }
                insert(&mut dist, key(&d.kept, &d.bottomed, bits), d.weight)?;
            }
            let out = dp(q, &binom, dist, hands_total.clone(), plan.draw, opts)?;
            Ok(DepthResult {
                keep_weight,
                hands_total: hands_total.clone(),
                outputs: out.outputs,
                denominator: out.denominator,
            })
        })
        .collect()
}

/// Per depth, every drawn-hand composition with P(output `output` | keep it) (MATH §9.5).
///
/// Each distinct `(kept, bottomed)` pair is evaluated once, even if it occurs at several
/// depths (e.g. with a free mulligan).
///
/// # Errors
/// As [`crate::engine::run`], plus [`crate::Error::Invalid`] for an unknown output.
pub fn hand_values<W: Weight>(
    q: &Query,
    plan: &MulliganPlan,
    output: usize,
    opts: &Options,
) -> Result<Vec<Vec<HandValue<W>>>> {
    check(q, plan)?;
    if output >= q.outputs.len() {
        return Err(invalid("output index out of range"));
    }
    let binom = binom_for::<W>(q, plan.draw);
    let mut cache: FxHashMap<(Vec<u16>, Vec<u16>), (W, W)> = FxHashMap::default();
    let mut per_depth = Vec::with_capacity(plan.bottoms.len());
    for m in 0..=plan.max_depth() {
        let mut values = Vec::new();
        for d in drawn_hands(q, plan, &binom, m)? {
            let cache_key = (d.kept, d.bottomed);
            if !cache.contains_key(&cache_key) {
                let mut start: Dist<W> = Dist::default();
                start.insert(key(&cache_key.0, &cache_key.1, 1u64 << KEEP_BIT), W::one());
                let out = dp(q, &binom, start, W::one(), plan.draw, opts)?;
                let success = out.outputs[output].clone();
                cache.insert(cache_key.clone(), (success, out.denominator));
            }
            let (success, denominator) = cache[&cache_key].clone();
            values.push(HandValue {
                hand: d.hand,
                weight: d.weight,
                success,
                denominator,
            });
        }
        per_depth.push(values);
    }
    Ok(per_depth)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::engine::tests::OPTS;
    use crate::logic::{Leaf, Program};
    use crate::policy::Policy;

    /// 60 cards with 4 copies of X (atom 0); success = keep = "X >= 1"; London, M = 1.
    fn four_of(max_depth: usize, free: u32) -> (Query, MulliganPlan) {
        let x_ge_1 = |bit| Leaf::new(bit, 0, 0, vec![0], 5, 1, 0, 0, vec![], 1).unwrap();
        let q = Query {
            deck_size: 60,
            counts: vec![4],
            pool: 56,
            hand_size: 7,
            batches: vec![0],
            leaves: vec![x_ge_1(1)],
            // outputs: success, success & keep
            outputs: vec![
                Program::new(vec![0, 1]).unwrap(),
                Program::new(vec![0, 1, 0, 0, 3, 2]).unwrap(),
            ],
            observers: vec![],
            retire_after: vec![vec![]],
            reserved_bits: 1,
        };
        let plan = MulliganPlan {
            policy: Policy::new(vec![(vec![0], 7)], 1).unwrap(),
            keep_leaves: vec![x_ge_1(0)],
            keep: Program::new(vec![0, 0]).unwrap(),
            bottoms: (0..=max_depth as u32)
                .map(|m| m.saturating_sub(free))
                .collect(),
            draw: 7,
        };
        (q, plan)
    }

    fn binom_u(n: u128, k: u128) -> u128 {
        (0..k).fold(1, |acc, i| acc * (n - i) / (i + 1))
    }

    /// Reference A3 (MATH §9.3): with a protected single card, every depth finds it as
    /// often as a fresh 7, so keep weight = success weight = C(60,7) - C(56,7).
    #[test]
    fn london_mulligan_keeps_the_card() {
        let (q, plan) = four_of(1, 0);
        let depths: Vec<DepthResult<u128>> = depths(&q, &plan, &OPTS).unwrap();
        let hit = binom_u(60, 7) - binom_u(56, 7);
        assert_eq!(depths.len(), 2);
        assert_eq!(depths[0].keep_weight, hit);
        assert_eq!(depths[0].hands_total, binom_u(60, 7));
        assert_eq!(
            depths[0].outputs[1] * depths[0].hands_total,
            hit * depths[0].denominator
        );
        assert_eq!(depths[1].keep_weight, depths[1].hands_total); // forced keep at M
    }

    #[test]
    fn hand_values_are_conditional_successes() {
        let (q, plan) = four_of(2, 1);
        let values: Vec<Vec<HandValue<u128>>> = hand_values(&q, &plan, 0, &OPTS).unwrap();
        assert_eq!(values.len(), 3);
        for depth in &values {
            let total: u128 = depth.iter().map(|v| v.weight).sum();
            assert_eq!(total, binom_u(60, 7));
            for v in depth {
                // success iff the hand holds a copy (the policy never bottoms it)
                let expected = u128::from(v.hand[0] >= 1);
                assert_eq!(v.success, expected * v.denominator);
            }
        }
    }

    #[test]
    fn mismatched_queries_are_rejected() {
        let (mut q, plan) = four_of(1, 0);
        q.reserved_bits = 0;
        q.leaves = vec![Leaf::new(0, 0, 0, vec![0], 5, 1, 0, 0, vec![], 1).unwrap()];
        assert!(depths::<u128>(&q, &plan, &OPTS).is_err());
        let (q, plan) = four_of(1, 0);
        assert!(hand_values::<u128>(&q, &plan, 9, &OPTS).is_err());
    }
}
