# Sprint 1.5g — pre_flight 衍生品阈值改用 captured_at + 30h

**Date:** 2026-04-29
**Branch:** main
**Status:** ✅ 本地完成,12 个新测试 + 865/865 全量回归过

---

## 一、根因

1.5f-revised 把衍生品反转回 daily cadence(jobs.py `interval='1d'`,
每小时 cron 刷今天的 daily bar),但 `_PREFLIGHT_THRESHOLDS_SEC` 里
衍生品阈值仍是 **10 min**(2.7-C 设计 hourly 时定的)。

后果:
- daily 数据点 captured_at_utc = 当天 00:00:00Z(永远 0-24h 老)
- 即使 inserted_at_utc 是 30 秒前,只要 daily bar 的语义时间是
  当天凌晨 → 早上 8 点已经 8h 了
- pre_flight 用 inserted_at_utc 时**碰巧通过**(每小时 cron 刚刷新)
- 一旦 cron 失败一两次,inserted_at 越过 10 min → degraded.derivatives 误报

而且老阈值的语义本身是错的:**对 daily 数据点用 10 min 阈值毫无意义**
(数据点本身就是当天 00:00:00,不可能比 10 min 还新)。

---

## 二、改动

### 任务 A:`src/data/storage/dao.py::DerivativesDAO`

新增 static method:

```python
@staticmethod
def get_latest_snapshot_captured_at(
    conn: sqlite3.Connection,
) -> Optional[str]:
    """Sprint 1.5g:最近 snapshot 的 captured_at_utc(数据点本身的时间)。

    与 inserted_at(系统抓取 wall clock)不同:captured_at 是数据点
    语义时间,daily bar 的 captured_at 永远是当天 00:00:00Z,即便系统
    每小时重抓也不变。pre_flight 用这个判 daily 数据点新鲜度更直观
    (建模 §3.2.3 "数据点 vs 系统侧"区分)。
    """
    row = conn.execute(
        "SELECT captured_at_utc FROM derivatives_snapshots "
        "ORDER BY captured_at_utc DESC LIMIT 1"
    ).fetchone()
    return row["captured_at_utc"] if row else None
```

### 任务 B:`src/pipeline/state_builder.py::_query_metric_inserted_at`

新增字段 `derivatives_snapshot_captured`(沿用 inserted 字段做兼容性 fallback)。

### 任务 C:`_PREFLIGHT_THRESHOLDS_SEC`

```python
"scheduled": {
    ...
    # Sprint 1.5g:衍生品改用 captured_at_utc(数据点时间)+ 30h 阈值。
    # 1.5f-revised 起 derivatives 是 daily cadence(jobs.py interval='1d',
    # 每小时 cron 刷今天 daily bar)。daily 数据点天然 0-24h 老,30h 阈值
    # = "yesterday's daily bar 最大可接受年龄"。
    # 老 10min 阈值是误判 hourly cadence 残留,生产实际从未通过。
    "derivatives":   30 * 3600,
    ...
},
"scheduled_8h_onchain": {
    ...
    # 8 点档 onchain 严格,但衍生品 daily 仍 30h
    "derivatives":   30 * 3600,
    ...
},
```

### 任务 D:`_latest_iso_for_group` 衍生品 group 走 captured-first

```python
deriv_captured = metric_inserted_at.get("derivatives_snapshot_captured")
deriv_inserted = metric_inserted_at.get("derivatives_snapshot")
...
if group == "derivatives":
    # Sprint 1.5g:用 captured_at(数据点时间)+ 30h 阈值;
    # 兼容旧 metric_inserted_at(无 captured 字段)→ 退回 inserted。
    return deriv_captured or deriv_inserted
```

---

## 三、测试

### 新建:`tests/test_pre_flight_derivatives_threshold.py`(12 测试)

| 类别 | 测试 |
|---|---|
| 阈值表 | `test_threshold_derivatives_bumped_to_30h_scheduled` |
| 阈值表 | `test_threshold_derivatives_bumped_to_30h_8h_onchain` |
| 反退化 | `test_old_10min_threshold_no_longer_in_table` |
| `_latest_iso_for_group` | `test_latest_iso_for_derivatives_prefers_captured_over_inserted` |
| `_latest_iso_for_group` | `test_latest_iso_for_derivatives_falls_back_to_inserted_when_captured_none` |
| `_latest_iso_for_group` | `test_latest_iso_for_derivatives_falls_back_when_captured_field_missing` |
| `_latest_iso_for_group` | `test_latest_iso_for_derivatives_none_when_both_missing` |
| `_evaluate_freshness` | `test_pre_flight_passes_with_daily_captured_within_30h`(captured -10h) |
| `_evaluate_freshness` | `test_pre_flight_fails_with_daily_captured_over_30h`(captured -36h) |
| `_evaluate_freshness` | `test_pre_flight_fails_with_inserted_over_30h_no_captured`(fallback 路径) |
| `_evaluate_freshness` | `test_pre_flight_passes_at_29h_boundary_inside_threshold`(boundary -29h) |
| `_evaluate_freshness` | `test_pre_flight_8h_onchain_derivatives_also_30h` |

### 修复 fixture

`tests/test_state_builder_pre_flight.py::_seed_fresh_data`:默认 `ts_iso`
改为运行时计算的真实 UTC `datetime.now()`,避免 captured_at 因日期固定
落到 30h 之外。

```python
def _seed_fresh_data(db_conn, ts_iso: str | None = None):
    if ts_iso is None:
        ts_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
```

### 全量回归

```
865 passed, 1 skipped, 7.21s
```

(853 baseline + 12 新 = 865)

---

## 四、改动文件

| 文件 | 改动 |
|---|---|
| `src/data/storage/dao.py` | 新增 `DerivativesDAO.get_latest_snapshot_captured_at` |
| `src/pipeline/state_builder.py` | `_query_metric_inserted_at` 暴露 captured 字段;阈值 10min→30h;`_latest_iso_for_group` 衍生品 captured-first |
| `tests/test_pre_flight_derivatives_threshold.py` | **新文件** 12 测试 |
| `tests/test_state_builder_pre_flight.py` | `_seed_fresh_data` 默认用 `datetime.now()` |

---

## 五、§X / §Y / §Z 自检

### §X(旧代码必删)
- 老 10min 阈值已替换为 30h(同位置改动,无残留)
- `_latest_iso_for_group` 旧 `deriv_snap` 单变量替换为 `deriv_captured / deriv_inserted` 双变量
- 不存在并存的"新旧路径双轨"

### §Y
本地 commit 后立即 push 到 GitHub origin/main。

### §Z 端到端断言
- 真 `_evaluate_freshness` + 真 `_PREFLIGHT_THRESHOLDS_SEC` + 真 `_latest_iso_for_group`
- 真 `_run_pre_flight_freshness_check` + 真 `_seed_fresh_data` 写真 SQLite
- 反退化 guard:`test_old_10min_threshold_no_longer_in_table`

### 同类风险扫描
- **klines_1h 阈值仍 10 min**:正确,K 线确实 hourly cadence
- **klines_1d_4h / onchain / macro 仍 30h**:正确,这些都是 daily cadence
- **fallback 路径(inserted-only)**:在迁移期或 captured_at 缺失时仍可用,
  阈值 30h 也合理(每小时 cron 应在 30h 内成功)
- 没扫到生产里其他用 `derivatives_snapshot` inserted 时间做判断的代码

---

## 六、部署状态四件事清单(本 sprint 必填)

| 步骤 | 状态 | 说明 |
|---|---|---|
| **1. 本地 pytest** | ✅ | 865 passed, 1 skipped, 7.21s |
| **2. push GitHub** | ✅ | 见 commit hash + git push origin main |
| **3. 服务器 git pull** | ❌ 等用户 SSH 执行 | `ssh ubuntu@124.222.89.86 "cd /home/ubuntu/btc_swing_system && git pull"` |
| **4. 服务器 systemctl restart** | ❌ 等用户 SSH 执行 | `sudo systemctl restart btc-strategy.service` |
| **5. 生产 DB 迁移/清污** | N/A 本 sprint | 1.5g 不动 schema、不动数据,只改阈值 + 多读一个字段;1.5f-revised 已清污过 |

### 验证脚本(SSH 部署后跑)

```bash
ssh ubuntu@124.222.89.86 << 'SSH'
cd /home/ubuntu/btc_swing_system
git pull
sudo systemctl restart btc-strategy.service
sleep 5

# 等下个整点 cron 跑完(衍生品 daily bar 写入)
sleep $(( ( 60 - $(date +%M) ) * 60 + 60 ))

# 验证 pre_flight 不再因衍生品 degraded
.venv/bin/python -c "
import sqlite3
from src.pipeline.state_builder import (
    _query_metric_inserted_at, _evaluate_freshness, _PREFLIGHT_THRESHOLDS_SEC,
)
conn = sqlite3.connect('btc_swing_system.db')
conn.row_factory = sqlite3.Row
mia = _query_metric_inserted_at(conn)
print('derivatives_snapshot:', mia.get('derivatives_snapshot'))
print('derivatives_snapshot_captured:', mia.get('derivatives_snapshot_captured'))
failed = _evaluate_freshness(mia, 'scheduled')
print('failed groups:', failed)
print('expected: \"derivatives\" NOT in failed')
"
SSH
```

---

## 七、未覆盖 / 留 v0.6

- **klines_1h 阈值 10 min**:理论上 1H K 线晚 10 分钟还是合理的,但生产
  CoinGlass 中转可能偶发 15-20 min 延迟。如果误报多再调
- **macro 30h**:对 FRED daily 是对的,对 yfinance batch 也对。无需改
- **衍生品 cron 失败重试**:本 sprint 不动 cron 重试逻辑,留给运维监控
