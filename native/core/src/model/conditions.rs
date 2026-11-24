//! Condition trees and queries (port of `mtgcalc.model.conditions`).
//!
//! Leaves (`Compare`, `Between`, `Assignable`) test how many seen cards a selector
//! matches; inner nodes combine them logically; `At` binds a subtree to a checkpoint
//! (turn), and the innermost `At` wins.

use std::collections::BTreeSet;

use super::selectors::Selector;
use crate::error::{validation, Result};

/// Comparison operators, as Python's `Op`.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Op {
    /// `==`
    Eq,
    /// `!=`
    Ne,
    /// `<`
    Lt,
    /// `<=`
    Le,
    /// `>`
    Gt,
    /// `>=`
    Ge,
}

impl Op {
    /// Parses Python's operator text.
    ///
    /// # Errors
    /// A validation error for anything else, as Python's `Compare`.
    pub fn parse(op: &str) -> Result<Self> {
        Ok(match op {
            "==" => Op::Eq,
            "!=" => Op::Ne,
            "<" => Op::Lt,
            "<=" => Op::Le,
            ">" => Op::Gt,
            ">=" => Op::Ge,
            _ => {
                return Err(validation(
                    "compare.op",
                    "must be one of ('==', '!=', '<', '<=', '>', '>=')",
                ))
            }
        })
    }
}

/// One demand of an exclusive assignment: `need` distinct cards matching `sel`.
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct Demand {
    pub(crate) sel: Selector,
    pub(crate) need: u64,
}

impl Demand {
    /// # Errors
    /// A validation error if `need < 1`.
    pub fn new(sel: Selector, need: i64) -> Result<Self> {
        let need = u64::try_from(need)
            .ok()
            .filter(|&n| n >= 1)
            .ok_or_else(|| validation("demand.need", "must be at least 1"))?;
        Ok(Demand { sel, need })
    }
}

/// A validated condition tree.
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct Condition(pub(crate) Cond);

/// The condition variants (crate-internal so every value passes through validation).
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub(crate) enum Cond {
    Compare { sel: Selector, op: Op, value: u64 },
    Between { sel: Selector, lo: u64, hi: u64 },
    And(Vec<Condition>),
    Or(Vec<Condition>),
    Xor(Box<Condition>, Box<Condition>),
    Not(Box<Condition>),
    Implies(Box<Condition>, Box<Condition>),
    AtLeast(u64, Vec<Condition>),
    Exactly(u64, Vec<Condition>),
    Assignable(Vec<Demand>),
    At(u64, Box<Condition>),
    Const(bool),
}

fn at_least(where_: &str, items: Vec<Condition>, minimum: usize) -> Result<Vec<Condition>> {
    if items.len() < minimum {
        return Err(validation(
            where_,
            format!("needs at least {minimum} operands"),
        ));
    }
    Ok(items)
}

fn non_negative(field: &str, n: i64) -> Result<u64> {
    u64::try_from(n).map_err(|_| validation(field, "must be non-negative"))
}

impl Condition {
    /// `count(sel) <op> value`.
    ///
    /// # Errors
    /// A validation error if `value < 0`.
    pub fn compare(sel: Selector, op: Op, value: i64) -> Result<Self> {
        let value = non_negative("compare.value", value)?;
        Ok(Condition(Cond::Compare { sel, op, value }))
    }

    /// `lo <= count(sel) <= hi`.
    ///
    /// # Errors
    /// A validation error unless `0 <= lo <= hi`.
    pub fn between(sel: Selector, lo: i64, hi: i64) -> Result<Self> {
        match (u64::try_from(lo), u64::try_from(hi)) {
            (Ok(lo), Ok(hi)) if lo <= hi => Ok(Condition(Cond::Between { sel, lo, hi })),
            _ => Err(validation("between", "requires 0 <= lo <= hi")),
        }
    }

    /// Conjunction of two or more conditions.
    ///
    /// # Errors
    /// A validation error for fewer than two items.
    pub fn and(items: Vec<Condition>) -> Result<Self> {
        Ok(Condition(Cond::And(at_least("and", items, 2)?)))
    }

    /// Disjunction of two or more conditions.
    ///
    /// # Errors
    /// A validation error for fewer than two items.
    pub fn or(items: Vec<Condition>) -> Result<Self> {
        Ok(Condition(Cond::Or(at_least("or", items, 2)?)))
    }

    /// Binary exclusive or.
    #[must_use]
    pub fn xor(a: Condition, b: Condition) -> Self {
        Condition(Cond::Xor(Box::new(a), Box::new(b)))
    }

    /// Negation.
    #[must_use]
    #[allow(clippy::should_implement_trait)] // a constructor, not an operator on values
    pub fn not(item: Condition) -> Self {
        Condition(Cond::Not(Box::new(item)))
    }

    /// Material implication `a -> b`.
    #[must_use]
    pub fn implies(a: Condition, b: Condition) -> Self {
        Condition(Cond::Implies(Box::new(a), Box::new(b)))
    }

    /// At least `n` of the items hold.
    ///
    /// # Errors
    /// A validation error for `n < 0` or no items.
    pub fn at_least(n: i64, items: Vec<Condition>) -> Result<Self> {
        let n = non_negative("atleast.n", n)?;
        Ok(Condition(Cond::AtLeast(n, at_least("atleast", items, 1)?)))
    }

    /// Exactly `n` of the items hold.
    ///
    /// # Errors
    /// A validation error for `n < 0` or no items.
    pub fn exactly(n: i64, items: Vec<Condition>) -> Result<Self> {
        let n = non_negative("exactly.n", n)?;
        Ok(Condition(Cond::Exactly(n, at_least("exactly", items, 1)?)))
    }

    /// All demands can be met at once by distinct seen cards (MATH §8).
    ///
    /// # Errors
    /// A validation error for no demands.
    pub fn assignable(demands: Vec<Demand>) -> Result<Self> {
        if demands.is_empty() {
            return Err(validation("assignable", "needs at least one demand"));
        }
        Ok(Condition(Cond::Assignable(demands)))
    }

    /// Evaluate `item` "by turn `turn`" (turn 0 is the opening hand).
    ///
    /// # Errors
    /// A validation error if `turn < 0`.
    pub fn at(turn: i64, item: Condition) -> Result<Self> {
        let turn = non_negative("at.turn", turn)?;
        Ok(Condition(Cond::At(turn, Box::new(item))))
    }

    /// A constant truth value.
    #[must_use]
    pub fn constant(value: bool) -> Self {
        Condition(Cond::Const(value))
    }

    /// Direct sub-conditions.
    pub(crate) fn children(&self) -> Vec<&Condition> {
        match &self.0 {
            Cond::And(items)
            | Cond::Or(items)
            | Cond::AtLeast(_, items)
            | Cond::Exactly(_, items) => items.iter().collect(),
            Cond::Xor(a, b) | Cond::Implies(a, b) => vec![a, b],
            Cond::Not(item) | Cond::At(_, item) => vec![item],
            Cond::Compare { .. } | Cond::Between { .. } | Cond::Assignable(_) | Cond::Const(_) => {
                Vec::new()
            }
        }
    }

    /// Every selector referenced by a leaf, with repetition, in pre-order.
    #[must_use]
    pub fn selectors(&self) -> Vec<&Selector> {
        let mut out = Vec::new();
        self.collect_selectors(&mut out);
        out
    }

    fn collect_selectors<'a>(&'a self, out: &mut Vec<&'a Selector>) {
        match &self.0 {
            Cond::Compare { sel, .. } | Cond::Between { sel, .. } => out.push(sel),
            Cond::Assignable(demands) => out.extend(demands.iter().map(|d| &d.sel)),
            _ => {}
        }
        for child in self.children() {
            child.collect_selectors(out);
        }
    }

    /// Checkpoint turns at which leaves are evaluated, given the default turn.
    #[must_use]
    pub fn turns(&self, default: u64) -> BTreeSet<u64> {
        let mut out = BTreeSet::new();
        self.collect_turns(default, &mut out);
        out
    }

    fn collect_turns(&self, turn: u64, out: &mut BTreeSet<u64>) {
        match &self.0 {
            Cond::At(t, item) => item.collect_turns(*t, out),
            Cond::Compare { .. } | Cond::Between { .. } | Cond::Assignable(_) => {
                out.insert(turn);
            }
            _ => {
                for child in self.children() {
                    child.collect_turns(turn, out);
                }
            }
        }
    }
}

/// A probability question: P(condition), or P(condition | given) (FR-35).
///
/// `turn` is the default checkpoint for leaves outside any `At`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Query {
    pub(crate) condition: Condition,
    pub(crate) given: Option<Condition>,
    pub(crate) turn: u64,
}

impl Query {
    /// # Errors
    /// A validation error if `turn < 0`.
    pub fn new(condition: Condition, given: Option<Condition>, turn: i64) -> Result<Self> {
        let turn = non_negative("query.turn", turn)?;
        Ok(Query {
            condition,
            given,
            turn,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::Error;

    fn tag(t: &str) -> Selector {
        Selector::tag(t).unwrap()
    }

    fn ge(t: &str, n: i64) -> Condition {
        Condition::compare(tag(t), Op::Ge, n).unwrap()
    }

    #[allow(clippy::needless_pass_by_value)] // reads naturally on `unwrap_err()`
    fn message(e: Error) -> String {
        e.to_string()
    }

    #[test]
    fn validation_matches_python() {
        assert_eq!(
            message(Condition::compare(tag("a"), Op::Ge, -1).unwrap_err()),
            "compare.value: must be non-negative"
        );
        assert_eq!(
            message(Condition::between(tag("a"), 3, 2).unwrap_err()),
            "between: requires 0 <= lo <= hi"
        );
        assert_eq!(
            message(Condition::between(tag("a"), -1, 2).unwrap_err()),
            "between: requires 0 <= lo <= hi"
        );
        assert_eq!(
            message(Condition::and(vec![ge("a", 1)]).unwrap_err()),
            "and: needs at least 2 operands"
        );
        assert_eq!(
            message(Condition::or(vec![]).unwrap_err()),
            "or: needs at least 2 operands"
        );
        assert_eq!(
            message(Condition::at_least(-1, vec![ge("a", 1)]).unwrap_err()),
            "atleast.n: must be non-negative"
        );
        assert_eq!(
            message(Condition::exactly(1, vec![]).unwrap_err()),
            "exactly: needs at least 1 operands"
        );
        assert_eq!(
            message(Condition::assignable(vec![]).unwrap_err()),
            "assignable: needs at least one demand"
        );
        assert_eq!(
            message(Demand::new(tag("a"), 0).unwrap_err()),
            "demand.need: must be at least 1"
        );
        assert_eq!(
            message(Condition::at(-1, ge("a", 1)).unwrap_err()),
            "at.turn: must be non-negative"
        );
        assert_eq!(
            message(Query::new(ge("a", 1), None, -2).unwrap_err()),
            "query.turn: must be non-negative"
        );
        assert!(matches!(Op::parse("=>"), Err(Error::Validation { .. })));
    }

    #[test]
    fn selectors_are_listed_in_preorder_with_repetition() {
        let c = Condition::and(vec![
            ge("a", 1),
            Condition::not(
                Condition::assignable(vec![
                    Demand::new(tag("b"), 1).unwrap(),
                    Demand::new(tag("a"), 2).unwrap(),
                ])
                .unwrap(),
            ),
        ])
        .unwrap();
        assert_eq!(c.selectors(), vec![&tag("a"), &tag("b"), &tag("a")]);
    }

    #[test]
    fn innermost_at_wins_for_turns() {
        let c = Condition::and(vec![
            ge("a", 1),
            Condition::at(
                3,
                Condition::or(vec![ge("b", 1), Condition::at(5, ge("c", 1)).unwrap()]).unwrap(),
            )
            .unwrap(),
            Condition::constant(true),
        ])
        .unwrap();
        assert_eq!(c.turns(2), BTreeSet::from([2, 3, 5]));
        assert!(Condition::constant(false).turns(4).is_empty());
    }
}
