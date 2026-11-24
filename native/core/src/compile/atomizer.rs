//! Atomization: overlapping selectors become disjoint atoms (port of
//! `mtgcalc.compile.atomizer`, MATH §6).
//!
//! An *atom* is the set of library cards sharing one membership signature over the
//! referenced selectors. Atom counts are multivariate hypergeometric (MATH §4); every
//! selector count is the sum of the counts of the atoms whose signature includes it.
//! Cards matched by no referenced selector form the untracked *pool*.

use std::collections::{HashMap, HashSet};

use crate::error::{validation, Result};
use crate::model::text::normalize;
use crate::model::{Card, Deck, Selector};

/// Disjoint atoms of a deck with respect to a list of selectors.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AtomTable {
    /// Library size.
    pub deck_size: u64,
    /// The distinct selectors, in first-reference order.
    pub selectors: Vec<Selector>,
    /// Membership signature of each atom (one flag per selector), descending order.
    pub signatures: Vec<Vec<bool>>,
    /// Cards in each atom.
    pub counts: Vec<u64>,
    /// Card names in each atom, in deck order.
    pub names: Vec<Vec<String>>,
    /// Cards in no tracked atom.
    pub pool: u64,
}

impl AtomTable {
    /// Number of tracked atoms.
    #[must_use]
    pub fn size(&self) -> usize {
        self.counts.len()
    }

    /// Indices of the atoms whose cards `sel` matches.
    ///
    /// # Errors
    /// A validation error if `sel` was not atomized.
    pub fn mask(&self, sel: &Selector) -> Result<Vec<usize>> {
        let j = self
            .selectors
            .iter()
            .position(|s| s == sel)
            .ok_or_else(|| validation("selector", format!("{sel:?} was not atomized")))?;
        Ok((0..self.signatures.len())
            .filter(|&i| self.signatures[i][j])
            .collect())
    }
}

/// Partitions the library into atoms over `selectors` (deterministic order).
///
/// # Errors
/// A validation error if a selector names a card that is not in the library.
pub fn atomize<'a>(
    deck: &Deck,
    selectors: impl IntoIterator<Item = &'a Selector>,
) -> Result<AtomTable> {
    let mut sels: Vec<Selector> = Vec::new();
    for s in selectors {
        if !sels.contains(s) {
            sels.push(s.clone());
        }
    }
    let known: HashSet<&str> = deck.library().map(Card::key).collect();
    for s in &sels {
        for name in s.card_names() {
            if !known.contains(normalize(name).as_str()) {
                return Err(validation(
                    "selector",
                    format!("no library card named '{name}'"),
                ));
            }
        }
    }
    let mut groups: HashMap<Vec<bool>, (u64, Vec<String>)> = HashMap::new();
    for card in deck.library() {
        let sig: Vec<bool> = sels.iter().map(|s| s.matches(card)).collect();
        let entry = groups.entry(sig).or_default();
        entry.0 += card.quantity();
        entry.1.push(card.name().to_owned());
    }
    let pool = groups
        .remove(&vec![false; sels.len()])
        .map_or(0, |(count, _)| count);
    let mut order: Vec<Vec<bool>> = groups.keys().cloned().collect();
    order.sort_unstable_by(|a, b| b.cmp(a)); // Python: sorted(groups, reverse=True)
    let (counts, names) = order.iter().map(|sig| groups[sig].clone()).unzip();
    Ok(AtomTable {
        deck_size: deck.size(),
        selectors: sels,
        signatures: order,
        counts,
        names,
        pool,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::Zone;
    use crate::Error;

    fn deck() -> Deck {
        let card = |name: &str, n: i64, tags: &[&str]| {
            Card::new(
                name,
                n,
                &tags.iter().map(ToString::to_string).collect::<Vec<_>>(),
                Zone::Library,
            )
            .unwrap()
        };
        Deck::new(vec![
            card("Forest", 20, &["land"]),
            card("Dryad Arbor", 1, &["land", "creature"]),
            card("Elf", 4, &["creature", "ramp"]),
            card("Bolt", 4, &["removal"]),
            card("Filler", 31, &[]),
            Card::new("Commander", 1, &["creature".into()], Zone::Commander).unwrap(),
        ])
        .unwrap()
    }

    fn tag(t: &str) -> Selector {
        Selector::tag(t).unwrap()
    }

    #[test]
    fn overlapping_tags_split_into_disjoint_atoms() {
        let land = tag("land");
        let creature = tag("creature");
        let t = atomize(&deck(), [&land, &creature, &land]).unwrap();
        assert_eq!(t.selectors, vec![land.clone(), creature.clone()]);
        // Signatures sorted descending: (T,T) arbor, (T,F) forest, (F,T) elf.
        assert_eq!(
            t.signatures,
            vec![vec![true, true], vec![true, false], vec![false, true]]
        );
        assert_eq!(t.counts, vec![1, 20, 4]);
        assert_eq!(t.names[0], vec!["Dryad Arbor".to_owned()]);
        assert_eq!(t.pool, 35); // Bolt + Filler; the commander is not in the library
        assert_eq!(t.mask(&land).unwrap(), vec![0, 1]);
        assert_eq!(t.mask(&creature).unwrap(), vec![0, 2]);
        assert!(t.mask(&tag("removal")).is_err());
    }

    #[test]
    fn everything_leaves_an_empty_pool() {
        let t = atomize(&deck(), [&Selector::everything()]).unwrap();
        assert_eq!((t.counts.clone(), t.pool), (vec![60], 0));
    }

    #[test]
    fn card_names_must_exist_in_the_library() {
        let ok = Selector::card("dryad  ARBOR").unwrap();
        assert_eq!(atomize(&deck(), [&ok]).unwrap().counts, vec![1]);
        let missing = Selector::card("Commander").unwrap(); // command zone only
        match atomize(&deck(), [&missing]).unwrap_err() {
            Error::Validation { field, message } => {
                assert_eq!(field, "selector");
                assert_eq!(message, "no library card named 'Commander'");
            }
            other => panic!("{other:?}"),
        }
    }
}
