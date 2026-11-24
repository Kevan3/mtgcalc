//! Mulligan configuration (port of `mtgcalc.model.mulligan`, FR-40 – FR-43, ADR-0005).

use super::conditions::Cond;
use super::{Condition, Selector};
use crate::error::{validation, Result};

/// A user-given bottoming priority group: up to `quota` cards of it are protected from
/// the bottom (`None` derives the quota from the conditions, LLD §4.5).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PriorityGroup {
    pub(crate) selector: Selector,
    pub(crate) quota: Option<u64>,
}

impl PriorityGroup {
    /// # Errors
    /// A validation error for a negative quota.
    pub fn new(selector: Selector, quota: Option<i64>) -> Result<Self> {
        let quota = quota
            .map(|q| {
                u64::try_from(q).map_err(|_| validation("priority.quota", "must be non-negative"))
            })
            .transpose()?;
        Ok(PriorityGroup { selector, quota })
    }
}

/// London mulligan with `free_mulligans` free mulligans (MATH §9.1).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MulliganConfig {
    pub(crate) priority: Vec<PriorityGroup>,
    pub(crate) keep_rule: Condition,
    pub(crate) max_mulligans: u64,
    pub(crate) free_mulligans: u64,
    pub(crate) draw_size: u64,
}

fn uses_a_later_turn(c: &Condition) -> bool {
    match &c.0 {
        Cond::At(t, _) if *t != 0 => true,
        _ => c.children().into_iter().any(uses_a_later_turn),
    }
}

impl MulliganConfig {
    /// Validates exactly as Python's `MulliganConfig.__post_init__` (same order, fields
    /// and messages).
    ///
    /// # Errors
    /// A validation error for no or repeated priority groups, a negative depth, more than
    /// one free mulligan, a non-positive draw, bottoming more than is drawn, or a keep
    /// rule that looks past the opening hand.
    pub fn new(
        priority: Vec<PriorityGroup>,
        keep_rule: Condition,
        max_mulligans: i64,
        free_mulligans: i64,
        draw_size: i64,
    ) -> Result<Self> {
        if priority.is_empty() {
            return Err(validation(
                "mulligan.priority",
                "at least one priority group is required",
            ));
        }
        for (i, g) in priority.iter().enumerate() {
            if priority[..i].iter().any(|h| h.selector == g.selector) {
                return Err(validation(
                    "mulligan.priority",
                    "priority group selectors must be distinct",
                ));
            }
        }
        let max_mulligans = u64::try_from(max_mulligans)
            .map_err(|_| validation("mulligan.max_mulligans", "must be non-negative"))?;
        let free_mulligans = match free_mulligans {
            0 => 0,
            1 => 1,
            _ => return Err(validation("mulligan.free_mulligans", "must be 0 or 1")),
        };
        let draw_size = u64::try_from(draw_size)
            .ok()
            .filter(|&d| d >= 1)
            .ok_or_else(|| validation("mulligan.draw_size", "must be positive"))?;
        let cfg = MulliganConfig {
            priority,
            keep_rule,
            max_mulligans,
            free_mulligans,
            draw_size,
        };
        if cfg.bottom_count(cfg.max_mulligans) > cfg.draw_size {
            return Err(validation(
                "mulligan.max_mulligans",
                "would require bottoming more cards than drawn",
            ));
        }
        if uses_a_later_turn(&cfg.keep_rule) {
            return Err(validation(
                "mulligan.keep_rule",
                "keep rule may only use turn 0",
            ));
        }
        Ok(cfg)
    }

    /// Cards put on the bottom after the `m`-th mulligan.
    #[must_use]
    pub fn bottom_count(&self, m: u64) -> u64 {
        m.saturating_sub(self.free_mulligans)
    }

    /// Kept hand size at mulligan depth `m`.
    #[must_use]
    pub fn hand_size(&self, m: u64) -> u64 {
        self.draw_size.saturating_sub(self.bottom_count(m))
    }

    /// Cards drawn for each hand.
    #[must_use]
    pub fn draw_size(&self) -> u64 {
        self.draw_size
    }

    /// M: the hand at depth M is always kept.
    #[must_use]
    pub fn max_mulligans(&self) -> u64 {
        self.max_mulligans
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::Op;

    fn land() -> Selector {
        Selector::tag("land").unwrap()
    }

    fn group(quota: Option<i64>) -> PriorityGroup {
        PriorityGroup::new(land(), quota).unwrap()
    }

    fn message(r: Result<MulliganConfig>) -> String {
        r.unwrap_err().to_string()
    }

    #[test]
    fn counts_follow_the_london_mulligan() {
        let cfg =
            MulliganConfig::new(vec![group(Some(3))], Condition::constant(true), 3, 1, 7).unwrap();
        assert_eq!(
            (0..=3).map(|m| cfg.hand_size(m)).collect::<Vec<_>>(),
            vec![7, 7, 6, 5]
        );
    }

    #[test]
    fn validation_matches_python() {
        let t = Condition::constant(true);
        assert_eq!(
            message(MulliganConfig::new(vec![], t.clone(), 2, 0, 7)),
            "mulligan.priority: at least one priority group is required"
        );
        assert_eq!(
            message(MulliganConfig::new(
                vec![group(None), group(Some(1))],
                t.clone(),
                2,
                0,
                7
            )),
            "mulligan.priority: priority group selectors must be distinct"
        );
        assert_eq!(
            message(MulliganConfig::new(vec![group(None)], t.clone(), -1, 0, 7)),
            "mulligan.max_mulligans: must be non-negative"
        );
        assert_eq!(
            message(MulliganConfig::new(vec![group(None)], t.clone(), 2, 2, 7)),
            "mulligan.free_mulligans: must be 0 or 1"
        );
        assert_eq!(
            message(MulliganConfig::new(vec![group(None)], t.clone(), 2, 0, 0)),
            "mulligan.draw_size: must be positive"
        );
        assert_eq!(
            message(MulliganConfig::new(vec![group(None)], t, 8, 0, 7)),
            "mulligan.max_mulligans: would require bottoming more cards than drawn"
        );
        let later = Condition::at(2, Condition::compare(land(), Op::Ge, 1).unwrap()).unwrap();
        assert_eq!(
            message(MulliganConfig::new(vec![group(None)], later, 2, 0, 7)),
            "mulligan.keep_rule: keep rule may only use turn 0"
        );
        assert_eq!(
            PriorityGroup::new(land(), Some(-1))
                .unwrap_err()
                .to_string(),
            "priority.quota: must be non-negative"
        );
    }
}
