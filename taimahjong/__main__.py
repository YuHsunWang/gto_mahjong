"""Command-line entry point."""

from __future__ import annotations

import argparse
import sys

from .shanten import shanten
from .tiles import format_tiles, parse_tiles
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


def main() -> None:
    parser = _ArgumentParser(description="Taiwanese mahjong shanten calculator")
    parser.add_argument("tiles", help="compact tiles, e.g. 123m456p789s1122334z")
    parser.add_argument("--melds", type=int, default=0, help="number of declared melds (0-5)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--ukeire", action="store_true", help="list shanten-improving draws from a 16-tile hand")
    mode.add_argument("--analyze", action="store_true", help="rank discards from a 17-tile hand")
    parser.add_argument("--visible", help="compact notation for tiles seen elsewhere")
    args = parser.parse_args()
    try:
        counts = parse_tiles(args.tiles)
        visible = parse_tiles(args.visible) if args.visible else None
        if args.ukeire:
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
