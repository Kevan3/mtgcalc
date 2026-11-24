//! Leaf predicates and compiled Boolean programs (LLD §4.3, ADR-0006, MATH §7-§8).
//!
//! Both are validated when constructed, so evaluation never has to handle malformed
//! input: masks index existing atoms, bits fit in a `u64`, and programs are well-formed
//! postfix code that leaves exactly one value on the stack.

use crate::error::{invalid, Result};

/// Predicate bits are stored in a `u64`.
pub const MAX_BITS: u32 = 64;

/// A comparison operator, encoded as in the Python adapter (`0` is `==` ... `5` is `>=`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Comparison {
    /// `==`
    Eq,
    /// `!=`
    Ne,
    /// `<`
    Lt,
    /// `<=`
    Le,
    /// `>`
    Gt,
    /// `>=`
    Ge,
}

impl TryFrom<u8> for Comparison {
    type Error = crate::error::Error;

    fn try_from(code: u8) -> Result<Self> {
        Ok(match code {
            0 => Comparison::Eq,
            1 => Comparison::Ne,
            2 => Comparison::Lt,
            3 => Comparison::Le,
            4 => Comparison::Gt,
            5 => Comparison::Ge,
            other => return Err(invalid(format!("unknown comparison code {other}"))),
        })
    }
}

impl Comparison {
    fn holds(self, x: u32, v: u32) -> bool {
        match self {
            Comparison::Eq => x == v,
            Comparison::Ne => x != v,
            Comparison::Lt => x < v,
            Comparison::Le => x <= v,
            Comparison::Gt => x > v,
            Comparison::Ge => x >= v,
        }
    }
}

/// What a leaf tests about the seen atom counts.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Test {
    /// `sum(seen[mask]) <op> value`
    Compare {
        /// Atoms counted.
        mask: Vec<usize>,
        /// Operator.
        op: Comparison,
        /// Right-hand side.
        value: u32,
    },
    /// `lo <= sum(seen[mask]) <= hi`
    Between {
        /// Atoms counted.
        mask: Vec<usize>,
        /// Lower bound (inclusive).
        lo: u32,
        /// Upper bound (inclusive).
        hi: u32,
    },
    /// Distinct seen cards can meet every `(mask, need)` demand (Hall/Gale, MATH §8).
    Assign {
        /// The demands.
        demands: Vec<(Vec<usize>, u32)>,
    },
}

/// A predicate evaluated at one checkpoint into one bit.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Leaf {
    /// Bit index set when the test holds.
    pub bit: u32,
    /// Checkpoint index at which it is evaluated.
    pub checkpoint: usize,
    /// The test itself.
    pub test: Test,
}

impl Leaf {
    /// Builds a leaf from the adapter's encoding (`kind`: 0 compare, 1 between, 2 assign).
    ///
    /// # Errors
    /// [`crate::Error::Invalid`] for an unknown kind/operator, a bit outside the `u64`,
    /// an empty or oversized assignment, or an atom index `>= atoms`.
    #[allow(clippy::too_many_arguments)] // mirrors the flat wire format
    pub fn new(
        bit: u32,
        checkpoint: usize,
        kind: u8,
        mask: Vec<usize>,
        op: u8,
        value: u32,
        lo: u32,
        hi: u32,
        demands: Vec<(Vec<usize>, u32)>,
        atoms: usize,
    ) -> Result<Self> {
        if bit >= MAX_BITS {
            return Err(invalid(format!(
                "predicate bit {bit} does not fit in 64 bits"
            )));
        }
        let test = match kind {
            0 => Test::Compare {
                mask,
                op: Comparison::try_from(op)?,
                value,
            },
            1 => Test::Between { mask, lo, hi },
            2 if demands.is_empty() || demands.len() > 16 => {
                return Err(invalid("an assignment needs 1 to 16 demands"));
            }
            2 => Test::Assign { demands },
            other => return Err(invalid(format!("unknown leaf kind {other}"))),
        };
        let leaf = Leaf {
            bit,
            checkpoint,
            test,
        };
        if let Some(i) = leaf.atoms().find(|&i| i >= atoms) {
            return Err(invalid(format!(
                "leaf reads atom {i}, but there are only {atoms}"
            )));
        }
        Ok(leaf)
    }

    /// Every atom index the leaf reads.
    pub fn atoms(&self) -> Box<dyn Iterator<Item = usize> + '_> {
        match &self.test {
            Test::Compare { mask, .. } | Test::Between { mask, .. } => {
                Box::new(mask.iter().copied())
            }
            Test::Assign { demands } => {
                Box::new(demands.iter().flat_map(|(mask, _)| mask.iter().copied()))
            }
        }
    }

    /// Whether the test holds for the seen counts.
    #[must_use]
    pub fn holds(&self, seen: &[u16]) -> bool {
        let total = |mask: &[usize]| mask.iter().map(|&i| u32::from(seen[i])).sum::<u32>();
        match &self.test {
            Test::Compare { mask, op, value } => op.holds(total(mask), *value),
            Test::Between { mask, lo, hi } => (*lo..=*hi).contains(&total(mask)),
            Test::Assign { demands } => hall_feasible(demands, seen),
        }
    }
}

/// Bitset of the leaves that hold on `seen`.
#[must_use]
pub fn leaf_bits<'a>(leaves: impl IntoIterator<Item = &'a Leaf>, seen: &[u16]) -> u64 {
    leaves
        .into_iter()
        .filter(|leaf| leaf.holds(seen))
        .fold(0, |bits, leaf| bits | (1u64 << leaf.bit))
}

/// Can distinct seen cards satisfy every `(mask, need)` demand?
///
/// Hall's condition with multiplicities: for every non-empty subset of demands, the total
/// need is at most the number of seen cards in atoms adjacent to the subset.
fn hall_feasible(demands: &[(Vec<usize>, u32)], seen: &[u16]) -> bool {
    (1u32..(1u32 << demands.len())).all(|subset| {
        let mut need = 0u32;
        let mut adjacent = vec![false; seen.len()];
        for (j, (mask, n)) in demands.iter().enumerate() {
            if subset >> j & 1 == 1 {
                need += n;
                for &i in mask {
                    adjacent[i] = true;
                }
            }
        }
        let supply: u32 = adjacent
            .iter()
            .zip(seen)
            .filter(|(adj, _)| **adj)
            .map(|(_, &s)| u32::from(s))
            .sum();
        need <= supply
    })
}

/// Opcodes of the postfix Boolean bytecode (must match `mtgcalc.compile.logic`).
pub mod op {
    /// `BIT i`: push predicate bit `i`.
    pub const BIT: i64 = 0;
    /// `CONST b`: push a constant.
    pub const CONST: i64 = 1;
    /// `NOT`: negate the top value.
    pub const NOT: i64 = 2;
    /// `AND n`: conjunction of the top `n` values.
    pub const AND: i64 = 3;
    /// `OR n`: disjunction of the top `n` values.
    pub const OR: i64 = 4;
    /// `XOR`: exclusive or of the top two values.
    pub const XOR: i64 = 5;
    /// `IMPLIES`: `a -> b` for the top two values `a`, `b`.
    pub const IMPLIES: i64 = 6;
    /// `ATLEAST k n`: at least `k` of the top `n` values are true.
    pub const ATLEAST: i64 = 7;
    /// `EXACTLY k n`: exactly `k` of the top `n` values are true.
    pub const EXACTLY: i64 = 8;

    /// Number of operands following an opcode.
    #[must_use]
    pub fn arity(code: i64) -> usize {
        match code {
            BIT | CONST | AND | OR => 1,
            ATLEAST | EXACTLY => 2,
            _ => 0,
        }
    }
}

/// A validated postfix Boolean program over predicate bits (ADR-0006).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Program(Vec<i64>);

impl Program {
    /// Validates `code`: known opcodes, operands present, bit indexes below 64, positive
    /// operand counts, no stack underflow, and exactly one result.
    ///
    /// # Errors
    /// [`crate::Error::Invalid`] describing the first problem found.
    pub fn new(code: Vec<i64>) -> Result<Self> {
        let mut depth: usize = 0;
        let mut pc = 0;
        while pc < code.len() {
            let opcode = code[pc];
            if !(op::BIT..=op::EXACTLY).contains(&opcode) {
                return Err(invalid(format!("unknown opcode {opcode} at {pc}")));
            }
            let arity = op::arity(opcode);
            if arity > 0 && pc + arity >= code.len() {
                return Err(invalid(format!(
                    "opcode {opcode} at {pc} is missing operands"
                )));
            }
            let operand = |k: usize| code[pc + k];
            let (pops, pushes) = match opcode {
                op::BIT if !(0..i64::from(MAX_BITS)).contains(&operand(1)) => {
                    return Err(invalid(format!("bit index {} out of range", operand(1))));
                }
                op::BIT | op::CONST => (0, 1),
                op::NOT => (1, 1),
                op::XOR | op::IMPLIES => (2, 1),
                _ => {
                    let n = if matches!(opcode, op::AND | op::OR) {
                        operand(1)
                    } else {
                        operand(2)
                    };
                    let n = usize::try_from(n)
                        .ok()
                        .filter(|&n| n >= 1)
                        .ok_or_else(|| invalid(format!("bad operand count at {pc}")))?;
                    (n, 1)
                }
            };
            depth = depth
                .checked_sub(pops)
                .ok_or_else(|| invalid(format!("stack underflow at {pc}")))?
                + pushes;
            pc += 1 + arity;
        }
        if depth != 1 {
            return Err(invalid(format!(
                "program leaves {depth} values, expected 1"
            )));
        }
        Ok(Program(code))
    }

    /// `self AND BIT(bit)` (postfix concatenation, Python's `conjoin_bit`, ADR-0006).
    ///
    /// # Errors
    /// [`crate::Error::Invalid`] if `bit` does not fit in 64 bits.
    pub fn conjoin_bit(&self, bit: u32) -> Result<Program> {
        let mut code = self.0.clone();
        code.extend([op::BIT, i64::from(bit), op::AND, 2]);
        Program::new(code)
    }

    /// Two-valued evaluation.
    ///
    /// # Panics
    /// Never: the program was validated by [`Program::new`].
    #[must_use]
    pub fn eval(&self, bits: u64) -> bool {
        let code = &self.0;
        let mut stack: Vec<bool> = Vec::with_capacity(8);
        let mut pc = 0;
        while pc < code.len() {
            let opcode = code[pc];
            match opcode {
                op::BIT => stack.push(bits >> code[pc + 1] & 1 == 1),
                op::CONST => stack.push(code[pc + 1] != 0),
                op::NOT => {
                    let v = stack.pop().expect("validated");
                    stack.push(!v);
                }
                op::XOR | op::IMPLIES => {
                    let b = stack.pop().expect("validated");
                    let a = stack.pop().expect("validated");
                    stack.push(if opcode == op::XOR { a != b } else { !a || b });
                }
                _ => {
                    let (k, n) = counts(code, pc);
                    let args = stack.split_off(stack.len() - n);
                    let t = args.iter().filter(|&&a| a).count();
                    stack.push(match opcode {
                        op::AND => t == n,
                        op::OR => t > 0,
                        op::ATLEAST => t >= k,
                        _ => t == k,
                    });
                }
            }
            pc += 1 + op::arity(opcode);
        }
        stack[0]
    }

    /// Kleene strong three-valued evaluation: bit `i` is unknown unless set in `known`.
    /// A decided result equals [`Program::eval`] for every completion (MATH §7.3).
    ///
    /// # Panics
    /// Never: the program was validated by [`Program::new`].
    #[must_use]
    pub fn eval3(&self, bits: u64, known: u64) -> Option<bool> {
        let code = &self.0;
        let mut stack: Vec<Option<bool>> = Vec::with_capacity(8);
        let mut pc = 0;
        while pc < code.len() {
            let opcode = code[pc];
            match opcode {
                op::BIT => {
                    let i = code[pc + 1];
                    stack.push((known >> i & 1 == 1).then_some(bits >> i & 1 == 1));
                }
                op::CONST => stack.push(Some(code[pc + 1] != 0)),
                op::NOT => {
                    let v = stack.pop().expect("validated");
                    stack.push(v.map(|x| !x));
                }
                op::XOR => {
                    let b = stack.pop().expect("validated");
                    let a = stack.pop().expect("validated");
                    stack.push(a.zip(b).map(|(x, y)| x != y));
                }
                op::IMPLIES => {
                    let b = stack.pop().expect("validated");
                    let a = stack.pop().expect("validated");
                    stack.push(match (a, b) {
                        (Some(false), _) | (_, Some(true)) => Some(true),
                        (Some(true), Some(false)) => Some(false),
                        _ => None,
                    });
                }
                _ => {
                    let (k, n) = counts(code, pc);
                    let args = stack.split_off(stack.len() - n);
                    let t = args.iter().filter(|&&a| a == Some(true)).count();
                    let u = args.iter().filter(|a| a.is_none()).count();
                    let (k, decided_false) = match opcode {
                        op::AND => (n, t + u < n),
                        op::OR => (1, t + u < 1),
                        op::ATLEAST => (k, t + u < k),
                        _ => (k, t > k || t + u < k),
                    };
                    stack.push(if decided_false {
                        Some(false)
                    } else if opcode == op::EXACTLY {
                        (u == 0).then_some(true)
                    } else if t >= k {
                        Some(true)
                    } else {
                        None
                    });
                }
            }
            pc += 1 + op::arity(opcode);
        }
        stack[0]
    }
}

/// `(k, n)` operands of AND/OR (k unused) and ATLEAST/EXACTLY at `pc`.
fn counts(code: &[i64], pc: usize) -> (usize, usize) {
    let as_usize = |v: i64| usize::try_from(v).unwrap_or(0);
    if matches!(code[pc], op::AND | op::OR) {
        (0, as_usize(code[pc + 1]))
    } else {
        (as_usize(code[pc + 1]), as_usize(code[pc + 2]))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn prog(code: &[i64]) -> Program {
        Program::new(code.to_vec()).unwrap()
    }

    fn table(p: &Program, bits: u32) -> Vec<bool> {
        (0..1u64 << bits).map(|b| p.eval(b)).collect()
    }

    #[test]
    fn two_valued_truth_tables() {
        let (t, f) = (true, false);
        assert_eq!(table(&prog(&[0, 0, 0, 1, 3, 2]), 2), [f, f, f, t]);
        assert_eq!(table(&prog(&[0, 0, 0, 1, 4, 2]), 2), [f, t, t, t]);
        assert_eq!(table(&prog(&[0, 0, 0, 1, 5]), 2), [f, t, t, f]);
        assert_eq!(table(&prog(&[0, 0, 0, 1, 6]), 2), [t, f, t, t]);
        assert_eq!(table(&prog(&[0, 0, 2]), 1), [t, f]);
        assert_eq!(
            table(&prog(&[0, 0, 0, 1, 0, 2, 7, 2, 3]), 3),
            [f, f, f, t, f, t, t, t]
        );
        assert_eq!(
            table(&prog(&[0, 0, 0, 1, 0, 2, 8, 1, 3]), 3),
            [f, t, t, f, t, f, f, f]
        );
        assert!(prog(&[1, 1]).eval(0));
    }

    /// Every program over 3 bits up to a small size: a decided three-valued result must
    /// agree with every completion of the unknown bits (MATH §7.3).
    #[test]
    fn three_valued_evaluation_is_sound() {
        let programs: Vec<Vec<i64>> = vec![
            vec![0, 0, 0, 1, 3, 2],
            vec![0, 0, 0, 1, 4, 2],
            vec![0, 0, 0, 1, 5],
            vec![0, 0, 0, 1, 6],
            vec![0, 0, 2, 0, 1, 6],
            vec![0, 0, 0, 1, 0, 2, 7, 2, 3],
            vec![0, 0, 0, 1, 0, 2, 8, 1, 3],
            vec![0, 0, 0, 1, 0, 2, 8, 0, 3],
            vec![0, 0, 0, 1, 3, 2, 0, 2, 4, 2, 2],
        ];
        for code in programs {
            let p = Program::new(code).unwrap();
            for known in 0..8u64 {
                for bits in 0..8u64 {
                    let Some(verdict) = p.eval3(bits, known) else {
                        continue;
                    };
                    for fill in 0..8u64 {
                        let completed = (bits & known) | (fill & !known);
                        assert_eq!(p.eval(completed), verdict);
                    }
                }
                for bits in 0..8u64 {
                    assert_eq!(p.eval3(bits, 0b111), Some(p.eval(bits)));
                }
            }
        }
    }

    #[test]
    fn malformed_programs_are_rejected() {
        for bad in [
            vec![],
            vec![9],
            vec![0],
            vec![0, 64],
            vec![2],
            vec![0, 0, 0, 1],
            vec![0, 0, 3, 0],
            vec![0, 0, 3, 2],
        ] {
            assert!(
                Program::new(bad.clone()).is_err(),
                "{bad:?} should be rejected"
            );
        }
    }

    #[test]
    fn leaves_validate_and_evaluate() {
        let ge = Leaf::new(3, 0, 0, vec![0, 1], 5, 3, 0, 0, vec![], 2).unwrap();
        assert!(ge.holds(&[2, 1]) && !ge.holds(&[1, 1]));
        let between = Leaf::new(0, 0, 1, vec![0], 0, 0, 2, 4, vec![], 1).unwrap();
        assert!(between.holds(&[2]) && !between.holds(&[5]));
        assert_eq!(leaf_bits(&[ge, between], &[2, 1]), 0b1001);
        assert!(Leaf::new(64, 0, 0, vec![], 0, 0, 0, 0, vec![], 1).is_err());
        assert!(Leaf::new(0, 0, 0, vec![5], 0, 0, 0, 0, vec![], 2).is_err());
        assert!(Leaf::new(0, 0, 0, vec![], 9, 0, 0, 0, vec![], 1).is_err());
        assert!(Leaf::new(0, 0, 2, vec![], 0, 0, 0, 0, vec![], 1).is_err());
        assert!(Leaf::new(0, 0, 7, vec![], 0, 0, 0, 0, vec![], 1).is_err());
    }

    /// MATH §8: two lands + one MDFC (land/ramp) cannot give 3 lands AND 1 ramp.
    #[test]
    fn exclusive_assignment_mdfc_example() {
        // atom 0 = pure land, atom 1 = MDFC (land and ramp)
        let infeasible = vec![(vec![0, 1], 3), (vec![1], 1)];
        let feasible = vec![(vec![0, 1], 2), (vec![1], 1)];
        assert!(!hall_feasible(&infeasible, &[2, 1]));
        assert!(hall_feasible(&feasible, &[2, 1]));
    }
}
