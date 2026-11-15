//! Binomial coefficients as exact weights.

use crate::error::{Error, Result};
use crate::weight::{add, Weight};

/// Pascal's triangle restricted to `k <= max_k`, one entry per `(n, k)`.
///
/// Entries that overflow `W` are stored as `None`; requesting one yields
/// [`Error::Overflow`], which makes the driver retry with big integers.
pub struct Binom<W> {
    table: Vec<Vec<Option<W>>>,
}

impl<W: Weight> Binom<W> {
    /// Builds the table for `0 <= n <= max_n`, `0 <= k <= max_k`.
    #[must_use]
    pub fn new(max_n: usize, max_k: usize) -> Self {
        let mut table: Vec<Vec<Option<W>>> = Vec::with_capacity(max_n + 1);
        for n in 0..=max_n {
            let row = (0..=max_k)
                .map(|k| {
                    if k == 0 {
                        Some(W::one())
                    } else if k > n {
                        Some(W::zero())
                    } else {
                        let prev = &table[n - 1];
                        match (&prev[k - 1], &prev[k]) {
                            (Some(a), Some(b)) => add(a, b).ok(),
                            _ => None,
                        }
                    }
                })
                .collect();
            table.push(row);
        }
        Binom { table }
    }

    /// `C(n, k)` (zero when `k > n`).
    ///
    /// # Errors
    /// [`Error::Overflow`] if the value does not fit `W` or lies outside the table
    /// (callers size the table to cover every request).
    pub fn get(&self, n: u32, k: u32) -> Result<W> {
        if k > n {
            return Ok(W::zero());
        }
        match self
            .table
            .get(n as usize)
            .and_then(|row| row.get(k as usize))
        {
            Some(Some(v)) => Ok(v.clone()),
            _ => Err(Error::Overflow),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use num_bigint::BigUint;

    #[test]
    fn small_values() {
        let b: Binom<u128> = Binom::new(10, 10);
        assert_eq!(b.get(5, 2), Ok(10));
        assert_eq!(b.get(5, 0), Ok(1));
        assert_eq!(b.get(5, 6), Ok(0));
        assert_eq!(b.get(10, 5), Ok(252));
    }

    #[test]
    fn overflow_is_reported_and_bigint_is_exact() {
        let small: Binom<u128> = Binom::new(200, 100);
        assert_eq!(small.get(200, 100), Err(Error::Overflow));
        let big: Binom<BigUint> = Binom::new(200, 100);
        let c = big.get(200, 100).unwrap();
        assert_eq!(
            c.to_string(),
            "90548514656103281165404177077484163874504589675413336841320"
        );
    }
}
