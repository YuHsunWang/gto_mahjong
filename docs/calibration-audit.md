# Deal-in calibration independence audit

Date: 2026-08-06

## Conclusion

The shipped table generalizes to a policy that never consumes it, but its
out-of-policy skill is modest and lower than the table's recorded on-policy
holdout skill. The coarse `9-13`/`13+` inversion alone remains compatible with
sampling noise. The loss of discrimination at the top is nevertheless real:
the old `13+` cell mixes a low-rate `13-16` population with a much higher-rate
`16+` population. A versioned `13-16`/`16+` split restores the top of the scale,
retains the existing minimum count, Jeffreys prior, and monotonic PAV fit, and
improves both proper scores on an untouched independent-policy holdout.

`data/calibration.json` was not changed. The candidate is
`data/calibration-independent.json`.

## Independent policy and measurement design

The instrument changes one mechanism in `ev_aware`: it keeps the same
top-five-plus-safest candidate set (`ATTACK_TOP_K = 5`), attack value, opponents,
policy mix (`attack,cautious,ev_aware,ev_aware`), rules, and seeded walls, but
does not load a `Calibration` and therefore omits only the calibrated deal-in
risk term. `attack` and `cautious` are unchanged.

Before every independent run, a fixed-decision ON/OFF probe exercises the
actual discard function. OFF loaded calibration zero times and chose tile 19;
ON loaded a synthetic score-sensitive calibration once and chose tile 28.
The probe also asserts `top_k = 5`. The 12-game serial, four-worker, and
reverse-completion-order count merges were identical.

The final fresh-process run used seeds 50001 through 58000: 8,000 games and
1,078,542 per-opponent discard exposures, with 5,406 deal-ins and a 0.501232%
base rate (5,406/1,078,542). Every fifth game by zero-based offset was held out:
6,400 fit games (865,683 exposures, 4,304 deal-ins, 0.497180%) and 1,600 holdout
games (212,859 exposures, 1,102 deal-ins, 0.517714%). No wall-clock result is
reported because the host was contended.

Reproduction command:

```bash
python3 scripts/generate_calibration.py \
  --games 8000 --seed-start 50001 --workers 4 --verify-games 12 \
  --independent-policy --out data/calibration-independent.json
```

## Shipped table: independent out-of-sample quality

All 8,000 independent-policy games are out of sample for the shipped table.
At 1,078,542 evaluated exposures and 5,406 deal-ins (0.501232%):

| Metric | Shipped | Constant base | Skill over base |
|---|---:|---:|---:|
| Brier | 0.004976729 | 0.004987199 | 0.2099% |
| Log loss | 0.030163272 | 0.031544276 | 4.3780% |

The shipped document's feedback-policy holdout had 263 deal-ins in 55,032
exposures (0.477904%) and recorded 0.2787% Brier skill and 5.7866% log-loss
skill. The independent-policy point estimates are lower by 0.0688 and 1.4087
percentage points respectively, but remain positive. This is evidence of a
modest generalization cost, not a collapse. The exact causal cost is not
identified because the old holdout is smaller and was not a paired same-seed
ON-policy arm.

### Shipped reliability on all independent data

Mean prediction is the shipped interpolated lookup averaged within each raw
score bin.

| Danger bin | Deal-ins / exposures | Observed rate | Mean prediction |
|---|---:|---:|---:|
| `0-1` | 2 / 107,703 | 0.001857% | 0.007012% |
| `1-2` | 34 / 63,918 | 0.053193% | 0.047537% |
| `2-4` | 353 / 220,484 | 0.160102% | 0.127907% |
| `4-6` | 695 / 128,227 | 0.542008% | 0.405730% |
| `6-9` | 1,505 / 225,758 | 0.666643% | 0.614326% |
| `9-13` | 1,729 / 199,589 | 0.866280% | 0.767170% |
| `13+` | 1,088 / 132,863 | 0.818889% | 0.826674% |

## Tail diagnosis

The shipped fit cells were 0.857410% (303/35,339) for `9-13` and 0.774546%
(176/22,723) for `13+`; its original holdout was 1.074151% (93/8,658) and
0.782361% (44/5,624). PAV consequently gave both shipped cells 0.826674%, based
on 479 deal-ins in 58,062 observations before the Jeffreys prior.

On all fresh independent data, `9-13` was 0.866280% (1,729/199,589) and `13+`
was 0.818889% (1,088/132,863), an upper-minus-lower difference of -0.0474
percentage points. A 2,000-replicate game-cluster bootstrap gave a 95% interval
of -0.1119 to +0.0155 percentage points. The prefix result did not separate
steadily with sample size:

| Games | `9-13` | `13+` |
|---:|---:|---:|
| 500 | 0.851443% (105/12,332) | 0.843359% (68/8,063) |
| 1,000 | 0.853525% (211/24,721) | 0.855806% (139/16,242) |
| 2,000 | 0.897338% (447/49,814) | 0.822259% (271/32,958) |
| 4,000 | 0.876676% (877/100,037) | 0.851909% (566/66,439) |
| 8,000 | 0.866280% (1,729/199,589) | 0.818889% (1,088/132,863) |

Thus the sign of the coarse inversion is not established. More importantly,
the diagnostic tail bands were fixed before the 8,000-game result and expose
heterogeneity that a single `13+` cell cannot represent:

| Score band | Deal-ins / exposures | Observed rate |
|---|---:|---:|
| `9-11` | 1,137 / 132,079 | 0.860848% |
| `11-13` | 592 / 67,510 | 0.876907% |
| `13-16` | 684 / 103,724 | 0.659442% |
| `16-20` | 204 / 12,857 | 1.586684% |
| `20+` | 200 / 16,282 | 1.228350% |

The untouched candidate holdout independently confirms the split: `13-16`
was 0.673236% (138/20,498), while `16+` was 1.707145% (97/5,682). These are not
thin cells. The evidence therefore supports a binning defect, not merely
collecting more observations into the old open-ended cell.

## Candidate fix and side-by-side result

The candidate declares its danger edges and buckets in document metadata.
Documents without that metadata, including the shipped file, retain the old
seven-bin interpretation. The candidate adds the predeclared edge at 16,
creating `13-16` and `16+`. Its fit cells are 0.866347% (1,386/159,982),
0.656045% (546/83,226), and 1.308778% (307/23,457). Jeffreys-smoothed PAV pools
the first two to 0.794786% while leaving `16+` at 1.310853%. Consequently score
30 is no longer capped at the shipped 0.826674% (479/58,062); it receives
1.310853% (307/23,457).

Both tables were scored on the same independent 1,600-game holdout: 1,102
deal-ins in 212,859 exposures (0.517714%).

| Predictor | Brier | Brier base | Brier skill | Log loss | Log base | Log skill |
|---|---:|---:|---:|---:|---:|---:|
| Shipped | 0.005138877 | 0.005150333 | 0.2224% | 0.030928069 | 0.032413584 | 4.5830% |
| Independent tail-split | 0.005137173 | 0.005150333 | 0.2555% | 0.030840424 | 0.032413584 | 4.8534% |

A fresh same-seed replay and 5,000-replicate paired game-cluster bootstrap put
the candidate's Brier-skill gain at +0.0331 percentage points (95% interval
+0.0178 to +0.0490) and log-skill gain at +0.2704 percentage points (+0.1371
to +0.4050), all on 1,102 deal-ins in 212,859 exposures (0.517714%).

### Candidate reliability on the shared holdout

| Danger bin | Deal-ins / exposures | Observed rate | Mean prediction |
|---|---:|---:|---:|
| `0-1` | 1 / 21,258 | 0.004704% | 0.005858% |
| `1-2` | 7 / 12,615 | 0.055489% | 0.038919% |
| `2-4` | 57 / 43,731 | 0.130342% | 0.167598% |
| `4-6` | 156 / 24,897 | 0.626582% | 0.458363% |
| `6-9` | 303 / 44,571 | 0.679814% | 0.641422% |
| `9-13` | 343 / 39,607 | 0.866009% | 0.752432% |
| `13-16` | 138 / 20,498 | 0.673236% | 0.795605% |
| `16+` | 97 / 5,682 | 1.707145% | 1.292089% |

All candidate fit cells have at least 23,457 observations. `MIN_CELL_COUNT`
remains 30, the prior remains Jeffreys Beta(0.5, 0.5), and PAV remains active.
The lowest candidate cell has one deal-in in 86,445 observations (0.001157%
empirical) and fits to 0.001735%, so no observed feasible cell prices to zero.

## Recommendation, cost, and limits

Keep the shipped file frozen for this round. Adopt the independent-policy
generation path for future calibration and stage the versioned tail-split
candidate for baseline revalidation before replacement. The measured cost is
8,000 self-play games / 1,078,542 exposures per build plus rerunning every
baseline that consumes `data/calibration.json`; no trustworthy wall-clock cost
is available on this host. The artifact itself is about 28 KiB.

The data cannot establish the exact causal cost of calibration feedback, the
optimal tail edge, or validity for human Taiwanese-mahjong play. This is bot
ecology only. The `16+` holdout rate of 1.707145% (97/5,682) also remains above
the candidate mean prediction of 1.292089%, so residual tail underprediction
remains. More independent games can refine that estimate, but should not be
used to recombine the heterogeneous tail.

## Verification

- Targeted calibration/self-play checks: `2 passed, 19 deselected`.
- Full suite: `1 failed, 263 passed, 1 warning`. The sole failure is the
  pre-existing DEV-115 `test_fold_policy` assertion `-0.925 > 12.3`; it was not
  modified, skipped, or fixed.
