//! Count distributions and turn tables (port of `mtgcalc.analysis.stats`, port stages
//! 3 and 4, FR-14, FR-24, FR-30).

use crate::analysis::{exact_values, prepare};
use crate::api;
use crate::engine::Options;
use crate::error::{validation, Error, Result};
use crate::model::{Condition, Op, Scenario, Selector};
use crate::probability::Fraction;

/// Most turns one question may ask about (each one is a checkpoint of the DP).
pub const MAX_TURNS: usize = 200;

/// The exact distribution of how many cards a selector matches, by one turn.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Distribution {
    /// The turn (0 is the opening hand).
    pub turn: u64,
    /// `pmf[k]` = P(exactly `k` matching cards seen).
    pub pmf: Vec<Fraction>,
}

/// One row of a turn table.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TurnRow {
    /// The turn (0 is the opening hand).
    pub turn: u64,
    /// The opening hand plus every card drawn by then.
    pub cards_seen: u64,
    /// P(condition) by that turn.
    pub probability: Fraction,
}

/// Sorted, de-duplicated turns (Python's `sorted(set(turns))`), checked.
fn turn_list(turns: &[i64]) -> Result<Vec<u64>> {
    if turns.len() > MAX_TURNS {
        return Err(validation("turns", format!("at most {MAX_TURNS} turns")));
    }
    let mut out = turns
        .iter()
        .map(|&t| u64::try_from(t).map_err(|_| validation("turns", "must be non-negative")))
        .collect::<Result<Vec<_>>>()?;
    out.sort_unstable();
    out.dedup();
    Ok(out)
}

fn options(limit: usize) -> Options {
    Options {
        limit,
        early_resolution: true,
        retirement: true,
    }
}

/// The opening hand plus every card drawn by `turn` (the first 7 under a mulligan).
fn cards_seen(scenario: &Scenario, turn: u64) -> Result<u64> {
    let hand = scenario
        .mulligan
        .as_ref()
        .map_or(scenario.game.hand_size(), |m| m.hand_size(0));
    Ok(hand + scenario.game.draws_through(turn)?)
}

/// The distribution of `count(selector)` at each turn, from one evaluation
/// (Python's `distributions`), in turn order. Under a mulligan strategy the distribution
/// mixes depths, so `count == k` is evaluated as outputs at strategy level instead.
///
/// # Errors
/// As [`crate::probability::probability`]; a validation error for a negative turn.
pub fn distributions(
    scenario: &Scenario,
    selector: &Selector,
    turns: &[i64],
    limit: usize,
) -> Result<Vec<Distribution>> {
    let turns = turn_list(turns)?;
    if scenario.mulligan.is_some() {
        let mut outputs = Vec::new();
        for &t in &turns {
            for k in 0..=cards_seen(scenario, t)? {
                let leaf = Condition::compare(
                    selector.clone(),
                    Op::Eq,
                    i64::try_from(k).unwrap_or(i64::MAX),
                )?;
                outputs.push((
                    format!("{t}:{k}"),
                    Condition::at(i64::try_from(t).unwrap_or(i64::MAX), leaf)?,
                ));
            }
        }
        let mut values = exact_values(&prepare(scenario, &outputs, 0, &[])?, limit)?.into_iter();
        return turns
            .iter()
            .map(|&t| {
                let mut pmf: Vec<Fraction> = (0..=cards_seen(scenario, t)?)
                    .filter_map(|_| values.next())
                    .collect();
                while pmf.len() > 1 && pmf.last().is_some_and(Fraction::is_zero) {
                    pmf.pop();
                }
                Ok(Distribution { turn: t, pmf })
            })
            .collect();
    }
    let observe: Vec<(u64, Selector)> = turns.iter().map(|&t| (t, selector.clone())).collect();
    let prep = prepare(scenario, &[], 0, &observe)?;
    let out = api::run(&prep.cq.query, None, &options(limit))?;
    turns
        .iter()
        .enumerate()
        .map(|(i, &turn)| {
            let snap = out
                .snapshots
                .iter()
                .find(|s| s.observer == i)
                .ok_or_else(|| Error::Invalid("an observer recorded nothing".into()))?;
            Ok(Distribution {
                turn,
                pmf: snap
                    .numerators
                    .iter()
                    .map(|n| Fraction::new(n.clone(), snap.denominator.clone()))
                    .collect(),
            })
        })
        .collect()
}

/// P(condition) by each turn, from one evaluation (Python's `turn_table`), at strategy
/// level under a mulligan configuration.
///
/// # Errors
/// As [`crate::probability::probability`]; a validation error for a negative turn.
pub fn turn_table(
    scenario: &Scenario,
    condition: &Condition,
    turns: &[i64],
    limit: usize,
) -> Result<Vec<TurnRow>> {
    let turns = turn_list(turns)?;
    let outputs = turns
        .iter()
        .map(|&t| {
            let at = i64::try_from(t).map_err(|_| validation("turns", "too large"))?;
            Ok((format!("t{t}"), Condition::at(at, condition.clone())?))
        })
        .collect::<Result<Vec<_>>>()?;
    if outputs.is_empty() {
        return Ok(Vec::new());
    }
    let values = exact_values(&prepare(scenario, &outputs, 0, &[])?, limit)?;
    turns
        .iter()
        .zip(values)
        .map(|(&turn, probability)| {
            Ok(TurnRow {
                turn,
                cards_seen: cards_seen(scenario, turn)?,
                probability,
            })
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use num_bigint::BigUint;
    use num_traits::One;

    use super::*;
    use crate::model::{Card, Deck, GameConfig, Op, Zone};
    use crate::probability::{probability, Answer, DEFAULT_LIMIT};

    fn lands(game: GameConfig) -> Scenario {
        Scenario {
            deck: Deck::new(vec![
                Card::new("land", 24, &["land".to_owned()], Zone::Library).unwrap(),
                Card::new("other", 36, &[], Zone::Library).unwrap(),
            ])
            .unwrap(),
            game,
            mulligan: None,
        }
    }

    fn c(n: u64, k: u64) -> BigUint {
        (0..k).fold(BigUint::one(), |acc, i| acc * (n - i) / (i + 1))
    }

    /// MATH §12 A2: the opening-hand PMF of 24 lands in 60 is hypergeometric.
    #[test]
    fn opening_hand_pmf_is_hypergeometric() {
        let land = Selector::tag("land").unwrap();
        let d = distributions(&lands(GameConfig::default()), &land, &[0], DEFAULT_LIMIT).unwrap();
        assert_eq!(d.len(), 1);
        let expected: Vec<Fraction> = (0..=7)
            .map(|k| Fraction::new(c(24, k) * c(36, 7 - k), c(60, 7)))
            .collect();
        assert_eq!(d[0].pmf, expected);
    }

    #[test]
    fn turns_are_sorted_and_deduplicated() {
        let land = Selector::tag("land").unwrap();
        let d = distributions(
            &lands(GameConfig::default()),
            &land,
            &[3, 0, 3],
            DEFAULT_LIMIT,
        )
        .unwrap();
        assert_eq!(d.iter().map(|x| x.turn).collect::<Vec<_>>(), vec![0, 3]);
        assert_eq!(d[1].pmf.len(), 10); // 7 cards + 2 draws on the play, 0..=9 lands
        assert!(matches!(
            distributions(&lands(GameConfig::default()), &land, &[-1], DEFAULT_LIMIT),
            Err(Error::Validation { .. })
        ));
    }

    #[test]
    fn turn_rows_equal_separate_probabilities() {
        let sc = lands(GameConfig::new(7, false, 1, &[], &[]).unwrap());
        let cond = Condition::compare(Selector::tag("land").unwrap(), Op::Ge, 3).unwrap();
        let rows = turn_table(&sc, &cond, &[0, 2, 4], DEFAULT_LIMIT).unwrap();
        for row in &rows {
            let q = crate::model::Query::new(cond.clone(), None, i64::try_from(row.turn).unwrap())
                .unwrap();
            let Answer::Probability(p) = probability(&sc, &q, DEFAULT_LIMIT).unwrap() else {
                panic!("expected a probability");
            };
            assert_eq!(row.probability, p, "turn {}", row.turn);
        }
        assert_eq!(
            rows.iter().map(|r| r.cards_seen).collect::<Vec<_>>(),
            vec![7, 9, 11]
        );
        assert_eq!(turn_table(&sc, &cond, &[], DEFAULT_LIMIT).unwrap().len(), 0);
    }
}
