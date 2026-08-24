# 從「精確 oracle」到「求解均衡」：GTO 一詞要怎麼才用得起

`tests/test_claims.py` 目前擋掉 `gto`、`理論最佳`、`最佳解` 等字。擋的理由不是這些詞本身不能用，
而是**目前還不成立**。這份筆記記錄：差在哪、什麼東西已經到位、以及要補什麼才能講一句有範圍且為真的話。

## 現在缺的是什麼

差距不在算力，而在**沒有任何一家在求最佳反應**。

- 全專案沒有 best response / equilibrium / Nash / CFR / exploitability 的實作
  （`grep -rniE "best.?response|equilibri|nash|cfr|exploitab" taimahjong/ server/` 無結果）。
- `taimahjong/reference_ev.py` 是**精確的終局／結算 oracle**，不是賽局求解器。它自己的 docstring
  講得很清楚：窮舉每一種實際抽牌順序，但**套用單一決定性出牌 policy**，因此它認證的是終局分類、
  結算與 aggregation 機制，不是對手模型的真實性。
- production rollout 的其他三家跑固定 heuristic policy，不會針對你的打法調整。

GTO 要的是一組策略組合，其中沒有任何一家能靠偏離獲利。這個 repo 目前**連「偏離能賺多少」都還沒量**。

## 已經到位、可以直接接手的東西

淺牌牆殘局這一塊的地基其實鋪得比想像中好：

| 已有 | 位置 | 為什麼對求解有用 |
| --- | --- | --- |
| 對抽牌順序的窮舉分支 | `reference_ev.py` 的 `branch()` | 值函數不需要抽樣，直接精確 |
| 精確有理數機率 | `branch(..., Fraction(1))` | 沒有蒙地卡羅誤差，均衡判定不會被雜訊污染 |
| 四家暗手全可見的狀態表示 | `ReferenceState` | 完全資訊子賽局，可以直接做動態規劃 |
| 榮和判定與四家零和結算 | `_ron_claims`、`_settlement` | 終局收益已經是正確的，不必重寫 |
| 26 個分層抽樣的驗收語料 | `MIN_GATE_CASES = 26` | 現成的測試床 |

限制條件也很明確：牌牆最多 4 張、`reference_ev.py:303` 直接 `assert melds_declared == 0`
（子賽局內不含吃碰槓）。

## 三個步驟，以及各自能換到什麼說法

**步驟 1 — 讓 policy 變成自由變數。**
現在出牌 policy 是注入的常數。改成可以對 acting seat 窮舉所有合法策略。狀態空間在 ≤4 張牌牆下
小到可以窮盡，且值函數已經是精確的。
*換到的說法：* 還沒有，這是基礎建設。

**步驟 2 — 算 best response，量 exploitability。**
固定其他三家的現行 policy，對 acting seat 求最佳反應，然後量 production policy 跟它差多少。
*換到的說法：* 「production policy 在 ≤4 張牌牆殘局中的 exploitability 為 X 台」。
**這一步的投報率最高**——它產出一個數字，回答「我的策略被針對能被賺走多少」，而且不需要真的解出
均衡。對量化職缺來說，這個數字比「GTO」三個字有說服力得多。

**步驟 3 — 迭代到近似均衡。**
反覆做 best response 直到收斂，在該受限子賽局內得到均衡策略組合。
*換到的說法：* 「在 ≤N 張牌牆、無鳴牌的殘局子賽局中求解到均衡」——**要連範圍一起講**。

## 就算做完，仍然不能說什麼

- 子賽局 ≠ 完整牌局。中盤 `ev_rank` 可以評估到 24 巡，跟 4 張牌牆的殘局不是同一個問題。
- 不含鳴牌的均衡，不等於含吃碰槓的均衡。
- 均衡策略與**真人**對手無關；bot-domain calibration 的限制照舊。

換句話說，步驟 3 之後可以講的是「在這個明確定義的子賽局裡解出了均衡」，而不是「這是一個 GTO
訓練器」。範圍講清楚的小主張，遠比講不清楚的大主張值錢。

## 解除條件

`tests/test_claims.py` 的守門條件應該逐項解除，不是整包拿掉：真的解出哪個子賽局，就只放行對應
範圍的措辭。

---

## 步驟 2 已完成（2026-08-24）：exploitability 量出來了

`taimahjong/best_response.py` 實作了 acting seat 的 best response 與
exploitability 量測，語料沿用 `reference_ev` 那 26 個 ≤4 張牌牆局面。

### 可以講的一句話

> production rollout policy 在 ≤4 張牌牆、無鳴牌的殘局子賽局中，在 production
> 自身的對手信念模型下，exploitability 為 **0.556 台**（26 局面平均，sims=60），
> clairvoyant 上界 **0.898 台**。26 個局面中有 11 個恰為 0。

範圍要連著講：這不是中盤（`ev_rank` 評到 24 巡）、不含吃碰槓、不是對真人。

### 設計上的兩個決定

**對照組**：acting seat 與三家對手都跑 `_production_discard_policy`，best response
只替換 acting seat。這是 production rollout 實際模擬的組合。

**資訊限制**：兩邊吃同樣的資訊。production 的 rollout policy 平常拿到的是 rollout
的真實剩餘牌牆——那對真人是暗的——所以在這裡 acting seat 自己的決策改吃它的信念池
（4 − 手牌 − 可見 − 已觀察到的棄牌）。少了這一步，被量測的 policy 會看得比 best
response 多，非負不變量就失去意義。

### 一個必須記錄的負面結果：完整 information-set BR 會退化

原計畫的「對整個 policy 求 information-set best response」**在任何負擔得起的樣本數
下都會退化成 clairvoyant**，原因是結構性的而非實作錯誤。

acting seat 在第二次決策時觀測到自己摸的那張加三家各棄的一張，這個觀測太細，兩個
抽樣世界幾乎不可能落進同一個資訊集：

| sims | 資訊集 | 被 >1 個世界抵達 | full 值 | clairvoyant 值 |
|---:|---:|---:|---:|---:|
| 20 | 304 | 0 | 1.762 | 1.762 |
| 100 | 1,631 | 3 | 1.675 | 1.675 |
| 200 | 3,170 | 17 (0.5%) | 1.522 | 1.522 |

資訊集數隨樣本數線性成長，所以加樣本只會讓退化更嚴重，不會改善。這個模式以
`mode="full"` 保留，並由 `test_full_mode_information_sets_are_effectively_singletons`
釘住其退化，避免下一個人把它的數字當成 exploitability。

**繞過的方式**：只優化開局那次決策（`mode="opening"`，預設）。所有抽樣世界依定義
共享開局資訊集，所以沒有退化，而且那正是 `ev_rank` 存在要回答的決策。續打維持
measured policy，兩邊一致。

### 這個數字怎麼用

policy 偏誤 0.56–0.90 台，與 `docs/hidden-world-strata.md` 量到的抽樣雜訊
（sims=2000 時 paired gap 半寬 0.67 台）**同一量級**。沒有一方輾壓另一方，因此：

- 加樣本仍有意義，雜訊還沒被偏誤淹沒；
- 但總誤差有一個約 0.6 台的地板是加樣本跨不過去的，把雜訊壓到遠低於此純屬拋光。

**這個比較要打折**：exploitability 語料是 ≤4 張牌牆殘局，strata 研究是中盤最多 12
巡，兩個不同 regime，屬量級參考而非嚴格對照。

### 解除了哪一條守門

`tests/test_claims.py` 的 `gto`／`理論最佳`／`最佳解` **維持全部封鎖**。本步驟量的是
exploitability，不是均衡；步驟 3（迭代到近似均衡）尚未開始。
