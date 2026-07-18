"""Regression coverage for common-random-number EV comparisons."""

from taimahjong.ev import ev_rank
from taimahjong.tiles import parse_tiles


def test_equivalent_lone_wind_discards_share_crn_ev_components():
    # 3z and 4z are interchangeable lone winds; their post-discard hands
    # differ only by that wind label, so shared trials must produce the same EV.
    hand = parse_tiles("123m123p123s11122234z")
    entries = {
        entry.discard: entry
        for entry in ev_rank(hand, [], (0,) * 34, turns=5, sims=24, seed=47, top_k=34)
        if not entry.is_fold
    }

    three_wind, four_wind = entries[29], entries[30]
    assert (
        three_wind.p_win,
        three_wind.mean_win_value,
        three_wind.attack_ev,
    ) == (
        four_wind.p_win,
        four_wind.mean_win_value,
        four_wind.attack_ev,
    )
