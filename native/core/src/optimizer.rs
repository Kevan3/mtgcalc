//! The card-count optimizer (port of `mtgcalc.analysis.optimizer`, port stage 5,
//! FR-50 – FR-54, MATH §10), single-threaded (Python's thread batching only changes
//! timing; with one worker it evaluates exactly the same points in the same order).
//!
//! Vocabulary: a *point* assigns a count to every variable; the *cap* is the most cards
//! the variables may use together; a *slice* is every point with one total; *monotone*
//! means adding a copy of a variable (removing a filler card) never lowers P.

use std::collections::HashMap;

use crate::analysis::{exact_values, prepare};
use crate::error::{validation, Error, Result};
use crate::model::conditions::Cond;
use crate::model::deck::Card;
use crate::model::{
    Condition, Deck, GameConfig, MulliganConfig, Op, Query, Scenario, Selector, Zone,
};
use crate::probability::Fraction;

/// Name of the cards that belong to no category (Python's `FILLER_NAME`).
pub const FILLER: &str = "(other)";

/// A category whose count the optimizer chooses, within `lo..=hi`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Variable {
    name: String,
    lo: u64,
    hi: u64,
    tags: Vec<String>,
}

impl Variable {
    /// # Errors
    /// A validation error unless `0 <= lo <= hi` (Python's message).
    pub fn new(name: &str, lo: i64, hi: i64, tags: Vec<String>) -> Result<Self> {
        match (u64::try_from(lo), u64::try_from(hi)) {
            (Ok(lo), Ok(hi)) if lo <= hi => Ok(Variable {
                name: name.to_owned(),
                lo,
                hi,
                tags,
            }),
            _ => Err(validation(
                format!("variable[{name}]"),
                "requires 0 <= lo <= hi",
            )),
        }
    }
}

/// A category with a fixed count (Python's `Category`).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Category {
    count: u64,
    tags: Vec<String>,
}

impl Category {
    /// # Errors
    /// A validation error for a negative count.
    pub fn new(count: i64, tags: Vec<String>) -> Result<Self> {
        let count = u64::try_from(count)
            .map_err(|_| validation("category.count", "must be non-negative"))?;
        Ok(Category { count, tags })
    }
}

/// What to optimize.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Objective {
    /// Fewest copies of the one variable reaching the target.
    MinCount,
    /// Highest probability within the cap.
    MaxProbability,
    /// Smallest total whose best split reaches the target.
    MinTotal,
}

/// An optimization problem over category counts (Python's `OptimizeProblem`).
#[derive(Clone, Debug)]
pub struct OptimizeProblem {
    /// Cards in the library.
    pub deck_size: u64,
    /// The categories whose counts are chosen.
    pub variables: Vec<Variable>,
    /// The question (no `given`).
    pub query: Query,
    /// Categories with fixed counts.
    pub fixed: Vec<(String, Category)>,
    /// How many cards are seen when.
    pub game: GameConfig,
    /// The mulligan, if modelled.
    pub mulligan: Option<MulliganConfig>,
    /// What to optimize.
    pub objective: Objective,
    /// The target probability (required for `MinCount` and `MinTotal`).
    pub target: Option<Fraction>,
    /// Most cards the variables may use together (besides the room left by `fixed`).
    pub budget: Option<u64>,
    /// Largest number of candidates searched exhaustively.
    pub exhaustive_limit: u64,
    /// Overrides the syntactic monotonicity test.
    pub assume_monotone: Option<bool>,
}

/// Python's `OptimizeProblem.__post_init__` checks, in order.
///
/// # Errors
/// A validation error naming the first problem.
pub fn validate(p: &OptimizeProblem, workers: Option<i64>, budget: Option<i64>) -> Result<()> {
    if p.variables.is_empty() {
        return Err(validation(
            "optimize.variables",
            "at least one variable is required",
        ));
    }
    let mut names: Vec<&str> = p.variables.iter().map(|v| v.name.as_str()).collect();
    names.extend(p.fixed.iter().map(|(n, _)| n.as_str()));
    let mut sorted = names.clone();
    sorted.sort_unstable();
    sorted.dedup();
    if sorted.len() != names.len() {
        return Err(validation(
            "optimize.variables",
            "category names must be unique",
        ));
    }
    if matches!(p.objective, Objective::MinCount | Objective::MinTotal) && p.target.is_none() {
        let name = if p.objective == Objective::MinCount {
            "min_count"
        } else {
            "min_total"
        };
        return Err(validation(
            "optimize.target",
            format!("required for objective {name}"),
        ));
    }
    if p.objective == Objective::MinCount && p.variables.len() != 1 {
        return Err(validation(
            "optimize.variables",
            "min_count takes exactly one variable",
        ));
    }
    if p.query.given.is_some() {
        return Err(validation(
            "optimize.query",
            "conditional queries are not supported",
        ));
    }
    if budget.is_some_and(|b| b < 0) {
        return Err(validation("optimize.budget", "must be non-negative"));
    }
    if workers.is_some_and(|w| w < 1) {
        return Err(validation("optimize.workers", "must be at least 1"));
    }
    Ok(())
}

/// The cards being searched over were refused (Python's `InfeasibleError`).
fn infeasible(why: impl Into<String>) -> Error {
    Error::Infeasible(why.into())
}

/// Python's `f"{float(p):.2%}"`, from the exact value (ties to even).
fn percent2(p: &Fraction) -> String {
    use num_bigint::BigUint;
    use num_integer::Integer;
    let scaled = p.numerator() * BigUint::from(10_000u32);
    let (q, r) = scaled.div_rem(p.denominator());
    let twice = r * 2u8;
    let q = if twice > *p.denominator() || (twice == *p.denominator() && q.is_odd()) {
        q + 1u8
    } else {
        q
    };
    let (whole, frac) = q.div_rem(&BigUint::from(100u8));
    format!("{whole}.{frac:0>2}%")
}

type Point = Vec<u64>;

impl OptimizeProblem {
    /// The cap: the room left after the fixed categories, further limited by the budget.
    #[must_use]
    pub fn max_total(&self) -> u64 {
        let room = self
            .deck_size
            .saturating_sub(self.fixed.iter().map(|(_, c)| c.count).sum());
        self.budget.map_or(room, |b| room.min(b))
    }

    /// Python's `build_deck` (`Deck.from_counts`): fixed categories, then the variables,
    /// one card each with its own name as a tag, then the filler.
    fn deck(&self, counts: &[u64]) -> Result<Deck> {
        let mut cats: Vec<(&str, u64, &[String])> = self
            .fixed
            .iter()
            .map(|(n, c)| (n.as_str(), c.count, c.tags.as_slice()))
            .collect();
        for (v, &c) in self.variables.iter().zip(counts) {
            cats.push((&v.name, c, &v.tags));
        }
        let total: u64 = cats.iter().map(|(_, c, _)| c).sum();
        if total > self.deck_size {
            return Err(validation(
                "categories",
                format!("total {total} exceeds deck size {}", self.deck_size),
            ));
        }
        let mut cards = Vec::new();
        for (name, count, tags) in cats {
            if count > 0 {
                let mut all: Vec<String> = vec![name.to_owned()];
                all.extend(tags.iter().cloned());
                cards.push(Card::new(
                    name,
                    i64::try_from(count).unwrap_or(i64::MAX),
                    &all,
                    Zone::Library,
                )?);
            }
        }
        if self.deck_size > total {
            let rest = i64::try_from(self.deck_size - total).unwrap_or(i64::MAX);
            cards.push(Card::new(
                FILLER,
                rest,
                &[FILLER.to_owned()],
                Zone::Library,
            )?);
        }
        Deck::new(cards)
    }

    /// Whether adding a copy of `var` can never lower P (sufficient test, MATH §10.2).
    fn is_monotone(&self, var: &Variable) -> Result<bool> {
        if let Some(assumed) = self.assume_monotone {
            return Ok(assumed);
        }
        if self.mulligan.is_some() {
            return Ok(false);
        }
        let mut tags = vec![var.name.clone()];
        tags.extend(var.tags.iter().cloned());
        let var_card = Card::new(&var.name, 1, &tags, Zone::Library)?;
        let filler = Card::new(FILLER, 1, &[FILLER.to_owned()], Zone::Library)?;
        Ok(monotone(&self.query.condition, true, &var_card, &filler))
    }
}

/// Whether a leaf's selector reads `var` or the filler.
fn reads(c: &Condition, var: &Card, filler: &Card) -> bool {
    let hit = |s: &Selector| s.matches(var) || s.matches(filler);
    match &c.0 {
        Cond::Compare { sel, .. } | Cond::Between { sel, .. } => hit(sel),
        Cond::Assignable(ds) => ds.iter().any(|d| hit(&d.sel)),
        _ => false,
    }
}

fn reads_anywhere(c: &Condition, var: &Card, filler: &Card) -> bool {
    reads(c, var, filler)
        || c.children()
            .into_iter()
            .any(|ch| reads_anywhere(ch, var, filler))
}

/// Python's `is_monotone.ok`: is `c` non-decreasing (positive) / non-increasing in var?
fn monotone(c: &Condition, positive: bool, var: &Card, filler: &Card) -> bool {
    match &c.0 {
        Cond::Compare { sel, op, .. } => {
            if sel.matches(filler) {
                return false;
            }
            !sel.matches(var) || (positive && matches!(op, Op::Ge | Op::Gt))
        }
        Cond::Between { sel, .. } => !sel.matches(filler) && !sel.matches(var),
        Cond::Assignable(ds) => {
            if ds.iter().any(|d| d.sel.matches(filler)) {
                return false;
            }
            positive || !ds.iter().any(|d| d.sel.matches(var))
        }
        Cond::And(items) | Cond::Or(items) | Cond::AtLeast(_, items) => {
            items.iter().all(|i| monotone(i, positive, var, filler))
        }
        Cond::Not(item) => monotone(item, !positive, var, filler),
        Cond::Implies(a, b) => {
            monotone(a, !positive, var, filler) && monotone(b, positive, var, filler)
        }
        Cond::At(_, item) => monotone(item, positive, var, filler),
        Cond::Const(_) => true,
        Cond::Xor(..) | Cond::Exactly(..) => !reads_anywhere(c, var, filler),
    }
}

/// Points within the bounds with sum `<= cap` (and `== total` if given), in Python's
/// order, pruning branches that cannot reach the required sum.
fn points(vs: &[Variable], cap: u64, total: Option<u64>) -> Vec<Point> {
    let n = vs.len();
    let mut walk = PointWalk {
        vs,
        lo_rest: (0..=n)
            .map(|i| vs[i..].iter().map(|v| v.lo).sum())
            .collect(),
        hi_rest: (0..=n)
            .map(|i| vs[i..].iter().map(|v| v.hi).sum())
            .collect(),
        bound: total.map_or(cap, |t| cap.min(t)),
        total,
        x: vec![0; n],
        out: Vec::new(),
    };
    walk.visit(0, 0);
    walk.out
}

/// Depth-first enumeration state for [`points`].
struct PointWalk<'a> {
    vs: &'a [Variable],
    lo_rest: Vec<u64>,
    hi_rest: Vec<u64>,
    bound: u64,
    total: Option<u64>,
    x: Point,
    out: Vec<Point>,
}

impl PointWalk<'_> {
    fn visit(&mut self, i: usize, used: u64) {
        if i == self.vs.len() {
            self.out.push(self.x.clone());
            return;
        }
        for c in self.vs[i].lo..=self.vs[i].hi {
            let s = used + c;
            if s + self.lo_rest[i + 1] > self.bound {
                break;
            }
            if self.total.is_some_and(|t| s + self.hi_rest[i + 1] < t) {
                continue;
            }
            self.x[i] = c;
            self.visit(i + 1, s);
        }
    }
}

/// How many points [`points`] yields, by dynamic programming over the sum.
fn count_points(vs: &[Variable], cap: u64, total: Option<u64>) -> u128 {
    let mut ways: HashMap<u64, u128> = HashMap::from([(0, 1)]);
    for v in vs {
        let mut next: HashMap<u64, u128> = HashMap::new();
        for (&s, &w) in &ways {
            for c in v.lo..=v.hi {
                if s + c > cap {
                    break;
                }
                *next.entry(s + c).or_insert(0) += w;
            }
        }
        ways = next;
    }
    match total {
        Some(t) => ways.get(&t).copied().unwrap_or(0),
        None => ways.values().sum(),
    }
}

/// Python's `_rank`: higher P, then fewer cards, then smaller counts first.
fn better(a: (&Point, &Fraction), b: (&Point, &Fraction)) -> bool {
    use std::cmp::Ordering;
    match a.1.cmp(b.1) {
        Ordering::Greater => true,
        Ordering::Less => false,
        Ordering::Equal => {
            let (sa, sb): (u64, u64) = (a.0.iter().sum(), b.0.iter().sum());
            if sa != sb {
                return sa < sb;
            }
            a.0 < b.0
        }
    }
}

/// Memoized P(point).
struct Memo<'a> {
    problem: &'a OptimizeProblem,
    limit: usize,
    values: HashMap<Point, Fraction>,
}

impl Memo<'_> {
    fn eval(&mut self, point: &Point) -> Result<Fraction> {
        if let Some(p) = self.values.get(point) {
            return Ok(p.clone());
        }
        let pr = self.problem;
        let scenario = Scenario {
            deck: pr.deck(point)?,
            game: pr.game.clone(),
            mulligan: pr.mulligan.clone(),
        };
        let prep = prepare(
            &scenario,
            &[("p".to_owned(), pr.query.condition.clone())],
            pr.query.turn,
            &[],
        )?;
        let p = exact_values(&prep, self.limit)?
            .into_iter()
            .next()
            .ok_or_else(|| Error::Invalid("no output".into()))?;
        self.values.insert(point.clone(), p.clone());
        Ok(p)
    }

    /// The first point with the highest value (Python's `max(..., key=value)`).
    fn best_of(&mut self, moves: &[Point]) -> Result<Option<(Point, Fraction)>> {
        let mut best: Option<(Point, Fraction)> = None;
        for m in moves {
            let v = self.eval(m)?;
            if best.as_ref().map_or(true, |(_, b)| v > *b) {
                best = Some((m.clone(), v));
            }
        }
        Ok(best)
    }
}

/// The optimizer's answer (Python's `OptimizeResult`).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OptimizeResult {
    /// The chosen count of each variable.
    pub counts: Vec<(String, u64)>,
    /// P at the chosen counts.
    pub probability: Fraction,
    /// Whether the answer is proven best (exhaustive search or monotone bisection).
    pub proven_optimal: bool,
    /// Distinct points evaluated.
    pub evaluations: usize,
    /// The 20 best points evaluated, best first.
    pub frontier: Vec<(Vec<(String, u64)>, Fraction)>,
}

/// The chance with one card fewer than `chosen` of the only variable (the desktop app's
/// `_one_fewer`): `None` when `chosen` is already the lowest count tried.
///
/// # Errors
/// [`Error::Invalid`] unless the problem has exactly one variable; engine errors.
pub fn one_fewer(problem: &OptimizeProblem, chosen: u64, limit: usize) -> Result<Option<Fraction>> {
    let [var] = problem.variables.as_slice() else {
        return Err(Error::Invalid(
            "one fewer needs exactly one variable".to_owned(),
        ));
    };
    if chosen <= var.lo {
        return Ok(None);
    }
    let smaller = OptimizeProblem {
        variables: vec![Variable {
            lo: chosen - 1,
            hi: chosen - 1,
            ..var.clone()
        }],
        objective: Objective::MaxProbability,
        target: None,
        ..problem.clone()
    };
    Ok(Some(optimize(&smaller, limit)?.probability))
}

/// Solves `problem` (Python's `optimize` with one worker).
///
/// # Errors
/// [`Error::Infeasible`] when no assignment can work (Python's messages); validation and
/// engine errors.
pub fn optimize(problem: &OptimizeProblem, limit: usize) -> Result<OptimizeResult> {
    if problem.variables.iter().map(|v| v.lo).sum::<u64>() > problem.max_total() {
        return Err(infeasible(
            "the variables' lower bounds already exceed the cap",
        ));
    }
    let mut f = Memo {
        problem,
        limit,
        values: HashMap::new(),
    };
    let (best, proven) = match problem.objective {
        Objective::MinCount => min_count(problem, &mut f)?,
        Objective::MaxProbability => max_probability(problem, &mut f)?,
        Objective::MinTotal => min_total(problem, &mut f)?,
    };
    let label = |c: &Point| -> Vec<(String, u64)> {
        problem
            .variables
            .iter()
            .zip(c)
            .map(|(v, &n)| (v.name.clone(), n))
            .collect()
    };
    let mut ranked: Vec<(&Point, &Fraction)> = f.values.iter().collect();
    ranked.sort_by(|a, b| {
        if better(*a, *b) {
            std::cmp::Ordering::Less
        } else if better(*b, *a) {
            std::cmp::Ordering::Greater
        } else {
            std::cmp::Ordering::Equal
        }
    });
    let frontier = ranked
        .iter()
        .take(20)
        .map(|(c, p)| (label(c), (*p).clone()))
        .collect();
    let probability = f.eval(&best)?;
    Ok(OptimizeResult {
        counts: label(&best),
        probability,
        proven_optimal: proven,
        evaluations: f.values.len(),
        frontier,
    })
}

fn all_monotone(problem: &OptimizeProblem) -> Result<bool> {
    for v in &problem.variables {
        if !problem.is_monotone(v)? {
            return Ok(false);
        }
    }
    Ok(true)
}

fn min_count(problem: &OptimizeProblem, f: &mut Memo<'_>) -> Result<(Point, bool)> {
    let var = &problem.variables[0];
    let target = problem.target.clone().unwrap_or_else(Fraction::zero);
    let (mut lo, mut hi) = (var.lo, var.hi.min(problem.max_total()));
    if problem.is_monotone(var)? {
        let top = f.eval(&vec![hi])?;
        if top < target {
            return Err(infeasible(format!(
                "even {hi} copies reach only {}",
                percent2(&top)
            )));
        }
        while lo < hi {
            let mid = (lo + hi) / 2;
            if f.eval(&vec![mid])? >= target {
                hi = mid;
            } else {
                lo = mid + 1;
            }
        }
        return Ok((vec![lo], true));
    }
    for c in lo..=hi {
        if f.eval(&vec![c])? >= target {
            return Ok((vec![c], true));
        }
    }
    Err(infeasible("no count in the range reaches the target"))
}

fn best_on(
    problem: &OptimizeProblem,
    f: &mut Memo<'_>,
    total: Option<u64>,
) -> Result<(Point, bool)> {
    let (vs, cap) = (&problem.variables, problem.max_total());
    let n = count_points(vs, cap, total);
    if n == 0 {
        return Err(infeasible("no assignment satisfies the bounds"));
    }
    if n <= u128::from(problem.exhaustive_limit) {
        let mut best: Option<(Point, Fraction)> = None;
        for p in points(vs, cap, total) {
            let v = f.eval(&p)?;
            if best
                .as_ref()
                .map_or(true, |(bp, bv)| better((&p, &v), (bp, bv)))
            {
                best = Some((p, v));
            }
        }
        return best
            .map(|(p, _)| (p, true))
            .ok_or_else(|| infeasible("no assignment satisfies the bounds"));
    }
    Ok((local_search(problem, f, total)?, false))
}

fn max_probability(problem: &OptimizeProblem, f: &mut Memo<'_>) -> Result<(Point, bool)> {
    if all_monotone(problem)? {
        let full = problem
            .max_total()
            .min(problem.variables.iter().map(|v| v.hi).sum());
        return best_on(problem, f, Some(full));
    }
    best_on(problem, f, None)
}

fn min_total(problem: &OptimizeProblem, f: &mut Memo<'_>) -> Result<(Point, bool)> {
    let target = problem.target.clone().unwrap_or_else(Fraction::zero);
    let mut lo: u64 = problem.variables.iter().map(|v| v.lo).sum();
    let mut hi = problem
        .max_total()
        .min(problem.variables.iter().map(|v| v.hi).sum());
    let mut proven = true;
    let best = |f: &mut Memo<'_>, total: u64, proven: &mut bool| -> Result<Point> {
        let (point, exact) = best_on(problem, f, Some(total))?;
        *proven = *proven && exact;
        Ok(point)
    };
    if all_monotone(problem)? {
        let top = best(f, hi, &mut proven)?;
        let top_p = f.eval(&top)?;
        if top_p < target {
            return Err(infeasible(format!(
                "even a total of {hi} reaches only {}",
                percent2(&top_p)
            )));
        }
        let mut answer = top;
        while lo < hi {
            let mid = (lo + hi) / 2;
            let point = best(f, mid, &mut proven)?;
            if f.eval(&point)? >= target {
                hi = mid;
                answer = point;
            } else {
                lo = mid + 1;
            }
        }
        return Ok((answer, proven));
    }
    for total in lo..=hi {
        let point = best(f, total, &mut proven)?;
        if f.eval(&point)? >= target {
            return Ok((point, proven));
        }
    }
    Err(infeasible(
        "no assignment within the bounds reaches the target",
    ))
}

fn bump(x: &[u64], i: usize, up: bool) -> Point {
    let mut y = x.to_vec();
    y[i] = if up { y[i] + 1 } else { y[i] - 1 };
    y
}

/// Python's `_local_search`: greedy ascent from the lower bounds, then "move one card
/// from variable j to variable i" steps until nothing improves.
fn local_search(problem: &OptimizeProblem, f: &mut Memo<'_>, total: Option<u64>) -> Result<Point> {
    let vs = &problem.variables;
    let cap = total.unwrap_or_else(|| problem.max_total());
    let mut x: Point = vs.iter().map(|v| v.lo).collect();
    while x.iter().sum::<u64>() < cap {
        let moves: Vec<Point> = (0..vs.len())
            .filter(|&i| x[i] < vs[i].hi)
            .map(|i| bump(&x, i, true))
            .collect();
        let Some((next, value)) = f.best_of(&moves)? else {
            break;
        };
        if total.is_none() && value <= f.eval(&x)? {
            break;
        }
        x = next;
    }
    if let Some(t) = total {
        if x.iter().sum::<u64>() != t {
            return Err(infeasible(format!(
                "cannot reach a total of {t} within the bounds"
            )));
        }
    }
    loop {
        let mut moves = Vec::new();
        for i in 0..vs.len() {
            for j in 0..vs.len() {
                if i != j && x[i] < vs[i].hi && x[j] > vs[j].lo {
                    moves.push(bump(&bump(&x, i, true), j, false));
                }
            }
        }
        let Some((next, value)) = f.best_of(&moves)? else {
            return Ok(x);
        };
        if value <= f.eval(&x)? {
            return Ok(x);
        }
        x = next;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tag(t: &str) -> Selector {
        Selector::tag(t).unwrap()
    }

    fn problem(
        objective: Objective,
        vars: Vec<Variable>,
        cond: Condition,
        target: Option<(u64, u64)>,
    ) -> OptimizeProblem {
        OptimizeProblem {
            deck_size: 60,
            variables: vars,
            query: Query::new(cond, None, 4).unwrap(),
            fixed: vec![],
            game: GameConfig::default(),
            mulligan: None,
            objective,
            target: target.map(|(n, d)| Fraction::new(n.into(), d.into())),
            budget: None,
            exhaustive_limit: 5000,
            assume_monotone: None,
        }
    }

    #[test]
    fn min_count_finds_the_fewest_lands_by_bisection() {
        let p = problem(
            Objective::MinCount,
            vec![Variable::new("land", 14, 30, vec![]).unwrap()],
            Condition::compare(tag("land"), Op::Ge, 4).unwrap(),
            Some((8, 10)),
        );
        let r = optimize(&p, 2_000_000).unwrap();
        let n = r.counts[0].1;
        let mut f = Memo {
            problem: &p,
            limit: 2_000_000,
            values: HashMap::new(),
        };
        assert!(f.eval(&vec![n]).unwrap() >= Fraction::new(8u8.into(), 10u8.into()));
        assert!(f.eval(&vec![n - 1]).unwrap() < Fraction::new(8u8.into(), 10u8.into()));
        assert!(r.proven_optimal);
    }

    #[test]
    fn monotonicity_follows_python() {
        let land = Variable::new("land", 0, 10, vec![]).unwrap();
        let ge = Condition::compare(tag("land"), Op::Ge, 4).unwrap();
        let le = Condition::compare(tag("land"), Op::Le, 4).unwrap();
        let other = Condition::compare(tag(FILLER), Op::Ge, 1).unwrap();
        let p = |c: Condition| problem(Objective::MaxProbability, vec![land.clone()], c, None);
        assert!(p(ge.clone()).is_monotone(&land).unwrap());
        assert!(!p(le.clone()).is_monotone(&land).unwrap());
        // Python's test is sufficient, not exact: "<=" never counts, even negated.
        assert!(!p(Condition::not(le)).is_monotone(&land).unwrap());
        assert!(!p(other).is_monotone(&land).unwrap());
        assert!(!p(Condition::xor(ge.clone(), Condition::constant(true)))
            .is_monotone(&land)
            .unwrap());
        assert!(p(Condition::implies(Condition::constant(true), ge))
            .is_monotone(&land)
            .unwrap());
    }

    #[test]
    fn points_and_counts_agree() {
        let vs = vec![
            Variable::new("a", 1, 4, vec![]).unwrap(),
            Variable::new("b", 0, 3, vec![]).unwrap(),
        ];
        for cap in 0..9 {
            assert_eq!(
                points(&vs, cap, None).len() as u128,
                count_points(&vs, cap, None)
            );
            for t in 0..9 {
                let ps = points(&vs, cap, Some(t));
                assert_eq!(
                    ps.len() as u128,
                    count_points(&vs, cap, Some(t)),
                    "cap {cap} total {t}"
                );
                assert!(ps.iter().all(|p| p.iter().sum::<u64>() == t));
            }
        }
    }

    #[test]
    fn infeasible_targets_are_reported_like_python() {
        let p = problem(
            Objective::MinCount,
            vec![Variable::new("land", 18, 20, vec![]).unwrap()],
            Condition::compare(tag("land"), Op::Ge, 7).unwrap(),
            Some((99, 100)),
        );
        let e = optimize(&p, 2_000_000).unwrap_err();
        assert!(
            matches!(&e, Error::Infeasible(m) if m.starts_with("even 20 copies reach only ") && m.ends_with('%'))
        );
        assert_eq!(percent2(&Fraction::new(1u8.into(), 8u8.into())), "12.50%");
        assert_eq!(percent2(&Fraction::new(1u8.into(), 3u8.into())), "33.33%");
    }
}
