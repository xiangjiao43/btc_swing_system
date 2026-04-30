# Sprint 1.6.1 — 1.6 收尾修复(派生 MVRV + CoinGlass 入库 + 今日门)

**Date:** 2026-04-30
**Branch:** main
**Status:** ✅ 本地完成,30 测试 + commits `5dd4a7d..` + 报告

---

## 一、SSH 实测发现的 3 个问题

1. **派生 MVRV 跳过整批**:1.6 `compute_and_save_derived_mvrv` 找
   `onchain_metrics.btc_price_close` — 该 metric 在生产 onchain 表里**根本不存在**
   (BTC 收盘价唯一来源是 `price_candles` timeframe='1d')。
2. **今日门误 skip 4 个新 fetcher**:`onchain_metrics` 是宽表,
   `_has_today_inserted_in_metric_table` "任意一个 metric 写过即 skip" →
   1.6 新 fetcher (sth_supply / ssr / cdd / hodl_waves) 永远不被调用。
3. **CoinGlass 2 新 metric 入库路径未真测**:fetcher 拉到数据,upsert 行为
   未 e2e 验证。

---

## 二、改动(3 commit + 报告)

| Commit | 任务 | 模块 |
|---|---|---|
| `5dd4a7d` | A | derived_onchain.py:BTC 收盘价改读 price_candles 1d |
| `4a55a9f` | B | jobs.py:细粒度今日门(_onchain_today_complete + _has_today_btc_dominance_or_etf_flow) |
| (本) | C | e2e 验证 + 报告 |

### 任务 A 关键修改

`src/data/collectors/derived_onchain.py`:

```python
# 老 1.6:_load_metric_by_ts(conn, "btc_price_close")  ← 找 onchain_metrics
# 1.6.1:
def _load_btc_close_by_date(conn):
    rows = conn.execute(
        "SELECT open_time_utc, close FROM price_candles "
        "WHERE timeframe = '1d' AND symbol = 'BTCUSDT' AND close IS NOT NULL"
    ).fetchall()
    ...
```

`onchain_metrics` 仍读 `lth_realized_price` / `sth_realized_price`(这两个是
Glassnode 原生)。在 timestamp 上 inner join,任一缺失跳过该日期。

### 任务 B 关键修改

`src/scheduler/jobs.py`:

```python
_ONCHAIN_EXPECTED_METRICS_TODAY = (
    # 老 13 个 fetcher 名
    "mvrv_z_score", "nupl", "lth_supply", ...,
    # 1.6 新 3 个(hodl_waves 用前缀匹配)
    "sth_supply", "ssr", "cdd",
)

def _onchain_today_complete(conn):
    written_today = ...  # SELECT DISTINCT metric_name WHERE captured_at_utc LIKE 'today%'
    # hodl_waves_<bucket> 任一出现 → 视为 'hodl_waves' 已抓
    expected_set = set(_ONCHAIN_EXPECTED_METRICS_TODAY) | {"hodl_waves"}
    return len(expected_set - written_today) == 0
```

`job_collect_onchain` 入口改用 `_onchain_today_complete`(老
`_has_today_inserted_in_metric_table` 保留供其他调用方用)。

`job_collect_klines_daily` 同步加 `_has_today_btc_dominance_or_etf_flow`
双门:1d K 线 + 1.6 CoinGlass 2 新 metric **都今天写过才 skip**。

### 任务 C 关键 e2e 测试

```python
def test_coinglass_btc_dominance_writes_to_derivatives_snapshots():
    # 真 SQLite + 真 DerivativesDAO.upsert_batch
    metrics = [DerivativeMetric(timestamp="2026-04-30T00:00:00Z",
                                 metric_name="btc_dominance",
                                 metric_value=60.36)]
    DerivativesDAO.upsert_batch(conn, metrics)
    # 验证 full_data_json extras 含 btc_dominance(因不在 _DERIVATIVES_WIDE_COLUMNS)
    row = conn.execute("SELECT full_data_json ...").fetchone()
    extras = json.loads(row["full_data_json"])
    assert abs(extras["btc_dominance"] - 60.36) < 0.01
```

---

## 三、测试

### 总计 30 测试(21 个 1.6 老 + 9 个 1.6.1 新)

| 类(1.6.1 新增) | 测试 |
|---|---|
| Task A 派生 MVRV 数据源 | `test_local_computed_mvrv_skips_when_price_candles_empty`(关键反退化) |
| Task B 今日门 | 5 个:expected metrics 含新 fetcher / 仅老 metric 写过返回 False / 全 expected 写过 True / hodl_waves 前缀视为齐 / btc_dom 检测 / 空 derivatives False |
| Task C e2e 写入 | 3 个:btc_dominance 入 full_data_json / etf_flow 入 / job_collect_klines_daily 调用静态字符串校验 |

```
30 passed in 0.55s
```

---

## 四、§X / §Y / §Z 自检

### §X(本 sprint 不删旧代码)
✅ 老 `_has_today_inserted_in_metric_table` 仍保留(供 macro_metrics 用)。
   只新加 `_onchain_today_complete` + `_has_today_btc_dominance_or_etf_flow`。
✅ 老 `_load_metric_by_ts` → 改名 `_load_onchain_metric_by_ts`(更清晰,
   行为不变;仍是 onchain_metrics 表读)。

### §Y
3 个代码 commit + 1 个报告 commit。一次性 push。

### §Z(测试用真值断言)
- `test_local_computed_mvrv_value_correct`:73000/35000 ≈ 2.086 真 SQL select
- `test_coinglass_btc_dominance_writes_to_derivatives_snapshots`:真 SQLite +
  真 DAO.upsert_batch + JSON 解析验证 extras 字段
- `test_onchain_today_complete_returns_false_when_missing`:关键反退化
- 不是 `.called=True` only

---

## 五、部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ 30/30 sprint 1.6+1.6.1 |
| GitHub push(commit hashes:`5dd4a7d..`) | ✅ |
| 服务器 git pull | ❌ 等用户 SSH 执行 |
| 服务器 systemctl restart | ❌ 等用户 SSH 执行 |
| 生产 DB 迁移 / 清污 | N/A |

### 用户 SSH 验收脚本

```bash
ssh ubuntu@124.222.89.86 << 'SSH'
cd /home/ubuntu/btc_swing_system
git pull
sudo systemctl restart btc-strategy.service
sleep 5

# 1. 强制跑一次完整采集
.venv/bin/python -c "
from src.scheduler.jobs import job_collect_onchain, job_collect_klines_daily
print('--- onchain ---')
print(job_collect_onchain())
print('--- klines daily + coinglass new ---')
print(job_collect_klines_daily())
"

# 2. 验证 1.6 全部 onchain 新 metric 真入库
sqlite3 data/btc_strategy.db "
SELECT metric_name, COUNT(*) AS rows, MAX(captured_at_utc) AS latest
FROM onchain_metrics
WHERE metric_name IN ('sth_supply', 'ssr', 'cdd', 'lth_mvrv', 'sth_mvrv')
   OR metric_name LIKE 'hodl_waves%'
GROUP BY metric_name;
"
# 预期:7 个 metric_name,每个 rows ≥ 7
# (sth_supply / ssr / cdd / lth_mvrv / sth_mvrv 各 1 个 +
#  hodl_waves_24h / 1d_1w / 1w_1m / 1m_3m / 3m_6m / 6m_12m / 1y_2y / 2y_3y /
#  3y_5y / 5y_7y / 7y_10y / more_10y 12 个 bucket)

# 3. 验证 CoinGlass 2 新 metric 真入 derivatives_snapshots full_data_json
sqlite3 data/btc_strategy.db "
SELECT captured_at_utc,
       json_extract(full_data_json, '\$.btc_dominance') AS btc_dom,
       json_extract(full_data_json, '\$.etf_flow') AS etf_flow
FROM derivatives_snapshots
WHERE full_data_json LIKE '%btc_dominance%'
   OR full_data_json LIKE '%etf_flow%'
ORDER BY captured_at_utc DESC LIMIT 5;
"
# 预期:5 行,每行 btc_dom + etf_flow 都有数值

# 4. 触发 pipeline 看 9 张新卡进入 factor_cards
.venv/bin/python -c "
from src.data.storage.connection import get_connection
from src.pipeline import StrategyStateBuilder
b = StrategyStateBuilder(get_connection())
r = b.run(run_trigger='manual_post_1_6_1')
cards = r.state.get('factor_cards') or []
new_names = ['STH Supply','LTH-MVRV','STH-MVRV','SSR',
             'HODL Waves (>1y)','CDD','aSOPR',
             'ETF Flows','Bitcoin Dominance']
for nm in new_names:
    print(f'  {nm:<22} {\"OK\" if any(c[\"name\"]==nm for c in cards) else \"MISSING\"}')
"
SSH
```

---

## 六、风险扫描

- **Glassnode 历史回填(720d)**:1.6.1 派生 MVRV 现在能跑 720 天历史(price_candles
  + lth/sth_realized_price 都 since_days=720)。生产首次运行会写 ~720 行 lth_mvrv
  + 720 行 sth_mvrv,DB 占用 < 100 KB,无压力
- **CoinGlass btc_dominance / etf_flow 历史 limit=720**:同样首次拉 720 行,
  通过 daily timestamp guard 后入 wide 表 extras
- **今日门改动可能影响 cron 多档补救**:已确认 _onchain_today_complete 和
  _has_today_btc_dominance_or_etf_flow 仅在 onchain / klines_daily 入口替代
  老 helper,不影响 macro / 1h kline / weekly cron。Sprint 2.8-F 多档补救
  逻辑(每档检查再决定 skip)正常工作 — 只是判定标准从"任意写过"变成"全部
  期望写过"
- **HODL Waves 早期数据缺桶 + 今日门**:`hodl_waves_<任一 bucket>` 视为
  齐(实际 alphanode 返回 12 个,只要至少 1 个就算)
