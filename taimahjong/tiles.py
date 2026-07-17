"""Tile-count representation and compact hand notation."""

from __future__ import annotations

SUITS = "mpsz"
SUIT_OFFSETS = {"m": 0, "p": 9, "s": 18, "z": 27}


def validate_counts(counts: tuple[int, ...] | list[int]) -> tuple[int, ...]:
    """Return validated immutable counts for the 34 tile kinds."""
    result = tuple(counts)
    if len(result) != 34:
        raise ValueError("tile counts must contain exactly 34 entries")
    if any(not isinstance(count, int) or isinstance(count, bool) for count in result):
        raise ValueError("tile counts must be integers")
    if any(count < 0 or count > 4 for count in result):
        raise ValueError("each tile count must be between 0 and 4")
    return result


def parse_tiles(text: str) -> tuple[int, ...]:
    """Parse compact notation such as ``123m456p789s11z``."""
    if not isinstance(text, str) or not text:
        raise ValueError("tile notation must be a non-empty string")

    counts = [0] * 34
    digits = ""
    for char in text:
        if char.isdigit():
            digits += char
            continue
        if char not in SUITS or not digits:
            raise ValueError("expected one or more digits followed by m, p, s, or z")
        limit = 7 if char == "z" else 9
        offset = SUIT_OFFSETS[char]
        for digit in digits:
            value = int(digit)
            if not 1 <= value <= limit:
                raise ValueError(f"{digit}{char} is not a valid tile")
            counts[offset + value - 1] += 1
        digits = ""
    if digits:
        raise ValueError("tile notation cannot end with digits without a suit")
    return validate_counts(counts)


def format_tiles(counts: tuple[int, ...] | list[int]) -> str:
    """Format 34 tile counts as compact notation in m/p/s/z order."""
    checked = validate_counts(counts)
    pieces: list[str] = []
    for suit in SUITS:
        offset = SUIT_OFFSETS[suit]
        limit = 7 if suit == "z" else 9
        digits = "".join(str(value + 1) * checked[offset + value] for value in range(limit))
        if digits:
            pieces.append(digits + suit)
    return "".join(pieces)
