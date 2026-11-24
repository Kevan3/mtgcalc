//! Draw schedule to batch plan (port of `mtgcalc.compile.schedule`, MATH §2).

use std::collections::BTreeSet;

use crate::error::{invalid, Result};
use crate::model::GameConfig;

/// Checkpoints (sorted turns, always including 0) and the draws between them.
///
/// `batches[j]` is the number of cards drawn between `checkpoints[j-1]` and
/// `checkpoints[j]`; `batches[0] == 0`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BatchPlan {
    /// Checkpoint turns, ascending, starting with 0.
    pub checkpoints: Vec<u64>,
    /// Cards drawn before each checkpoint.
    pub batches: Vec<u64>,
    /// Cards in hand before the first draw.
    pub hand_size: u64,
}

impl BatchPlan {
    /// Cards drawn after the opening hand through the last checkpoint.
    #[must_use]
    pub fn total_draws(&self) -> u64 {
        self.batches.iter().sum()
    }

    /// Checkpoint index of `turn`.
    ///
    /// # Errors
    /// [`crate::Error::Invalid`] if `turn` is not a checkpoint (a compiler bug).
    pub fn index(&self, turn: u64) -> Result<usize> {
        self.checkpoints
            .binary_search(&turn)
            .map_err(|_| invalid(format!("turn {turn} is not a checkpoint")))
    }
}

/// Builds the batch plan for the given checkpoint turns.
///
/// # Errors
/// [`crate::Error::Unsupported`] if a draw count does not fit in 64 bits.
pub fn plan(game: &GameConfig, turns: &BTreeSet<u64>, hand_size: u64) -> Result<BatchPlan> {
    let mut checkpoints: Vec<u64> = turns.iter().copied().collect();
    if checkpoints.first() != Some(&0) {
        checkpoints.insert(0, 0);
    }
    let through: Vec<u64> = checkpoints
        .iter()
        .map(|&t| game.draws_through(t))
        .collect::<Result<_>>()?;
    let batches = std::iter::once(0)
        .chain(through.windows(2).map(|w| w[1] - w[0])) // draws never go backwards
        .collect();
    Ok(BatchPlan {
        checkpoints,
        batches,
        hand_size,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn batches_are_the_draws_between_checkpoints() {
        let game = GameConfig::new(7, true, 1, &[], &[(3, 2)]).unwrap();
        let p = plan(&game, &BTreeSet::from([4, 1]), 7).unwrap();
        assert_eq!(p.checkpoints, vec![0, 1, 4]);
        assert_eq!(p.batches, vec![0, 0, 5]); // on the play: turn 1 skips; 2,3(+2),4
        assert_eq!(p.total_draws(), 5);
        assert_eq!(p.index(4).unwrap(), 2);
        assert!(p.index(2).is_err());
    }

    #[test]
    fn turn_zero_is_always_a_checkpoint() {
        let p = plan(&GameConfig::default(), &BTreeSet::new(), 7).unwrap();
        assert_eq!((p.checkpoints, p.batches), (vec![0], vec![0]));
    }
}
