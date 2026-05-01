# Sprint 1.8.1.2 — 真修 test_market_route_spot_fail_falls_back_to_kline

**报告日期:** 2026-05-01
**Sprint 范围:** 修 1 个环境敏感测试,纠正 1.8.1.1 段 1 "实测已通过(无操作)" 的错误结论
**状态:** 完成,1 commit 已 push origin/main(7729906)
**前置:** Sprint 1.8.1.1(commit ddd2b93)

---

## 0. 红线自查 — 本报告的"实测"说明

本 sprint 所有 PASS / FAIL 数据均为**当次任务**实际跑出的输出,逐条粘到
本报告 §1 + §3。不再凭 1.8.1.1 段 1 那种"上一次的记忆"。

---

## 1. 5 次诊断 — 是 flaky 还是稳定 fail?

### 1.1 Pre-fix 5 次输出(仅运行该测试,本地 Mac)

```
$ for i in 1 2 3 4 5; do uv run pytest tests/test_market_route_spot_priority.py::test_spot_fail_falls_back_to_kline -v 2>&1 | tail -3; echo "--- run $i done ---"; done

run 1: ======================== 1 passed, 12 warnings in 4.24s ========================
run 2: ======================== 1 passed, 12 warnings in 2.82s ========================
run 3: ======================== 1 passed, 12 warnings in 2.98s ========================
run 4: ======================== 1 passed, 12 warnings in 2.98s ========================
run 5: ======================== 1 passed, 12 warnings in 3.08s ========================
```

**5/5 在本地 Mac 通过**。但用户 SSH 跑显示 1 fail。

**关键观察**:每次运行 ~3 秒,远超正常 0.4 秒。这是个**红旗信号**——
说明测试在跑过程中**真发起了网络请求**(慢的部分就是 CoinGlass HTTP 调用)。

### 1.2 全套 pytest 在本地 Mac 3 次运行

```
$ for i in 1 2 3; do uv run pytest tests/ 2>&1 | tail -3; done
run 1: ================ 809 passed, 1 skipped, 360 warnings in 12.39s ================
run 2: ================ 809 passed, 1 skipped, 360 warnings in 11.60s ================
run 3: ================ 809 passed, 1 skipped, 360 warnings in 11.38s ================
```

**3/3 本地全通过**,但用户 SSH 1 fail → **环境敏感**(env-specific)。

---

## 2. 根因 — 网络依赖 + 时间硬编码 双重叠加

### 2.1 测试结构

`tests/test_market_route_spot_priority.py:144`(原版):

```python
def test_spot_fail_falls_back_to_kline(client: TestClient, db_path: Path):
    _seed_klines_25h(db_path)        # seed 25 根 1h K 线,最后 ts = 2026-05-01T00:00:00Z
    with patch(
        "src.data.collectors.coinglass.CoinglassCollector.fetch_spot_price_history",
        return_value=[],            # mock spot fail
    ):
        r = client.get("/api/market/btc-price")
    body = r.json()
    assert body["price"] is not None
    assert abs(body["price"] - 72100.0) < 0.1   # K 线最后 close = 72100
```

### 2.2 endpoint 内部行为(`src/api/routes/market.py:217-230`)

```python
# Fallback:1h K 线
rows = _query_latest_1h(conn)
current, h24, d7, ts = _compute_changes(rows)   # current = 72100, ts = 2026-05-01T00:00:00Z

age_min = None
stale = False
if ts is not None:
    age_min = (now - ts).total_seconds() / 60.0   # large(now=2026-05-01 下午)
    if age_min > _STALE_THRESHOLD_KLINE_MIN:      # 30 min
        stale = True

if stale or current is None:
    _try_refresh_from_coinglass(conn)             # 真请求 CoinGlass
    rows = _query_latest_1h(conn)
    current, h24, d7, ts = _compute_changes(rows)
    ...
```

`_try_refresh_from_coinglass(conn)` 真发 HTTP 请求(`src/api/routes/market.py:84`):

```python
coll = CoinglassCollector()
rows = coll.fetch_klines(interval="1h", limit=48) or []
if not rows:
    return
...
BTCKlinesDAO.upsert_klines(conn, klines)
```

### 2.3 双重原因叠加

1. **时间硬编码**:测试种入 K 线最后一根 ts=`2026-05-01T00:00:00Z`(写测试
   时是"今天")。今天 2026-05-01 下午跑测试时,age = 几百分钟 > 30 min
   阈值 → 触发 `_try_refresh_from_coinglass`

2. **网络依赖未 mock**:`_try_refresh_from_coinglass` 调用真实 CoinGlass
   API,会环境敏感:
   - **Mac 本地**:无 OPENAI_API_KEY / 无 CoinGlass 凭据 → silent skip(silently
     warning)→ DB 中 seeded 70000-72100 保留 → 测试碰巧 PASS
   - **Ubuntu 生产服务器**:有 key → 真请求成功 → upsert 实时价
     (BTC ~$95k 之类)→ DB 覆盖 seeded 数据 → re-query 取到实时价
     → `assert abs(body["price"] - 72100.0) < 0.1` FAIL

### 2.4 为什么 isolated 5/5 PASS 但还是错的

isolated 5/5 PASS 不代表代码正确,只代表**当前 env 没 CoinGlass key**。
3 秒运行时间的细节(网络超时)透露了网络调用的存在,但被忽略。

**CC 的过失**:1.8.1.1 段 1 写"实测已通过(无操作)"时,只看 PASS 标签,
没看运行时间,也没注意到网络调用。**违反 §Z 真断言原则**。

---

## 3. 修法 + 10 次验证

### 3.1 修法

`tests/test_market_route_spot_priority.py:144` 加二号 patch:

```python
with patch(
    "src.data.collectors.coinglass.CoinglassCollector.fetch_spot_price_history",
    return_value=[],
), patch(
    "src.api.routes.market._try_refresh_from_coinglass",
    return_value=None,                  # 新增:让 refresh 无操作
):
    r = client.get("/api/market/btc-price")
```

同步对 `test_spot_exception_falls_back_to_kline`(同 vulnerability)补 patch。

### 3.2 Post-fix 10 次验证

```
$ for i in $(seq 1 10); do uv run pytest tests/test_market_route_spot_priority.py::test_spot_fail_falls_back_to_kline 2>&1 | tail -1; done

======================== 1 passed, 12 warnings in 0.43s ========================
======================== 1 passed, 12 warnings in 0.49s ========================
======================== 1 passed, 12 warnings in 0.45s ========================
======================== 1 passed, 12 warnings in 0.43s ========================
======================== 1 passed, 12 warnings in 0.43s ========================
======================== 1 passed, 12 warnings in 0.44s ========================
======================== 1 passed, 12 warnings in 0.45s ========================
======================== 1 passed, 12 warnings in 0.44s ========================
======================== 1 passed, 12 warnings in 0.44s ========================
======================== 1 passed, 12 warnings in 0.44s ========================
```

**10/10 PASS,运行时间从 ~3s 降到 ~0.45s**。

时间从 3s → 0.4s 是关键证据 — 印证网络调用已被消除,测试现在真正在测
"K 线 fallback 路径计算逻辑",而不是在等 HTTP 超时。

### 3.3 全套 pytest

```
$ uv run pytest tests/ 2>&1 | tail -3
================= 809 passed, 1 skipped, 360 warnings in 6.88s =================
```

**809 passed, 0 failed**(全套时间也从 12s 降到 7s,因为这两个测试现在
不再等网络)。

---

## 4. commit diff

```diff
@@ -141,12 +141,24 @@
 def test_spot_fail_falls_back_to_kline(client: TestClient, db_path: Path):
-    """spot fetch 返回空 → fallback 到 K 线路径,source 含 kline_1h。"""
+    """spot fetch 返回空 → fallback 到 K 线路径,source 含 kline_1h。
+
+    Sprint 1.8.1.2:同时 mock _try_refresh_from_coinglass。原因:测试种入
+    K 线最后一根 ts=2026-05-01T00:00:00Z(写测试时是"今天"),age 超过
+    30 分钟阈值后会触发 endpoint 的 _try_refresh_from_coinglass(),如生产
+    环境有 CoinGlass API key,会真请求并把 seeded 70000-72100 覆盖成实时价。
+    Mac 本地无 key → silent skip → 测试碰巧 PASS;
+    生产 Ubuntu 服务器有 key → 真覆盖 → 断言 fail。
+    本次 patch 让 refresh 无操作,环境无关。
+    """
     _seed_klines_25h(db_path)
     with patch(
         "src.data.collectors.coinglass.CoinglassCollector.fetch_spot_price_history",
         return_value=[],
+    ), patch(
+        "src.api.routes.market._try_refresh_from_coinglass",
+        return_value=None,
     ):

 def test_spot_exception_falls_back_to_kline(client: TestClient, db_path: Path):
+    """... Sprint 1.8.1.2:同样 mock _try_refresh_from_coinglass(同 reasoning)。"""
     ...
     with patch(
         "src.data.collectors.coinglass.CoinglassCollector.fetch_spot_price_history",
         side_effect=RuntimeError("network down"),
+    ), patch(
+        "src.api.routes.market._try_refresh_from_coinglass",
+        return_value=None,
     ):
```

---

## 5. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ tests/ai/ 58/58 + tests/ 809 passed,目标测试 10/10 PASS |
| GitHub push(commit 7729906) | ✅ push origin/main |
| 服务器 git pull | ⏳ 待用户 SSH(需求是回归这个 fail) |
| 服务器 systemctl restart | N/A(只改 tests/,无 src/ Python module 改动) |
| 生产 DB 迁移 / 清污 | N/A |

---

## 6. 用户 SSH 验证脚本(完整可复制)

```bash
ssh ubuntu@124.222.89.86
cd /home/ubuntu/btc_swing_system
git pull origin main

# 目标测试 10 次必须全 pass
for i in $(seq 1 10); do
  .venv/bin/pytest tests/test_market_route_spot_priority.py::test_spot_fail_falls_back_to_kline 2>&1 | tail -1
done
# 期望:10 行全是 "1 passed",运行时间 < 1s/次

# pytest 全套必须 0 fail
.venv/bin/pytest tests/ 2>&1 | tail -3
# 期望:809 passed, 1 skipped, 0 failed
```

---

## 7. 同类风险扫描(主动找其他 flaky / env-sensitive 测试)

### 7.1 调用真 CoinGlass class 但可能未 mock 的测试

```bash
$ grep -rln "CoinglassCollector\|fetch_klines\|fetch_spot" tests/ | grep -v __pycache__
tests/test_scheduler_2_7_b_collectors.py
tests/test_sprint_1_6_new_factors.py
tests/test_factor_cards_refresher.py
tests/test_coinglass_funding_aggregated.py
tests/test_coinglass_no_silent_zero.py
tests/test_coinglass_endpoints_contract.py
tests/test_coinglass_spot_price.py
tests/test_market_route_spot_priority.py    ← 本 sprint 已修
tests/test_collector_retry_skip.py
```

8 个候选(本 sprint 修了 1 个)。这些大多数 mock 了 CoinglassCollector,
但需要验证是否还有类似 `_try_refresh_from_coinglass` 这种"endpoint 内部
真实兜底" 路径未 mock。

### 7.2 时间硬编码 2026-04 / 2026-05 的测试

```bash
$ grep -rln "2026-04\|2026-05" tests/ | grep -v __pycache__
tests/test_events_pipeline_integration.py
tests/test_scheduler_2_7_b_collectors.py
tests/test_factor_card_24h_daily.py
tests/test_sprint_1_6_new_factors.py
tests/test_factor_card_emitter.py
tests/test_state_machine.py
tests/test_lth_sth_realized_price_e2e.py
tests/test_dao_inserted_at_utc.py
tests/test_strategy_stream_overlays_latest.py
tests/test_event_listener.py
```

10 个候选。每个都可能在 2026-05-02 / 2026-06-01 等未来日期出现 collateral
fail(因 stale time threshold 触发)。**强烈建议 Sprint 1.10 引入
freezegun**,把所有"看 datetime.now() 的测试"统一固定时间。

### 7.3 直接调用 _try_refresh / _try_fetch / requests / httpx 的测试

```bash
$ grep -rln "_try_refresh\|_try_fetch_spot\|requests.get\|httpx.get" tests/
tests/test_market_route_spot_priority.py    ← 已修
```

只有这一个。其他直接 HTTP 的测试可能用 mock library 已隔离。

### 7.4 修法建议

1. **本 sprint(1.8.1.2)**:只修 1 个明确的 fail。其他候选不动。
2. **Sprint 1.10 / 1.11 时**:做"测试环境无关性"专项扫描:
   - 引入 `freezegun` 库(`pip install freezegun`)
   - 在所有"种 K 线 + 调 endpoint"的测试加 `@freeze_time("2026-05-01T01:00:00Z")`
     decorator,让 stale threshold 测试结果可预测
   - 添加 conftest.py 全局 fixture 自动 mock 所有 `*_try_refresh_*` /
     `*_try_fetch_*` 路径,防止意外网络调用

---

## 8. Sprint 1.8.1.2 commit

```
7729906 Sprint 1.8.1.2: 真修 test_spot_fail_falls_back_to_kline 环境敏感性
```

---

## 9. 总结 + 自我检讨

### 9.1 修复成果

- ✅ 5 次 isolated 诊断 → 都 PASS,但运行时间 3s 是红旗
- ✅ 根因诊断到位:**网络依赖 + 时间硬编码** 双重原因
- ✅ 10 次 post-fix 验证全 PASS,运行时间从 3s → 0.45s(网络消除)
- ✅ pytest tests/ 全套 809 passed, 0 failed

### 9.2 自我检讨(纳入 §X 工程纪律)

1.8.1.1 段 1 说"实测已通过(无操作)"是**错误结论**。当时:
- 看 PASS 标签 → 没看运行时间(3s 是网络调用的红旗)
- 没在当次任务中真跑(凭"上一报告"印象)
- 没考虑环境差异(CoinGlass key 在生产 vs 本地不同)

**纠正后纪律**:每次 sprint 报告里写"PASS / FAIL"必须附**当次任务**
跑出的输出 verbatim。不能凭印象 / 不能引用上一 sprint 数据。

本 sprint 已遵循:§1 5x + §3 10x 输出全部当次跑出,逐字粘报告。
