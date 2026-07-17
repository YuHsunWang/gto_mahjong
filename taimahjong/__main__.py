"""Command-line entry point."""

from __future__ import annotations

import argparse

from .shanten import shanten
from .tiles import format_tiles, parse_tiles


def main() -> None:
    parser = argparse.ArgumentParser(description="Taiwanese mahjong shanten calculator")
    parser.add_argument("tiles", help="compact tiles, e.g. 123m456p789s1122334z")
    parser.add_argument("--melds", type=int, default=0, help="number of declared melds (0-5)")
    args = parser.parse_args()
    counts = parse_tiles(args.tiles)
    print(f"Hand: {format_tiles(counts)}")
    print(f"Shanten: {shanten(counts, args.melds)}")


if __name__ == "__main__":
    main()
