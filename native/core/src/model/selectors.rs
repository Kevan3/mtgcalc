//! Selectors: rules that pick cards out of a deck (port of `mtgcalc.model.selectors`).

use super::deck::Card;
use super::text::{collapse_whitespace, normalize};
use crate::error::{validation, Result};

/// A validated selector. Equality is Python's dataclass equality: tags compare after
/// normalization, card names after whitespace collapsing (case still matters for
/// equality, although matching ignores case, exactly as in Python).
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct Selector(pub(crate) Sel);

/// The selector variants (crate-internal so every value passes through validation).
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub(crate) enum Sel {
    Tag(String),
    CardName(String),
    AnyOf(Vec<Selector>),
    AllOf(Vec<Selector>),
    NoneOf(Vec<Selector>),
    Everything,
}

fn non_empty(kind: &str, items: Vec<Selector>) -> Result<Vec<Selector>> {
    if items.is_empty() {
        return Err(validation(kind, "needs at least one selector"));
    }
    Ok(items)
}

impl Selector {
    /// Cards carrying a tag (case-insensitive).
    ///
    /// # Errors
    /// A validation error if the tag is empty after normalization.
    pub fn tag(name: &str) -> Result<Self> {
        let clean = normalize(name);
        if clean.is_empty() {
            return Err(validation("tag", "tag name must not be empty"));
        }
        Ok(Selector(Sel::Tag(clean)))
    }

    /// Cards with a given name (case-insensitive).
    ///
    /// # Errors
    /// A validation error if the name is empty after whitespace collapsing.
    pub fn card(name: &str) -> Result<Self> {
        let clean = collapse_whitespace(name);
        if clean.is_empty() {
            return Err(validation("card", "card name must not be empty"));
        }
        Ok(Selector(Sel::CardName(clean)))
    }

    /// Union: cards matched by at least one item.
    ///
    /// # Errors
    /// A validation error if `items` is empty.
    pub fn any_of(items: Vec<Selector>) -> Result<Self> {
        Ok(Selector(Sel::AnyOf(non_empty("any_of", items)?)))
    }

    /// Intersection: cards matched by every item.
    ///
    /// # Errors
    /// A validation error if `items` is empty.
    pub fn all_of(items: Vec<Selector>) -> Result<Self> {
        Ok(Selector(Sel::AllOf(non_empty("all_of", items)?)))
    }

    /// Complement of the union: cards matched by no item.
    ///
    /// # Errors
    /// A validation error if `items` is empty.
    pub fn none_of(items: Vec<Selector>) -> Result<Self> {
        Ok(Selector(Sel::NoneOf(non_empty("none_of", items)?)))
    }

    /// Every card in the library.
    #[must_use]
    pub fn everything() -> Self {
        Selector(Sel::Everything)
    }

    /// Whether this selector picks `card`.
    #[must_use]
    pub fn matches(&self, card: &Card) -> bool {
        match &self.0 {
            Sel::Tag(name) => card.has_tag(name),
            Sel::CardName(name) => normalize(name) == card.key(),
            Sel::AnyOf(items) => items.iter().any(|s| s.matches(card)),
            Sel::AllOf(items) => items.iter().all(|s| s.matches(card)),
            Sel::NoneOf(items) => !items.iter().any(|s| s.matches(card)),
            Sel::Everything => true,
        }
    }

    /// Every card name referenced anywhere inside this selector, in order.
    #[must_use]
    pub fn card_names(&self) -> Vec<&str> {
        match &self.0 {
            Sel::CardName(name) => vec![name.as_str()],
            Sel::AnyOf(items) | Sel::AllOf(items) | Sel::NoneOf(items) => {
                items.iter().flat_map(Selector::card_names).collect()
            }
            Sel::Tag(_) | Sel::Everything => Vec::new(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::deck::Zone;

    fn card(name: &str, tags: &[&str]) -> Card {
        Card::new(
            name,
            2,
            &tags.iter().map(ToString::to_string).collect::<Vec<_>>(),
            Zone::Library,
        )
        .unwrap()
    }

    #[test]
    fn tags_normalize_and_compare_equal() {
        assert_eq!(
            Selector::tag(" Card  Draw ").unwrap(),
            Selector::tag("card draw").unwrap()
        );
        assert!(Selector::tag("  ").is_err());
    }

    #[test]
    fn card_names_keep_case_for_equality_but_match_any_case() {
        let a = Selector::card("Sol Ring").unwrap();
        let b = Selector::card("sol ring").unwrap();
        assert_ne!(a, b); // as Python's dataclass equality
        let sol = card("SOL  RING", &[]);
        assert!(a.matches(&sol) && b.matches(&sol));
        assert!(Selector::card("\t").is_err());
    }

    #[test]
    fn combinators_follow_set_logic() {
        let land = Selector::tag("land").unwrap();
        let ramp = Selector::tag("ramp").unwrap();
        let dork = card("Elf", &["ramp", "creature"]);
        let forest = card("Forest", &["land"]);
        let any = Selector::any_of(vec![land.clone(), ramp.clone()]).unwrap();
        let all = Selector::all_of(vec![land.clone(), ramp.clone()]).unwrap();
        let none = Selector::none_of(vec![land, ramp]).unwrap();
        assert!(any.matches(&dork) && any.matches(&forest));
        assert!(!all.matches(&dork) && !all.matches(&forest));
        assert!(!none.matches(&dork) && none.matches(&card("Bolt", &["removal"])));
        assert!(Selector::everything().matches(&forest));
        assert!(Selector::any_of(vec![]).is_err());
        assert!(Selector::all_of(vec![]).is_err());
        assert!(Selector::none_of(vec![]).is_err());
    }

    #[test]
    fn card_names_are_collected_recursively() {
        let s = Selector::any_of(vec![
            Selector::card("A").unwrap(),
            Selector::none_of(vec![
                Selector::card("B").unwrap(),
                Selector::tag("x").unwrap(),
            ])
            .unwrap(),
        ])
        .unwrap();
        assert_eq!(s.card_names(), vec!["A", "B"]);
    }
}
