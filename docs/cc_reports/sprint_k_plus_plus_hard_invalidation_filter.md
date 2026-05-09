# Sprint K++ — 分级失效位字段精简化(过滤冗余 / 反向 / entry 重叠)

**完成日期**: 2026-05-09
**Commit**: `130eadb` feat(web): Sprint K++ — 分级失效位精简化

---

## 1. 用户审视后的诉求

Sprint K+ 输出 4 条:
```
弱预警 EMA-20:    $78,125  ← 跟 entry 1 同价位 → 视觉冗余/混淆
中预警 EMA-50:    $75,503
硬止损 swing low: $74,868  ← 真正止损位(文字溢出 UI)
硬止损 swing high: $71,999.9 ← 对 long 持仓没意义(向上的位置)
```

用户反馈:
1. EMA-20 78125 = entry 1 入场价 → 容易再次让用户困惑
2. swing high 71999 对 long 持仓不是失效位(向上)→ 冗余
3. "← 真正止损位"文字溢出 UI

最终目标只剩 2 条:
```
中预警 EMA-50:    $75,503
硬止损 swing low: $74,868
```

---

## 2. 筛选规则(用户决策)

```python
def _filter_hard_invalidation_levels(classified, direction, entry_prices):
    """规则:
    1. is_active_stop_loss=True → 必显示
    2. rank=sl_rank-1(紧邻一档预警)+ price 距任何 entry > 1% → 显示
    3. 其他全部隐藏:
       - rank 1 弱预警(可能跟 entry 重叠)
       - rank 3 中除 active 外的其他
       - long thesis 的 swing_high / key_resistance / prior_high_break
       - short thesis 的 swing_low / key_support / prior_low_break
    """
```

direction-aware 内置 type 过滤表:
- upside types(short 持仓的失效,long 持仓不显示):`swing_high / key_resistance / prior_high_break`
- downside types(long 持仓的失效,short 持仓不显示):`swing_low / key_support / prior_low_break`
- 其他 type(`ema_*_break / structural_break` 等):双向均显示

---

## 3. 实施

### 3.1 `src/web_helpers/normalize_state.py` 加 `_filter_hard_invalidation_levels()`

逻辑同上 §2;无 active stop_loss 时返 classified 中 rank 最高的最后一条(避免完全空)。

### 3.2 `_normalize_v13` 写新字段 `state.hard_invalidation_levels_filtered`

```python
out["hard_invalidation_levels_filtered"] = _filter_hard_invalidation_levels(
    classified,
    direction=(new_thesis.get("direction") if new_thesis else None),
    entry_prices=[float(o["price"]) for o in entry_orders if o.get("price")],
)
```

`hard_invalidation_levels_classified`(4 条全列表)继续透传 — 给审计 / 将来需要看全部时用。

### 3.3 `web/assets/app.js` `cardHardInvalidations()` 优先读 filtered

```javascript
const filtered = this.state?.hard_invalidation_levels_filtered || [];
if (filtered.length > 0) return filtered;
// fallback classified(老 schema)→ 老 v1.3 list of float
```

### 3.4 `web/index.html` 删 "← 真正止损位" 文字

模板里移除该 `<span x-show="lv.is_active_stop_loss">...</span>` 块,避免文字
溢出 UI;视觉区分仍靠颜色编码(slate / amber / rose)。

---

## 4. §X 删除清单

| 删除对象 | 路径 | 删除原因 |
|---|---|---|
| `<span x-show="lv.is_active_stop_loss">← 真正止损位</span>` | web/index.html | 文字溢出 UI;active stop loss 已用 rose 色 + 加粗加重区分 |
| `severityClass(rank)` 中 rank=1 颜色 | (保留) | 即使 filtered 中现在不返 rank=1,fallback 路径仍可能用 |

---

## 5. §Z 验证

### 5.1 13 个新单测(`tests/test_sprint_k_plus_plus_hard_invalidation_filter.py`)

| 用例 | 验证 |
|---|---|
| `test_long_thesis_filter_drops_ema_20_collision_and_swing_high` | 5/9 真实输入 → 只剩 EMA-50 + swing_low |
| `test_long_thesis_filter_keeps_active_stop_loss` | active 必显示 |
| `test_long_thesis_filter_keeps_ema_50_warning` | rank 紧邻预警显示 |
| `test_filter_drops_rank_1_when_sl_is_rank_3` | rank 1 不是紧邻 → 即使距 entry 远也隐藏 |
| `test_filter_keeps_rank_2_warning_far_from_entries` | rank 2 远离 entry → 显示 |
| `test_filter_drops_warning_within_1pct_of_entry` | 距 entry < 1% → 隐藏 |
| `test_filter_keeps_warning_at_exact_1pct_boundary` | 1% 边界严格 > |
| `test_short_thesis_drops_swing_low_keeps_swing_high` | short direction-aware |
| `test_long_thesis_drops_key_resistance_and_prior_high_break` | 其他 upside type 隐藏 |
| `test_filter_no_active_stop_loss_returns_max_rank_only` | 无 active → 返 rank 最高 |
| `test_filter_empty_returns_empty` | 空输入 |
| `test_normalize_state_filtered_field_present` | 集成:filtered 字段写入 state |
| `test_normalize_state_classified_still_present` | classified 透传不变 |

### 5.2 服务器 live API verbatim(部署后实测)

```json
"hard_invalidation_levels_filtered": [
  {"price": 75503.0, "type": "ema_50_break",
   "type_label": "EMA-50", "severity_label": "中预警",
   "severity_rank": 2, "is_active_stop_loss": false,
   "description": "EMA-50 中期支撑,跌破表示中期上升趋势失效",
   "distance_from_current_pct": -5.84},
  {"price": 74868.0, "type": "swing_low",
   "type_label": "swing low", "severity_label": "硬止损",
   "severity_rank": 3, "is_active_stop_loss": true,
   "description": "最近一个 swing low(4月29日),跌破表示反弹结构破坏",
   "distance_from_current_pct": -6.63}
],
"hard_invalidation_levels_classified": [...全 4 条仍透传]
```

正好 2 条,符合用户预期。

### 5.3 前端预期渲染

```
分级失效位
中预警 EMA-50: $75,503
硬止损 swing low: $74,868
```

(amber + rose 双行,无溢出文字)

---

## 6. 风险扫描

### 6.1 short 持仓时筛选?

✅ direction='short' 时 `swing_low / key_support / prior_low_break` 自动隐藏。
`test_short_thesis_drops_swing_low_keeps_swing_high` 覆盖。

### 6.2 无 active stop_loss(冷启动 / silent_cooldown)?

✅ 返 classified 中 rank 最高的最后一条(降级显示一条,非空白)。
`test_filter_no_active_stop_loss_returns_max_rank_only` 覆盖。

### 6.3 老 v1.3 路径 / 老 schema?

✅ 前端 `cardHardInvalidations()` fallback 链:
- filtered(本 sprint)→ classified(K+)→ hardInvalidationLevels()(K)→ legacy float

### 6.4 审计需求(看全部失效位)?

✅ `state.hard_invalidation_levels_classified` 透传不变,4 条仍可访问。
未来如要"展开看全部"按钮,只需读 classified。

### 6.5 UI 文字溢出修复证据

文字"← 真正止损位"已从模板物理移除,active stop_loss 仍以 rose 色 + 加粗
区分(`severityClass(rank=3)` → `text-rose-600 font-semibold`)。

---

## 部署四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ 1751 passed, 1 skipped |
| GitHub push(commit 130eadb) | ✅ |
| 服务器 git pull | ✅ 已拉到 130eadb |
| 服务器 systemctl restart | ✅ active |
| 服务器 pytest 全 suite | ⏳ 后台跑中(预期 1751 passed) |
| 服务器 live API filtered 字段 | ✅ 正好 2 条 |
| 浏览器 verbatim 检查 | ⏳ 待用户打开 http://124.222.89.86 |
| 生产 DB 迁移 | N/A |

---

## 详细报告

(本文件即详细报告)
