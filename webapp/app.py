"""Mobile-first Streamlit teaching UI for the Taiwanese mahjong engine."""

from __future__ import annotations

import random
import sys
from pathlib import Path

# `streamlit run webapp/app.py` puts webapp/ (not the repo root) on sys.path.
_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import streamlit as st

from taimahjong.calibration import Calibration
from taimahjong.danger import OpponentView, RiverEntry, fold_score, format_river, parse_river, tenpai_score
from taimahjong.ev import EVRankEntry, ev_rank, remaining_draws
from taimahjong.quiz import QuizGrade, QuizPosition, explain, generate_position, grade
from taimahjong.scoring import BASE_UNITS, WinContext, score_hand
from taimahjong.tiles import SUIT_OFFSETS, format_tiles, parse_tiles
from taimahjong.trainer import (
    TrainerCallDecision,
    TrainerDecision,
    TrainerKongDecision,
    TrainerOutcome,
    evaluate_call,
    evaluate_kong,
    play_trainer,
)


st.set_page_config(page_title="台灣麻將教室", page_icon="🀄", layout="centered")


@st.cache_resource
def load_calibration() -> Calibration | None:
    """Load the bot calibration once per Streamlit process."""
    path = Path(__file__).resolve().parents[1] / "data" / "calibration.json"
    return Calibration.from_path(path) if path.exists() else None


_NUMERALS = "一二三四五六七八九"
_HONOR_FACES = ("東", "南", "西", "北", "白", "發", "中")
_WIND_COLOR = "#23407a"
_SUIT_COLORS = {"m": ("#c02c2c", "#2a4fa2"), "p": ("#2a4fa2", "#2a4fa2"), "s": ("#2e7d32", "#2e7d32")}
_HONOR_COLORS = (_WIND_COLOR, _WIND_COLOR, _WIND_COLOR, _WIND_COLOR, "#b5b0a0", "#2e7d32", "#c02c2c")

TILE_CSS = """
<style>
.mj-strip {display:flex;flex-wrap:nowrap;overflow-x:auto;gap:4px;padding:6px 2px;align-items:flex-end;}
.mj-strip.mj-wrap {flex-wrap:wrap;}
.mj-tile {display:inline-flex;flex-direction:column;align-items:center;justify-content:center;
  flex:0 0 auto;background:#fbfaf2;border:1px solid #cfcabc;border-radius:6px;
  box-shadow:0 3px 0 #b5b0a0;font-weight:800;line-height:1.05;user-select:none;
  font-family:"Noto Serif TC","PMingLiU",serif;}
.mj-lg {width:46px;height:62px;font-size:21px;}
.mj-sm {width:28px;height:40px;font-size:12px;}
.mj-gap {width:14px;flex:0 0 auto;}
.mj-draw {outline:3px solid #e0a300;outline-offset:1px;}
.mj-cut {opacity:.5;outline:2px solid #c02c2c;position:relative;}
.mj-tsumogiri {border-top:4px solid #c02c2c;}
.mj-tedashi {border-top:4px solid #2a4fa2;}
div[class*="st-key-quiz_discard_"] button {background:#fbfaf2;border:1px solid #cfcabc;border-radius:6px;
  box-shadow:0 3px 0 #b5b0a0;width:100%;min-height:66px;padding:4px 0;}
div[class*="st-key-quiz_discard_"] button:hover {border-color:#e0a300;}
div[class*="st-key-quiz_discard_"] button p {writing-mode:vertical-rl;text-orientation:upright;
  font-weight:800;font-size:19px;letter-spacing:1px;margin:0 auto;
  font-family:"Noto Serif TC","PMingLiU",serif;}
/* keep discard buttons on one horizontal row even on phones: Streamlit stacks
   columns below its mobile breakpoint, which turns the hand into a vertical list */
div.st-key-quiz_hand_row div[data-testid="stHorizontalBlock"] {flex-wrap:nowrap !important;
  overflow-x:auto;gap:0.25rem !important;}
div.st-key-quiz_hand_row div[data-testid="stColumn"] {width:auto !important;
  min-width:34px !important;flex:1 1 0 !important;}
/* Mahjong-Soul-style table: the four discard rivers converge into a centre
   cross, each rotated to face the middle; hand sits at the near edge. */
.mj-felt{display:grid;place-items:center;width:100%;max-width:440px;margin:0 auto;
  aspect-ratio:1/1;padding:6px;
  grid-template-columns:1fr 1.25fr 1fr;grid-template-rows:1fr 1.25fr 1fr;
  grid-template-areas:"c top c2" "left center right" "c3 bottom c4";
  background:radial-gradient(ellipse at center,#4a2b52 0%,#3a2140 68%,#291630 100%);
  border:10px solid #45203a;border-radius:16px;box-shadow:inset 0 0 30px rgba(0,0,0,.45);}
.mj-river{display:grid;grid-template-columns:repeat(6,auto);gap:2px;justify-content:center;}
.mj-block{display:flex;flex-direction:column;align-items:center;gap:3px;min-width:0;}
.mj-z-top{grid-area:top;transform:rotate(180deg);}
.mj-z-left{grid-area:left;transform:rotate(90deg);}
.mj-z-right{grid-area:right;transform:rotate(-90deg);}
.mj-z-bottom{grid-area:bottom;}
.mj-z-center{grid-area:center;}
.mj-mmelds .mj-strip{gap:1px;padding:0;}
.mj-center-box{background:rgba(15,8,20,.82);color:#f2eaf7;border-radius:12px;
  padding:7px 13px;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,.45);}
.mj-turn{color:#f2eaf7;font-size:12px;font-weight:700;}
.mj-zsub{color:#d9c2e6;font-size:10px;margin:2px 0 1px;}
.mj-seatbar{display:flex;flex-wrap:wrap;gap:6px;justify-content:center;
  font-size:11px;color:#555;margin-bottom:2px;}
.mj-seatbar b{color:#333;}
/* hand row = near edge of the table, matching felt */
div.st-key-quiz_hand_row div[data-testid="stHorizontalBlock"],
div.st-key-trainer_hand_row div[data-testid="stHorizontalBlock"]{
  background:linear-gradient(#3a2140,#291630);border:10px solid #45203a;
  border-radius:16px;margin-top:6px;padding:9px 6px !important;}
.mj-score{display:flex;flex-wrap:wrap;gap:10px;justify-content:center;
  background:#f3eef7;border-radius:10px;padding:8px 10px;margin:4px 0;font-size:13px;}
.mj-score b{font-size:16px;color:#5a2f7a;}
</style>
"""


def _face(tile: int) -> tuple[str, str, str, str]:
    """Return (top char, bottom char, top color, bottom color); honors have one char."""
    if tile < 27:
        suit = "mps"[tile // 9]
        top, bottom = _SUIT_COLORS[suit]
        return _NUMERALS[tile % 9], "萬筒條"[tile // 9], top, bottom
    face = _HONOR_FACES[tile - 27]
    color = _HONOR_COLORS[tile - 27]
    return face, "", color, color


def face_text(tile: int) -> str:
    top, bottom, _, _ = _face(tile)
    return top + bottom


def tile_div(tile: int, size: str = "mj-lg", extra: str = "") -> str:
    top, bottom, top_color, bottom_color = _face(tile)
    if tile == 31:  # white dragon: a blank face, like the real tile
        body = ""
    elif bottom:
        body = f'<span style="color:{top_color}">{top}</span><span style="color:{bottom_color}">{bottom}</span>'
    else:
        body = f'<span style="color:{top_color}">{top}</span>'
    return f'<div class="mj-tile {size} {extra}" title="{face_text(tile)}">{body}</div>'


def strip_html(parts: list[str], wrap: bool = False) -> str:
    inner = "".join(parts) if parts else '<span style="color:#999">-</span>'
    wrap_cls = " mj-wrap" if wrap else ""
    return f'<div class="mj-strip{wrap_cls}">{inner}</div>'


def hand_strip(hand: tuple[int, ...] | list[int], drawn: int | None = None) -> str:
    counts = list(hand)
    parts: list[str] = []
    if drawn is not None and counts[drawn] > 0:
        counts[drawn] -= 1
    for tile, count in enumerate(counts):
        parts.extend(tile_div(tile) for _ in range(count))
    if drawn is not None:
        parts.append('<div class="mj-gap"></div>')
        parts.append(tile_div(drawn, extra="mj-draw"))
    return strip_html(parts, wrap=True)


def counts_strip(counts: tuple[int, ...] | list[int], size: str = "mj-sm") -> str:
    parts = [tile_div(tile, size) for tile, count in enumerate(counts) for _ in range(count)]
    return strip_html(parts, wrap=True)


def hand_view(hand: tuple[int, ...] | list[int], drawn: int | None = None, chosen: int | None = None) -> str:
    """Full hand in sorted order; the drawn tile is gold-framed and the chosen
    discard is marked, so it stays visible while EV computes and in feedback."""
    parts: list[str] = []
    drawn_used = chosen_used = False
    for tile, count in enumerate(hand):
        for _ in range(count):
            classes: list[str] = []
            if tile == drawn and not drawn_used:
                classes.append("mj-draw")
                drawn_used = True
            if chosen is not None and tile == chosen and not chosen_used:
                classes.append("mj-cut")
                chosen_used = True
            parts.append(tile_div(tile, "mj-lg", " ".join(classes)))
    return strip_html(parts, wrap=True)


def river_strip(river: tuple[RiverEntry, ...] | list[RiverEntry]) -> str:
    marker = {"tsumogiri": "mj-tsumogiri", "tedashi": "mj-tedashi", "unknown": ""}
    parts = [tile_div(entry.tile, "mj-sm", marker[entry.origin]) for entry in river]
    return strip_html(parts, wrap=True)


def meld_strip(melds: tuple[tuple[int, int, int], ...] | list[tuple[int, int, int]]) -> str:
    parts: list[str] = []
    for index, meld in enumerate(melds):
        if index:
            parts.append('<div class="mj-gap"></div>')
        parts.extend(tile_div(tile, "mj-sm") for tile in meld)
    return strip_html(parts, wrap=True)


def meld_text(melds: tuple[tuple[int, int, int], ...] | list[tuple[int, int, int]]) -> str:
    rendered: list[str] = []
    for meld in melds:
        counts = [0] * 34
        for tile in meld:
            counts[tile] += 1
        rendered.append(format_tiles(counts))
    return ";".join(rendered) or "-"


def tile_from_compact(text: str) -> int:
    counts = parse_tiles(text)
    found = [tile for tile, count in enumerate(counts) if count]
    if len(found) != 1 or counts[found[0]] != 1:
        raise ValueError("請輸入剛好一張牌，例如 3m")
    return found[0]


def parse_melds(text: str) -> list[tuple[int, int, int]]:
    if not text.strip():
        return []
    melds: list[tuple[int, int, int]] = []
    for item in text.split(";"):
        counts = parse_tiles(item.strip())
        tiles = tuple(tile for tile, count in enumerate(counts) for _ in range(count))
        if len(tiles) != 3:
            raise ValueError("每組副露必須剛好三張牌，例如 123s;777s")
        melds.append(tiles)
    return melds


def add_visible(*groups: tuple[int, ...] | list[int]) -> tuple[int, ...]:
    counts = [0] * 34
    for group in groups:
        for tile, count in enumerate(group):
            counts[tile] += count
    return tuple(counts)


def public_counts(opponent: OpponentView) -> tuple[int, ...]:
    counts = [0] * 34
    for entry in opponent.river:
        counts[entry.tile if isinstance(entry, RiverEntry) else entry] += 1
    for meld in opponent.melds:
        for tile in meld:
            counts[tile] += 1
    return tuple(counts)


def ev_rows(entries: tuple[EVRankEntry, ...] | list[EVRankEntry]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for entry in entries:
        rows.append({
            "切牌": entry.label if entry.is_fold else f"{face_text(entry.discard)} {format_tiles(tuple(1 if tile == entry.discard else 0 for tile in range(34)))}",
            "淨 EV": round(entry.net_ev, 1),
            "P(自摸和)": round(entry.p_win, 3),
            "存活後 P(和)": round(entry.survival_adjusted_p_win, 3),
            "P(流局)": round(entry.p_draw, 3),
            "E[和牌值]": "-" if entry.mean_win_value is None else round(entry.mean_win_value, 1),
            "E[放銃]": round(entry.risk_ev, 1),
        })
    return rows


def river_grid(river: tuple[RiverEntry, ...] | list[RiverEntry]) -> str:
    """Discards laid out 6-per-row like a real river (not a single flex line)."""
    marker = {"tsumogiri": "mj-tsumogiri", "tedashi": "mj-tedashi", "unknown": ""}
    tiles = "".join(tile_div(entry.tile, "mj-sm", marker[entry.origin]) for entry in river)
    return f'<div class="mj-river">{tiles}</div>' if tiles else '<div class="mj-river"></div>'


def _river_block(css_class: str, river, melds) -> str:
    parts = ['<div class="mj-block ' + css_class + '">']
    if melds:
        parts.append(f'<div class="mj-mmelds">{meld_strip(melds)}</div>')
    parts.append(river_grid(river))
    parts.append("</div>")
    return "".join(parts)


def render_position(position: QuizPosition, offered_tile: int | None = None) -> None:
    """Render the position as a Mahjong-Soul-style table: the four discard
    rivers meet in a centre cross, each rotated toward the middle; the clickable
    hand is rendered separately as the table's near edge. ``offered_tile`` marks
    a tile an opponent just discarded that the human may call."""
    opps = list(position.opponents)
    right = opps[0] if len(opps) > 0 else None
    top = opps[1] if len(opps) > 1 else None
    left = opps[2] if len(opps) > 2 else None

    seatbar = " ｜ ".join(
        f'<b>對手 {opp.seat}</b>{" 宣告" if opp.declared else ""} 聽{opp.tenpai_estimate:.2f}/棄{opp.fold_estimate:.2f}'
        for opp in opps
    )
    st.markdown(f'<div class="mj-seatbar">{seatbar}</div>', unsafe_allow_html=True)
    role = "你是莊家（莊 +1 台）" if position.is_dealer else f"你在座位 {position.seat}"
    st.caption(f"牌牆剩 {position.wall_remaining} 張（約可再摸 {position.draws_remaining} 巡）　·　{role}")

    if offered_tile is not None:
        center_inner = f'<div class="mj-zsub">可鳴</div>{tile_div(offered_tile, "mj-sm", "mj-draw")}'
    elif position.drawn_tile is not None:
        center_inner = f'<div class="mj-zsub">摸入</div>{tile_div(position.drawn_tile, "mj-sm", "mj-draw")}'
    else:
        center_inner = '<div class="mj-zsub">剛鳴牌</div>'
    center = (
        '<div class="mj-z-center"><div class="mj-center-box">'
        f'<div class="mj-turn">第 {position.turn} 巡</div>{center_inner}</div></div>'
    )
    felt = (
        '<div class="mj-felt">'
        + _river_block("mj-z-top", top.river if top else [], top.melds if top else [])
        + _river_block("mj-z-left", left.river if left else [], left.melds if left else [])
        + center
        + _river_block("mj-z-right", right.river if right else [], right.melds if right else [])
        + _river_block("mj-z-bottom", position.own_river, position.own_melds)
        + "</div>"
    )
    st.markdown(felt, unsafe_allow_html=True)
    with st.expander("文字記法（可複製到 CLI）", expanded=False):
        st.caption(f"手牌 `{format_tiles(position.hand)}`")
        st.caption(f"我的河 `{format_river(list(position.own_river)) or '-'}` · 副露 `{meld_text(position.own_melds)}`")
        for opp in opps:
            st.caption(f"對手 {opp.seat} 河 `{format_river(list(opp.river)) or '-'}` · 副露 `{meld_text(opp.melds)}`")


def _queue_next_quiz() -> None:
    """Advance the seed from a button callback: session_state keys backing an
    instantiated widget may only be written before widgets render, and
    on_click callbacks run at the start of the rerun."""
    next_seed = int(st.session_state.quiz_position.seed) + 1
    st.session_state.quiz_seed = next_seed
    st.session_state.quiz_pending_generate = True
    st.session_state.quiz_grade = None


def show_quiz() -> None:
    st.subheader("練習")
    if "quiz_seed" not in st.session_state:
        st.session_state.quiz_seed = random.SystemRandom().randrange(1, 1_000_000)
    seed = int(st.number_input("種子", min_value=0, step=1, key="quiz_seed"))
    generate_clicked = st.button("出題", type="primary", key="quiz_generate")
    if st.session_state.pop("quiz_pending_generate", False) or generate_clicked:
        try:
            st.session_state.quiz_position = generate_position(seed)
            st.session_state.quiz_grade = None
        except ValueError as error:
            st.error(f"無法出題：{error}")

    position = st.session_state.get("quiz_position")
    if position is None:
        st.info("輸入種子後按「出題」，或直接使用隨機種子。")
        return

    render_position(position)
    st.caption("我的手牌 — 點一張切出（金框為剛摸入的牌）")
    unique_tiles = [tile for tile, count in enumerate(position.hand) if count]
    color_rules = "".join(
        f'.st-key-quiz_discard_{tile} button p {{color:{_face(tile)[2]};}}' for tile in unique_tiles
    )
    color_rules += f'.st-key-quiz_discard_{position.drawn_tile} button {{outline:3px solid #e0a300;outline-offset:1px;}}'
    st.markdown(f"<style>{color_rules}</style>", unsafe_allow_html=True)
    with st.container(key="quiz_hand_row"):
        columns = st.columns(len(unique_tiles), gap="small")
        for column, tile in zip(columns, unique_tiles):
            label = face_text(tile) if position.hand[tile] == 1 else f"{face_text(tile)}×{position.hand[tile]}"
            with column:
                if st.button(label, key=f"quiz_discard_{tile}"):
                    st.session_state.quiz_grade = grade(position, tile)

    controls = st.columns(2)
    with controls[0]:
        st.button("下一題", key="quiz_next", on_click=_queue_next_quiz)
    with controls[1]:
        if st.button("重出這題", key="quiz_repeat"):
            st.session_state.quiz_position = generate_position(position.seed)
            st.session_state.quiz_grade = None
            st.rerun()

    result: QuizGrade | None = st.session_state.get("quiz_grade")
    if result is None:
        return
    message = _verdict_message(result.verdict, result.marginal, result.ev_delta)
    _show_verdict(result.verdict, message)
    st.dataframe(ev_rows(result.ranked), use_container_width=True, hide_index=True)
    st.markdown("**說明**")
    st.text(explain(result))


def _trainer_scorecard() -> None:
    score = st.session_state.get("trainer_score", {"decisions": 0, "best": 0, "loss": 0.0})
    decisions = score["decisions"]
    accuracy = f"{100 * score['best'] / decisions:.0f}%" if decisions else "—"
    avg = f"{score['loss'] / decisions:.2f}" if decisions else "—"
    st.markdown(
        '<div class="mj-score">'
        f'<span>手數 <b>{decisions}</b></span>'
        f'<span>最佳率 <b>{accuracy}</b></span>'
        f'<span>總 EV 損失 <b>{score["loss"]:.2f}</b> 台</span>'
        f'<span>每手均損 <b>{avg}</b></span>'
        '</div>',
        unsafe_allow_html=True,
    )


def _trainer_start(seed: int, human_seat: int = 0, dealer_streak: int = 0) -> None:
    generator = play_trainer(seed, human_seat=human_seat, dealer_streak=dealer_streak)
    st.session_state.trainer_gen = generator
    st.session_state.trainer_item = next(generator)
    st.session_state.trainer_seed = seed
    st.session_state.trainer_seat = human_seat
    st.session_state.trainer_streak = dealer_streak
    st.session_state.trainer_score = {"decisions": 0, "best": 0, "loss": 0.0}
    st.session_state.trainer_feedback = None
    st.session_state.trainer_pending_tile = None
    st.session_state.trainer_call_feedback = None
    st.session_state.pop("trainer_call_pending", None)
    st.session_state.trainer_kong_feedback = None
    st.session_state.pop("trainer_kong_pending", None)


# The human's seat choice, labelled by where the fixed seat-0 dealer sits
# relative to them (turn order 0->1->2->3, so seat 0 is seat 1's upstream).
_SEAT_LABELS = {0: "莊家（你自己做莊）", 1: "莊的下家", 2: "莊的對家", 3: "莊的上家"}
# Where the dealer sits, from the human's chair.
_DEALER_RELATION = {1: "上家", 2: "對家", 3: "下家"}


def _seat_relation_note(human_seat: int, streak: int) -> str:
    streak_note = f"，莊家連 {streak} 拉 {streak}（放槍給莊代價更高）" if streak else ""
    if human_seat == 0:
        return f"你這局做莊{streak_note}"
    return f"莊家在你的{_DEALER_RELATION[human_seat]}{streak_note}"


def _trainer_advance() -> None:
    """Send the graded tile into the generator and move to the next decision."""
    tile = st.session_state.trainer_pending_tile
    st.session_state.trainer_item = st.session_state.trainer_gen.send(tile)
    st.session_state.trainer_feedback = None
    st.session_state.trainer_pending_tile = None


def _trainer_call_advance() -> None:
    """Send the chosen call (option index) or a pass (None) into the generator."""
    pending = st.session_state.trainer_call_pending
    choice = None if pending == "pass" else int(pending)
    st.session_state.trainer_item = st.session_state.trainer_gen.send(choice)
    st.session_state.trainer_call_feedback = None
    st.session_state.pop("trainer_call_pending", None)


def _trainer_kong_advance() -> None:
    """Send the chosen kong (option index) or skip (None) into the generator."""
    pending = st.session_state.trainer_kong_pending
    choice = None if pending == "skip" else int(pending)
    st.session_state.trainer_item = st.session_state.trainer_gen.send(choice)
    st.session_state.trainer_kong_feedback = None
    st.session_state.pop("trainer_kong_pending", None)


def _call_label(option) -> str:
    return ("碰 " if option.kind == "pon" else "吃 ") + "".join(face_text(tile) for tile in option.meld)


def _kong_label(option) -> str:
    return ("暗槓 " if option.kind == "concealed" else "加槓 ") + face_text(option.tile)


def _verdict_label(verdict: str, marginal: bool) -> str:
    """A verdict that still hugs a boundary is flagged '（邊緣）': even the
    escalated budget cannot make it certain, so the UI must not read as crisp."""
    return f"{verdict}（邊緣）" if marginal else verdict


def _verdict_message(verdict: str, marginal: bool, ev_delta: float) -> str:
    """Shared verdict suffix for quiz, discard, and call feedback."""
    return f"判定：{_verdict_label(verdict, marginal)} · EV 差 {ev_delta:.1f} 台"


def _show_verdict(verdict: str, message: str) -> None:
    """Render a graded message with the Streamlit tone matching the verdict."""
    {"best": st.success, "good": st.info, "inaccuracy": st.warning, "mistake": st.error}[verdict](message)


def show_trainer_call(item: TrainerCallDecision) -> None:
    """Call decision: same GTO-Wizard flow as discards — choose, see EV, advance."""
    position = item.position
    render_position(position, offered_tile=item.offered_tile)
    pending = st.session_state.get("trainer_call_pending")
    feedback = st.session_state.get("trainer_call_feedback")

    # State 1 — awaiting: show the hand and the call/pass buttons.
    if pending is None and feedback is None:
        st.markdown(hand_view(position.hand), unsafe_allow_html=True)
        st.caption(f"對手 {item.discarder} 打出 {face_text(item.offered_tile)} — 要鳴牌嗎？")
        columns = st.columns(len(item.options) + 1, gap="small")
        for index, option in enumerate(item.options):
            with columns[index]:
                if st.button(_call_label(option), key=f"trainer_call_{index}"):
                    st.session_state.trainer_call_pending = index
                    st.rerun()
        with columns[-1]:
            if st.button("過（不鳴）", key="trainer_call_pass"):
                st.session_state.trainer_call_pending = "pass"
                st.rerun()
        return

    # State 2 — computing: keep the hand visible while EV is evaluated.
    if feedback is None:
        st.markdown(hand_view(position.hand), unsafe_allow_html=True)
        st.caption("計算 EV 中…")
        with st.spinner("計算 EV…"):
            evaluation = evaluate_call(item)
        choice = None if pending == "pass" else int(pending)
        result = evaluation.verdict_for(choice)
        score = st.session_state.trainer_score
        score["decisions"] += 1
        score["best"] += int(result.verdict == "best")
        score["loss"] += result.ev_loss
        st.session_state.trainer_call_feedback = (evaluation, choice, result)
        st.rerun()
        return

    # State 3 — feedback: verdict, best action, per-option EV table.
    st.markdown(hand_view(position.hand), unsafe_allow_html=True)
    evaluation, choice, result = feedback
    verdict, delta = result.verdict, result.ev_delta
    chosen = "過（不鳴）" if choice is None else _call_label(item.options[choice])
    message = f"你選擇：{chosen} · {_verdict_message(verdict, result.marginal, delta)}"
    _show_verdict(verdict, message)
    if evaluation.best_index is None:
        st.caption(f"最佳：過（不鳴），EV {result.best_ev:.1f} 台")
    else:
        best = item.options[evaluation.best_index]
        st.caption(f"最佳：{_call_label(best)}，EV {result.best_ev:.1f} 台")
    rows = [{"選項": "過（不鳴）", "EV（台）": round(evaluation.pass_ev, 1)}]
    for index, option in enumerate(item.options):
        rows.append({"選項": _call_label(option), "EV（台）": round(evaluation.option_evs[index], 1)})
    st.dataframe(rows, use_container_width=True, hide_index=True)
    st.button("繼續 ▶", type="primary", key="trainer_call_next", on_click=_trainer_call_advance)


def show_trainer_kong(item: TrainerKongDecision) -> None:
    """Kong decision: choose, receive shared-EV feedback, then advance."""
    position = item.position
    render_position(position)
    pending = st.session_state.get("trainer_kong_pending")
    feedback = st.session_state.get("trainer_kong_feedback")

    if pending is None and feedback is None:
        st.markdown(hand_view(position.hand, position.drawn_tile), unsafe_allow_html=True)
        st.caption("剛摸入的牌可形成不惡化向聽數的槓 — 要宣告嗎？")
        columns = st.columns(len(item.options) + 1, gap="small")
        for index, option in enumerate(item.options):
            with columns[index]:
                if st.button(_kong_label(option), key=f"trainer_kong_{index}"):
                    st.session_state.trainer_kong_pending = index
                    st.rerun()
        with columns[-1]:
            if st.button("不槓", key="trainer_kong_skip"):
                st.session_state.trainer_kong_pending = "skip"
                st.rerun()
        return

    if feedback is None:
        st.markdown(hand_view(position.hand, position.drawn_tile), unsafe_allow_html=True)
        st.caption("計算槓的 EV 中…")
        with st.spinner("計算 EV…"):
            evaluation = evaluate_kong(item)
        choice = None if pending == "skip" else int(pending)
        result = evaluation.verdict_for(choice)
        score = st.session_state.trainer_score
        score["decisions"] += 1
        score["best"] += int(result.verdict == "best")
        score["loss"] += result.ev_loss
        st.session_state.trainer_kong_feedback = (evaluation, choice, result)
        st.rerun()
        return

    st.markdown(hand_view(position.hand, position.drawn_tile), unsafe_allow_html=True)
    evaluation, choice, result = feedback
    chosen = "不槓" if choice is None else _kong_label(item.options[choice])
    _show_verdict(result.verdict, f"你選擇：{chosen} · {_verdict_message(result.verdict, result.marginal, result.ev_delta)}")
    if evaluation.best_index is None:
        st.caption(f"最佳：不槓，EV {result.best_ev:.1f} 台")
    else:
        st.caption(f"最佳：{_kong_label(item.options[evaluation.best_index])}，EV {result.best_ev:.1f} 台")
    rows = [{"選項": "不槓", "EV（台）": round(evaluation.pass_ev, 1)}]
    for index, option in enumerate(item.options):
        rows.append({"選項": _kong_label(option), "EV（台）": round(evaluation.option_evs[index], 1)})
    st.dataframe(rows, use_container_width=True, hide_index=True)
    st.button("繼續 ▶", type="primary", key="trainer_kong_next", on_click=_trainer_kong_advance)


def show_trainer() -> None:
    st.subheader("實戰")
    st.caption("一局打到底，每一手切牌都即時給你 EV 回饋與計分（GTO Wizard 式）。")
    item = st.session_state.get("trainer_item")

    if item is None:
        if "trainer_new_seed" not in st.session_state:
            st.session_state.trainer_new_seed = random.SystemRandom().randrange(1, 1_000_000)
        seed = int(st.number_input("種子", min_value=0, step=1, key="trainer_new_seed"))
        columns = st.columns(2)
        with columns[0]:
            human_seat = st.selectbox(
                "你的座位", options=[0, 1, 2, 3], format_func=lambda seat: _SEAT_LABELS[seat], key="trainer_new_seat",
            )
        with columns[1]:
            streak = int(st.number_input("初始連莊數", min_value=0, max_value=8, step=1, key="trainer_new_streak"))
        st.caption(_seat_relation_note(int(human_seat), streak))
        if st.button("開始新局", type="primary", key="trainer_start"):
            with st.spinner("發牌中…"):
                _trainer_start(seed, int(human_seat), streak)
            st.rerun()
        st.info("每手切牌，以及可吃碰或可宣告不惡化向聽數的暗槓／加槓時，都會即時給 EV 回饋。")
        return

    if isinstance(item, TrainerOutcome):
        _trainer_scorecard()
        tone = st.success if item.human_won else (st.error if item.human_dealt_in else st.info)
        streak_in = f"（連莊 {item.dealer_streak_in}）" if item.dealer_streak_in else ""
        tone(f"本局結束{streak_in}：{item.headline}　你的收支 {item.point_delta:+d} 台單位（{item.turns} 手）")
        if item.next_human_seat != st.session_state.get("trainer_seat", 0):
            st.warning(f"莊家易主，換座位 — 下局你是{_SEAT_LABELS[item.next_human_seat]}")
        elif item.next_dealer_streak:
            st.info(f"莊家連莊 — 下局連 {item.next_dealer_streak} 拉 {item.next_dealer_streak}，對莊防守要更緊")
        controls = st.columns(2)
        with controls[0]:
            if st.button("再來一局", type="primary", key="trainer_again"):
                with st.spinner("發牌中…"):
                    _trainer_start(int(st.session_state.trainer_seed) + 1, item.next_human_seat, item.next_dealer_streak)
                st.rerun()
        with controls[1]:
            if st.button("結束", key="trainer_quit"):
                for key in ("trainer_gen", "trainer_item", "trainer_feedback", "trainer_pending_tile"):
                    st.session_state.pop(key, None)
                st.rerun()
        return

    _trainer_scorecard()

    if isinstance(item, TrainerKongDecision):
        show_trainer_kong(item)
        return

    if isinstance(item, TrainerCallDecision):
        show_trainer_call(item)
        return

    position = item.position
    render_position(position)
    feedback: QuizGrade | None = st.session_state.get("trainer_feedback")
    pending: int | None = st.session_state.get("trainer_pending_tile")

    # State 1 — awaiting a discard: show the clickable hand.
    if feedback is None and pending is None:
        st.caption("我的手牌 — 點一張切出（金框為剛摸入的牌）")
        unique_tiles = [tile for tile, count in enumerate(position.hand) if count]
        color_rules = "".join(
            f'.st-key-trainer_discard_{tile} button p {{color:{_face(tile)[2]};}}' for tile in unique_tiles
        )
        color_rules += f'.st-key-trainer_discard_{position.drawn_tile} button {{outline:3px solid #e0a300;outline-offset:1px;}}'
        st.markdown(f"<style>{color_rules}</style>", unsafe_allow_html=True)
        with st.container(key="trainer_hand_row"):
            columns = st.columns(len(unique_tiles), gap="small")
            for column, tile in zip(columns, unique_tiles):
                label = face_text(tile) if position.hand[tile] == 1 else f"{face_text(tile)}×{position.hand[tile]}"
                with column:
                    if st.button(label, key=f"trainer_discard_{tile}"):
                        st.session_state.trainer_pending_tile = tile
                        st.rerun()
        return

    # State 2 — computing: the hand (with the cut tile marked) stays on screen
    # while EV is evaluated, so the position is never hidden behind a spinner.
    if feedback is None and pending is not None:
        st.caption(f"你切 {face_text(pending)}，計算 EV 中…（紅框為切出、金框為摸入）")
        st.markdown(hand_view(position.hand, position.drawn_tile, pending), unsafe_allow_html=True)
        with st.spinner("計算 EV…"):
            result = grade(position, pending)
        score = st.session_state.trainer_score
        score["decisions"] += 1
        score["best"] += int(result.verdict == "best")
        score["loss"] += result.ev_loss
        st.session_state.trainer_feedback = result
        st.rerun()
        return

    # State 3 — feedback: keep the hand visible alongside the verdict and table.
    assert feedback is not None
    st.markdown(hand_view(position.hand, position.drawn_tile, feedback.chosen.discard), unsafe_allow_html=True)
    message = f"你切 {face_text(feedback.chosen.discard)} · {_verdict_message(feedback.verdict, feedback.marginal, feedback.ev_delta)}"
    _show_verdict(feedback.verdict, message)
    # Only point to a different "best" tile when it actually beats the player's
    # pick; a noisy near-tie can leave ev_delta<=0 (verdict best) with the tiles
    # differing, and naming a lower-EV tile "best" there would contradict itself.
    if feedback.ev_delta > 0 and feedback.best.discard != feedback.chosen.discard:
        st.caption(f"最佳切牌為 {face_text(feedback.best.discard)}（淨 EV {feedback.best.net_ev:.1f}）")
    st.dataframe(ev_rows(feedback.ranked), use_container_width=True, hide_index=True)
    st.button("下一手 ▶", type="primary", key="trainer_next", on_click=_trainer_advance)


def show_ev() -> None:
    st.subheader("切牌分析")
    hand = st.text_input("手牌（17 張）", value="123m123p123s11122233z", key="ev_hand")
    try:
        st.markdown(counts_strip(parse_tiles(hand), "mj-lg"), unsafe_allow_html=True)
    except ValueError:
        pass
    river = st.text_input("對手河（可用 * / .）", value="", key="ev_river")
    if river.strip():
        try:
            st.markdown(river_strip(parse_river(river)), unsafe_allow_html=True)
        except ValueError:
            pass
    melds = st.text_input("對手副露（以 ; 分隔）", value="", key="ev_melds")
    declared = st.text_input("宣告位置（0 或 1，可留白）", value="", key="ev_declared")
    visible = st.text_input("其他可見牌", value="", key="ev_visible")
    with st.expander("進階設定", expanded=False):
        turns = int(st.number_input("摸牌回合（0 = 自動）", min_value=0, value=0, step=1, key="ev_turns"))
        sims = int(st.number_input("模擬次數", min_value=1, value=400, step=20, key="ev_sims"))
        seed = int(st.number_input("模擬種子", min_value=0, value=7, step=1, key="ev_seed"))
    if st.button("分析 EV", type="primary", key="ev_run"):
        try:
            counts = parse_tiles(hand)
            opponent: OpponentView | None = None
            if river or melds or declared:
                if not river:
                    raise ValueError("提供對手狀態時，請同時輸入對手河")
                declared_at = None if not declared.strip() else int(declared)
                opponent = OpponentView(parse_river(river), parse_melds(melds), declared_at)
                opponent.validate()
            other_visible = (0,) * 34 if not visible.strip() else parse_tiles(visible)
            combined_visible = add_visible(other_visible, public_counts(opponent)) if opponent else other_visible
            effective_turns = turns or remaining_draws(counts, combined_visible)
            result = ev_rank(
                counts, [] if opponent is None else [opponent], combined_visible,
                turns=effective_turns, sims=sims, seed=seed, calibration=load_calibration(),
            )
            st.session_state.ev_result = (result, opponent, effective_turns)
        except ValueError as error:
            st.session_state.pop("ev_result", None)
            st.error(f"輸入有誤：{error}")

    saved = st.session_state.get("ev_result")
    if saved is None:
        return
    entries, opponent, effective_turns = saved
    if opponent is None:
        st.caption(f"剩餘摸牌回合：{effective_turns} · 對手聽牌／棄和估計：未提供")
    else:
        estimate = tenpai_score(opponent, len(opponent.river)).score
        fold = fold_score(opponent, [])
        st.caption(f"剩餘摸牌回合：{effective_turns} · 對手聽牌估計：{estimate:.2f} · 棄和估計：{fold:.2f}")
    st.dataframe(ev_rows(entries), use_container_width=True, hide_index=True)


def show_score() -> None:
    st.subheader("算台")
    hand = st.text_input("和牌手牌", value="123m111555666777z22z", key="score_hand")
    try:
        st.markdown(counts_strip(parse_tiles(hand), "mj-lg"), unsafe_allow_html=True)
    except ValueError:
        pass
    win_tile = st.text_input("和牌", value="2z", key="score_win_tile")
    self_draw = st.toggle("自摸", key="score_self_draw")
    dealer = st.toggle("莊家", key="score_dealer")
    streak = int(st.number_input("連莊次數", min_value=0, value=0, step=1, key="score_streak"))
    migi = st.toggle("宣告聽牌（migi）", key="score_migi")
    heavenly = st.toggle("天胡", key="score_heavenly")
    earthly = st.toggle("地胡", key="score_earthly")
    round_wind = st.selectbox("圈風", options=[None, "1z", "2z", "3z", "4z"], format_func=lambda value: "無" if value is None else value, key="score_round_wind")
    seat_wind = st.selectbox("門風", options=[None, "1z", "2z", "3z", "4z"], format_func=lambda value: "無" if value is None else value, key="score_seat_wind")
    if st.button("計算台數", type="primary", key="score_run"):
        try:
            context = WinContext(
                winning_tile=tile_from_compact(win_tile), self_draw=self_draw, dealer=dealer,
                dealer_streak=streak, migi_declared=migi, heavenly=heavenly, earthly=earthly,
                round_wind=None if round_wind is None else tile_from_compact(round_wind),
                seat_wind=None if seat_wind is None else tile_from_compact(seat_wind),
            )
            st.session_state.score_result = score_hand(parse_tiles(hand), (), context)
        except ValueError as error:
            st.session_state.pop("score_result", None)
            st.error(f"輸入有誤：{error}")
    result = st.session_state.get("score_result")
    if result is not None:
        st.dataframe([{"項目": name, "台": tai} for name, tai in result.items], use_container_width=True, hide_index=True)
        st.success(f"總計：{result.total_tai} 台（底 {BASE_UNITS} + 台數 = {result.value_units} 台單位）")


def render_legend() -> None:
    st.caption("記法：`m/p/s/z` = 萬／筒／條／字；河牌 `*`／紅槓 = 摸切，`.`／藍槓 = 手切；金框 = 剛摸入的牌。")


def main() -> None:
    st.markdown(TILE_CSS, unsafe_allow_html=True)
    st.title("🀄 台灣麻將教室")
    render_legend()
    quiz_tab, trainer_tab, ev_tab, score_tab = st.tabs(["單題", "實戰", "切牌分析", "算台"])
    with quiz_tab:
        show_quiz()
    with trainer_tab:
        show_trainer()
    with ev_tab:
        show_ev()
    with score_tab:
        show_score()
    st.divider()
    st.caption(
        "機率以機器人自我對局校準，不代表真人牌局；進攻 EV 僅計自摸。"
        "EV 為蒙地卡羅估計：判定會精算最佳與所選兩手，壓在門檻上的判定會自動加碼精算；"
        "標「（邊緣）」表示該判定仍貼著門檻、受殘餘取樣誤差影響（加模擬次數可降雜訊，但不動模型偏差）。"
    )


main()
