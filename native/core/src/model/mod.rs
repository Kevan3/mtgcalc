//! The input model (port of `mtgcalc.model`): decks, selectors, conditions, game
//! settings and scenarios. Every value is validated when constructed, with the same
//! rules, field paths and messages as Python, so later stages can trust it.

pub mod conditions;
pub mod deck;
pub mod game;
pub mod mulligan;
pub mod selectors;
pub mod text;
#[allow(missing_docs, clippy::unreadable_literal)] // generated
#[rustfmt::skip]
mod unicode_tables;

pub use conditions::{Condition, Demand, Op, Query};
pub use deck::{Card, Deck, Zone, MAX_LIBRARY};
pub use game::GameConfig;
pub use mulligan::{MulliganConfig, PriorityGroup};
pub use selectors::Selector;
pub use unicode_tables::UNICODE_VERSION;

/// Deck, game configuration and optional mulligan configuration (Python's `Scenario`).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Scenario {
    /// The deck.
    pub deck: Deck,
    /// How many cards are seen when.
    pub game: GameConfig,
    /// The London mulligan, if modelled.
    pub mulligan: Option<MulliganConfig>,
}
