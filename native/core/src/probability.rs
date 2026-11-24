//! Exact probabilities of queries (port of `mtgcalc.api.probability`, FR-90),
//! strategy-level under a mulligan configuration (FR-46).

use num_bigint::BigUint;
use num_integer::Integer;
use num_traits::{One, Zero};

use crate::analysis::{exact_values, prepare};
use crate::error::{Error, Result};
use crate::model::{Condition, Query, Scenario};

/// Python's default live-state limit (`mtgcalc.engine.base.DEFAULT_LIMIT`, NFR-06).
pub const DEFAULT_LIMIT: usize = 2_000_000;

/// An exact probability in lowest terms, like Python's `Fraction`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Fraction {
    numerator: BigUint,
    denominator: BigUint,
}

impl Fraction {
    /// `numerator / denominator` in lowest terms (`0/1` for zero).
    ///
    /// # Panics
    /// If `denominator` is zero (the engine's denominators never are).
    #[must_use]
    pub fn new(numerator: BigUint, denominator: BigUint) -> Self {
        assert!(!denominator.is_zero(), "zero denominator");
        if numerator.is_zero() {
            return Fraction {
                numerator,
                denominator: BigUint::one(),
            };
        }
        let g = numerator.gcd(&denominator);
        Fraction {
            numerator: numerator / &g,
            denominator: denominator / g,
        }
    }

    /// The numerator (lowest terms).
    #[must_use]
    pub fn numerator(&self) -> &BigUint {
        &self.numerator
    }

    /// The denominator (lowest terms, positive).
    #[must_use]
    pub fn denominator(&self) -> &BigUint {
        &self.denominator
    }

    /// Whether the value is zero.
    #[must_use]
    pub fn is_zero(&self) -> bool {
        self.numerator.is_zero()
    }

    /// `self / other`, or `None` when `other` is zero.
    #[must_use]
    pub fn checked_div(&self, other: &Fraction) -> Option<Fraction> {
        (!other.is_zero()).then(|| {
            Fraction::new(
                &self.numerator * &other.denominator,
                &self.denominator * &other.numerator,
            )
        })
    }
}

impl Fraction {
    /// Zero.
    #[must_use]
    pub fn zero() -> Self {
        Fraction::new(BigUint::zero(), BigUint::one())
    }

    /// The nearest `f64` (for display and tests; never used in calculations).
    #[must_use]
    pub fn to_f64(&self) -> f64 {
        use num_traits::ToPrimitive;
        // Scale so both parts fit an f64 without overflow, keeping 64 significant bits.
        let shift = self
            .denominator
            .bits()
            .saturating_sub(64)
            .max(self.numerator.bits().saturating_sub(64));
        let n = (&self.numerator >> shift).to_f64().unwrap_or(f64::NAN);
        let d = (&self.denominator >> shift).to_f64().unwrap_or(f64::NAN);
        n / d
    }

    /// One.
    #[must_use]
    pub fn one() -> Self {
        Fraction::new(BigUint::one(), BigUint::one())
    }

    /// `self + other`.
    #[must_use]
    pub fn add(&self, other: &Fraction) -> Fraction {
        Fraction::new(
            &self.numerator * &other.denominator + &other.numerator * &self.denominator,
            &self.denominator * &other.denominator,
        )
    }

    /// `self * other`.
    #[must_use]
    pub fn mul(&self, other: &Fraction) -> Fraction {
        Fraction::new(
            &self.numerator * &other.numerator,
            &self.denominator * &other.denominator,
        )
    }

    /// `1 - self` (for probabilities, which never exceed 1).
    #[must_use]
    pub fn complement(&self) -> Fraction {
        let num = if self.numerator > self.denominator {
            BigUint::zero()
        } else {
            &self.denominator - &self.numerator
        };
        Fraction::new(num, self.denominator.clone())
    }

    /// `self * k` for a whole number `k`.
    #[must_use]
    pub fn times(&self, k: u64) -> Fraction {
        Fraction::new(&self.numerator * k, self.denominator.clone())
    }
}

impl PartialOrd for Fraction {
    fn partial_cmp(&self, other: &Self) -> Option<std::cmp::Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for Fraction {
    fn cmp(&self, other: &Self) -> std::cmp::Ordering {
        (&self.numerator * &other.denominator).cmp(&(&other.numerator * &self.denominator))
    }
}

impl std::fmt::Display for Fraction {
    /// `n/d`, as Python's serialization writes every `Fraction` (also `0/1` and `1/1`).
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}/{}", self.numerator, self.denominator)
    }
}

/// The answer to a query: Python's `Probability` or `ConditionalResult` (exact only).
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Answer {
    /// P(condition).
    Probability(Fraction),
    /// P(condition | given), with P(condition and given) and P(given).
    Conditional {
        /// P(condition and given).
        joint: Fraction,
        /// P(given).
        given: Fraction,
        /// P(condition | given), or `None` when P(given) = 0.
        result: Option<Fraction>,
    },
}

/// P(condition), or P(condition | given) when the query has `given`.
///
/// # Errors
/// A validation error for invalid input (as Python), [`crate::Error::Limit`] when the
/// exact computation needs more than `limit` live states, [`crate::Error::Unsupported`]
/// beyond the engine's limits.
pub fn probability(scenario: &Scenario, query: &Query, limit: usize) -> Result<Answer> {
    let outputs: Vec<(String, Condition)> = match &query.given {
        None => vec![("p".into(), query.condition.clone())],
        Some(given) => vec![
            (
                "joint".into(),
                Condition::and(vec![query.condition.clone(), given.clone()])?,
            ),
            ("given".into(), given.clone()),
        ],
    };
    // Strategy-level under a mulligan configuration (FR-46).
    let prep = prepare(scenario, &outputs, query.turn, &[])?;
    let mut values = exact_values(&prep, limit)?.into_iter();
    Ok(match (values.next(), values.next()) {
        (Some(p), None) => Answer::Probability(p),
        (Some(joint), Some(given)) => Answer::Conditional {
            result: joint.checked_div(&given),
            joint,
            given,
        },
        _ => return Err(Error::Invalid("the engine returned no outputs".into())),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::{Card, Deck, GameConfig, Op, Selector, Zone};

    fn frac(n: u64, d: u64) -> Fraction {
        Fraction::new(n.into(), d.into())
    }

    fn scenario(types: &[(&str, i64)], size: i64, game: GameConfig) -> Scenario {
        let mut cards: Vec<Card> = types
            .iter()
            .map(|(t, n)| Card::new(t, *n, &[(*t).to_owned()], Zone::Library).unwrap())
            .collect();
        let used: i64 = types.iter().map(|(_, n)| n).sum();
        if size > used {
            cards.push(Card::new("(other)", size - used, &[], Zone::Library).unwrap());
        }
        Scenario {
            deck: Deck::new(cards).unwrap(),
            game,
            mulligan: None,
        }
    }

    fn cmp(t: &str, op: Op, n: i64) -> Condition {
        Condition::compare(Selector::tag(t).unwrap(), op, n).unwrap()
    }

    fn p(sc: &Scenario, cond: Condition, turn: i64) -> Fraction {
        match probability(sc, &Query::new(cond, None, turn).unwrap(), DEFAULT_LIMIT).unwrap() {
            Answer::Probability(f) => f,
            other @ Answer::Conditional { .. } => panic!("{other:?}"),
        }
    }

    #[test]
    fn fractions_are_reduced_like_python() {
        assert_eq!(frac(6, 8).to_string(), "3/4");
        assert_eq!(frac(0, 8).to_string(), "0/1");
        assert_eq!(frac(5, 5).to_string(), "1/1");
        assert_eq!(frac(1, 2).checked_div(&frac(3, 4)), Some(frac(2, 3)));
        assert_eq!(frac(1, 2).checked_div(&frac(0, 1)), None);
    }

    /// MATH §12 A1: P(at least one of 4 copies in a 7-card hand from 60) = 1 - C(56,7)/C(60,7)
    /// = 38962/97527 (≈ 0.3994996257).
    #[test]
    fn reference_a1_one_of_four_in_the_opening_hand() {
        let sc = scenario(&[("x", 4)], 60, GameConfig::default());
        assert_eq!(p(&sc, cmp("x", Op::Ge, 1), 0), frac(38_962, 97_527));
    }

    /// Hypergeometric by hand: 3 or more of 24 lands in 9 cards (turn 3, on the draw).
    #[test]
    fn multi_turn_matches_the_hypergeometric_tail() {
        let draw = GameConfig::new(7, false, 1, &[], &[]).unwrap();
        let sc = scenario(&[("land", 24)], 60, draw);
        let c = |n: u64, k: u64| -> BigUint {
            (0..k).fold(BigUint::one(), |acc, i| acc * (n - i) / (i + 1))
        };
        let below: BigUint = (0..3).map(|k| c(24, k) * c(36, 10 - k)).sum();
        let total = c(60, 10);
        let expected = Fraction::new(&total - below, total);
        assert_eq!(p(&sc, cmp("land", Op::Ge, 3), 3), expected);
    }

    #[test]
    fn conditional_probability_and_impossible_givens() {
        let sc = scenario(&[("land", 24)], 60, GameConfig::default());
        let q = Query::new(cmp("land", Op::Ge, 2), Some(cmp("land", Op::Ge, 1)), 0).unwrap();
        let Answer::Conditional {
            joint,
            given,
            result,
        } = probability(&sc, &q, DEFAULT_LIMIT).unwrap()
        else {
            panic!("expected a conditional answer");
        };
        assert_eq!(result, joint.checked_div(&given));
        let never = Query::new(cmp("land", Op::Ge, 1), Some(cmp("land", Op::Gt, 7)), 0).unwrap();
        let Answer::Conditional { given, result, .. } =
            probability(&sc, &never, DEFAULT_LIMIT).unwrap()
        else {
            panic!("expected a conditional answer");
        };
        assert!(given.is_zero() && result.is_none());
    }

    #[test]
    fn complementary_conditions_sum_to_one() {
        let sc = scenario(&[("a", 10), ("b", 7)], 40, GameConfig::default());
        let c = Condition::or(vec![cmp("a", Op::Ge, 2), cmp("b", Op::Eq, 1)]).unwrap();
        let yes = p(&sc, Condition::at(4, c.clone()).unwrap(), 0);
        let no = p(&sc, Condition::at(4, Condition::not(c)).unwrap(), 0);
        let sum = Fraction::new(
            yes.numerator() * no.denominator() + no.numerator() * yes.denominator(),
            yes.denominator() * no.denominator(),
        );
        assert_eq!(sum, frac(1, 1));
    }

    #[test]
    fn the_state_limit_is_enforced() {
        let sc = scenario(
            &[("a", 10), ("b", 10), ("c", 10)],
            60,
            GameConfig::default(),
        );
        let c = Condition::and(vec![
            cmp("a", Op::Ge, 1),
            cmp("b", Op::Ge, 1),
            cmp("c", Op::Ge, 1),
        ])
        .unwrap();
        let q = Query::new(c, None, 0).unwrap();
        assert!(matches!(probability(&sc, &q, 3), Err(Error::Limit(_))));
    }
}
