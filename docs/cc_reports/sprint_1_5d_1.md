# Sprint 1.5d.1 — events_seeder 孤儿清理 + 前端事件卡渲染 PCE/期权

**Date:** 2026-04-29
**Branch:** main
**Status:** ✅ 完成,11 个新测试 + 823/823 全量回归过

---

## 一、问题

1.5d 部署后 SSH 验证两个问题:

### 问题 1:options_expiry 24 条并存(应 12)
1.5d 把 event_id 从 `options_expiry_2026_XX` 改成
`options_expiry_major_2026_XX`,新 id 全是新行,旧 12 条没被删 → 24 条并存。
违反 §X(旧代码必须删)。

用户已 SSH 手动 DELETE 清理,但 events_seeder.upsert_to_db **体系性弱点**
未修 — 未来重命名 event_id 都会留脏。

### 问题 2:前端事件日历卡只显示 3 项(FOMC/CPI/NFP)
`src/strategy/factor_card_emitter.py::_emit_events_reference` 硬编码:
```python
target_types = ("fomc", "cpi", "nfp")
```
1.5d 后端接通了 PCE + options_expiry_major,但前端没渲染这两类卡。

---

## 二、改动

### 任务 A:`src/data/collectors/events_seeder.py` 加孤儿清理

`upsert_to_db` 在 INSERT/UPDATE 之前先做孤儿清理:

```python
# 阶段 1:按 (event_type, date) 找新旧 id 不一致的
seed_map = {(ev.event_type, ev.date): ev.event_id for ev in events}

existing = conn.execute(
    "SELECT event_type, date, event_id FROM events_calendar"
).fetchall()
for r in existing:
    key = (r.event_type, r.date)
    if key in seed_map and r.event_id != seed_map[key]:
        conn.execute("DELETE FROM events_calendar WHERE event_id = ?", (r.event_id,))
        orphans_removed += 1
```

**只清理"同 type+date 但 event_id 不一致的"**;不在新 seed 列表的 type 不动
(future v0.6 加 ppi 时,旧表里没 ppi 不会被误删;反之只 reseed cpi 时旧 fomc
保留)。

返回 dict 加 `orphans_removed: int` 字段。

### 任务 B:`src/strategy/factor_card_emitter.py::_emit_events_reference`

```python
target_types = ("fomc", "cpi", "pce", "nfp", "options_expiry_major")
type_labels = {
    "fomc": "FOMC 利率决议",
    "cpi": "CPI 通胀数据",
    "pce": "PCE 通胀指标",
    "nfp": "非农就业数据",
    "options_expiry_major": "期权大到期",
}
event_descriptions = {
    "fomc": ...,  # 原有
    "cpi":  ...,  # 原有
    "pce":  "📍 PCE = 美联储偏好的通胀指标(每月最后一周公布),含 headline 和 core PCE。Pinchuk (2024) 实证证据:1σ 通胀意外 → BTC -24bps,与 CPI 等量级。",
    "nfp":  ...,  # 原有
    "options_expiry_major": "📍 BTC 期权大到期(Deribit 月度/季度)。季度到期(Q1=3月/Q2=6月/Q3=9月/Q4=12月)规模显著放大,可能引发 24h 内 gamma hedging 波动放大。",
}
```

3 张卡 → 5 张卡。

---

## 三、测试

### `tests/test_events_seeder_orphan_cleanup.py`(5 测试)

| 测试 | 验证 |
|---|---|
| `test_orphan_removal_on_event_id_rename` | seed `fomc_old_id` → reseed `fomc_new_id`(同 type+date)→ 旧 id 删,只剩 1 条 |
| `test_no_orphan_for_unrelated_records` | 旧表 fomc + cpi;新 seed 只 reseed cpi(不同 date)→ fomc 保留,orphans=0 |
| `test_orphan_only_within_same_type_date` | fomc 改 id,cpi 不变 → 只 fomc 旧 id 删 |
| `test_idempotent_no_orphans_on_repeat` | 同 seed 两次,第二次 orphans=0 |
| **`test_orphan_cleanup_options_expiry_rename`** | **真翻车场景**:`options_expiry_2026_03` → `options_expiry_major_2026_03`(同 type+date)→ 旧 id 自动清 |

### `tests/test_factor_card_emitter_events.py`(6 测试)

| 测试 | 验证 |
|---|---|
| `test_emit_events_card_count_is_five` | next_by_type 含 5 类 → 渲染 5 张卡(card_id 含 fomc/cpi/pce/nfp/options_expiry_major)|
| `test_emit_events_card_includes_pce` | PCE 卡 strategy_impact 含 "PCE" + Pinchuk 描述 |
| `test_emit_events_card_includes_options_expiry_major` | 期权卡 strategy_impact 含 "季度" 或 "Q" 季度区分说明 |
| `test_emit_events_card_value_none_when_event_missing` | next_by_type 不全 → 缺失类卡仍渲染但 value=None(5 张依然全) |
| `test_emit_events_card_uses_fallback_from_events_when_next_by_type_empty` | next_by_type=None → 从 events(72h 内)兜底 |
| `test_emit_events_card_pce_value_persisted_when_far_future` | 720h(30 天)远期 PCE 仍正常渲染数值,不强制 None |

**回归**:全量 `pytest tests/` = **823 passed, 1 skipped, 6.56s**(812 + 11 新)。

---

## 四、用户验证脚本(SSH 部署后)

```bash
ssh ubuntu@124.222.89.86 << 'SSH'
cd /home/ubuntu/btc_swing_system
git pull
sudo systemctl restart btc-strategy.service
sleep 5

# 1. reseed 验证孤儿清理(用户已手动清过,这次应 orphans_removed=0)
.venv/bin/python -c "
from src.data.collectors.events_seeder import EventsSeeder
from src.data.storage.connection import get_connection
seeder = EventsSeeder()
events = seeder.load_seed()
conn = get_connection()
result = seeder.upsert_to_db(conn, events)
print(result)
conn.close()
"
# 预期:{'valid': 56, 'skipped': 0, 'total_rows_affected': ..., 'orphans_removed': 0}

# 2. 验证类型分布
.venv/bin/python -c "
import sqlite3
conn = sqlite3.connect('data/btc_strategy.db')
for r in conn.execute(
    'SELECT event_type, COUNT(*) AS n FROM events_calendar '
    'GROUP BY event_type ORDER BY event_type'
):
    print(f'  {r[0]:25s} n={r[1]}')
"
# 预期 fomc=8 / cpi=12 / nfp=12 / pce=12 / options_expiry_major=12 = 56 条

# 3. 等下次 pipeline_run,验证 5 张事件卡
curl -s -u admin:Y_RhcxeApFa0H- http://127.0.0.1:8000/api/strategy/current | \
  python3 -c "
import json, sys
state = json.load(sys.stdin)['state']
event_cards = [c for c in state.get('factor_cards') or []
               if c.get('category') == 'events']
print(f'event 卡数: {len(event_cards)}')
for c in event_cards:
    print(f'  {c[\"card_id\"]:50s} value={c.get(\"current_value\")}')
"
# 预期 5 张(fomc/cpi/pce/nfp/options_expiry_major 各 1)

# 4. 浏览器刷新事件日历区域应显示 5 个槽位
SSH
```

---

## 五、§X / §Y / §Z 自检

### §X(修补 1.5d 留脏事故)
- events_seeder upsert_to_db **本身**修补孤儿清理逻辑,
  保证未来任何 event_id 重命名都不会再留脏
- factor_card_emitter `target_types` 跟后端 event_type 全集对齐
  (后端 1.5d 的 thresholds.event_type_weights 5 个 type 全有 UI 卡)

### §Y
本 commit 立即 push。

### §Z 端到端断言
- 真 init_db + EventsSeeder.upsert_to_db 两次跑(不同 event_id)→ 断言旧
  id DELETE,新 id INSERT,行数 = 1
- factor_card_emitter._emit_events_reference 用真 next_by_type 输入,断言
  card_id 集合 = 预期 5 个,strategy_impact 含 PCE / 期权说明
- 真翻车场景测试 `test_orphan_cleanup_options_expiry_rename` 复现 1.5d 翻车
  路径(options_expiry_2026_03 → options_expiry_major_2026_03)

### 同类风险扫描
1. **新 seed 列表为空时清理逻辑** — `if seed_map: existing = ...`,空 seed 不
   触发清理(避免误删全表)
2. **同 (type, date) 多个新 id**(理论不可能,seed 文件是平面 list)— `seed_map`
   字典 key 重复时后写覆盖,实际不会触发(events_2026.json 同 type+date 只 1 条)
3. **大量 events_calendar 全表扫** — 56 条规模,SELECT * 微秒级;未来如膨胀到
   万级再考虑加索引(目前 `idx_events_type` 已存在,但孤儿扫不走索引,查全表)
4. **前端 5 类卡 captured_at_bjt** — 都用 `now_bjt`(预期,事件类卡 captured_at
   是"渲染时刻",不是事件本身时间)

---

## 六、改动文件

| 文件 | 改动 |
|---|---|
| `src/data/collectors/events_seeder.py` | upsert_to_db 加孤儿清理(同 type+date 但新旧 id 不一致 → DELETE);返回 `orphans_removed` 字段 |
| `src/strategy/factor_card_emitter.py` | `_emit_events_reference` target_types 加 pce + options_expiry_major(3→5);type_labels + event_descriptions 同步 |
| `tests/test_events_seeder_orphan_cleanup.py` | 新文件 5 测试 |
| `tests/test_factor_card_emitter_events.py` | 新文件 6 测试 |

---

## 七、未覆盖项

- 1.5c.x + 1.5d + 1.5d.1 完结了 events_calendar 系列;留 v0.6:IBIT 期权
  / 真实日期偏移自动同步 / API 接入(取代手动 seed)
