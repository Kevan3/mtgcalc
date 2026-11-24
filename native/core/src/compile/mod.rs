//! Compilation (port of `mtgcalc.compile`): atomize the deck over the selectors a
//! question uses, plan the draws between checkpoints, and compile conditions into engine
//! leaves and postfix programs; resolve mulligan bottom policies into engine plans.

pub mod atomizer;
pub mod compiler;
pub mod policy;
pub mod schedule;

pub use atomizer::{atomize, AtomTable};
pub use compiler::{compile_predicate, compile_query, CompileRequest, CompiledQuery, MAX_DEMANDS};
pub use policy::{build_plan, lower_bounds};
pub use schedule::{plan, BatchPlan};
