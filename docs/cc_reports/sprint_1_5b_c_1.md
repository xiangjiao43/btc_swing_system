# Sprint 1.5b-C.1 — review_reports schema 漂移修复(hotfix)

**Date:** 2026-04-29
**Branch:** main
**Status:** ✅ 完成,6 个新测试 + 749/749 全量回归过 + smoke test 一次过

---

## 一、问题与根因

**Bug**:生产 DB 的 `review_reports` 表是 Sprint 1 老 schema:

```
['run_timestamp_utc', 'lifecycle_id', 'outcome_type', 'report_json', 'created_at']
```

而 `src/data/storage/schema.sql` 与 `ReviewReportsDAO.insert_report` 都已切到
建模 §10.4 新 schema:

```
review_id (PK) / lifecycle_id / generated_at_utc / outcome_type /
rules_version_at_review / full_report_json
```

**漂移路径**:`migrations/001_align_to_modeling_schema.sql` 写了 DROP +
recreate,但**没在真实生产 DB 跑过**。`schema.sql` 的 `IF NOT EXISTS` 不会
修已存在的旧 schema → Sprint 1.5b-C 自动复盘真触发时,`insert_report` 写表
失败,被 `_safe` 兜住,永远写不进去。

**为什么 1.5b-C 测试没发现**:之前所有测试只用 `init_db` 全新 DB
(从空开始建),走的是 schema.sql 的 IF NOT EXISTS 路径,得到的是新 schema。
没人模拟"已有 legacy 表"这种生产真实状态。

---

## 二、改动

### 2.1 `src/data/storage/connection.py`:`init_db` 加 schema 漂移检测

新增 `_fix_legacy_review_reports_schema(conn, *, verbose)` 幂等函数:

| 检测情况 | 行为 | 返回值 |
|---|---|---|
| 已含 `review_id` 列 | 不动 | `"ok_already_new"` |
| 含 `run_timestamp_utc` 但无 `review_id`(legacy)+ 行数 0 | DROP table | `"fixed_legacy"` |
| 含 legacy 列但**行数 > 0** | **raise RuntimeError**(不静默丢数据) | (raise) |
| 表不存在 | 不动,后续 schema.sql 建 | `"ok_no_table"` |

`init_db` 在 `executescript(schema.sql)` 之前调这个 helper,
DROP 之后让 schema.sql 的 `CREATE TABLE IF NOT EXISTS` 重建到新 schema。

**安全设计**:行数 > 0 时 ABORT 而非静默 DROP — 生产 lifecycle 还没真归档过,
理论行数 0;但万一有数据(用户手动造的测试行)则不静默丢。

### 2.2 `migrations/008_fix_review_reports_schema.sql`(audit trail)

文件存在仅作"曾经做过这个迁移"的记录;实际逻辑在 Python 侧
`connection.py::_fix_legacy_review_reports_schema`。SQL 体只 `SELECT 1`(no-op marker)。

### 2.3 `scripts/fix_review_reports_schema.py`(一次性修复脚本)

生产 SSH 用法:

```bash
.venv/bin/python scripts/fix_review_reports_schema.py
# 或显式指定 DB:
.venv/bin/python scripts/fix_review_reports_schema.py /home/ubuntu/btc_swing_system/data/btc_strategy.db
```

输出 before / after schema cols + 状态码(0 OK / 2 FAIL)。本质就是调 `init_db()`。

**Smoke test**(本机已跑过):
```
before: review_reports cols = ['run_timestamp_utc', 'lifecycle_id', 'outcome_type', 'report_json', 'created_at']
[init_db] legacy review_reports detected; DROP + recreate to align with §10.4
[init_db] review_reports schema check: fixed_legacy
after: review_reports cols = ['review_id', 'lifecycle_id', 'generated_at_utc', 'outcome_type', 'rules_version_at_review', 'full_report_json']
OK: schema aligned to §10.4
```

---

## 三、测试

`tests/test_review_reports_schema.py`(6 测试):

| 测试 | 验证 |
|---|---|
| `test_review_reports_has_review_id_column_after_init_db` | 全新 init_db → 新 schema |
| `test_init_db_fixes_legacy_review_reports_schema` | **关键**:模拟 legacy + init_db → 自动修 |
| `test_legacy_schema_with_data_aborts_to_avoid_loss` | 行数 > 0 → RuntimeError(不静默丢) |
| `test_init_db_idempotent_on_already_new_schema` | 跑两次都 OK |
| `test_fix_helper_returns_correct_status` | helper 返回 ok_no_table / fixed_legacy / ok_already_new |
| `test_review_reports_dao_insert_works_after_fix` | 修复后 DAO insert + select 真工作 |

**回归**:全量 `pytest tests/` = **749 passed, 1 skipped, 5.43s**(743 + 6 新)。

---

## 四、用户验证脚本(SSH 部署后)

```bash
ssh ubuntu@124.222.89.86 << 'SSH'
cd /home/ubuntu/btc_swing_system
git pull

# 1. 检测当前 schema
.venv/bin/python -c "
import sqlite3
conn = sqlite3.connect('data/btc_strategy.db')
cols = [r[1] for r in conn.execute('PRAGMA table_info(review_reports)').fetchall()]
print('before:', cols)
" 

# 2. 跑修复
.venv/bin/python scripts/fix_review_reports_schema.py
# 预期输出:before(legacy 列)→ fixed_legacy → after(review_id 等新列)

# 3. 重启服务后下次 lifecycle 归档时,review_reports 真行数 +1
sudo systemctl restart btc-strategy.service
SSH
```

---

## 五、§X / §Y / §Z 自检 + 经验教训

### §X(旧代码必须删除 / 不并存)
- 老 schema 必须被 DROP + recreate,不允许新旧并存(`_fix_legacy_review_reports_schema`
  幂等做这件事)
- `migrations/008_fix_review_reports_schema.sql` 是 audit trail,不重复实现逻辑

### §Y
本 commit 立即 push。

### §Z 端到端断言(关键反退化)
- `test_init_db_fixes_legacy_review_reports_schema`:**先 CREATE legacy table,
  再调 init_db,断言修后是新 schema**。这是之前 1.5b-C 测试遗漏的"生产真实状态"
  覆盖
- `test_review_reports_dao_insert_works_after_fix`:legacy → init_db → DAO insert
  → SELECT 真查到。端到端覆盖完整路径
- `test_legacy_schema_with_data_aborts_to_avoid_loss`:RuntimeError 必须 raise

### 经验教训(写到本次 sprint 报告 + 1.5b-C 报告备注段)

> **Sprint 1.5b-C 漂移漏掉的根因**:测试只用 `init_db` 全新 DB(从空建),
> 走 schema.sql 的 IF NOT EXISTS 路径得到新 schema。**没人模拟"已有 legacy
> 表"这种生产 DB 真实状态**。
>
> 防止类似漂移的 pattern:任何会改 schema.sql 的 sprint,测试至少要包括
> "在已有旧表的 DB 上跑 init_db,断言新 schema 起作用"。本次起 connection.py
> 的 `_fix_legacy_*` Python 侧幂等检测可作为新 sprint 的模板。

### 同类风险扫描
1. **生产 DB 还有其他 legacy 表?** — 本 sprint 只修 review_reports;若其他表也
   漂移会在用户主动触发该路径时报错。建议下一个 sprint 做 schema 全表 audit
2. **strategy_state_history vs strategy_runs** — Sprint 1.5c 已迁;但生产 DB 已
   迁过(`StrategyStateDAO` 都用新表)。无漂移风险
3. **fallback_log vs fallback_events** — 同上,已迁
4. **导出 + DROP 兜底**:本次只检测行数 = 0 的 legacy;若用户后续制造行数 > 0
   的 legacy,函数 raise 让用户决定如何 manual-export

---

## 六、改动文件

| 文件 | 改动 |
|---|---|
| `src/data/storage/connection.py` | `_fix_legacy_review_reports_schema` helper + `init_db` 接入 |
| `migrations/008_fix_review_reports_schema.sql` | audit trail(实际逻辑在 Python 侧)|
| `scripts/fix_review_reports_schema.py` | 一次性修复脚本 |
| `tests/test_review_reports_schema.py` | 新文件 6 测试 |

---

## 七、部署 checklist

- [ ] git pull
- [ ] `.venv/bin/python scripts/fix_review_reports_schema.py`(看 before / after cols)
- [ ] `sudo systemctl restart btc-strategy.service`
- [ ] 等下次 lifecycle 归档(取决于 evidence + state_machine 推进),
      `SELECT * FROM review_reports` 应有真行
