//! `PyO3` bindings: the `mtgcalc_native` extension module (ADR-0009, ADR-0013).
//!
//! Converts the flat tuples produced by `mtgcalc.engine.native` into validated Rust
//! types, releases the GIL for the computation (`Python::detach`), and maps errors to Python exceptions:
//! [`Error::Invalid`] becomes `ValueError`, [`Error::Limit`] becomes `StateLimitExceeded`.

use num_bigint::BigUint;
use pyo3::exceptions::{PyException, PyValueError};
use pyo3::prelude::*;

use mtgcalc_core::api;
use mtgcalc_core::engine::{Options, Query, Start, StartState};
use mtgcalc_core::error::Error;
use mtgcalc_core::logic::{Leaf, Program};
use mtgcalc_core::policy::{MulliganPlan, Policy};

pyo3::create_exception!(
    mtgcalc_native,
    StateLimitExceeded,
    PyException,
    "More live states than the limit; args[0] is the state count."
);

/// `(bit, checkpoint, kind, mask, op, value, lo, hi, demands)`
type PyLeaf = (
    u32,
    usize,
    u8,
    Vec<usize>,
    u8,
    u32,
    u32,
    u32,
    Vec<(Vec<usize>, u32)>,
);

/// The flattened query, in `mtgcalc.engine.native._flatten` order.
#[derive(FromPyObject)]
struct PyQuery(
    u32,
    Vec<u32>,
    u32,
    u32,
    Vec<u32>,
    Vec<PyLeaf>,
    Vec<Vec<i64>>,
    Vec<(usize, Vec<usize>)>,
    Vec<Vec<usize>>,
    u32,
);

/// The flattened mulligan plan: `(rules, keep_leaves, keep_program, bottoms, draw)`.
#[derive(FromPyObject)]
struct PyPlan(Vec<(Vec<usize>, u32)>, Vec<PyLeaf>, Vec<i64>, Vec<u32>, u32);

/// `(limit, early_resolution, retirement)`
#[derive(FromPyObject)]
struct PyOptions(usize, bool, bool);

fn leaves(raw: Vec<PyLeaf>, atoms: usize) -> Result<Vec<Leaf>, Error> {
    raw.into_iter()
        .map(|(bit, cp, kind, mask, op, value, lo, hi, demands)| {
            Leaf::new(bit, cp, kind, mask, op, value, lo, hi, demands, atoms)
        })
        .collect()
}

impl PyQuery {
    fn into_query(self) -> Result<Query, Error> {
        let PyQuery(
            deck_size,
            counts,
            pool,
            hand_size,
            batches,
            raw_leaves,
            outputs,
            observers,
            retire_after,
            reserved_bits,
        ) = self;
        let atoms = counts.len();
        Ok(Query {
            deck_size,
            counts,
            pool,
            hand_size,
            batches,
            leaves: leaves(raw_leaves, atoms)?,
            outputs: outputs
                .into_iter()
                .map(Program::new)
                .collect::<Result<_, _>>()?,
            observers,
            retire_after,
            reserved_bits,
        })
    }
}

impl PyPlan {
    fn into_plan(self, atoms: usize) -> Result<MulliganPlan, Error> {
        let PyPlan(rules, keep_leaves, keep, bottoms, draw) = self;
        Ok(MulliganPlan {
            policy: Policy::new(rules, atoms)?,
            keep_leaves: leaves(keep_leaves, atoms)?,
            keep: Program::new(keep)?,
            bottoms,
            draw,
        })
    }
}

impl From<PyOptions> for Options {
    fn from(PyOptions(limit, early_resolution, retirement): PyOptions) -> Self {
        Options {
            limit,
            early_resolution,
            retirement,
        }
    }
}

fn to_py(e: Error) -> PyErr {
    match e {
        Error::Limit(states) => StateLimitExceeded::new_err(states),
        other => PyValueError::new_err(other.to_string()),
    }
}

type InitState = (Vec<u16>, Vec<u16>, u64, BigUint);
type Snapshots = Vec<(usize, Vec<BigUint>, BigUint)>;
/// `(outputs, denominator, snapshots, peak)`
type RunOut = (Vec<BigUint>, BigUint, Snapshots, usize);
/// Per depth: `(keep_weight, hands_total, outputs, denominator)`
type DepthsOut = Vec<(BigUint, BigUint, Vec<BigUint>, BigUint)>;
/// Per depth, per hand: `(hand, weight, success, denominator)`
type HandsOut = Vec<Vec<(Vec<u16>, BigUint, BigUint, BigUint)>>;

/// Evaluates a query. Returns `(outputs, denominator, snapshots, peak)`.
#[pyfunction]
#[pyo3(signature = (query, init, options))]
fn run(
    py: Python<'_>,
    query: PyQuery,
    init: Option<(Vec<InitState>, BigUint, u32)>,
    options: PyOptions,
) -> PyResult<RunOut> {
    let q = query.into_query().map_err(to_py)?;
    let start = init.map(|(states, denominator, removed)| Start {
        states: states
            .into_iter()
            .map(|(seen, bottomed, bits, weight)| StartState {
                seen,
                bottomed,
                bits,
                weight,
            })
            .collect(),
        denominator,
        removed,
    });
    let opts = Options::from(options);
    let out = py
        .detach(|| api::run(&q, start.as_ref(), &opts))
        .map_err(to_py)?;
    let snapshots = out
        .snapshots
        .into_iter()
        .map(|s| (s.observer, s.numerators, s.denominator))
        .collect();
    Ok((out.outputs, out.denominator, snapshots, out.peak))
}

/// Every mulligan depth: `[(keep_weight, hands_total, outputs, denominator)]`.
#[pyfunction]
#[pyo3(signature = (query, plan, options))]
fn mulligan(
    py: Python<'_>,
    query: PyQuery,
    plan: PyPlan,
    options: PyOptions,
) -> PyResult<DepthsOut> {
    let q = query.into_query().map_err(to_py)?;
    let plan = plan.into_plan(q.counts.len()).map_err(to_py)?;
    let opts = Options::from(options);
    let depths = py
        .detach(|| api::mulligan_depths(&q, &plan, &opts))
        .map_err(to_py)?;
    Ok(depths
        .into_iter()
        .map(|d| (d.keep_weight, d.hands_total, d.outputs, d.denominator))
        .collect())
}

/// Per depth, every drawn hand: `[[(hand, weight, success, denominator)]]`.
#[pyfunction]
#[pyo3(signature = (query, plan, output, options))]
fn hand_values(
    py: Python<'_>,
    query: PyQuery,
    plan: PyPlan,
    output: usize,
    options: PyOptions,
) -> PyResult<HandsOut> {
    let q = query.into_query().map_err(to_py)?;
    let plan = plan.into_plan(q.counts.len()).map_err(to_py)?;
    let opts = Options::from(options);
    let values = py
        .detach(|| api::hand_values(&q, &plan, output, &opts))
        .map_err(to_py)?;
    Ok(values
        .into_iter()
        .map(|depth| {
            depth
                .into_iter()
                .map(|v| (v.hand, v.weight, v.success, v.denominator))
                .collect()
        })
        .collect())
}

/// Answers a probability request in the JSON format of ADR-0013 §3 (the same format as
/// `mtgcalc.model.serialization.to_dict`). Used by the conformance suite to check the
/// Rust model and compiler, which the web app runs, against Python.
#[pyfunction]
fn probability_json(py: Python<'_>, request: &str) -> String {
    let request = request.to_owned();
    py.detach(move || mtgcalc_core::json::probability(&request))
}

/// A text decklist in Python's `to_dict` format, or an error object (conformance).
#[pyfunction]
fn parse_deck_json(py: Python<'_>, text: &str) -> String {
    let text = text.to_owned();
    py.detach(move || mtgcalc_core::json::parse_deck(&text))
}

/// A rule (with its default turn) in Python's `to_dict` format, or an error object.
#[pyfunction]
fn parse_rule_json(text: &str, turn: i64) -> String {
    mtgcalc_core::json::parse_rule(text, turn)
}

/// The rule-language text of a `to_dict` query: `{"type": "Rule", "text": ...}`.
#[pyfunction]
fn format_rule_json(query: &str) -> String {
    mtgcalc_core::json::format_rule(query)
}

/// The core's tag and card-name normalization (Python's
/// `" ".join(s.split()).casefold()`), exposed for the Unicode conformance test.
#[pyfunction]
fn normalize_text(text: &str) -> String {
    mtgcalc_core::model::text::normalize(text)
}

/// The `mtgcalc_native` module.
#[pymodule]
fn mtgcalc_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(run, m)?)?;
    m.add_function(wrap_pyfunction!(mulligan, m)?)?;
    m.add_function(wrap_pyfunction!(hand_values, m)?)?;
    m.add_function(wrap_pyfunction!(probability_json, m)?)?;
    m.add_function(wrap_pyfunction!(normalize_text, m)?)?;
    m.add_function(wrap_pyfunction!(parse_deck_json, m)?)?;
    m.add_function(wrap_pyfunction!(parse_rule_json, m)?)?;
    m.add_function(wrap_pyfunction!(format_rule_json, m)?)?;
    m.add("UNICODE_VERSION", mtgcalc_core::model::UNICODE_VERSION)?;
    m.add(
        "StateLimitExceeded",
        m.py().get_type::<StateLimitExceeded>(),
    )?;
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
