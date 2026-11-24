//! The London-mulligan bottom policy and plan (port of `mtgcalc.compile.policy`,
//! ADR-0005). The bottoming itself runs in the engine ([`crate::policy::Policy`]).

use std::collections::HashMap;

use super::atomizer::AtomTable;
use super::compiler::compile_predicate;
use crate::error::Result;
use crate::model::conditions::Cond;
use crate::model::mulligan::MulliganConfig;
use crate::model::{Condition, Op, Selector};
use crate::policy::{MulliganPlan, Policy};

/// The largest lower bound each selector must reach for the conditions to hold (only
/// bounds that are required: positive leaves under AND/OR/at-least/implication
/// consequents, and negated upper bounds), as Python's `lower_bounds`.
#[must_use]
pub fn lower_bounds(conditions: &[&Condition]) -> HashMap<Selector, u64> {
    fn note(bounds: &mut HashMap<Selector, u64>, sel: &Selector, v: u64) {
        let b = bounds.entry(sel.clone()).or_insert(0);
        *b = (*b).max(v);
    }
    fn rec(c: &Condition, positive: bool, bounds: &mut HashMap<Selector, u64>) {
        match &c.0 {
            Cond::Compare { sel, op, value } => match (positive, op) {
                (true, Op::Ge | Op::Eq) | (false, Op::Lt) => note(bounds, sel, *value),
                (true, Op::Gt) | (false, Op::Le) => note(bounds, sel, value.saturating_add(1)),
                _ => {}
            },
            Cond::Between { sel, lo, .. } if positive => note(bounds, sel, *lo),
            Cond::Assignable(demands) if positive => {
                for d in demands {
                    note(bounds, &d.sel, d.need);
                }
            }
            Cond::And(items) | Cond::Or(items) | Cond::AtLeast(_, items) => {
                for it in items {
                    rec(it, positive, bounds);
                }
            }
            Cond::Not(item) => rec(item, !positive, bounds),
            Cond::At(_, item) => rec(item, positive, bounds),
            Cond::Implies(_, b) => rec(b, positive, bounds),
            _ => {} // XOR, exactly and constants impose no one-sided bound
        }
    }
    let mut bounds = HashMap::new();
    for c in conditions {
        rec(c, true, &mut bounds);
    }
    bounds
}

fn small(n: u64) -> u32 {
    // Quotas above the deck size behave like the deck size; the engine counts in u16.
    u32::try_from(n.min(u64::from(u16::MAX) + 1)).unwrap_or(u32::MAX)
}

/// Compiles a mulligan configuration against an atom table (Python's `build_plan`):
/// priority groups become `(atom mask, quota)` rules, explicit or derived from the keep
/// rule and success conditions.
///
/// # Errors
/// A validation error if a selector was not atomized.
pub fn build_plan(
    cfg: &MulliganConfig,
    success: &[&Condition],
    atoms: &AtomTable,
) -> Result<MulliganPlan> {
    let keep_bounds = lower_bounds(&[&cfg.keep_rule]);
    let success_bounds = lower_bounds(success);
    let rules = cfg
        .priority
        .iter()
        .map(|g| {
            let quota = match g.quota {
                Some(q) => q,
                None if keep_bounds.contains_key(&g.selector)
                    || success_bounds.contains_key(&g.selector) =>
                {
                    let k = keep_bounds.get(&g.selector).copied().unwrap_or(0);
                    let s = success_bounds.get(&g.selector).copied().unwrap_or(0);
                    k.max(s)
                }
                None => cfg.draw_size,
            };
            Ok((atoms.mask(&g.selector)?, small(quota)))
        })
        .collect::<Result<Vec<_>>>()?;
    let (keep_leaves, keep) = compile_predicate(&cfg.keep_rule, atoms)?;
    Ok(MulliganPlan {
        policy: Policy::new(rules, atoms.size())?,
        keep_leaves,
        keep,
        bottoms: (0..=cfg.max_mulligans)
            .map(|m| small(cfg.bottom_count(m)))
            .collect(),
        draw: small(cfg.draw_size),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::Demand;

    fn tag(t: &str) -> Selector {
        Selector::tag(t).unwrap()
    }

    fn cmp(t: &str, op: Op, v: i64) -> Condition {
        Condition::compare(tag(t), op, v).unwrap()
    }

    #[test]
    fn lower_bounds_follow_python() {
        let c = Condition::and(vec![
            cmp("land", Op::Ge, 3),
            cmp("land", Op::Gt, 3),                 // -> 4
            Condition::not(cmp("ramp", Op::Lt, 2)), // -> 2
            Condition::not(cmp("draw", Op::Le, 1)), // -> 2
            Condition::between(tag("x"), 2, 5).unwrap(),
            Condition::assignable(vec![Demand::new(tag("y"), 3).unwrap()]).unwrap(),
            Condition::implies(cmp("z", Op::Ge, 9), cmp("w", Op::Eq, 1)),
            Condition::xor(cmp("q", Op::Ge, 5), cmp("q", Op::Ge, 1)),
            Condition::at(3, cmp("r", Op::Le, 2)).unwrap(), // upper bound: none
        ])
        .unwrap();
        let b = lower_bounds(&[&c]);
        let get = |t: &str| b.get(&tag(t)).copied();
        assert_eq!(
            (get("land"), get("ramp"), get("draw"), get("x"), get("y")),
            (Some(4), Some(2), Some(2), Some(2), Some(3))
        );
        assert_eq!(
            (get("z"), get("w"), get("q"), get("r")),
            (None, Some(1), None, None)
        );
    }
}
