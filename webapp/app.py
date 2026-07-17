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
            "淨 EV": round(entry.net_ev, 2),
            "P(自摸和)": round(entry.p_win, 3),
            "存活後 P(和)": round(entry.survival_adjusted_p_win, 3),
            "P(流局)": round(entry.p_draw, 3),
            "E[和牌值]": "-" if entry.mean_win_value is None else round(entry.mean_win_value, 2),
            "E[放銃]": round(entry.risk_ev, 2),
        })
    return rows


def render_position(position: QuizPosition) -> None:
    for opponent in position.opponents:
        declaration = f"宣告第 {opponent.declared_at + 1} 張" if opponent.declared else "未宣告"
        st.markdown(f"**對手 {opponent.seat}**（{declaration}；聽牌估計 {opponent.tenpai_estimate:.2f}；棄和估計 {opponent.fold_estimate:.2f}）")
        st.markdown(river_strip(opponent.river), unsafe_allow_html=True)
        if opponent.melds:
            st.markdown(f"副露 {meld_strip(opponent.melds)}", unsafe_allow_html=True)
        st.caption(f"`{format_river(list(opponent.river)) or '-'}` · 副露 `{meld_text(opponent.melds)}`")
    if any(entry for entry in position.own_river) or position.own_melds:
        st.markdown("**自己的河與副露**")
        st.markdown(river_strip(position.own_river), unsafe_allow_html=True)
        if position.own_melds:
            st.markdown(meld_strip(position.own_melds), unsafe_allow_html=True)
        st.caption(f"`{format_river(list(position.own_river)) or '-'}` · 副露 `{meld_text(position.own_melds)}`")
    st.markdown(f"**手牌**（種子 {position.seed} · 座位 {position.seat} · 第 {position.turn} 巡 · 右側為摸入的 {face_text(position.drawn_tile)}）")
    st.markdown(hand_strip(position.hand, position.drawn_tile), unsafe_allow_html=True)
    st.caption(f"`{format_tiles(position.hand)}`")


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
    st.markdown("**點一張牌切出**")
    unique_tiles = [tile for tile, count in enumerate(position.hand) if count]
    color_rules = "".join(
        f'.st-key-quiz_discard_{tile} button p {{color:{_face(tile)[2]};}}' for tile in unique_tiles
    )
    st.markdown(f"<style>{color_rules}</style>", unsafe_allow_html=True)
    with st.container(key="quiz_hand_row"):
        columns = st.columns(len(unique_tiles), gap="small")
        for column, tile in zip(columns, unique_tiles):
            with column:
                if st.button(face_text(tile), key=f"quiz_discard_{tile}"):
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
    message = f"判定：{result.verdict} · EV 差 {result.ev_delta:.2f} 台"
    {"best": st.success, "good": st.info, "inaccuracy": st.warning, "mistake": st.error}[result.verdict](message)
    st.dataframe(ev_rows(result.ranked), use_container_width=True, hide_index=True)
    st.markdown("**說明**")
    st.text(explain(result))


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
    quiz_tab, ev_tab, score_tab = st.tabs(["練習", "切牌分析", "算台"])
    with quiz_tab:
        show_quiz()
    with ev_tab:
        show_ev()
    with score_tab:
        show_score()
    st.divider()
    st.caption("機率以機器人自我對局校準，不代表真人牌局；進攻 EV 僅計自摸。")


main()
