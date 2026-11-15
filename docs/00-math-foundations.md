# MTG Super Calculator: Mathematical Foundations

| | |
|---|---|
| Status | v1.0 (research baseline for the design documents) |
| Audience | Implementers and reviewers of the calculation engine |
| Used by | `01-requirements.md`, `02-high-level-design.md`, `03-low-level-design.md`, `04-test-plan.md` |

This document sets out the probability theory the engine relies on. Each result is either standard (with a reference) or derived here with a proof sketch. Every numerical claim marked ✔ was checked by an independent brute-force calculation in exact rational arithmetic. The design treats these results as **contracts**: the test plan (`04-test-plan.md`) turns each one into an executable check.

---

## 1. Notation

| Symbol | Meaning |
|---|---|
| N | Library size at game start (the commander is excluded) |
| K, Kᵢ | Number of cards in a category or atom *i* |
| n | Number of cards seen (opening hand plus draws) |
| X, Xᵢ | Number of category or atom *i* cards among the seen cards |
| C(a, b) | Binomial coefficient. It is 0 if b < 0, b > a, or a < 0. |
| m | Number of tracked atoms (disjoint categories). The untracked rest is the **pool**. |
| π | A uniformly random permutation of the library (the shuffle) |

---

## 2. The shuffle model and exchangeability

**Model.** A shuffled library is a uniformly random permutation π of the N cards. Cards with the same name or tags are interchangeable for counting purposes. Drawing cards means reading positions 1, 2, 3, … of π.

**Theorem 2.1 (positions are uniform subsets).** For any fixed set P of positions with |P| = n, the set of cards at positions P is a uniformly random n-subset of the library.
*Proof.* Every n-subset S is mapped to P by exactly n!(N − n)! permutations, which is the same number for every S. ∎

**Consequences used by the design**

1. **Draw order does not matter for one checkpoint.** "By turn T" depends only on how many cards have been seen, n(T) = hand + draws through T. The answer is one hypergeometric or multivariate hypergeometric evaluation with that n. Being on the play or on the draw only changes n. In particular, P_draw(turn t) = P_play(turn t + 1) when one card is drawn per turn. This is a test invariant.
2. **Disjoint segments.** The positions split into consecutive segments (opening hand, turn-2 draw, …, rest of library). The joint counts of each atom in each segment have the distribution of an **r × c contingency table with fixed margins**. The row margins are the atom totals Kᵢ and the column margins are the segment sizes s_j:

   P({x_ij}) = (∏ᵢ Kᵢ!)(∏ⱼ s_j!) / (N! ∏ᵢⱼ x_ij!)

   This is the distribution behind Fisher's exact test for r × c tables [Fisher 1922; Agresti 2013, §3.5]. ✔ It agrees with the sequential computation in §5 on reference A5 (0.78865447).
3. **Conditional exchangeability.** Given the contents of the first n positions, the remaining N − n cards are in uniformly random order. This justifies (a) treating each draw batch as a fresh hypergeometric draw from what remains (§5), and (b) the mulligan model (§9).

---

## 3. Univariate hypergeometric distribution

X ~ Hyp(N, K, n): the number of successes in n draws without replacement from N cards, K of which are successes.

| Property | Formula |
|---|---|
| PMF | P(X = k) = C(K, k) · C(N − K, n − k) / C(N, n) |
| Support | max(0, n − (N − K)) ≤ k ≤ min(n, K) |
| Normalization (Vandermonde) | Σₖ C(K, k) C(N − K, n − k) = C(N, n) |
| Symmetry | Hyp(N, K, n) and Hyp(N, n, K) have the same PMF (swap the roles of K and n) |
| Complement | X ~ Hyp(N, K, n) ⇒ n − X ~ Hyp(N, N − K, n) |
| Mean | E[X] = nK/N |
| Variance | Var[X] = n · (K/N) · ((N − K)/N) · ((N − n)/(N − 1)) (binomial variance times the finite-population correction) |
| Ratio recursion | P(k+1)/P(k) = (K − k)(n − k) / ((k + 1)(N − K − n + k + 1)) |
| Mode | ⌊(n + 1)(K + 1)/(N + 2)⌋ |

✔ For N = 60, K = 24, n = 7: the exact mean is 14/5 and the exact variance is 2226/1475. Both formulas match summation over the PMF.

The ratio recursion lets a PMF row be built with O(n) rational multiplications. It is used as an independent cross-check of the binomial path.

**Why exact arithmetic.** Floating-point evaluation via log-gamma loses relative precision in the far tails, and 1 − P(…) suffers cancellation when P ≈ 1. Exact integers avoid both. They stay small: C(100, 50) has 97 bits ✔, and Python integers have arbitrary precision. Converting an exact `Fraction` to `float` with true division of two Python ints is correctly rounded. The ±ulp tolerance in floating-point tests therefore comes only from the formulas used for comparison, never from the engine.

---

## 4. Multivariate hypergeometric distribution

Let the library be split into disjoint categories with sizes K₁, …, K_m and a pool K₀ = N − ΣKᵢ. Then (X₁, …, X_m) ~ MVHyp(N; K; n):

  P(X = x) = C(K₀, n − Σxᵢ) · ∏ᵢ C(Kᵢ, xᵢ) / C(N, n)

| Property | Statement | Used for |
|---|---|---|
| Marginals | Xᵢ ~ Hyp(N, Kᵢ, n) | Tests, and the univariate fast path |
| **Aggregation (lumping)** | Merging any categories gives another MVHyp. For example, (X₁ + X₂, X₃, …) ~ MVHyp(N; K₁ + K₂, K₃, …; n). | Atomization (§6) and atom retirement (§5.3) are exact |
| **Conditioning** | Given X₁ = x₁, the other counts are MVHyp(N − K₁; K₂, …; n − x₁) | Sequential DP and enumeration order |
| Chu–Vandermonde | Σ over x with Σx ≤ n of ∏ᵢ C(Kᵢ, xᵢ) · C(K₀, n − Σx) = C(N, n) | Normalization tests; exactness of early resolution |
| Generating function | ∏ᵢ (1 + tᵢ z)^Kᵢ · (1 + z)^K₀: the coefficient of z^n ∏ tᵢ^xᵢ is the numerator of P(X = x) | Alternative derivation; convolution view of the DP |
| Means | E[Xᵢ] = nKᵢ/N | Tests |
| Covariance | Cov(Xᵢ, Xⱼ) = −n (Kᵢ/N)(Kⱼ/N)(N − n)/(N − 1) for i ≠ j (counts are negatively correlated) | Tests; the explanation for why "independent" products are wrong |

References: Johnson, Kotz & Balakrishnan, *Discrete Multivariate Distributions* (1997), ch. 39; QuantEcon, "Multivariate Hypergeometric Distribution".

**Enumeration size.** The number of count vectors x with 0 ≤ xᵢ ≤ Kᵢ and Σx ≤ n is at most C(n + m, m). For n = 17 and m = 4 this is 5,985 ✔. That small number is why exact enumeration is practical for the deck sizes and group counts this tool targets.

---

## 5. Sequential draws (multi-turn and path-dependent events)

### 5.1 Markov-chain formulation

Let s_t be the vector of atom counts seen after step t. By §2, Consequence 3, drawing a batch of b cards from a library whose remaining atom counts are r = K − s (pool remainder r₀) produces increments d with

  P(d | s) = C(r₀, b − Σd) · ∏ᵢ C(rᵢ, dᵢ) / C(L, b),   L = N − (cards removed so far)

So (s_t) is a Markov chain: a multivariate Pólya urn without replacement. By the chain rule, the probability of a full path is the product of its transition probabilities. Summed over paths, this equals the contingency-table formula in §2.

### 5.2 Integer weights with a shared denominator

The denominator C(L, b) at each step depends only on the step, not on the state. So the engine keeps an **integer numerator per state** and one shared denominator D = C(N, h) · ∏_steps C(L_t, b_t). Each final probability is (Σ numerators over accepting states)/D, a single exact division. This is decision D2 in the HLD.

### 5.3 Exact state reductions

1. **Merging.** Two paths that reach the same (seen counts, bottomed counts, predicate bits) have identical futures, so their weights add.
2. **Atom retirement.** If no predicate at a later checkpoint reads atom *i*, aggregation (§4) lets the engine merge *i* into the pool with no error. Only the pool's total remaining count affects future transitions.
3. **Early resolution.** If a state's outcome is already decided (§7.3), its future does not matter. By Chu–Vandermonde, the sum over all future paths of the products of transition numerators equals ∏_{future steps} C(L_t, b_t). So the engine can add `weight × ∏ future denominators` to the accepted or rejected total and drop the state. This is exact.

### 5.4 Path-dependent events need the joint distribution

Because counts are negatively correlated (§4), multiplying per-turn probabilities is wrong.

| Example (60 cards, 24 lands, on the play) | Exact | Product of marginals |
|---|---|---|
| A5: ≥1 land in the opening hand ∧ ≥2 by T2 ∧ ≥3 by T3 | 0.78865447 ✔ | 0.70206420 ✔ |
| A7: ≥2 lands in the opening hand ∧ ≥4 by T4 | 0.62263468 ✔ (= 209193119/335980515) | 0.54165747 ✔ |

A5 also shows a **monotone-implication collapse**. With one draw per turn, "≥3 lands in 9 cards" already implies "≥2 in 8" and "≥1 in 7". The joint probability therefore equals the last marginal (✔ 0.78865447 = P(X₉ ≥ 3)). The engine does not need to exploit this, but the test plan uses it as an invariant. A7 is a genuinely path-dependent event, so it is the main regression test for sequential evaluation.

### 5.5 Complexity

The number of live states after a step is at most ∏ᵢ (min(Kᵢ, n) + 1) × (number of distinct predicate-bit patterns), where n is the cards seen so far. One step costs |states| × |transitions per state|. The transitions per state are at most C(b + m, m), which is small because b is usually 1–3. Atom retirement and early resolution only ever shrink these bounds.

---

## 6. Overlapping groups: atoms

Tags overlap. A modal double-faced card can be both a `land` and a `ramp` spell. For g referenced groups, assign every card the membership signature σ ∈ {0, 1}^g. Cards with the same σ form an **atom**, and atoms are disjoint, so their counts follow MVHyp (§4). Each group count is a **linear image** of the atom counts:

  G_j = Σ_{σ : σ_j = 1} X_σ

The joint distribution of (G_1, …, G_g) is *not* multivariate hypergeometric. Groups overlap, and the group counts can sum to more than n. It is computed exactly by pushing the atom distribution through this linear map. The number of atoms is at most min(2^g, number of distinct cards). In practice it is much smaller, because most signature combinations do not occur.

**Counting semantics.** By default a card counts toward every group it belongs to ("shared" semantics). This is the right reading for questions like "do I have a land?" and "do I have a ramp spell?" asked independently. For "can my hand satisfy all these needs at once, using each card once?", see §8.

---

## 7. Logical conditions

### 7.1 Events as sets of count vectors

At one checkpoint, a condition is a subset A of the count-vector space, and P(A) = Σ_{x ∈ A} P(X = x). AND, OR, and NOT are intersection, union, and complement, so P(A ∪ B) = P(A) + P(B) − P(A ∩ B) (inclusion–exclusion) and P(¬A) = 1 − P(A). These identities are test invariants. **A Boolean combination is not determined by the marginal probabilities**, so the engine evaluates conditions per state on the joint distribution and never combines probabilities.

### 7.2 Multiple checkpoints

A condition that spans checkpoints is a subset of path space. The engine evaluates each leaf predicate when its checkpoint is reached and stores the result as a bit. It then evaluates the Boolean formula over those bits at the end (§5.3 justifies the state merging).

### 7.3 Three-valued (Kleene) evaluation for early resolution

Before all bits are known, the engine evaluates the formula in Kleene's strong three-valued logic {T, F, U}: F ∧ U = F, T ∨ U = T, ¬U = U, and "at least k of n" is T once k are true and F once fewer than k can still become true. **Soundness:** if the three-valued result is T (or F), then every way of filling in the unknown bits gives T (or F) in two-valued logic. This follows from the monotonicity of the Kleene connectives in the information order [Kleene 1952, §64]. So resolving early never changes the answer. The test plan checks results with early resolution on and off.

### 7.4 Conditional probability

P(A | B) = P(A ∩ B)/P(B). It is undefined when P(B) = 0. One engine run with two outputs gives both numerators over the same denominator, so the result is the exact ratio of two integers. Karsten's widely used colored-source methodology is exactly this kind of query. It asks for P(enough colored sources | enough lands) and ignores games where the land count fails [Karsten 2018/2022, as described by secondary sources]. ✔ Example: 60 cards, 24 lands of which 14 are red sources, 9 cards seen. P(≥1 red ∧ ≥3 lands) = 0.76637747, P(≥3 lands) = 0.78865447, and the conditional probability is 0.97175316.

---

## 8. Exclusive assignment: Hall's theorem with multiplicities

Requirement FR-34 asks whether the seen cards can meet demands (G_1 ≥ d_1, …, G_g ≥ d_g) with each card used at most once. This is a bipartite supply–demand (transportation) feasibility problem. Each atom σ has supply x_σ and can serve demand *j* iff σ_j = 1.

**Theorem 8.1 (Hall/Gale supply–demand).** A feasible assignment exists iff for every subset S of demands,

  Σ_{j ∈ S} d_j ≤ Σ_{σ : σ_j = 1 for some j ∈ S} x_σ.

This is Hall's marriage theorem generalized to multiplicities, equivalently max-flow/min-cut on the bipartite network [Hall 1935; Gale 1957; Schrijver, *Combinatorial Optimization*, §21]. Checking 2^g − 1 subsets is cheap for g ≤ 6. A max-flow check gives the same answer and serves as the test oracle.

✔ Example: hand {2 pure lands, 1 MDFC land/ramp}. "lands ≥ 3 ∧ ramp ≥ 1" is true under shared counting but **false** under exclusive assignment (S = {land, ramp}: need 4, supply 3).

---

## 9. Mulligans

### 9.1 Rules being modelled

- **London mulligan:** draw 7. After the m-th mulligan, put `bottom(m)` cards from hand on the bottom of the library, where `bottom(m) = max(0, m − F)` and F is the number of free mulligans.
- **Free mulligan:** in multiplayer formats, the first mulligan does not count toward the cards put on the bottom (F = 1). Duel formats use F = 0. Rule numbering has varied across Comprehensive Rules revisions, so the design takes F as a parameter rather than encoding a rule number.
- **Draw on turn 1:** in two-player games the starting player skips their first draw. In other multiplayer games (other than Two-Headed Giant) no player skips it. The design exposes this as `GameConfig.on_play` / draw overrides and does not hard-code it.

### 9.2 Independence across mulligans and the hand after bottoming

Each mulligan is a fresh uniform shuffle, so the 7-card draws at depths 0, 1, … are independent and identically distributed. At a fixed depth, the 7-card hand H is a uniform 7-subset (Theorem 2.1). The bottom policy is a deterministic function B(H), so the kept hand is H − B(H). The cards put on the bottom sit below the other N − 7 cards. By conditional exchangeability (§2.3), later draws from the top are a uniformly random ordering of the N − 7 cards not in H. This holds as long as total draws ≤ N − 7 (validated). **The library to draw from is the complement of the 7-card hand, not of the kept hand.**

### 9.3 Strategy-level probability (law of total probability)

Let k_m = P(keep at depth m), with k_M = 1 because the last allowed depth is forced. Let a_m = P(success ∧ keep at depth m), where both events are evaluated from depth m's own hand. Then

  P(reach 0) = 1,   P(reach m+1) = P(reach m)(1 − k_m),   P(success) = Σ_m P(reach m) · a_m.

Also E[mulligans] = Σ_m m · P(reach m) k_m and E[hand size] = Σ_m (7 − bottom(m)) · P(reach m) k_m.

**Closed-form check (✔ A3).** Let the keep rule and the success condition both be "≥1 copy of X in the kept hand", with a bottom policy that protects X. Bottoming never removes the only copy as long as the hand keeps at least one card. So a_m = k_m = p, the probability that 7 cards contain X, and P(success) = 1 − (1 − p)^(M+1). With N = 60, four copies, and M = 1: 0.63939930. For one desired card, the London rule makes a mulligan to *any* size as good as a fresh 7 at finding the card. This is the main qualitative difference from the older Vancouver and Paris rules (compare the jump from 53% to 63% for "1 of 4 & 1 of 10" in [Mikonen 2019]).

### 9.4 Bottom policy

The design uses the **user-given groups in priority order** (decision Q3). Since B(H) depends only on the atom composition of H, it can be computed once per composition, and there are at most C(7 + m, m) compositions (330 for m = 4).

### 9.5 Optimal keep strategy (finite-horizon optimal stopping)

For a fixed bottom policy, let s_m(H) = P(success | the 7-card hand at depth m is H and it is kept). Mulliganing is a finite-horizon optimal-stopping problem, solved by backward induction [Bellman 1957; Ferguson, *Optimal Stopping and Applications*, ch. 2]:

  V_M = E_H[s_M(H)],   V_m = E_H[max(s_m(H), V_{m+1})],   keep at m ⟺ s_m(H) ≥ V_{m+1}.

V_0 is the best success probability any keep rule can achieve with that bottom policy, so it is an **upper bound** for every user keep rule (a test invariant). Computing s_m(H) needs one engine run per (kept, bottomed) composition. This is affordable with memoization because the compositions are few.

---

## 10. Monotonicity and the optimizer

### 10.1 Univariate: monotone likelihood ratio in K

For Hyp(N, K, n),

  P_{K+1}(k) / P_K(k) = [(K + 1)/(K + 1 − k)] · [(N − K − n + k)/(N − K)],

and both factors increase in k. So the family has a **monotone likelihood ratio** in K, which implies it is stochastically increasing: P_K(X ≥ k) is non-decreasing in K for every k. See Klenke & Mattner (2010) for the complete characterization of stochastic order between hypergeometric laws with the same sample size.

### 10.2 Multivariate: coupling argument

Let the optimizer move one card from the pool (filler) into category v. Couple the two decks by relabelling one uniformly chosen filler card as v, with the same shuffle. In every outcome, the count of v rises by 0 or 1 and no other tracked count changes. So **if every predicate that reads v is non-decreasing in v's count, and no predicate reads the pool, then P(condition) is non-decreasing in |v|**. "Non-decreasing" means: `≥`/`>` comparisons, exclusive assignment demands, and any combination of these through AND, OR, and at-least-n with no negation, XOR, IMPLIES, or exactly-n. The optimizer uses binary search (proven optimal) only when this syntactic test passes.

**Counterexamples** (the reason for the guard):
- P(exactly 2 copies in 7) as K grows from 0 to 28 in steps of 4: 0, 0.059, 0.188, 0.293, 0.337, 0.324, 0.269, 0.197 ✔. It rises and then falls.
- With mulligans, adding a good card can make a keep rule accept hands that are worse for a *different* success condition. So mulligan scenarios are treated as non-monotone unless the user overrides.

### 10.3 Multi-variable search

Maximizing P over several integer counts is a black-box integer program. P need not be concave or separable, so greedy and local search are **heuristics**. Only exhaustive search (or binary search in the monotone single-variable case) is reported as proven optimal (FR-53).

### 10.4 Search reductions when every variable is monotone

Write x for a vector of variable counts with bounds lo ≤ x ≤ hi and cap C (the budget, or the room left after fixed categories). Let T* = min(C, Σhi), and let P*(T) = max over Σx = T of P(x).

**Lemma 10.1 (full-cap slice).** If P is non-decreasing in every variable (§10.2), then max over Σx ≤ C of P(x) = P*(T*).
*Proof.* Take any feasible x with Σx < T*. Then Σx < Σhi, so some xᵢ < hiᵢ. Also Σx + 1 ≤ T* ≤ C, so x + eᵢ is feasible, and P(x + eᵢ) ≥ P(x). Repeat until Σx = T*. ∎

**Lemma 10.2 (slices improve with the total).** Under the same assumption, P*(T) is non-decreasing for Σlo ≤ T ≤ T*.
*Proof.* Let x attain P*(T) with T < T*. Some xᵢ < hiᵢ, so x + eᵢ lies in slice T + 1 and P*(T + 1) ≥ P(x + eᵢ) ≥ P*(T). ∎

Consequences used by the optimizer (LLD §6.3):
- `max_probability` searches only the slice Σx = T*. The search loses one dimension and the result is still proven.
- `min_total` binary-searches T, finding the smallest T with P*(T) ≥ target.

Both shortcuts are cross-checked against unpruned searches by property test P16. Example: 3 variables with 8 × 9 × 9 bounds and cap 36 need 74 evaluations instead of 648.

---

## 11. Monte Carlo estimation (test oracle and fallback)

- The estimator is p̂ = S/n from n independent simulated games. Var(p̂) = p(1 − p)/n.
- Interval: **Wilson score** interval, center (p̂ + z²/2n)/(1 + z²/n) and half-width z·√(p̂(1−p̂)/n + z²/4n²)/(1 + z²/n). It behaves well near 0 and 1, unlike the Wald interval [Wilson 1927; Brown, Cai & DasGupta 2001].
- Sample size: ±0.5% at 95% confidence needs n ≈ 1.96² · 0.25/0.005² ≈ 38,416 ✔ in the worst case p = ½.
- **Testing without flakiness:** agreement tests use fixed seeds, so a passing test stays passing. They use 99.9% intervals, and across a suite of T random scenarios a Bonferroni-style budget is used. A seeded test fails only if the code changes.

---

## 12. Reference values (✔ brute-force verified)

| # | Scenario | Exact value |
|---|---|---|
| A1 | N=60, K=4, n=7, P(X ≥ 1) | 0.3994996257 |
| A2 | N=60, K=24, n=7, PMF k=0..7 | 0.021615, 0.121041, 0.269415, 0.308704, 0.196448, 0.069335, 0.012546, 0.000896 |
| A3 | A1 with London mulligan, M=1, keep = success = "≥1 copy" | 0.6393993005 |
| A4 | N=60, K=4, on the draw, P(≥1 by T3) (n=10) | 0.5277205287 |
| A5 | 60/24 on the play: ≥1 land @T0 ∧ ≥2 @T2 ∧ ≥3 @T3 | 0.7886544700 |
| A6 | Two disjoint 4-ofs, n=7, P(A ≥ 1 ∧ B ≥ 1) | 0.1454056805 |
| A7 | 60/24 on the play: ≥2 lands @T0 ∧ ≥4 @T4 | 209193119/335980515 ≈ 0.6226346757 |
| A8 | 60 cards, 24 lands (14 red), n=9: P(red ≥ 1 \| lands ≥ 3) | 0.9717531574 |
| A9 | N=60, K=24, n=7: E[X] = 14/5, Var[X] = 2226/1475 | exact |

---

## 13. References

- Agresti, A. *Categorical Data Analysis*, 3rd ed., Wiley, 2013 (r × c tables with fixed margins).
- Bellman, R. *Dynamic Programming*, Princeton, 1957.
- Brown, L. D., Cai, T. T., DasGupta, A. "Interval Estimation for a Binomial Proportion." *Statistical Science* 16(2), 2001.
- Ferguson, T. S. *Optimal Stopping and Applications* (online lecture notes, UCLA).
- Fisher, R. A. "On the interpretation of χ² from contingency tables…" *JRSS* 85, 1922.
- Gale, D. "A theorem on flows in networks." *Pacific J. Math.* 7, 1957.
- Hall, P. "On representatives of subsets." *J. London Math. Soc.* 10, 1935.
- Johnson, N. L., Kotz, S., Balakrishnan, N. *Discrete Multivariate Distributions*, Wiley, 1997.
- Kleene, S. C. *Introduction to Metamathematics*, 1952 (strong three-valued logic).
- Klenke, A., Mattner, L. "Stochastic ordering of classical discrete distributions." *Advances in Applied Probability* 42(2), 2010. [arXiv:0903.1361](https://arxiv.org/abs/0903.1361)
- Karsten, F. "How Many Sources Do You Need to Consistently Cast Your Spells? A 2022 Update." TCGplayer, 2022 (methodology only cited through secondary sources: [gist summary](https://gist.github.com/teryror/881d60e08480a56043895d3bbb83c374)).
- Mikonen, T. "The London Mulligan." 2019. <https://tmikonen.github.io/quantitatively/2019-03-01-london-mulligan>
- QuantEcon. "Multivariate Hypergeometric Distribution." <https://python.quantecon.org/multi_hyper.html>
- Schrijver, A. *Combinatorial Optimization: Polyhedra and Efficiency*, Springer, 2003.
- Wilson, E. B. "Probable inference, the law of succession, and statistical inference." *JASA* 22, 1927.
- Magic: The Gathering Comprehensive Rules, §103 (Starting the Game). Rule letter numbering varies by revision; see [mtg.wiki summary](https://mtg.wiki/page/Starting_the_game).
