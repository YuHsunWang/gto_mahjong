# 台灣十六張麻將專案：可執行修改清單

來源：`docs/codex-gpt-5.6-sol-full-review.md`  
狀態：2026-07-23 深度審查

本清單依依賴順序編排。P0 是規則／模型正確性或產品聲稱的阻斷項；P1 是會實質誤導決策、降低統計可信度或造成服務風險；P2 是範圍、文件、可用性與維護品質。

---

## MJ-001 — 建立並固定端到端底台設定

- **優先級**：P0
- **狀態**：CONFIRMED
- **問題描述**：核心 `ScoringScheme` 支援底 3／台 1 與底 5／台 2，但 score API/UI、analyze UI、CLI、trainer generator、terminal settlement 與自動 migi 不是同一設定；trainer 每個 action 還可切換 scheme，scorecard 會混合單位。
- **涉及檔案與位置**：
  - `taimahjong/scoring.py:67-97`
  - `taimahjong/selfplay.py:429-482`
  - `taimahjong/trainer.py:572-707`
  - `taimahjong/__main__.py:97-135,197-205`
  - `server/api.py:184-200,280-293,356-452,478-548`
  - `server/static/js/tools.js:62-106,122-217`
  - `server/static/js/scheme.js`
- **建議修改方案**：
  1. 定義 immutable `GameConfig`，scheme 只允許兩個 preset。
  2. trainer `new` 時指定並保存，後續 act 禁止更換；generator、auto migi、grading、settlement 共用同一 instance。
  3. `_settlement` 接 `ScoringScheme`，一律用 `result.value_in(scheme)`。
  4. score/EV API 接 preset id 或嚴格 pair；CLI 增加 `--scheme 3-1|5-2`。
  5. analyze/score 讀取同一 global setting，response 回傳實際 scheme。
- **風險**：會改 seeded trainer 的 point delta、部分 EV 排名、既有 localStorage stats 單位；不能直接把舊 stats 當新 scheme 的紀錄。
- **驗收條件**：
  - 同一已知 4 台手牌在所有入口分別回 7 與 13 units。
  - ron/tsumo/dealer/streak 在兩 scheme 下 payment legs 與總和皆有 golden tests，四家守恆。
  - trainer session 建立後改送另一 scheme 得 409/422，不會靜默混用。
  - score、analyze、quiz、endgame、trainer、CLI 的 response/output 都標示相同 scheme。
  - 原 168 tests 加新 scheme E2E tests 全通過。

## MJ-002 — 修正 opponent open meld 的 live-wall 重複扣除

- **優先級**：P0
- **狀態**：CONFIRMED
- **問題描述**：`remaining_draws` 固定扣三家 48 張後，又從 `visible` 扣 opponent meld；副露仍是對手持牌的一部分，因而每組多扣三張，可能少算一巡。
- **涉及檔案與位置**：
  - `taimahjong/ev.py:82-93`
  - `server/api.py:94-101,497-511`
  - `taimahjong/__main__.py:76-90,197-205`
  - `tests/test_ev.py:108-111`
  - `scripts/review_validation.py:58-75`
- **建議修改方案**：
  1. 不再用一個 `visible` 同時表示「已離開所有手牌」與「公開但仍在對手 16 張 holdings」。
  2. `remaining_draws` 接明確的 `public_discards/other_out_of_hands`，或直接接 `wall_remaining`。
  3. danger/ukeire 仍可用包含副露的 visible；wall accounting 則只扣不在固定 holdings 中的牌。
- **風險**：修改 public-count contract 容易在 ukeire/danger 又漏扣副露；應以 typed state 避免布林旗標。
- **驗收條件**：
  - 同一 river 下只把對手三張手牌標成 open meld，不改 remaining draws。
  - 多家副露、槓、吃碰後 physical tile accounting 有 table-driven tests。
  - explicit `wall_remaining` 與 derived path 在等價局面回相同 turns。

## MJ-003 — 模擬每巡累積自家棄牌與剩餘牌狀態

- **優先級**：P0
- **狀態**：CONFIRMED
- **問題描述**：`win_probability`/`winning_trials` 的 draw pool 正確不回收棄牌，但 greedy ukeire 永遠使用初始 `seen`，後續會高估已棄同種牌並改變決策。
- **涉及檔案與位置**：
  - `taimahjong/simulate.py:59-109,116-135,174-210,214-227`
  - `scripts/review_validation.py:78-132`
- **建議修改方案**：
  1. 每 trial 維護 `remaining_counts` 或 `visible_with_own_discards`。
  2. greedy cache key 必須包含影響 ukeire 的 remaining/visible state。
  3. `win_probability` 與 `winning_trials` 共用單一 rollout helper，避免兩份邏輯再度漂移。
  4. 保留 CRN 的 draw stream，修正只改 policy accounting。
- **風險**：cache 命中率下降、runtime 上升、所有 MC snapshot 可能變動。
- **驗收條件**：
  - 將 review script 找到的固定 seed/state 轉成 regression test，static 與正確 dynamic choice 的差異被消除。
  - 每 trial 驗證 `hand + visible + remaining + opponents/dead assumptions` 不超過物理四張。
  - `win_probability` 與從 `winning_trials` 聚合出的 p_win 完全一致。
  - 報告修正前後 30 個代表局面的 p_win/ranking flip 與 runtime。

## MJ-004 — 統一注入 calibration 並回報 fallback 狀態

- **優先級**：P0
- **狀態**：CONFIRMED
- **問題描述**：stateless EV API 會載入 committed table，但 quiz、endgame、trainer discard/call/kong rank 沒傳 calibration，實際走 fallback；產品文字卻把機率概括為 self-play calibrated。
- **涉及檔案與位置**：
  - `server/api.py:104-107,492-516`
  - `taimahjong/quiz.py:338-353,400-417`
  - `taimahjong/trainer.py:397-452`
  - `taimahjong/ev.py:241-261`
  - `server/static/js/main.js:122-126`
- **建議修改方案**：
  1. 建立明確 `CalibrationProvider`/analysis context，由 API/CLI composition root 載入。
  2. quiz/trainer 的 cache key 納入 calibration version/hash。
  3. 每個 EV response 回 `calibration_id`、`domain=bot`、`fallback_used`。
  4. 若 table 不存在，UI 顯示 heuristic fallback，而非仍稱校準。
- **風險**：接表後題目 ranking 與 verdict 會改；若 cache 未含 version 會回舊結果。
- **驗收條件**：
  - monkeypatch 一個極端 calibration 後，stateless EV、quiz 與 trainer 同一候選的 risk 同方向改變。
  - table missing 時三條路徑都一致 fallback 且 response 明示。
  - 同 seed + 同 calibration hash 可重現；換 hash cache 不共用。

## MJ-005 — 移除或嚴格限定 GTO／最佳解宣稱

- **優先級**：P0
- **狀態**：CONFIRMED
- **問題描述**：目前是 deterministic heuristic policies + bot self-play calibration + partial MC EV，沒有均衡求解或 exploitability；UI 卻稱「GTO 最佳解」。
- **涉及檔案與位置**：
  - `README.md:3,9-12,124-127,172-186`
  - `README.en.md:3,11-15,193-208`
  - `server/static/js/main.js:21-25`
  - `server/static/js/quiz.js:1-3,138-143`
  - `taimahjong/selfplay.py:335-399,773-806`
- **建議修改方案**：
  1. 立即將文字改為「本模型的估計最佳／heuristic EV 建議」。
  2. 在 README 加 methodology card：outcomes、未建模項、calibration domain、sampling uncertainty。
  3. 只有未來具備 formal game abstraction、best response/exploitability 與可重現研究結果後才恢復 GTO 字樣。
- **風險**：品牌名稱可能受影響，但保留錯誤宣稱的信任風險更高。
- **驗收條件**：
  - UI/README/metadata 不再無條件使用 GTO、理論最佳或「所有機率已校準」。
  - 每個建議頁可看到 self-draw-only、bot-domain、MC/heuristic 範圍。
  - 文案 review checklist 有模型工程 owner 簽核。

## MJ-006 — 建立完整 outcome EV 規格與 reference evaluator

- **優先級**：P1
- **狀態**：CONFIRMED
- **問題描述**：目前 attack 只計自己自摸；他家先胡只折 survival，不扣自摸支付；future discard deal-in 與自己 ron 都缺失，不能稱完整籌碼 EV。
- **涉及檔案與位置**：
  - `taimahjong/ev.py:96-132,147-218,264-331`
  - `taimahjong/simulate.py:40-228`
  - `docs/ui-plan.md:10-12,91-93`
- **建議修改方案**：
  1. 先寫 outcome/payment spec：self tsumo、self ron by target、opponent ron、opponent tsumo、draw。
  2. 建立小牌牆 exact evaluator 作 oracle，不直接替換 production model。
  3. 以代表 corpus 比較 current approximation 與 oracle，再逐項加入 target-specific win、future public state/risk。
- **風險**：狀態空間與運算量大；沒有 oracle 前直接重寫容易引入更深錯誤。
- **驗收條件**：
  - 小牌牆所有 outcome probability 和為 1。
  - 每個 terminal payment 四家守恆，兩 scheme 都正確。
  - 報告 current vs reference 的 absolute EV error、top-1 agreement、ranking inversion。
  - latency 超標時保留 approximate mode 並明確標籤。

## MJ-007 — 將 fold 改成可執行的多巡防守 policy

- **優先級**：P1
- **狀態**：CONFIRMED
- **問題描述**：目前 fold row 等於「最安全真實候選的當張風險 + 0 attack」，數學上不會嚴格打敗該真實候選，也不描述後續巡目如何棄牌。
- **涉及檔案與位置**：
  - `taimahjong/ev.py:324-331`
  - `taimahjong/endgame.py:60-68`
  - `scripts/review_validation.py:205-218`
- **建議修改方案**：
  1. 定義 fold policy（例如每巡最低 conditional loss、現物優先、手牌安全庫存）。
  2. 用與 attack candidates 相同 outcome rollout 評估。
  3. UI 顯示第一張建議及後續原則，不把 pseudo-row 當牌。
- **風險**：防守 policy 仍是 heuristic，需要清楚命名。
- **驗收條件**：
  - 至少一個 crafted late-game state 中 fold 能因未來風險較低而真正優於 push。
  - endgame tag 依 policy EV，不依 list position。
  - fold row 的 action plan 可由 trainer 實際執行。

## MJ-008 — 驗證候選 pruning 不會漏掉 net-EV 最佳牌

- **優先級**：P1
- **狀態**：CONFIRMED
- **問題描述**：production 只算 pure efficiency top-k，加至多兩個更安全候選；其餘牌沒有 net EV，卻輸出「最佳」。
- **涉及檔案與位置**：
  - `taimahjong/ev.py:279-317`
  - `taimahjong/quiz.py:338-367`
- **建議修改方案**：
  1. 先加入 `exhaustive=True` reference mode，所有合法 discard 共用 CRN。
  2. 對 seeded corpus 計 pruning recall@1、EV regret 與 latency。
  3. 若 recall 未達門檻，改 two-stage confidence-bound screening，而非固定 top-k。
- **風險**：全候選模擬變慢。
- **驗收條件**：
  - corpus 至少含早／中／晚、宣告對手、染手、莊連莊與兩 scheme。
  - production top-1 recall 目標事先定義（建議 ≥99%）且 worst regret 有界。
  - UI 若未 exhaustive，不使用未限定的「全手最佳」。

## MJ-009 — 修正 kong 教學 EV 的立即和牌與槓上開花

- **優先級**：P1
- **狀態**：CONFIRMED
- **問題描述**：trainer 實際 replacement draw 可以立即和且加槓上開花，但 `_kong_option_ev` 一律進 `_best_discard_ev`，漏掉 terminal win 與 +1 台。
- **涉及檔案與位置**：
  - `taimahjong/trainer.py:490-512,548-569,642-672`
  - `taimahjong/scoring.py:55-60`
- **建議修改方案**：
  1. replacement 後先檢查 `shanten == -1`。
  2. terminal branch 用含 kong state、`kong_bloom=True`、正確 scheme 的 score/payment。
  3. 非 terminal branch 再評估 post-discard。
  4. 把「搶槓風險」另列 outcome，不與 replacement 平均混在一起。
- **風險**：槓 decision ranking 變動；dead-wall posterior 仍是近似。
- **驗收條件**：
  - crafted only-winning-replacement case 的 kong EV 包含正確 win value 與 +1 台。
  - 兩 scheme 的數值有 closed-form test。
  - grading 與實際 trainer settlement 對同一 forced path 一致。

## MJ-010 — 改善 calibration 的 OOS 評估、平滑與 provenance

- **優先級**：P1
- **狀態**：CONFIRMED
- **問題描述**：`0-1` danger bucket 目前 0/31,883，lookup 精確回 0；table 沒有 holdout 指標／CI；`ev_aware` 重建時會讀舊 committed table，metadata 未記 source hash。
- **涉及檔案與位置**：
  - `taimahjong/calibration.py:115-167,215-251`
  - `taimahjong/selfplay.py:321-369`
  - `taimahjong/__main__.py:174-189`
  - `data/calibration.json:3-304,306-635`
- **建議修改方案**：
  1. train/validation seed split，保存 Brier、log loss、ECE/reliability bins。
  2. 對 binomial probability 使用有文件的 Beta prior/credible interval。
  3. metadata 加 commit、Python、policy config、seed ranges、source calibration SHA-256。
  4. bootstrap mode 明確指定 `--source-calibration none|path`。
- **風險**：平滑後低 danger risk 不再為 0，會改 EV 與 bot data distribution。
- **驗收條件**：
  - 任何有限樣本 bucket 的 teaching risk 不回不帶說明的絕對 0/1。
  - holdout metrics 與 95% interval 寫入 artifact。
  - 同 code/config/source hash/seeds 產物 byte-reproducible 或數值等價。

## MJ-011 — 為 MC 排名與實驗輸出不確定性

- **優先級**：P1
- **狀態**：CONFIRMED
- **問題描述**：UI 只顯示點估計；kong/streak 文件沒有 paired CI；chunked head-to-head 輸出不足以合併 SE。
- **涉及檔案與位置**：
  - `taimahjong/selfplay.py:773-806`
  - `scripts/head_to_head.py:14-27`
  - `docs/experiments.md:56-97,115-149`
  - `taimahjong/ev.py:49-72`
  - `server/static/js/feedback.js`
- **建議修改方案**：
  1. EV trial 保存 win count、value sum/sumsq，候選 paired delta 保存 moments。
  2. response 加 SE/CI 與 top1-top2 paired CI。
  3. 實驗腳本輸出 per-game differences 或 n/sum/sumsq。
  4. 用 CI 跨 0 與 effect-size 門檻決定 wording。
- **風險**：conditional hand value 與 stopping/selection 使簡單常態 CI 可能偏；必要時 bootstrap。
- **驗收條件**：
  - chunk merge 後 mean/SE 與 single run 相同。
  - docs 所有「明顯」「提升 X%」旁都有 n 與 CI。
  - 邊界題若 top gap CI 含 0，標示 uncertain/marginal。

## MJ-012 — 限制 expensive API 輸入並隔離 CPU 工作

- **優先級**：P1
- **狀態**：CONFIRMED
- **問題描述**：`sims` 沒上限，CPU-heavy 同步 endpoint 可被單一 request 長時間佔用；trainer/quiz refinement 也在 request 內完成。
- **涉及檔案與位置**：
  - `server/api.py:464-475,492-525`
  - `taimahjong/quiz.py:400-425`
  - `taimahjong/trainer.py:515-569`
- **建議修改方案**：
  1. Pydantic 設定 `sims/turns/wall_remaining` 合理 bounds。
  2. 設 request timeout/budget；高成本 analysis 走 bounded worker pool/job。
  3. cache 以完整 config/calibration key，並限制 memory。
- **風險**：過低 bounds 會阻擋研究用途；可分 public API 與 offline CLI。
- **驗收條件**：
  - 超界 payload 在進 engine 前 422。
  - 兩個一般請求不會被一個超大分析無限阻塞。
  - 有 p50/p95 latency 與 peak RSS benchmark。

## MJ-013 — 補齊 score context 與 kong API 驗證

- **優先級**：P1
- **狀態**：CONFIRMED
- **問題描述**：API 可計不可能的天地胡／莊家 context，也無法輸入核心支援的 kongs、kong_bloom、robbed_kong。
- **涉及檔案與位置**：
  - `taimahjong/scoring.py:100-139,322-387`
  - `server/api.py:478-548`
  - `server/static/js/tools.js:122-217`
- **建議修改方案**：
  1. 在 domain validation 定義 heavenly ⇒ dealer + self/initial，earthly ⇒ nondealer + self/first draw 等 invariants。
  2. ScoreRequest 加 typed kongs 與槓上／搶槓 flags，重用 `_parse_melds` 的物理 copy 檢查。
  3. UI 只顯示相容 flags，或提交時給具體錯誤。
- **風險**：天地胡的 house definition需先由規則 owner 明文化。
- **驗收條件**：
  - 所有互斥／蘊含組合 table-driven。
  - Web score 能重現現有 scoring kong tests。
  - 不可能 context 422，不回虛構台數。

## MJ-014 — 修正吃碰教學中的自摸敘述

- **優先級**：P1
- **狀態**：CONFIRMED
- **問題描述**：lesson 說碰後失去自摸機會／自摸額外台；本專案 scoring 對開門手仍加自摸，只失去門清。
- **涉及檔案與位置**：
  - `server/static/js/lessons.js:58-72`
  - `taimahjong/scoring.py:261-265`
- **建議修改方案**：改為「碰後失去門清台與部分彈性；仍可自摸並取得本桌自摸台」，將速度差、台差、即時棄牌風險分開。
- **風險**：純文字低風險，但例題「通常不碰」仍依 incomplete EV，應避免斷言。
- **驗收條件**：
  - lesson text 與 score engine 相符。
  - 加一個開門自摸 scoring/API example 作文件測試。

## MJ-015 — 在 trainer position 完整呈現 own kongs

- **優先級**：P2
- **狀態**：CONFIRMED
- **問題描述**：domain position 有 `own_kongs`，API payload 漏掉，前端後續局面看不到自己的已宣告槓。
- **涉及檔案與位置**：
  - `server/api.py:118-148`
  - `server/static/js/trainer.js:282-337`
  - `server/static/js/table.js`
- **建議修改方案**：序列化 tile + concealed/open，table component 以四張或槓標記呈現，concealed kong 遵守資訊顯示規則。
- **風險**：暗槓的牌面顯示方式是 UX/house choice。
- **驗收條件**：
  - forced human kong 後下一 decision payload 含 kong。
  - DOM/browser test 確認四張與 open/concealed 標籤。

## MJ-016 — 統一「台數」與「籌碼 EV 單位」

- **優先級**：P2
- **狀態**：CONFIRMED
- **問題描述**：5/2 下 EV 是 chip/value units，不是台數；首頁、score total、trainer feedback 混用「台」「分」「台單位」。
- **涉及檔案與位置**：
  - `server/static/js/main.js:54-62`
  - `server/static/js/tools.js:199-217`
  - `server/static/js/feedback.js`
  - `server/static/js/trainer.js`
- **建議修改方案**：資料層分 `total_tai` 與 `value_units`，UI 固定顯示「X 台；依底 A／台 B = Y 籌碼單位」，stats 依 scheme 分桶。
- **風險**：舊 localStorage stats 無 scheme metadata，需 migration 或清楚標 legacy。
- **驗收條件**：
  - 兩 scheme screenshot/DOM assertions 無將 value units 稱為台。
  - stats 不跨 scheme 聚合，或明確換算後才聚合。

## MJ-017 — 更新過期文件與能力矩陣

- **優先級**：P2
- **狀態**：CONFIRMED
- **問題描述**：scoring/selfplay docstring 與 README 仍稱不支援 kong 或 trainer 不含吃碰，與程式不符。
- **涉及檔案與位置**：
  - `taimahjong/scoring.py:3-9`
  - `taimahjong/selfplay.py` 模組 docstring
  - `README.md:154-156`
  - `README.en.md:170-173`
  - `docs/ui-plan.md`
- **建議修改方案**：建立一張 capability matrix（core/API/CLI/UI/tests），由測試或小腳本驗證 route/flag 存在；同步中英文。
- **風險**：文件容易再次漂移。
- **驗收條件**：
  - kong/call/scheme/calibration/outcome 每項都標 core、API、UI 是否支援。
  - 中英文 scope 一致，CI 檢查關鍵 route/CLI flag。

## MJ-018 — 建立真實瀏覽器可及性與響應式測試

- **優先級**：P2
- **狀態**：UNVERIFIED
- **問題描述**：本次只做 HTTP 與 JS syntax，未在 browser 驗證 mobile、keyboard、screen reader、focus、contrast；這些不是「沒有問題」，而是尚未測。
- **涉及檔案與位置**：
  - `server/static/index.html`
  - `server/static/style.css`
  - `server/static/js/*.js`
- **建議修改方案**：用 Playwright 跑 trainer/quiz/analyze/score happy path 與 invalid input；加 320/768/1280 viewports、keyboard-only、axe。
- **風險**：視覺基準易 flaky；只對結構與關鍵區域做穩定 assertion。
- **驗收條件**：
  - 所有主要操作不用滑鼠可完成。
  - 動態 feedback 有適當 live announcement，tile controls 有可辨識名稱。
  - axe 無 critical/serious；主要 viewport 無橫向溢出。

## MJ-019 — 對完整規則表建立外部 golden corpus

- **優先級**：P2
- **狀態**：UNVERIFIED
- **問題描述**：現有 tests 能證明 implementation 與專案內 expectation 一致，不能證明所有台目值／stacking 符合使用者採用的外部 house table。
- **涉及檔案與位置**：
  - `taimahjong/scoring.py:29-60,219-319`
  - `tests/test_scoring.py`
- **建議修改方案**：由規則 owner 提供版本化 table 與 50–100 個人工裁定和牌（含互斥、最高分解、天地胡、莊連莊、明暗槓）。
- **風險**：不同台灣牌桌規則衝突，不能用「一般標準」含糊處理。
- **驗收條件**：
  - corpus 每例附 rule-table version、expected items/tai/payment。
  - engine 全數通過；任何 house variant 以 config 分開，不在常數上覆蓋。

## MJ-020 — 建立長時間與多 worker 工程基準

- **優先級**：P2
- **狀態**：UNVERIFIED
- **問題描述**：本次未做 sustained concurrency/RSS/session stickiness；in-memory sessions 與 CPU work 在多 worker 下可能產生一致性問題。
- **涉及檔案與位置**：
  - `server/api.py:262-365`
  - `taimahjong/simulate.py`
  - `taimahjong/selfplay.py`
- **建議修改方案**：分 offline research CLI 與 interactive API 的 budget；以 1/2/4 workers 跑固定 workload，量 p50/p95、RSS、timeout、session reload。
- **風險**：benchmark 受機器與 Python 版本影響，需保存環境資訊。
- **驗收條件**：
  - 30 分鐘 workload 無單調 RSS leak。
  - session 在部署拓撲下有明確 sticky/shared-store 策略。
  - latency/SLO 與最大 sims 有文件化數值。

## MJ-021 — 補齊 stateless analyze 的完整桌面狀態

- **優先級**：P1
- **狀態**：CONFIRMED
- **問題描述**：Web `/api/ev/rank` 只能輸入一名對手，`melds` 指該對手；不能輸入自己的副露／槓，也不能同時表達三名對手。核心函式其實支援 opponent list、`melds_declared` 與 scoring context，能力在 API/UI 邊界流失。
- **涉及檔案與位置**：
  - `server/api.py:464-516`
  - `server/static/js/tools.js:62-120`
  - `taimahjong/ev.py:264-278`
- **建議修改方案**：
  1. 定義 typed `TableStateRequest`：own concealed/melds/kongs/river、三名 opponents、wall/dead state、seat/dealer/streak。
  2. server 從 typed state 只建立一次 public counts，分清 wall accounting 與 danger visible。
  3. UI 先提供簡易一對手模式，再以 advanced editor 支援完整三家，避免一次塞滿表單。
- **風險**：狀態 contract 較大，physical-copy validation 與 seat relationship 容易出錯；應先完成 MJ-002 的 typed tile accounting。
- **驗收條件**：
  - 自家有吃／碰／暗槓／明槓時，hand size、declared set count 與 win scoring 正確。
  - 0/1/3 opponents 均有 API tests；三家各自 dealer/streak/river/meld 不串位。
  - 完整 state 的 public counts 與 selfplay `DecisionSnapshot` 相同。

---

# 建議交付批次

1. **批次 A（correctness baseline）**：MJ-001、002、003、004、005。
2. **批次 B（EV reference，不直接大改 production）**：MJ-006、007、008、011。
3. **批次 C（槓、校準、API 安全）**：MJ-009、010、012、013、014。
4. **批次 D（UI/文件/外部驗證）**：MJ-015–021。

每個批次完成前都應執行：

```bash
python3 -m pytest tests/ -q
python3 scripts/review_validation.py
for file in server/static/js/*.js; do node --check "$file"; done
```

若修改 API/UI，再啟動 Uvicorn 跑 score、ukeire、EV、quiz、trainer 的 HTTP/browser E2E。大型 EV 模型替換必須先完成 MJ-006 的 reference corpus，不應直接覆蓋現有模型。
