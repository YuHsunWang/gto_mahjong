# 公開上線準備度 review

> 本文件記錄首次 review 的狀態。後續修正與剩餘發布阻擋請看
> [P0 實作紀錄](p0-implementation.md)。

日期：2026-10-11（Asia/Taipei）  
基準：`main` / `7ab74bcb1566e9c8aaa896db24442c58cc123e64`

## 結論與範圍

已有完整的訓練流程、模型邊界說明和大量引擎測試，但目前仍是單機 Web 原型；不建議直接開放不受控的公開流量。先完成 P0，再以有容量限制的 Web beta 上線。此 review 以 FastAPI 網站為目標；沒有評估 App Store / Google Play 送審，repository 也沒有原生 App 打包流程。

本次檢視 API、前端狀態與錯誤處理、CI、依賴、測試及模型聲明。未取得正式環境網址或主機設定，因此「未見部署防護」只指 repository 內沒有證據，不能斷言外部平台未配置。未做公開網站壓測或真機驗收。

## P0：公開 beta 前解決

### 1. 慢速 CI 已紅燈，發布驗證鏈不完整

證據：[2026-10-10 CI run](https://github.com/YuHsunWang/gto_mahjong/actions/runs/38041763922)。同一 SHA 的 Python 3.11、3.13 fast jobs 通過；slow job 為 **3 failed / 16 passed / 601 deselected**。最近 10/8、10/9、10/10 三次 schedule 均為 failure。

- `tests/test_symmetry.py:166` 仍以兩個參數呼叫 `_calibrated_ron`；`taimahjong/ev.py:1295` 現在要求第三個 `ron_value_hands`。兩個對稱性測試因此在真正驗證模型前就 TypeError。應與 production 一致接入 `world.ron_value_hands`，再檢查統計結果；不能視為模型已通過對稱性驗證。
- `tests/test_best_response.py:482` 的 mean constrained exploitability 為 **0.8531784188034188**，高於上限 **0.8**。需要歸因模型、語料、預算與 baseline 變化，不能直接提高上限。這是回歸警報，不等於已證明真人牌局表現有特定程度的退步。

驗收：修復後同一 release SHA 的 fast 與 slow CI 全數通過；若調整基準，附上原因與可重現比較數據。

### 2. CPU 工作缺少公開流量下的容量控制

證據：`server/api.py:393–434,560–575,762–840` 為同步出題／模擬；`EvRankRequest` 允許 `sims=5000`、`turns=24`、`exhaustive=true`。repository 內未見 rate limit、有限工作佇列或運算 deadline。雖有單次 sims 上限，仍未限制同時運算總量；任意新 seed 也可避開題目快取。`tests/test_api.py:17–22` 刻意降低模擬預算，不能當作實際回應速度證據。

處理方向：限制來源請求頻率、全域並行數與佇列容量；限制 body/string 大小；耗時工作放可限制資源的 worker。超載回應 429/503，並設定真正作用於工作端的時間／運算預算。單純在前端 abort fetch 或把 def 改成 async def 都不會解決 CPU 工作量。

驗收：在目標機器用正式預算量測 cold/warm p50/p95、CPU、RSS、錯誤率；1/5/10 並行是建議起始測試矩陣，並非已測得的承載量。測試超載時仍能操作輕量健康檢查，且佇列與記憶體不會持續增長。

### 3. 牌局生命週期無法支援一般多 worker 部署

證據：`server/api.py:437–464,551–557` 使用程序內 `OrderedDict`，最多 64 個 session，超過直接淘汰最舊者；session 含 live generator。不同 worker 各有自己的字典，請求被分配至別的 worker 會 404，重啟也會丟局。第 65 個 session 可淘汰尚未完成的第 1 局，不是「第 65 個同時在線使用者」才發生。

短期 beta：明確限制單 worker／單 instance、設定 admission 與 session TTL、完成後釋放、容量滿時拒絕新局而非無聲踢掉進行中牌局，並提供清楚的失效重開流程。長期：把 generator 狀態轉為可序列化的局面或版本化事件重播，再處理共用儲存與一致性；只加 Redis 不會自動解決 generator。

驗收：覆蓋容量滿、閒置到期、程序重啟、重複 act、回應遺失與 stale step。現有 lock / step=409 防重機制是有用的基礎。

## P1：對外上線配套

| 方向 | 現況與具體補項 | 驗收 |
| --- | --- | --- |
| 可重現部署 | 僅見本機 uvicorn 指令；未見 Dockerfile、部署 manifest 或依賴 lock。補一條可重現的部署路徑、鎖定依賴與版本、HTTPS／代理設定及回滾步驟。 | 乾淨環境部署同一版本，首頁、靜態 JS、API 與資料載入 smoke test 通過，演練回滾。 |
| readiness 與監控 | `/api/health` 永遠回 status ok，校準資料 lazy-load；不會證明模型資料可用。補 readiness、校準 hash/fallback 可觀測性、request id、耗時、錯誤及資源告警。 | 校準缺失或損毀時依明確發布政策阻止 readiness 或呈現可見降級；可定位耗時請求。 |
| 前端失敗恢復 | `server/static/js/api.js:11–29` 無 timeout；`trainer.js:64–78` resume 遇任何錯誤都清 session id；`:97–107` 只有 409 自動 resync，404 後會回到失效牌局等待狀態。 | 區分 transient network/5xx 與真正失效；暫時斷網保留 id、可重試；404 可重開；超時後以 GET 確認 act 是否已完成。 |
| 瀏覽器 CI | 有 `scripts/check_phone_layout.py` 與 screenshot 證據，但 `.github/workflows/tests.yml` 沒有瀏覽器 job，requirements-dev 也沒有 Playwright。 | 安裝可重現瀏覽器依賴，CI 跑出題→作答→回饋、整局續玩、切方案及 320/375/390px；加入 404/409/503/斷網情境。 |
| 使用者資訊 | 模型限制已說明良好，紀錄存 localStorage；補使用中的規則範圍、版本、資料保存／清除方式與問題回報入口。 | 新使用者能知道不含花牌／特殊牌型、沒有雲端同步、清除瀏覽器資料會失去紀錄；完成首次訓練流程。 |

## 後續產品方向，不應擋住有邊界的 beta

- 定位先維持「台灣十六張麻將 heuristic EV 訓練器」。不需要先完成完整賽局均衡求解才能上線，也不能以目前的研究結果宣稱已完成。
- 題庫預生成／預熱與按版本快取，可降低即時出題成本；仍須保留方案與 calibration identity，避免混用模型版本。
- 若目標是日常台灣牌桌，安排花牌、特殊牌型及更多家規；目前可先清楚標示支援範圍。
- 真人牌譜或專家盲評用於擴大外部效度。現有小牌牆精確參考與 bot calibration 是有價值的工程驗證，不能外推成真人整局準確率。
- 帳號、跨裝置同步、付費與原生 App 可待 beta 使用數據確認後做，不是現有匿名 Web 工具的必要前置。

## 建議實作順序

1. 修 slow CI，建立可信的 release SHA。
2. 完成限流／運算容量與單 instance session 生命週期。
3. 補可重現部署、readiness、監控與回滾。
4. 修前端恢復流程，接上瀏覽器 CI，做真機與正式預算壓測。
5. 有容量限制的 beta 收集完成率、等待時間、錯誤率與回饋，再決定擴容及新功能。

## 本次變更

僅補強根目錄 `AGENTS.md` 與新增此 review；未修 production 程式、未部署、未修改遠端 main。AGENTS 保留原本資料目錄、聲明、快速測試與 commit 規則，新增 release gates、slow callers、統計門檻、session、運算限制及瀏覽器驗證要求。

## 驗證紀錄

- `.venv/bin/python -m pytest -q tests/test_claims.py`：**10 passed in 0.05s**。
- `git diff --check`：通過。
- 本機以 `_store_session` 放入 65 個輕量替身 session：容器剩 64 個；TestClient GET 最舊 session 為 **404**。此為儲存／淘汰路徑重現，未宣稱實際執行了 65 局模擬。
- 以 `inspect.signature(_calibrated_ron).bind(None, 0)` 重現缺少 `ron_value_hands` 的 TypeError；完整 slow failure 以以上 GitHub CI log 為證。
- 本機曾啟動完整 fast suite，但未完成即中止；**不宣稱本機全套通過**。Python 3.11 / 3.13 fast 通過的依據是上述同 SHA 的 GitHub CI；本機為 Python 3.12。
- 未執行 slow suite、瀏覽器 E2E、正式預算負載測試或部署驗收。以上容量與延遲驗收項目都是待辦，不是實測保證。
