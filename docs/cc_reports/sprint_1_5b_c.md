# Sprint 1.5b-C — 集成 + API + 反向切换 + 复盘触发

**Date:** 2026-04-29
**Branch:** main
**Status:** ✅ 完成,11 个新测试 + 743/743 全量回归过

---

## 一、问题与决策

Sprint 1.5b-A/B 完成后,lifecycle 数据已实时写到 `strategy_runs.full_state_json`,
但:
1. `lifecycles` 表(schema 已存在)永远是空的
2. `/api/lifecycle/history` 查 lifecycles 表 → 永远返空
3. `ReviewReportGenerator` 只支持周期性报告,不支持"lifecycle 关闭时为这个 lc 生成报告"
4. 反向交易完整路径(LONG_HOLD → LONG_TRIM → LONG_EXIT → FLIP_WATCH → SHORT_PLANNED)
   只有单步测试,没有完整 e2e

本 sprint 闭环这 4 项,完成 lifecycle 系列。

---

## 二、改动

### 2.1 新建 `LifecyclesDAO`(`src/data/storage/dao.py`)

3 静态方法:
- `upsert_lifecycle(conn, lifecycle_dict) -> int` — 字段映射 lc dict → 表列;
  `ai_models_used` / `rules_versions_used` 逗号分隔;整 dict 进 `full_data_json`;
  `ON CONFLICT(lifecycle_id) DO UPDATE`
- `get_lifecycle(conn, lifecycle_id) -> dict | None`
- `list_lifecycles(conn, *, status=None, limit=50)` — 支持 status 过滤

### 2.2 `LifecycleManager` 接 LifecyclesDAO

- `__init__(conn=None)` 接 conn
- `compute_post_sm` 重构为**外层 wrapper**(`_dispatch_post_sm` 是内部纯逻辑):
  外层产出 lc 后,如果 conn 可用,**每次都 upsert**(active 中的 lc 也实时反映)
- DAO 写失败 → log warning,不拖垮 pipeline
- `_archive_lifecycle` 归档时把 `direction` 镜像到 `prev_cycle_side`,
  让 state_machine FLIP_WATCH → *_PLANNED 路径能读
- `_dispatch_post_sm`:**FLIP_WATCH → *_PLANNED** 反向切换路径加入"创建草稿"分支
  (之前只覆盖 FLAT → *_PLANNED)

### 2.3 `ReviewReportGenerator` 加 per-lifecycle 触发

`src/review/generator.py` 新增 2 个方法(保留原周期性 `generate` / `generate_and_save`):

- `generate_for_lifecycle(lifecycle_id, *, lifecycle_dict=None) -> dict`
  - 产 ReviewReport dict(建模 §8.3 v1 简化版)
  - 字段:`review_id`(`{lc_id}_{utc_iso}`)/ direction / entry_time_bjt /
    exit_time_bjt / duration_hours / entry_price_avg / max_favorable_pct /
    realized_pnl_pct / total_runs_during_lifecycle(SQL COUNT) / outcome_type /
    feedback_to_system="复盘结果不自动反哺,人工参考" /
    key_moments_replay(从 position_adjustments 转换)
  - 写入 `review_reports` 表(`ReviewReportsDAO.insert_report`)
  - v1 简化:`dimensional_assessment` 4 字段返回固定 `"v1 unevaluated"`,
    `improvements` 留空,留 v1.x 真实评估

- `maybe_generate_for_closed_lifecycle(prev_lifecycle, current_lifecycle) -> dict | None`
  - 检测 `prev.status="active"` 且 `curr.status="closed"`(同 lc_id)→ 自动触发
  - 返回 None 表示无需触发

### 2.4 `state_builder.py` 接通自动复盘

- `__init__`:`self._review_generator = ReviewReportGenerator(conn=self.conn)`
- 在 `lifecycle_post_sm` stage 之后加 `auto_review_on_close` stage:
  - 调 `maybe_generate_for_closed_lifecycle(prev_lifecycle, lifecycle_post)`
  - 用 `_safe`(已有 helper)包,异常只记 fallback log,不拖垮 pipeline

### 2.5 `/api/lifecycle/current` 防 legacy 占位泄漏

`src/api/routes/lifecycle.py`:读出 lifecycle 后,如 `managed_by="sprint_1_5b_pending"`
→ 降级返回 `{"lifecycle": null, "message": "Legacy placeholder filtered ..."}`
(防止 1.5b-B 部署前留下的旧 row 把占位透到前端)

`/api/lifecycle/history` 已正确查 lifecycles 表,无改动。

---

## 三、测试

### `tests/test_lifecycle_dao_and_review.py`(10 测试)
- LifecyclesDAO upsert / get / list / by-status
- API `/api/lifecycle/history` 真启 FastAPI + DAO seed → JSON 返回 + 过滤
- API `/api/lifecycle/current` 模拟 legacy 占位 row → null 降级
- `generate_for_lifecycle`:closed lc → 写 `review_reports` 表 + 字段断言
- `maybe_generate_for_closed_lifecycle`:active → closed 触发,pending → 不触发
- LifecycleManager 接通 DAO:`compute_post_sm` 创建 / 归档 → DB 行真增

### `tests/test_lifecycle_e2e_reversal.py`(1 测试,7 步真推进)
关键反退化 + 闭环验证:
- Step 1: FLAT → LONG_PLANNED(创建 lc,lifecycles 表 +1)
- Step 2: LONG_PLANNED → LONG_OPEN(avg_entry=区间中点,status=active)
- Step 3: LONG_OPEN → LONG_HOLD(25h + +3% PnL)
- Step 4: LONG_HOLD → LONG_TRIM(TP1 触达,position_adjustments 追加 trim)
- Step 5: LONG_TRIM → LONG_EXIT(`is_final_trim_or_exhausted=True`)
- Step 6: LONG_EXIT → FLIP_WATCH(positions_flat + L1 down + L2 hint bearish)
  - lc6 status="closed",exit_time_utc 已设
  - **review_reports 表 +1 自动复盘行**
- Step 7: FLIP_WATCH → SHORT_PLANNED(冷却 30h 后 + L2 bearish 0.75 + thesis_invalidated)
  - 新 lifecycle_id != 旧
  - lifecycles 表此时 2 条:closed long + pending short

**回归**:全量 `pytest tests/` = **743 passed, 1 skipped, 4.88s**(732 + 11 新)。

---

## 四、用户验证脚本(SSH 部署后)

```bash
ssh ubuntu@124.222.89.86 << 'SSH'
cd /home/ubuntu/btc_swing_system
git pull
sudo systemctl restart btc-strategy.service
sleep 5

# 1. lifecycles 表能查
.venv/bin/python -c "
import sqlite3
conn = sqlite3.connect('data/btc_strategy.db')
n = conn.execute('SELECT COUNT(*) FROM lifecycles').fetchone()[0]
print('lifecycles 表行数:', n)
"

# 2. API 调通
curl -s -u admin:Y_RhcxeApFa0H- http://127.0.0.1:8000/api/lifecycle/history | \
  python3 -c "import json,sys; d=json.load(sys.stdin); print('count:', d['count'])"

# 3. /current 不再透出 legacy 占位
curl -s -u admin:Y_RhcxeApFa0H- http://127.0.0.1:8000/api/lifecycle/current | \
  python3 -c "
import json, sys
d = json.load(sys.stdin)
lc = d.get('lifecycle')
print('lifecycle:', 'null (legacy filtered)' if lc is None else type(lc).__name__)
print('message:', d.get('message'))
"

# 4. 等下次 pipeline_run 进 PLANNED+(取决于 evidence),
#    review_reports 表会在 lifecycle 关闭时自动新增
SSH
```

---

## 五、§X / §Y / §Z 自检

### §X(旧代码必须删除 / 不重复)
- 不重写 `ReviewReportGenerator.generate` / `generate_and_save`(保留)
- 只新增 `generate_for_lifecycle` + `maybe_generate_for_closed_lifecycle`
- `LifecycleManager.compute_post_sm` 重构为 wrapper + `_dispatch_post_sm`(纯逻辑)
  以便插入 DAO upsert,**没有**重写状态过渡分支(只把 FLIP_WATCH → *_PLANNED 加进
  现有 PLANNED 创建分支)
- legacy 占位检测在两处:`_read_previous_lifecycle`(state_builder)和
  `/api/lifecycle/current`(防 1.5b-B 部署前残留)

### §Y
本 commit 立即 push。

### §Z 端到端断言
- 11 个测试都用真 SQLite + 真 schema + DAO upsert / SELECT 断言
- API 测试用真 TestClient + 真 conn_factory
- e2e reversal 7 步真推 build_state_machine_fields + LifecycleManager.compute_post_sm +
  state_machine.compute_next,断言:
  - 每步 state_machine.current_state 正确
  - lifecycles 表行数 / 状态正确演进
  - review_reports 表在 archive 后 +1
  - 第 7 步 lifecycle_id != 旧(确认是新 lc)

### 同类风险扫描
1. **`LifecyclesDAO.upsert` 失败** — try/except 包,只 log warning,
   `compute_post_sm` 仍返回 in-memory dict
2. **每次都 upsert(active 也写)** — sqlite UPSERT 单条几 ms 级,微观影响可忽略;
   好处是 active lc 也能在 `/api/lifecycle/history` 查到
3. **`/api/lifecycle/history` 排序** — 用 `entry_time_utc DESC NULLS LAST`,
   pending_open(无 entry_time)排在末尾
4. **`prev_cycle_side` 兜底** — 归档时 `_archive_lifecycle` 把 `direction` 镜像;
   `_prev_cycle_side` 还有 fallback 看 `lifecycle.direction`,双重保护
5. **`generate_for_lifecycle` review_id 唯一** — 用 `{lc_id}_{utc_iso}`,
   `ON CONFLICT(review_id) DO UPDATE` 保证幂等(同一 lc 多次触发也不会爆表)
6. **总 runs 计数** — `_count_runs_during_lifecycle` SELECT COUNT 真查表
   (区间 entry-exit),不靠估算
7. **`auto_review_on_close` stage 异常** — 用 `_safe` 包,失败只记 fallback log,
   pipeline 仍跑完

---

## 六、改动文件

| 文件 | 改动 |
|---|---|
| `src/data/storage/dao.py` | 新增 LifecyclesDAO 类(upsert / get / list)|
| `src/strategy/lifecycle_manager.py` | conn 入参 + compute_post_sm wrapper 接 DAO + FLIP_WATCH→PLANNED 分支 + archive 镜像 prev_cycle_side |
| `src/strategy/state_machine_inputs.py` | _prev_cycle_side 兜底 direction;long/short_thesis_invalidated 接受显式输入 + inv_side 用 prev_cycle_side |
| `src/review/generator.py` | _to_bjt_pretty + generate_for_lifecycle + maybe_generate_for_closed_lifecycle + _count_runs_during_lifecycle |
| `src/pipeline/state_builder.py` | __init__ 实例化 review_generator + auto_review_on_close stage |
| `src/api/routes/lifecycle.py` | /current legacy 占位过滤 |
| `tests/test_lifecycle_dao_and_review.py` | 新文件 10 测试 |
| `tests/test_lifecycle_e2e_reversal.py` | 新文件 1 个 7 步推进 |

---

## 七、未覆盖项

- **dimensional_assessment 4 维度真实评估** — v1 占位 `"v1 unevaluated"`,
  v1.x 复盘工具细化(L1/L2/L3/L4 各自贡献度需要更细的 transition history)
- **完整 outcome_type 10+ 类**(C/D/E/H/I/J/X)— v1 仍是 4 类
- **/api/review/by-lifecycle/{lc_id}** API 端点 — 留 v1.x;目前 `ReviewReportsDAO.get_reports_for_lifecycle` 已可用
