//! Exact non-negative integer weights with checked arithmetic (ADR-0002).
//!
//! The dynamic program is generic over [`Weight`]. It first runs with `u128` (fast) and,
//! if any operation would overflow, the drivers in [`crate::api`] re-run it with
//! [`BigUint`] (never overflows). Results are therefore always exact.

use num_bigint::BigUint;
use num_traits::{One, ToPrimitive, Zero};

use crate::error::{Error, Result};

/// An exact non-negative integer type usable as a DP weight.
pub trait Weight: Clone + Send + Sync + std::fmt::Debug + PartialEq {
    /// The additive identity.
    fn zero() -> Self;
    /// The multiplicative identity.
    fn one() -> Self;
    /// Converts from an arbitrary-precision integer (`None` if it does not fit).
    fn from_big(x: &BigUint) -> Option<Self>;
    /// `self + other`, or `None` on overflow.
    fn checked_add(&self, other: &Self) -> Option<Self>;
    /// `self * other`, or `None` on overflow.
    fn checked_mul(&self, other: &Self) -> Option<Self>;
    /// Whether the value is zero.
    fn is_zero(&self) -> bool;
    /// Converts to an arbitrary-precision integer.
    fn to_big(&self) -> BigUint;
}

impl Weight for u128 {
    fn zero() -> Self {
        0
    }
    fn one() -> Self {
        1
    }
    fn from_big(x: &BigUint) -> Option<Self> {
        x.to_u128()
    }
    fn checked_add(&self, other: &Self) -> Option<Self> {
        u128::checked_add(*self, *other)
    }
    fn checked_mul(&self, other: &Self) -> Option<Self> {
        u128::checked_mul(*self, *other)
    }
    fn is_zero(&self) -> bool {
        *self == 0
    }
    fn to_big(&self) -> BigUint {
        BigUint::from(*self)
    }
}

impl Weight for BigUint {
    fn zero() -> Self {
        <BigUint as Zero>::zero()
    }
    fn one() -> Self {
        <BigUint as One>::one()
    }
    fn from_big(x: &BigUint) -> Option<Self> {
        Some(x.clone())
    }
    fn checked_add(&self, other: &Self) -> Option<Self> {
        Some(self + other)
    }
    fn checked_mul(&self, other: &Self) -> Option<Self> {
        Some(self * other)
    }
    fn is_zero(&self) -> bool {
        Zero::is_zero(self)
    }
    fn to_big(&self) -> BigUint {
        self.clone()
    }
}

/// `a + b`, failing with [`Error::Overflow`].
pub(crate) fn add<W: Weight>(a: &W, b: &W) -> Result<W> {
    a.checked_add(b).ok_or(Error::Overflow)
}

/// `a * b`, failing with [`Error::Overflow`].
pub(crate) fn mul<W: Weight>(a: &W, b: &W) -> Result<W> {
    a.checked_mul(b).ok_or(Error::Overflow)
}

/// Converts an input weight, failing with [`Error::Overflow`] if it does not fit `W`.
pub(crate) fn from_big<W: Weight>(x: &BigUint) -> Result<W> {
    W::from_big(x).ok_or(Error::Overflow)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn u128_overflow_is_detected() {
        assert_eq!(add(&u128::MAX, &1), Err(Error::Overflow));
        assert_eq!(mul(&(u128::MAX / 2 + 1), &2), Err(Error::Overflow));
        assert_eq!(mul(&3u128, &4), Ok(12));
    }

    #[test]
    fn biguint_never_overflows_and_round_trips() {
        let big = BigUint::from(u128::MAX);
        let sum: BigUint = add(&big, &big).unwrap();
        assert_eq!(sum, BigUint::from(u128::MAX) * 2u32);
        assert_eq!(from_big::<u128>(&sum), Err(Error::Overflow));
        assert_eq!(from_big::<u128>(&BigUint::from(7u32)), Ok(7));
        assert_eq!(7u128.to_big(), BigUint::from(7u32));
    }
}
