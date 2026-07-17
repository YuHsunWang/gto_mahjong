"""Mobile-first Streamlit teaching UI for the Taiwanese mahjong engine."""

from __future__ import annotations

import random
from pathlib import Path

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


def tile_glyph(tile: int) -> str:
    """Return the Unicode Mahjong Tiles glyph for an engine tile index."""
    if tile < 9:
        return chr(0x1F007 + tile)  # characters
    if tile < 18:
        return chr(0x1F019 + tile - 9)  # circles
    if tile < 27:
        return chr(0x1F010 + tile - 18)  # bamboo
    return chr((0x1F000, 0x1F001, 0x1F002, 0x1F003, 0x1F006, 0x1F005, 0x1F004)[tile - 27])


def glyphs(counts: tuple[int, ...] | list[int]) -> str:
    return " ".join(tile_glyph(tile) for tile, count in enumerate(counts) for _ in range(count))


def meld_text(melds: tuple[tuple[int, int, int], ...] | list[tuple[int, int, int]]) -> str:
    rendered: list[str] = []
    for meld in melds:
        counts = [0] * 34
        for tile in meld:
            counts[tile] += 1
        rendered.append(format_tiles(counts))
    return ";".join(rendered) or "-"


def meld_glyphs(melds: tuple[tuple[int, int, int], ...] | list[tuple[int, int, int]]) -> str:
    return "  ".join(" ".join(tile_glyph(tile) for tile in meld) for meld in melds) or "-"


def river_glyphs(river: tuple[RiverEntry, ...] | list[RiverEntry]) -> str:
    marker = {"tsumogiri": "*", "tedashi": ".", "unknown": ""}
    return " ".join(f"{tile_glyph(entry.tile)}{marker[entry.origin]}" for entry in river) or "-"


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
            "切牌": entry.label if entry.is_fold else f"{tile_glyph(entry.discard)} {format_tiles(tuple(1 if tile == entry.discard else 0 for tile in range(34)))}",
            "淨 EV": round(entry.net_ev, 2),
            "P(自摸和)": round(entry.p_win, 3),
            "存活後 P(和)": round(entry.survival_adjusted_p_win, 3),
            "P(流局)": round(entry.p_draw, 3),
            "E[和牌值]": "-" if entry.mean_win_value is None else round(entry.mean_win_value, 2),
            "E[放銃]": round(entry.risk_ev, 2),
        })
    return rows


def render_position(position: QuizPosition) -> None:
    st.caption(f"種子 {position.seed} · 座位 {position.seat} · 第 {position.turn} 巡 · 摸入 {tile_glyph(position.drawn_tile)} {format_tiles(tuple(1 if tile == position.drawn_tile else 0 for tile in range(34)))}")
    st.markdown(f"**手牌**  \\n+{glyphs(position.hand)}  \\n+`{format_tiles(position.hand)}`")
    st.markdown(f"**自己的河**  \\n+{river_glyphs(position.own_river)}  \\n+`{format_river(list(position.own_river)) or '-'}'")
    st.markdown(f"**自己的副露**  \\n+{meld_glyphs(position.own_melds)}  \\n+`{meld_text(position.own_melds)}`")
    for opponent in position.opponents:
        declaration = f"立直第 {opponent.declared_at + 1} 張" if opponent.declared else "未宣告"
        st.markdown(
            f"**對手 {opponent.seat}**（{declaration}；聽牌估計 {opponent.tenpai_estimate:.2f}；棄和估計 {opponent.fold_estimate:.2f}）  \\n+{river_glyphs(opponent.river)}  \\n+`{format_river(list(opponent.river)) or '-'}` · 副露 {meld_glyphs(opponent.melds)} `{meld_text(opponent.melds)}`"
        )


def show_quiz() -> None:
    st.subheader("練習")
    if "quiz_seed" not in st.session_state:
        st.session_state.quiz_seed = random.SystemRandom().randrange(1, 1_000_000)
    seed = int(st.number_input("種子", min_value=0, step=1, key="quiz_seed"))
    if st.button("出題", type="primary", key="quiz_generate"):
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
    st.markdown("**選一張要切的牌**")
    unique_tiles = [tile for tile, count in enumerate(position.hand) if count]
    for start in range(0, len(unique_tiles), 5):
        columns = st.columns(5)
        for column, tile in zip(columns, unique_tiles[start:start + 5]):
            with column:
                if st.button(f"{tile_glyph(tile)} {format_tiles(tuple(1 if index == tile else 0 for index in range(34)))}", key=f"quiz_discard_{tile}"):
                    st.session_state.quiz_grade = grade(position, tile)

    controls = st.columns(2)
    with controls[0]:
        if st.button("下一題", key="quiz_next"):
            st.session_state.quiz_seed = position.seed + 1
            st.session_state.quiz_position = generate_position(position.seed + 1)
            st.session_state.quiz_grade = None
            st.rerun()
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
    river = st.text_input("對手河（可用 * / .）", value="", key="ev_river")
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
    st.caption("記法：`m/p/s/z` = 萬／筒／索／字；河牌 `*` = 摸切，`.` = 手切。")


def main() -> None:
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
