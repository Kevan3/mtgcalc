//! The JSON boundary (feature `json`, ADR-0013 §3).
//!
//! Requests and responses use the format of `mtgcalc.model.serialization.to_dict`, so
//! Python can send any scenario unchanged and compare answers as JSON:
//!
//! ```json
//! {"scenario": {"type": "Scenario", "deck": {...}, "game": {...}, "mulligan": null},
//!  "query": {"type": "Query", "condition": {...}, "given": null, "turn": 3},
//!  "limit": 2000000}
//! ```
//!
//! The answer is a `Probability` or `ConditionalResult` exactly as Python serializes it,
//! or an error object `{"type": "Error", "kind", "field", "message"}` where `kind` is
//! `validation`, `too_large`, `unsupported`, `malformed` or `internal`.
//!
//! Missing fields take Python's dataclass defaults; unknown fields, non-integer counts
//! and integers beyond 64 bits are `malformed`. Parsing builds data-transfer types,
//! which are then converted into the validated model types: validation happens once,
//! with Python's rules and messages.

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use crate::analysis;
use crate::error::validation;
use crate::error::Error;
use crate::io::{format_query, parse_condition, parse_decklist, parse_query, Format};
use crate::model::conditions::Cond;
use crate::model::selectors::Sel;
use crate::model::text::py_repr;
use crate::model::{
    Card, Condition, Deck, Demand, GameConfig, MulliganConfig, Op, PriorityGroup, Query, Scenario,
    Selector, Zone,
};
use crate::optimizer;
use crate::probability::{self, Answer, Fraction, DEFAULT_LIMIT};
use crate::stats;

/// Largest request accepted, in bytes (a 1,000,000-character decklist, NFR-14, at up to
/// 4 bytes per character).
pub const MAX_REQUEST_BYTES: usize = 4 << 20;

/// The deck comes as a `scenario` object, or as `decklist` text plus an optional
/// `game`; the question as a `query` object, or as `rule` text plus a default `turn`.
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    #[serde(default)]
    scenario: Option<ScenarioDto>,
    #[serde(default)]
    decklist: Option<String>,
    #[serde(default)]
    game: Option<GameDto>,
    /// With a decklist: the mulligan configuration, if modelled.
    #[serde(default)]
    mulligan: Option<MulliganDto>,
    #[serde(default)]
    query: Option<QueryDto>,
    #[serde(default)]
    rule: Option<String>,
    #[serde(default)]
    turn: Option<i64>,
    /// What to work out; absent means the probability of the query.
    #[serde(default)]
    question: Option<QuestionDto>,
    /// An optimization problem (`to_dict(OptimizeProblem)`), instead of a scenario and a
    /// question (port stage 5).
    #[serde(default)]
    optimize: Option<ProblemDto>,
    /// With `optimize` and one variable: also give the chance with one card fewer than
    /// the answer (`"one_fewer"`, null when the answer is the lowest count tried).
    #[serde(default)]
    one_fewer: bool,
    #[serde(default = "default_limit")]
    limit: usize,
}

/// The question a request asks (port stage 3).
#[derive(Deserialize)]
#[serde(tag = "type", deny_unknown_fields)]
enum QuestionDto {
    /// P(query), the default.
    Probability {},
    /// Python's `distributions(scenario, selector, turns)`; no query or rule.
    Distributions {
        selector: SelectorDto,
        turns: Vec<i64>,
    },
    /// Python's `turn_table(scenario, condition, turns)`, the condition being the query's
    /// (without `given`) or the rule's.
    TurnTable { turns: Vec<i64> },
    /// Python's `mulligan_report(scenario, success, turn)` (port stage 4).
    MulliganReport {},
    /// Python's `optimal_keep(scenario, success, turn)` (port stage 4).
    OptimalKeep {},
    /// Both of the above for one condition, in one reply (the "Should I mulligan?" page).
    MulliganAdvice {},
}

fn default_limit() -> usize {
    DEFAULT_LIMIT
}

#[derive(Deserialize)]
#[serde(tag = "type", deny_unknown_fields)]
enum ScenarioDto {
    Scenario {
        deck: DeckDto,
        #[serde(default)]
        game: Option<GameDto>,
        #[serde(default)]
        mulligan: Option<MulliganDto>,
    },
}

#[derive(Deserialize)]
#[serde(tag = "type", deny_unknown_fields)]
enum ProblemDto {
    OptimizeProblem {
        deck_size: i64,
        variables: Vec<VariableDto>,
        query: QueryDto,
        #[serde(default)]
        fixed: Vec<(String, CategoryDto)>,
        #[serde(default)]
        game: Option<GameDto>,
        #[serde(default)]
        mulligan: Option<MulliganDto>,
        #[serde(default = "max_probability")]
        objective: String,
        #[serde(default)]
        target: Option<FractionDto>,
        #[serde(default)]
        budget: Option<i64>,
        #[serde(default = "five_thousand")]
        exhaustive_limit: i64,
        #[serde(default)]
        assume_monotone: Option<bool>,
        #[serde(default)]
        workers: Option<i64>,
    },
}

fn max_probability() -> String {
    "max_probability".into()
}

fn five_thousand() -> i64 {
    5000
}

#[derive(Deserialize)]
#[serde(tag = "type", deny_unknown_fields)]
enum VariableDto {
    Variable {
        name: String,
        lo: i64,
        hi: i64,
        #[serde(default)]
        tags: Option<FrozenSetDto>,
    },
}

#[derive(Deserialize)]
#[serde(tag = "type", deny_unknown_fields)]
enum CategoryDto {
    Category {
        count: i64,
        #[serde(default)]
        tags: Option<FrozenSetDto>,
    },
}

#[derive(Deserialize)]
#[serde(tag = "type", deny_unknown_fields)]
enum FractionDto {
    Fraction { value: String },
}

/// Python's `Fraction(text)` for "n/d" or "n": negative values become 0 (a target below
/// zero is met by every probability, exactly as 0 is).
fn fraction_of(dto: FractionDto) -> std::result::Result<Fraction, ErrorReply> {
    let FractionDto::Fraction { value } = dto;
    let bad = || malformed(&format!("not a fraction: {value}"));
    let (num, den) = value.split_once('/').unwrap_or((value.as_str(), "1"));
    let negative = num.trim().starts_with('-');
    let num: num_bigint::BigUint = num
        .trim()
        .trim_start_matches(['-', '+'])
        .parse()
        .map_err(|_| bad())?;
    let den: num_bigint::BigUint = den.trim().parse().map_err(|_| bad())?;
    if den == num_bigint::BigUint::default() {
        return Err(bad());
    }
    Ok(if negative {
        Fraction::zero()
    } else {
        Fraction::new(num, den)
    })
}

fn tags_of(tags: Option<FrozenSetDto>) -> Vec<String> {
    tags.map_or_else(Vec::new, |FrozenSetDto::FrozenSet { items }| items)
}

fn optimize_problem(
    dto: ProblemDto,
) -> std::result::Result<optimizer::OptimizeProblem, ErrorReply> {
    let ProblemDto::OptimizeProblem {
        deck_size,
        variables,
        query: q,
        fixed,
        game,
        mulligan,
        objective,
        target,
        budget,
        exhaustive_limit,
        assume_monotone,
        workers,
    } = dto;
    // Python decodes nested values (variables, query, fixed, ...) before checking the
    // problem itself.
    let variables = variables
        .into_iter()
        .map(|VariableDto::Variable { name, lo, hi, tags }| {
            optimizer::Variable::new(&name, lo, hi, tags_of(tags))
        })
        .collect::<Result<Vec<_>>>()?;
    let query = query(q)?;
    let fixed = fixed
        .into_iter()
        .map(|(name, CategoryDto::Category { count, tags })| {
            Ok((name, optimizer::Category::new(count, tags_of(tags))?))
        })
        .collect::<Result<Vec<_>>>()?;
    let game = game_config(game)?;
    let mulligan = mulligan.map(mulligan_config).transpose()?;
    let objective = match objective.as_str() {
        "min_count" => optimizer::Objective::MinCount,
        "max_probability" => optimizer::Objective::MaxProbability,
        "min_total" => optimizer::Objective::MinTotal,
        other => return Err(malformed(&format!("unknown objective {other}"))),
    };
    let target = target.map(fraction_of).transpose()?;
    let problem = optimizer::OptimizeProblem {
        deck_size: u64::try_from(deck_size)
            .map_err(|_| malformed("deck_size must be non-negative"))?,
        variables,
        query,
        fixed,
        game,
        mulligan,
        objective,
        target,
        budget: budget.and_then(|b| u64::try_from(b).ok()),
        exhaustive_limit: u64::try_from(exhaustive_limit).unwrap_or(0),
        assume_monotone,
    };
    optimizer::validate(&problem, workers, budget)?;
    Ok(problem)
}

fn optimize_result_json(r: &optimizer::OptimizeResult) -> Value {
    let counts = |c: &[(String, u64)]| -> Value { c.iter().map(|(n, k)| json!([n, k])).collect() };
    let frontier: Vec<Value> = r
        .frontier
        .iter()
        .map(|(c, p)| json!([counts(c), fraction_json(p)]))
        .collect();
    json!({
        "type": "OptimizeResult",
        "counts": counts(&r.counts),
        "probability": fraction_json(&r.probability),
        "proven_optimal": r.proven_optimal,
        "evaluations": r.evaluations,
        "frontier": frontier,
    })
}

fn two() -> i64 {
    2
}

fn keep_any() -> ConditionDto {
    ConditionDto::Const { value: true }
}

#[derive(Deserialize)]
#[serde(tag = "type", deny_unknown_fields)]
enum MulliganDto {
    MulliganConfig {
        priority: Vec<PriorityDto>,
        #[serde(default = "keep_any")]
        keep_rule: ConditionDto,
        #[serde(default = "two")]
        max_mulligans: i64,
        #[serde(default)]
        free_mulligans: i64,
        #[serde(default = "seven")]
        draw_size: i64,
    },
}

#[derive(Deserialize)]
#[serde(tag = "type", deny_unknown_fields)]
enum PriorityDto {
    PriorityGroup {
        selector: SelectorDto,
        #[serde(default)]
        quota: Option<i64>,
        #[serde(default)]
        #[allow(dead_code)] // part of the format; not used in calculations
        name: Option<String>,
    },
}

#[derive(Deserialize)]
#[serde(tag = "type", deny_unknown_fields)]
enum DeckDto {
    Deck {
        cards: Vec<CardDto>,
        #[serde(default)]
        #[allow(dead_code)] // part of the format; not used in calculations
        name: Option<String>,
    },
}

fn one() -> i64 {
    1
}

fn library() -> String {
    "library".into()
}

#[derive(Deserialize)]
#[serde(tag = "type", deny_unknown_fields)]
enum CardDto {
    Card {
        name: String,
        #[serde(default = "one")]
        quantity: i64,
        #[serde(default)]
        tags: Option<FrozenSetDto>,
        #[serde(default = "library")]
        zone: String,
    },
}

#[derive(Deserialize)]
#[serde(tag = "type", deny_unknown_fields)]
enum FrozenSetDto {
    #[serde(rename = "frozenset")]
    FrozenSet { items: Vec<String> },
}

fn seven() -> i64 {
    7
}

fn yes() -> bool {
    true
}

#[derive(Deserialize)]
#[serde(tag = "type", deny_unknown_fields)]
enum GameDto {
    GameConfig {
        #[serde(default = "seven")]
        hand_size: i64,
        #[serde(default = "yes")]
        on_play: bool,
        #[serde(default = "one")]
        draws_per_turn: i64,
        #[serde(default)]
        draw_overrides: Vec<(i64, i64)>,
        #[serde(default)]
        extra_draws: Vec<(i64, i64)>,
    },
}

#[derive(Deserialize)]
#[serde(tag = "type", deny_unknown_fields)]
enum SelectorDto {
    Tag { name: String },
    CardName { name: String },
    AnyOf { items: Vec<SelectorDto> },
    AllOf { items: Vec<SelectorDto> },
    NoneOf { items: Vec<SelectorDto> },
    Everything {},
}

#[derive(Deserialize)]
#[serde(tag = "type", deny_unknown_fields)]
enum DemandDto {
    Demand { sel: SelectorDto, need: i64 },
}

#[derive(Deserialize)]
#[serde(tag = "type", deny_unknown_fields)]
enum ConditionDto {
    Compare {
        sel: SelectorDto,
        op: String,
        value: i64,
    },
    Between {
        sel: SelectorDto,
        lo: i64,
        hi: i64,
    },
    And {
        items: Vec<ConditionDto>,
    },
    Or {
        items: Vec<ConditionDto>,
    },
    Xor {
        a: Box<ConditionDto>,
        b: Box<ConditionDto>,
    },
    Not {
        item: Box<ConditionDto>,
    },
    Implies {
        a: Box<ConditionDto>,
        b: Box<ConditionDto>,
    },
    AtLeast {
        n: i64,
        items: Vec<ConditionDto>,
    },
    Exactly {
        n: i64,
        items: Vec<ConditionDto>,
    },
    Assignable {
        demands: Vec<DemandDto>,
    },
    At {
        turn: i64,
        item: Box<ConditionDto>,
    },
    Const {
        value: bool,
    },
}

#[derive(Deserialize)]
#[serde(tag = "type", deny_unknown_fields)]
enum QueryDto {
    Query {
        condition: ConditionDto,
        #[serde(default)]
        given: Option<ConditionDto>,
        #[serde(default)]
        turn: i64,
    },
}

type Result<T> = std::result::Result<T, Error>;

fn selector(dto: SelectorDto) -> Result<Selector> {
    let items = |xs: Vec<SelectorDto>| xs.into_iter().map(selector).collect::<Result<Vec<_>>>();
    match dto {
        SelectorDto::Tag { name } => Selector::tag(&name),
        SelectorDto::CardName { name } => Selector::card(&name),
        SelectorDto::AnyOf { items: xs } => Selector::any_of(items(xs)?),
        SelectorDto::AllOf { items: xs } => Selector::all_of(items(xs)?),
        SelectorDto::NoneOf { items: xs } => Selector::none_of(items(xs)?),
        SelectorDto::Everything {} => Ok(Selector::everything()),
    }
}

fn condition(dto: ConditionDto) -> Result<Condition> {
    let many = |xs: Vec<ConditionDto>| xs.into_iter().map(condition).collect::<Result<Vec<_>>>();
    let boxed = |x: Box<ConditionDto>| condition(*x);
    match dto {
        ConditionDto::Compare { sel, op, value } => {
            let sel = selector(sel)?;
            Condition::compare(sel, Op::parse(&op)?, value)
        }
        ConditionDto::Between { sel, lo, hi } => Condition::between(selector(sel)?, lo, hi),
        ConditionDto::And { items } => Condition::and(many(items)?),
        ConditionDto::Or { items } => Condition::or(many(items)?),
        ConditionDto::Xor { a, b } => Ok(Condition::xor(boxed(a)?, boxed(b)?)),
        ConditionDto::Not { item } => Ok(Condition::not(boxed(item)?)),
        ConditionDto::Implies { a, b } => Ok(Condition::implies(boxed(a)?, boxed(b)?)),
        ConditionDto::AtLeast { n, items } => Condition::at_least(n, many(items)?),
        ConditionDto::Exactly { n, items } => Condition::exactly(n, many(items)?),
        ConditionDto::Assignable { demands } => Condition::assignable(
            demands
                .into_iter()
                .map(|DemandDto::Demand { sel, need }| Demand::new(selector(sel)?, need))
                .collect::<Result<_>>()?,
        ),
        ConditionDto::At { turn, item } => Condition::at(turn, boxed(item)?),
        ConditionDto::Const { value } => Ok(Condition::constant(value)),
    }
}

fn card(dto: CardDto) -> Result<Card> {
    let CardDto::Card {
        name,
        quantity,
        tags,
        zone,
    } = dto;
    let tags = tags.map_or_else(Vec::new, |FrozenSetDto::FrozenSet { items }| items);
    // Python validates the name, the quantity, the zone, then the tags.
    let probe = Card::new(&name, quantity, &[], Zone::Library)?;
    Card::new(&name, quantity, &tags, Zone::parse(&zone, probe.name())?)
}

fn scenario(dto: ScenarioDto) -> Result<Scenario> {
    let ScenarioDto::Scenario {
        deck,
        game,
        mulligan,
    } = dto;
    let DeckDto::Deck { cards, .. } = deck;
    let deck = Deck::new(cards.into_iter().map(card).collect::<Result<_>>()?)?;
    let game = game_config(game)?;
    let mulligan = mulligan.map(mulligan_config).transpose()?;
    Ok(Scenario {
        deck,
        game,
        mulligan,
    })
}

fn mulligan_config(dto: MulliganDto) -> Result<MulliganConfig> {
    let MulliganDto::MulliganConfig {
        priority,
        keep_rule,
        max_mulligans,
        free_mulligans,
        draw_size,
    } = dto;
    let priority = priority
        .into_iter()
        .map(
            |PriorityDto::PriorityGroup {
                 selector: s, quota, ..
             }| PriorityGroup::new(selector(s)?, quota),
        )
        .collect::<Result<Vec<_>>>()?;
    MulliganConfig::new(
        priority,
        condition(keep_rule)?,
        max_mulligans,
        free_mulligans,
        draw_size,
    )
}

fn game_config(game: Option<GameDto>) -> Result<GameConfig> {
    Ok(match game {
        None => GameConfig::default(),
        Some(GameDto::GameConfig {
            hand_size,
            on_play,
            draws_per_turn,
            draw_overrides,
            extra_draws,
        }) => GameConfig::new(
            hand_size,
            on_play,
            draws_per_turn,
            &draw_overrides,
            &extra_draws,
        )?,
    })
}

fn query(dto: QueryDto) -> Result<Query> {
    let QueryDto::Query {
        condition: c,
        given,
        turn,
    } = dto;
    Query::new(condition(c)?, given.map(condition).transpose()?, turn)
}

fn probability_json(p: &Fraction) -> Value {
    json!({
        "type": "Probability",
        "exact": {"type": "Fraction", "value": p.to_string()},
        "estimate": null,
        "ci95": null,
        "method": "exact",
        "warnings": [],
    })
}

fn answer_json(answer: &Answer) -> Value {
    match answer {
        Answer::Probability(p) => probability_json(p),
        Answer::Conditional {
            joint,
            given,
            result,
        } => json!({
            "type": "ConditionalResult",
            "joint": probability_json(joint),
            "given": probability_json(given),
            "result": result.as_ref().map(probability_json),
        }),
    }
}

/// An error in the boundary's format.
#[derive(Serialize, Debug, PartialEq, Eq)]
pub struct ErrorReply {
    #[serde(rename = "type")]
    tag: &'static str,
    /// `validation`, `too_large`, `unsupported`, `malformed` or `internal`.
    pub kind: &'static str,
    /// The offending field for validation errors (Python's field path), else empty.
    pub field: String,
    /// A developer-facing explanation (front ends write their own wording per kind).
    pub message: String,
    /// For `parse` errors: the 1-based line of the text.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub line: Option<usize>,
    /// For `parse` errors: the 1-based column (in characters).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub column: Option<usize>,
}

impl ErrorReply {
    fn new(kind: &'static str, field: impl Into<String>, message: impl Into<String>) -> Self {
        ErrorReply {
            tag: "Error",
            kind,
            field: field.into(),
            message: message.into(),
            line: None,
            column: None,
        }
    }
}

impl From<Error> for ErrorReply {
    fn from(e: Error) -> Self {
        match e {
            Error::Validation { field, message } => ErrorReply::new("validation", field, message),
            Error::Parse {
                message,
                line,
                column,
            } => ErrorReply {
                line: Some(line),
                column: Some(column),
                ..ErrorReply::new("parse", "", message)
            },
            Error::Limit(states) => ErrorReply::new(
                "too_large",
                "",
                format!("the exact calculation needs more than {states} states"),
            ),
            Error::Unsupported(why) => ErrorReply::new("unsupported", "", why),
            Error::Infeasible(why) => ErrorReply::new("infeasible", "", why),
            // The u128 driver retries with big integers, and compiled input is valid, so
            // reaching these is a bug: report it rather than panic.
            Error::Overflow | Error::Invalid(_) => ErrorReply::new("internal", "", e.to_string()),
        }
    }
}

/// Answers a probability request (format in the module docs). Never panics on input.
#[must_use]
pub fn probability(request: &str) -> String {
    reply(answer(request))
}

type Reply = std::result::Result<Value, ErrorReply>;

fn malformed(why: &str) -> ErrorReply {
    ErrorReply::new("malformed", "", why)
}

fn answer(request: &str) -> Reply {
    if request.len() > MAX_REQUEST_BYTES {
        return Err(malformed(&format!(
            "requests are limited to {MAX_REQUEST_BYTES} bytes"
        )));
    }
    let req: Request = serde_json::from_str(request).map_err(|e| malformed(&e.to_string()))?;
    if let Some(problem) = req.optimize {
        let alone = req.scenario.is_none()
            && req.decklist.is_none()
            && req.game.is_none()
            && req.mulligan.is_none()
            && req.query.is_none()
            && req.rule.is_none()
            && req.turn.is_none()
            && req.question.is_none();
        if !alone {
            return Err(malformed(
                "an optimize request takes only the problem (and a limit)",
            ));
        }
        let problem = optimize_problem(problem)?;
        if req.one_fewer && problem.variables.len() != 1 {
            return Err(malformed("one_fewer needs exactly one variable"));
        }
        let result = optimizer::optimize(&problem, req.limit)?;
        let mut reply = optimize_result_json(&result);
        if req.one_fewer {
            let chosen = result.counts.first().map_or(0, |(_, c)| *c);
            let fewer = optimizer::one_fewer(&problem, chosen, req.limit)?;
            reply["one_fewer"] = fewer.as_ref().map_or(Value::Null, fraction_json);
        }
        return Ok(reply);
    }
    if req.one_fewer {
        return Err(malformed("one_fewer goes with an optimize request"));
    }
    let sc = match (req.scenario, req.decklist) {
        (Some(s), None) if req.game.is_none() && req.mulligan.is_none() => scenario(s)?,
        (None, Some(text)) => Scenario {
            deck: parse_decklist(&text, Format::Auto)?,
            game: game_config(req.game)?,
            mulligan: req.mulligan.map(mulligan_config).transpose()?,
        },
        _ => {
            return Err(malformed(
                "give either a scenario, or a decklist with an optional game",
            ))
        }
    };
    let asked = Asked {
        query: req.query,
        rule: req.rule,
        turn: req.turn,
        limit: req.limit,
    };
    match req.question.unwrap_or(QuestionDto::Probability {}) {
        QuestionDto::Probability {} => answer_probability(&sc, asked),
        QuestionDto::Distributions {
            selector: sel,
            turns,
        } => answer_distributions(&sc, sel, &turns, &asked),
        QuestionDto::TurnTable { turns } => answer_turn_table(&sc, &turns, asked),
        QuestionDto::MulliganReport {} => answer_mulligan(&sc, asked, true),
        QuestionDto::OptimalKeep {} => answer_mulligan(&sc, asked, false),
        QuestionDto::MulliganAdvice {} => {
            let limit = asked.limit;
            let (success, turn) = asked.condition("a mulligan question")?;
            Ok(json!({
                "type": "MulliganAdvice",
                "report": mulligan_report_json(&analysis::mulligan_report(&sc, &success, turn, limit)?),
                "best": optimal_keep_json(&analysis::optimal_keep(&sc, &success, turn, limit)?),
            }))
        }
    }
}

/// The question's condition, as a query or a rule, plus the default turn and the limit.
struct Asked {
    query: Option<QueryDto>,
    rule: Option<String>,
    turn: Option<i64>,
    limit: usize,
}

impl Asked {
    /// A condition without `given`, and its default turn (questions other than P(...)).
    fn condition(self, what: &str) -> std::result::Result<(Condition, u64), ErrorReply> {
        match (self.query, self.rule) {
            (Some(q), None) if self.turn.is_none() => {
                let q = query(q)?;
                if q.given.is_some() {
                    return Err(malformed(&format!("{what} takes a query without given")));
                }
                Ok((q.condition, q.turn))
            }
            (None, Some(text)) => {
                let turn = u64::try_from(self.turn.unwrap_or(0))
                    .map_err(|_| validation("query.turn", "must be non-negative"))?;
                Ok((parse_condition(&text)?, turn))
            }
            _ => Err(malformed(&format!("{what} takes either a query or a rule"))),
        }
    }
}

fn answer_probability(sc: &Scenario, asked: Asked) -> Reply {
    let q = match (asked.query, asked.rule) {
        (Some(q), None) if asked.turn.is_none() => query(q)?,
        (None, Some(text)) => parse_query(&text, asked.turn.unwrap_or(0))?,
        _ => {
            return Err(malformed(
                "give either a query, or a rule with an optional turn",
            ))
        }
    };
    Ok(answer_json(&probability::probability(sc, &q, asked.limit)?))
}

fn answer_distributions(sc: &Scenario, sel: SelectorDto, turns: &[i64], asked: &Asked) -> Reply {
    if asked.query.is_some() || asked.rule.is_some() || asked.turn.is_some() {
        return Err(malformed(
            "a Distributions question takes a selector, not a query",
        ));
    }
    let items: Vec<Value> = stats::distributions(sc, &selector(sel)?, turns, asked.limit)?
        .iter()
        .map(|d| {
            let pmf: Vec<Value> = d.pmf.iter().map(fraction_json).collect();
            json!({"type": "Distribution", "turn": d.turn, "pmf": pmf})
        })
        .collect();
    Ok(json!({"type": "Distributions", "items": items}))
}

fn answer_turn_table(sc: &Scenario, turns: &[i64], asked: Asked) -> Reply {
    if asked.turn.is_some() {
        return Err(malformed(
            "a TurnTable question takes either a query or a rule",
        ));
    }
    let limit = asked.limit;
    let (cond, _) = asked.condition("a TurnTable question")?;
    let rows: Vec<Value> = stats::turn_table(sc, &cond, turns, limit)?
        .iter()
        .map(|r| {
            json!({
                "type": "TurnRow",
                "turn": r.turn,
                "cards_seen": r.cards_seen,
                "probability": fraction_json(&r.probability),
            })
        })
        .collect();
    Ok(json!({"type": "TurnTable", "rows": rows}))
}

fn answer_mulligan(sc: &Scenario, asked: Asked, report: bool) -> Reply {
    let limit = asked.limit;
    let (success, turn) = asked.condition("a mulligan question")?;
    Ok(if report {
        mulligan_report_json(&analysis::mulligan_report(sc, &success, turn, limit)?)
    } else {
        optimal_keep_json(&analysis::optimal_keep(sc, &success, turn, limit)?)
    })
}

fn fraction_json(p: &Fraction) -> Value {
    json!({"type": "Fraction", "value": p.to_string()})
}

fn mulligan_report_json(r: &analysis::MulliganReport) -> Value {
    let rows: Vec<Value> = r
        .rows
        .iter()
        .map(|row| {
            json!({
                "type": "MulliganRow",
                "depth": row.depth,
                "hand_size": row.hand_size,
                "p_reach": fraction_json(&row.p_reach),
                "p_keep_given_reach": fraction_json(&row.p_keep_given_reach),
                "p_success_forced": fraction_json(&row.p_success_forced),
                "p_success_and_keep_given_reach": fraction_json(&row.p_success_and_keep_given_reach),
            })
        })
        .collect();
    json!({
        "type": "MulliganReport",
        "rows": rows,
        "p_success": fraction_json(&r.p_success),
        "expected_mulligans": fraction_json(&r.expected_mulligans),
        "expected_hand_size": fraction_json(&r.expected_hand_size),
    })
}

fn optimal_keep_json(r: &analysis::OptimalKeepReport) -> Value {
    let rows: Vec<Value> = r
        .rows
        .iter()
        .map(|row| {
            let hands: Vec<Value> = row
                .hands
                .iter()
                .map(|h| {
                    json!({
                        "type": "KeptHand",
                        "atom_counts": h.atom_counts,
                        "probability": fraction_json(&h.probability),
                        "success": fraction_json(&h.success),
                        "keep": h.keep,
                    })
                })
                .collect();
            json!({
                "type": "OptimalKeepRow",
                "depth": row.depth,
                "hand_size": row.hand_size,
                "continuation_value": fraction_json(&row.continuation_value),
                "p_keep_given_reach": fraction_json(&row.p_keep_given_reach),
                "hands": hands,
            })
        })
        .collect();
    json!({"type": "OptimalKeepReport", "value": fraction_json(&r.value), "rows": rows, "atoms": r.atoms})
}

// -- Python's to_dict format, for parsed text ------------------------------------------

/// A frozenset of strings, sorted as Python's `to_dict` sorts them (by `repr`).
fn frozenset_json<'a>(items: impl Iterator<Item = &'a str>) -> Value {
    let mut items: Vec<&str> = items.collect();
    items.sort_by_cached_key(|s| py_repr(s));
    json!({"type": "frozenset", "items": items})
}

fn selector_json(sel: &Selector) -> Value {
    let items = |xs: &[Selector]| Value::Array(xs.iter().map(selector_json).collect());
    match &sel.0 {
        Sel::Tag(name) => json!({"type": "Tag", "name": name}),
        Sel::CardName(name) => json!({"type": "CardName", "name": name}),
        Sel::AnyOf(xs) => json!({"type": "AnyOf", "items": items(xs)}),
        Sel::AllOf(xs) => json!({"type": "AllOf", "items": items(xs)}),
        Sel::NoneOf(xs) => json!({"type": "NoneOf", "items": items(xs)}),
        Sel::Everything => json!({"type": "Everything"}),
    }
}

fn op_str(op: Op) -> &'static str {
    match op {
        Op::Eq => "==",
        Op::Ne => "!=",
        Op::Lt => "<",
        Op::Le => "<=",
        Op::Gt => ">",
        Op::Ge => ">=",
    }
}

fn condition_json(c: &Condition) -> Value {
    let items = |xs: &[Condition]| Value::Array(xs.iter().map(condition_json).collect());
    match &c.0 {
        Cond::Compare { sel, op, value } => {
            json!({"type": "Compare", "sel": selector_json(sel), "op": op_str(*op), "value": value})
        }
        Cond::Between { sel, lo, hi } => {
            json!({"type": "Between", "sel": selector_json(sel), "lo": lo, "hi": hi})
        }
        Cond::And(xs) => json!({"type": "And", "items": items(xs)}),
        Cond::Or(xs) => json!({"type": "Or", "items": items(xs)}),
        Cond::Xor(a, b) => json!({"type": "Xor", "a": condition_json(a), "b": condition_json(b)}),
        Cond::Not(x) => json!({"type": "Not", "item": condition_json(x)}),
        Cond::Implies(a, b) => {
            json!({"type": "Implies", "a": condition_json(a), "b": condition_json(b)})
        }
        Cond::AtLeast(n, xs) => json!({"type": "AtLeast", "n": n, "items": items(xs)}),
        Cond::Exactly(n, xs) => json!({"type": "Exactly", "n": n, "items": items(xs)}),
        Cond::Assignable(ds) => json!({
            "type": "Assignable",
            "demands": ds.iter().map(|d| json!({"type": "Demand", "sel": selector_json(&d.sel), "need": d.need})).collect::<Vec<_>>(),
        }),
        Cond::At(t, x) => json!({"type": "At", "turn": t, "item": condition_json(x)}),
        Cond::Const(v) => json!({"type": "Const", "value": v}),
    }
}

fn query_json(q: &Query) -> Value {
    json!({
        "type": "Query",
        "condition": condition_json(&q.condition),
        "given": q.given.as_ref().map(condition_json),
        "turn": q.turn,
    })
}

fn deck_json(deck: &Deck) -> Value {
    let cards: Vec<Value> = deck
        .cards()
        .iter()
        .map(|c| {
            json!({
                "type": "Card",
                "name": c.name(),
                "quantity": c.quantity(),
                "tags": frozenset_json(c.tags()),
                "zone": c.zone().as_str(),
            })
        })
        .collect();
    json!({"type": "Deck", "cards": cards, "name": null})
}

fn reply(result: std::result::Result<Value, ErrorReply>) -> String {
    match result {
        Ok(value) => value,
        Err(e) => serde_json::to_value(e).unwrap_or(Value::Null),
    }
    .to_string()
}

fn bounded(text: &str) -> std::result::Result<(), ErrorReply> {
    if text.len() > MAX_REQUEST_BYTES {
        return Err(ErrorReply::new(
            "malformed",
            "",
            format!("requests are limited to {MAX_REQUEST_BYTES} bytes"),
        ));
    }
    Ok(())
}

/// A text decklist as Python's `to_dict(parse_decklist(text))`, or an error.
#[must_use]
pub fn parse_deck(text: &str) -> String {
    reply(bounded(text).and_then(|()| Ok(deck_json(&parse_decklist(text, Format::Auto)?))))
}

/// A rule as Python's `to_dict(parse_query(text, turn))`, or an error.
#[must_use]
pub fn parse_rule(text: &str, turn: i64) -> String {
    reply(bounded(text).and_then(|()| Ok(query_json(&parse_query(text, turn)?))))
}

/// The rule-language text of a `Query` object (Python's `format_query`), as
/// `{"type": "Rule", "text": ...}`, or an error.
#[must_use]
pub fn format_rule(query_object: &str) -> String {
    reply(bounded(query_object).and_then(|()| {
        let dto: QueryDto = serde_json::from_str(query_object)
            .map_err(|e| ErrorReply::new("malformed", "", e.to_string()))?;
        Ok(json!({"type": "Rule", "text": format_query(&query(dto)?)}))
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn deck(cards: &str) -> String {
        format!(
            r#"{{"type": "Scenario", "deck": {{"type": "Deck", "cards": [{cards}], "name": null}}, "game": {{"type": "GameConfig", "hand_size": 7, "on_play": true, "draws_per_turn": 1, "draw_overrides": [], "extra_draws": []}}, "mulligan": null}}"#
        )
    }

    const LANDS: &str = r#"{"type": "Card", "name": "land", "quantity": 24, "tags": {"type": "frozenset", "items": ["land"]}, "zone": "library"}, {"type": "Card", "name": "(other)", "quantity": 36, "tags": {"type": "frozenset", "items": ["(other)"]}, "zone": "library"}"#;

    fn ask(scenario: &str, query: &str) -> Value {
        let text = probability(&format!(r#"{{"scenario": {scenario}, "query": {query}}}"#));
        serde_json::from_str(&text).unwrap()
    }

    fn kind(v: &Value) -> &str {
        v["kind"].as_str().unwrap_or("")
    }

    const AT_LEAST_ONE_LAND: &str = r#"{"type": "Query", "condition": {"type": "Compare", "sel": {"type": "Tag", "name": "land"}, "op": ">=", "value": 1}, "given": null, "turn": 0}"#;

    #[test]
    fn answers_in_python_format() {
        let v = ask(&deck(LANDS), AT_LEAST_ONE_LAND);
        assert_eq!(v["type"], "Probability");
        assert_eq!(v["method"], "exact");
        assert_eq!(v["exact"]["type"], "Fraction");
        assert!(v["exact"]["value"].as_str().unwrap().contains('/'));
        assert_eq!(v["warnings"], json!([]));
    }

    #[test]
    fn conditional_answers_have_three_parts() {
        let q = r#"{"type": "Query", "condition": {"type": "Compare", "sel": {"type": "Tag", "name": "land"}, "op": ">=", "value": 2}, "given": {"type": "Compare", "sel": {"type": "Tag", "name": "land"}, "op": ">", "value": 7}, "turn": 0}"#;
        let v = ask(&deck(LANDS), q);
        assert_eq!(v["type"], "ConditionalResult");
        assert_eq!(v["given"]["exact"]["value"], "0/1");
        assert_eq!(v["result"], Value::Null);
    }

    #[test]
    fn python_defaults_fill_missing_fields() {
        let sc = r#"{"type": "Scenario", "deck": {"type": "Deck", "cards": [{"type": "Card", "name": "Forest", "quantity": 60}]}}"#;
        let q = r#"{"type": "Query", "condition": {"type": "Compare", "sel": {"type": "CardName", "name": "forest"}, "op": "==", "value": 7}}"#;
        assert_eq!(ask(sc, q)["exact"]["value"], "1/1");
    }

    #[test]
    fn errors_are_classified() {
        // validation, with Python's field path
        let bad = deck(r#"{"type": "Card", "name": "x", "quantity": 0}"#);
        let v = ask(&bad, AT_LEAST_ONE_LAND);
        assert_eq!(
            (kind(&v), v["field"].as_str().unwrap()),
            ("validation", "card[x].quantity")
        );
        // malformed: unknown type, unknown field, float, broken JSON, oversize
        for q in [
            r#"{"type": "Query", "condition": {"type": "Maybe"}}"#,
            r#"{"type": "Query", "condition": {"type": "Const", "value": true, "extra": 1}}"#,
            r#"{"type": "Query", "condition": {"type": "Compare", "sel": {"type": "Everything"}, "op": ">=", "value": 1.5}}"#,
            r#"{"type": "Query", "condition": "#,
        ] {
            assert_eq!(kind(&ask(&deck(LANDS), q)), "malformed", "{q}");
        }
        let huge = format!("{{\"pad\": \"{}\"}}", "x".repeat(MAX_REQUEST_BYTES));
        assert_eq!(
            kind(&serde_json::from_str::<Value>(&probability(&huge)).unwrap()),
            "malformed"
        );
        // A mulligan configuration needs its priority groups (malformed without them),
        // and validates like Python (no groups at all is a validation error).
        let broken = deck(LANDS).replace(
            r#""mulligan": null"#,
            r#""mulligan": {"type": "MulliganConfig"}"#,
        );
        assert_eq!(kind(&ask(&broken, AT_LEAST_ONE_LAND)), "malformed");
        let empty = deck(LANDS).replace(
            r#""mulligan": null"#,
            r#""mulligan": {"type": "MulliganConfig", "priority": []}"#,
        );
        assert_eq!(kind(&ask(&empty, AT_LEAST_ONE_LAND)), "validation");
    }

    #[test]
    fn mulligans_are_answered_at_strategy_level() {
        let mull = deck(LANDS).replace(
            r#""mulligan": null"#,
            r#""mulligan": {"type": "MulliganConfig", "priority": [{"type": "PriorityGroup", "selector": {"type": "Tag", "name": "land"}, "quota": 3}], "keep_rule": {"type": "Between", "sel": {"type": "Tag", "name": "land"}, "lo": 2, "hi": 5}}"#,
        );
        let plain = ask(&deck(LANDS), AT_LEAST_ONE_LAND);
        let with = ask(&mull, AT_LEAST_ONE_LAND);
        assert_eq!(with["type"], "Probability");
        assert_ne!(with["exact"], plain["exact"]); // mulligans change the answer
        let q = format!(
            r#"{{"scenario": {mull}, "query": {AT_LEAST_ONE_LAND}, "question": {{"type": "MulliganReport"}}}}"#
        );
        let report: Value = serde_json::from_str(&probability(&q)).unwrap();
        assert_eq!(report["type"], "MulliganReport");
        assert_eq!(report["rows"].as_array().map(Vec::len), Some(3));
        assert_eq!(report["p_success"], with["exact"]);
        let q = q.replace("MulliganReport", "OptimalKeep");
        let best: Value = serde_json::from_str(&probability(&q)).unwrap();
        assert_eq!(best["type"], "OptimalKeepReport");
        assert_eq!(best["atoms"], json!([["land"]]));
    }

    #[test]
    fn too_large_is_reported_with_the_limit() {
        let text = probability(&format!(
            r#"{{"scenario": {}, "query": {AT_LEAST_ONE_LAND}, "limit": 1}}"#,
            deck(LANDS)
        ));
        let v: Value = serde_json::from_str(&text).unwrap();
        assert_eq!(kind(&v), "too_large");
    }

    #[test]
    fn deep_nesting_is_malformed_not_a_crash() {
        let mut c = r#"{"type": "Const", "value": true}"#.to_owned();
        for _ in 0..200 {
            c = format!(r#"{{"type": "Not", "item": {c}}}"#);
        }
        let q = format!(r#"{{"type": "Query", "condition": {c}}}"#);
        assert_eq!(kind(&ask(&deck(LANDS), &q)), "malformed");
    }
}
