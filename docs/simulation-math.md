# Mahjong simulation: the mathematics

Model estimates, not real-table probabilities. This describes three separate
calculations in the engine: the single-player self-draw curve, the four-player
terminal EV, and the uncertainty attached to each discard candidate.

## Provenance

This started as an external revision document (`simulationmath`, reviewed
2026-09-01) and was brought into the repository so that it can be corrected
alongside the code it describes. The review raised eight defects, filed as
DEV-149 through DEV-156. All eight are resolved in the text below:

- **DEV-155** — §1 claimed the settlement rules were hard-coded. They are not;
  only the single-player discard rule fails to read them. §1 and §3 are
  rewritten accordingly.
- **DEV-156** — §5 described a common-random-number misalignment that the
  non-calibration path was already immune to and that commit `68f8fd3`
  removed the cause of entirely. §5.1 is rewritten and the four-substream
  proposal is demoted to a forward-looking clause.
- **DEV-149** — §6's control variate specified a `μ_C` that does not match the
  four-player distribution. Ruled 2026-09-01: redefine `C`, and make the
  control variate and §2's importance weighting mutually exclusive.
- **DEV-150** — §6 now records the O(1/n) bias from same-sample `β̂` and chooses
  split-sample estimation of `β̂` for the equal-weight control-variate path.
- **DEV-151** — §7 uses the self-normalized delta-method variance when §2's
  weighting is on and restricts the equal-weight bounds accordingly.
- **DEV-152** — §4.3's pooled event means now include the continuation value
  and sum exactly to net EV.
- **DEV-153** — §8 takes the sample-splitting route through every elimination
  round and reserves an independent batch for the final estimate and MCB.
- **DEV-154** — §2 estimates stratum weights and variances under the weighted
  posterior measure and reports effective sample size per stratum.

Still open against this document: DEV-157 (§3's discard rule, an
implementation ticket).

## 0. What changed against the previous revision

Five items change the numbers, not just the wording:

| Item | Previous | This revision |
|---|---|---|
| Ron events | Draw `u ~ U(0,1)`, compare against the calibration table `C(g)` | Decided by the drawn hidden hand `H`; the remaining randomness is taken in conditional expectation rather than tossed for. **Implemented in `68f8fd3`.** |
| Hidden-hand distribution | Uniform draw from the unseen pool | Uniform draw as the proposal, reweighted by discard likelihood (self-normalized). **Not implemented.** |
| Common random numbers | Candidates share one `(H,U)` stream | Alignment is by wall *position*, not by count of random calls. See §5 — the misalignment this row used to describe no longer has a cause. |
| Confidence intervals | `x̄ ± 1.96·SE` on the pilot-selected winner | Pilot samples excluded from the final estimate; t or empirical-Bernstein intervals; effective sample size reported. **Not implemented — `moments.ci95` still uses a fixed normal quantile.** |
| Payoff definition | Single-hand point delta `Δq` | Adds a between-hand continuation value, and lets the base/tai ratio enter the discard rule. **Not implemented.** |

## 1. Notation, rule parameters, and the information set

The 34 tile kinds are `t = 0,…,33`, four copies each. With own-hand counts `h`
and visible tiles `v`, the unseen pool holds `rₜ = 4 − hₜ − vₜ`, and
`R = Σₜ rₜ` unseen tiles in total.

A trial does not redraw each turn independently: it permutes the finite unseen
pool once, so draws are without replacement and the four-copy limit holds by
construction.

### Rule parameters

Taiwanese play is dominated by the base/tai ratio, so the settlement rule is
parameterized rather than hard-coded:

- `B` = base (底), `P` = tai value (台值), `c` = dealer streak,
  `F` = no-tenpai penalty, `T(·)` = the tai-counting function.
- One payment is `A = B + (T + 2c·𝟙[dealer involved] + dealer surcharge) · P`.

`B/P` decides the speed-versus-shape trade-off: a relatively large `B` makes
fast cheap hands worth taking; a relatively large `P` is what makes flush and
all-triplet routes pay.

**This is already how the code works** (DEV-155). `taimahjong/scoring.py`'s
`ScoringScheme(base_units, tai_units)` *is* `B` and `P`, with
`value = base_units + tai_units * total_tai`; `taimahjong/config.py`'s
`GameConfig` ships `3-1` and `5-2` presets and deliberately refuses a third
unit system; `taimahjong/ev.py` threads `scheme` throughout and
`server/api.py` accepts it as a request parameter.

The gap is in exactly one function: `taimahjong/simulate.py`'s
`_greedy_discard` never reads the scheme. It compares candidates purely on the
count of accepted tiles (`total += copies`) and is blind to the tai those
tiles lead to. §3 describes the fix; DEV-157 tracks it. Nothing in the
settlement layer or the config layer needs to change, and in particular no new
rule-parameter layer is needed — `GameConfig.__post_init__` restricts presets
on purpose.

### Information set

At a decision point the actor holds
`ℐ = (h, four rivers, melds, turn, scores, dealer and streak)`. Every
probability below is conditional on `ℐ`; §2 depends on this.

## 2. Sampling the hidden worlds

Write the three concealed hands as `H = (H₁,H₂,H₃)`. A uniform permutation of
the unseen pool gives the proposal `q(H)`, but the distribution that should be
used is the posterior given the rivers:

```
π(H | ℐ) ∝ q(H) · L(rivers | H)
```

`L` comes from a discard model: a seat that holds a tile yet discarded a
middle tile of the same suit early makes that world less likely (genbutsu,
suji, walls, and live-versus-dead tiles are all components of this
likelihood). No resampling is needed — apply self-normalized importance
sampling to the uniform sample:

```
wᵢ = L(rivers | Hᵢ)
ÊV(a) = Σᵢ wᵢ Xᵢ(a) ⁄ Σᵢ wᵢ
```

Weighting costs effective sample size, which must be reported alongside:

```
N_eff = (Σᵢ wᵢ)² ⁄ Σᵢ wᵢ²
```

**Why:** the previous revision put the river-reading information into the ron
probability `C(g)`, a bolt-on, instead of into the distribution of `H`. The
sampled world and the ron decision then contradicted each other — the world
says nobody is waiting, the coin says somebody just won. Moving the
information into `π(H)` is what would eventually make `C(g)` removable; until
§2 is implemented, `data/calibration.json` remains production's source for
deal-in pricing (`ev.deal_in_ev`, the fold policy, and the calibrated ron
path all read it), so it cannot be deleted on the strength of this section
alone.

### Stratified sampling

Stratify on the opponents' minimum shanten `k` into `S₀,S₁,…`. The mechanisms
are ordered: propose worlds under `q`, weight them to the posterior
`π(H | ℐ)`, then stratify under that weighted measure. For a pilot sample,
estimate the posterior stratum weights and weighted within-stratum means and
variances as:

```
π̂_k = Σ_{i∈S_k} wᵢ ⁄ Σᵢ wᵢ
x̄_k = Σ_{i∈S_k} wᵢ xᵢ ⁄ Σ_{i∈S_k} wᵢ
s_k² = [Σ_{i∈S_k} wᵢ ⁄ ((Σ_{i∈S_k} wᵢ)²−Σ_{i∈S_k} wᵢ²)]
       · Σ_{i∈S_k} wᵢ (xᵢ−x̄_k)²
x̄_str = Σ_k π_k x̄_k
Var(x̄_str) = Σ_k π_k² s_k² ⁄ n_k
Neyman:  n_k ∝ π_k · s_k
```

Here `π_k` in the allocation formulas is the pilot estimate `π̂_k`. When all
weights are equal, these quantities reduce to plain stratum count proportions
and ordinary within-stratum means and variances. Report effective sample size
for every stratum, because weight collapse usually concentrates in one
stratum, and keep the global value as a summary:

```
N_eff,k = (Σ_{i∈S_k} wᵢ)² ⁄ Σ_{i∈S_k} wᵢ²
```

DEV-120 replaced the uniform fill for non-tenpai opponents with an observed
shanten distribution, changing the occupancy of these very strata. Over 400
sampled worlds with three undeclared opponents at turn 8, `k = min shanten`:

| | k=0 | k=1 | k=2 | k=3 | k=4 | k=5 |
|---|--:|--:|--:|--:|--:|--:|
| uniform fill | 43.5% | 0.2% | 4.5% | 20.0% | 26.5% | 5.2% |
| observed fill | 43.0% | 44.8% | 11.5% | 0.8% | 0.0% | 0.0% |

The earlier claim that most samples have nobody waiting no longer describes
the sampler: 88% of worlds now hold somebody at 1-shanten or better. Any
pilot estimate of `π_k` taken before that change is void. The claim that the
variance sits in `k=0`, and therefore that Neyman allocation has a lot to
gain, must be re-derived from the new weighted distribution.

## 3. Single-player self-draw simulation

For trial `i`, let `Tᵢ` be the first turn at tenpai (infinite if never within
the window) and `Wᵢ` the first self-draw turn. After `N` trials the cumulative
estimates at turn `k` are:

```
p̂tenpai(k) = (1/N) Σᵢ 𝟙[Tᵢ ≤ k]
p̂win(k)    = (1/N) Σᵢ 𝟙[Wᵢ ≤ k]
```

`Tᵢ = ∞` is right-censoring, so this curve cannot produce a "mean turn to
tenpai"; only the cumulative proportions are unbiased.

### Discard rule: value-weighted acceptance

The current rule maximizes the physical count of accepted tiles and ignores
tai entirely. Weight each accepted tile by the hand value it leads to:

```
score(d) = Σₜ rₜ · 𝟙[s(h − e_d + eₜ) < s(h − e_d)] · (B + T̂(h − e_d + eₜ) · P)
d* = arg max_d score(d)
```

`s(·)` is shanten and `T̂(·)` estimates the tai of that shape. As `P → 0` this
degenerates to pure ukeire maximization, which is the current behaviour.

This is the one place §1's parameters are not yet plumbed through, and it is a
single-function change: replace `copies` with `copies * scheme.value(T̂(...))`
in `simulate._greedy_discard`.

> **Implementation note.** `_greedy_discard` is `lru_cache`d on
> `(current, remaining_counts, melds_declared)`. Once the scheme weights the
> score, **the scheme must enter the cache key**, or switching between the
> `3-1` and `5-2` presets returns the previous preset's answer.

### A simultaneous band for the curve

`p̂(k)` at different `k` are strongly correlated, so pointwise intervals
support no conclusion about the shape of the curve. Use DKW for a band over
the whole curve:

```
sup_k |p̂(k) − p(k)| ≤ √( ln(2/δ) ⁄ (2N) )   with probability at least 1−δ
```

**Scope:** this curve answers only "what fraction of the time am I at tenpai
or self-drawn by turn `k`". It contains no opponent wins and no deal-ins, so
it is not a win rate.

## 4. Four-player terminal payoff

For candidate discard `a`, sample a hidden world `H` (§2) and a wall order
`U`. The terminal simulator is a map:

```
Z(a,H,U) ∈ {self-draw, own ron, opponent ron, opponent self-draw, exhaustive draw}
```

### 4.1 Ron is decided by the hand, not by a coin

Once `H` is drawn, whether a seat can ron a given discard is a function of
`H`:

```
r_j(d, H) = 𝟙[d ∈ W(H_j)] · 𝟙[T(H_j ∪ d) ≥ T_min] · 𝟙[not furiten / not passed]
```

`W(H_j)` is that seat's waiting set. The only randomness left is the policy
layer's call probability `ρ_j` (essentially always 1 in Taiwanese play, apart
from passing and declining). Take the conditional expectation over that known
discrete distribution instead of sampling it:

```
X̃ᵢ(a) = Σ_z P(Z = z | Hᵢ, Uᵢ) · Δ_q(z)
```

By the law of total variance this step cannot increase variance:

```
Var(X) = Var(E[X | H,U]) + E[Var(X | H,U)] ≥ Var(X̃)
```

**Why:** two independent errors were stacked. First, `C(g)` is a self-play
*marginal* probability, already integrated over hidden worlds; using it as a
probability conditional on `H` is a conditioning error. Second, even keeping
`C(g)`, a known probability should not be resampled through a Bernoulli —
that only adds noise back to a known quantity. The side effect was that the
correlation between tai and danger disappeared: a player going for a flush is
more likely to take your tile in that suit *and* to be worth more, and an
independent coin cannot see that, so the risk tail was systematically
understated.

**Implemented in `68f8fd3`**, which removed the ron coin in favour of the
conditional expectation.

### 4.2 Zero sum and between-hand continuation value

The house settlement turns a terminal into four point deltas
`Δ = (Δ₀,…,Δ₃)` with `Σⱼ Δⱼ = 0`. But a single hand's points are not the
objective: keeping the dealership, losing it, and the number of hands left all
carry value. With post-hand state
`σ' = (seat, dealer, streak, scores, hands remaining)`:

```
Xᵢ(a) = Δ_q(zᵢ) + [ V_q(σ'ᵢ) − V_q(σ₀) ]
```

`V` is estimated by self-play bootstrap. For the augmented payoff to stay zero
sum, `V` must be zero-sum normalized: `Σⱼ Vⱼ(σ) = 0` for every `σ`.

With `V ≡ 0` this degenerates to the previous revision. In that case the
dealer's incentive to push is systematically understated, because the
continuation value of an exhaustive draw or a dealer win is recorded as zero.
An exhaustive draw also adds the no-tenpai penalty `F` and is no longer an
all-zero vector.

### 4.3 Decompose by terminal event, replacing Attack/Risk

The previous `max(0,X)` / `max(0,−X)` split is algebraically correct but
`RiskEV` mixes dealing in, being self-drawn against, and paying nothing while
two other seats settle. Being self-drawn against barely depends on which tile
you choose, so it appears at nearly the same magnitude in every candidate and
dilutes the differences between them. Decompose by event instead:

```
p̂(z) = (1/N) Σᵢ P(Z = z | Hᵢ,Uᵢ)
m̂(z) = Σᵢ P(z|i)·(Δ_q + ΔV_q)(z,i) ⁄ Σᵢ P(z|i)
ĉ(z) = p̂(z) · m̂(z),   with Σ_z ĉ(z) = x̄
```

Here `ΔV_q = V_q(σ') − V_q(σ₀)`. The identity `Σ_z ĉ(z) = x̄` holds exactly
only with this pooled definition: the same event probabilities pool both the
settlement delta and continuation value across trials. Separately estimated
marginal conditional means will not sum back to net EV.

The output columns become "deal-in rate × mean loss" and "self-draw rate ×
mean gain", quantities a player can read directly, and they still add up to
net EV.

## 5. Common random numbers and stream separation

Comparing discards `a` and `b`, run both against the same random world to form
a paired difference:

```
Dᵢ = Xᵢ(a) − Xᵢ(b)
Var(D) = Var(X(a)) + Var(X(b)) − 2Cov(X(a),X(b))
```

### 5.1 Synchronisation

The classic CRN failure is that "sharing one stream `U`" stops holding after
the first divergence: candidates trigger different calls and ron events, the
seats consume different counts of random numbers, the wall index slips, and
the tail of `U` is silently different for the two candidates. When that
happens the covariance can turn negative and CRN *inflates* the variance of
the difference.

**This engine does not have that failure, and had it only on one path**
(DEV-156).

- On the non-calibration path, `taimahjong/ev.py`'s `_OrderedWallRandom`
  makes the wall order an attribute of the world and aligns by *position*
  rather than by count of random calls; it raises outright when the
  consumption pattern does not match. That path was always immune.
- The calibration path did have the slip, because it fell back to a single
  `random.Random(world.terminal_seed)` where the wall draw and the ron coin
  shared one stream. The ron coin was the only consumer whose *number* of
  draws varied with the candidate.
- Commit `68f8fd3` removed the ron coin (§4.1). The only remaining consumer on
  the calibration path is the wall draw, and `remaining` evolves independently
  of the candidate — a discarded tile does not go back into the wall — so the
  `k`-th draw yields the same tile for every candidate.

Measured on `resolve_terminal_distribution` with calibration on, candidates 0,
3 and 19 in the same world:

```
candidate  0:  40 rng calls, prefix-aligned=True
candidate  3:  40 rng calls, prefix-aligned=True
candidate 19:  40 rng calls, prefix-aligned=True
```

All three sequences are identical, and not one `random()` call occurs.

**Forward-looking clause, not a task.** Splitting randomness into independent
substreams addressed by trial index rather than by sequence position —

```
S_wall(seed, i)         wall order
S_hand(seed, i, j)      seat j's concealed hand
S_policy(seed, i, j)    seat j's per-turn decisions
S_call(seed, i, j)      call / pass decisions
```

— becomes necessary again as soon as a new random decision point is added
whose *count* of draws varies by candidate. Melds (the `mj-meld` line) are
exactly that. Until then there is nothing to fix.

### 5.2 Gate condition

CRN only helps when the covariance is positive, and that should be measured
rather than assumed:

```
Var(D̄) = (s²(a) + s²(b) − 2·Ĉov) ⁄ N
```

If `Ĉov ≤ 0`, fall back to independent sampling and record a warning.

> Note that choosing whether to use CRN from an estimated `Ĉov` is a
> data-dependent decision. The `Var(D̄)` reported afterwards is therefore
> optimistic: it does not account for having selected the arm with the more
> favourable covariance estimate.

## 6. Variance reduction

Besides §2's stratification and §4.1's conditional expectation, the
single-player module's output is an available control variate: cheap,
correlated with `X`, and with a known expectation.

```
X_cvᵢ = Xᵢ − β (Cᵢ − μ_C)
β̂ = Ĉov(X,C) ⁄ V̂ar(C)
Var(X_cv) = Var(X) · (1 − ρ²_{X,C})
```

**The definition of `C` and the scope of `μ_C` (DEV-149, ruled 2026-09-01).**
`C` is the indicator that *the actor self-draws within the simulated window in
the same world, ignoring the opponents*. It is not "the actor self-draws in
the four-player rollout": in a four-player rollout an opponent's earlier win
truncates the window, so that quantity is necessarily smaller than §3's curve
and `μ_C` taken from §3 would be wrong.

Under uniform sampling, exchangeability makes the redefined `C` share its
expectation with §3's `p̂win(k)`, so `μ_C` may be read off that curve.

**The control variate and §2's importance weighting are mutually exclusive.**
Once §2 reweights the sample, the actor's draw marginal is no longer uniform
and the exchangeability argument fails. The weights `w = L(rivers | H)` are a
function of the hidden hands, and the actor's wall tiles come from the same
unseen pool as `H`, so `C` and `w` are dependent: under the weighted measure
`μ_C` is neither §3's number nor any other known constant. The unbiasedness of
a control variate rests entirely on `μ_C` being the true value — using the
wrong one shifts the estimator by `β(μ_C^true − μ_C^used)`, and that shift does
not shrink with `N`. So: **when §2's weighting is on, the control variate is
off.**

Estimating `β̂` and applying it on the same sample correlates `β̂` with
`C−μ_C`. That control-variate estimator is consistent but biased, with bias
`O(1/n)`. §2's self-normalized importance-sampling estimator is likewise
consistent but biased, with bias `O(1/n)`; the variance-reduction techniques
therefore do not stack while preserving unbiasedness.

The repository takes the split-sample route for `β̂`: estimate `β̂` on the
first half of the equal-weight sample and apply it to the second half. The
estimating and applying sample indices must be disjoint. This is chosen over
a jackknife because it is simpler to state and directly testable.

## 7. Standard errors and intervals

On the equal-weight path, sample variance and standard error are:

```
s² = [1/(N−1)] Σᵢ (Xᵢ−x̄)²
SE(x̄) = s ⁄ √N
```

When §2's weighting is on, use the self-normalized delta-method variance:

```
V̂ar(x̄) = Σᵢ wᵢ² (xᵢ−x̄)² ⁄ (Σᵢ wᵢ)²
SE(x̄) = √V̂ar(x̄)
```

When all weights are equal, this is the equal-weight plug-in variance; applying
the usual `N ⁄ (N−1)` finite-sample correction gives `s² ⁄ N` and therefore
`SE(x̄) = s ⁄ √N`. `N_eff` is a reported diagnostic of weight concentration,
not a correction to this variance and not a replacement for `N` in the
variance formula.

The payment distribution is discrete, extremely peaked (mostly zeros) and
heavy-tailed (a self-draw and a deal-in differ by several times over), so the
CLT converges slowly and a fixed normal quantile of 1.959964 conveys a
precision that is not there. Use instead:

```
t interval:            x̄ ± t_{ν,0.975} · SE(x̄)
Empirical Bernstein:   |x̄ − μ| ≤ s√( 2 ln(3/δ) ⁄ N ) + 3R ln(3/δ) ⁄ (N−1)
```

`R` is the width of the payment range. The Empirical Bernstein bound is
restricted to the equal-weight path; it does not carry over to weighted
samples as written. On that path it does not rely on a normal approximation
and is safer in small samples with heavy tails, at the cost of a wider
interval.

Two diagnostics must be reported with every candidate, or `N` misleads:

- Effective sample size `N_eff` (§2's post-weighting diagnostic).
- The proportion of non-zero settlements. If `N = 10000` but only 400 hands
  settled non-zero, those 400 carry essentially all the variance.

## 8. Comparing candidates and sequential elimination

### 8.1 Pilot samples do not enter the final estimate

The previous procedure conflicts with itself: use a pilot to eliminate the
laggards, concentrate the budget on the survivors, then report `x̄ ± 1.96·SE`
on the winner. That interval's actual coverage is far below 95%, and the
winner's point estimate is biased upward by construction — it is the maximum
of a set of noisy estimates. Two workable routes:

- **Sample splitting.** The pilot is used only to eliminate and does not enter
  the final average; the winner is re-estimated on a fresh independent batch.
  Simplest to implement.
- **Anytime-valid intervals.** A confidence sequence keeps coverage at any
  stopping time, so pilot samples can be reused for interval coverage:

```
x̄_N ± √( 2 s²_N · ln( ln(2N)/δ ) ⁄ N ) + O( R·ln(ln(2N)/δ) ⁄ N )
```

A confidence sequence fixes coverage under optional stopping. It does not fix
the upward selection bias in the winner's point estimate, which remains the
maximum of a set of noisy estimates when pilot samples enter that estimate.

The repository takes sample splitting because it is the simplest route to
implement and makes the independence boundary directly testable. Pilot and
elimination samples do not enter the final point estimate or MCB intervals.
The anytime-valid route remains an alternative for coverage, not a remedy for
winner-selection bias.

### 8.2 Multiple comparisons

A 17-tile hand usually leaves ten or more distinct candidates. Pairwise tests
accumulate type-I error. Report MCB (multiple comparisons with the best)
intervals instead, per candidate `a`:

```
[ min(0, x̄_a − max_{b≠a} x̄_b − w) ,  max(0, x̄_a − max_{b≠a} x̄_b + w) ]
```

`w` is the width needed for simultaneous coverage. A candidate whose interval
contains 0 may still be the best. Allocate budget by sample-split successive
halving: each of the `⌈log₂K⌉` rounds eliminates the bottom half using only
that round's fresh samples, with defensive candidates held out of elimination.
After elimination, draw a new independent batch for the final reported point
estimate and MCB intervals. No accumulated elimination sample enters that
batch, preserving the simultaneous-coverage construction from adaptive reuse.

### 8.3 Region of practical equivalence

"The difference interval crosses zero" means two very different things to a
player and should be reported as two different outcomes. Fix a practical
threshold `δ_prac` (say 0.3 tai, i.e. `0.3·P`):

| Difference interval `CI(D)` | Report | More samples? |
|---|---|---|
| entirely inside `(δ_prac, ∞)` | `a` is meaningfully better | no |
| entirely inside `[−δ_prac, δ_prac]` | practically equivalent, either will do | no |
| crosses 0 and leaves the ROPE | unresolved | yes |

## 9. Worked example

A candidate run five times, with actor terminal payments `[+8, 0, −4, +2, −6]`:

| Quantity | Derivation | Result |
|---|---|---|
| Net EV | `(8+0−4+2−6)/5` | 0 |
| Sample variance `s²` | `(64+0+16+4+36)/4` | 30 |
| `s` | `√30` | 5.477 |
| `SE(x̄)` | `5.477/√5` | 2.449 |
| Normal interval (previous) | `0 ± 1.960 × 2.449` | `[−4.80, +4.80]` |
| t interval (this revision, `ν=4`) | `0 ± 2.776 × 2.449` | `[−6.80, +6.80]` |
| Non-zero settlement rate | `4/5` | 0.80 |

Normal and t differ by 42% at `N=5`, which is the problem with a fixed 1.96.
The interval is far wider than the point estimate, meaning five trials say
nothing about this candidate.

The event decomposition also shows why a win rate alone is not enough: two
candidates with identical win rates can still have completely different net
EV, depending on how `p̂(z)·m̂(z)` splits between self-draws and deal-ins.

## 10. Where the derivation stops

This revision fixes inconsistency and efficiency in the estimators. The
following are model biases that more samples will not remove:

- **Calls are not fully simulated.** Taiwanese mahjong is a heavy-calling
  game and closed hands are the minority; without chi/pon/kong the actor's
  own speed curve shifts later and the opponent model is too slow, so the
  timing of risk is understated. This is very likely larger in magnitude than
  the sum of every variance reduction in this document.
- **Flowers are not simulated.** Replacement draws change the wall length and
  pay tai, so per-seat turn counts do not line up with a real table.
- **The discard likelihood `L` and the tai estimate `T̂` are heuristics**,
  calibrated from built-in bot self-play, and do not represent human play.
  `π(H)` is therefore still biased in shape.
- **The value function `V` comes from bootstrap** and carries its own bias
  before convergence. Disabled (`V ≡ 0`), the dealer plays systematically too
  conservatively.
- **The payoff is expected points, not expected placement.** Near the end of a
  match, the same net EV should lead to different variance preferences when
  ahead than when behind. A quantile summary of the payment distribution
  should be reported alongside.
- **Every interval covers sampling uncertainty only**, never the systematic
  error from rule choices and heuristic assumptions.

### Where each section lands in the code

- `taimahjong/simulate.py` — §3's B/P-weighted discard rule (DEV-157); the
  DKW band.
- `taimahjong/ev.py` — §4.1's conditional expectation (**done, `68f8fd3`**);
  §4.3's event decomposition replacing the Attack/Risk columns.
- `taimahjong/rollout.py` — §2's importance weights and stratification; §5's
  substreams, if and when a new varying-count random consumer appears.
- `taimahjong/selfplay.py` — §4.2's zero-sum normalized `V`. `C(g)` becomes
  removable only after §2 lands; today `data/calibration.json` is still
  production's deal-in and ron pricing.
- New — §7 and §8's intervals and successive halving belong in a `stats.py`
  decoupled from the simulation logic.
