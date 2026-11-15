//! London-mulligan bottoming and keep rule (LLD §4.5, ADR-0005, MATH §9.4).
//!
//! A port of `mtgcalc.compile.policy.bottom`; both must make identical choices.

use crate::error::{invalid, Result};
use crate::logic::{leaf_bits, Leaf, Program};

/// Bottoming priority rules `(atom mask, quota)`, highest priority first, with the
/// per-atom orderings precomputed.
#[derive(Clone, Debug)]
pub struct Policy {
    rules: Vec<(Vec<usize>, u32)>,
    /// For each rule, its mask sorted with multi-role atoms first.
    protect_order: Vec<Vec<usize>>,
    /// All atoms, in the order unprotected cards are bottomed (lowest priority first).
    bottom_order: Vec<usize>,
}

impl Policy {
    /// Builds a policy over `atoms` tracked atoms.
    ///
    /// # Errors
    /// [`crate::Error::Invalid`] if a mask names an atom `>= atoms`.
    pub fn new(rules: Vec<(Vec<usize>, u32)>, atoms: usize) -> Result<Self> {
        if rules.iter().flat_map(|(mask, _)| mask).any(|&i| i >= atoms) {
            return Err(invalid(
                "a priority group names an atom that does not exist",
            ));
        }
        let mut rule_count = vec![0usize; atoms];
        let mut best_rule = vec![rules.len(); atoms]; // rules.len() = "in no group"
        for (r, (mask, _)) in rules.iter().enumerate() {
            for &i in mask {
                rule_count[i] += 1;
                best_rule[i] = best_rule[i].min(r);
            }
        }
        let protect_order = rules
            .iter()
            .map(|(mask, _)| {
                let mut order = mask.clone();
                order.sort_by_key(|&a| (std::cmp::Reverse(rule_count[a]), a));
                order
            })
            .collect();
        let mut bottom_order: Vec<usize> = (0..atoms).collect();
        bottom_order.sort_by_key(|&a| (std::cmp::Reverse(best_rule[a]), a));
        Ok(Policy {
            rules,
            protect_order,
            bottom_order,
        })
    }

    /// Atom counts to put on the bottom when `n` cards must go from `hand` (tracked atoms)
    /// plus `pool_in_hand` untracked cards. The pool part is implicit.
    ///
    /// Order: (1) untracked cards, (2) unprotected cards, lowest priority first,
    /// (3) protected cards, releasing the lowest-priority protections first.
    ///
    /// # Errors
    /// [`crate::Error::Invalid`] if `n` exceeds the cards in hand.
    pub fn bottom(&self, hand: &[u16], pool_in_hand: u32, n: u32) -> Result<Vec<u16>> {
        let in_hand: u32 = hand.iter().map(|&h| u32::from(h)).sum::<u32>() + pool_in_hand;
        if n > in_hand {
            return Err(invalid("cannot bottom more cards than are in hand"));
        }
        let mut protected = vec![0u32; hand.len()];
        let mut log: Vec<(usize, u32)> = Vec::new();
        for ((mask, quota), order) in self.rules.iter().zip(&self.protect_order) {
            let already: u32 = mask.iter().map(|&i| protected[i]).sum();
            let mut need = quota.saturating_sub(already);
            for &i in order {
                if need == 0 {
                    break;
                }
                let take = need.min(u32::from(hand[i]) - protected[i]);
                if take > 0 {
                    protected[i] += take;
                    need -= take;
                    log.push((i, take));
                }
            }
        }
        let mut bottomed = vec![0u32; hand.len()];
        let mut left = n - n.min(pool_in_hand);
        for &i in &self.bottom_order {
            let take = left.min(u32::from(hand[i]) - protected[i]);
            bottomed[i] += take;
            left -= take;
        }
        for &(i, qty) in log.iter().rev() {
            if left == 0 {
                break;
            }
            let take = left.min(qty);
            bottomed[i] += take;
            left -= take;
        }
        debug_assert_eq!(left, 0, "bottoming must place every card");
        Ok(bottomed.into_iter().map(|b| b as u16).collect())
    }
}

/// A compiled London-mulligan procedure (see `mtgcalc.compile.policy.MulliganPlan`).
#[derive(Clone, Debug)]
pub struct MulliganPlan {
    /// Bottoming policy.
    pub policy: Policy,
    /// Leaves of the keep rule (their own bit namespace, evaluated on the kept hand).
    pub keep_leaves: Vec<Leaf>,
    /// The keep rule.
    pub keep: Program,
    /// Cards bottomed at each depth `0..=M`.
    pub bottoms: Vec<u32>,
    /// Cards drawn for every hand (7).
    pub draw: u32,
}

impl MulliganPlan {
    /// Validates the plan against the number of tracked atoms.
    ///
    /// # Errors
    /// [`crate::Error::Invalid`] for an empty depth list, bottoming more than is drawn,
    /// or a keep leaf reading a missing atom.
    pub fn validate(&self, atoms: usize) -> Result<()> {
        if self.bottoms.is_empty() {
            return Err(invalid("a mulligan plan needs at least one depth"));
        }
        if self.bottoms.iter().any(|&b| b > self.draw) {
            return Err(invalid("cannot bottom more cards than are drawn"));
        }
        if self
            .keep_leaves
            .iter()
            .any(|l| l.atoms().any(|i| i >= atoms))
        {
            return Err(invalid("the keep rule reads an atom that does not exist"));
        }
        Ok(())
    }

    /// The last depth M (that hand is always kept).
    #[must_use]
    pub fn max_depth(&self) -> usize {
        self.bottoms.len() - 1
    }

    /// Whether the keep rule accepts a kept-hand composition.
    #[must_use]
    pub fn keeps(&self, kept: &[u16]) -> bool {
        self.keep.eval(leaf_bits(&self.keep_leaves, kept))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Same cases as `tests/unit/test_compile.py::test_bottom_order_...` (Python reference).
    #[test]
    fn bottom_order_pool_then_unprotected_then_release() {
        // atoms: 0 = land, 1 = ramp; rules: land quota 2 (high), ramp quota 1 (low)
        let p = Policy::new(vec![(vec![0], 2), (vec![1], 1)], 2).unwrap();
        let hand = [4, 2]; // + 1 pool card = 7
        assert_eq!(p.bottom(&hand, 1, 1).unwrap(), [0, 0]);
        assert_eq!(p.bottom(&hand, 1, 2).unwrap(), [0, 1]);
        assert_eq!(p.bottom(&hand, 1, 4).unwrap(), [2, 1]);
        assert_eq!(p.bottom(&hand, 1, 5).unwrap(), [2, 2]);
        assert_eq!(p.bottom(&hand, 1, 7).unwrap(), [4, 2]);
        assert!(p.bottom(&hand, 1, 8).is_err());
    }

    #[test]
    fn unmatched_atoms_go_first_and_multi_role_is_protected() {
        let p = Policy::new(vec![(vec![0], 1)], 2).unwrap();
        assert_eq!(p.bottom(&[2, 3], 0, 3).unwrap(), [0, 3]);
        // atom 0 = land only, atom 1 = land+ramp; rules: land 1, ramp 1
        let p = Policy::new(vec![(vec![0, 1], 1), (vec![1], 1)], 2).unwrap();
        assert_eq!(p.bottom(&[1, 1], 0, 1).unwrap(), [1, 0]);
    }

    #[test]
    fn bad_masks_are_rejected() {
        assert!(Policy::new(vec![(vec![3], 1)], 2).is_err());
    }
}
