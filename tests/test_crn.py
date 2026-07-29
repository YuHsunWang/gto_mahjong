"""Regression coverage for common-random-number EV comparisons."""

from taimahjong.ev import ev_rank
from taimahjong.tiles import parse_tiles


def test_equivalent_lone_wind_discards_agree_within_reported_uncertainty():
    # 3z and 4z are interchangeable lone winds; their post-discard hands
    # differ only by that wind label. A determinized opponent can break the
    # symmetry in one sampled world, so require each estimate to cover the
    # other's expectation-equivalent estimate instead of exact trial equality.
    hand = parse_tiles("123m123p123s11122234z")
    entries = {
        entry.discard: entry
        for entry in ev_rank(
            hand, [], (0,) * 34, turns=5, sims=1000, seed=47, top_k=34,
        )
        if not entry.is_fold
    }

    three_wind, four_wind = entries[29], entries[30]
    assert three_wind.ci95_low <= four_wind.net_ev <= three_wind.ci95_high
    assert four_wind.ci95_low <= three_wind.net_ev <= four_wind.ci95_high
