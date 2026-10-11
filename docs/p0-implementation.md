# P0 實作與剩餘發布阻擋

日期：2026-10-11（Asia/Taipei）。基準：`7ab74bcb1566e9c8aaa896db24442c58cc123e64`。

**服務端防護與牌局生命週期已實作；模型仍有一項既有 gate 不通過，不能標記為已可公開發布。** 未調高任何統計門檻，未改流局／跨局 EV 定義，未部署正式環境。

## 已實作

- `server/limits.py`：最多 2 個同時 POST、無等待佇列、每 IP 60 次／分鐘、16 KiB body、5 秒 body 接收上限、最多 4096 個 IP 計數器。超載回 503、頻率超限回 429，附 Retry-After。健康檢查免除運算與頻率限制。
- `taimahjong/budget.py` 與引擎 checkpoints：每個 POST 共用 60 秒運算期限，在 worker 端停止工作，回 504。瀏覽器中斷不會提早釋放仍在工作的名額。採協作式中止，並非 OS 強制終止程序。
- `server/api.py`：建立前保留名額，容量滿時拒絕新局，保留現有牌局；30 分鐘閒置 TTL，運算中的局不被淘汰；完成後關閉 generator，結果獨立保留最多 5 分鐘且數量有上限；支援 DELETE 釋放。相同牌局忙碌時回 409，避免佔住更多 worker 等 lock。
- `server/lifecycle.py`：同一路徑的第二個程序啟動失敗。此版仍限制單 instance；未做跨重啟持久化。
- 前端：暫時斷線／503／409 保留 session；404 提示重開；act 回應遺失或逾時先讀最新 step，不盲目重送；以 session/step 去除重複計分；加入 75 秒等待期限。
- CI：新增 opt-in Chromium 恢復流程 job。新增容量、逾時、取消、並行建局、到期、失效、計分恢復等回歸測試。操作與環境變數見 [beta-operations.md](beta-operations.md)。

## 慢速測試：修正與仍未通過部分

### 對稱性接線修正

`tests/test_symmetry.py` 的兩項測試原本在 `_calibrated_ron()` 呼叫處 TypeError，且 actor 的抽樣分布仍使用舊 lookup 方式。現在 actor/opponent 使用相同校準 tenpai rate、lookup turn，以及 production 建立的 `world.ron_value_hands`。

命令：`python -m pytest -q -m slow tests/test_symmetry.py`。結果：**2 passed in 51.22s**。保留 `BIAS_TOLERANCE=0.5` 與 `MIN_ACTOR_WIN_SHARE=0.70`。

### Best-response 工具修正

1. `production_rank_policy` 知道可見的剩餘牌牆長度，卻未傳給 `ev_rank`，原本 ≤3 張的局面可能模擬到 4 張，且不能正確套用最後活牌條件。現在透過 `WinValueContext.wall_remaining` 傳遞；沒有透露隱藏牌內容。
2. `_analyse_opening` 沒有把最後活牌與傳入的家規帶入結算，已補上。新增 8 個短牌牆局面的所有合法棄牌對照，直接與獨立 `reference_ev.evaluate_candidate` 的精確 payment 比對。

固定 **26 cases、seed=1、rank sims=200、fit/holdout 各 60 worlds** 的分段重測：

| 版本 | in-sample 平均 | clairvoyant 平均 | held-out 平均 |
| --- | ---: | ---: | ---: |
| review 基準 | 0.853178419 | 1.370219017 | 0.058760684 |
| 僅修已知牌牆長度 | 0.738434829 | 1.255475427 | 0.096260684 |
| 再修 oracle 最後活牌／家規傳遞 | 0.744070513 | 1.293135684 | 0.098344017 |

既有 gate 保留：in-sample `0.1…0.8`，clairvoyant `≤1.0`，holdout `−0.6…0.6`。**最終仍是 clairvoyant 1.293135684 > 1.0 未通過**；其他兩條符合，但這不是放行理由。

最高 clairvoyant gap 的局面集中於多家宣告與連莊：

| 局面 | clairvoyant gap | held-out gap |
| --- | ---: | ---: |
| `self-ron-tenpai-dealer-streak2-5-2-deep-4-threat-multiple` | 8.095833 | 1.454167 |
| `opponent-tsumo-tenpai-nondealer-streak2-5-2-deep-4-threat-multiple` | 6.780556 | 1.397222 |
| `opponent-tsumo-tenpai-dealer-streak2-3-1-deep-4-threat-multiple` | 4.140278 | 0.737500 |

clairvoyant 允許後續動作使用隱藏資訊，是上界，不是可實現的真人策略收益；holdout 是另一個不同估計量。這次沒有把上界超標直接解讀成真人表現退步，也沒有據此改寫 production 策略。下一步應針對上述局面比較校準資料版本、root 選擇與後續策略，並檢查 production marginal RON 模型與 physical-world oracle 的評估差異；證據不足前保留發布 gate。

重現命令：

```bash
python scripts/production_rank_exploitability.py --holdout --rank-sims 200 --sims 60 --seed 1
python -m pytest -q -m slow tests/test_best_response.py::test_corpus_exploitability_at_a_reportable_budget
```

本次完整重跑的是上面的 report 計算，並按原測試三個門檻檢查其均值；沒有額外重跑一次相同的昂貴 pytest corpus test，也沒有宣稱完整 slow suite 通過。

## 服務驗證

- `python -m pytest -q -m "not slow" --durations=10`：**627 passed, 4 skipped, 19 deselected**，118.05 秒。4 項 skipped 為 opt-in 瀏覽器測試，19 項 deselected 為 slow。
- 定向 API／容量／聲明測試首輪 **75 passed**；後續補上的取消與並行預約測試已包含在上面的 627 項。
- 短牌牆精確 payment 與 root context 接線定向檢查 **10 passed**；`node --check` 檢查三個修改的 JS 模組通過；`git diff --check` 通過。
- Python 3.12，本機 ASGI 正式預算探測：`python scripts/benchmark_api_capacity.py --in-process`。使用 `/api/ev/rank` 預設 sims/turns、固定手牌 `123m123p123s11122233z`。

| 批次 | 成功／拒絕 | 成功請求耗時 | health 最慢 |
| --- | --- | --- | ---: |
| 冷機 1 並行 | 1×200 | 17.87 秒 | 0.421 秒 |
| 暖機 1 並行 | 1×200 | 9.95 秒 | 0.569 秒 |
| 5 並行 | 2×200、3×503 | 15.84–15.92 秒 | 0.848 秒 |
| 10 並行 | 2×200、8×503 | 14.52 秒 | 0.207 秒 |

所有探測的 health 為 200；超載立即拒絕，不累積工作佇列。數字只描述本次環境與單一牌型；還沒有目標主機的 p95/RSS／長時間穩定性證據，成功計算也仍需約 10–18 秒。

## 尚未完成的發布驗收

- 上述模型 clairvoyant gate 仍失敗。
- Chromium 安裝下載得到不完整 ZIP，未能在本機執行瀏覽器 E2E；已接 CI，但不能把待跑的 CI 當成通過證據。
- 本機獨立工具呼叫間的 TCP 探測遇 connection refused，因此容量數據採 ASGI transport；未驗證 uvicorn／反向代理／HTTPS。
- 未量測目標部署 CPU/RAM 配額、持續流量及多樣牌型；未做跨重啟續局。現階段可 review、可繼續內測，不能宣稱 P0 已全部清除。
