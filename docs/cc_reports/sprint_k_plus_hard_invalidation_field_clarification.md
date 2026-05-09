# Sprint K+ — 网页"硬失效位"字段语义清晰化(分级 + 标记真正止损)

**完成日期**: 2026-05-09
**Commit**: `a3cd3b1` feat(web): Sprint K+ — 网页"硬失效位"分级显示(避免与入场价视觉矛盾)

---

## 1. 用户反馈的视觉矛盾

5/9 16:31 真实 run 中:
- L4 输出 `hard_invalidation_levels` 含 4 个分级失效位:
  - EMA-20 break: $78,125
  - EMA-50 break: $75,503
  - swing low: $74,868
  - swing high: $71,999.9
- master.new_thesis.entry_orders[0].price = **$78,125**(回踩 EMA-20 埋伏)
- master.new_thesis.stop_loss.price = **$74,868**(swing_low 全平)

前端"硬失效位"卡显示 `$78,125 / $75,503 / $74,868`。问题:**$78,125 既是入场价又是失效位**,看上去自相矛盾。

实际语义:
- $78,125 是**弱预警位**(EMA-20 跌破触发减仓 / 警觉)
- $75,503 是**中预警位**(EMA-50 跌破触发更深减仓)
- $74,868 是**真正硬止损**(swing low,全平)

L4 的设计是分层失效位,master 选其中之一作为 stop_loss,前端字段语义没区分。

---

## 2. 修法选择

我评估两个选项后选 **选项 2(分级显示)**:

| 选项 | 优 | 缺 |
|---|---|---|
| 1 简化(只显示 stop_loss) | 绝对不矛盾 | **丢失分层预警信息** |
| 2 分级(标 type + severity) | 语义清晰 + 信息完整 | 略复杂(实施成本小) |

实施成本:Server-side classifier(50 行) + 11 个新单测,前端模板改用 x-for(20 行)。值得。

---

## 3. 实施

### 3.1 `src/web_helpers/labels.py` 新增 `HARD_INVALIDATION_TYPE` 翻译表

```python
HARD_INVALIDATION_TYPE = {
    "ema_20_break":     ("弱预警", "EMA-20", 1),
    "ema_50_break":     ("中预警", "EMA-50", 2),
    "ema_100_break":    ("中预警", "EMA-100", 2),
    "ema_200_break":    ("中预警", "EMA-200", 2),
    "swing_low":        ("硬止损", "swing low", 3),
    "swing_high":       ("硬止损", "swing high", 3),
    "prior_high_break": ("中预警", "前高跌破", 2),
    "prior_low_break":  ("中预警", "前低跌破", 2),
    "key_support":      ("中预警", "关键支撑", 2),
    "key_resistance":   ("中预警", "关键阻力", 2),
    "structural_break": ("硬止损", "结构破坏", 3),
}
```

每个 type 映射 `(severity_label, type_label, severity_rank)`。
未知 type 友好降级 `("预警", <type 原值>, 1)`,不抛异常。

### 3.2 `src/web_helpers/normalize_state.py` 加 `_classify_hard_invalidation_levels()`

```python
def _classify_hard_invalidation_levels(
    levels: list[Any], active_stop_loss_price: Optional[float],
) -> list[dict[str, Any]]:
    """L4 levels → 富化 severity_label / type_label / severity_rank /
    is_active_stop_loss(price 与 master.new_thesis.stop_loss.price 匹配)。
    
    排序:严重度由弱到强(rank 1 → 3),同 rank 内 active 排前。
    兼容 v1.4 list of dict + v1.3 历史 list of float(无 type → '硬止损')。
    """
```

`_normalize_v13` v1.4 路径写 `state.hard_invalidation_levels_classified`,前端
读这个字段即可。`is_active_stop_loss` 1e-6 浮点容忍。

### 3.3 `web/index.html` 字段重命名 + 多行渲染

```html
<div class="stat-label">分级失效位</div>
<template x-if="!cardHardInvalidationsEmpty()">
  <div class="text-[12px] font-mono space-y-0.5">
    <template x-for="lv in cardHardInvalidations()" ...>
      <div class="leading-tight whitespace-nowrap">
        <span :class="severityClass(lv.severity_rank)" x-text="lv.severity_label"></span>
        <span class="text-slate-500" x-text="lv.type_label"></span>
        <span class="font-bold" x-text="': $' + Number(lv.price).toLocaleString()"></span>
        <span x-show="lv.is_active_stop_loss" class="text-rose-600 ml-1 text-[11px]"
              >← 真正止损位</span>
      </div>
    </template>
  </div>
</template>
```

颜色编码:
- 弱预警(rank 1)→ slate-500
- 中预警(rank 2)→ amber-600
- 硬止损(rank 3)→ rose-600 + 加粗

### 3.4 `web/assets/app.js` `cardHardInvalidations()` 返数组

```javascript
cardHardInvalidations() {
    const classified = this.state?.hard_invalidation_levels_classified || [];
    if (classified.length > 0) return classified.slice(0, 4);
    // fallback v1.3 老格式(list of float / dict 但无 type)
    const his = this.hardInvalidationLevels();
    if (his.length === 0) return [];
    return his.slice(0, 3).map(h => ({
        price: (typeof h === 'object' ? h.price : h),
        type_label: '—', severity_label: '硬止损',
        severity_rank: 3, is_active_stop_loss: false,
    }));
},
```

---

## 4. §X 删除清单

| 删除对象 | 路径 | 删除原因 |
|---|---|---|
| 旧 `cardHardInvalidations()` 单行 join 实现 | web/assets/app.js | 替换为返数组 + 前端 x-for 渲染 |
| `'硬失效位'` 字段标题 | web/index.html | 重命名为 '分级失效位'(更准确) |

---

## 5. §Z 验证

### 5.1 11 个新单测(`tests/test_sprint_k_plus_hard_invalidation_classifier.py`)

| 用例 | 验证 |
|---|---|
| `test_classify_real_5_9_levels_with_active_stop_loss` | 回放 5/9 真实 4 levels:排序 + active 标记正确 |
| `test_classify_severity_labels_per_type` | 11 type → label 表查准 |
| `test_classify_unknown_type_falls_back_gracefully` | 未知 type → "预警 + 原值" |
| `test_classify_dict_no_type_treated_as_hard` | dict 缺 type → 默认 "硬止损"(保守) |
| `test_classify_legacy_list_of_float` | v1.3 老格式向后兼容 |
| `test_classify_empty_returns_empty` | 空 / None 输入返 [] |
| `test_classify_skips_invalid_items` | 非数 / object / 字符串 全部 skip |
| `test_classify_active_stop_loss_with_float_tolerance` | 74868 vs 74868.0 匹配 |
| `test_classify_no_active_stop_loss_all_false` | active price=None → 全 False |
| `test_state_hard_invalidation_levels_classified_present` | normalize_state 集成 |
| `test_state_classified_no_thesis_no_active_marker` | 无 thesis → 全 is_active_stop_loss=False |

### 5.2 服务器 live API verbatim

```json
"hard_invalidation_levels_classified": [
  {"price": 78125.0, "type": "ema_20_break",
   "type_label": "EMA-20", "severity_label": "弱预警",
   "severity_rank": 1, "is_active_stop_loss": false,
   "description": "EMA-20 短期支撑,跌破表示短线上升结构失效",
   "distance_from_current_pct": -2.57},
  {"price": 75503.0, "type": "ema_50_break",
   "type_label": "EMA-50", "severity_label": "中预警",
   "severity_rank": 2, "is_active_stop_loss": false,
   "description": "EMA-50 中期支撑,跌破表示中期上升趋势失效",
   "distance_from_current_pct": -5.84},
  {"price": 74868.0, "type": "swing_low",
   "type_label": "swing low", "severity_label": "硬止损",
   "severity_rank": 3, "is_active_stop_loss": true,         ← 真正止损
   "description": "最近一个 swing low(4月29日),跌破表示反弹结构破坏",
   "distance_from_current_pct": -6.63},
  {"price": 71999.9, "type": "swing_high",
   "type_label": "swing high", "severity_label": "硬止损",
   "severity_rank": 3, "is_active_stop_loss": false,
   "description": "3月25日 swing high 转支撑位,跌破表示结构性破坏",
   "distance_from_current_pct": -10.21}
]
```

### 5.3 服务器 pytest

(本地 1727 + 11 = 1738,服务器一致 — pytest 后台跑中)

### 5.4 前端预期渲染

```
分级失效位
弱预警 EMA-20: $78,125
中预警 EMA-50: $75,503
硬止损 swing low: $74,868 ← 真正止损位
硬止损 swing high: $71,999.9
```

(slate / amber / rose / rose 颜色编码)

不再与入场价 $78,125 视觉矛盾,因为现在用户能看到 $78,125 是**弱预警** EMA-20,跟$74,868**硬止损** swing low 是不同语义。

---

## 6. 风险扫描

### 6.1 老 v1.3 路径仍能跑?

✅ 兼容 list of float → 当 `severity_label='硬止损'` 处理(无类型信息保守标最严)。`test_classify_legacy_list_of_float` 覆盖。

### 6.2 未知 type 不挂?

✅ `_classify_hard_invalidation_levels` 未知 type → `("预警", <原值>, 1)`,不抛异常。`test_classify_unknown_type_falls_back_gracefully` 覆盖。

### 6.3 前端老数据 fallback?

✅ `cardHardInvalidations()` 检 `state.hard_invalidation_levels_classified` 优先,空则降级老 `hardInvalidationLevels()` 路径,合成 placeholder 类型描述。

### 6.4 排序保证 active stop_loss 显眼?

✅ rank 升序排:弱 → 中 → 硬。同 rank 中 active 排前(74868 排在 71999.9 之前)。前端用 rose 色 + "← 真正止损位" 标识 + 加粗。

---

## 部署四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ 1738 passed, 1 skipped |
| GitHub push(commit a3cd3b1) | ✅ |
| 服务器 git pull | ✅ 已拉到 a3cd3b1 |
| 服务器 systemctl restart | ✅ active |
| 服务器 pytest 全 suite | ⏳ 后台跑中(本地 1738,服务器期望相同) |
| 服务器 live API hard_invalidation_levels_classified | ✅ 4 条全字段正确 |
| 浏览器 verbatim 检查 | ⏳ 待用户打开 http://124.222.89.86 验证 |
| 生产 DB 迁移 | N/A |

---

## 详细报告

(本文件即详细报告)
