# 決策文件：是否排「完整 outcome EV 模型替換」批次

- 狀態：**建議通過（分兩段執行）**
- 日期：2026-07-24
- 依據：批次 B（MJ-006）產出的 exact oracle 與對照量測
- 相關文件：`docs/ev-reference-report.md`、`docs/outcome-ev-reference.md`、`docs/codex-gpt-5.6-sol-full-review.md`（Phase 3.5）、`docs/codex-gpt-5.6-sol-action-items.md`（MJ-006）
- 相關程式：`taimahjong/reference_ev.py`、`taimahjong/ev_benchmark.py`、`taimahjong/ev.py`、`scripts/ev_reference_report.py`

---

## 1. 觸發原因

批次 B 建立了 small-wall exact oracle（`taimahjong.reference_ev`，以 `Fraction` 逐物理分支、終端機率質量恰為 1，非 MC 估計），並對照現行 production 近似 EV。對照結果顯示現行近似在完整支付下排序不可靠，需決定是否提前排真正的 EV 模型替換。

## 2. 量測結果（grounded）

指令：`python3 scripts/ev_reference_report.py --sims 24`

| 指標 | 數值 |
|---|---|
| Exact cases | 2（`3-1` 與 `5-2`）|
| Candidate comparisons | 30 |
| Mean absolute actor-EV error | **2.35 value units** |
| Top-1 agreement | **50%** |
| Non-tied ranking pairs | 13 |
| Ranking inversion rate | **100%** |

## 3. 落差的根本原因（結構性，非隨機誤差）

現行 production EV 只模型化「自己自摸」（attack-only）：

```
net EV ≈ survival-discounted P(自摸) × hand value
         + P(draw) × 0
         − Σ 當下候選 discard 的即時放槍損失
```

Oracle 則模型化**完整 outcome space**：self tsumo、self ron by target、opponent ron、opponent tsumo、draw，四家支付在兩 scheme 皆守恆。

因此缺口是**已知的模型不完整**（審查 Phase 3.5、MJ-006 早已點名：缺自己榮和、缺他家自摸支付、缺未來棄牌放槍、`DRAW_VALUE=0`），oracle 只是把這些缺項量化成**排序後果**——在完整支付下 attack-only 的排序會被顛覆。

## 4. 必須誠實的限制（不得過度解讀）

- Corpus **極小且刻意 omniscient**：僅 **2 個 exact state、13 個 non-tied pair**。
- 100% inversion 很刺眼，但這是「刻意挑出會暴露缺項的小牌牆」，**不是母體偏差估計**。
- Oracle 規格文件自述：「A future model replacement requires a larger, versioned reference corpus and may not be inferred from this small oracle alone.」

**正確結論**：「現行近似在完整支付下不可靠」有強證據；但「整體偏差量多大、在真實對局分布下多常翻轉排序」**尚無代表性估計**。

## 5. 決策

**排這個批次，但分兩段，且不得在有代表性 corpus 前直接重寫 production。**

理由：沒有代表性 oracle corpus，就無法區分「新模型真的更準」與「只是換了另一種偏差」；且完整 outcome 評估的狀態空間呈指數成長，latency 風險需先量測。

---

## 批次 E — 完整 outcome EV（提案）

### E0 — 擴充版本化 reference corpus（前置，先做，低風險）

**目標**：把 oracle corpus 從 2 個小 state 擴到具代表性的版本化集合，作為 E1 的驗收底線。

**涉及**：`taimahjong/reference_ev.py`、`taimahjong/ev_benchmark.py`、`scripts/ev_reference_report.py`、新增 corpus fixture 與 `tests/`。

**驗收條件**：
- Corpus 版本化（含 corpus_version 欄位），涵蓋早／中／晚牌牆、0/1/3 宣告對手、染手、莊連莊、兩 scheme，至少數十個 state。
- 每個 state 的 oracle 終端機率和為 1、四家支付兩 scheme 皆守恆（table-driven test）。
- 報告現行近似對此擴充 corpus 的 MAE、top-1 agreement、ranking inversion 的**分布**（非單點），並記錄 per-state latency。
- 產物 byte-reproducible 或數值等價（固定 seed／Fraction）。

### E1 — 實作完整 outcome EV（主體，較大、需 E0 支撐）

**目標**：production EV 納入完整 outcome 與支付，並以 E0 corpus 驗證確實改善。

**涉及**：`taimahjong/ev.py`、`taimahjong/simulate.py`，及其 API/UI/quiz/trainer 消費端。

**驗收條件**：
- EV 納入 self ron by target、opponent ron、opponent tsumo、future discard deal-in 與狀態更新；draw value 依 house model。
- 以 E0 corpus 對照，報告替換**前後**的 absolute EV error、top-1 agreement、ranking inversion 改善；新模型須在多數指標上優於 attack-only baseline。
- latency 超標時保留 approximate mode 並在 response/UI 明確標籤；量測 p50/p95。
- 保留 CRN 與固定 seed 可重現；seeded snapshot 變動須逐項記錄原因，不得靜默改答案。
- 與 MJ-011 的 SE/CI 整合：排名邊界（top-gap CI 含 0）標 uncertain/marginal。

**風險**：狀態空間與運算量大；沒有 E0 corpus 前直接重寫容易引入更深且更難察覺的錯誤。

---

## 6. 排序建議

- 這是原審查 roadmap **R2（補 EV 模型）** 的落實；批次 B 已完成其前置（oracle + 量測框架 + CI 輸出）。
- 建議先做**批次 C**（MJ-009/010/012/013/014：槓教學、校準治理、API 安全與 score context）——多為獨立、低風險的正確性/安全修正，可快速清理；
- 批次 E（E0→E1）排在 C 之後或與 E0 平行起手，E1 為整個 roadmap 中最大、最需 corpus 支撐的一項。
