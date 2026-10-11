# 單程序 beta 操作與驗收

這一版支援 **Linux、單 API worker、單 instance**。牌局仍是記憶體中的 Python generator，沒有跨重啟持久化；重啟後前端會提示重開。不要用多 replica 或自動橫向擴容。程序鎖會拒絕同一路徑下的第二個 worker，但不能偵測使用各自磁碟的其他容器。

## 啟動

```bash
python -m pip install -r requirements.txt
python -m uvicorn server.api:app --host 127.0.0.1 --port 8000 --workers 1
```

正式代理應配置 HTTPS、body/header 限制、連線 timeout 與主機 CPU/RAM 配額。若需轉交 client IP，僅信任自己代理的 IP，且代理必須覆寫外來的 forwarding headers；不要把 `--forwarded-allow-ips` 設為 `*`。若 client IP 都落在同一代理 IP，使用者會共用一份 rate limit。

| 設定 | 預設 | 行為 |
| --- | --- | --- |
| `MJ_MAX_COMPUTE` | 2 | 同時受理的 POST 請求上限，包含讀取 body；沒有等待佇列，滿載回 503。 |
| `MJ_REQUESTS_PER_MINUTE` | 60 | 每來源 IP 的 API 請求固定 60 秒視窗上限；超出回 429，health 不計入。 |
| `MJ_COMPUTE_SECONDS` | 60 | 整個 POST 共用的 worker-side cooperative deadline；不是每個子函式各重置一次。 |
| `MJ_MAX_SESSIONS` | 64 | 進行中牌局加尚未完成的建立預約上限；滿載回 503，不淘汰仍在玩的牌局。 |
| `MJ_SESSION_TTL_SECONDS` | 1800 | 進行中牌局閒置到期時間；正在運算的牌局不會被清掉。 |
| `MJ_PROCESS_LOCK` | `artifacts/work/api.lock` | 同一 instance 的所有 worker 必須使用同一個可寫路徑。 |

其他固定界線：POST body 16 KiB、body 接收 5 秒、模型字串 2048 字元、最多 4096 個未過期 IP 計數器。完成牌局立即關閉 generator 並釋放進行中名額；結果最多保留 5 分鐘、最多 `MJ_MAX_SESSIONS` 份，供回應遺失後恢復。`DELETE /api/trainer/{id}` 可提早釋放牌局。

## 逾時與恢復

引擎在抽樣、向聽計算、rollout 巡目、出題搜尋與對局迴圈檢查 deadline，逾時拋出 504，工作停止後才釋放並行名額。這是協作式期限，並非作業系統強制 kill；新增昂貴迴圈時必須加入 checkpoint。外部 C 擴充卡死、記憶體上限仍需由主機／容器管理。

若逾時發生在評分階段，未送進 generator 的動作可以重試；若 generator 推進中拋錯，該局失效，後續讀取回 404。前端對回應遺失、5xx、409 先 GET 確認最新 step，不自動重送 act。短暫錯誤保留 session id，只有 404 才清掉；同一 session/step 的紀錄不重複累計。瀏覽器 75 秒 timeout 只管理等待，不是服務端運算期限。

## 驗證

```bash
python -m pytest -q -m "not slow"
python -m pytest -q -m slow
python -m pip install -r requirements-browser.txt
python -m playwright install chromium
MJ_BROWSER_TESTS=1 python -m pytest -q tests/test_browser_recovery.py
```

slow suite 是發布 gate；日常修改仍遵循 AGENTS 的 targeted/fast 流程。Chromium 測試使用縮小的模擬預算，驗證 404/409/503 恢復、已提交但回應遺失的出牌、重整不重複計分，不能拿來當效能數據。

針對自己啟動的本機服務執行正式預算探測：

```bash
python scripts/benchmark_api_capacity.py --url http://127.0.0.1:8000
```

若環境不能連接本機 TCP，可使用 `--in-process` 經 TestClient 直接跑 ASGI；這仍會跑正式引擎與 admission middleware，但不驗證 uvicorn、代理或網路。

依序跑 1/1/5/10 並行；第一批為冷機、第二批觀察暖機，其餘驗證超載回應與 health。程式不覆寫 sims/turns，結果包含成功／拒絕／逾時狀態。這只是固定一手牌的有限探測，不等於任意牌型或長時間流量的 SLO；還需在目標機器量測多種局面、p95、RSS 及成本。

目前仍應以 `docs/p0-implementation.md` 的實測與未通過項目判斷是否可發布；不能只因容量測試通過便略過模型 gate。
