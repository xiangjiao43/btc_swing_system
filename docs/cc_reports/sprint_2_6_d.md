# Sprint 2.6-D — events_calendar 填充 + L4 EventRisk 激活

**Date:** 2026-04-27
**Branch:** main · 当前 HEAD = `6968786`(本 sprint 4 commit + 1 报告 commit)
**Status:** ✅ Commits 1-4 落地;Commit 5 部署留给用户

---

## Triggers(偏离用户原 spec 的自主决策)

1. **Commit 2 EventsSeeder 实现路径变更**:用户 spec 让 seeder 自己写 `INSERT OR REPLACE` SQL。
   实际仓库里 `EventsCalendarDAO.upsert_events()`(`src/data/storage/dao.py:636`)已存在,
   带正确的 `ON CONFLICT(event_id) DO UPDATE SET ...`。按 §X "新代码不堆叠重复 INSERT 逻辑",
   seeder 只做 JSON→EventRow 转换 + 调现有 DAO。

2. **Commit 3 reframed 为集成测试**:用户 spec 让我修 `state_builder.py` 加 events_upcoming_48h 注入。
   实际 `state_builder._assemble_context`(`src/pipeline/state_builder.py:611-643`)已经在调
   `EventsCalendarDAO.get_upcoming_within_hours(conn, hours=72, now_utc=...)` 并把结果挂到
   `context["events_upcoming_48h"]`(line 642)。
   按 §X 不重写已有逻辑,改为新增集成测试覆盖 seed→DAO→event_risk 全链路。

3. **Commit 5 部署未自动执行**:生产部署是 hard-to-reverse + shared system,
   留给用户手动触发(参考 sprint_2_6_b 部署流程)。报告里给出完整验证脚本。

---

## 一、本 sprint commits

| commit | 摘要 |
|---|---|
| `d7a9a25` | data(seeds): add 2026 FOMC/NFP/CPI events seed (10 entries) |
| `213ce6e` | feat(events): add EventsSeeder to load FOMC/CPI/NFP from JSON seed |
| `e60bb98` | test(events): integration coverage for seed → DAO → event_risk chain |
| `6968786` | feat(startup): seed events_calendar on scheduler startup |
| (本) | docs(reports): sprint_2_6_d complete |

435 pytest pass(无回归,新增 13 测试),pre-commit gitleaks 每次自动 Passed。

---

## 二、Recon 关键发现:四件事已先行存在

读代码后发现 Sprint 2.6-D 的目标基本"已铺好管道,只差数据":

| 用户 spec 期望补的 | 仓库已有 | 文件位置 |
|---|---|---|
| EventRow 数据类 | ✅ 已有 | `src/data/storage/dao.py:99-108` |
| `events_calendar` 表 schema(含 CHECK timezone IN ('America/New_York','UTC') + impact_level 1-5) | ✅ 已有 | `src/data/storage/schema.sql:226-240` |
| `EventsCalendarDAO.upsert_events()` 带 ON CONFLICT | ✅ 已有 | `src/data/storage/dao.py:636` |
| `EventsCalendarDAO.get_upcoming_within_hours()` 自动附加 `hours_to` 字段 | ✅ 已有 | `src/data/storage/dao.py:673-708` |
| `_assemble_context()` 把 `events_upcoming_48h` 注入 context | ✅ 已有 | `src/pipeline/state_builder.py:634-642` |
| `event_risk.py` 读 `context["events_upcoming_48h"]` | ✅ 已有 | `src/composite/event_risk.py:34` |
| factor_card_emitter 渲染"下次 FOMC/CPI/NFP" 卡 | ✅ 已有 | `src/strategy/factor_card_emitter.py:1393-1434` |
| 真正缺的 | ❌ 没数据 | `events_calendar` 行数 = 0 |

→ 真问题不是"补管道",而是"喂数据"。本 sprint 实际工作量比 spec 估的小很多。

---

## 三、Commits 改动清单

### Commit 1 `d7a9a25`:`data/seeds/events_2026.json`
10 条 events:8 FOMC(全年)+ 5 月 NFP + 5 月 CPI。
DST 处理:Apr-Oct 用 EDT(UTC-4 → 14:00 ET = 18:00 UTC);Jan/Feb/Dec 用 EST(UTC-5 → 14:00 ET = 19:00 UTC)。
`_meta.next_review_date: 2027-01-15` 提示明年要更新。

### Commit 2 `213ce6e`:`src/data/collectors/events_seeder.py` + 10 测试

**§X 关键决策:不重写 INSERT。** 直接复用 `EventsCalendarDAO.upsert_events(conn, list[EventRow])`。
seeder 只负责:
1. 读 JSON
2. 校验必填字段(`event_id`)
3. 校验 timezone 在 `{America/New_York, UTC}` 白名单(否则会撞 CHECK 失败,提前 skip + warn)
4. 转 `EventRow` dataclass
5. 调 DAO

返回 `{valid, skipped, total_rows_affected}`。

**测试覆盖:**
- load:成功 / 文件不存在 / 非法 JSON / events 字段非 list
- upsert:首次插入 / 幂等(2 次 run 行数仍是 N)
- 防御:无 event_id skip / 非法 timezone skip(不抛 IntegrityError)
- 真实 seed 文件能 100% load 进真实 schema(end-to-end check)

### Commit 3 `e60bb98`:`tests/test_events_pipeline_integration.py` + 3 测试

**Reframed 为集成测试**(state_builder 已实现注入,无需改代码)。

3 个测试用 36h 锚点构造 FOMC,验证全链路:
1. seed → `DAO.get_upcoming_within_hours` 返回 `hours_to ≈ 36.0`
2. seed → DAO → `EventRiskFactor.compute()` → `score=4.0, band="medium", cap=0.85`
   - 公式:fomc 权重 4 × 距离 multiplier(36h ∈ [24,48] = 1.0)= 4.0
   - 4.0 ≥ medium_at_or_above(4)→ medium → cap_multiplier = 0.85
3. 真实 seed 文件 → 表里能 grep 到 `fomc_2026_04_29 / fomc_2026_12_09 / nfp_2026_05_01 / cpi_2026_05_13`

### Commit 4 `6968786`:`src/scheduler/main.py::_seed_events_on_startup` + 2 测试

挂在 `run_forever()` 顶部,在 `scheduler.start()` 之前执行。
异常全吞(scheduler 不能因为 seed 失败而起不来)。
`build_scheduler()` 不调 seeder → 单元测试不被影响。

测试:
1. `get_connection` raises → seed hook 不抛
2. happy path → `seed_events(conn)` 被调一次 + `conn.close()` 被调一次

---

## 四、未触动的清单(按 spec 硬约束)

| 文件 | 状态 |
|---|---|
| `src/composite/event_risk.py` | ✅ 未动(本来就 ready) |
| `src/evidence/layer1_regime.py` ~ `layer5_*.py` | ✅ 未动 |
| `src/pipeline/state_builder.py` | ✅ 未动(注入逻辑已就位) |
| `src/data/storage/schema.sql` | ✅ 未动 |
| `src/data/storage/dao.py::EventsCalendarDAO` | ✅ 未动(复用 upsert_events) |
| `docs/modeling.md` | ✅ 未动 |
| `CLAUDE.md` | ✅ 未动 |

---

## 五、测试验证

```
$ python -m pytest tests/test_events_seeder.py tests/test_events_pipeline_integration.py tests/test_scheduler.py -q
............................                                              [100%]
22 passed in 0.4s

$ python -m pytest -q
435 passed, 1 skipped, 84 warnings in 1.95s
```

无回归。pre-commit gitleaks 每次 commit 自动 Passed。

---

## 六、待用户手动执行(原 Commit 5 部署)

```bash
# 服务器(124.222.89.86)
ssh user@server
cd /path/to/btc_swing_system
git pull
sudo systemctl restart btc-strategy   # 触发 _seed_events_on_startup
```

### 验证 1:`events_calendar` 有数据

```bash
.venv/bin/python -c "
from src import _env_loader
from src.data.storage.connection import get_connection
c = get_connection()
cur = c.cursor()
cur.execute('SELECT event_id, event_type, utc_trigger_time, impact_level FROM events_calendar ORDER BY utc_trigger_time')
print('=== events_calendar ===')
for r in cur.fetchall():
    print(f'  {r[0]:25s} {r[1]:6s} {r[2]} impact={r[3]}')
"
```

预期:看到 10 条事件,`fomc_2026_04_29` 在列表里。

### 验证 2:跑 pipeline

```bash
.venv/bin/python scripts/run_pipeline_once.py 2>&1 | tail -10
```

### 验证 3:L4 EventRisk 激活 + Apr 29 FOMC 在窗口内

```bash
.venv/bin/python -c "
from src import _env_loader
import requests
resp = requests.get('http://127.0.0.1:8000/api/strategy/current',
                    auth=('admin', 'Y_RhcxeApFa0H-'), timeout=10)
s = resp.json().get('state', {})

# composite EventRisk
cf = s.get('composite_factors') or {}
er = cf.get('event_risk') or {}
print('=== EventRisk ===')
print(f'  score: {er.get(\"score\")}')
print(f'  band: {er.get(\"band\")}')
print(f'  position_cap_multiplier: {er.get(\"position_cap_multiplier\")}')
print(f'  upcoming_events_count: {er.get(\"upcoming_events_count\")}')
print(f'  contributing_events: {er.get(\"contributing_events\")}')

# 找 FOMC 事件卡
cards = s.get('factor_cards') or []
for c in cards:
    cid = c.get('card_id', '').lower()
    if 'event_fomc' in cid:
        print(f'\\n=== {c.get(\"name\")} ({c.get(\"card_id\")}) ===')
        print(f'  current_value: {c.get(\"current_value\")}')
        print(f'  plain: {c.get(\"plain_interpretation\")}')
"
```

### 预期值

距 Apr 29 18:00 UTC 的小时数取决于跑 pipeline 的实时时刻:

| 距离 (h) | distance_multiplier | EventRisk score (fomc=4) | band | cap |
|---|---|---|---|---|
| 0-24 | 1.5 | 6.0 | medium | 0.85 |
| 24-48 | 1.0 | 4.0 | medium | 0.85 |
| 48-72 | 0.5 | 2.0 | low | 1.00 |
| > 72 | 0 | 0.0 | low | 1.00 |

注意:用户在 spec 里说"明天 BJT 凌晨 2:00 (UTC 18:00)= < 14h"。事实核查 today=2026-04-27,
FOMC = 2026-04-29 18:00Z = ~48h 以外。**预期 EventRisk score = 4.0(medium 档)**,
若波动率 extreme 触发 +bonus 可能到 5+。如真要进 [0,24]h 高档窗口,需等到 4-29 凌晨 BJT(UTC 4-28 下午)
之后再跑 pipeline。

### 验证 4:网页"距下次 FOMC 利率决议"卡

`card_id = event_fomc_next_<date>`,`current_value = hours_to`(浮点),`value_unit = "小时"`,
`plain_interpretation` 中文说明含"距离下次 FOMC 利率决议还有 N 小时" + 24/48/72 阈值。

---

## 七、§X 工程纪律本次践行

- ✅ EventsSeeder **不**自己写 `INSERT OR REPLACE`,复用 `EventsCalendarDAO.upsert_events`
- ✅ Commit 3 reframed 为集成测试,不重写已有的 `_assemble_context` 注入逻辑
- ✅ `_seed_events_on_startup` 失败吞异常 + 不写额外 fallback DAO(让现有的查询 0 行返回 [] 即可)
- ✅ 没新建独立 `events_collector.py`,因 spec 明确"不依赖外部 API"

---

## 八、遗留(下个 sprint 候选)

### 8.1 NFP / CPI 全年 seed
当前只 seed 了 5 月。建议 Sprint 2.6-D.1 或 F 补全 6-12 月 NFP(每月第一周五)+ CPI(每月中旬)。
当前空缺不影响本 sprint 验收,因为本月 FOMC 已能驱动 L4。

### 8.2 期权大到期(`options_expiry_major`)
`event_risk_scoring.event_type_weights` 含 `options_expiry_major: 2`,但 seed 目前 0 条。
Deribit 月末/季末大到期日历可后补,优先级低于 NFP/CPI。

### 8.3 `_meta.next_review_date: 2027-01-15`
seed 文件年级别更新,提示明年 1 月需手动添加 2027 年事件。可考虑加 `/schedule` 提醒(本 sprint 不做)。

### 8.4 spec 里说"events_window_hours = 48",实际 state_builder 默认 = 72
`_assemble_context` 用 `self.events_window_hours = 72.0`(line 214 默认)和 event_risk 距离桶上限 72h 对齐。
spec 名字保留 `events_upcoming_48h` 但实际是 72h 窗口 — 历史命名,不动。

---

## 九、git log(本 sprint)

```
6968786 feat(startup): seed events_calendar on scheduler startup
e60bb98 test(events): integration coverage for seed -> DAO -> event_risk chain
213ce6e feat(events): add EventsSeeder to load FOMC/CPI/NFP from JSON seed
d7a9a25 data(seeds): add 2026 FOMC/NFP/CPI events seed (10 entries)
```
