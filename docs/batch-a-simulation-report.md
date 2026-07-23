# Batch A MJ-003 before/after corpus

Method: 30 fixed observable self-play positions (10 each at shanten 0, 1,
and 2), 32 CRN trials per candidate, at most six own draws, and the same
candidate pruning in both arms. “Before” reproduces the former static-visible
rollout; “after” is the production dynamic-remaining rollout. The corpus is
bot-domain diagnostic evidence, not a human-play probability study.

| Case | Shanten | Seed | Hand | Top before→after | P(win) before→after | Runtime s before→after |
|---:|---:|---:|---|---|---|---|
| 0 | 0 | 1200 | `12345789m22p2s` | 2s → 2s | 0.3438 → 0.3438 | 0.643 → 0.565 |
| 1 | 0 | 1200 | `12223m78p1666s` | 1s → 1s | 0.2812 → 0.2812 | 0.262 → 0.249 |
| 2 | 0 | 1202 | `2346678m6689p222567s` | 6m → 6m | 0.3750 → 0.3750 | 0.689 → 0.639 |
| 3 | 0 | 1202 | `234678m6689p222567s7z` | 7z → 7z | 0.3438 → 0.3438 | 0.845 → 0.794 |
| 4 | 0 | 1203 | `1678m33356p23456799s` | 1m → 1m | 0.6250 → 0.6250 | 0.779 → 0.719 |
| 5 | 0 | 1204 | `345667888m56677s111z` | 3m → 3m | 0.2500 → 0.2500 | 1.306 → 1.229 |
| 6 | 0 | 1204 | `45667888m456677s111z` | 4s → 4s | 0.4062 → 0.4062 | 1.742 → 1.683 |
| 7 | 0 | 1204 | `45667888m566779s111z` | 9s → 9s | 0.4062 → 0.4062 | 1.495 → 1.388 |
| 8 | 0 | 1205 | `5688m222p7889s` | 8s → 8s | 0.4375 → 0.4375 | 0.580 → 0.522 |
| 9 | 0 | 1205 | `234m1124789p2456s` | 2s → 2s | 0.3438 → 0.3438 | 0.405 → 0.372 |
| 10 | 1 | 1200 | `12345577789m22p6s` | 1m → 1m | 0.0312 → 0.0312 | 1.224 → 0.945 |
| 11 | 1 | 1200 | `122237m478p23666s` | 1m → 1m | 0.1250 → 0.1250 | 1.955 → 1.842 |
| 12 | 1 | 1200 | `56m789p2344779s11z` | 1z → 1z | 0.1250 → 0.1250 | 0.705 → 0.680 |
| 13 | 1 | 1201 | `78m11456p126788s5z` | 5z → 5z | 0.0000 → 0.0000 | 0.779 → 0.721 |
| 14 | 1 | 1201 | `236p24599s` | 2s → 2s | 0.1875 → 0.1875 | 0.344 → 0.306 |
| 15 | 1 | 1201 | `78m11456p12678s57z` | 5z → 5z | 0.0625 → 0.0625 | 0.677 → 0.641 |
| 16 | 1 | 1201 | `23p245999s` | 9s → 9s | 0.1875 → 0.1875 | 0.219 → 0.215 |
| 17 | 1 | 1201 | `78m114568p12678s7z` | 7z → 7z | 0.0625 → 0.0625 | 0.675 → 0.635 |
| 18 | 1 | 1201 | `1m23p45999s` | 1m → 1m | 0.2188 → 0.2188 | 0.176 → 0.171 |
| 19 | 1 | 1201 | `78m114456p12678s7z` | 7z → 7z | 0.0000 → 0.0000 | 0.720 → 0.660 |
| 20 | 2 | 1200 | `12345577789m226p248s` | 8s → 8s | 0.0312 → 0.0312 | 6.368 → 6.200 |
| 21 | 2 | 1200 | `569m135789p233477s11z` | 9m → 9m | 0.0312 → 0.0312 | 2.828 → 2.789 |
| 22 | 2 | 1200 | `12345577789m22p248s4z` | 4z → 4z | 0.0000 → 0.0000 | 3.633 → 3.488 |
| 23 | 2 | 1200 | `56m135789p233477s113z` | 3z → 3z | 0.0000 → 0.0000 | 1.432 → 1.418 |
| 24 | 2 | 1200 | `56m135789p234779s113z` | 3z → 3z | 0.0312 → 0.0312 | 1.553 → 1.532 |
| 25 | 2 | 1200 | `156m1245p4s115z` | 5z → 5z | 0.0000 → 0.0000 | 0.659 → 0.652 |
| 26 | 2 | 1201 | `37789m11456p1126788s` | 1s → 1s | 0.0938 → 0.0938 | 1.779 → 1.761 |
| 27 | 2 | 1201 | `37789m11456p126788s6z` | 3m → 3m | 0.0625 → 0.0625 | 1.272 → 1.211 |
| 28 | 2 | 1201 | `123459m1235p1246s677z` | 6z → 6z | 0.0312 → 0.0312 | 1.884 → 1.819 |
| 29 | 2 | 1201 | `12345m12359p1246s677z` | 6z → 6z | 0.0625 → 0.0625 | 1.823 → 1.723 |

Summary: p_win changed in 0/30 and top/ranking flips were 0/30 at this
small six-draw budget. Aggregate measured runtime was 39.447s before and
37.569s after. The longer fixed reproduction remains behaviorally decisive:
seed 1, turn 10, state `22344567789m234p567s` changes the stale 2m policy
choice to the physically correct 4m choice; the production regression test
and `scripts/review_validation.py` both lock that result.
