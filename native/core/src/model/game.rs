//! Game configuration and draw schedule (port of `mtgcalc.model.game`, ADR-0004).
//!
//! Turn 0 is the kept opening hand; turn T >= 1 means *after the draw step of turn T*.

use std::collections::BTreeMap;

use crate::error::{unsupported, validation, Result};

/// How many cards are seen when.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct GameConfig {
    hand_size: u64,
    on_play: bool,
    draws_per_turn: u64,
    draw_overrides: BTreeMap<u64, u64>,
    extra_draws: BTreeMap<u64, u64>,
}

fn turn_map(name: &str, pairs: &[(i64, i64)]) -> Result<BTreeMap<u64, u64>> {
    let mut out = BTreeMap::new();
    for &(turn, n) in pairs {
        let t = u64::try_from(turn)
            .ok()
            .filter(|&t| t >= 1)
            .ok_or_else(|| validation(format!("game.{name}"), "turn keys must be >= 1"))?;
        let n = u64::try_from(n)
            .map_err(|_| validation(format!("game.{name}[{turn}]"), "must be non-negative"))?;
        if out.insert(t, n).is_some() {
            return Err(validation(format!("game.{name}[{turn}]"), "duplicate turn"));
        }
    }
    Ok(out)
}

impl GameConfig {
    /// Validates a game configuration, exactly as Python's `GameConfig.__post_init__`.
    ///
    /// `draw_overrides` and `extra_draws` are `(turn, cards)` pairs.
    ///
    /// # Errors
    /// A validation error for a negative size or count, a turn below 1, or a repeated
    /// turn.
    pub fn new(
        hand_size: i64,
        on_play: bool,
        draws_per_turn: i64,
        draw_overrides: &[(i64, i64)],
        extra_draws: &[(i64, i64)],
    ) -> Result<Self> {
        let hand_size = u64::try_from(hand_size)
            .map_err(|_| validation("game.hand_size", "must be non-negative"))?;
        let draws_per_turn = u64::try_from(draws_per_turn)
            .map_err(|_| validation("game.draws_per_turn", "must be non-negative"))?;
        Ok(GameConfig {
            hand_size,
            on_play,
            draws_per_turn,
            draw_overrides: turn_map("draw_overrides", draw_overrides)?,
            extra_draws: turn_map("extra_draws", extra_draws)?,
        })
    }

    /// Opening hand size when no mulligan is modelled.
    #[must_use]
    pub fn hand_size(&self) -> u64 {
        self.hand_size
    }

    /// The draw-step size of turn `t >= 1` before extra draws.
    fn base(&self, t: u64) -> u64 {
        match self.draw_overrides.get(&t) {
            Some(&n) => n,
            None if t == 1 && self.on_play => 0,
            None => self.draws_per_turn,
        }
    }

    /// Cards drawn during turn `t` (0 for the opening hand).
    ///
    /// # Errors
    /// [`crate::Error::Unsupported`] if the count does not fit in 64 bits.
    pub fn draws_on_turn(&self, t: u64) -> Result<u64> {
        if t == 0 {
            return Ok(0);
        }
        self.base(t)
            .checked_add(self.extra_draws.get(&t).copied().unwrap_or(0))
            .ok_or_else(too_many)
    }

    /// Total cards drawn after the opening hand, through the draw step of turn `t`.
    ///
    /// Computed in closed form (Python sums turn by turn), so a far-away turn with no
    /// draws costs nothing.
    ///
    /// # Errors
    /// [`crate::Error::Unsupported`] if the total does not fit in 64 bits.
    pub fn draws_through(&self, t: u64) -> Result<u64> {
        if t == 0 {
            return Ok(0);
        }
        let dpt = i128::from(self.draws_per_turn);
        let default = |u: u64| if u == 1 && self.on_play { 0 } else { dpt };
        // Every turn 1..=t at the default rate, then correct the turns that differ. Each
        // term is below 2^64 in size and there are at most 2^64 of them, so the running
        // total is checked rather than assumed to fit.
        let mut total = i128::from(t).checked_mul(dpt).ok_or_else(too_many)?;
        if self.on_play {
            total -= dpt;
        }
        let corrections = self
            .draw_overrides
            .range(1..=t)
            .map(|(&u, &n)| i128::from(n) - default(u))
            .chain(self.extra_draws.range(1..=t).map(|(_, &n)| i128::from(n)));
        for c in corrections {
            total = total.checked_add(c).ok_or_else(too_many)?;
        }
        u64::try_from(total).map_err(|_| too_many())
    }
}

fn too_many() -> crate::Error {
    unsupported("more than 2^64 cards drawn")
}

impl Default for GameConfig {
    /// Python's `GameConfig()`: 7 cards, on the play, one draw per turn.
    fn default() -> Self {
        GameConfig::new(7, true, 1, &[], &[]).expect("the defaults are valid")
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::Error;

    /// Python's definition, turn by turn, as the oracle for the closed form.
    fn reference(g: &GameConfig, t: u64) -> u64 {
        (1..=t).map(|u| g.draws_on_turn(u).unwrap()).sum()
    }

    #[test]
    fn closed_form_matches_the_turn_by_turn_sum() {
        for on_play in [true, false] {
            for dpt in 0..3 {
                for overrides in [vec![], vec![(1, 2)], vec![(2, 0), (5, 3)]] {
                    for extra in [vec![], vec![(1, 1)], vec![(3, 2), (4, 1)]] {
                        let g = GameConfig::new(7, on_play, dpt, &overrides, &extra).unwrap();
                        for t in 0..8 {
                            assert_eq!(
                                g.draws_through(t).unwrap(),
                                reference(&g, t),
                                "{g:?} t={t}"
                            );
                        }
                    }
                }
            }
        }
    }

    #[test]
    fn going_first_skips_the_first_draw_unless_overridden() {
        let play = GameConfig::default();
        assert_eq!(play.draws_on_turn(1).unwrap(), 0);
        assert_eq!(play.draws_through(3).unwrap(), 2);
        let draw = GameConfig::new(7, false, 1, &[], &[]).unwrap();
        assert_eq!(draw.draws_through(3).unwrap(), 3);
        let forced = GameConfig::new(7, true, 1, &[(1, 1)], &[]).unwrap();
        assert_eq!(forced.draws_on_turn(1).unwrap(), 1);
    }

    #[test]
    fn far_turns_are_cheap_and_exact() {
        let g = GameConfig::new(7, true, 0, &[(3, 2)], &[(2, 1)]).unwrap();
        assert_eq!(g.draws_through(u64::MAX).unwrap(), 3);
        let busy = GameConfig::new(7, false, i64::MAX, &[], &[]).unwrap();
        assert!(matches!(busy.draws_through(3), Err(Error::Unsupported(_))));
    }

    #[test]
    fn validation_matches_python() {
        let field = |r: Result<GameConfig>| match r.unwrap_err() {
            Error::Validation { field, message } => format!("{field}: {message}"),
            other => panic!("{other:?}"),
        };
        assert_eq!(
            field(GameConfig::new(-1, true, 1, &[], &[])),
            "game.hand_size: must be non-negative"
        );
        assert_eq!(
            field(GameConfig::new(7, true, -1, &[], &[])),
            "game.draws_per_turn: must be non-negative"
        );
        assert_eq!(
            field(GameConfig::new(7, true, 1, &[(0, 1)], &[])),
            "game.draw_overrides: turn keys must be >= 1"
        );
        assert_eq!(
            field(GameConfig::new(7, true, 1, &[], &[(2, -1)])),
            "game.extra_draws[2]: must be non-negative"
        );
        assert_eq!(
            field(GameConfig::new(7, true, 1, &[(2, 1), (2, 3)], &[])),
            "game.draw_overrides[2]: duplicate turn"
        );
    }
}
