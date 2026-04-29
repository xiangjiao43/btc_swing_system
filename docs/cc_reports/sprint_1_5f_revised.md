# Sprint 1.5f-revised — derivatives_snapshots 清污 + 算法回归 daily 语义

**Date:** 2026-04-29
**Branch:** main
**Status:** ✅ 完成,11 个新测试 + 853/853 全量回归过

---

## 一、根因(用户 SSH 真 DB 复检定位)

1.5e.1 修了 3 张 24h 卡用 `series.iloc[-24:].sum()` / `_pct_change(series, 24)`,
**假设 series 是 hourly**。SSH 真 DB 复检后用户拒绝通过判断,真相是:

- **生产代码 100% daily**:`scripts/backfill_data.py` interval='1d',
  `collect_and_save_all` interval='1d',派生因子算法(7d 均 / 30d 分位 / 90d Z)
  全部用 `series.tail(N)` 假设 daily
- **`jobs.py` 短暂 hourly**(Sprint 2.7-B,误判)— 让 hourly 入库
- **501 行 hourly 调试遗留**:用户 + Claude 在过去 SSH 测试中跑
  `fetch_*(interval='1h')` 写入的污染
- **混存导致**:`series` 平均间隔 5.9-11.8h(混合频率),`series.tail(N)`
  N 行 ≈ N/24 ~ N/2 天数据,数值毫无语义
- **1.5e.1 24h 卡碰巧算对**:因为最末 24 行刚好是 hourly 污染段。清污后
  会变成 24 天

---

## 二、改动

### 任务 A:`src/scheduler/jobs.py` 衍生品 fetch interval 1h → 1d

```python
# Sprint 1.5f-revised:衍生品反转回 daily(interval='1d', limit=7)。
# Sprint 2.7-B 一度改 1h limit=168 是误判;实际派生因子算法(7d 均 / 30d 分位 /
# 90d Z)以及"24h 卡"语义都是基于 daily bar 设计的。
# daily limit=7 + 每小时 cron 让"今天进行中的 daily bar"持续刷新。
rows = fn(interval="1d", limit=7)
```

### 任务 B:`src/data/storage/dao.py::DerivativesDAO.upsert_batch` 防再污染

```python
# Sprint 1.5f-revised §X 防再污染:**只接受 daily timestamp**
# ('YYYY-MM-DDT00:00:00Z')。生产 jobs.py 已用 interval='1d',hourly
# timestamp 一律 logger.warning + 跳过(避免 SSH 调试遗留再次混存到表)。
for r in rows:
    ts = r.timestamp
    if not isinstance(ts, str) or not ts.endswith("T00:00:00Z"):
        logger.warning(
            "DerivativesDAO.upsert_batch: rejecting non-daily ts=%s ...",
            ts, r.metric_name, r.metric_value,
        )
        continue
    ...
```

模块级新增 `logger = logging.getLogger(__name__)`(原文件没有 logger)。

### 任务 C:`src/strategy/factor_card_emitter.py` 24h 卡反转 daily 语义

| 卡 | 1.5e.1(hourly 假设)| 1.5f-revised(daily) |
|---|---|---|
| Binance 24h 清算总额 | `series.iloc[-24:].sum()` | `_latest(series)` — daily bar 自带 24h 累计 USD |
| 未平仓合约 24h 变化 | `_pct_change(series, 24)` | `_pct_change(series, 1)` — 今 daily / 昨 daily - 1 |
| Binance 多空比 24h 变化 | `_pct_change(lsr, 24)` | `_pct_change(lsr, 1)` |

**§X**:1.5e.1 引入的 `sum_24h` / `coverage_h` 局部变量删除。

### 任务 D:`scripts/cleanup_hourly_pollution.py`(新)

清除 derivatives_snapshots 所有非 daily 行:

```bash
.venv/bin/python scripts/cleanup_hourly_pollution.py            # dry-run
.venv/bin/python scripts/cleanup_hourly_pollution.py --execute
```

幂等,完成后 VACUUM 回收空间 + 验证 hourly_after = 0。

---

## 三、测试

### 删除(§X):`tests/test_factor_card_24h_window.py`(8 测试)
1.5e.1 的"hourly 假设"测试(24 行 sum、24 行 lookback、partial 5 行)— 整文件删除。

### 新建:`tests/test_factor_card_24h_daily.py`(7 测试)

| 测试 | 验证 |
|---|---|
| `test_24h_liquidation_uses_daily_last_value` | daily series 末值 = 7,686,347.99 → current_value = 7,686,347.99 |
| `test_24h_liquidation_only_one_day_still_works` | 单 daily 行 → 直接显示该值 |
| `test_24h_liquidation_none_when_empty` | 无数据 → None |
| `test_24h_oi_uses_daily_pct_change` | [55_000, 56_000] → +1.82% |
| `test_24h_oi_none_when_only_one_day` | 单 daily → None(days=1 lookback 缺) |
| `test_24h_lsr_uses_daily_pct_change` | [0.94, 0.81] → -13.83% |
| `test_24h_lsr_none_when_only_one_day` | 单 daily → None |

### 新建:`tests/test_derivatives_daily_only.py`(4 测试)

| 测试 | 验证 |
|---|---|
| `test_upsert_rejects_hourly_timestamp` | hourly ts → DB 没行,logger 出 "non-daily ts" warning |
| `test_upsert_accepts_daily_timestamp` | T00:00:00Z → 正常入库 |
| **`test_upsert_mixed_batch_only_daily_kept`** | **关键反退化**:3 daily + 3 hourly 混合 batch → DB 仅 3 daily,hourly 假数据 99.0 不进 DB |
| `test_get_all_metrics_after_cleanup_is_pure_daily` | 5 daily 行 → get_all_metrics 返回 series 平均间隔 ≈ 24h |

### 修复 fixtures
- `tests/test_state_builder_pre_flight.py::_seed_fresh_data`:derivatives 用
  `ts_iso[:10] + "T00:00:00Z"` 截断为 daily,绕过 DAO guard
- `tests/test_scheduler_2_7_b_collectors.py::test_collect_klines_1h_uses_1d_interval_for_derivatives`:
  断言 interval='1d' limit=7(老断言 1h/168 反转)

**回归**:全量 `pytest tests/` = **853 passed, 1 skipped, 6.70s**(850 + 11 新 - 8 删除 = 净 + 3)。

---

## 四、用户验证脚本(SSH 部署后)

```bash
ssh ubuntu@124.222.89.86 << 'SSH'
cd /home/ubuntu/btc_swing_system
git pull

# 1. 部署前 dry-run 看污染
.venv/bin/python scripts/cleanup_hourly_pollution.py
# 期望:hourly rows: 501 (will DELETE);daily rows: 500

# 2. 真清污(用户确认数据量后)
.venv/bin/python scripts/cleanup_hourly_pollution.py --execute
# 期望:DELETED 501;total after: 500;hourly after: 0

# 3. 重启服务(jobs.py 已 daily)
sudo systemctl restart btc-strategy.service
sleep 5

# 4. 等下个整点 cron(每小时 fn(interval='1d',limit=7)刷新今天 daily)
sleep $(( ( 60 - $(date +%M) ) * 60 + 60 ))

# 5. 验证 series 全 daily(24h cadence)
.venv/bin/python -c "
from src.data.storage.connection import get_connection
from src.data.storage.dao import DerivativesDAO
conn = get_connection()
m = DerivativesDAO.get_all_metrics(conn, lookback_days=180)
for name, s in m.items():
    if len(s) > 1:
        span_h = (s.index[-1] - s.index[0]).total_seconds() / 3600
        avg_h = span_h / (len(s) - 1)
        print(f'{name}: n={len(s)}, avg_interval={avg_h:.1f}h')
"
# 期望:所有 metric avg_interval ≈ 24.0h

# 6. 网页前端 3 张 24h 卡:
#    - Binance 24h 清算总额:DB 最新 daily liquidation_total(单天值)
#    - OI 24h 变化:今 daily / 昨 daily - 1,绝对值 < 5%(正常市场)
#    - LSR 24h 变化:同上,绝对值 < 30%
SSH
```

---

## 五、§X / §Y / §Z 自检

### §X(旧代码必删)
- 删除 `tests/test_factor_card_24h_window.py`(1.5e.1 整个 hourly 假设测试)
- 删除 `factor_card_emitter` 的 `sum_24h` / `coverage_h` 局部变量(1.5e.1 引入)
- 删除 `jobs.py` 衍生品 1h interval(2.7-B 误判)
- DAO `upsert_batch` 防再污染机制阻止未来 hourly 数据从任何路径进入

### §Y
本 commit 立即 push。

### §Z 端到端断言
- 真 init_db + 真 DerivativesDAO.upsert_batch + COUNT(*) 验证 hourly 拒绝
- 真 daily Series + 真 emit_factor_cards 验证 3 张 24h 卡数值
- `test_upsert_mixed_batch_only_daily_kept` **关键反退化** guard:
  混合 batch 中 hourly 假数据 99.0 不进 DB

### 同类风险扫描
1. **生产 SQL 调试** — 未来仍可能有人手工 `INSERT INTO derivatives_snapshots`
   绕开 DAO guard。本 sprint 不加表级 CHECK 约束(SQLite CHECK 表达式
   不容易写)— 留 v0.6
2. **DAO guard 放宽到允许其他 daily-aligned ts** — 如 `T00:00:00.000Z` 微秒
   级也是 daily 但 endswith 不通过。当前 collector 不会产生这种 ts,
   生产风险低
3. **派生因子 7d / 30d / 90d / 180d** — 这些用 `series.tail(N)` 在纯 daily
   下是对的(N 行 = N 天)。本 sprint 后,清污前的"5.9h 平均间隔"消失,
   tail 语义恢复正确
4. **cleanup 脚本 VACUUM 时长** — 500 行小表,< 1s
5. **历史 365 天回填** — 任务 D(可选)未做,留下个 sprint;当前 500 行
   daily 已够 30d/90d/180d 派生(180 daily = 180 天)

---

## 六、改动文件

| 文件 | 改动 |
|---|---|
| `src/scheduler/jobs.py` | 衍生品 fetch interval='1h' limit=168 → '1d' limit=7 |
| `src/data/storage/dao.py` | 加 logger;DerivativesDAO.upsert_batch 拒绝非 daily ts |
| `src/strategy/factor_card_emitter.py` | 3 张 24h 卡反转 daily 语义(_latest / _pct_change(.., 1)) |
| `scripts/cleanup_hourly_pollution.py` | 新文件 dry-run / --execute 清 hourly 污染 |
| `tests/test_factor_card_24h_window.py` | **删除**(§X 1.5e.1 hourly 测试) |
| `tests/test_factor_card_24h_daily.py` | 新文件 7 测试 daily 语义 |
| `tests/test_derivatives_daily_only.py` | 新文件 4 测试 DAO guard |
| `tests/test_state_builder_pre_flight.py` | _seed_fresh_data 用 daily ts |
| `tests/test_scheduler_2_7_b_collectors.py` | test name + 断言反转为 1d/7 |

---

## 七、未覆盖 / 留 v0.6

- `scripts/backfill_data.py` 仍 interval='1d',OK(本 sprint 验证 daily 是对的)
- 365 天历史回填:当前 500 行 daily 已够 90d/180d
- 表级 CHECK 约束(数据库层强制 daily 约束):SQLite CHECK 复杂,留 v0.6
- L2/Crowding 因子里若有 24-行 假设(本 sprint 没扫到,留 1.5f.1 续修)
