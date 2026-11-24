//! Condition compiler (port of `mtgcalc.compile.compiler`, LLD §4.4).
//!
//! Turns condition trees into (a) deduplicated *leaves* that the engine evaluates into
//! predicate bits at their checkpoints and (b) one postfix program per named output.
//! Bits are numbered in checkpoint order, so every bit of checkpoint `j` is known once
//! the engine has processed checkpoint `j` (needed for early resolution, MATH §5.3).

use std::collections::{BTreeSet, HashMap, HashSet};

use super::atomizer::{atomize, AtomTable};
use super::schedule::{plan, BatchPlan};
use crate::engine::Query as EngineQuery;
use crate::error::{unsupported, validation, Error, Result};
use crate::logic::{op, Leaf, Program, MAX_BITS};
use crate::model::conditions::Cond;
use crate::model::{Condition, Deck, GameConfig, Op, Selector, MAX_LIBRARY};

/// Largest number of demands in one exclusive assignment (the engine enumerates every
/// subset of demands, MATH §8).
pub const MAX_DEMANDS: usize = 16;

/// Every count the engine sees is at most the library size, so any number above it can
/// be replaced by this one without changing a comparison's outcome.
const BEYOND: u64 = MAX_LIBRARY + 1;

fn clamp(n: u64) -> u32 {
    // BEYOND fits in u32, so the conversion cannot fail.
    u32::try_from(n.min(BEYOND)).unwrap_or(u32::MAX)
}

/// What a leaf tests, with selectors already resolved to atom masks.
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
enum Test {
    Compare {
        mask: Vec<usize>,
        op: Op,
        value: u64,
    },
    Between {
        mask: Vec<usize>,
        lo: u64,
        hi: u64,
    },
    Assign {
        demands: Vec<(Vec<usize>, u64)>,
    },
}

/// A leaf before bit assignment; equal specs share one bit (deduplication).
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
struct LeafSpec {
    turn: u64,
    test: Test,
}

impl LeafSpec {
    fn to_leaf(&self, bit: u32, checkpoint: usize, atoms: usize) -> Result<Leaf> {
        let code = |op: Op| match op {
            Op::Eq => 0,
            Op::Ne => 1,
            Op::Lt => 2,
            Op::Le => 3,
            Op::Gt => 4,
            Op::Ge => 5,
        };
        let (kind, mask, op, value, lo, hi, demands) = match &self.test {
            Test::Compare { mask, op, value } => {
                (0, mask.clone(), code(*op), clamp(*value), 0, 0, vec![])
            }
            Test::Between { mask, lo, hi } => {
                (1, mask.clone(), 0, 0, clamp(*lo), clamp(*hi), vec![])
            }
            Test::Assign { demands } => (
                2,
                vec![],
                0,
                0,
                0,
                0,
                demands
                    .iter()
                    .map(|(m, n)| (m.clone(), clamp(*n)))
                    .collect(),
            ),
        };
        Leaf::new(
            bit, checkpoint, kind, mask, op, value, lo, hi, demands, atoms,
        )
    }
}

/// Everything the engine needs to evaluate named outputs on one scenario.
#[derive(Clone, Debug)]
pub struct CompiledQuery {
    /// The atoms the outputs are expressed over.
    pub atoms: AtomTable,
    /// Checkpoints and draws.
    pub plan: BatchPlan,
    /// The engine input, validated.
    pub query: EngineQuery,
    /// Output names, in the order of `query.outputs`.
    pub names: Vec<String>,
}

fn leaf_key(node: &Condition, turn: u64, atoms: &AtomTable) -> Result<LeafSpec> {
    let test = match &node.0 {
        Cond::Compare { sel, op, value } => Test::Compare {
            mask: atoms.mask(sel)?,
            op: *op,
            value: *value,
        },
        Cond::Between { sel, lo, hi } => Test::Between {
            mask: atoms.mask(sel)?,
            lo: *lo,
            hi: *hi,
        },
        Cond::Assignable(demands) => Test::Assign {
            demands: demands
                .iter()
                .map(|d| Ok((atoms.mask(&d.sel)?, d.need)))
                .collect::<Result<_>>()?,
        },
        _ => return Err(Error::Invalid("not a leaf".into())),
    };
    Ok(LeafSpec { turn, test })
}

/// Appends the postfix program for `node` to `out`; `bit_of` numbers each leaf.
fn emit(
    node: &Condition,
    turn: u64,
    atoms: &AtomTable,
    bit_of: &mut dyn FnMut(LeafSpec) -> Result<i64>,
    out: &mut Vec<i64>,
) -> Result<()> {
    let count = |n: usize| i64::try_from(n).map_err(|_| unsupported("too many operands"));
    match &node.0 {
        Cond::Compare { .. } | Cond::Between { .. } | Cond::Assignable(_) => {
            let bit = bit_of(leaf_key(node, turn, atoms)?)?;
            out.extend([op::BIT, bit]);
        }
        Cond::At(t, item) => emit(item, *t, atoms, bit_of, out)?,
        Cond::Const(value) => out.extend([op::CONST, i64::from(*value)]),
        Cond::Not(item) => {
            emit(item, turn, atoms, bit_of, out)?;
            out.push(op::NOT);
        }
        Cond::And(items) | Cond::Or(items) => {
            for item in items {
                emit(item, turn, atoms, bit_of, out)?;
            }
            let code = if matches!(node.0, Cond::And(_)) {
                op::AND
            } else {
                op::OR
            };
            out.extend([code, count(items.len())?]);
        }
        Cond::Xor(a, b) | Cond::Implies(a, b) => {
            emit(a, turn, atoms, bit_of, out)?;
            emit(b, turn, atoms, bit_of, out)?;
            out.push(if matches!(node.0, Cond::Xor(..)) {
                op::XOR
            } else {
                op::IMPLIES
            });
        }
        Cond::AtLeast(n, items) | Cond::Exactly(n, items) => {
            for item in items {
                emit(item, turn, atoms, bit_of, out)?;
            }
            let code = if matches!(node.0, Cond::AtLeast(..)) {
                op::ATLEAST
            } else {
                op::EXACTLY
            };
            // At most `len` items can hold, so any larger `n` behaves like `len + 1`.
            let n = usize::try_from(*n)
                .unwrap_or(usize::MAX)
                .min(items.len() + 1);
            out.extend([code, count(n)?, count(items.len())?]);
        }
    }
    Ok(())
}

/// Pass 1: every distinct leaf, in discovery order (Python's dict insertion order).
fn discover_leaves(
    outputs: &[(String, Condition)],
    turn: u64,
    atoms: &AtomTable,
) -> Result<Vec<LeafSpec>> {
    let mut seen: HashSet<LeafSpec> = HashSet::new();
    let mut order: Vec<LeafSpec> = Vec::new();
    let mut discover = |key: LeafSpec| {
        if let Test::Assign { demands } = &key.test {
            if demands.len() > MAX_DEMANDS {
                return Err(unsupported(format!(
                    "more than {MAX_DEMANDS} demands in one assignment"
                )));
            }
        }
        if seen.insert(key.clone()) {
            order.push(key);
        }
        Ok(0)
    };
    for (_, cond) in outputs {
        emit(cond, turn, atoms, &mut discover, &mut Vec::new())?;
    }
    Ok(order)
}

/// Numbers the leaves in checkpoint order, then discovery order (a stable sort keeps
/// the latter), and returns the engine leaves with each spec's bit.
fn assign_bits(
    order: Vec<LeafSpec>,
    bp: &BatchPlan,
    atoms: usize,
    reserved: u32,
) -> Result<(Vec<Leaf>, HashMap<LeafSpec, i64>)> {
    if order.len() + reserved as usize > MAX_BITS as usize {
        return Err(unsupported(format!(
            "more than {MAX_BITS} different conditions in one question"
        )));
    }
    let mut ranked: Vec<(usize, LeafSpec)> = order
        .into_iter()
        .map(|k| Ok((bp.index(k.turn)?, k)))
        .collect::<Result<_>>()?;
    ranked.sort_by_key(|(checkpoint, _)| *checkpoint);
    let mut bits = HashMap::with_capacity(ranked.len());
    let mut leaves = Vec::with_capacity(ranked.len());
    for (bit, (checkpoint, key)) in ranked.into_iter().enumerate() {
        let bit = reserved + u32::try_from(bit).map_err(|_| unsupported("too many conditions"))?;
        leaves.push(key.to_leaf(bit, checkpoint, atoms)?);
        bits.insert(key, i64::from(bit));
    }
    Ok((leaves, bits))
}

/// Atom retirement plan (MATH §5.3): after each checkpoint, the atoms that no later
/// checkpoint reads and that are not retired yet.
fn retirement_plan(
    leaves: &[Leaf],
    observers: &[(usize, Vec<usize>)],
    checkpoints: usize,
    atoms: usize,
) -> Vec<Vec<usize>> {
    let mut retired = vec![false; atoms];
    let mut plan = Vec::with_capacity(checkpoints);
    for j in 0..checkpoints {
        let mut needed = vec![false; atoms];
        for leaf in leaves.iter().filter(|l| l.checkpoint > j) {
            for i in leaf.atoms() {
                needed[i] = true;
            }
        }
        for (_, mask) in observers.iter().filter(|(at, _)| *at > j) {
            for &i in mask {
                needed[i] = true;
            }
        }
        let now: Vec<usize> = (0..atoms).filter(|&i| !needed[i] && !retired[i]).collect();
        for &i in &now {
            retired[i] = true;
        }
        plan.push(now);
    }
    plan
}

/// What to compile (the arguments of Python's `compile_query`).
#[derive(Clone, Copy, Debug)]
pub struct CompileRequest<'a> {
    /// Named output conditions.
    pub outputs: &'a [(String, Condition)],
    /// `(turn, selector)` pairs whose count distribution the engine records.
    pub observe: &'a [(u64, Selector)],
    /// Selectors to atomize even if no output uses them (keep rule, priority groups).
    pub extra_selectors: &'a [Selector],
    /// Low predicate bits reserved for flags set outside the compiler (the keep bit).
    pub reserved_bits: u32,
    /// Cards taken before the first draw (the kept hand, or the whole drawn hand when
    /// mulligans are modelled).
    pub hand_size: u64,
    /// The default checkpoint for leaves outside any `At`.
    pub turn: u64,
}

impl<'a> CompileRequest<'a> {
    /// Outputs only, no observers, extras or reserved bits.
    #[must_use]
    pub fn outputs(outputs: &'a [(String, Condition)], hand_size: u64, turn: u64) -> Self {
        CompileRequest {
            outputs,
            observe: &[],
            extra_selectors: &[],
            reserved_bits: 0,
            hand_size,
            turn,
        }
    }
}

/// Compiles named output conditions for one scenario (Python's `compile_query`).
///
/// # Errors
/// A validation error (as Python) for an unknown card name, or when the hand plus all
/// draws exceed the library; [`Error::Unsupported`] beyond the engine's limits.
pub fn compile_query(
    deck: &Deck,
    game: &GameConfig,
    req: &CompileRequest<'_>,
) -> Result<CompiledQuery> {
    let CompileRequest {
        outputs,
        observe,
        extra_selectors,
        reserved_bits,
        hand_size,
        turn,
    } = *req;
    // Python's order: the outputs' selectors, the observed ones, then the extras.
    let selectors = outputs
        .iter()
        .flat_map(|(_, c)| c.selectors())
        .chain(observe.iter().map(|(_, s)| s))
        .chain(extra_selectors.iter());
    let atoms = atomize(deck, selectors)?;

    let mut turns = BTreeSet::from([turn]);
    turns.extend(observe.iter().map(|(t, _)| *t));
    for (_, cond) in outputs {
        turns.extend(cond.turns(turn));
    }
    let bp = plan(game, &turns, hand_size)?;
    let draws = bp.total_draws();
    if hand_size
        .checked_add(draws)
        .map_or(true, |n| n > deck.size())
    {
        return Err(validation(
            "game",
            format!(
                "{hand_size} cards in hand plus {draws} draws exceed the {} cards available",
                deck.size()
            ),
        ));
    }

    let order = discover_leaves(outputs, turn, &atoms)?;
    let (leaves, bits) = assign_bits(order, &bp, atoms.size(), reserved_bits)?;

    // Pass 2: emit programs.
    let mut programs = Vec::with_capacity(outputs.len());
    for (_, cond) in outputs {
        let mut code = Vec::new();
        let mut lookup = |key: LeafSpec| {
            bits.get(&key)
                .copied()
                .ok_or_else(|| Error::Invalid("leaf missed by discovery".into()))
        };
        emit(cond, turn, &atoms, &mut lookup, &mut code)?;
        programs.push(Program::new(code)?);
    }

    let observers = observe
        .iter()
        .map(|(t, s)| Ok((bp.index(*t)?, atoms.mask(s)?)))
        .collect::<Result<Vec<_>>>()?;
    let small = |n: u64| u32::try_from(n).map_err(|_| unsupported("counts above 2^32"));
    let query = EngineQuery {
        deck_size: small(deck.size())?,
        counts: atoms
            .counts
            .iter()
            .map(|&c| small(c))
            .collect::<Result<_>>()?,
        pool: small(atoms.pool)?,
        hand_size: small(hand_size)?,
        batches: bp
            .batches
            .iter()
            .map(|&b| small(b))
            .collect::<Result<_>>()?,
        retire_after: retirement_plan(&leaves, &observers, bp.checkpoints.len(), atoms.size()),
        leaves,
        outputs: programs,
        observers,
        reserved_bits,
    };
    query.validate()?;
    Ok(CompiledQuery {
        atoms,
        plan: bp,
        query,
        names: outputs.iter().map(|(name, _)| name.clone()).collect(),
    })
}

/// Compiles a single-checkpoint condition (a keep rule) on an existing atom table
/// (Python's `compile_predicate`): every leaf is read from one count vector, and bits
/// are numbered from 0 in discovery order.
///
/// # Errors
/// A validation error if the condition uses a selector the table does not have;
/// [`Error::Unsupported`] beyond the engine's limits.
pub fn compile_predicate(cond: &Condition, atoms: &AtomTable) -> Result<(Vec<Leaf>, Program)> {
    let mut keys: Vec<LeafSpec> = Vec::new();
    let mut code = Vec::new();
    let mut bit_of = |key: LeafSpec| {
        let index = if let Some(i) = keys.iter().position(|k| *k == key) {
            i
        } else {
            keys.push(key);
            keys.len() - 1
        };
        i64::try_from(index).map_err(|_| unsupported("too many conditions"))
    };
    emit(cond, 0, atoms, &mut bit_of, &mut code)?;
    if keys.len() > MAX_BITS as usize {
        return Err(unsupported(format!(
            "more than {MAX_BITS} parts in a keep rule"
        )));
    }
    let leaves = keys
        .iter()
        .enumerate()
        .map(|(bit, k)| k.to_leaf(u32::try_from(bit).unwrap_or(u32::MAX), 0, atoms.size()))
        .collect::<Result<Vec<_>>>()?;
    Ok((leaves, Program::new(code)?))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::logic::Test as EngineTest;
    use crate::model::{Card, Demand, Selector, Zone};

    fn deck(types: &[(&str, i64)], size: i64) -> Deck {
        let mut cards: Vec<Card> = types
            .iter()
            .map(|(t, n)| Card::new(t, *n, &[(*t).to_owned()], Zone::Library).unwrap())
            .collect();
        let used: i64 = types.iter().map(|(_, n)| n).sum();
        if size > used {
            cards.push(
                Card::new("(other)", size - used, &["(other)".into()], Zone::Library).unwrap(),
            );
        }
        Deck::new(cards).unwrap()
    }

    fn ge(t: &str, n: i64) -> Condition {
        Condition::compare(Selector::tag(t).unwrap(), Op::Ge, n).unwrap()
    }

    fn compile_query_t(
        d: &Deck,
        outputs: &[(String, Condition)],
        hand: u64,
        turn: u64,
    ) -> Result<CompiledQuery> {
        compile_query(
            d,
            &GameConfig::default(),
            &CompileRequest::outputs(outputs, hand, turn),
        )
    }

    fn one(cond: Condition) -> Vec<(String, Condition)> {
        vec![("p".to_owned(), cond)]
    }

    #[test]
    fn single_leaf_compiles_to_one_bit() {
        let d = deck(&[("land", 24)], 60);
        let cq = compile_query_t(&d, &one(ge("land", 3)), 7, 0).unwrap();
        assert_eq!(cq.query.counts, vec![24]);
        assert_eq!(cq.query.pool, 36);
        assert_eq!(cq.query.batches, vec![0]);
        assert_eq!(cq.query.leaves.len(), 1);
        assert_eq!(cq.query.outputs[0], Program::new(vec![op::BIT, 0]).unwrap());
        assert_eq!(cq.query.retire_after, vec![vec![0]]);
    }

    #[test]
    fn equal_leaves_share_a_bit_and_bits_follow_checkpoints() {
        let d = deck(&[("land", 24), ("ramp", 8)], 60);
        // Discovery order: land@3, ramp@1, land@3 again. Checkpoint order puts ramp@1 first.
        let cond = Condition::and(vec![
            Condition::at(3, ge("land", 3)).unwrap(),
            Condition::at(1, ge("ramp", 1)).unwrap(),
            Condition::at(3, ge("land", 3)).unwrap(),
        ])
        .unwrap();
        let cq = compile_query_t(&d, &one(cond), 7, 0).unwrap();
        assert_eq!(cq.plan.checkpoints, vec![0, 1, 3]);
        assert_eq!(cq.query.leaves.len(), 2);
        assert_eq!(
            (cq.query.leaves[0].bit, cq.query.leaves[0].checkpoint),
            (0, 1)
        );
        assert_eq!(
            (cq.query.leaves[1].bit, cq.query.leaves[1].checkpoint),
            (1, 2)
        );
        let expected = vec![op::BIT, 1, op::BIT, 0, op::BIT, 1, op::AND, 3];
        assert_eq!(cq.query.outputs[0], Program::new(expected).unwrap());
        // Ramp is not read after turn 1; land is read at the end.
        assert_eq!(cq.query.retire_after, vec![vec![], vec![1], vec![0]]);
    }

    #[test]
    fn observers_are_atomized_scheduled_and_kept_until_read() {
        let d = deck(&[("land", 24), ("ramp", 8)], 60);
        let ramp = Selector::tag("ramp").unwrap();
        let cq = compile_query(
            &d,
            &GameConfig::default(),
            &CompileRequest {
                observe: &[(4, ramp)],
                ..CompileRequest::outputs(&one(ge("land", 3)), 7, 0)
            },
        )
        .unwrap();
        assert_eq!(cq.plan.checkpoints, vec![0, 4]);
        assert_eq!(cq.query.observers, vec![(1, vec![1])]);
        // land is read at turn 0; ramp is observed at turn 4, so it is kept until then.
        assert_eq!(cq.query.retire_after, vec![vec![0], vec![1]]);
        let none = compile_query(
            &d,
            &GameConfig::default(),
            &CompileRequest {
                observe: &[(0, Selector::everything())],
                ..CompileRequest::outputs(&[], 7, 0)
            },
        )
        .unwrap();
        assert_eq!(none.query.outputs.len(), 0);
    }

    #[test]
    fn huge_numbers_are_clamped_without_changing_meaning() {
        let d = deck(&[("land", 24)], 60);
        let cond = Condition::at_least(
            i64::MAX,
            vec![Condition::compare(Selector::tag("land").unwrap(), Op::Lt, i64::MAX).unwrap()],
        )
        .unwrap();
        let cq = compile_query_t(&d, &one(cond), 7, 0).unwrap();
        match &cq.query.leaves[0].test {
            EngineTest::Compare { value, .. } => assert_eq!(*value, 65_536),
            other => panic!("{other:?}"),
        }
        let code = vec![op::BIT, 0, op::ATLEAST, 2, 1];
        assert_eq!(cq.query.outputs[0], Program::new(code).unwrap());
    }

    #[test]
    fn the_default_turn_is_always_a_checkpoint() {
        // As in Python: draws through the default turn are validated even if every leaf
        // is bound to another turn.
        let d = deck(&[("land", 5)], 10);
        let cond = Condition::at(0, ge("land", 1)).unwrap();
        let err = compile_query_t(&d, &one(cond), 7, 5).unwrap_err();
        assert_eq!(
            err.to_string(),
            "game: 7 cards in hand plus 4 draws exceed the 10 cards available"
        );
    }

    #[test]
    fn limits_are_reported_as_unsupported() {
        let d = deck(&[("land", 60)], 60);
        let many: Vec<Condition> = (0..65).map(|k| ge("land", k)).collect();
        let err = compile_query_t(&d, &one(Condition::and(many).unwrap()), 7, 0);
        assert!(matches!(err, Err(Error::Unsupported(_))));
        let demands = (0..17)
            .map(|_| Demand::new(Selector::tag("land").unwrap(), 1).unwrap())
            .collect();
        let err = compile_query_t(&d, &one(Condition::assignable(demands).unwrap()), 7, 0);
        assert!(matches!(err, Err(Error::Unsupported(_))));
    }
}
