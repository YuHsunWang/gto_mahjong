"""Command-line entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .analysis import AnalysisContext, CalibrationProvider
from .calibration import counts_from_games, format_report, load_table, write_merged_table
from .config import GameConfig
from .danger import OpponentView, fold_score, parse_river, rank_discards
from .ev import TileAccounting, declaration_ev, ev_rank, remaining_draws
from .quiz import best_discard, explain, generate_position, grade
from .scoring import WinContext, score_hand
from .selfplay import POLICIES, play_games
from .shanten import shanten
from .simulate import win_probability
from .tiles import SUIT_OFFSETS, format_tiles, parse_tiles
from .ukeire import discard_analysis, ukeire


class _ArgumentParser(argparse.ArgumentParser):
    """Keep command-line input errors to a single line."""

    def error(self, message: str) -> None:
        self.exit(2, f"error: {message}\n")


def _tile_name(tile: int) -> str:
    counts = [0] * 34
    counts[tile] = 1
    return format_tiles(counts)


def _accepted_kinds(accepted: dict[int, int]) -> str:
    return ", ".join(f"{_tile_name(tile)}:{remaining}" for tile, remaining in accepted.items()) or "-"


def _ordered_tiles(text: str) -> list[int]:
    """Parse compact notation while preserving the user-written tile order."""
    parse_tiles(text)
    ordered: list[int] = []
    digits = ""
    for char in text:
        if char.isdigit():
            digits += char
        else:
            offset = SUIT_OFFSETS[char]
            ordered.extend(offset + int(digit) - 1 for digit in digits)
            digits = ""
    return ordered


def _single_tile(text: str | None) -> int | None:
    if not text:
        return None
    tiles = _ordered_tiles(text)
    if len(tiles) != 1:
        raise ValueError("expected exactly one tile")
    return tiles[0]


def _parse_opponent_melds(text: str | None) -> list[tuple[int, int, int]]:
    if not text:
        return []
    melds: list[tuple[int, int, int]] = []
    for item in text.split(";"):
        tiles = _ordered_tiles(item)
        if len(tiles) != 3:
            raise ValueError("each --opp-melds entry must contain exactly three tiles")
        melds.append(tuple(tiles))
    return melds


def _opponent_view(args) -> OpponentView:
    """Build the modeled opponent from the shared --opp-* flags.

    Dealer identity is part of that state: settlement always applies the 莊 and
    連莊 premium to one seat, so leaving an opponent unflagged does not remove
    the premium, it just hands it to whichever seat the sampler filled first.
    """
    if args.opp_streak and not args.opp_dealer:
        raise ValueError("--opp-streak requires --opp-dealer")
    return OpponentView(
        parse_river(args.opp_river),
        _parse_opponent_melds(args.opp_melds),
        args.opp_declared,
        is_dealer=args.opp_dealer,
        dealer_streak=args.opp_streak if args.opp_dealer else 0,
    )


def _add_visible(*groups: tuple[int, ...] | list[int]) -> tuple[int, ...]:
    total = [0] * 34
    for group in groups:
        for tile, count in enumerate(group):
            total[tile] += count
    return tuple(total)


def _opponent_discard_counts(opponent: OpponentView) -> tuple[int, ...]:
    counts = [0] * 34
    for entry in opponent.river:
        tile = entry if isinstance(entry, int) else entry.tile
        counts[tile] += 1
    return tuple(counts)


def _opponent_holding_counts(opponent: OpponentView) -> tuple[int, ...]:
    counts = [0] * 34
    for meld in opponent.melds:
        for tile in meld:
            counts[tile] += 1
    return tuple(counts)


def _default_calibration_path() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "calibration.json"


def main() -> None:
    parser = _ArgumentParser(description="Taiwanese mahjong hand analyzer")
    parser.add_argument("tiles", nargs="?", help="compact tiles, e.g. 123m456p789s1122334z")
    parser.add_argument("--melds", type=int, default=0, help="number of declared melds (0-5)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--ukeire", action="store_true", help="list shanten-improving draws from a 16-tile hand")
    mode.add_argument("--analyze", action="store_true", help="rank discards from a 17-tile hand")
    mode.add_argument("--danger", action="store_true", help="rank M2 discards with one opponent's deal-in danger")
    mode.add_argument("--simulate", action="store_true", help="estimate self-draw tenpai and win probabilities")
    mode.add_argument("--ev", action="store_true", help="rank discards by approximate tai-unit EV")
    mode.add_argument("--declare", action="store_true", help="advise migi declaration from a 16-tile tenpai hand")
    mode.add_argument("--score", action="store_true", help="itemized tai scoring for a complete winning hand")
    mode.add_argument("--selfplay", action="store_true", help="run four-player self-play and append calibration counts")
    mode.add_argument("--selfplay-report", metavar="PATH", help="print a self-play calibration report")
    mode.add_argument("--quiz", action="store_true", help="generate and grade one seeded teaching position")
    mode.add_argument("--quiz-batch", type=int, metavar="N", help="print N seeded quiz drills and their best discards")
    parser.add_argument("--visible", help="compact notation for other tiles seen elsewhere")
    parser.add_argument("--opp-river", help="ordered compact notation for the modeled opponent's discards")
    parser.add_argument("--opp-melds", help="semicolon-separated three-tile declared melds, e.g. 123s;777s")
    parser.add_argument("--opp-declared", type=int, help="migi declaration river index (only 0 or 1)")
    parser.add_argument("--opp-dealer", action="store_true", help="the modeled opponent is the dealer (莊)")
    parser.add_argument("--opp-streak", type=int, default=0, help="the modeled opponent's 連莊 count (needs --opp-dealer)")
    parser.add_argument("--others", help="other players' discard kinds for fold estimation")
    parser.add_argument("--tile", help="show the danger shape breakdown for one discard tile (with --danger)")
    parser.add_argument("--my-melds", help="semicolon-separated declared melds of the scored hand, e.g. 123s;777z")
    parser.add_argument("--win-tile", help="winning tile for --score, e.g. 3z")
    parser.add_argument("--self-draw", action="store_true", help="the win was by self-draw (自摸)")
    parser.add_argument("--dealer", action="store_true", help="the winner is the dealer (莊家)")
    parser.add_argument("--streak", type=int, default=0, help="dealer repeat count for 連莊拉莊 (default: 0)")
    parser.add_argument("--migi", action="store_true", help="the winner had declared tenpai (migi)")
    parser.add_argument("--heavenly", action="store_true", help="dealer initial-hand win (天胡)")
    parser.add_argument("--earthly", action="store_true", help="non-dealer first-draw win (地胡)")
    parser.add_argument("--round-wind", help="round wind tile for --score, e.g. 1z")
    parser.add_argument("--seat-wind", help="seat wind tile for --score, e.g. 2z")
    parser.add_argument("--turns", type=int, help="simulation draws (default: 10; --ev/--declare: live-wall auto)")
    parser.add_argument("--sims", type=int, help="simulation trials (default: 5000; EV modes: 400 per discard)")
    parser.add_argument("--seed", type=int, help="random seed for simulation")
    parser.add_argument("--games", type=int, default=1, help="self-play games to run (default: 1)")
    parser.add_argument("--policies", help="four comma-separated self-play policies (attack, cautious, ev_aware)")
    parser.add_argument("--out", help="self-play calibration JSON destination")
    parser.add_argument("--answer", help="quiz discard answer, e.g. 3m")
    parser.add_argument(
        "--scheme",
        choices=("3-1", "5-2"),
        default="3-1",
        help="底/台 payout preset (default: 3-1)",
    )
    args = parser.parse_args()
    try:
        config = GameConfig.from_id(args.scheme)
        analysis = AnalysisContext(
            config,
            CalibrationProvider(_default_calibration_path()).load(),
        )
        scheme_line = (
            f"Scheme: {config.scheme_id} "
            f"(底{config.scheme.base_units}/台{config.scheme.tai_units})"
        )
        if args.quiz_batch is not None:
            if args.tiles:
                raise ValueError("tiles are not used with --quiz-batch")
            if args.answer:
                raise ValueError("--answer requires --quiz")
            if args.quiz_batch < 1:
                raise ValueError("--quiz-batch must be at least 1")
            next_seed = 0 if args.seed is None else args.seed
            for _ in range(args.quiz_batch):
                position = generate_position(next_seed, analysis)
                # The cheap ranking already names the best discard; no need to pay
                # grade()'s REFINE_SIMS re-estimation just to print one tile.
                discard = best_discard(position, analysis=analysis)
                print(f"seed {position.seed}: heuristic EV {_tile_name(discard)}")
                next_seed = position.seed + 1
            print(scheme_line)
            print(
                f"Calibration: {analysis.calibration.calibration_id}; "
                f"domain={analysis.calibration.domain}; "
                f"fallback_used={str(analysis.calibration.fallback_used).lower()}"
            )
            return
        if args.quiz:
            if args.tiles:
                raise ValueError("tiles are not used with --quiz")
            position = generate_position(0 if args.seed is None else args.seed, analysis)
            print(position.render())
            answer = args.answer if args.answer is not None else input("Discard tile: ")
            chosen = _single_tile(answer)
            quiz_grade = grade(position, chosen, analysis=analysis)
            print(scheme_line)
            print(
                f"Calibration: {analysis.calibration.calibration_id}; "
                f"domain={analysis.calibration.domain}; "
                f"fallback_used={str(analysis.calibration.fallback_used).lower()}"
            )
            marginal_note = " (marginal — hugs a verdict boundary)" if quiz_grade.marginal else ""
            print(f"Verdict: {quiz_grade.verdict}{marginal_note}")
            print(f"EV delta: {quiz_grade.ev_delta:.1f} tai")
            print(explain(quiz_grade))
            return
        if args.answer:
            raise ValueError("--answer requires --quiz")
        if args.selfplay_report:
            if args.tiles:
                raise ValueError("tiles are not used with --selfplay-report")
            print(format_report(load_table(args.selfplay_report)))
            return
        if args.selfplay:
            if args.tiles:
                raise ValueError("tiles are not used with --selfplay")
            if not args.out:
                raise ValueError("--selfplay requires --out")
            policies = ("attack", "cautious", "attack", "cautious")
            if args.policies:
                policies = tuple(args.policies.split(","))
                if len(policies) != 4 or any(policy not in POLICIES for policy in policies):
                    raise ValueError("--policies requires four entries from attack, cautious, ev_aware")
            games = play_games(args.games, args.seed, policies, config=config)
            metadata = {
                "seeds": [] if args.seed is None else [args.seed],
                "policy_mix": list(policies),
                "scheme": config.payload(),
            }
            if args.seed is not None:
                metadata["last_seed"] = args.seed
            document = write_merged_table(args.out, counts_from_games(games), metadata)
            print(scheme_line)
            print(f"self-play: appended {args.games} games; total {document['counts']['games']} games -> {args.out}")
            return
        if not args.tiles:
            raise ValueError("tiles are required unless using --selfplay or --selfplay-report")
        counts = parse_tiles(args.tiles)
        visible = parse_tiles(args.visible) if args.visible else None
        if args.tile and not args.danger:
            raise ValueError("--tile requires --danger")
        if args.ev:
            opponent = None
            if args.opp_river or args.opp_melds or args.opp_declared is not None or args.opp_dealer:
                if not args.opp_river:
                    raise ValueError("--ev opponent state requires --opp-river")
                opponent = _opponent_view(args)
            other_visible = (0,) * 34 if visible is None else visible
            accounting = TileAccounting(
                _add_visible(
                    other_visible,
                    _opponent_discard_counts(opponent) if opponent else (0,) * 34,
                ),
                _opponent_holding_counts(opponent) if opponent else (0,) * 34,
            )
            ev_visible = accounting.visible
            template = WinContext(
                winning_tile=0,
                dealer=args.dealer,
                dealer_streak=args.streak,
                migi_declared=args.migi,
                heavenly=args.heavenly,
                earthly=args.earthly,
                round_wind=_single_tile(args.round_wind),
                seat_wind=_single_tile(args.seat_wind),
            )
            turns = args.turns if args.turns is not None else remaining_draws(counts, accounting)
            entries = ev_rank(
                counts, [] if opponent is None else [opponent], ev_visible, args.melds, turns,
                args.sims or 400, args.seed, template,
                analysis.calibration.calibration, scheme=config.scheme,
            )
            print(f"Hand: {format_tiles(counts)}")
            print(scheme_line)
            print(
                f"Calibration: {analysis.calibration.calibration_id}; "
                f"domain={analysis.calibration.domain}; "
                f"fallback_used={str(analysis.calibration.fallback_used).lower()}"
            )
            if args.turns is None:
                print(f"Remaining draws (auto): {turns}")
            print("Discard  Net EV  P(win)  P(draw)  E[win value]  E[loss]")
            for entry in entries:
                value = "-" if entry.mean_win_value is None else f"{entry.mean_win_value:.2f}"
                discard = entry.label if entry.is_fold else _tile_name(entry.discard)
                print(
                    f"{discard:<7}  {entry.net_ev:>6.2f}  {entry.p_win:>6.3f}  "
                    f"{entry.p_draw:>6.3f}  {value:>12}  {entry.risk_ev:>7.2f}"
                )
            print("Note: EV is the mean signed payment over coherent four-seat terminals; E[loss] is its loss side.")
        elif args.declare:
            opponent = None
            if args.opp_river or args.opp_melds or args.opp_declared is not None or args.opp_dealer:
                if not args.opp_river:
                    raise ValueError("--declare opponent state requires --opp-river")
                opponent = _opponent_view(args)
            other_visible = (0,) * 34 if visible is None else visible
            accounting = TileAccounting(
                _add_visible(
                    other_visible,
                    _opponent_discard_counts(opponent) if opponent else (0,) * 34,
                ),
                _opponent_holding_counts(opponent) if opponent else (0,) * 34,
            )
            declare_visible = accounting.visible
            template = WinContext(
                winning_tile=0,
                dealer=args.dealer,
                dealer_streak=args.streak,
                heavenly=args.heavenly,
                earthly=args.earthly,
                round_wind=_single_tile(args.round_wind),
                seat_wind=_single_tile(args.seat_wind),
            )
            turns = args.turns if args.turns is not None else remaining_draws(counts, accounting)
            advice = declaration_ev(
                counts, declare_visible, turns, template, args.sims or 400, args.seed,
                [] if opponent is None else [opponent], config.scheme,
            )
            print(f"Hand: {format_tiles(counts)}")
            print(scheme_line)
            if args.turns is None:
                print(f"Remaining draws (auto): {turns}")
            print("Branch       P(win)  Surv P(win)  P(draw)  E[win value]  Net EV")
            for name, branch in (("Declare", advice.declared), ("Continue", advice.undeclared)):
                value = "-" if branch.mean_value_units is None else f"{branch.mean_value_units:.2f}"
                print(
                    f"{name:<11}  {branch.p_win:>6.3f}  {branch.survival_adjusted_p_win:>11.3f}  "
                    f"{branch.p_draw:>6.3f}  {value:>12}  {branch.net_ev:>6.2f}"
                )
            print(f"Recommendation: {'DECLARE migi' if advice.should_declare else 'DO NOT declare'}")
        elif args.danger:
            if not args.opp_river:
                raise ValueError("--danger requires --opp-river")
            opponent = _opponent_view(args)
            other_visible = (0,) * 34 if visible is None else visible
            danger_visible = _add_visible(
                other_visible,
                _opponent_discard_counts(opponent),
                _opponent_holding_counts(opponent),
            )
            analyses = rank_discards(counts, opponent, danger_visible, args.melds)
            calibration = analysis.calibration.calibration
            opponent_tenpai = analyses[0].tenpai if analyses else None
            opponent_fold = fold_score(opponent, parse_tiles(args.others) if args.others else [])
            print(f"Hand: {format_tiles(counts)}")
            print(scheme_line)
            if opponent_tenpai is not None:
                signals = ", ".join(f"{name}={value}" for name, value in opponent_tenpai.signals.items())
                run = int(opponent_tenpai.signals.get("trailing_tsumogiri_run", 0))
                calibrated = calibration.tenpai_probability(len(opponent.melds), len(opponent.river), run) if calibration else None
                probability = "unavailable" if calibrated is None else f"{calibrated:.3f}"
                if calibration:
                    print(f"Opponent tenpai: heuristic {opponent_tenpai.score:.2f}; calibrated P(tenpai) {probability} ({signals})")
                else:
                    print(f"Opponent tenpai: {opponent_tenpai.score:.2f} ({signals})")
            print(f"Opponent fold: {opponent_fold:.2f}")
            if calibration:
                print("Discard  Shanten  Total  Danger          P(deal-in)  ExpDanger  Accepted")
            else:
                print("Discard  Shanten  Total  Danger          ExpDanger  Accepted")
            for entry in analyses:
                analysis = entry.analysis
                danger = "SAFE(declared)" if "declared_safe" in entry.danger.modifiers else f"{entry.danger.score:.2f}"
                if calibration:
                    probability = calibration.deal_in_probability(entry.danger.score)
                    probability_text = "heuristic" if probability is None else f"{probability:.3f}"
                    print(
                        f"{_tile_name(analysis.discard):<7}  {analysis.shanten_after:<7}  "
                        f"{analysis.total:<5}  {danger:<14}  {probability_text:<10}  {entry.expected_danger:<9.2f}  {_accepted_kinds(analysis.ukeire)}"
                    )
                else:
                    print(
                        f"{_tile_name(analysis.discard):<7}  {analysis.shanten_after:<7}  "
                        f"{analysis.total:<5}  {danger:<14}  {entry.expected_danger:<9.2f}  {_accepted_kinds(analysis.ukeire)}"
                    )
            print("Note: danger, tenpai, and fold heuristics remain separate from bot-calibrated probabilities.")
            if args.tile:
                requested = _ordered_tiles(args.tile)
                if len(requested) != 1:
                    raise ValueError("--tile must name exactly one tile")
                selected = next((entry for entry in analyses if entry.discard == requested[0]), None)
                if selected is None:
                    raise ValueError("--tile must be present in the hand")
                print(f"Danger breakdown for {_tile_name(selected.discard)}: {selected.danger.score:.2f}")
                for shape in selected.danger.feasible_shapes:
                    required = ", ".join(_tile_name(tile) for tile in shape.required_tiles)
                    print(
                        f"  {shape.name}({required}): base {shape.base_weight:g}, "
                        f"river x{shape.river_multiplier:.3f}, weight {shape.weight:.3f}"
                    )
                modifiers = ", ".join(f"{name}=x{value:g}" for name, value in selected.danger.modifiers.items()) or "none"
                print(f"  Modifiers: {modifiers}")
        elif args.score:
            if not args.win_tile:
                raise ValueError("--score requires --win-tile")
            winning = _ordered_tiles(args.win_tile)
            if len(winning) != 1:
                raise ValueError("--win-tile must name exactly one tile")
            my_melds = _parse_opponent_melds(args.my_melds)
            context = WinContext(
                winning_tile=winning[0],
                self_draw=args.self_draw,
                dealer=args.dealer,
                dealer_streak=args.streak,
                migi_declared=args.migi,
                heavenly=args.heavenly,
                earthly=args.earthly,
                round_wind=_single_tile(args.round_wind),
                seat_wind=_single_tile(args.seat_wind),
            )
            result = score_hand(counts, my_melds, context)
            melds_text = args.my_melds or "-"
            print(f"Hand: {format_tiles(counts)} (melds: {melds_text})")
            print(scheme_line)
            print(f"Win tile: {_tile_name(winning[0])} ({'self-draw' if args.self_draw else 'ron'})")
            print("Tai breakdown:")
            for name, tai in result.items:
                print(f"  {name:<38} {tai}")
            print(f"Total: {result.total_tai} tai")
            print(
                f"Value: 底 {config.scheme.base_units} + 台 {config.scheme.tai_units}"
                f" × {result.total_tai} = {result.value_in(config.scheme)} units"
            )
        elif args.simulate:
            result = win_probability(counts, args.turns if args.turns is not None else 10, args.melds, visible, args.sims or 5000, args.seed)
            print(f"Hand: {format_tiles(counts)}")
            print(scheme_line)
            print("Turn  Tenpai %  Win %")
            for turn, (tenpai, win) in enumerate(zip(result.tenpai_by_turn, result.win_by_turn), start=1):
                print(f"{turn:<4}  {tenpai * 100:>7.2f}  {win * 100:>5.2f}")
            print(f"Totals: tenpai {result.p_tenpai * 100:.2f}%, win {result.p_win * 100:.2f}%")
            print("Note: self-draw-only estimate; opponent discards are not modeled.")
        elif args.ukeire:
            accepted = ukeire(counts, args.melds, visible)
            current_shanten = shanten(counts, args.melds)
            print(f"Hand: {format_tiles(counts)}")
            print(scheme_line)
            print(f"Shanten: {current_shanten}")
            for tile, remaining in accepted.items():
                print(f"{_tile_name(tile)}: {remaining}")
            print(f"Total: {sum(accepted.values())}")
        elif args.analyze:
            analyses = discard_analysis(counts, args.melds, visible)
            print(f"Hand: {format_tiles(counts)}")
            print(scheme_line)
            print("Discard  Shanten  Total  Accepted")
            for analysis in analyses:
                print(
                    f"{_tile_name(analysis.discard):<7}  {analysis.shanten_after:<7}  "
                    f"{analysis.total:<5}  {_accepted_kinds(analysis.ukeire)}"
                )
        else:
            current_shanten = shanten(counts, args.melds)
            print(f"Hand: {format_tiles(counts)}")
            print(scheme_line)
            print(f"Shanten: {current_shanten}")
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
