# Sprint 1.5c.2 — composite_composition value=None 写死接通(剩余 4 项 missing)

**Date:** 2026-04-29
**Branch:** main
**Status:** ✅ 完成,6 个新测试 + 771/771 全量回归过

---

## 一、问题

Sprint 1.5c / 1.5c.1 修了 L1/L2 字段 export,但用户网页截图发现 4 项仍 missing:

- 长周期位置卡:**LTH Supply 90d 变化** = "—"
- 拥挤度卡:**资金费率 30 日分位** + **OI 24h 变化** = "—"
- 宏观逆风卡:**DXY 20 日 / US10Y 30 日 / 纳指 20 日** = "—"

诊断后根因:**`composite_composition.py` 在构建 composition 数组时,这 4
项的 `value` 字段直接写死 None**。底层 composite 因子(cycle_position /
crowding / macro_headwind)真算了这些数值,只是没接通到展示层。

数据真实状态(SSH):onchain.lth_supply 180 天 ✅,derivatives funding/OI 271 行
✅,macro 各 60+ 行 ✅。

---

## 二、改动

### 任务 A:`src/composite/cycle_position.py`

在已有 `lth_90d_chg`(0.0234 这种小数)基础上,产出 `lth_90d_chg_pct`(乘 100 + round 2):
- 顶层字段 `lth_90d_chg_pct` 新增
- `diagnostics["lth_90d_chg_pct"]` 也加(双 alias 兜底)

`composite_composition._cycle_position`:
- `onchain_lth_supply` 的 value 改为 `cp.get("lth_90d_chg_pct") or _lookup(cp.diagnostics, "lth_90d_chg_pct")`

### 任务 B:`src/composite/crowding.py`

`compute` 内部已经为打分计算了 `pct`(funding 30d 分位)和 `chg`(OI 24h 变化),
本次保存到局部 `funding_30d_pctile` / `oi_24h_change_pct`(都是百分比),
返回 dict 末尾新增 `"diagnostics": {funding_rate_30d_pctile, oi_24h_change_pct}`。

`composite_composition._crowding`:
- `derivatives_funding_rate_30d_pctile` value 改为 `_lookup(cr.diagnostics, "funding_rate_30d_pctile")`
- `derivatives_oi_24h_change` value 改为 `_lookup(cr.diagnostics, "oi_24h_change_pct")`

### 任务 C:`src/strategy/composite_composition.py::_macro_headwind`

`macro_headwind.py` 已经在 `diagnostics` 里有 `dxy_20d_change /
us10y_30d_change_bp / nasdaq_20d_change / btc_nasdaq_corr`,本次只在
composite_composition 接通(读 `mh.diagnostics`):
- `macro_dxy_20d_change` value = `_to_pct(diag.dxy_20d_change)`(0.025 → 2.5)
- `macro_us10y_30d_change` value = `_round_or_none(diag.us10y_30d_change_bp, 2)`(已是 bp)
- `macro_nasdaq_20d` value = `_to_pct(diag.nasdaq_20d_change)`
- `macro_btc_nasdaq_corr` value = `_round_or_none(diag.btc_nasdaq_corr, 3)`

新增模块级 helper `_to_pct(v)`(0.0234 → 2.34)和 `_round_or_none(v, n)`。

---

## 三、测试

`tests/test_composite_composition_value_pipeline.py`(6 测试):

| 测试 | 验证 |
|---|---|
| `test_cycle_position_exports_lth_90d_chg_pct` | 120 天 LTH series → cycle_position 顶层 + diagnostics 都有 lth_90d_chg_pct |
| `test_composite_composition_cycle_lth_value_not_none` | 真 cp.compute → composite_composition 注入后 onchain_lth_supply.value 是数值 |
| `test_crowding_diagnostics_funding_pctile_and_oi` | crowding.compute diagnostics 含 funding_rate_30d_pctile(0-100)+ oi_24h_change_pct |
| `test_composite_composition_crowding_values_not_none` | 接通后 derivatives_funding_rate_30d_pctile + derivatives_oi_24h_change 不是 None |
| `test_composite_composition_macro_headwind_values_not_none` | dxy_20d_change / us10y_30d_change_bp / nasdaq_20d_change 全部到 composition.value |
| **`test_all_six_missing_values_filled_when_data_sufficient`** | **关键反退化 guard**:6 项 user-reported missing 在数据充足时全部不为 None |

**回归**:全量 `pytest tests/` = **771 passed, 1 skipped, 5.01s**(765 + 6 新)。

---

## 四、用户验证脚本(SSH 部署后)

```bash
ssh ubuntu@124.222.89.86 << 'SSH'
cd /home/ubuntu/btc_swing_system
git pull
sudo systemctl restart btc-strategy.service
sleep 5

# 等下次 pipeline_run 跑完(取决于 cron 时刻),验证 6 项 value
.venv/bin/python -c "
import sqlite3, json
conn = sqlite3.connect('data/btc_strategy.db')
row = conn.execute(
    'SELECT full_state_json FROM strategy_runs '
    'ORDER BY reference_timestamp_utc DESC LIMIT 1'
).fetchone()
state = json.loads(row[0])
cf = state.get('composite_factors') or {}

def value_of(name, fid):
    for it in (cf.get(name) or {}).get('composition') or []:
        if it.get('factor_id') == fid: return it.get('value')
    return 'NOT FOUND'

print('LTH Supply 90d:', value_of('cycle_position', 'onchain_lth_supply'))
print('Funding 30d 分位:', value_of('crowding', 'derivatives_funding_rate_30d_pctile'))
print('OI 24h:', value_of('crowding', 'derivatives_oi_24h_change'))
print('DXY 20d:', value_of('macro_headwind', 'macro_dxy_20d_change'))
print('US10Y 30d:', value_of('macro_headwind', 'macro_us10y_30d_change'))
print('纳指 20d:', value_of('macro_headwind', 'macro_nasdaq_20d'))
"
# 全部应为数字,不是 None / NOT FOUND
SSH
```

---

## 五、§X / §Y / §Z 自检

### §X(只暴露已计算值,不重写计算逻辑)
- `cycle_position` `_pct_change_90d(lth_supply)` 不动,只把结果乘 100 暴露
- `crowding` 打分逻辑不动,只把内部 `pct` / `chg` 同步保存到 output diagnostics
- `macro_headwind` 完全不动,composite_composition 直接读已有 diagnostics
- 没双 key 名扩散:cycle_position 的 `lth_90d_chg_pct` 顶层 + diagnostics 是
  alias(指向同一个 round 后的数值);composition_composition 优先顶层后兜底

### §Y
本 commit 立即 push。

### §Z 端到端断言
- `test_all_six_missing_values_filled_when_data_sufficient`:同时跑 3 个 composite
  + composite_composition 注入,断言 6 项 user-reported missing 都不为 None
- 单项测试都用真 pandas Series(120/60 天充足)+ 真 compute,不只 mock

### 同类风险扫描
1. **`cycle_position.lth_90d_chg = None`(数据不足)** — `lth_90d_chg_pct` 也是
   None,前端继续 "—"(预期降级)
2. **crowding funding < 30 行** — `funding_30d_pctile = None` → composition.value
   None;但生产现有 271 行,触发率高
3. **macro_headwind nasdaq < 20 行** — `nasdaq_20d_change = None` → 同上
4. **`_to_pct` 边界**:小数 0.025 → 2.5(2 位精度);bp 字段(us10y_30d_change_bp)
   不走 `_to_pct`,直接 `_round_or_none(..., 2)`,因为它已是 bp 单位

---

## 六、改动文件

| 文件 | 改动 |
|---|---|
| `src/composite/cycle_position.py` | output 加 `lth_90d_chg_pct`(顶层 + diagnostics)|
| `src/composite/crowding.py` | compute 内保存 `funding_30d_pctile` + `oi_24h_change_pct`,output 加 `diagnostics` 字段 |
| `src/strategy/composite_composition.py` | 4 处 `value=None` 改为读真值;新 helpers `_to_pct` + `_round_or_none` |
| `tests/test_composite_composition_value_pipeline.py` | 新文件 6 测试 |

---

## 七、未覆盖项

- 用户截图剩余 missing(L4 失效位 / L5 v0.5)同 1.5c,留下 sprint
