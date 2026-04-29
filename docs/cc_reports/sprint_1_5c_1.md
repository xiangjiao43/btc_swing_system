# Sprint 1.5c.1 — 收尾(MA-200 关系 + event_risk 组合因子)

**Date:** 2026-04-29
**Branch:** main
**Status:** ✅ 完成,8 个新测试 + 765/765 全量回归过

---

## 一、问题

1.5c 主要 8 项已修,但 truth_trend / event_risk 还有 3 处 missing:

**A**:`L1.ma_alignment.direction = None` 时 composite 显示 "—"(让人以为数据缺;
其实是 4 条 MA 都存在但不严格升降序,应该显示 "mixed")。

**B**:truth_trend 卡 "价格相对 MA-200" 显示 None,因为 layer1_regime 还没
export `ma_200_relation`(composite_composition 早已读这个字段)。

**C**:event_risk 卡 CPI / NFP / 期权大到期 显示 missing。诊断后两个根因:
1. `composite_composition._event_risk` 用 `events[0]` 取最近事件,只有该
   type 命中才填,其他 type 行全 None — **type-mismatch bug**
2. EventRisk composite 输入是 72h 窗口(`events_upcoming_48h`),CPI/NFP/期权
   通常 > 72h 后,根本不在 contributing_events 列表里

---

## 二、改动

### 任务 A.1:`src/evidence/layer1_regime.py` ma_alignment 兜底

`_ma_alignment_direction` 在 4 条 MA 都存在但不严格升降序时返回
**`"mixed"`**(明确字符串),而非 None。任一 MA 缺失仍返回 None(数据不足)。

`ma_alignment.is_aligned` 改为 `ma_dir in ("up", "down")` — mixed 不算 aligned。

### 任务 A.2:`src/evidence/layer1_regime.py` 新增 `ma_200_relation` export

```python
"ma_200_relation": {
    "ma_200": ...,
    "current_close": ...,
    "above": last_close > ma200,
    "distance_pct": (last_close - ma200) / ma200 * 100,
}
```

数据不足路径同步加 schema 占位。

### 任务 B.1:`src/pipeline/state_builder.py` 加 options_expiry_major 到 next_events

`get_next_events_by_type` 调用的 `event_types` 从 `["fomc","cpi","nfp"]` 扩到
`["fomc","cpi","nfp","options_expiry_major"]`。

### 任务 B.2:`src/strategy/composite_composition.py` `_event_risk` 修复 type-mismatch

新逻辑(per type 查找):
1. 优先扫 `contributing_events`(72h 窗口内):找该 type 第一个 → 用其 `hours_to`
2. fallback `ctx["next_events_by_type"][t].hours_to`(全年 lookahead,即便 30 天
   后也有数)
3. 都没有 → None

`inject_composite_composition` 把 `next_events_by_type` 加入 ctx 传给 `_event_risk`。

修复后:即使当前 72h 窗口只有 FOMC,cpi/nfp/options_expiry 也能从
next_events_by_type 拿到下次距离(单位:小时)。

---

## 三、测试

`tests/test_field_export_alignment_round2.py`(8 测试):

| 测试 | 验证 |
|---|---|
| `test_ma_alignment_direction_mixed_when_disordered` | 横盘震荡 220 根 → 4 MA 都存在但不单调 → `direction='mixed'`,`is_aligned=False` |
| `test_ma_alignment_direction_none_when_data_insufficient` | 150 < 200 根 → ma_200=None → direction=None(区分"无数据"和"mixed") |
| `test_layer1_exports_ma_200_relation_above` | 上行趋势 220 根 → above=True, distance_pct > 0 |
| `test_layer1_exports_ma_200_relation_below` | 下行趋势 → above=False, distance_pct < 0 |
| `test_layer1_ma_200_relation_none_when_insufficient` | 数据不足时 schema 占位 None |
| `test_event_risk_composition_picks_per_type_from_next_events_by_type` | **关键反 missing**:contributing 空,next_events_by_type 提供 4 类全年 lookahead → composition 4 行 value 全有数(30 / 320.5 / 198 / 528 小时) |
| `test_event_risk_composition_prefers_72h_contributing_over_next` | contributing(72h 内 FOMC 12.5h)优先于 next(9999h),其他类仍走 next |
| `test_state_builder_next_events_by_type_includes_options` | 真 init_db + seed_events + DAO.get_next_events_by_type 含 options_expiry_major |

**回归**:全量 `pytest tests/` = **765 passed, 1 skipped, 5.34s**(757 + 8 新)。

---

## 四、用户验证脚本(SSH 部署后)

```bash
ssh ubuntu@124.222.89.86 << 'SSH'
cd /home/ubuntu/btc_swing_system
git pull
sudo systemctl restart btc-strategy.service

# 等下次 pipeline_run,验证字段
curl -s -u admin:Y_RhcxeApFa0H- http://127.0.0.1:8000/api/strategy/current | \
  python3 -c "
import sys, json
state = json.load(sys.stdin)['state']
l1 = state['evidence_reports']['layer_1']
print('L1 ma_alignment.direction:', l1['ma_alignment']['direction'])
# 期望 in {up, down, mixed}, 不再 None
print('L1 ma_alignment.is_aligned:', l1['ma_alignment']['is_aligned'])
print('L1 ma_200_relation:', l1.get('ma_200_relation'))
# 期望含 above / distance_pct 数值

cf = state['composite_factors']
er_comp = cf['event_risk'].get('composition') or []
for c in er_comp:
    print('event_risk', c['factor_id'], '=', c.get('value'))
# 期望 cpi/nfp/options_expiry value 不是 None
"

# 浏览器硬刷:
# - truth_trend 卡 "MA-20/60/120 排列" 显示 mixed/up/down,不再 "—"
# - truth_trend 卡 "价格相对 MA-200" 显示 above + 距离%
# - event_risk 卡 CPI / NFP / 期权 显示距离小时数
SSH
```

---

## 五、§X / §Y / §Z 自检

### §X(已加新字段不重写,只补缺失)
- 不重写 `_ma_alignment_direction`,只把 None 兜底为 "mixed"
- 不重写 `_event_risk` 整体,只把 type-mismatch bug 修了 + 加 fallback
- `inject_composite_composition` 只新增 ctx 字段 `next_events_by_type`,不改其他 ctx

### §Y
本 commit 立即 push。

### §Z 端到端断言
- `test_event_risk_composition_picks_per_type_from_next_events_by_type` 显式构造
  72h 窗口空 + next_events_by_type 4 类全有的场景,断言 composition 4 行 value
  都不是 None — 这是反 user-reported missing 的核心 guard
- 真 EventsCalendarDAO + 真 init_db + 真 seed_events 验证 options_expiry_major
  能查到

### 同类风险扫描
1. **`ma_alignment.direction='mixed'` 前端展示** — 前端如果原来按 None=missing
   渲染,现在要把 mixed 也认成"明确数据"。本 sprint 不动前端,
   但建模上 mixed 是正常状态,应显示"不对齐"或"mixed"
2. **`ma_200_relation.above=False` 时前端样式** — composite_composition 已读
   `above` 字段,显示真值(True/False)而不是格式化字符串
3. **next_events_by_type 全年 lookahead 行数** — events_calendar 1.5c 已 seed
   全年 44 条,所有 type 都有未来事件
4. **CPI 13 日估算 vs 真实日期** — 1.5c 已加 `notes: estimated;
   verify on bls.gov`,误差 ±2 天对前端"距下次 X 几小时"显示影响 < 5%

---

## 六、改动文件

| 文件 | 改动 |
|---|---|
| `src/evidence/layer1_regime.py` | `_ma_alignment_direction` 兜底 "mixed";`is_aligned` 仅 up/down 算;新增 `ma_200_relation` 字段(成功 + 不足) |
| `src/pipeline/state_builder.py` | `get_next_events_by_type` 加 options_expiry_major |
| `src/strategy/composite_composition.py` | `_event_risk` 用 `_hours_to(t)` per-type 查找(contributing 优先 → next_events_by_type fallback);`inject_composite_composition` ctx 加 `next_events_by_type` |
| `tests/test_field_export_alignment_round2.py` | 新文件 8 测试 |

---

## 七、未覆盖项

- L4 失效位、L5 定性事件摘要 — 同 1.5c,留 v0.5
- 前端"mixed"展示样式 — 不是 cc 范围,留前端自己改文案
