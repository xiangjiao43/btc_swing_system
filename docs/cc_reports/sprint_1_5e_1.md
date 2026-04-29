# Sprint 1.5e.1 — 衍生品因子卡 24h 算法 + latest_factor_cards 同步 + DB 清理

**Date:** 2026-04-29
**Branch:** main
**Status:** ✅ 完成,10 个新测试 + 850/850 全量回归过

---

## 一、问题(1.5e SSH 验证后发现的派生 bug)

### Bug 1:卡名"24h"实际算 1h
衍生品是 hourly 时序,但 3 张 24h 卡都用了"取最近 1 个点"或 `_pct_change(.., 1)`:
- "Binance 24h 清算总额":`_latest(liq_series)` → 1h 单点值
- "未平仓合约 24h 变化":`_pct_change(series, 1)` → 1h diff
- "Binance 多空比 24h 变化":`_pct_change(lsr_series, 1)` → 1h diff

→ 用户看到"清算 11,409 USD"被误导(实际是某个 1h 真值);"24h 变化 0%"也是 1h 噪声。

### Bug 3:latest_factor_cards 与 pipeline.run 不同步
`refresh_factor_cards` 只在 collector 跑完后被调用。`pipeline.run()` 不调用 →
manual run / event-driven run 后,`/strategy/current` 仍返回上次 cron 的旧快照
(因为 `_overlay_latest_factor_cards` 走 latest_factor_cards 表)。

### 老 1.5e 假 0 历史污染
1.5e 修了源头 collector,但 DB 已有的 552+ 行假 0 没清。

(Bug 2 crowding=0 经诊断是当前市场极度中性的正确结果,_crowding_narrative
的"正常 ≤3 分,不收紧仓位"已诚实表达,本 sprint 不动。)

---

## 二、改动

### 任务 A:`src/strategy/factor_card_emitter.py` 修 24h 算法

**A.1 liquidation_24h** — 改为最近 24 行 hourly 累加 sum:
```python
if isinstance(liq_series, pd.Series):
    s = liq_series.dropna()
    last_24 = s.iloc[-24:]
    coverage_h = len(last_24)
    sum_24h = float(last_24.sum())
# 数据 < 24h → current_value=None,前端显示 "—"
current_value = round(sum_24h, 2) if sum_24h is not None and coverage_h >= 24 else None
```

**A.2 oi_24h_change** — `_pct_change(series, 1)` → `_pct_change(series, 24)`

**A.3 lsr_change_24h** — 同上

### 任务 C:`src/pipeline/state_builder.py` 接通 latest_factor_cards

`run_with_context` 在 final commit 后增加一段:
```python
try:
    cards_in_state = state.get("factor_cards") or []
    if cards_in_state:
        from ..data.storage.dao import LatestFactorCardsDAO
        LatestFactorCardsDAO.upsert(
            self.conn, cards_in_state,
            refreshed_at_utc=run_ts_utc,
        )
        self.conn.commit()
except Exception as e:
    logger.warning("post-run latest_factor_cards refresh failed: %s", e)
```

→ 每次 `pipeline.run()` 后 latest_factor_cards.refreshed_at_utc 反映本次 run_ts;
`/strategy/current` 立刻拿到本次 run 的真值。

### 任务 D:`scripts/cleanup_zero_liquidation.py`(新)

扫 `derivatives_snapshots` 处理 3 类污染:
1. 全失败 row(`funding_rate IS NULL AND liquidation_total = 0`)→ DELETE
2. `long=0 AND short>0` → `long=NULL, total=short`(单边失败但短侧有真值)
3. `long>0 AND short=0` → 反之

dry-run 默认开启,`-y/--apply` 才真执行。报告"会删/会改多少行"。

---

## 三、测试

`tests/test_factor_card_24h_window.py`(8 测试):

| 测试 | 验证 |
|---|---|
| `test_liquidation_24h_sums_24_hourly_rows` | 30 行 each 1000 → current=24,000(不是 1000) |
| `test_liquidation_24h_returns_none_when_insufficient` | 5 行 → None + interp 提示数据不足 |
| `test_liquidation_24h_picks_last_24_when_more` | 30 行(前 6 个 0,后 24 个 5000)→ 末尾 24 行 sum=120,000 |
| `test_oi_24h_change_uses_24_hourly_lookback` | iloc[-25]=100, iloc[-1]=110 → +10% |
| `test_oi_24h_change_returns_none_when_insufficient` | 10 行 < 25 → None |
| `test_lsr_24h_change_uses_24_hourly_lookback` | 0.94→0.81 → ≈ -13.83% |
| `test_lsr_partial_window_returns_none` | 5 行 → None |
| **`test_24h_cards_not_using_single_point_diff`** | **关键反退化**:iloc[-2]=iloc[-1] 但 iloc[-25]≠iloc[-1] → 必须用 24 路径(老 _pct_change(..,1) 会得 0%,新 24 得 +5%) |

`tests/test_pipeline_refreshes_latest_factor_cards.py`(2 测试):

| 测试 | 验证 |
|---|---|
| `test_pipeline_run_updates_latest_factor_cards` | builder.run → LatestFactorCardsDAO.get_latest 含 cards + refreshed_at = run_ts_utc |
| `test_two_runs_update_refreshed_at` | 连跑两次 manual run(间隔 1s),refreshed_at_utc 反映第二次 |

**回归**:全量 `pytest tests/` = **850 passed, 1 skipped, 6.36s**(840 + 10 新)。

---

## 四、用户验证脚本(SSH 部署后)

```bash
ssh ubuntu@124.222.89.86 << 'SSH'
cd /home/ubuntu/btc_swing_system
git pull
sudo systemctl restart btc-strategy.service
sleep 5

# 1. dry-run 看历史污染
.venv/bin/python scripts/cleanup_zero_liquidation.py
# 看输出确认要删/修的行数,确认后:
# .venv/bin/python scripts/cleanup_zero_liquidation.py --apply

# 2. 跑一次 collect 收集 24h 真数据(等下次 1h cron 即可)
sleep $(( ( 60 - $(date +%M) ) * 60 + 60 ))

# 3. 触发 manual pipeline run + 等 latest_factor_cards 刷新
.venv/bin/python -c "
from src.pipeline import StrategyStateBuilder
from src.data.storage.connection import get_connection
conn = get_connection()
b = StrategyStateBuilder(conn)
r = b.run(run_trigger='manual')
print('run_id:', r.run_id, 'persisted:', r.persisted)
conn.close()
"

# 4. 查 API
curl -s -u admin:Y_RhcxeApFa0H- http://127.0.0.1:8000/api/strategy/current | \
  python3 -c "
import json, sys
state = json.load(sys.stdin)['state']
for c in state.get('factor_cards') or []:
    cid = c.get('card_id', '')
    if any(k in cid for k in ['liquidation_24h', 'oi_24h_change',
                              'lsr_change_24h']):
        print(f'  {c.get(\"name\"):40s} value={c.get(\"current_value\")}')
"
# 期望:liquidation_24h 显示几十万到几百万 USD;OI 24h 变化显示真实 24h 累计百分比
SSH
```

---

## 五、§X / §Y / §Z 自检

### §X(直击算法 / 同步根因,不引入新函数)
- 修 `_latest` → `last_24.sum()` 直接在原行替换;`_pct_change(.., 1)` → `(.., 24)`
- pipeline.run 接 `LatestFactorCardsDAO.upsert` 用现有 DAO,不新写 helper
- 数据不足 24h 时显式返 None(前端"—"),不写 0 误导

### §Y
本 commit 立即 push。

### §Z 端到端断言
- `test_24h_cards_not_using_single_point_diff` 关键反退化 guard:
  设计 iloc[-2]=iloc[-1]=105 但 iloc[-25]=100,只有走 24 路径才能算出 +5%
- 真 builder.run + 真 SQLite + 真 LatestFactorCardsDAO.get_latest 验证 refreshed_at_utc 反映 run_ts

### 同类风险扫描
1. **数据不足 24h 时 sum 0** — 已显式判 `coverage_h >= 24` 才用,否则 None
2. **liquidation 包含其他真 0**(市场极度平静)— 24 行 each 0 → sum=0,
   仍显示 0 而非 None(数据足够,值就是 0,正确)
3. **OI hourly 数据有 gap** — `_pct_change(.., 24)` 用 dropna 后的 iloc,
   gap 不影响逻辑(看的是非 NaN 序列的 -25 / -1)
4. **manual run 速度** — refresh 增加 1 个 DAO upsert,耗时 < 100ms 微影响
5. **latest_factor_cards 表锁** — SQLite 单写,refresh 紧贴 final commit,
   收尾期 < 1s,几乎无锁竞争

---

## 六、改动文件

| 文件 | 改动 |
|---|---|
| `src/strategy/factor_card_emitter.py` | liquidation_24h 改 24 行 sum;oi_24h / lsr_24h 改 _pct_change(.., 24);数据不足 → None |
| `src/pipeline/state_builder.py` | run_with_context final commit 后接 LatestFactorCardsDAO.upsert |
| `scripts/cleanup_zero_liquidation.py` | 新文件,dry-run / --apply 清理假 0 历史 |
| `tests/test_factor_card_24h_window.py` | 新文件 8 测试 |
| `tests/test_pipeline_refreshes_latest_factor_cards.py` | 新文件 2 测试 |

---

## 七、未覆盖项 / 留 v0.6

- collect cadence 改 1h(任务 E,1.5e.1 不修)
- crowding "市场中性 = 0" 语义边界优化
- DB 历史 552+ 行假 0 完整回填(脚本已给,用户 SSH 执行)
