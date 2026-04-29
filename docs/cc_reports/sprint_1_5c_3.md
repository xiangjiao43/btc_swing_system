# Sprint 1.5c.3 — 五层证据链 4 项 missing 修复(展示分类 + L5 规则路径)

**Date:** 2026-04-29
**Branch:** main
**Status:** ✅ 完成,12 个新测试 + 783/783 全量回归过

---

## 一、问题与根因

用户截图显示五层证据链 4 项 missing,根因不一:

| 项 | 根因 | 类别 |
|---|---|---|
| L2 相对位置 | phase=unclear 时被标 missing,但底层 `impulse_extension_ratio=1.026` 已真算出 | 展示分类 |
| L4 结构性失效位 | stance=neutral 时建模 §4.5.4 主动返回空 list(设计:不挂硬止损),但展示 missing 误导 | 展示分类 |
| L5 结构化宏观 | layer5_macro 规则路径写死 `structured_macro={}`,虽然 dxy_trend / yields_trend / vix_regime / btc_nasdaq_corr 都已算 | 数据接通 |
| L5 定性事件摘要 | v0.5 设计不产出,展示 missing 让人误以为出问题 | 展示分类 |

跟 1.5c.1 修 ma_alignment="mixed" 同思路:**把"已计算但结果不明"或"按设计不产出"
和"真数据缺"区分开**。

---

## 二、改动

### 任务 A:`src/evidence/pillars.py::_pillars_l2` 相对位置

`phase=unclear` 走"已算扩展但结果不明"分支,显示 `"波段位置不明确(扩展 103%,
多档并列)"`,`status="ok"`。`phase=n_a` 才是真 missing(stance=neutral 没算波段)。

`pct_pct = pct_of_move * 100` 修正显示:`{pct_pct:.0f}%` 现在能显示 "103%"
而非旧 "1%"(原 `f"{pct_of_move:.0f}%"` 把 1.026 直接 round 是 bug 的副产物)。

### 任务 B:`src/evidence/pillars.py::_pillars_l4` 失效位

签名加 `l2_stance: Optional[str] = None`。

- 有失效位 → `status="ok"`(原行为)
- 失效位空 + `l2_stance in ("neutral", None)` → **`status="ok"`**,
  interp `"方向中性,系统不挂硬止损位(等 stance 明确为多/空才生效)"`
- 失效位空 + 有方向(bullish/bearish)→ `status="missing"`,真问题
  (swing 数据不足)

`inject_pillars` 调用时从 `state.evidence_reports.layer_2.stance` 读 stance 传入。

### 任务 C:`src/evidence/layer5_macro.py` rule 路径填 `structured_macro`

抽出 module-level helper `_build_structured_macro_rule(...)`,把已计算的
`dxy_trend / yields_trend / vix_regime / btc_nasdaq_corr` 汇总成 dict:

```python
{
  "DXY":   {"trend": "rising", "magnitude_30d_pct": 1.5, "latest": 105.5},
  "US10Y": {"trend": "stable", "magnitude_30d_pct": 0.6, "latest": 4.3},
  "VIX":   {"regime": "normal", "latest": 18.0},
  "btc_nasdaq_corr": {"value": 0.45, "amplified": false},
  "data_completeness_pct": 80.0,
}
```

替换原 `"structured_macro": {}` 占位。AI 启用路径(`rule_output.update(...)`)
保持不变 — AI 输出会覆盖规则路径的基础版。

### 任务 D:`src/evidence/pillars.py::_pillars_l5` 定性事件摘要

无 AI 摘要时 `status="ok"`(按设计不产出),interp:`"AI 定性事件摘要为
v0.5 启用功能,规则路径不产出(设计行为)"`。

### Bug fix(顺手):

`_pillars_l2` 老代码 `f"扩展 {pct_of_move:.0f}%"` 把 1.026 ratio 显示成 "1%"
是显示 bug,本次乘 100 修正(impulse_extension_ratio 是 ratio 不是百分比)。

---

## 三、测试

`tests/test_pillars_status_classification.py`(12 测试):

| 测试 | 验证 |
|---|---|
| `test_l2_relative_position_unclear_is_ok_status` | unclear + extension 1.026 → ok + "扩展 103%" |
| `test_l2_relative_position_n_a_is_missing` | phase=n_a → missing(真没算波段) |
| `test_l2_relative_position_ok_with_clear_phase` | phase=mid + 0.7 → ok + "扩展 70%" |
| `test_l4_invalidation_neutral_stance_is_ok_status` | hard_inv=[] + stance=neutral → ok + "方向中性" |
| `test_l4_invalidation_no_stance_is_ok_status` | l2_stance=None → 同上 ok |
| `test_l4_invalidation_bullish_no_levels_is_missing` | stance=bullish 但失效位空 → missing(真问题) |
| `test_l4_invalidation_with_levels_is_ok` | 有 P1 失效位 → ok + 显示价格 |
| `test_l5_structured_macro_filled_in_rule_path` | 真 Layer5Macro.compute 120 天 macro → structured_macro 含 DXY/US10Y/VIX 各自有 latest |
| `test_l5_pillars_structured_macro_ok_when_filled` | structured_macro 非空 → status=ok |
| `test_l5_qualitative_summary_v05_is_ok` | active_event_summaries=[] → ok + 含 "v0.5" |
| `test_l5_qualitative_summary_with_ai_summaries` | 有 AI 摘要 → ok + "2 条" |
| **`test_inject_pillars_clears_four_missing_when_data_sufficient`** | **关键反退化 guard**:模拟当前生产状态(stance=neutral, phase=unclear, hard_inv=[], structured_macro 已填),`inject_pillars` 后 4 项 missing 全为 ok |

**回归**:全量 `pytest tests/` = **783 passed, 1 skipped, 5.44s**(771 + 12 新)。

---

## 四、用户验证脚本(SSH 部署后)

```bash
ssh ubuntu@124.222.89.86 << 'SSH'
cd /home/ubuntu/btc_swing_system
git pull
sudo systemctl restart btc-strategy.service
sleep 5

# 等下次 pipeline_run,验证 5 层 pillars
.venv/bin/python -c "
import sqlite3, json
conn = sqlite3.connect('data/btc_strategy.db')
row = conn.execute(
    'SELECT full_state_json FROM strategy_runs '
    'ORDER BY reference_timestamp_utc DESC LIMIT 1'
).fetchone()
state = json.loads(row[0])
for layer_id in (2, 4, 5):
    l = state['evidence_reports'].get(f'layer_{layer_id}', {})
    print(f'L{layer_id} pillars:')
    for p in l.get('pillars') or []:
        print(f'  {p.get(\"name\")}: status={p.get(\"status\")}, '
              f'interp={(p.get(\"interpretation\") or \"\")[:60]}')
"
# 预期:
# L2 相对位置: status=ok
# L4 结构性失效位: status=ok(stance=neutral 时,interp 含"方向中性")
# L5 结构化宏观: status=ok(含 DXY/US10Y/VIX latest)
# L5 定性事件摘要: status=ok(interp 含 v0.5)

# 浏览器硬刷:五层证据链卡 4 个 missing 标记全消失
SSH
```

---

## 五、§X / §Y / §Z 自检

### §X(只改展示 + 规则路径填基础数据,不改业务逻辑)
- L4 `_build_hard_invalidation_levels` 在 stance=neutral 时返回空 list 的纪律
  保持(建模 §4.5.4)— 只改 pillars 的展示分类
- L5 AI 启用路径 `rule_output.update(...)` 不动 — AI 输出仍可覆盖规则版
  structured_macro
- `_pillars_l2` `pct_of_move:.0f}%` 老 bug 顺手修(1.026 ratio 显示 1% → 103%)

### §Y
本 commit 立即 push。

### §Z 端到端断言
- `test_inject_pillars_clears_four_missing_when_data_sufficient`:
  **核心反退化 guard**,模拟当前生产真实状态(stance=neutral, phase=unclear,
  hard_inv 空)+ structured_macro 已填,断言 4 项原 missing 全 ok
- `test_l5_structured_macro_filled_in_rule_path`:**真跑 Layer5Macro.compute**
  120 天 macro 数据 → 断言 structured_macro 含 DXY/US10Y/VIX 各自 `latest`
  数值

### 同类风险扫描
1. **`_pillars_l4` 默认 `l2_stance=None`** — 调用方未传时当作 neutral,
   保持向后兼容
2. **structured_macro 规则路径仍有 `data_completeness_pct` 字段** — 前端显示
   时多一行没影响
3. **VIX latest 字段名** — `_compute_vix_regime` 返回 `latest_value`(老
   key),helper 用 `latest_value or latest` 兜底,future-proof
4. **`pct_of_move:.0f}%` 显示 1% bug** — 修了之后老前端如有 hardcode 1% 字样
   测试不会触发(无此 case);但若用户已习惯看 1%,新版 103% 会跳变,
   是 expected 修复

---

## 六、改动文件

| 文件 | 改动 |
|---|---|
| `src/evidence/pillars.py` | `_pillars_l2` unclear → ok + 修 *100 显示 bug;`_pillars_l4` 加 `l2_stance=` 参数 + neutral 时 ok;`_pillars_l5` qualitative_events 永远 ok;`inject_pillars` 把 l2.stance 传给 _pillars_l4 |
| `src/evidence/layer5_macro.py` | 新 `_build_structured_macro_rule` helper,rule 路径 `structured_macro` 不再空 dict |
| `tests/test_pillars_status_classification.py` | 新文件 12 测试 |

---

## 七、未覆盖项

- 1.5c 系列(.0 / .1 / .2 / .3)修了用户截图所有 missing。L4 失效位有方向但
  swing 不足、L5 AI 启用 timeline 留 v0.5 sprint
