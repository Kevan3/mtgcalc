//! Cards and decks (port of `mtgcalc.model.deck`).

use std::collections::{BTreeSet, HashSet};

use super::text::{collapse_whitespace, normalize};
use crate::error::{unsupported, validation, Result};

/// Largest library the engine accepts (its counts are 16-bit).
pub const MAX_LIBRARY: u64 = u16::MAX as u64;

/// Where a card starts the game. Only [`Zone::Library`] cards are shuffled.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Zone {
    /// Shuffled into the library.
    Library,
    /// The command zone.
    Commander,
    /// The sideboard.
    Sideboard,
    /// The maybeboard.
    Maybeboard,
}

impl Zone {
    /// Python's name for the zone.
    #[must_use]
    pub fn as_str(self) -> &'static str {
        match self {
            Zone::Library => "library",
            Zone::Commander => "commander",
            Zone::Sideboard => "sideboard",
            Zone::Maybeboard => "maybeboard",
        }
    }

    /// Parses Python's zone name.
    ///
    /// # Errors
    /// A validation error naming the card for an unknown zone, as Python's `Card`.
    pub fn parse(zone: &str, card: &str) -> Result<Self> {
        Ok(match zone {
            "library" => Zone::Library,
            "commander" => Zone::Commander,
            "sideboard" => Zone::Sideboard,
            "maybeboard" => Zone::Maybeboard,
            _ => {
                return Err(validation(
                    format!("card[{card}].zone"),
                    "must be one of ('library', 'commander', 'sideboard', 'maybeboard')",
                ))
            }
        })
    }
}

/// A card entry: a name, how many copies, its tags and its zone.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Card {
    name: String,
    key: String,
    quantity: u64,
    tags: BTreeSet<String>,
    zone: Zone,
}

impl Card {
    /// Validates and normalizes a card, exactly as Python's `Card.__post_init__`.
    ///
    /// # Errors
    /// A validation error for an empty name, a quantity below 1, or an empty tag.
    pub fn new(name: &str, quantity: i64, tags: &[String], zone: Zone) -> Result<Self> {
        let clean = collapse_whitespace(name);
        if clean.is_empty() {
            return Err(validation("card.name", "must not be empty"));
        }
        let quantity = u64::try_from(quantity)
            .ok()
            .filter(|&q| q >= 1)
            .ok_or_else(|| validation(format!("card[{clean}].quantity"), "must be at least 1"))?;
        let tags: BTreeSet<String> = tags.iter().map(|t| normalize(t)).collect();
        if tags.contains("") {
            return Err(validation(
                format!("card[{clean}].tags"),
                "tags must not be empty",
            ));
        }
        Ok(Card {
            key: normalize(&clean),
            name: clean,
            quantity,
            tags,
            zone,
        })
    }

    /// The card's name (whitespace collapsed).
    #[must_use]
    pub fn name(&self) -> &str {
        &self.name
    }

    /// The case-insensitive lookup key of the name.
    #[must_use]
    pub fn key(&self) -> &str {
        &self.key
    }

    /// Number of copies.
    #[must_use]
    pub fn quantity(&self) -> u64 {
        self.quantity
    }

    /// The card's (normalized) tags, sorted.
    pub fn tags(&self) -> impl Iterator<Item = &str> {
        self.tags.iter().map(String::as_str)
    }

    /// Whether the card carries a (normalized) tag.
    #[must_use]
    pub fn has_tag(&self, tag: &str) -> bool {
        self.tags.contains(tag)
    }

    /// The card's zone.
    #[must_use]
    pub fn zone(&self) -> Zone {
        self.zone
    }
}

/// An immutable, validated decklist.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Deck {
    cards: Vec<Card>,
    size: u64,
}

impl Deck {
    /// Validates a deck, exactly as Python's `Deck.__post_init__`.
    ///
    /// # Errors
    /// A validation error for a duplicate card within a zone or an empty library;
    /// [`crate::Error::Unsupported`] for a library above [`MAX_LIBRARY`] cards.
    pub fn new(cards: Vec<Card>) -> Result<Self> {
        let mut seen = HashSet::new();
        for c in &cards {
            if !seen.insert((c.zone, c.key.as_str())) {
                return Err(validation(
                    format!("deck.cards[{}]", c.name),
                    format!("duplicate card in zone {}", c.zone.as_str()),
                ));
            }
        }
        let size = cards
            .iter()
            .filter(|c| c.zone == Zone::Library)
            .try_fold(0u64, |acc, c| acc.checked_add(c.quantity))
            .ok_or_else(|| unsupported(format!("libraries above {MAX_LIBRARY} cards")))?;
        if size == 0 {
            return Err(validation(
                "deck.cards",
                "library must contain at least one card",
            ));
        }
        if size > MAX_LIBRARY {
            return Err(unsupported(format!("libraries above {MAX_LIBRARY} cards")));
        }
        Ok(Deck { cards, size })
    }

    /// Every card, in deck order.
    #[must_use]
    pub fn cards(&self) -> &[Card] {
        &self.cards
    }

    /// Cards shuffled into the library, in deck order.
    pub fn library(&self) -> impl Iterator<Item = &Card> {
        self.cards.iter().filter(|c| c.zone == Zone::Library)
    }

    /// Library size N (at most [`MAX_LIBRARY`]).
    #[must_use]
    pub fn size(&self) -> u64 {
        self.size
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::Error;

    fn card(name: &str, n: i64, zone: Zone) -> Card {
        Card::new(name, n, &[], zone).unwrap()
    }

    fn field(e: Error) -> String {
        match e {
            Error::Validation { field, .. } => field,
            other => panic!("expected a validation error, got {other:?}"),
        }
    }

    #[test]
    fn card_validation_matches_python() {
        assert_eq!(
            field(Card::new("  ", 1, &[], Zone::Library).unwrap_err()),
            "card.name"
        );
        assert_eq!(
            field(Card::new(" Sol  Ring ", 0, &[], Zone::Library).unwrap_err()),
            "card[Sol Ring].quantity"
        );
        assert_eq!(
            field(Card::new("X", 1, &[" ".into()], Zone::Library).unwrap_err()),
            "card[X].tags"
        );
        let c = Card::new(" Sol  Ring ", 2, &[" Mana  ROCK ".into()], Zone::Library).unwrap();
        assert_eq!(
            (c.name(), c.key(), c.quantity()),
            ("Sol Ring", "sol ring", 2)
        );
        assert!(c.has_tag("mana rock"));
    }

    #[test]
    fn zones_parse_and_reject_unknown_names() {
        for z in [
            Zone::Library,
            Zone::Commander,
            Zone::Sideboard,
            Zone::Maybeboard,
        ] {
            assert_eq!(Zone::parse(z.as_str(), "x").unwrap(), z);
        }
        assert_eq!(
            field(Zone::parse("graveyard", "X").unwrap_err()),
            "card[X].zone"
        );
    }

    #[test]
    fn deck_counts_only_the_library() {
        let d = Deck::new(vec![
            card("Forest", 20, Zone::Library),
            card("Bolt", 4, Zone::Library),
            card("Atraxa", 1, Zone::Commander),
            card("Forest", 3, Zone::Sideboard), // same name, other zone: allowed
        ])
        .unwrap();
        assert_eq!(d.size(), 24);
        assert_eq!(d.library().count(), 2);
    }

    #[test]
    fn deck_rejects_duplicates_and_empty_libraries() {
        let dup = Deck::new(vec![
            card("Forest", 1, Zone::Library),
            card("FOREST", 1, Zone::Library),
        ]);
        assert_eq!(field(dup.unwrap_err()), "deck.cards[FOREST]");
        let empty = Deck::new(vec![card("Atraxa", 1, Zone::Commander)]);
        assert_eq!(field(empty.unwrap_err()), "deck.cards");
    }

    #[test]
    fn huge_libraries_are_unsupported_not_wrong() {
        let big = Deck::new(vec![
            card("A", 65_535, Zone::Library),
            card("B", 1, Zone::Library),
        ]);
        assert!(matches!(big, Err(Error::Unsupported(_))));
        let overflow = Deck::new(vec![
            card("A", i64::MAX, Zone::Library),
            card("B", i64::MAX, Zone::Library),
            card("C", i64::MAX, Zone::Library),
        ]);
        assert!(matches!(overflow, Err(Error::Unsupported(_))));
        assert!(Deck::new(vec![card("A", 65_535, Zone::Library)]).is_ok());
    }
}
