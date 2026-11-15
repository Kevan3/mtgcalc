//! The exact sequential dynamic program (LLD §5.2, MATH §5).
//!
//! A distribution over states `(seen counts, bottomed counts, predicate bits)` with
//! integer weights over one shared integer denominator. State merging, atom retirement
//! and early resolution are exact (MATH §5.3). This is a port of
//! `mtgcalc.engine.exact.ExactEngine.run`; the two must agree bit for bit.

use num_bigint::BigUint;
use rustc_hash::FxHashMap;

use crate::binom::Binom;
use crate::error::{invalid, Error, Result};
use crate::logic::{leaf_bits, Leaf, Program, MAX_BITS};
use crate::weight::{add, from_big, mul, Weight};

/// A flattened `CompiledQuery` (see `mtgcalc.engine.native._flatten`).
#[derive(Clone, Debug)]
pub struct Query {
    /// Library size N.
    pub deck_size: u32,
    /// Cards in each tracked atom.
    pub counts: Vec<u32>,
    /// Cards in no tracked atom.
    pub pool: u32,
    /// Cards taken before the first checkpoint (hand, or the full draw with mulligans).
    pub hand_size: u32,
    /// Cards drawn before each checkpoint (`batches[0] == 0`).
    pub batches: Vec<u32>,
    /// Leaf predicates.
    pub leaves: Vec<Leaf>,
    /// One program per output.
    pub outputs: Vec<Program>,
    /// `(checkpoint, atom mask)` marginals to record.
    pub observers: Vec<(usize, Vec<usize>)>,
    /// Atoms that can be folded into the pool after each checkpoint.
    pub retire_after: Vec<Vec<usize>>,
    /// Low bits reserved for flags set by the caller (e.g. the mulligan keep bit).
    pub reserved_bits: u32,
}

impl Query {
    /// Checks every index and size so the DP can index without bounds failures.
    ///
    /// # Errors
    /// [`Error::Invalid`] describing the first inconsistency.
    pub fn validate(&self) -> Result<()> {
        let atoms = self.counts.len();
        let checkpoints = self.batches.len();
        if checkpoints == 0 || self.retire_after.len() != checkpoints {
            return Err(invalid(
                "batches and retire_after must be non-empty and equally long",
            ));
        }
        let total = self.counts.iter().map(|&c| u64::from(c)).sum::<u64>() + u64::from(self.pool);
        if total != u64::from(self.deck_size) || self.deck_size > u32::from(u16::MAX) {
            return Err(invalid(
                "atom counts plus pool must equal a deck size below 65536",
            ));
        }
        let drawn =
            u64::from(self.hand_size) + self.batches.iter().map(|&b| u64::from(b)).sum::<u64>();
        if drawn > u64::from(self.deck_size) {
            return Err(invalid("the hand plus all draws exceed the deck"));
        }
        if self.reserved_bits as usize + self.leaves.len() > MAX_BITS as usize {
            return Err(invalid("more than 64 predicate bits"));
        }
        let in_range = |mask: &[usize]| mask.iter().all(|&i| i < atoms);
        if self
            .leaves
            .iter()
            .any(|l| l.checkpoint >= checkpoints || l.atoms().any(|i| i >= atoms))
            || self
                .observers
                .iter()
                .any(|(j, m)| *j >= checkpoints || !in_range(m))
            || self.retire_after.iter().any(|r| !in_range(r))
        {
            return Err(invalid("a checkpoint or atom index is out of range"));
        }
        Ok(())
    }

    fn max_batch(&self) -> u32 {
        self.batches.iter().copied().max().unwrap_or(0)
    }
}

/// Run options.
#[derive(Clone, Copy, Debug)]
pub struct Options {
    /// Maximum number of live states.
    pub limit: usize,
    /// Drop states whose outputs are already decided (exact).
    pub early_resolution: bool,
    /// Fold atoms that are no longer read into the pool (exact).
    pub retirement: bool,
}

/// One weighted starting state.
#[derive(Clone, Debug)]
pub struct StartState {
    /// Seen count per atom.
    pub seen: Vec<u16>,
    /// Bottomed count per atom.
    pub bottomed: Vec<u16>,
    /// Predicate bits already set.
    pub bits: u64,
    /// Weight (numerator over [`Start::denominator`]).
    pub weight: BigUint,
}

/// Caller-provided starting distribution (instead of the default opening hand).
#[derive(Clone, Debug)]
pub struct Start {
    /// The states.
    pub states: Vec<StartState>,
    /// Shared denominator of the weights.
    pub denominator: BigUint,
    /// Cards already taken from the top of the library.
    pub removed: u32,
}

/// One observer's marginal: `numerators[k] / denominator` = P(count = k).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Snapshot<W> {
    /// Index into [`Query::observers`].
    pub observer: usize,
    /// Numerator per count.
    pub numerators: Vec<W>,
    /// Denominator at that checkpoint.
    pub denominator: W,
}

/// Result of a run: `outputs[o] / denominator` per output.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Output<W> {
    /// Numerator per output.
    pub outputs: Vec<W>,
    /// Shared denominator.
    pub denominator: W,
    /// Observer marginals.
    pub snapshots: Vec<Snapshot<W>>,
    /// Largest number of live states.
    pub peak: usize,
}

impl<W: Weight> Output<W> {
    /// Converts every weight to an arbitrary-precision integer.
    #[must_use]
    pub fn to_big(&self) -> Output<BigUint> {
        Output {
            outputs: self.outputs.iter().map(Weight::to_big).collect(),
            denominator: self.denominator.to_big(),
            snapshots: self
                .snapshots
                .iter()
                .map(|s| Snapshot {
                    observer: s.observer,
                    numerators: s.numerators.iter().map(Weight::to_big).collect(),
                    denominator: s.denominator.to_big(),
                })
                .collect(),
            peak: self.peak,
        }
    }
}

/// State key: `counts = seen ++ bottomed` (length 2m) plus predicate bits.
#[derive(Clone, PartialEq, Eq, Hash)]
pub(crate) struct Key {
    pub(crate) counts: Box<[u16]>,
    pub(crate) bits: u64,
}

pub(crate) type Dist<W> = FxHashMap<Key, W>;

/// Adds `w` to the weight of `key`.
pub(crate) fn insert<W: Weight>(dist: &mut Dist<W>, key: Key, w: W) -> Result<()> {
    match dist.get_mut(&key) {
        Some(existing) => *existing = add(existing, &w)?,
        None => {
            dist.insert(key, w);
        }
    }
    Ok(())
}

/// Ways to draw a batch: `(atom counts drawn, number of such subsets)`.
pub(crate) type Draws<W> = Vec<(Vec<u16>, W)>;

/// Depth-first enumeration state for [`transitions`].
struct DrawEnumerator<'a, W> {
    binom: &'a Binom<W>,
    rem: &'a [u32],
    pool_rem: u32,
    current: Vec<u16>,
    out: Draws<W>,
}

impl<W: Weight> DrawEnumerator<'_, W> {
    /// Chooses how many cards of atom `i` (and onwards) to draw, `left` cards to go.
    fn visit(&mut self, i: usize, left: u32, coef: &W) -> Result<()> {
        if i == self.rem.len() {
            if left <= self.pool_rem {
                let c = mul(coef, &self.binom.get(self.pool_rem, left)?)?;
                if !c.is_zero() {
                    self.out.push((self.current.clone(), c));
                }
            }
            return Ok(());
        }
        for x in 0..=self.rem[i].min(left) {
            self.current[i] = x as u16;
            let c = mul(coef, &self.binom.get(self.rem[i], x)?)?;
            self.visit(i + 1, left - x, &c)?;
        }
        self.current[i] = 0;
        Ok(())
    }
}

/// All ways to draw `b` cards from atoms with `rem` cards left plus `pool_rem` pool cards:
/// `coef = prod C(rem[i], d[i]) * C(pool_rem, b - sum(d))` (sums to `C(total, b)`).
pub(crate) fn transitions<W: Weight>(
    binom: &Binom<W>,
    rem: &[u32],
    pool_rem: u32,
    b: u32,
) -> Result<Draws<W>> {
    let mut walk = DrawEnumerator {
        binom,
        rem,
        pool_rem,
        current: vec![0u16; rem.len()],
        out: Vec::new(),
    };
    walk.visit(0, b, &W::one())?;
    Ok(walk.out)
}

/// Binomial table covering every coefficient a run starting after `removed` cards needs.
pub(crate) fn binom_for<W: Weight>(q: &Query, removed: u32) -> Binom<W> {
    let max_k = removed.max(q.hand_size).max(q.max_batch());
    Binom::new(q.deck_size as usize, max_k as usize)
}

/// The default start: every opening hand of `hand_size` cards, nothing bottomed.
pub(crate) fn opening<W: Weight>(q: &Query, binom: &Binom<W>) -> Result<(Dist<W>, W)> {
    let m = q.counts.len();
    let mut dist = Dist::default();
    for (seen, c) in transitions(binom, &q.counts, q.pool, q.hand_size)? {
        let mut counts = vec![0u16; 2 * m];
        counts[..m].copy_from_slice(&seen);
        insert(
            &mut dist,
            Key {
                counts: counts.into_boxed_slice(),
                bits: 0,
            },
            c,
        )?;
    }
    Ok((dist, binom.get(q.deck_size, q.hand_size)?))
}

/// Runs `q` from the default opening hand or from `start`.
///
/// # Errors
/// [`Error::Invalid`] for a malformed query or start, [`Error::Limit`] when more than
/// `opts.limit` states are live, [`Error::Overflow`] when `W` is too small (use
/// [`crate::api::run`] for automatic big-integer fallback).
pub fn run<W: Weight>(q: &Query, start: Option<&Start>, opts: &Options) -> Result<Output<W>> {
    q.validate()?;
    let m = q.counts.len();
    let removed = start.map_or(q.hand_size, |s| s.removed);
    let binom = binom_for::<W>(q, removed);
    let (dist, denominator) = match start {
        None => opening(q, &binom)?,
        Some(s) => {
            let mut dist = Dist::default();
            for st in &s.states {
                if st.seen.len() != m || st.bottomed.len() != m {
                    return Err(invalid("start state vectors must have one entry per atom"));
                }
                let w: W = from_big(&st.weight)?;
                if w.is_zero() {
                    continue;
                }
                let counts: Vec<u16> = st.seen.iter().chain(&st.bottomed).copied().collect();
                insert(
                    &mut dist,
                    Key {
                        counts: counts.into_boxed_slice(),
                        bits: st.bits,
                    },
                    w,
                )?;
            }
            (dist, from_big(&s.denominator)?)
        }
    };
    dp(q, &binom, dist, denominator, removed, opts)
}

/// The DP proper (MATH §5). `q` must already be validated.
pub(crate) fn dp<W: Weight>(
    q: &Query,
    binom: &Binom<W>,
    dist: Dist<W>,
    denominator: W,
    removed: u32,
    opts: &Options,
) -> Result<Output<W>> {
    let mut run = Run::new(q, binom, opts, dist, denominator, removed)?;
    for checkpoint in 0..q.batches.len() {
        let batch = q.batches[checkpoint];
        if checkpoint > 0 && batch > 0 {
            run.draw(batch)?;
        }
        run.evaluate_leaves(checkpoint)?;
        run.observe(checkpoint)?;
        let last = checkpoint + 1 == q.batches.len();
        if !last {
            run.resolve_early(checkpoint)?;
            run.retire(checkpoint)?;
        }
    }
    run.finish()
}

/// The state of one DP run; each method is one phase of a checkpoint (MATH §5).
struct Run<'a, W> {
    q: &'a Query,
    binom: &'a Binom<W>,
    opts: &'a Options,
    dist: Dist<W>,
    denominator: W,
    /// Cards taken from the top of the library so far.
    removed: u32,
    /// Remaining (not yet retired) cards per atom.
    counts_left: Vec<u32>,
    /// Untracked cards, including retired atoms.
    pool: u32,
    /// Product of the batch denominators after each checkpoint.
    future_den: Vec<W>,
    /// Numerators of early-resolved true outcomes, per output.
    resolved: Vec<W>,
    snapshots: Vec<Snapshot<W>>,
    peak: usize,
}

impl<'a, W: Weight> Run<'a, W> {
    fn new(
        q: &'a Query,
        binom: &'a Binom<W>,
        opts: &'a Options,
        dist: Dist<W>,
        denominator: W,
        removed: u32,
    ) -> Result<Self> {
        let all_draws: u32 = q.batches.iter().sum();
        if removed + all_draws > q.deck_size {
            return Err(invalid("draws exceed the library"));
        }
        let mut future_den: Vec<W> = vec![W::one(); q.batches.len()];
        let mut removed_before = removed + all_draws;
        for j in (1..q.batches.len()).rev() {
            removed_before -= q.batches[j];
            let den = binom.get(q.deck_size - removed_before, q.batches[j])?;
            future_den[j - 1] = mul(&future_den[j], &den)?;
        }
        let peak = dist.len();
        if peak > opts.limit {
            return Err(Error::Limit(peak));
        }
        Ok(Run {
            q,
            binom,
            opts,
            dist,
            denominator,
            removed,
            counts_left: q.counts.clone(),
            pool: q.pool,
            future_den,
            resolved: vec![W::zero(); q.outputs.len()],
            snapshots: Vec::new(),
            peak,
        })
    }

    fn atoms(&self) -> usize {
        self.q.counts.len()
    }

    /// Draws `batch` cards: convolves every state with the multivariate hypergeometric
    /// numerators of the remaining library (MATH §5.1).
    fn draw(&mut self, batch: u32) -> Result<()> {
        let atoms = self.atoms();
        let mut cache: FxHashMap<(Vec<u32>, u32), Draws<W>> = FxHashMap::default();
        let mut next: Dist<W> = FxHashMap::default();
        next.reserve(self.dist.len() * 2);
        for (key, weight) in &self.dist {
            let (seen, bottomed) = key.counts.split_at(atoms);
            let rem: Vec<u32> = (0..atoms)
                .map(|i| self.counts_left[i] - u32::from(seen[i]) - u32::from(bottomed[i]))
                .collect();
            let taken: u32 = key.counts.iter().map(|&x| u32::from(x)).sum();
            let pool_rem = self.pool - (self.removed - taken);
            let cache_key = (rem, pool_rem);
            if !cache.contains_key(&cache_key) {
                let draws = transitions(self.binom, &cache_key.0, pool_rem, batch)?;
                cache.insert(cache_key.clone(), draws);
            }
            for (drawn, ways) in &cache[&cache_key] {
                let mut counts = key.counts.clone();
                for (slot, &x) in counts.iter_mut().zip(drawn) {
                    *slot += x;
                }
                insert(
                    &mut next,
                    Key {
                        counts,
                        bits: key.bits,
                    },
                    mul(weight, ways)?,
                )?;
            }
        }
        self.dist = next;
        let den = self.binom.get(self.q.deck_size - self.removed, batch)?;
        self.denominator = mul(&self.denominator, &den)?;
        self.removed += batch;
        self.peak = self.peak.max(self.dist.len());
        if self.dist.len() > self.opts.limit {
            return Err(Error::Limit(self.dist.len()));
        }
        Ok(())
    }

    /// Sets the bits of the leaves evaluated at `checkpoint` (equal keys merge).
    fn evaluate_leaves(&mut self, checkpoint: usize) -> Result<()> {
        let here: Vec<&Leaf> = self
            .q
            .leaves
            .iter()
            .filter(|l| l.checkpoint == checkpoint)
            .collect();
        if here.is_empty() {
            return Ok(());
        }
        let atoms = self.atoms();
        let mut evaluated: Dist<W> = FxHashMap::default();
        for (key, weight) in self.dist.drain() {
            let bits = key.bits | leaf_bits(here.iter().copied(), &key.counts[..atoms]);
            insert(
                &mut evaluated,
                Key {
                    counts: key.counts,
                    bits,
                },
                weight,
            )?;
        }
        self.dist = evaluated;
        Ok(())
    }

    /// Records the marginals of the observers at `checkpoint`.
    fn observe(&mut self, checkpoint: usize) -> Result<()> {
        for (index, (at, mask)) in self.q.observers.iter().enumerate() {
            if *at != checkpoint {
                continue;
            }
            let mut numerators: Vec<W> = vec![W::zero()];
            for (key, weight) in &self.dist {
                let k: usize = mask.iter().map(|&i| usize::from(key.counts[i])).sum();
                if numerators.len() <= k {
                    numerators.resize(k + 1, W::zero());
                }
                numerators[k] = add(&numerators[k], weight)?;
            }
            self.snapshots.push(Snapshot {
                observer: index,
                numerators,
                denominator: self.denominator.clone(),
            });
        }
        Ok(())
    }

    /// Moves states whose outputs are already decided into `resolved`, scaled by the
    /// remaining batch denominators (exact by Vandermonde; MATH §5.3).
    fn resolve_early(&mut self, checkpoint: usize) -> Result<()> {
        let observers_done = self.q.observers.iter().all(|(at, _)| *at <= checkpoint);
        if !self.opts.early_resolution || self.q.outputs.is_empty() || !observers_done {
            return Ok(());
        }
        let n_known = self.q.reserved_bits as usize
            + self
                .q
                .leaves
                .iter()
                .filter(|l| l.checkpoint <= checkpoint)
                .count();
        let known: u64 = if n_known >= 64 {
            u64::MAX
        } else {
            (1u64 << n_known) - 1
        };
        let mut kept: Dist<W> = FxHashMap::default();
        for (key, weight) in self.dist.drain() {
            let verdicts: Option<Vec<bool>> = self
                .q
                .outputs
                .iter()
                .map(|p| p.eval3(key.bits, known))
                .collect();
            match verdicts {
                None => insert(&mut kept, key, weight)?,
                Some(verdicts) => {
                    for (slot, holds) in self.resolved.iter_mut().zip(verdicts) {
                        if holds {
                            *slot = add(slot, &mul(&weight, &self.future_den[checkpoint])?)?;
                        }
                    }
                }
            }
        }
        self.dist = kept;
        Ok(())
    }

    /// Folds atoms that no later checkpoint reads into the pool (exact; MATH §5.3).
    fn retire(&mut self, checkpoint: usize) -> Result<()> {
        let gone = &self.q.retire_after[checkpoint];
        if !self.opts.retirement || gone.is_empty() {
            return Ok(());
        }
        let atoms = self.atoms();
        for &i in gone {
            self.pool += self.counts_left[i];
            self.counts_left[i] = 0;
        }
        let mut folded: Dist<W> = FxHashMap::default();
        for (mut key, weight) in self.dist.drain() {
            for &i in gone {
                key.counts[i] = 0;
                key.counts[atoms + i] = 0;
            }
            insert(&mut folded, key, weight)?;
        }
        self.dist = folded;
        Ok(())
    }

    /// Evaluates every output on the surviving states.
    fn finish(mut self) -> Result<Output<W>> {
        for (key, weight) in &self.dist {
            for (slot, program) in self.resolved.iter_mut().zip(&self.q.outputs) {
                if program.eval(key.bits) {
                    *slot = add(slot, weight)?;
                }
            }
        }
        Ok(Output {
            outputs: self.resolved,
            denominator: self.denominator,
            snapshots: self.snapshots,
            peak: self.peak,
        })
    }
}

#[cfg(test)]
pub(crate) mod tests {
    use super::*;

    /// A query over one atom of `k` cards in an `n`-card deck: `count >= at_least` by
    /// the given checkpoint batches.
    pub(crate) fn single_atom(
        n: u32,
        k: u32,
        hand: u32,
        batches: Vec<u32>,
        at_least: u32,
    ) -> Query {
        let checkpoints = batches.len();
        Query {
            deck_size: n,
            counts: vec![k],
            pool: n - k,
            hand_size: hand,
            batches,
            leaves: vec![
                Leaf::new(0, checkpoints - 1, 0, vec![0], 5, at_least, 0, 0, vec![], 1).unwrap(),
            ],
            outputs: vec![Program::new(vec![0, 0]).unwrap()],
            observers: vec![(checkpoints - 1, vec![0])],
            retire_after: vec![vec![]; checkpoints],
            reserved_bits: 0,
        }
    }

    pub(crate) const OPTS: Options = Options {
        limit: 1_000_000,
        early_resolution: true,
        retirement: true,
    };

    fn binom_u(n: u128, k: u128) -> u128 {
        (0..k).fold(1, |acc, i| acc * (n - i) / (i + 1))
    }

    /// Reference A1 (MATH §12): P(at least 1 of 4 copies in 7 of 60).
    #[test]
    fn hypergeometric_reference_value() {
        let out: Output<u128> = run(&single_atom(60, 4, 7, vec![0], 1), None, &OPTS).unwrap();
        assert_eq!(out.denominator, binom_u(60, 7));
        assert_eq!(out.outputs[0], binom_u(60, 7) - binom_u(56, 7));
        let pmf_total: u128 = out.snapshots[0].numerators.iter().sum();
        assert_eq!(pmf_total, out.denominator);
    }

    /// Reference A4: on the draw by turn 3 = 10 cards seen, in batches.
    #[test]
    fn batches_equal_one_big_draw() {
        let batched: Output<u128> =
            run(&single_atom(60, 4, 7, vec![0, 1, 1, 1], 1), None, &OPTS).unwrap();
        let direct: Output<u128> = run(&single_atom(60, 4, 10, vec![0], 1), None, &OPTS).unwrap();
        assert_eq!(
            batched.outputs[0] * direct.denominator,
            direct.outputs[0] * batched.denominator
        );
    }

    #[test]
    fn optimizations_do_not_change_results() {
        let mut q = single_atom(40, 17, 7, vec![0, 2, 1, 3], 4);
        q.observers.clear();
        let base: Output<u128> = run(
            &q,
            None,
            &Options {
                early_resolution: false,
                retirement: false,
                ..OPTS
            },
        )
        .unwrap();
        for (early, retire) in [(true, false), (false, true), (true, true)] {
            let o: Output<u128> = run(
                &q,
                None,
                &Options {
                    early_resolution: early,
                    retirement: retire,
                    ..OPTS
                },
            )
            .unwrap();
            assert_eq!(
                o.outputs[0] * base.denominator,
                base.outputs[0] * o.denominator
            );
        }
    }

    #[test]
    fn limit_and_validation_errors() {
        let q = single_atom(60, 24, 7, vec![0, 3], 2);
        assert!(matches!(
            run::<u128>(&q, None, &Options { limit: 1, ..OPTS }),
            Err(Error::Limit(_))
        ));
        let mut bad = q.clone();
        bad.pool += 1;
        assert!(matches!(
            run::<u128>(&bad, None, &OPTS),
            Err(Error::Invalid(_))
        ));
        let mut bad = q;
        bad.batches = vec![0, 60];
        assert!(matches!(
            run::<u128>(&bad, None, &OPTS),
            Err(Error::Invalid(_))
        ));
    }

    #[test]
    fn u128_overflow_is_reported() {
        let q = single_atom(
            250,
            100,
            7,
            vec![0; 1].into_iter().chain([10; 20]).collect(),
            50,
        );
        assert_eq!(run::<u128>(&q, None, &OPTS), Err(Error::Overflow));
        assert!(run::<BigUint>(&q, None, &OPTS).is_ok());
    }
}
