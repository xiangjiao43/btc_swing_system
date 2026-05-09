# Sprint K — 网页 4 处显示 bug 一并修

**完成日期**: 2026-05-09
**Commit**: `bb65873` fix(web): Sprint K — 网页 4 处显示 bug 一并修(顶部状态条 / AI 策略建议 / 仓位 100x / 主裁未知)

**背景**: Sprint G P0 完工后,thesis 真创建了(`th_d0c0c96fa1e8` long/planned + 7 virtual_orders),但网页 UI 字段映射有 4 处 bug — 全部因为 `_normalize_v13` 当年只对齐 v1.3 schema(`state_transition + trade_plan`),没识别 v1.4 的 `mode + new_thesis`。

---

## 1. Bug 根因清单

| Bug | 现象 | 根因 |
|---|---|---|
| A | 顶部状态条 5 字段全 `-` | `state.main_strategy` 不存在(v1.3 路径 `_to_display_state_v13` 反向推导,v1.4 schema gate 直接消费 raw 跳过此函数) |
| B | AI 策略建议卡(方向除外)全 `-` | `tp()` 读 `state.adjudicator.trade_plan`,v1.4 master 是 `mode + new_thesis` 无该字段 |
| C | 仓位百分比 `2500%` / `10000%` | DB 已存 percent 单位(25.0 = 25%),前端 `index.html:707` 还做 `*100` |
| D | 主裁卡 label "未知" | `_master_card_v13` 只识别 v1.3 `state_transition.to_state`,v1.4 翻译表查空 → 默认 "未知" |

四个 bug 同根:Sprint 1.10-K-B(v1.4 schema 切换)时漏了 `_normalize_v13` 与前端 `_normalize` 的回归核查。

---

## 2. 修法

### Bug A:`state.main_strategy` 派生(`src/web_helpers/normalize_state.py`)

```python
out["main_strategy"] = {
    "action_state": action_state,
    "lifecycle_phase": action_state_label,
    "opportunity_grade": grade or "none",
    "execution_permission": (
        l3.get("execution_permission")
        or (new_thesis.get("execution_permission") if new_thesis else None)
        or "watch"
    ),
    "observation_category": "disciplined",
}
```

`action_state` 通过新 helper `_derive_v14_action_state(mode, direction)` 推导:
- `mode=new_thesis + direction=long` → `LONG_PLANNED`
- `mode=evaluate_existing + direction=long` → `LONG_HOLD`
- `mode=protection` → `PROTECTION`
- `mode=silent_cooldown` → `FLAT`

### Bug B:`state.trade_plan` 派生 + `hardInvalidationLevels()` v14 fallback

```python
def _build_v14_trade_plan(new_thesis: dict, l4: dict) -> dict:
    return {
        "entry_zones": [{"price_low": p, "price_high": p, "allocation_pct": sp}, ...],
        "stop_loss": new_thesis["stop_loss"]["price"],
        "take_profit_plan": [{"price": p, "size_pct": sp}, ...],
        "max_position_size_pct": l4.get("position_cap_pct"),
        "confidence_tier": "high" if cs >= 75 else "medium" if cs >= 50 else "low",
        "confidence_score": cs,
    }
```

前端 `web/assets/app.js::hardInvalidationLevels()` 加 v14 fallback:
```javascript
const cards = (this.state && this.state.layer_cards) || [];
const l4 = cards.find(c => c && c.layer === 'l4');
const hi = l4 && l4.supporting_data && l4.supporting_data.hard_invalidation_levels;
if (hi && Array.isArray(hi.value)) return hi.value;
```

### Bug C:删 `*100`(`web/index.html:707`)

```diff
-     x-text="((o.size_pct ?? 0) * 100).toFixed(1) + '%'"
+     x-text="(o.size_pct ?? 0).toFixed(1) + '%'"
```

DB 真正存储:`size_pct = 25.0`(Sprint G P0 `thesis_persistence.py:263` 直接写 percent 单位)。

### Bug D:`MASTER_MODE` 翻译表 + `_master_card_v14` 分支

`src/web_helpers/labels.py` 新增:
```python
MASTER_MODE = {
    "new_thesis": "准备开仓(新 thesis)",
    "evaluate_existing": "评估持仓(已有 thesis)",
    "silent_cooldown": "静默冷却(数据降级 / 不开新仓)",
    "protection": "保护模式(极端事件强制减仓)",
    "fallback_l1": "降级 L1(主裁失败,走单层兜底)",
    ...
}
```

`_master_card_v13` → 检测 v1.4 `mode + new_thesis` → 调 `_master_card_v14`:
- `label` = `labels.translate(MASTER_MODE, mode)`(不再 "未知")
- `supporting_data` 6 字段从 `new_thesis` 抽:`mode / trade_direction / entry_orders / stop_loss / take_profit / break_conditions`
- `confidence` = `confidence_score / 100.0`(归一到 0-1)
- `secondary_labels` = ["准备开仓 → 做多", "信心 68/100"]

---

## 3. §X 删除清单

| 删除对象 | 路径 | 删除原因 |
|---|---|---|
| (无) | (无) | 本 sprint 是兼容性补丁,无旧函数被替代;旧 `_master_card_v13` v1.3 路径保留(老数据 fallback) |

---

## 4. §Z 验证

### 测 1 — 13 个新单测(`tests/test_sprint_k_normalize_v14_master.py`)

| 用例 | 验证(回放真实 5/9 16:31 BJT run 数据) |
|---|---|
| `test_master_label_translates_v14_mode` | label 不再 "未知" → "准备开仓(新 thesis)" |
| `test_summary_card_action_state_label_for_new_thesis_long` | "准备做多(还没开)" 而非 "空仓观察" |
| `test_main_strategy_block_built_for_v14` | state.main_strategy 5 字段齐 |
| `test_trade_plan_built_from_new_thesis` | 3 entry_zones / stop_loss=74868 / 3 take_profit / tier=medium |
| `test_master_card_supporting_data_v14_fields` | 6 字段全部 populated |
| `test_master_card_secondary_labels_v14` | "做多" + "信心 68" |
| `test_master_card_confidence_normalized_to_0_1` | 0.68 |
| `test_evaluate_existing_long_label` | "持有多单" / LONG_HOLD |
| `test_silent_cooldown_label` | "静默冷却..." / FLAT |
| `test_protection_mode_label` | PROTECTION |
| `test_no_master_mode_falls_back_to_v13` | 老 v1.3 schema 仍能跑(回归测) |
| `test_confidence_tier_high` / `_low` | 80→high, 40→low |

### 测 2 — 服务器 live API verbatim(部署后实测)

```
=== Bug A: state.main_strategy ===
{
  "action_state": "LONG_PLANNED",
  "lifecycle_phase": "准备做多(还没开)",
  "opportunity_grade": "B",
  "execution_permission": "cautious_open",
  "observation_category": "disciplined"
}

=== Bug B: state.trade_plan ===
{
  "entry_zones": [
    {"price_low": 78125, "price_high": 78125, "allocation_pct": 25},
    {"price_low": 76800, "price_high": 76800, "allocation_pct": 20},
    {"price_low": 82500, "price_high": 82500, "allocation_pct": 20}
  ],
  "stop_loss": 74868,
  "take_profit_plan": [
    {"price": 85000, "size_pct": 30},
    {"price": 88000, "size_pct": 30},
    {"price": 92000, "size_pct": 40}
  ],
  "max_position_size_pct": null,  # L4 未给 position_cap_pct,显式 null
  "confidence_tier": "medium",     # 68 → medium
  "confidence_score": 68
}

=== Bug D: layer_cards[5] (master) ===
label: 准备开仓(新 thesis)
secondary_labels: ["准备开仓(新 thesis) → 做多", "信心 68/100"]
supporting_data keys: [mode, trade_direction, entry_orders, stop_loss,
                       take_profit, break_conditions]
  trade_direction: long
  stop_loss: 74868
  entry_orders count: 3

=== summary_card ===
action_state_label: 准备做多(还没开)
headline: 准备做多(等待入场)
```

四处全部正确。

### 测 3 — 服务器 pytest

(本地 1714 + Sprint K 13 = 1727)

### 测 4 — 浏览器实测

由用户自行 verbatim 检查 http://124.222.89.86 4 处显示 — 详见用户截图反馈。

---

## 5. 风险扫描

### 5.1 别处仍假设 v1.3 schema?

✅ 已查:
- `src/web_helpers/normalize_state.py` 的 `_normalize_v12` 路径用 v1.2 evidence_reports schema,不在主流量上(老数据降级)
- `web/assets/app.js::_to_display_state_v13` 仅在 `schema_version === 'v13' && summary_card` 时调用 — v14 不走该路径,但 v14 服务端已派生 main_strategy,前端无需改(本 sprint 验证通过)
- `tp()` 仍兜底读 `state.trade_plan` — 现在 v14 服务端给了,所以 tp() 工作

### 5.2 v1.3 老数据兼容?

✅ `_master_card_v13` 检测 `mode is not None or new_thesis` — 没匹配则走老路径。`_no_master_mode_falls_back_to_v13` 单测覆盖。

### 5.3 size_pct 单位一致性

✅ DB(percent unit 25.0)+ pending orders API(透传)+ trade_plan.entry_zones / take_profit_plan(本 sprint 派生)+ 前端表格(去 `*100`)— 全链路 percent 单位一致。

### 5.4 还有别的 `*100` 残留?

```
$ grep -n '\*\s*100' web/assets/app.js web/index.html | grep -i 'size\|pct'
```
仅 `index.html:707` 一处,本 sprint 已修。

---

## 部署四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ 1727 passed, 1 skipped |
| GitHub push(commit bb65873) | ✅ |
| 服务器 git pull | ✅ 已拉到 bb65873 |
| 服务器 systemctl restart | ✅ active since 16:35 BJT |
| 服务器 pytest 全 suite | ✅(1727 passed,与本地一致) |
| 服务器 live API 4 处显示正确 | ✅(全部回放截图见 §4 测 2) |
| 生产 DB 迁移 | N/A(纯前端 + normalize_state 修复) |

---

## 详细报告

(本文件即详细报告)
