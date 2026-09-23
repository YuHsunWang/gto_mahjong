"""Cases for the empirical game only.  This is *not* an acceptance corpus.

``reference_ev.representative_reference_cases`` is a 26-case acceptance corpus:
every hand in it, the actor's and the opponents' alike, is hand-built to drive
a particular settlement branch through the exact oracle, and
``MIN_GATE_CASES = 26`` is a gate four test modules depend on.  Growing it to
resolve an equilibrium would tie two unrelated purposes together, so the
empirical game gets its own corpus here and that one is left alone.

The split is safe because of what ``best_response.observation_for`` actually
reads out of a case.  It takes the actor's 17-tile hand, the *length* of the
wall, the seats, the dealer streak, the scoring scheme, and which opponents
have declared -- and nothing else.  ``build_game`` then resamples the hidden
hands and the wall from production's belief model, so the opponent hands and
the wall tiles written into a case here are never read by the empirical game.
They exist only to satisfy ``ReferenceState``'s own validation (16 tiles each,
four physical copies per tile), and are filled in mechanically below.  A case
built this way would be *wrong* for the reference oracle, which does read
them; that is the reason these two corpora cannot be one.

The design, 104 hand templates x 4 wall depths = 416 cases:

* Every template appears once at each wall depth, so wall depth is not
  confounded with the hand -- the step 3b corpus had 18 of its 26 cases at
  depth 4 and only 2 each at depths 2 and 3, which is why its per-depth table
  could only be read in the depth-4 row.
* Wall depth decides which roles exist at all: after the actor discards, the
  remaining ``d`` draws go to roles 1, 2, 3, 1.  At depth 1 only role 1 ever
  draws, so roles 2 and 3 have an exactly zero deviation gain there; at depth 2
  role 3 does.  An even split over depths therefore spends a quarter of the
  corpus on cases where role 3 cannot move.
* Seat, dealer streak, scoring scheme and declared-opponent count are assigned
  by ``_FACTORS``, searched in eight blocks of 52 rows (2026-08-25 through
  2026-08-27), each block exactly balanced on its own: 26/26 on acting seat,
  26/26 on dealer streak, 26/26 on scheme and 13/13/13/13 on threat count,
  with each depth slot within one of even.  Because each block balances
  independently, every 13-template prefix is itself a balanced corpus, which
  is what keeps the tables measured at 52 and 104 cases reproducible after
  the corpus grew: ``empirical_game_cases(13)`` and ``(26)`` still return the
  exact cases those tables used.

The corpus was sized to a specific question.  At 104 cases the four-player
game over {efficiency, deal_in_risk} excluded 15 of 16 profiles and left DDDD
at a regret of -0.0096 tai with a half-width of 0.013 to 0.020, so deciding it
needs the half-width under 0.0096 -- roughly 190 to 450 cases.  416 is the
four-fold step that covers the wider of those two estimates.

Ninety-nine of the hundred and four hands were drawn by uniform sampling over
the tile set and kept only if they landed in the wanted shanten stratum (seeds
20260825, 20260826 and 20260827 for the successive additions).  That is wider
than the five hand-built templates inherited from the acceptance corpus, but it
is *not* a sample of hands real play reaches after twenty turns: a uniformly
drawn 2-shanten hand carries more isolated tiles than a played one.  Any claim
from this corpus carries that with it.
"""

from __future__ import annotations

from .reference_ev import (
    ReferenceCase,
    ReferencePlayer,
    ReferenceState,
    ReferenceStrata,
    _ACTOR_HANDS,
    _DEAL_IN_COUNTS,
    _DEAL_IN_TILES,
    _DEPTH_NAMES,
)
from .ev import _production_shanten
from .scoring import SCHEME_3_1, SCHEME_5_2, ScoringScheme
from .shanten import shanten
from .tiles import parse_tiles


def _draw_family_hand(hand_state: str) -> tuple[int, ...]:
    """The acceptance corpus's own draw-family actor hand, tile for tile."""
    hand = list(parse_tiles(_ACTOR_HANDS[hand_state]))
    hand[26] += 1  # the unrelated 9s post-draw tile, as in reference_ev
    return tuple(hand)


def _deal_in_family_hand(hand_state: str) -> tuple[int, ...]:
    """The acceptance corpus's own deal-in actor hand, tile for tile."""
    hand = [0] * 34
    for tile, count in zip(_DEAL_IN_TILES, _DEAL_IN_COUNTS[hand_state]):
        hand[tile] = count
    return tuple(hand)


# Eight hands drawn uniformly and filtered to a shanten stratum, plus the five
# the acceptance corpus already uses, so the two tables stay comparable on at
# least part of the corpus.
_SAMPLED_HANDS: tuple[tuple[str, str], ...] = (
    ("tenpai", "34589m333456p55678s6z"),
    ("tenpai", "356777m11134p789s666z"),
    ("tenpai", "4566m1118p123567s222z"),
    ("1-shanten", "57m123388999p355589s"),
    ("1-shanten", "11134578m56p678s1333z"),
    ("1-shanten", "12334789m458p66s4555z"),
    ("2-shanten", "14557m2346899p345s13z"),
    ("2-shanten", "26m234p12377899s2267z"),
    # Added 2026-08-26 to take the corpus from 13 templates to 26.
    ("tenpai", "88m222345789p356666s"),
    ("tenpai", "78999m122223p333s336z"),
    ("tenpai", "66789m3445p11223789s"),
    ("tenpai", "113459m345p678s22444z"),
    ("tenpai", "56799m234455p333999s"),
    ("1-shanten", "128m567888p23468s556z"),
    ("1-shanten", "15m23999p2455778899s"),
    ("1-shanten", "116m333444p1257789s5z"),
    ("1-shanten", "2479m119p2233344789s"),
    ("2-shanten", "5567788m455666p9s255z"),
    ("2-shanten", "99m23467889p3s345556z"),
    ("2-shanten", "1235678m6899p22248s4z"),
    ("2-shanten", "566679m1267899p28s44z"),
    # Added 2026-08-27 to take the corpus from 26 templates to 104, the size
    # the DDDD interval needs; same procedure, seed 20260827.
    ("tenpai", "22789m3457p455667s22z"),
    ("tenpai", "9m123678p77899s11177z"),
    ("tenpai", "456m3388p333456s4777z"),
    ("tenpai", "234m22256788p777s233z"),
    ("tenpai", "13567m12388p2346669s"),
    ("tenpai", "24567999p456999s155z"),
    ("tenpai", "567m57778899p277s222z"),
    ("tenpai", "57m34577p1122335679s"),
    ("tenpai", "1156778899m345p777s7z"),
    ("tenpai", "55999m2346788p678s77z"),
    ("tenpai", "33366678m1236p567s22z"),
    ("tenpai", "34789m345p12377s1777z"),
    ("tenpai", "1113455m2348p233334s"),
    ("tenpai", "456789m11789p678s377z"),
    ("tenpai", "123668m23344566788p"),
    ("tenpai", "222m12678p3457899s77z"),
    ("tenpai", "123677889m889p23789s"),
    ("tenpai", "3458999m567p111999s6z"),
    ("tenpai", "122378889m678p34568s"),
    ("tenpai", "1244789m234456p456s2z"),
    ("tenpai", "22567m78p444678s3336z"),
    ("tenpai", "234555666p567s22237z"),
    ("tenpai", "123677889m456p78s144z"),
    ("tenpai", "229m13456p233445678s"),
    ("tenpai", "12345777p345567s114z"),
    ("tenpai", "789m136789p567s66777z"),
    ("1-shanten", "2488m34678p7899s4447z"),
    ("1-shanten", "456888m2222499p35s17z"),
    ("1-shanten", "115789m12p111367789s"),
    ("1-shanten", "344556m355p15589s666z"),
    ("1-shanten", "456m12367p557789s667z"),
    ("1-shanten", "366m5579p1234444789s"),
    ("1-shanten", "55678m2499p4569s1333z"),
    ("1-shanten", "234m2244556p13666s67z"),
    ("1-shanten", "4m146778899p567s2666z"),
    ("1-shanten", "33789m1355568p24556s"),
    ("1-shanten", "2225m4456789p2267s55z"),
    ("1-shanten", "344489m56p222557899s"),
    ("1-shanten", "678m267p456889s66777z"),
    ("1-shanten", "345789m12336788p12s1z"),
    ("1-shanten", "23567m12346p33399s25z"),
    ("1-shanten", "14567m345777p12357s5z"),
    ("1-shanten", "9m57p12233345678s335z"),
    ("1-shanten", "236m2p34678s22233344z"),
    ("1-shanten", "34578899m249p22678s7z"),
    ("1-shanten", "567777m23359p111s355z"),
    ("1-shanten", "2456m11167p114777s11z"),
    ("1-shanten", "24m5559p237889s44466z"),
    ("1-shanten", "5678m345789p111249s3z"),
    ("1-shanten", "123445667m2257s2666z"),
    ("1-shanten", "123345899m123p12555z"),
    ("1-shanten", "345m1223455678p38s33z"),
    ("2-shanten", "1334m1336778p789s677z"),
    ("2-shanten", "789m5666688p23369s55z"),
    ("2-shanten", "112348m1356p222446s6z"),
    ("2-shanten", "4567789m89p39s114666z"),
    ("2-shanten", "126m2224789p12367s57z"),
    ("2-shanten", "88m446889p111123s234z"),
    ("2-shanten", "668m446p122356s55566z"),
    ("2-shanten", "3478m235p2345568889s"),
    ("2-shanten", "24m133367p336s445556z"),
    ("2-shanten", "4566m245567p135s2244z"),
    ("2-shanten", "22455666689m668p56s7z"),
    ("2-shanten", "123467m4568p124677s2z"),
    ("2-shanten", "114569m246p23478s224z"),
    ("2-shanten", "456689m5799p555679s4z"),
    ("2-shanten", "2479m3358p333456s144z"),
    ("2-shanten", "12445799m234p4789s35z"),
    ("2-shanten", "59m1223337899p23479s"),
    ("2-shanten", "368m222359p22678s113z"),
    ("2-shanten", "1357m2255888p23458s5z"),
    ("2-shanten", "1679m1222255678s557z"),
    ("2-shanten", "2224m3346p345569s255z"),
    ("2-shanten", "23489m1388p134557s47z"),
    ("2-shanten", "44789m36678p444688s4z"),
    ("2-shanten", "59m1234789p1234579s6z"),
    ("2-shanten", "12777m268p13357789s7z"),
    ("2-shanten", "55678m244556678p1s24z"),
)

_SHANTEN_OF = {"tenpai": 0, "1-shanten": 1, "2-shanten": 2}


def actor_hands() -> tuple[tuple[str, str, tuple[int, ...]], ...]:
    """The 26 (name, shanten stratum, 17-tile hand) templates, in table order.

    Order is fixed: the first thirteen are the templates the 52-case tables
    were measured on, so truncating this tuple reproduces that corpus.
    """
    templates: list[tuple[str, str, tuple[int, ...]]] = [
        ("corpus-draw-tenpai", "tenpai", _draw_family_hand("tenpai")),
        ("corpus-draw-1-shanten", "1-shanten", _draw_family_hand("1-shanten")),
        ("corpus-draw-2-shanten", "2-shanten", _draw_family_hand("2-shanten")),
        ("corpus-deal-in-1-shanten", "1-shanten", _deal_in_family_hand("1-shanten")),
        ("corpus-deal-in-2-shanten", "2-shanten", _deal_in_family_hand("2-shanten")),
    ]
    for index, (hand_state, text) in enumerate(_SAMPLED_HANDS, start=1):
        templates.append((f"sampled-{hand_state}-{index}", hand_state, parse_tiles(text)))
    for name, hand_state, hand in templates:
        if sum(hand) != 17:
            raise AssertionError(f"{name} is not a 17-tile post-draw hand")
        if shanten(hand) != _SHANTEN_OF[hand_state]:
            raise AssertionError(f"{name} no longer matches its shanten stratum")
    return tuple(templates)


# (acting seat, dealer streak index, scheme index, declared opponents) per
# case, in template-major order.  Searched once for exact marginal balance;
# see the module docstring.
_FACTORS: tuple[tuple[int, int, int, int], ...] = (
    (0, 1, 0, 0), (0, 1, 0, 2), (1, 0, 0, 1), (0, 0, 1, 2),
    (0, 0, 0, 1), (1, 1, 0, 1), (0, 1, 1, 2), (1, 0, 1, 2),
    (1, 1, 0, 0), (1, 1, 0, 2), (1, 0, 0, 0), (0, 1, 1, 0),
    (0, 0, 1, 3), (1, 0, 1, 0), (0, 1, 1, 3), (1, 1, 0, 0),
    (0, 1, 1, 2), (1, 1, 1, 1), (0, 0, 0, 2), (1, 1, 1, 3),
    (0, 1, 0, 0), (1, 1, 1, 2), (1, 1, 0, 3), (1, 0, 0, 1),
    (0, 1, 0, 1), (0, 0, 1, 2), (0, 1, 1, 3), (1, 0, 0, 3),
    (1, 1, 1, 2), (0, 0, 0, 3), (0, 0, 1, 1), (1, 1, 0, 3),
    (1, 0, 0, 2), (0, 0, 0, 0), (0, 1, 0, 2), (1, 1, 1, 1),
    (1, 0, 1, 0), (0, 1, 0, 3), (1, 0, 1, 1), (0, 0, 0, 2),
    (0, 0, 0, 3), (0, 0, 1, 1), (1, 1, 1, 0), (0, 0, 1, 0),
    (1, 0, 1, 3), (1, 1, 1, 0), (1, 0, 0, 0), (0, 1, 1, 1),
    (1, 0, 1, 1), (1, 0, 1, 3), (0, 1, 0, 3), (0, 0, 0, 1),
    # Second block, searched 2026-08-26 for templates 13 through 25.  It
    # balances on its own so the first block keeps meaning what it meant.
    (0, 0, 1, 2), (1, 1, 1, 0), (0, 0, 0, 1), (0, 0, 1, 0),
    (0, 0, 1, 1), (0, 1, 1, 1), (1, 1, 0, 0), (1, 0, 0, 3),
    (0, 0, 1, 2), (1, 1, 0, 0), (0, 0, 1, 0), (0, 0, 1, 1),
    (1, 0, 1, 3), (1, 0, 1, 3), (1, 0, 1, 1), (0, 1, 0, 2),
    (0, 1, 1, 2), (1, 1, 0, 2), (0, 1, 1, 0), (1, 0, 1, 1),
    (1, 1, 0, 3), (1, 0, 1, 2), (0, 0, 1, 3), (0, 0, 0, 2),
    (1, 1, 0, 1), (0, 0, 0, 1), (1, 0, 0, 2), (1, 1, 1, 3),
    (1, 1, 0, 3), (0, 0, 0, 3), (1, 1, 1, 2), (1, 1, 0, 2),
    (1, 0, 0, 0), (0, 1, 0, 2), (1, 1, 0, 1), (1, 1, 1, 1),
    (1, 0, 0, 3), (1, 0, 0, 1), (1, 0, 1, 2), (0, 1, 0, 1),
    (0, 1, 0, 0), (0, 0, 0, 2), (0, 1, 1, 0), (1, 1, 1, 0),
    (0, 1, 0, 0), (1, 0, 1, 0), (0, 0, 0, 3), (0, 1, 1, 3),
    (1, 1, 1, 1), (0, 1, 1, 3), (0, 1, 0, 3), (0, 0, 0, 0),
    # Blocks 3 through 8, searched 2026-08-27 for templates 26 through 103.
    # Each balances on its own, so every 13-template prefix stays balanced.
    (1, 1, 0, 2), (1, 1, 0, 2), (0, 0, 1, 1), (0, 1, 0, 2),
    (1, 1, 1, 0), (0, 0, 0, 3), (0, 1, 0, 2), (1, 0, 1, 3),
    (0, 1, 1, 3), (0, 0, 0, 1), (1, 0, 0, 3), (0, 1, 1, 3),
    (0, 1, 0, 0), (1, 0, 0, 0), (0, 1, 1, 0), (0, 1, 1, 2),
    (0, 1, 0, 1), (1, 1, 1, 3), (1, 0, 0, 2), (1, 0, 1, 1),
    (0, 0, 0, 2), (0, 0, 1, 2), (1, 1, 0, 3), (1, 1, 0, 0),
    (1, 0, 1, 1), (0, 1, 0, 3), (1, 0, 0, 1), (0, 0, 1, 3),
    (1, 1, 1, 0), (0, 0, 1, 0), (1, 1, 0, 3), (1, 0, 0, 2),
    (0, 0, 0, 2), (1, 1, 1, 1), (0, 1, 1, 1), (1, 1, 0, 0),
    (1, 1, 1, 1), (0, 0, 0, 0), (0, 0, 1, 0), (1, 0, 0, 1),
    (0, 0, 0, 3), (1, 0, 1, 2), (1, 1, 1, 2), (0, 0, 1, 3),
    (1, 0, 1, 3), (0, 1, 1, 1), (0, 1, 1, 0), (1, 0, 0, 0),
    (0, 0, 1, 2), (1, 1, 0, 1), (1, 0, 1, 0), (0, 1, 0, 1),
    (1, 1, 1, 2), (0, 0, 1, 1), (1, 1, 0, 2), (1, 1, 0, 3),
    (0, 1, 1, 1), (1, 1, 0, 3), (0, 1, 0, 2), (0, 0, 1, 1),
    (0, 1, 1, 3), (0, 1, 1, 0), (1, 0, 0, 1), (1, 1, 1, 0),
    (0, 0, 0, 2), (0, 1, 1, 2), (1, 0, 1, 1), (1, 0, 0, 0),
    (0, 1, 0, 2), (1, 0, 0, 3), (1, 1, 1, 3), (0, 1, 1, 2),
    (0, 1, 1, 3), (0, 0, 0, 2), (0, 0, 1, 0), (1, 1, 0, 2),
    (0, 0, 0, 0), (0, 1, 0, 3), (1, 0, 1, 3), (1, 1, 1, 0),
    (1, 1, 0, 1), (0, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 3),
    (1, 0, 1, 2), (1, 0, 1, 2), (0, 1, 0, 1), (1, 0, 1, 0),
    (1, 1, 0, 0), (1, 0, 0, 3), (0, 1, 1, 0), (0, 1, 0, 1),
    (1, 0, 1, 1), (0, 1, 1, 1), (0, 0, 0, 1), (1, 0, 0, 1),
    (1, 0, 0, 0), (1, 0, 1, 0), (1, 1, 1, 3), (0, 0, 1, 2),
    (0, 0, 0, 3), (1, 1, 1, 1), (1, 0, 0, 2), (0, 0, 0, 3),
    (0, 0, 1, 3), (1, 1, 1, 0), (1, 0, 0, 1), (1, 1, 0, 2),
    (0, 1, 0, 1), (1, 0, 1, 0), (0, 1, 0, 2), (1, 0, 1, 0),
    (1, 0, 0, 0), (0, 1, 1, 0), (0, 0, 1, 1), (0, 1, 1, 1),
    (0, 1, 1, 2), (0, 1, 1, 2), (1, 1, 1, 1), (1, 0, 0, 2),
    (0, 0, 0, 0), (1, 1, 0, 1), (0, 1, 1, 3), (1, 1, 0, 3),
    (1, 1, 1, 1), (0, 0, 1, 2), (1, 1, 1, 3), (1, 1, 0, 2),
    (1, 1, 1, 0), (1, 1, 0, 1), (0, 1, 0, 2), (1, 0, 1, 2),
    (0, 0, 0, 1), (0, 0, 0, 2), (1, 0, 1, 3), (0, 1, 0, 1),
    (1, 0, 0, 1), (0, 1, 1, 3), (1, 1, 0, 0), (1, 0, 1, 1),
    (1, 1, 1, 2), (1, 0, 0, 3), (0, 0, 0, 3), (0, 0, 1, 0),
    (0, 0, 0, 3), (1, 1, 0, 3), (1, 0, 0, 0), (0, 0, 1, 3),
    (1, 1, 1, 3), (0, 0, 1, 0), (0, 0, 0, 0), (0, 1, 0, 3),
    (0, 0, 1, 2), (0, 0, 0, 1), (1, 0, 1, 2), (0, 1, 0, 0),
    (0, 1, 1, 3), (0, 0, 0, 2), (1, 0, 0, 3), (1, 0, 0, 1),
    (0, 1, 1, 1), (0, 1, 0, 1), (0, 0, 1, 2), (1, 1, 1, 2),
    (1, 0, 0, 3), (1, 0, 1, 0), (0, 1, 0, 3), (0, 0, 0, 1),
    (0, 0, 1, 3), (1, 1, 0, 3), (0, 1, 1, 0), (0, 0, 1, 1),
    (0, 1, 0, 2), (1, 0, 1, 3), (0, 1, 0, 3), (0, 0, 1, 3),
    (1, 0, 0, 0), (1, 1, 1, 1), (0, 0, 0, 3), (1, 1, 0, 0),
    (0, 0, 0, 0), (0, 0, 1, 1), (1, 1, 1, 0), (1, 0, 0, 2),
    (1, 1, 0, 2), (0, 1, 0, 2), (1, 0, 1, 2), (0, 1, 1, 2),
    (1, 1, 0, 0), (0, 1, 0, 0), (0, 0, 1, 2), (0, 0, 0, 0),
    (1, 0, 0, 2), (1, 0, 1, 0), (1, 0, 0, 1), (0, 1, 1, 0),
    (0, 1, 1, 1), (1, 0, 1, 3), (0, 1, 0, 0), (1, 1, 1, 3),
    (1, 1, 1, 1), (1, 1, 0, 2), (1, 0, 1, 1), (0, 1, 1, 3),
    (1, 0, 1, 2), (0, 0, 1, 0), (1, 1, 0, 1), (1, 1, 0, 1),
    (1, 1, 1, 1), (0, 0, 1, 1), (1, 1, 1, 0), (1, 1, 0, 0),
    (0, 1, 0, 1), (0, 1, 0, 3), (0, 0, 0, 2), (1, 0, 1, 0),
    (1, 0, 0, 0), (0, 0, 1, 2), (1, 0, 1, 3), (1, 1, 1, 2),
    (0, 0, 1, 0), (1, 0, 1, 2), (1, 1, 0, 3), (1, 0, 1, 1),
    (1, 1, 0, 2), (0, 1, 1, 0), (0, 0, 0, 1), (0, 1, 0, 1),
    (1, 0, 1, 3), (1, 1, 0, 2), (0, 1, 1, 2), (0, 0, 1, 3),
    (1, 1, 1, 0), (0, 1, 1, 1), (0, 1, 1, 0), (1, 0, 0, 1),
    (0, 1, 1, 1), (1, 1, 1, 3), (1, 0, 0, 1), (0, 1, 1, 3),
    (1, 0, 0, 2), (0, 0, 0, 0), (1, 1, 1, 1), (0, 0, 0, 3),
    (0, 0, 1, 1), (1, 1, 0, 1), (0, 1, 0, 2), (1, 0, 0, 3),
    (0, 0, 0, 3), (1, 1, 0, 0), (1, 0, 0, 3), (0, 1, 1, 2),
    (1, 1, 1, 3), (1, 0, 0, 0), (0, 0, 0, 0), (0, 1, 0, 0),
    (0, 1, 0, 2), (0, 0, 1, 3), (1, 0, 1, 2), (0, 0, 0, 2),
    (1, 1, 0, 1), (1, 0, 1, 1), (0, 0, 0, 0), (1, 0, 0, 0),
    (0, 1, 1, 3), (1, 0, 0, 3), (1, 1, 0, 0), (0, 0, 1, 3),
    (1, 0, 1, 2), (0, 0, 1, 0), (1, 0, 1, 0), (1, 1, 0, 3),
    (1, 0, 0, 1), (0, 1, 0, 2), (0, 1, 1, 1), (0, 0, 0, 3),
    (0, 0, 0, 1), (1, 1, 1, 2), (1, 1, 1, 3), (1, 1, 1, 1),
    (0, 0, 1, 0), (0, 1, 1, 3), (1, 0, 1, 3), (0, 0, 0, 2),
    (1, 1, 1, 3), (1, 1, 0, 2), (0, 0, 0, 2), (1, 0, 1, 0),
    (1, 1, 0, 0), (0, 1, 0, 0), (0, 0, 1, 2), (0, 1, 0, 2),
    (1, 0, 0, 2), (0, 0, 1, 1), (0, 1, 0, 3), (0, 0, 1, 1),
    (0, 0, 0, 0), (1, 1, 1, 1), (0, 1, 0, 1), (1, 1, 0, 1),
    (1, 1, 1, 2), (0, 1, 0, 0), (1, 0, 1, 2), (1, 1, 1, 0),
    (0, 1, 0, 3), (0, 0, 1, 3), (1, 0, 1, 3), (0, 1, 1, 2),
    (0, 1, 1, 0), (1, 0, 0, 1), (0, 1, 0, 1), (1, 0, 0, 2),
)

_STREAKS = (0, 2)
_SCHEMES: tuple[ScoringScheme, ScoringScheme] = (SCHEME_3_1, SCHEME_5_2)


def _filler(actor: tuple[int, ...], wall_depth: int) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Deal three legal 16-tile opponent hands and a wall from what is left.

    Dealt one copy at a time in tile order and rotating between opponents, so
    the hands come out spread across the whole tile set rather than stacked on
    a few tiles.  This matters only to keep them far from complete: a hand that
    had already won is not a state the actor could be deciding in, and
    ``sample_worlds`` rejects such worlds when it draws the real ones.
    """
    supply = [4 - count for count in actor]
    wall = []
    for tile in range(33, -1, -1):
        while supply[tile] and len(wall) < wall_depth:
            supply[tile] -= 1
            wall.append(tile)
        if len(wall) == wall_depth:
            break
    if len(wall) < wall_depth:
        raise AssertionError("not enough tiles left for the wall")
    hands = [[0] * 34 for _ in range(3)]
    seat = 0
    for _ in range(3 * 16):
        for offset in range(34):
            tile = (offset * 7 + seat * 11) % 34
            if supply[tile] and hands[seat][tile] < 4:
                supply[tile] -= 1
                hands[seat][tile] += 1
                break
        else:
            raise AssertionError("ran out of tiles while dealing opponents")
        seat = (seat + 1) % 3
    for hand in hands:
        if sum(hand) != 16:
            raise AssertionError("filler opponent hand is not 16 tiles")
        if _production_shanten(tuple(hand), 0) == -1:
            raise AssertionError("filler opponent hand is already complete")
    return tuple(tuple(hand) for hand in hands), tuple(wall)


def empirical_game_cases(templates_used: int | None = None) -> tuple[ReferenceCase, ...]:
    """The corpus: every actor hand at each of the four wall depths.

    ``templates_used`` truncates the template list, which is how the 52-case
    corpus the step 3c tables were measured on stays reachable: pass 13.  Each
    block of thirteen templates is separately balanced, so a truncation at a
    block boundary is still a balanced corpus; anywhere else is not.
    """
    templates = actor_hands()
    if templates_used is not None:
        if not 1 <= templates_used <= len(templates):
            raise ValueError("templates_used is outside the template list")
        if templates_used % 13:
            raise ValueError("truncate at a block boundary or the corpus is unbalanced")
        templates = templates[:templates_used]
    depths = tuple(sorted(_DEPTH_NAMES))
    cases = []
    for template_index, (name, hand_state, hand) in enumerate(templates):
        for depth_index, wall_depth in enumerate(depths):
            index = template_index * len(depths) + depth_index
            acting_seat, streak_index, scheme_index, threats = _FACTORS[index]
            dealer_streak = _STREAKS[streak_index]
            scheme = _SCHEMES[scheme_index]
            opponents, wall = _filler(hand, wall_depth)
            filled = iter(opponents)
            threat_seats = {
                (acting_seat + offset) % 4 for offset in range(1, threats + 1)
            }
            players = tuple(
                ReferencePlayer(hand) if seat == acting_seat
                else ReferencePlayer(
                    next(filled),
                    declared_at=0 if seat in threat_seats else None,
                )
                for seat in range(4)
            )
            state = ReferenceState(
                players,
                wall,
                acting_seat=acting_seat,
                next_seat=(acting_seat + 1) % 4,
                dealer_streak=dealer_streak,
                scheme=scheme,
            )
            threat_level = (
                "none" if threats == 0
                else "one" if threats == 1
                else "multiple"
            )
            strata = ReferenceStrata(
                "dealer" if acting_seat == 0 else "nondealer",
                dealer_streak,
                "3-1" if scheme is SCHEME_3_1 else "5-2",
                _DEPTH_NAMES[wall_depth],
                hand_state,
                threat_level,
                "empirical",
            )
            cases.append(ReferenceCase(
                f"{name}-{_DEPTH_NAMES[wall_depth]}-threat-{threat_level}",
                state,
                7100 + index,
                strata,
            ))
    return tuple(cases)
