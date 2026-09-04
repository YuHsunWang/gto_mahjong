# 台灣十六張麻將策略與教學專案：完整深度審查

審查日期：2026-07-23  
審查範圍：`/mnt/d/Claude/mahjong` 全 repository  
規則基準：使用者指定的台灣十六張、34 種普通牌、無花牌、無寶牌、無立直／振聽／一發，並支援底 3／台 1 與底 5／台 2。

## 0. 結論摘要

### 0.1 狀態定義

- **CONFIRMED（已確認問題）**：已讀到實作路徑，且有測試、腳本輸出、API 行為或可直接推導的控制流程證據。
- **PLAUSIBLE（合理懷疑）**：實作顯示明確風險，但欠缺外部規則表、真實分布或足夠樣本，不能斷言實際偏差量。
- **UNVERIFIED（尚未驗證）**：本次沒有可用的權威基準、執行環境或可行的窮舉範圍；不以「沒發現問題」取代。

### 0.2 整體判斷

專案不是空殼：牌張表示、一般牌型向聽、進張、台數分解、吃碰槓流程、莊家／連莊結算、危險度、固定 seed 模擬、練習題與 SPA/API 已形成一條可執行產品鏈。現有測試也明顯超過一般原型的 smoke tests。

但目前不能把輸出稱為「GTO 最佳解」，也不能說兩種底台模式已在所有收益、損失與教學流程一致套用。最重要的問題是：

1. **CONFIRMED / P0 — 底 5／台 2 沒有端到端傳遞。** 核心 `ScoringScheme` 算式正確，但算台 API、算台／分析 UI、CLI、trainer 實際結算與自動決策仍使用底 3／台 1；同一局甚至可以逐步切換評分 scheme，造成 scorecard 混合單位。
2. **CONFIRMED / P0 — 自摸模擬的貪婪策略不累積自家先前棄牌。** 牌池不會把棄牌放回，但後續進張比較仍一直使用初始 `seen`，會高估已棄出的同種牌並可能改變後續打牌。
3. **CONFIRMED / P0 — 對手公開副露在自動估算剩餘摸牌數時被重複扣除。** `remaining_draws` 已固定扣掉三家各 16 張，又把其副露算進 `visible` 再扣一次。
4. **CONFIRMED / P0 — 教學路徑沒有使用 committed calibration。** Stateless EV API 有載入校準表，但 quiz、endgame、trainer 的 discard/call/kong 評分未傳入 calibration；首頁「機率以機器人自我對局校準」的涵蓋範圍因此過廣。
5. **CONFIRMED / P0 — 「GTO」宣稱不成立。** 實作是固定規則／greedy／proxy EV bot 產生資料，再以危險分數查表；沒有策略空間、混合策略、best response、regret、Nash/均衡求解或 exploitability 評估。

此外，EV 只模擬自己的自摸，不模擬胡牌、他家自摸造成的支付、未來棄牌放槍與狀態更新；`fold` 是用最安全候選的單次風險建立的偽列，不是一個可執行的防守策略。這些限制在部分文件有坦白，但 UI 與「最佳解」文字仍給出過強的確定性。

## 0.3 實際驗證紀錄

| 檢查 | 指令／方法 | 結果 |
|---|---|---|
| 測試收集 | `python3 -m pytest --collect-only -q` | 168 tests collected；1 個 Starlette/httpx deprecation warning |
| 完整測試 | `python3 -m pytest tests/ -q` | 168 passed、0 failed、1 warning；766.96 秒（12:46） |
| 前端語法 | `for file in server/static/js/*.js; do node --check "$file"; done` | 全部 exit 0 |
| HTTP E2E | `uvicorn server.api:app --host 127.0.0.1 --port 8765` + 本機 HTTP client | `GET /` 200；score/ukeire/ev-rank 三個 POST 均 200；服務已關閉 |
| 獨立審查腳本 | `python3 scripts/review_validation.py` | 固定 seed 的 scheme、wall、visible、收斂與 fold 證據；輸出摘要見 Phase 3/4 |
| CLI | `python3 -m taimahjong ...` 代表性 analyze/ukeire/simulate | 三個模式皆 exit 0；固定 seed 400 sims 的 6 巡自摸率 32.00% |
| self-play | `head_to_head(20, 24001)` | 完成；difference −5.35、SE 1.082、RSS peak 約 177 MB；小樣本只作代表性執行，不外推 |

第一次直接執行審查腳本時因 `scripts/` 成為 `sys.path[0]` 而找不到同層 `server`，未產生驗證結果；加入 repo root 到腳本自己的 import path 後重跑。這是審查腳本的啟動修正，不改正式邏輯。

---

# Phase 1 — Repository Mapping

## 1.1 完整範圍與資料流

審查時逐檔閱讀 59 個 tracked files、12,160 行 tracked text，另閱讀本次新增的 `scripts/review_validation.py`。主要執行流如下：

```text
compact tile text
  └─ taimahjong/tiles.py
       ├─ shanten.py ↔ bruteforce.py (獨立交叉驗證)
       ├─ ukeire.py
       ├─ simulate.py ─ winning_trials / win_probability
       ├─ scoring.py ─ score_hand / ScoringScheme
       ├─ danger.py ─ opponent state / deal-in shape
       └─ ev.py ─ candidate selection + attack MC − immediate deal-in risk
             ├─ quiz.py / endgame.py
             ├─ trainer.py
             └─ server/api.py
                   └─ server/static/js/*.js SPA

selfplay.py ─ game loop / policies / settlement / calibration counts
  └─ calibration.py + data/calibration.json
```

### 核心模組

- `tiles.py:9-44`：34 維 count tuple、m/p/s/z 解析、每種最多四張。
- `shanten.py`：一般 5 組 1 對的十六張向聽；`bruteforce.py` 提供較慢、演算法獨立的 BFS oracle。
- `ukeire.py`：依向聽下降枚舉有效進張；`discard_analysis` 先向聽、再進張總數排序。
- `simulate.py:40-228`：固定策略下的多巡自摸 Monte Carlo 與 winning trial。
- `scoring.py:29-97,219-387`：台目、最大分解、scheme 換算與輸入檢查。
- `danger.py`：公開河／副露／宣告、牌形壁、染手、摸切手切、聽牌／棄和 heuristic。
- `ev.py:82-331`：剩餘巡、存活 heuristic、自摸收益、當張放槍損失、候選排序。
- `selfplay.py:335-482,766-806`：四人 bot、結算、批次與 head-to-head。
- `calibration.py:115-251`：count table、單調化與 lookup；`data/calibration.json` 是 2,000 局產物。
- `quiz.py`、`endgame.py`、`trainer.py`：可重現題目、評分、完整一局 generator。

### 後端與前端

- `server/api.py:180-550` 暴露 quiz/endgame/trainer/EV/score；`557` 後為進張教學 API。
- `server/api.py:118-177` 把 domain objects 轉成 JSON。
- `server/static/js/api.js` 統一 fetch/error；`main.js:12-139` hash router；`quiz.js`、`trainer.js`、`tools.js` 是主要畫面；`scheme.js` 使用 localStorage。
- `server/static/index.html` + `style.css` 是無 bundler 的原生 SPA。

### 測試、腳本、資料與文件

- 16 個 `tests/test_*.py`，collect 後為 168 cases，涵蓋 parser、向聽、進張、計分、模擬、CRN、危險度、對手狀態、EV、scheme、selfplay、quiz、trainer、API。
- `scripts/head_to_head.py`、`streak_defense.py`、`kong_ev.py` 是批次策略實驗；`gen_tile_faces.py` 是牌面資產生成；`review_validation.py` 是本次新增的唯讀驗證。
- `data/calibration.json:3-304` 保存 counts/metadata，`:306-635` 保存派生 tables。
- `README.md`、`README.en.md`、`docs/experiments.md`、`docs/ui-plan.md` 均已納入聲稱與實作比對。

## 1.2 Mapping 結論

- **CONFIRMED**：正式邏輯並非單一 model，而是規則演算法 + heuristic + Monte Carlo + bot calibration 的組合。
- **CONFIRMED**：SPA → API → domain modules 的資料流簡單清楚，但 scheme/calibration/kong state 在邊界上不完整。
- **CONFIRMED**：測試集中在 Python；前端只有靜態資產 HTTP smoke，沒有 JS unit、DOM、browser E2E。

---

# Phase 2 — 台灣麻將規則與計分

## 2.1 規則體系與牌張

- **CONFIRMED**：`tiles.py:5-44` 只接受 m/p/s/z，共 34 種，字牌限 1–7、每種 0–4 張。
- **CONFIRMED**：程式沒有 dora、立直、一發等日麻計分；`danger.py:382-390` 的宣告後安全牌是本專案 migi 規則，不是永久振聽。
- **CONFIRMED / 非缺陷**：目前沒有花牌與補花符合指定 scope。`scoring.py:119` 的 `extra` 只是未來擴充槽；首頁也明示「本桌無花牌」（`main.js:82,124-126`）。
- **CONFIRMED**：一般和牌目標為 5 組 + 1 對；特殊牌型未實作，README 有揭露。這是產品 scope，不在本次 ground truth 中被要求為缺陷。

## 2.2 吃、碰、槓

- **CONFIRMED**：selfplay/trainer 有吃、碰、暗槓、加槓、大明槓、搶槓與槓上開花流程；trainer 的 replacement win 實際會帶 `kong_bloom=True` 到 settlement（`trainer.py:642-672`）。
- **CONFIRMED**：計分把槓視為一組；明槓破門清、暗槓保留門清，且本 house table 槓本身 0 台、槓上／搶槓各 1 台（`scoring.py:55-60` 及 scoring tests）。
- **PLAUSIBLE**：固定 16 張 dead wall 不回補，與某些實桌做法不同；專案已在 `docs/experiments.md:21-23` 說明。使用者沒有指定 dead-wall 回補細則，故不能判為規則錯誤。
- **CONFIRMED / 文件問題**：`scoring.py:7` 還寫「kongs are not modelled」；`selfplay.py` 頂部與 README 的 trainer「不含吃碰」說明也落後於現況。

## 2.3 台數計算

`scoring.py:29-60` 把莊、連莊、門清、自摸、獨聽、平胡、全求人、暗刻、碰碰胡、混一色、清一色、字一色、三元、風牌、天地胡、migi、槓上／搶槓設為具名常數。`score_hand` 在 `219-319` 枚舉完成分解並取最高台，`322-387` 檢查張數、跨 concealed/meld/kong 的物理 copy 與 context。

- **CONFIRMED**：現有 table 的內部運算與 stacking 選擇有直接測試，包含最大分解、明暗刻、大小三元／四喜、平胡、自摸、莊連莊、槓。
- **CONFIRMED**：`WinContext.__post_init__` 阻止天地胡同時、槓上與非自摸、搶槓與自摸等部分矛盾。
- **CONFIRMED / P1**：仍可提交不可能 context，例如非莊 `heavenly=true`、莊家 `earthly=true`、地胡非自摸等；`server/api.py:531-542` 直接建 context 並計台。這會把不可能局面算成有效分數。
- **UNVERIFIED**：每一項台值與互斥／相疊是否符合某一個外部「標準台灣十六張」權威表。台灣規則有 house variants，而使用者提供的 ground truth 沒有列出台目表；本次只能確認專案 table 的內部一致性，不能把單元測試當成外部規則證明。

## 2.4 底台換算與支付

`ScoringScheme.value` 明確使用 `base_units + tai_units * total_tai`（`scoring.py:67-97`）：

- 底 3／台 1：`3 + 台數`
- 底 5／台 2：`5 + 2 × 台數`

`tests/test_scheme.py` 驗證兩 preset、win value 與 opponent loss 在核心 EV 層會隨 scheme 改變。`selfplay._settlement` 則在 `414-482` 做：

- 放槍：實際 discarder 單獨支付。
- 自摸：三家各支付一腿。
- 莊家贏：莊／連莊 premium 已進每腿 hand value。
- 閒家贏：只有涉及莊家的 payment leg 加 bilateral premium。
- 每局四家 delta 合計為 0，測試涵蓋放槍者、連莊與非莊胡莊。

這個支付模型的**底 3／台 1 內部算術為 CONFIRMED**。但第二模式在產品邊界斷裂：

1. `ScoreRequest` 無 scheme 欄位（`server/api.py:478-490`），response 固定 `result.value_units` 與 `BASE_UNITS`（`:528-548`）。
2. score/analyze UI 不讀 `scheme.js`，也不送 `base_units/tai_units`（`tools.js:62-106,122-217`）。
3. CLI parser 沒有 scheme options（`__main__.py:97-135`）。
4. trainer `new` 不保存 scheme（`server/api.py:280-293,356-366`）；`act` 的 scheme 只用於當步評分（`:400-452`）。
5. `play_trainer` 沒有 scheme parameter，終局 `_settlement(...).value_units` 固定 default（`trainer.py:572-617,630-707`；`selfplay.py:429-482`）。
6. 同一 trainer session 可以每個 action 送不同 scheme，`score.loss` 因而混合不可比較的單位。

**CONFIRMED / P0**：兩種模式沒有一致套用所有胡牌收益、放槍損失、攻守與籌碼 EV，違反本次核心規則基準。獨立腳本亦顯示 engine 的 3/1 與 5/2 值不同，但 `/api/score` 即使多送 5/2 欄位，response 與 default 完全相同。

---

# Phase 3 — 機率與期望值

## 3.1 向聽與有效進張

- `shanten.py` 使用數字牌 suit DP 與 honor options，並依 declared meld count 調整 concealed size。
- `bruteforce.py` 以較慢 BFS 建立演算法獨立 oracle。
- `tests/test_cross_validation.py:42-63` 比對 320 個固定 seed、接近完成且含副露的合法狀態。
- `ukeire.py` 對 34 種摸牌逐一檢查向聽是否下降，copies 為 `4 - hand - visible`；`tests/test_ukeire.py` 同時有已知答案與 seeded direct enumeration。

判定：

- **CONFIRMED**：在測試覆蓋的合法一般牌型上，fast shanten 與獨立 oracle 一致；進張與逐牌枚舉一致。
- **PLAUSIBLE**：一般牌型演算法正確性很強，但 320 個狀態不是所有合法 34 維狀態的窮舉證明。
- **CONFIRMED**：進張只在呼叫者給的 visible 正確時才代表真實剩餘張；模擬呼叫者沒有動態更新 visible，見下節。

## 3.2 剩餘牌與剩餘摸牌

`remaining_draws` 在 `ev.py:82-93` 計算：

```text
136 - dead wall 16 - own hand - three opponent hands 48 - visible
```

API 又將對手的 river 和 meld 全部加入 visible（`server/api.py:94-101,497-511`）。

**CONFIRMED / P0**：river 是已離開牌手的額外公開牌，應扣；但 open meld 本來就是該對手 16 張持牌的一部分，已包含在固定 48 中，不能再扣。審查腳本的最小例：

- 17 張自家 post-draw hand + 對手 1 張 river：函式回 14 次。
- 同一狀態只多標示該對手一組 3 張 open meld：函式回 13 次。
- 實體牌總數沒有因「把對手手內三張標成公開」再少三張，正確仍應是 14 次。

`tests/test_ev.py:108-111` 只測「四張 public tiles」會少一巡，沒有區分 discard 與已計入 opponent holding 的 meld，故測試通過不能發現這個 double count。

## 3.3 多巡聽牌率與自摸率

`simulate.py:40-154` 建立實體 unseen pool、shuffle、逐巡 draw，未和則選「最低向聽、最高進張」的 greedy discard；`157-228` 收集 winning trials 供 EV 計分。初始聽牌的單巡命中已有 exact hypergeometric 測試（`tests/test_simulate.py`）。

**CONFIRMED / P0**：`seen` 只在第 59/174 行由輸入建立，greedy 進張在第 105/207 行永遠使用這個初始值。雖然 draw pool 不把棄牌放回（故物理抽牌本身正確），後續決策卻把先前棄出的同種牌當仍可摸，造成策略 bias。審查腳本沿 production 牌池與 production 選擇走訪，並比較累積自家 discard 的 dynamic visible，找到固定 seed 下選擇分歧（完整 state 在腳本輸出）。

- 這不是「棄牌會被重新摸回」；問題精確地是**policy 的 ukeire accounting stale**。
- `@lru_cache` 也只以 hand 為 key（`simulate.py:72-109,183-210`）；修正時要把 visible state 納入 key 或改成按剩餘 counts 計算。

## 3.4 放槍率與 calibration

`danger_score` 是公開牌形 heuristic；`deal_in_ev` 在 `ev.py:241-261`：

1. 先取得 danger score。
2. 有 calibration 時查 `deal_in_probability`。
3. 無 calibration 時使用 `0.02 * score / 9`。
4. 乘宣告／聽牌 factor 與估計的 opponent hand value。

`data/calibration.json` metadata 記錄 2,000 games、277,905 exposures、1,308 deal-ins、92,635 tenpai observations；這是 bot ecology，不是真人資料。

- **CONFIRMED / P1**：`Calibration.deal_in_probability` 對低分第一個 usable bucket 直接回該概率（`calibration.py:234-251`）。目前 `0-1` bucket 是 0 deal-in / 31,883 observations，lookup 因而回精確 0，沒有 Beta/Laplace smoothing 或下置信界；對風險教學過度確定。
- **PLAUSIBLE**：isotonic/單調化本身合理，但同一批資料 fit 又 report，沒有 holdout、Brier/log loss、reliability diagram 或 bootstrap CI，外樣本 calibration 品質未知。
- **CONFIRMED / P0**：stateless `/api/ev/rank` 傳 `_calibration()`（`server/api.py:104-107,512-516`），但 `quiz._rank_cached/_refine`（`quiz.py:338-353,400-417`）與 trainer 的 option/refine/best-discard（`trainer.py:397-452`）都未傳 calibration，因此真正教學評分走 fallback。
- **CONFIRMED / P1**：`Calibration.tenpai_probability` 除測試外只在 CLI danger 顯示使用（`__main__.py:282`）；Web opponent `tenpai_estimate` 及 EV hazard 仍使用手寫 `tenpai_score`，所以 committed table 的 tenpai 部分沒有接進 Web 教學。
- **CONFIRMED / P1**：重建 calibration 的 `ev_aware` bot 會讀現有 committed calibration（`selfplay.py:321-369`），而 CLI metadata 沒記 source table hash（`__main__.py:174-189`）。在有／無舊檔時，同 seed 產生的是不同資料生成政策，形成未被記錄的 circular provenance。

## 3.5 籌碼 EV 與候選比較

`ev_rank` 的實際公式可概括為：

```text
net EV(candidate)
  = survival-discounted P(own self-draw) × conditional hand value
  + P(draw) × DRAW_VALUE(=0)
  - Σ immediate deal-in probability(candidate discard, opponent) × opponent value
```

證據：`ev.py:185-218,241-323`。

### 已正確處理

- **CONFIRMED**：候選使用 common random numbers（同 seed）降低差值 variance（`:297-317`；`tests/test_crn.py`）。
- **CONFIRMED**：scheme 會同時縮放自己的 hand value 與 opponent loss（`:147-162,221-261`）。
- **CONFIRMED**：莊／連莊在 own template 與 opponent value 中都有路徑；現有測試覆蓋。

### 模型缺口

- **CONFIRMED / P0**：attack simulation 只含自摸；不含自己胡牌。
- **CONFIRMED / P1**：對手先胡只以固定 per-turn survival hazard 折減自己的攻擊，沒有扣除對手自摸支付；hazard 在整段 future 不更新（`ev.py:96-132`）。
- **CONFIRMED / P1**：只扣當下候選 discard 的放槍損失，沒有 rollout 後續每次 discard 的放槍。
- **CONFIRMED / P1**：`DRAW_VALUE=0`，沒有流局聽牌支付或牌局價值。
- **CONFIRMED / P1**：先由純效率 top-k 選候選，再最多補兩張比 baseline 更安全的牌（`ev.py:285-295`）；未被選中的 discard 沒有算 net EV，故不能保證全手最佳。
- **CONFIRMED / P1**：`fold` row 取真實候選的 minimum one-discard risk、attack=0（`:324-331`）。因此同風險的真實候選有非負 attack，fold 不可能嚴格優於最佳真實候選；它不是多巡棄和 policy，卻被 endgame 當 defense tag 的來源（`endgame.py:60-68`）。
- **PLAUSIBLE**：這些近似可作教學排序，但排序偏差量與排名反轉率未以 full-game counterfactual oracle 驗證。

---

# Phase 4 — 模擬收斂與效能

## 4.1 固定 seed、樣本量與信賴區間

既有測試確認：

- 同 seed deterministic、不同 seed 可不同。
- cumulative tenpai/win curve 單調。
- 單巡聽牌 exact hypergeometric 在 20,000 sims 內符合 tolerance。
- quiz 只在 verdict boundary 提高 sims，且 CRN 下 refined delta 的跨 seed variance 較低。

但 UI 只顯示點估計。`main.js:124-126` 有一般性的 Monte Carlo 提醒，單筆 EV table 沒顯示 SE/CI；`EVRankEntry` 也沒有 sampling variance。

本次 `scripts/review_validation.py` 對同一 16 張手牌、6 次摸牌，使用 3 seeds × 100/400/1,600 sims，記錄：

- 各 seed `p_win`
- seed 間 sample SD
- 合併 Bernoulli 近似 SE 與 95% CI
- wall-clock time

並對固定 17 張手牌使用 24/96 sims × 3 seeds 記錄候選排名。最終數值見附錄 A 原始輸出摘要。

判定：

- **CONFIRMED**：固定 seed 的可重現性成立。
- **CONFIRMED**：低 budget 會有明顯離散化（例如 24 trials 時每次 win 使機率跳 4.17%）；CRN 只降低候選差值的共同噪音，不消除 absolute MC error。
- **CONFIRMED**：本次 6 巡例在 100 sims/seed 時三 seeds 為 25%/37%/29%（seed 間 SD 6.11 個百分點）；1,600 sims/seed 收斂為 28.50%/30.06%/30.00%（SD 0.88 個百分點）。
- **CONFIRMED**：EV 排名例在 24 與 96 sims、共 6 組 seed/budget 中，top choice 為 `1m` 4 次、`9m` 2 次；96 sims 仍有 seed 23 的 top 反轉。
- **PLAUSIBLE**：現行 cheap/refine/escalate budgets 對一般 verdict 多半可用，但沒有對所有題型提供「排名反轉機率 < 某門檻」的驗收證據。

## 4.2 自我對打實驗的統計強度

- `selfplay.head_to_head` 有 sample SE 與 z-like `difference / SE`（`selfplay.py:773-806`）。
- `scripts/head_to_head.py:14-27` 的 chunk output 只輸出 sums，合併後需要保留 second moment 才能精確重建 SE。
- `docs/experiments.md:56-97` 的 cautious 研究每 cell 1,000 games，但表格沒有 CI；120-game ev-aware 結果自己承認只是 directional。
- `docs/experiments.md:115-141` 以 1,000 games/cell 將大明槓 −0.112 稱為 clearly negative，卻沒有 paired-difference SE/CI。
- `tests/test_selfplay.py:312-330` 的大明槓測試只有 200 games 與方向 tolerance，能防大型 regression，不能證明效應估計精度。

**PLAUSIBLE**：大明槓方向可能穩健，但「約 −0.11」與 seat/streak 百分比不應在沒有 CI 的情況下當精確教學常數。

## 4.3 效能、記憶體與平行化

- **CONFIRMED**：`play_games` list comprehension 與 `head_to_head` for loop 都是單程序循序（`selfplay.py:766-790`）；EV candidates 也是循序。
- **CONFIRMED**：FastAPI endpoints 是同步 `def` 且直接執行 CPU-heavy engine；`EvRankRequest.sims` 無上限（`server/api.py:464-475`）。超大 sims 請求可長時間佔 worker，是可重現的資源耗盡風險。
- **CONFIRMED**：simulation 的 per-call `lru_cache(maxsize=None)` 生命期只在該函式呼叫內；不會跨 request 永久累積，但單次高 sims/turns 仍可能建立大量 hand states。
- **CONFIRMED**：selfplay 有 bounded caches；shanten 的部分全域 cache 需要監控，但本次代表性執行未證明 memory leak。
- **UNVERIFIED**：多使用者持續併發、長時間 RSS 趨勢、4/8 worker scaling、Windows/WSL 原生瀏覽器延遲。沒有做壓力測試，不能聲稱 production capacity。

---

# Phase 5 — 策略與教學

## 5.1 系統實際教的決策方法

正向部分：

- **CONFIRMED**：pure efficiency 明確教「先減向聽、再看進張」，並顯示有效牌與剩餘張數。
- **CONFIRMED**：quiz feedback 拆成 attack、risk、net EV，且顯示 chosen vs best、EV loss、marginal verdict。
- **CONFIRMED**：trainer 覆蓋打牌、吃碰、暗／加槓、完整 outcome；endgame 依 late wall + pressure 篩題。
- **CONFIRMED**：首頁有明示「bot calibration 非真人」與「進攻 EV 僅計自摸」（`main.js:122-126`），這是重要的 honest scope。

主要問題：

1. **CONFIRMED / P0**：`main.js:24` 寫「和 GTO 最佳解比對」，但本專案沒有 GTO 計算。
2. **CONFIRMED / P0**：README 的「理論最佳」「所有機率校準」類文字與實際 heuristic/fallback 不符。
3. **CONFIRMED / P1**：`lessons.js:63,71` 說碰牌會「失去自摸機會／自摸額外台」；計分 `scoring.py:261-265` 對開門手仍加自摸台，只失去門清台。這是直接錯誤的教學。
4. **CONFIRMED / P1**：kong recommendation 的 `_kong_option_ev` 對 replacement tile 一律接 `_best_discard_ev`（`trainer.py:490-512`），沒有先判斷立即和牌，也沒有計槓上開花 +1；docstring 自己承認（`:548-557`）。實際 game loop 卻會正確結算（`:665-672`），造成「評分模型」與「遊戲結果」不一致。
5. **CONFIRMED / P1**：call pass branch 只算 self-draw win EV，沒算未來放槍；call branch 則有當下 discard risk（`trainer.py:381-430,526-530`），比較基準不對稱。
6. **CONFIRMED / P1**：fold row 不是可執行策略，使用者學不到「接下來幾巡應如何守」。
7. **CONFIRMED / P2**：API `_position_payload` 沒輸出 `own_kongs`（`server/api.py:118-148`）；人類槓後，trainer 畫面只畫 own melds，已宣告槓在後續局面不可見。

## 5.2 速度、台數與攻守取捨

核心 scheme 可以讓高台 vs 快和的 value 比例改變，這個設計方向正確。但由於：

- 題目產生固定使用 default scheme（`quiz.py:356-396`）；
- teaching rank 又沒有 calibration；
- EV attack 缺 ron、future risk 與 opponent tsumo；
- trainer settlement 不用所選 scheme；

**PLAUSIBLE**：教學可作「heuristic EV 練習」，但目前不能作兩種底台制度下的權威攻守建議。

建議產品文字應明確叫「此模型估計的最佳選擇」，並在每題顯示模型版本、scheme、sims/seed、是否 calibration、主要未建模項目。

---

# Phase 6 — UI／UX 與工程品質

## 6.1 完整操作流程

已用 Uvicorn 實際啟動 SPA/API：

- `/` 回 HTML 200。
- `/api/score`、`/api/ukeire`、`/api/ev/rank` 代表性合法 payload 均回 JSON 200。
- TestClient 測試另涵蓋 quiz new/grade、trainer session/act/reload、錯誤 payload。
- 所有 `server/static/js/*.js` 通過 `node --check`。

**UNVERIFIED**：沒有真實 browser automation，故視覺排版、窄螢幕、touch、螢幕閱讀器、focus order、顏色對比與一點即切的實際誤觸率均未驗證。

## 6.2 資訊層級與單位

- **CONFIRMED / P0**：全域 scheme toggle 沒進 analyze/score，使用者會以為設定已套用。
- **CONFIRMED / P1**：trainer 每步 grading 可能用 5/2，但 outcome point delta 用 3/1，畫面中的「同一局」不是同一籌碼制度。
- **CONFIRMED / P2**：首頁 stats 將 EV loss 標「台」（`main.js:54-62`），但 5/2 時是 value/chip units；score 又顯示「台單位」（`tools.js:217`），名詞混用。
- **CONFIRMED / P2**：own kong 未序列化／未畫出，使公開桌面狀態不完整。
- **PLAUSIBLE**：tile `title` 與文字資訊可提供部分可及性，但動態牌按鈕缺一致的 `aria-label`/live region；需要 axe/browser 實測。

## 6.3 輸入驗證與 API

優點：

- Pydantic + `_engine` 統一轉 422。
- tile physical copies、meld shape、river origin、session step conflict、非法 action/option 有測試。
- trainer 每 session lock，錯誤選擇在 send generator 前驗證（`server/api.py:391-457`）。

缺口：

- **CONFIRMED / P1**：`sims`、`turns` 等 expensive inputs 沒合理上限；同步 CPU endpoint 可被單 request 壟斷。
- **CONFIRMED / P1**：score context 允許規則上不可能的天地胡／莊家組合。
- **CONFIRMED / P1**：score API 沒有 kongs、kong_bloom、robbed_kong 欄位，無法從 Web 完整使用核心 scoring 能力。
- **CONFIRMED / P1**：stateless analyze 只接受一名對手，且 `melds` 是該對手副露；沒有 own meld/kong 輸入。核心 `ev_rank` 可接受三名 opponents 與 `melds_declared`，但 Web 任意局面分析無法表達三家完整公開狀態或自己的開門手（`server/api.py:464-516`；`tools.js:62-106`）。
- **CONFIRMED / P2**：`_scheme` 接受 0–100/1–100 的任意組合（`server/api.py:184-200`），產品明明只有兩個支援模式；API 與 UI contract 不一致。
- **CONFIRMED / P2**：session 是 process-memory，64 筆 FIFO eviction，無 persistence；作本機教學可接受，但多 worker/session stickiness 未處理。

## 6.4 架構、耦合、測試與技術債

- **CONFIRMED**：domain modules 大致可獨立測試，`WinValueContext` 把 scoring template 與 EV 相接，方向良好。
- **CONFIRMED**：private functions/constants 跨模組使用較多，例如 EV 直接 import danger private helper；calibration、selfplay、teaching 各自決定是否載表，使 feature flags 分散。
- **CONFIRMED**：`trainer.py` 直接 import quiz budgets/thresholds，完整局與單手題的計算政策耦合。
- **CONFIRMED**：tests 很多，但「既有 implementation 對自身 expectation」比例仍高；缺少 scheme E2E、open-meld live wall、dynamic visible、calibration wiring、score context、browser/UI tests。
- **CONFIRMED**：Starlette TestClient 發出 httpx 相依 deprecation warning；目前不影響結果，但 Python 3.14 升級路徑需處理。

---

# Phase 7 — 整合報告與 Roadmap

## 7.1 風險整合

| 優先級 | 狀態 | 問題 | 影響面 |
|---|---|---|---|
| P0 | CONFIRMED | scheme 沒端到端傳遞 | 規則、計分、EV、trainer、UI、CLI |
| P0 | CONFIRMED | simulation policy 不累積 own discards | 機率、EV、策略排名 |
| P0 | CONFIRMED | opponent meld 在 live wall double count | 摸牌巡數、EV、API |
| P0 | CONFIRMED | quiz/trainer 未使用 calibration，文字卻廣泛宣稱 | 機率、教學、可信度 |
| P0 | CONFIRMED | GTO／最佳解宣稱無對應方法 | 產品誠信、策略 |
| P1 | CONFIRMED | EV 缺 ron、opponent payment、future discard risk | 攻守與 net EV |
| P1 | CONFIRMED | fold 不是 policy，候選亦非 exhaustive | 殘局與「最佳」排名 |
| P1 | CONFIRMED | kong grading 漏立即槓上開花 | 槓教學 |
| P1 | CONFIRMED | calibration 零風險 bucket、無 OOS/CI/provenance | 放槍率可信度 |
| P1 | CONFIRMED | 無 sims 上限且同步 CPU endpoint | 可用性／資源 |
| P1 | CONFIRMED | impossible score contexts、Web scoring 缺 kong | 規則/API |
| P1 | CONFIRMED | Web analyze 無法表達三名對手與自己的副露／槓 | EV/API/UI |
| P1 | CONFIRMED | lesson 誤稱碰後無自摸 | 教學正確性 |
| P2 | CONFIRMED | stale docs、單位混用、own kong 不顯示 | UX／維護 |
| P2 | PLAUSIBLE | accessibility / responsive defects | UI |

## 7.2 分階段可執行 Roadmap

完整、可逐項交付的 acceptance criteria 見
`docs/codex-gpt-5.6-sol-action-items.md`。建議依以下依賴順序：

### R0 — 先建立可信基準

1. 固定兩個 scheme 的端到端 golden scenarios（score、ron、tsumo、dealer/streak、trainer outcome）。
2. 把本次 live-wall 與 dynamic-visible reproductions 轉成正式 regression tests。
3. 建立 representative position corpus，保存每個 candidate 的 raw trials 或至少 win count/value moments。

風險：若先調模型再補 baseline，無法區分 bug fix 與策略行為漂移。  
驗證：新增 tests 在修正前能重現問題、修正後通過；舊 168 tests 全通過。

### R1 — 修 P0 correctness

1. 建立 immutable `GameConfig/AnalysisConfig`，只允許 3/1、5/2，session 建立時固定；貫穿 API、CLI、score、EV、trainer、自動宣告與 settlement。
2. 將 public state 分成 `discards` 與 `tiles_in_opponent_holdings`，避免 live-wall double count。
3. simulation 每巡更新 own discards，cache key 包含 remaining/visible。
4. 用單一 calibration provider 注入 stateless EV、quiz、endgame、trainer；response 回傳 calibration id/fallback。
5. 在模型補齊前，移除 GTO／「理論最佳」字眼，改為「目前 heuristic/MC 模型的估計最佳」。

風險：scheme 與 visible 修正會改大量 seeded snapshot/quiz ranking。  
驗證：保留 seed 可重現，但允許更新 expected snapshots；用 before/after corpus 報告 ranking flip，不靜默改答案。

### R2 — 補 EV 模型

1. 先定義完整 outcome space 與支付：self tsumo、self ron by target、opponent ron、opponent tsumo、draw。
2. 把 future public state、future discard danger、target-specific dealer leg 放入 rollout。
3. 將 fold 變成明確多巡 policy；先用 all-discard reference/equivalence tests 驗證 candidate pruning，再決定是否恢復 pruning。
4. 每個 entry 回傳樣本數、SE/CI、與第一／第二名差值 CI；邊界排名自動增樣。

風險：計算量顯著上升，且不能在沒有 reference corpus 前取代現模型。  
驗證：小牌牆 exact enumeration、支付守恆、CRN paired SE、排名穩定率與 latency budget。

### R3 — 校準與實驗治理

1. time/seed holdout，輸出 Brier、log loss、reliability、bucket CI。
2. 對零事件 bucket 做有文件的 Bayesian/Beta smoothing 或置信上界。
3. metadata 記 code commit、config、source calibration hash、policy、seeds、Python version。
4. head-to-head/kong/streak 腳本保存 per-game paired difference 或 sum/sumsq，所有結論附 CI。

風險：bot ecology calibration 仍不能外推真人。  
驗證：OOS 指標優於明確 baseline，且 UI 永遠標出資料域。

### R4 — 教學與 UI

1. 修正吃碰自摸敘述與 kong grading。
2. 顯示 scheme、模型 scope、seed/sims、CI、calibration/fallback。
3. 顯示 own kongs；統一「台數」與「籌碼單位」。
4. 加 browser E2E、keyboard、mobile viewport、axe。

風險：資訊過多會壓過教學主線。  
驗證：先做可展開的「模型細節」，主畫面只保留決策與一個不確定性指標。

## 7.3 最終適用性判斷

- 作為**台灣十六張一般牌型／進張／heuristic EV 的研究與教學原型**：可用，且有不錯的測試基礎。
- 作為**兩種底台制度都一致的籌碼決策工具**：目前不合格（CONFIRMED）。
- 作為**校準過的真人牌局機率工具**：不合格；資料只來自 bot ecology，部分教學甚至沒接表。
- 作為**GTO solver 或 GTO 最佳解教師**：不合格；方法與驗證都不存在。

---

# 附錄 A — 命令、原始結果摘要與限制

## A.1 pytest

```text
$ python3 -m pytest --collect-only -q
168 tests collected in 1.09s
warning: Starlette TestClient/httpx deprecated
```

完整 suite 最終結果：

```text
$ python3 -m pytest tests/ -q
168 passed, 1 warning in 766.96s (0:12:46)
warning: StarletteDeprecationWarning — current FastAPI TestClient/httpx bridge deprecated
```

第一次在網路／socket 受限的 sandbox 內執行時，連最小
`TestClient(app).get("/api/health")` 都會無限等待；同一最小命令在 sandbox
外 0.57 秒回 200。因此中止那次環境阻塞的 suite，經核准在 sandbox 外以
**完全相同指令**重跑並取得上述完整結果。這段軌跡不能算成 test failure，
但顯示測試 harness 依賴 thread/socket 能力；最終 168 項確實全部執行。

## A.2 HTTP 與 JS

```text
GET  /             200 text/html; charset=utf-8 1073 bytes
POST /api/score    200 keys=[base_units, items, total_tai, value_units]
POST /api/ukeire   200 keys=[discards, mode]
POST /api/ev/rank  200 keys=[entries, turns]
```

`server/static/js/*.js` 全數 `node --check` exit 0。

代表性 CLI：

```text
ukeire: 123m123p123s1112223z -> shanten 0, 3z:3
analyze: 123m123p123s11122233z -> 12 個候選；1m/1p/1s 各 7 張進張居首
simulate: 123456789m1123p567s, turns=6, sims=400, seed=17
          cumulative win = 4.50%, 9.75%, 14.50%, 20.25%, 26.25%, 32.00%
```

代表性 self-play：

```text
head_to_head(games=20, seed=24001)
ev_aware_mean=-2.675, attack_mean=+2.675
difference=-5.35, SE=1.0816, difference/SE=-4.946
elapsed=14.06s, max RSS=177,348 KiB
```

這只是確認完整四人模擬可執行並示範 seed-specific 結果；20 局不能證明一般政策優劣。這組結果反而顯示不能因政策名為 `ev_aware` 就預設優於 attack。

## A.3 `scripts/review_validation.py`

用途：

- 比對同一 score 的 engine 3/1、5/2 與 score API 行為。
- 重現 opponent open meld 對 `remaining_draws` 的 double deduction。
- 沿固定牌池找 static vs cumulative-visible greedy discard 分歧。
- 記錄 win probability 的 seed/budget/SE/CI/time。
- 記錄 EV top choice 在 seed/budget 下的穩定性。
- 顯示 committed calibration 的零事件 bucket。
- 驗證目前 fold pseudo-action 不會嚴格打敗最佳真實候選。

執行：

```bash
python3 scripts/review_validation.py
```

最終輸出摘要（`/usr/bin/time -v`：exit 0、15.18 秒、max RSS 81,936 KiB）：

```text
score: total_tai=20; engine 3/1=23, engine 5/2=45;
       API default=23, API with extra 5/2 fields=23 (fields ignored)
remaining draws: one river=14; same river + open meld=13; physical expectation=14
visible divergence: seed=1, turn=10, state=22344567789m234p567s;
                    static choice=2m, cumulative-visible choice=4m
6-turn p_win means:
  100 sims/seed  = 0.3033, between-seed SD=0.0611, approx CI=[0.2513,0.3554]
  400 sims/seed  = 0.2833, between-seed SD=0.0333, approx CI=[0.2578,0.3088]
  1600 sims/seed = 0.2952, between-seed SD=0.00885, approx CI=[0.2823,0.3081]
EV top choice over 6 seed/budget cells: 1m=4, 9m=2
calibration bucket 0-1: 0/31,883, lookup(0)=lookup(0.5)=0.0
fold: net=0, best real=1.75, fold strictly beats best real=false
```

## A.4 尚未驗證清單

1. **UNVERIFIED**：外部權威 house rule 下每一台目數值與 stacking；缺少使用者指定的完整台目表。
2. **UNVERIFIED**：所有合法一般手牌的 exhaustive shanten/scoring 正確性；已做 known cases + seeded cross-validation，不等於全狀態證明。
3. **UNVERIFIED**：真實瀏覽器的視覺、mobile、鍵盤、screen reader、axe。
4. **UNVERIFIED**：真人牌局上的 tenpai/deal-in calibration 與策略 uplift。
5. **UNVERIFIED**：長時間、多 worker、多使用者的吞吐、RSS 與 session 一致性。
6. **UNVERIFIED**：特殊牌型與花牌；兩者均不在目前 scope，花牌缺席不得列為缺陷。

## A.5 本次檔案修改

- 新增 `scripts/review_validation.py`：唯讀、固定 seed 的審查驗證。
- 新增本報告。
- 新增 `docs/codex-gpt-5.6-sol-action-items.md`。
- 沒有修改核心引擎、API、SPA 或既有測試的正式行為。

## A.6 逐檔閱讀覆蓋清單

以下是開始審查時 59 個 tracked files；均已讀取，非只看 README：

- 根目錄／資料／文件：`.gitignore`、`requirements.txt`、`README.md`、`README.en.md`、`data/calibration.json`、`docs/experiments.md`、`docs/ui-plan.md`。
- scripts：`gen_tile_faces.py`、`head_to_head.py`、`kong_ev.py`、`streak_defense.py`。
- server：`server/__init__.py`、`server/api.py`。
- SPA：`index.html`、`style.css`、`tiles-demo.html`，以及 `api.js`、`feedback.js`、`lessons.js`、`main.js`、`quiz.js`、`scheme.js`、`stats.js`、`table.js`、`tile-faces.js`、`tiles.js`、`tools.js`、`trainer.js`。
- core：`taimahjong/__init__.py`、`__main__.py`、`bruteforce.py`、`calibration.py`、`danger.py`、`endgame.py`、`ev.py`、`quiz.py`、`scoring.py`、`selfplay.py`、`shanten.py`、`simulate.py`、`tiles.py`、`trainer.py`、`ukeire.py`。
- tests：`test_api.py`、`test_crn.py`、`test_cross_validation.py`、`test_danger.py`、`test_endgame.py`、`test_ev.py`、`test_opponent_state.py`、`test_quiz.py`、`test_scheme.py`、`test_scoring.py`、`test_selfplay.py`、`test_shanten.py`、`test_simulate.py`、`test_tiles.py`、`test_trainer.py`、`test_ukeire.py`。

生成型 `tile-faces.js` 亦檢查 export/key/資產結構並通過 JS syntax；沒有對每段 SVG path 的每個座標做視覺正確性裁定，該部分歸入真實瀏覽器的 UNVERIFIED 範圍。
