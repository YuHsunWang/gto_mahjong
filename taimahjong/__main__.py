"""Command-line entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .calibration import Calibration, counts_from_games, format_report, load_table, write_merged_table
from .danger import OpponentView, fold_score, parse_river, rank_discards
from .selfplay import play_games
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


def _add_visible(*groups: tuple[int, ...] | list[int]) -> tuple[int, ...]:
    total = [0] * 34
    for group in groups:
        for tile, count in enumerate(group):
            total[tile] += count
    return tuple(total)


def _public_counts(opponent: OpponentView) -> tuple[int, ...]:
    counts = [0] * 34
    for entry in opponent.river:
        tile = entry if isinstance(entry, int) else entry.tile
        counts[tile] += 1
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
    mode.add_argument("--selfplay", action="store_true", help="run four-player self-play and append calibration counts")
    mode.add_argument("--selfplay-report", metavar="PATH", help="print a self-play calibration report")
    parser.add_argument("--visible", help="compact notation for other tiles seen elsewhere")
    parser.add_argument("--opp-river", help="ordered compact notation for the modeled opponent's discards")
    parser.add_argument("--opp-melds", help="semicolon-separated three-tile declared melds, e.g. 123s;777s")
    parser.add_argument("--opp-declared", type=int, help="migi declaration river index (only 0 or 1)")
    parser.add_argument("--others", help="other players' discard kinds for fold estimation")
    parser.add_argument("--tile", help="show the danger shape breakdown for one discard tile (with --danger)")
    parser.add_argument("--turns", type=int, default=10, help="simulation draws (default: 10)")
    parser.add_argument("--sims", type=int, default=5000, help="simulation trials (default: 5000)")
    parser.add_argument("--seed", type=int, help="random seed for simulation")
    parser.add_argument("--games", type=int, default=1, help="self-play games to run (default: 1)")
    parser.add_argument("--out", help="self-play calibration JSON destination")
    args = parser.parse_args()
    try:
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
            games = play_games(args.games, args.seed)
            metadata = {"seeds": [] if args.seed is None else [args.seed]}
            if args.seed is not None:
                metadata["last_seed"] = args.seed
            document = write_merged_table(args.out, counts_from_games(games), metadata)
            print(f"self-play: appended {args.games} games; total {document['counts']['games']} games -> {args.out}")
            return
        if not args.tiles:
            raise ValueError("tiles are required unless using --selfplay or --selfplay-report")
        counts = parse_tiles(args.tiles)
        visible = parse_tiles(args.visible) if args.visible else None
        if args.tile and not args.danger:
            raise ValueError("--tile requires --danger")
        if args.danger:
            if not args.opp_river:
                raise ValueError("--danger requires --opp-river")
            opponent = OpponentView(parse_river(args.opp_river), _parse_opponent_melds(args.opp_melds), args.opp_declared)
            other_visible = (0,) * 34 if visible is None else visible
            danger_visible = _add_visible(other_visible, _public_counts(opponent))
            analyses = rank_discards(counts, opponent, danger_visible, args.melds)
            calibration_path = _default_calibration_path()
            calibration = Calibration.from_path(calibration_path) if calibration_path.exists() else None
            opponent_tenpai = analyses[0].tenpai if analyses else None
            opponent_fold = fold_score(opponent, parse_tiles(args.others) if args.others else [])
            print(f"Hand: {format_tiles(counts)}")
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
        elif args.simulate:
            result = win_probability(counts, args.turns, args.melds, visible, args.sims, args.seed)
            print(f"Hand: {format_tiles(counts)}")
            print("Turn  Tenpai %  Win %")
            for turn, (tenpai, win) in enumerate(zip(result.tenpai_by_turn, result.win_by_turn), start=1):
                print(f"{turn:<4}  {tenpai * 100:>7.2f}  {win * 100:>5.2f}")
            print(f"Totals: tenpai {result.p_tenpai * 100:.2f}%, win {result.p_win * 100:.2f}%")
            print("Note: self-draw-only estimate; opponent discards are not modeled.")
        elif args.ukeire:
            accepted = ukeire(counts, args.melds, visible)
            current_shanten = shanten(counts, args.melds)
            print(f"Hand: {format_tiles(counts)}")
            print(f"Shanten: {current_shanten}")
            for tile, remaining in accepted.items():
                print(f"{_tile_name(tile)}: {remaining}")
            print(f"Total: {sum(accepted.values())}")
        elif args.analyze:
            analyses = discard_analysis(counts, args.melds, visible)
            print(f"Hand: {format_tiles(counts)}")
            print("Discard  Shanten  Total  Accepted")
            for analysis in analyses:
                print(
                    f"{_tile_name(analysis.discard):<7}  {analysis.shanten_after:<7}  "
                    f"{analysis.total:<5}  {_accepted_kinds(analysis.ukeire)}"
                )
        else:
            current_shanten = shanten(counts, args.melds)
            print(f"Hand: {format_tiles(counts)}")
            print(f"Shanten: {current_shanten}")
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
