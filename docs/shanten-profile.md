# Production shanten profile (DEV-118)

Measured 2026-09-23 on the current branch. This is a report, not a proposed
code change. Times below are **cProfile-instrumented** wall and function times;
they should be used as shares and within-run comparisons, not as unprofiled
latency estimates. No two timed configurations shared a Python process.

## Reproduction and production-path check

Run these from the repository root, in this order. Each `run` and `audit`
command starts a fresh interpreter. The corpus pickle and JSON outputs are
temporary artifacts, not committed data.

| ID | Exact command | Purpose |
|---|---|---|
| P | `python scripts/profile_shanten.py prepare /tmp/shanten-corpus.pkl` | Fixed corpus; generation outside timing |
| R1 | `python scripts/profile_shanten.py run /tmp/shanten-corpus.pkl /tmp/shanten-run1.json` | Production profile |
| A | `python scripts/profile_shanten.py audit /tmp/shanten-corpus.pkl /tmp/shanten-audit.json` | Exact request-key count, separate from timing |
| R2 | `python scripts/profile_shanten.py run /tmp/shanten-corpus.pkl /tmp/shanten-run2.json` | Fresh-process repeat |
| E | `python scripts/profile_shanten.py run /tmp/shanten-corpus.pkl /tmp/shanten-exhaustive.json --exhaustive` | Same `top_k=5`, exhaustive comparison |
| R3 | `python scripts/profile_shanten.py run /tmp/shanten-corpus.pkl /tmp/shanten-final.json` | Final-harness path-assertion check |

P reported requested `generate_position` seeds **1 and 20**, with actual
position seeds **1 and 20**, plus all six cases from
`ev_benchmark.benchmark_corpus()`: early-default, mid-declared,
late-pressure, flush-hand, dealer-streak, and open-flush-opponent. The harness
loads `data/calibration.json` through the same `CalibrationProvider` used by
the server; P reported calibration ID
`sha256:3edbea05a714f77083f46c4711e9c6b03c3d8fafd6952d1dce09274770cd1834`.
The profile measures only the eight `ev_rank` calls; quiz generation, calibration
loading, imports, and the legal-discard count are outside the timed region.

The harness passes the same arguments as `quiz._display_rank_cached` for quiz
positions: `REFINE_SIMS=200`, `EV_TOP_K=5`, the position's evaluation seed and
score template, scheme, and loaded calibration. Benchmark cases use their
committed hand, opponents, turns, seed, and scheme, with that same production
calibration. R1 reports `exhaustive=false`, calibration present, and 16 calls to
`_production_worlds` for eight rankings: one reported base and one independent
pilot base each. `_calibrated_ron` ran 12,648 times. Every case had more legal
discards (9–16) than real survivors (5–6; a sixth can be appended to retain the
fold discard), so candidate screening was active. E's eight world-builder calls
and 9–16 survivors confirm that `--exhaustive` bypassed the pilot. The source
path is `quiz._display_rank_cached` → `ev_rank` →
`resolve_terminal_distribution` → `_production_discard_policy` →
`_production_discard_analysis` → `_production_shanten`.

## Time attribution (R1)

R1 took **96.033 s** around the eight ranking calls; cProfile assigned
**96.008 s** cumulative to `ev_rank` itself. The 0.025 s difference is harness
bookkeeping. `tottime` is time in the function body, excluding children;
`cumtime` includes children. Cached calls that return from the C `lru_cache`
wrapper do not enter the Python function body and therefore are not counted as
function calls by cProfile.

| Function | cProfile calls | tottime | share of R1 wall | cumtime | share of R1 wall |
|---|---:|---:|---:|---:|---:|
| `_production_shanten` | 4,592,799 misses | 1.619 s | **1.69%** | 34.129 s | **35.54%** |
| `_production_discard_analysis` | 37,831 misses | 8.294 s | 8.64% | 34.905 s | 36.35% |
| `_production_discard_policy` | 159,189 | 0.284 s | 0.30% | 37.092 s | 38.62% |
| `resolve_terminal_distribution` | 12,648 | 1.639 s | 1.71% | 79.555 s | 82.84% |
| `_production_worlds` | 16 | 0.031 s | 0.03% | 15.751 s | 16.40% |

The caller cumulative times overlap: do **not** add those rows. The policy's
37.092 s contains analysis and shanten work. The terminal rollout's 79.555 s
contains that policy work. A disjoint view, using the same R1 cProfile tree, is
34.129 s shanten, 45.426 s other terminal-rollout work, 15.751 s hidden-world
construction, and 0.727 s elsewhere and harness overhead. Thus the
**non-shanten 61.904 s** is mostly terminal simulation and world construction.
The 34.129 s shanten bucket includes its inner `_shanten_unchecked` call; its
own 12.401 s `tottime` must not be added to the bucket.

Top ten functions by exclusive `tottime` in R1, including the non-shanten
hotspots (same R1 command):

| Rank | Function | Calls | tottime |
|---:|---|---:|---:|
| 1 | `shanten.py:155:_shanten_unchecked` | 4,783,447 | 12.401 s |
| 2 | `shanten.py:166:<genexpr>` | 36,789,039 | 8.548 s |
| 3 | `ev.py:663:_production_discard_analysis` | 37,831 | 8.294 s |
| 4 | `builtins.max` | 5,351,764 | 8.217 s |
| 5 | `tiles.py:14:<genexpr>` | 15,603,035 | 4.652 s |
| 6 | `tiles.py:9:validate_counts` | 445,801 | 3.688 s |
| 7 | `builtins.isinstance` | 39,786,847 | 3.624 s |
| 8 | `builtins.min` | 32,267,292 | 3.001 s |
| 9 | `random.py:245:_randbelow_with_getrandbits` | 5,315,521 | 2.314 s |
| 10 | `danger.py:549:assess_validated_danger` | 132,336 | 1.956 s |

Built-in rows aggregate every caller, so their time cannot all be assigned to
shanten or to the non-shanten remainder. `validate_counts`, random draws, and
danger assessment are visible non-shanten costs. The disjoint totals above are
the appropriate answer to where the remaining wall time went.

## Cache misses and key evidence (R1, A)

Both caches were cleared immediately before R1's timed region. R1's
`cache_info()` and A's exact key recorder produced the following counts.
A used a collision-free 35-byte representation of each 34-count hand plus
meld count; its wrappers ran in a separate process, so their overhead is absent
from R1 and R2. A produced exactly the same ranks and cache counters as R1.

| Cache | Requests (hits + misses) | Hits | Hit rate | Misses | Distinct requested keys | `currsize/maxsize` |
|---|---:|---:|---:|---:|---:|---:|
| `_production_shanten` | 6,480,172 | 1,887,373 | **29.13%** | 4,592,799 | 4,412,662 | 200,000 / 200,000 |
| `_production_discard_analysis` | 159,189 | 121,358 | **76.24%** | 37,831 | 37,831 | 37,831 / 100,000 |

The shanten key is exactly `(hand, melds_declared)`; analysis uses the same
two fields on the 17-tile hand. Neither key includes `remaining`, visible
tiles, calibration, or another rollout state. A found the same number of
distinct hand-only encodings as full keys for both caches, so differing meld
counts did not explain any misses in this corpus. The analysis cache never
reached capacity: every miss was a genuinely new key. For shanten,
**4,412,662** of the misses were first encounters (**96.08%** of misses) and
**180,137** were requests for previously seen keys that had been evicted
(**3.92%**). Its full `currsize` confirms capacity pressure, but the measured
miss problem is predominantly distinct hands. The code constructs many nearby
post-discard and post-draw hands in `_production_discard_analysis`; attributing
the observed unique-key count specifically to hidden-world diversity is an
inference from that path, not separately measured.

## Screen cross-check and repeat (E, R1, R2)

E kept `top_k=5` and changed only `exhaustive=True`. It took **102.493 s**
versus R1's **96.033 s**, **6.73%** more on this eight-case corpus. Terminal
rollout calls rose from 12,648 to 22,000, while world builds fell from 16 to
8 because exhaustive ranking has no pilot. This explains why the much larger
candidate set caused a modest net increase. The earlier ~15% figure used a
different, larger corpus; this eight-case check does not reproduce its exact
percentage and should not be pooled with it.

| Production profile | R1 | R2 | Difference |
|---|---:|---:|---:|
| Wall around eight ranks | 96.033 s | 96.614 s | +0.61% |
| `_production_shanten` tottime | 1.619 s | 1.583 s | -2.23% |
| `_production_shanten` cumtime | 34.129 s | 34.255 s | +0.37% |
| Shanten cumtime / wall | 35.54% | 35.46% | -0.08 percentage points |

R2 was a new process with the same corpus and settings. All eight rank outputs,
both cache counters, and the 4,592,799 shanten function calls were identical
across R1 and R2. This is the requested within-noise reproduction check.
R3, run after adding explicit production-path assertions to the harness, passed
with 96.073 s wall, 34.263 s shanten cumulative (35.66%), and identical ranks
and cache counters.

## Ranked opportunities, not changes

These are *scenario estimates* from R1, not measured gains from patches.
Percentages use R1's 96.033 s wall time. The first two target disjoint
buckets; the cache proposal overlaps the first. Actual gains are **UNKNOWN** until isolated variants
are implemented and timed in fresh processes.

1. **Speed up exact shanten evaluation.** `_production_shanten` costs 34.129 s
   cumulative. Halving that cost would save about **17.1 s / 17.8%**; the hard
   bound from eliminating it is 35.5%. Intended EV-output change: none for an
   exact replacement. The risk is an incorrect shanten value, which changes
   discard policy and therefore EV output. Verify exact results
   across encountered hand/meld keys, then bit-for-bit seeded rank output and
   fresh-process timing on this corpus.
2. **Reduce hidden-world construction cost while preserving sampled worlds.**
   `_production_worlds` costs 15.751 s cumulative, separate from the terminal
   shanten path. For example, hoist public-state work now repeated in
   `_sample_production_world` across its 200 reported and 24 pilot worlds. If
   that bucket were halved, the implied gain is **7.9 s / 8.2%**; its maximum
   possible gain is 16.4%. Intended EV-output change: none. Altering random
   draw order or sampled hands would change EV output. Verify exact world objects and seeds, exact rank output,
   and paired fresh-process timing.
3. **Trial a larger shanten LRU only if memory permits.** At most 180,137 of
   4,592,799 misses are repeated-key misses. At the observed mean miss cost,
   eliminating *all* of them has an optimistic bound of **1.34 s / 1.39%**.
   A larger but still finite cache may recover less; the capacity needed to
   retain all 4.41 million keys would be substantial, and its memory cost is
   **UNKNOWN** here. Intended EV-output change: none; cache size alone should
   not change EV output. Verify rank
   identity, resident memory, hits/misses, and fresh-process timing before
   considering the trade-off.
