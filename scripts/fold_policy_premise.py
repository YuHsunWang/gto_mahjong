"""Re-price the hand-crafted fold-policy position from its premises (DEV-115).

``tests/test_fold_policy.py`` once asserted that folding beats pushing on
``1112345678999m1234p`` against a 連莊-20 declared dealer.  It was red for a
week, and commit 8a97fe3 resolved it by swapping the position out.  That
commit's reasoning lived only in its message, so nobody could re-run it --
which is the failure this script exists to prevent.  It reconstructs the
*original* position and answers the ticket's two questions from measurement.

Question 1 was whether ``attack_ev = 14.5`` is credible, on the reasoning that
a two-suit 閒家 hand worth 5-8 units cannot expect 14.5 without an implausible
win rate.  The premise misreads the field.  ``_rollout_entry`` sums *every*
positive payment in chip units, while ``mean_win_value`` is in 台/底 units, so
the two are not comparable and ``attack_ev`` is not ``p_win`` times a value.
``decomposition`` splits the payout by terminal kind and by payer; ``streak``
then varies only ``dealer_streak``.  The two together localise the whole
excess: 連莊 is a property of the hand involving the dealer, so it inflates
payments in *both* directions -- the rule that makes dealing in cost 52 pays
about the same back when we are the one ronning that dealer.

Question 2 asked for a 牌理 backing.  ``tenpai`` gives it deterministically,
with no rollout: keeping the 九蓮 body whole and discarding a 筒子 waits on
nine kinds, and the ticket's own "best push 8m" is the narrow line.  ``power``
then checks that push beats fold across seeds rather than at one lucky one.

Scope: this measures the position, not the engine's realism.  The absolute
numbers drift with the opponent model -- the best push has already moved from
8m to 1p since the ticket -- so read the *mechanism* columns (``streak``
linearity, ``tenpai`` widths), which are structural, over any single value.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from taimahjong import ev
from taimahjong.danger import OpponentView, danger_score, parse_river
from taimahjong.shanten import shanten
from taimahjong.tiles import parse_tiles

# The position exactly as tests/test_fold_policy.py carried it before 8a97fe3.
HAND = parse_tiles("1112345678999m1234p")
RIVER = "19m"
DECLARED_AT = 1
STREAK = 20
VISIBLE = (1,) + (0,) * 7 + (1,) + (0,) * 25
NAMES = [f"{n}{s}" for s in "mps" for n in range(1, 10)] + list("ESWNPFC")


def _opponent(dealer_streak: int = STREAK) -> OpponentView:
    return OpponentView(
        parse_river(RIVER), [], DECLARED_AT,
        is_dealer=True, dealer_streak=dealer_streak,
    )


@contextlib.contextmanager
def _captured_terminals(store: dict):
    """Record the per-world terminal distributions ``ev_rank`` summarises.

    ``ev_rank`` returns only the summary entry, so the payout split has to be
    read off the terminals themselves.  This wraps ``_rollout_entry`` rather
    than rebuilding the worlds, which keeps the decomposition honest -- it is
    the same sample the reported entry is computed from -- at the cost of
    being coupled to that private signature.
    """
    original = ev._rollout_entry

    def spy(discard, terminals, acting_seat, *args, **kwargs):
        store[discard] = (terminals, acting_seat)
        return original(discard, terminals, acting_seat, *args, **kwargs)

    ev._rollout_entry = spy
    try:
        yield
    finally:
        ev._rollout_entry = original


def _tenpai_column() -> dict:
    """Which discards reach tenpai, and how wide each resulting wait is."""
    rows = []
    for tile in range(34):
        if not HAND[tile]:
            continue
        post = list(HAND)
        post[tile] -= 1
        if shanten(tuple(post)) != 0:
            continue
        waits, live = [], 0
        for candidate in range(34):
            probe = list(post)
            probe[candidate] += 1
            if probe[candidate] <= 4 and shanten(tuple(probe)) == -1:
                waits.append(candidate)
                live += 4 - post[candidate] - VISIBLE[candidate]
        rows.append({
            "discard": tile,
            "discard_name": NAMES[tile],
            "wait_kinds": len(waits),
            "waits": [NAMES[w] for w in waits],
            "live_copies": live,
        })
        print(
            f"  discard {NAMES[tile]:<3} waits on {len(waits):>2} kinds, "
            f"{live:>2} live copies  [{' '.join(NAMES[w] for w in waits)}]",
            flush=True,
        )
    return {"rows": rows, "tenpai_discards": len(rows)}


def _genbutsu_column() -> dict:
    """Did the ticket's '19m river -> six safe copies' inventory ever exist?

    ``danger_score`` only treats river entries *after* ``declared_at`` as
    declared-safe, so the window here is empty and the fold line has nothing
    to spend.  Checked because the ticket's whole tension -- defending forces
    breaking tenpai -- rests on that inventory being real.
    """
    opponent = _opponent()
    rows = []
    for tile in (0, 8):
        post = list(HAND)
        post[tile] -= 1
        rows.append({
            "tile": NAMES[tile],
            "is_genbutsu": ev._is_genbutsu(tile, tuple(post), VISIBLE, (opponent,)),
            "danger_score": danger_score(tile, opponent, VISIBLE, tuple(post)).score,
        })
        print(
            f"  {NAMES[tile]}: genbutsu={rows[-1]['is_genbutsu']} "
            f"danger={rows[-1]['danger_score']:.3f}",
            flush=True,
        )
    return {"rows": rows}


def _decomposition_column(discard: int, turns: int, sims: int, seed: int) -> dict:
    """Split one push candidate's payout by terminal kind and by payer."""
    store: dict = {}
    with _captured_terminals(store):
        entry = ev.ev_rank(
            HAND, [_opponent()], VISIBLE, turns=turns, sims=sims, seed=seed,
            exhaustive=True, _target_discard=discard,
        )[0]
    terminals, seat = store[discard]
    positive: dict = defaultdict(lambda: [0.0, 0.0])
    negative: dict = defaultdict(lambda: [0.0, 0.0])
    payers: dict = defaultdict(lambda: [0.0, 0.0])
    count = len(terminals)
    for mixture in terminals:
        for probability, terminal in mixture.outcomes:
            delta = float(terminal.deltas[seat])
            bucket = positive if delta > 0 else negative if delta < 0 else None
            if bucket is not None:
                bucket[terminal.kind][0] += probability
                bucket[terminal.kind][1] += probability * abs(delta)
            if terminal.kind not in ("self_tsumo", "self_ron"):
                continue
            if terminal.kind == "self_ron":
                payers[terminal.discarder][0] += probability
                payers[terminal.discarder][1] += probability * delta
            else:
                for other, paid in enumerate(terminal.deltas):
                    if other != seat:
                        payers[other][0] += probability
                        payers[other][1] += probability * -float(paid)

    def summarise(source: dict) -> list[dict]:
        return sorted(
            (
                {
                    "key": str(key),
                    "probability": weight / count,
                    "contribution": total / count,
                    "mean_when_it_happens": total / weight if weight else 0.0,
                }
                for key, (weight, total) in source.items()
            ),
            key=lambda row: -row["contribution"],
        )

    report = {
        "discard": discard,
        "discard_name": NAMES[discard],
        "acting_seat": seat,
        "dealer_seat": 0,
        "p_win": entry.p_win,
        "attack_ev": entry.attack_ev,
        "risk_ev": entry.risk_ev,
        "net_ev": entry.net_ev,
        "mean_win_value_units": entry.mean_win_value,
        "positive_by_kind": summarise(positive),
        "negative_by_kind": summarise(negative),
        "payers_when_we_win": summarise(payers),
    }
    print(
        f"  discard {NAMES[discard]} (seat {seat}): p_win={entry.p_win:.3f} "
        f"attack={entry.attack_ev:.3f} risk={entry.risk_ev:.3f} "
        f"net={entry.net_ev:.3f} value={entry.mean_win_value:.3f} 台/底 units",
        flush=True,
    )
    for row in report["positive_by_kind"]:
        print(
            f"    + {row['key']:<16} P={row['probability']:.3f} "
            f"contrib={row['contribution']:7.3f} "
            f"mean={row['mean_when_it_happens']:7.3f}",
            flush=True,
        )
    for row in report["payers_when_we_win"]:
        tag = " (dealer)" if row["key"] == "0" else ""
        print(
            f"    paid by seat {row['key']}{tag:<9} P={row['probability']:.3f} "
            f"mean={row['mean_when_it_happens']:7.3f}",
            flush=True,
        )
    return report


def _streak_column(turns: int, sims: int, seed: int) -> dict:
    """Vary only ``dealer_streak``; everything else is held fixed.

    A flat ``attack_ev`` would support the ticket (the payout would have to
    come from the hand).  Linear growth with a fixed ``p_win`` localises it in
    the 連莊 conversion instead.  This is a real control: the streak is the
    single quantity that differs between rows.
    """
    rows = []
    for streak in (0, 1, 2, 5, 10, 20):
        ranked = ev.ev_rank(
            HAND, [_opponent(streak)], VISIBLE,
            turns=turns, sims=sims, seed=seed, exhaustive=True,
        )
        fold = next(entry for entry in ranked if entry.is_fold)
        push = max(
            (entry for entry in ranked if not entry.is_fold),
            key=lambda entry: entry.net_ev,
        )
        rows.append({
            "dealer_streak": streak,
            "push_discard": NAMES[push.discard],
            "push_p_win": push.p_win,
            "push_attack_ev": push.attack_ev,
            "push_net_ev": push.net_ev,
            "fold_net_ev": fold.net_ev,
            "fold_wins": fold.net_ev > push.net_ev,
        })
        print(
            f"  streak {streak:>2}: push {NAMES[push.discard]:>3} "
            f"p_win={push.p_win:.3f} attack={push.attack_ev:7.3f} "
            f"net={push.net_ev:7.3f} | fold net={fold.net_ev:8.3f}"
            f"{'  FOLD WINS' if rows[-1]['fold_wins'] else ''}",
            flush=True,
        )
    return {"rows": rows, "streaks_where_fold_wins": sum(r["fold_wins"] for r in rows)}


def _power_column(turns: int, sims: int, seeds: int) -> dict:
    """Push versus fold across independent seeds, not one lucky sample."""
    rows = []
    for seed in range(1, seeds + 1):
        ranked = ev.ev_rank(
            HAND, [_opponent()], VISIBLE,
            turns=turns, sims=sims, seed=seed, exhaustive=True,
        )
        fold = next(entry for entry in ranked if entry.is_fold)
        push = max(
            (entry for entry in ranked if not entry.is_fold),
            key=lambda entry: entry.net_ev,
        )
        rows.append({
            "seed": seed,
            "push_discard": NAMES[push.discard],
            "push_p_win": push.p_win,
            "push_attack_ev": push.attack_ev,
            "push_net_ev": push.net_ev,
            "push_standard_error": push.standard_error,
            "fold_net_ev": fold.net_ev,
            "margin": push.net_ev - fold.net_ev,
        })
        print(
            f"  seed {seed}: push {NAMES[push.discard]:>3} "
            f"p_win={push.p_win:.3f} net={push.net_ev:7.3f} | "
            f"fold net={fold.net_ev:8.3f} | margin={rows[-1]['margin']:+7.3f}",
            flush=True,
        )
    margins = [row["margin"] for row in rows]
    wins = [row["push_p_win"] for row in rows]
    return {
        "rows": rows,
        "mean_margin": statistics.mean(margins),
        "stdev_margin": statistics.stdev(margins) if len(margins) > 1 else 0.0,
        "min_margin": min(margins),
        "max_margin": max(margins),
        "mean_push_p_win": statistics.mean(wins),
        "seeds_where_fold_wins": sum(margin <= 0 for margin in margins),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--turns", type=int, default=3)
    parser.add_argument("--sims", type=int, default=400)
    parser.add_argument(
        "--decomposition-sims", type=int, default=40,
        help="the ticket's own budget, so its table is comparable",
    )
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--seeds", type=int, default=8)
    parser.add_argument(
        "--out", type=Path, default=ROOT / "data" / "dev115_fold_premise.json",
    )
    args = parser.parse_args()

    started = perf_counter()
    report: dict = {
        "position": {
            "hand": "1112345678999m1234p",
            "river": RIVER,
            "declared_at": DECLARED_AT,
            "dealer_streak": STREAK,
            "turns": args.turns,
        },
    }

    print("=== tenpai discards and wait width (deterministic) ===", flush=True)
    report["tenpai"] = _tenpai_column()
    print("=== the ticket's claimed genbutsu inventory ===", flush=True)
    report["genbutsu"] = _genbutsu_column()

    print(
        f"=== attack_ev decomposition (sims={args.decomposition_sims}, "
        f"seed={args.seed}) ===",
        flush=True,
    )
    widest = max(report["tenpai"]["rows"], key=lambda row: row["live_copies"])
    report["decomposition"] = _decomposition_column(
        widest["discard"], args.turns, args.decomposition_sims, args.seed,
    )

    print(f"=== dealer_streak sweep (sims={args.sims}, seed={args.seed}) ===", flush=True)
    report["streak"] = _streak_column(args.turns, args.sims, args.seed)

    print(f"=== push vs fold, {args.seeds} seeds x {args.sims} sims ===", flush=True)
    report["power"] = _power_column(args.turns, args.sims, args.seeds)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )

    power, streak = report["power"], report["streak"]
    print(f"\nwrote {args.out} ({perf_counter() - started:.0f}s)")
    print(
        f"widest tenpai wait: {widest['discard_name']} on "
        f"{widest['wait_kinds']} kinds, {widest['live_copies']} live copies"
    )
    print(
        "attack_ev by streak: "
        + " ".join(
            f"{row['dealer_streak']}->{row['push_attack_ev']:.3f}"
            for row in streak["rows"]
        )
    )
    print(
        f"push beats fold by {power['mean_margin']:+.3f} "
        f"+/- {power['stdev_margin']:.3f} chips; fold wins "
        f"{power['seeds_where_fold_wins']}/{args.seeds} seeds and "
        f"{streak['streaks_where_fold_wins']}/{len(streak['rows'])} streaks"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
