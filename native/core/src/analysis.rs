//! Questions under the London mulligan (port of `mtgcalc.analysis.prepare` and
//! `mtgcalc.analysis.mulligan`, port stage 4, FR-40 – FR-48, MATH §9).
//!
//! The engine enumerates each depth's drawn hands and returns exact integers; this
//! module turns them into probabilities: depths are combined with the law of total
//! probability (MATH §9.3), and the optimal keep strategy is found by backward induction
//! (MATH §9.5).

use num_bigint::BigUint;

use crate::api;
use crate::binom::Binom;
use crate::compile::{build_plan, compile_query, CompileRequest, CompiledQuery};
use crate::engine::Options;
use crate::error::{validation, Error, Result};
use crate::model::{Condition, Scenario, Selector};
use crate::mulligan::KEEP_BIT;
use crate::policy::MulliganPlan;
use crate::probability::Fraction;

/// A compiled question, plus the mulligan plan when the scenario models mulligans.
///
/// With a mulligan, bit [`KEEP_BIT`] means "this hand was kept", and output `n + i`
/// (for `n` outputs) is output `i` AND kept.
#[derive(Clone, Debug)]
pub struct Prepared {
    /// The compiled outputs (and their "and kept" companions).
    pub cq: CompiledQuery,
    /// The mulligan plan, if any.
    pub plan: Option<MulliganPlan>,
    /// The output names, in order (without the companions).
    pub names: Vec<String>,
}

/// Python's `prepare`: atomize, schedule and compile `outputs` for `scenario`.
///
/// # Errors
/// As [`compile_query`] and [`build_plan`].
pub fn prepare(
    scenario: &Scenario,
    outputs: &[(String, Condition)],
    turn: u64,
    observe: &[(u64, Selector)],
) -> Result<Prepared> {
    let names: Vec<String> = outputs.iter().map(|(n, _)| n.clone()).collect();
    let Some(cfg) = &scenario.mulligan else {
        let req = CompileRequest {
            observe,
            ..CompileRequest::outputs(outputs, scenario.game.hand_size(), turn)
        };
        let cq = compile_query(&scenario.deck, &scenario.game, &req)?;
        return Ok(Prepared {
            cq,
            plan: None,
            names,
        });
    };
    let extra: Vec<Selector> = cfg
        .keep_rule
        .selectors()
        .into_iter()
        .cloned()
        .chain(cfg.priority.iter().map(|g| g.selector.clone()))
        .collect();
    // The whole drawn hand (including cards later bottomed) leaves the top of the
    // library, so compiling with the draw size enforces FR-42 (draws never reach them).
    let req = CompileRequest {
        outputs,
        observe,
        extra_selectors: &extra,
        reserved_bits: 1,
        hand_size: cfg.draw_size(),
        turn,
    };
    let mut cq = compile_query(&scenario.deck, &scenario.game, &req)?;
    let with_keep = cq
        .query
        .outputs
        .iter()
        .map(|p| p.conjoin_bit(KEEP_BIT))
        .collect::<Result<Vec<_>>>()?;
    cq.query.outputs.extend(with_keep);
    cq.query.validate()?;
    let success: Vec<&Condition> = outputs.iter().map(|(_, c)| c).collect();
    let plan = build_plan(cfg, &success, &cq.atoms)?;
    Ok(Prepared {
        cq,
        plan: Some(plan),
        names,
    })
}

fn options(limit: usize) -> Options {
    Options {
        limit,
        early_resolution: true,
        retirement: true,
    }
}

/// Exact per-depth results for every output.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DepthOutcome {
    /// The mulligan depth (0 is the first 7 cards).
    pub depth: u64,
    /// Cards kept at this depth.
    pub hand_size: u64,
    /// P(keep the hand at this depth).
    pub p_keep: Fraction,
    /// P(output) if this depth's hand is always kept.
    pub forced: Vec<Fraction>,
    /// P(output and this depth's hand is kept).
    pub with_keep: Vec<Fraction>,
}

/// Per-depth outcomes, reach probabilities and strategy-level output probabilities.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MulliganOutcome {
    /// Every depth.
    pub depths: Vec<DepthOutcome>,
    /// P(reach depth m).
    pub reach: Vec<Fraction>,
    /// P(output) under the mulligan strategy, per output.
    pub strategy: Vec<Fraction>,
}

fn plan_of(prep: &Prepared) -> Result<&MulliganPlan> {
    prep.plan.as_ref().ok_or_else(|| {
        validation(
            "scenario.mulligan",
            "scenario has no mulligan configuration",
        )
    })
}

/// Python's `run_mulligan`: every output of `prep` under the mulligan strategy.
///
/// # Errors
/// A validation error without a mulligan plan; engine errors.
pub fn run_mulligan(prep: &Prepared, limit: usize) -> Result<MulliganOutcome> {
    let plan = plan_of(prep)?;
    let n = prep.names.len();
    let depths: Vec<DepthOutcome> = api::mulligan_depths(&prep.cq.query, plan, &options(limit))?
        .into_iter()
        .enumerate()
        .map(|(m, d)| {
            let frac = |x: &BigUint| Fraction::new(x.clone(), d.denominator.clone());
            DepthOutcome {
                depth: m as u64,
                hand_size: u64::from(plan.draw - plan.bottoms[m]),
                p_keep: Fraction::new(d.keep_weight.clone(), d.hands_total.clone()),
                forced: d.outputs[..n].iter().map(frac).collect(),
                with_keep: d.outputs[n..].iter().map(frac).collect(),
            }
        })
        .collect();
    let mut reach = vec![Fraction::one()];
    for d in &depths[..depths.len().saturating_sub(1)] {
        let last = reach.last().cloned().unwrap_or_else(Fraction::one);
        reach.push(last.mul(&d.p_keep.complement()));
    }
    let strategy = (0..n)
        .map(|i| {
            depths
                .iter()
                .zip(&reach)
                .fold(Fraction::zero(), |acc, (d, r)| {
                    acc.add(&r.mul(&d.with_keep[i]))
                })
        })
        .collect();
    Ok(MulliganOutcome {
        depths,
        reach,
        strategy,
    })
}

/// Python's `exact_values`: P(output) for every output (strategy-level with mulligans).
///
/// # Errors
/// Engine errors.
pub fn exact_values(prep: &Prepared, limit: usize) -> Result<Vec<Fraction>> {
    if prep.plan.is_some() {
        return Ok(run_mulligan(prep, limit)?.strategy);
    }
    let out = api::run(&prep.cq.query, None, &options(limit))?;
    let denominator = out.denominator;
    Ok(out
        .outputs
        .into_iter()
        .map(|x| Fraction::new(x, denominator.clone()))
        .collect())
}

/// One row of a mulligan report (Python's `MulliganRow`).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MulliganRow {
    /// The mulligan depth.
    pub depth: u64,
    /// Cards kept at this depth.
    pub hand_size: u64,
    /// P(reach this depth).
    pub p_reach: Fraction,
    /// P(keep | reach).
    pub p_keep_given_reach: Fraction,
    /// P(success) if this depth's hand is always kept.
    pub p_success_forced: Fraction,
    /// P(success and keep | reach).
    pub p_success_and_keep_given_reach: Fraction,
}

/// Python's `MulliganReport` (FR-45, FR-46).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MulliganReport {
    /// Every depth.
    pub rows: Vec<MulliganRow>,
    /// P(success) under the strategy.
    pub p_success: Fraction,
    /// E[number of mulligans].
    pub expected_mulligans: Fraction,
    /// E[kept hand size].
    pub expected_hand_size: Fraction,
}

/// Per-depth and strategy-level mulligan statistics (Python's `mulligan_report`).
///
/// # Errors
/// A validation error without a mulligan configuration; as [`prepare`]; engine errors.
pub fn mulligan_report(
    scenario: &Scenario,
    success: &Condition,
    turn: u64,
    limit: usize,
) -> Result<MulliganReport> {
    let prep = prepare(
        scenario,
        &[("success".to_owned(), success.clone())],
        turn,
        &[],
    )?;
    let out = run_mulligan(&prep, limit)?;
    let rows: Vec<MulliganRow> = out
        .depths
        .iter()
        .zip(&out.reach)
        .map(|(d, r)| MulliganRow {
            depth: d.depth,
            hand_size: d.hand_size,
            p_reach: r.clone(),
            p_keep_given_reach: d.p_keep.clone(),
            p_success_forced: d.forced[0].clone(),
            p_success_and_keep_given_reach: d.with_keep[0].clone(),
        })
        .collect();
    let stop: Vec<Fraction> = out
        .depths
        .iter()
        .zip(&out.reach)
        .map(|(d, r)| r.mul(&d.p_keep))
        .collect();
    let expected_mulligans = stop
        .iter()
        .enumerate()
        .fold(Fraction::zero(), |acc, (m, p)| acc.add(&p.times(m as u64)));
    let expected_hand_size = out
        .depths
        .iter()
        .zip(&stop)
        .fold(Fraction::zero(), |acc, (d, p)| {
            acc.add(&p.times(d.hand_size))
        });
    Ok(MulliganReport {
        rows,
        p_success: out.strategy[0].clone(),
        expected_mulligans,
        expected_hand_size,
    })
}

/// One drawn-hand composition in the optimal-keep analysis (Python's `KeptHand`).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct KeptHand {
    /// Cards of each atom among the drawn cards.
    pub atom_counts: Vec<u16>,
    /// P(drawing this composition).
    pub probability: Fraction,
    /// P(success | keep it).
    pub success: Fraction,
    /// Whether the best plan keeps it.
    pub keep: bool,
}

/// One depth of the optimal-keep analysis (Python's `OptimalKeepRow`).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OptimalKeepRow {
    /// The mulligan depth.
    pub depth: u64,
    /// Cards kept at this depth.
    pub hand_size: u64,
    /// The value of mulliganing instead (0 at the last depth).
    pub continuation_value: Fraction,
    /// P(keep | reach) under the best plan.
    pub p_keep_given_reach: Fraction,
    /// Every drawn composition.
    pub hands: Vec<KeptHand>,
}

/// The optimal keep strategy (Python's `OptimalKeepReport`, FR-48).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OptimalKeepReport {
    /// P(success) under the best plan.
    pub value: Fraction,
    /// Every depth.
    pub rows: Vec<OptimalKeepRow>,
    /// The card names in each atom.
    pub atoms: Vec<Vec<String>>,
}

/// The keep strategy maximizing P(success) for the configured bottom policy (Python's
/// `optimal_keep`): `V_M = E[s_M(H)]`, `V_m = E[max(s_m(H), V_{m+1})]`, keep iff
/// `s_m(H) >= V_{m+1}`. The scenario's keep rule is ignored.
///
/// # Errors
/// As [`mulligan_report`].
pub fn optimal_keep(
    scenario: &Scenario,
    success: &Condition,
    turn: u64,
    limit: usize,
) -> Result<OptimalKeepReport> {
    let prep = prepare(
        scenario,
        &[("success".to_owned(), success.clone())],
        turn,
        &[],
    )?;
    let plan = plan_of(&prep)?;
    let deck = prep.cq.query.deck_size;
    let total: BigUint =
        Binom::<BigUint>::new(deck as usize, plan.draw as usize).get(deck, plan.draw)?;
    let per_depth = api::hand_values(&prep.cq.query, plan, 0, &options(limit))?;
    let mut continuation: Option<Fraction> = None;
    let mut rows = Vec::with_capacity(per_depth.len());
    for (m, depth) in per_depth.iter().enumerate().rev() {
        let hands: Vec<KeptHand> = depth
            .iter()
            .map(|v| {
                let success = Fraction::new(v.success.clone(), v.denominator.clone());
                KeptHand {
                    atom_counts: v.hand.clone(),
                    probability: Fraction::new(v.weight.clone(), total.clone()),
                    keep: continuation.as_ref().map_or(true, |c| success >= *c),
                    success,
                }
            })
            .collect();
        let value = hands.iter().try_fold(Fraction::zero(), |acc, h| {
            let worth = if h.keep {
                h.success.clone()
            } else {
                continuation.clone().ok_or_else(|| {
                    Error::Invalid("a hand was mulliganed at the last depth".into())
                })?
            };
            Ok::<_, Error>(acc.add(&h.probability.mul(&worth)))
        })?;
        let kept = hands
            .iter()
            .filter(|h| h.keep)
            .fold(Fraction::zero(), |acc, h| acc.add(&h.probability));
        rows.push(OptimalKeepRow {
            depth: m as u64,
            hand_size: u64::from(plan.draw - plan.bottoms[m]),
            continuation_value: continuation.clone().unwrap_or_else(Fraction::zero),
            p_keep_given_reach: kept,
            hands,
        });
        continuation = Some(value);
    }
    rows.reverse();
    Ok(OptimalKeepReport {
        value: continuation.unwrap_or_else(Fraction::zero),
        rows,
        atoms: prep.cq.atoms.names.clone(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::{Card, Deck, GameConfig, MulliganConfig, Op, PriorityGroup, Zone};

    fn scenario(max_mulligans: i64, keep: Condition) -> Scenario {
        let x = Selector::tag("x").unwrap();
        Scenario {
            deck: Deck::new(vec![
                Card::new("x", 4, &["x".to_owned()], Zone::Library).unwrap(),
                Card::new("other", 56, &[], Zone::Library).unwrap(),
            ])
            .unwrap(),
            game: GameConfig::default(),
            mulligan: Some(
                MulliganConfig::new(
                    vec![PriorityGroup::new(x, None).unwrap()],
                    keep,
                    max_mulligans,
                    0,
                    7,
                )
                .unwrap(),
            ),
        }
    }

    fn at_least_one() -> Condition {
        Condition::compare(Selector::tag("x").unwrap(), Op::Ge, 1).unwrap()
    }

    /// MATH §12 A3: A1 with one London mulligan, keep = success = "at least one copy":
    /// 1 - (1 - p)^2 with p = 38962/97527 (the 6-card hand still sees 7 cards first).
    #[test]
    fn reference_a3_one_mulligan() {
        let sc = scenario(1, at_least_one());
        let rep = mulligan_report(&sc, &at_least_one(), 0, 2_000_000).unwrap();
        let p = Fraction::new(38_962u64.into(), 97_527u64.into());
        let miss = p.complement();
        assert_eq!(rep.p_success, miss.mul(&miss).complement());
        assert_eq!(rep.rows[0].p_reach, Fraction::one());
        assert_eq!(rep.rows[1].p_reach, miss);
        assert!((rep.p_success.to_f64() - 0.639_399_300_5).abs() < 1e-9);
    }

    #[test]
    fn the_best_plan_is_never_worse_than_the_configured_one() {
        let sc = scenario(2, Condition::constant(true)); // "always keep": poor plan
        let rep = mulligan_report(&sc, &at_least_one(), 0, 2_000_000).unwrap();
        let best = optimal_keep(&sc, &at_least_one(), 0, 2_000_000).unwrap();
        assert!(best.value >= rep.p_success);
        assert_eq!(rep.p_success, rep.rows[0].p_success_forced); // never mulligans
        assert!(best.rows.last().unwrap().hands.iter().all(|h| h.keep));
        assert_eq!(
            best.rows.last().unwrap().continuation_value,
            Fraction::zero()
        );
    }

    #[test]
    fn questions_without_a_mulligan_are_refused() {
        let mut sc = scenario(1, at_least_one());
        sc.mulligan = None;
        assert!(matches!(
            mulligan_report(&sc, &at_least_one(), 0, 10),
            Err(Error::Validation { .. })
        ));
    }
}
