# Sprint 1.5c.5 — 修 _build_structured_macro_rule 字段名 mismatch(1.5c.4 漏修)

**Date:** 2026-04-29
**Branch:** main
**Status:** ✅ 完成,7 个新测试 + 798/798 全量回归过

---

## 一、问题与教训

1.5c.4 部署后 SSH 验证 `structured_macro` 仍是空 dict,但 791 测试全过。
诊断后定位是 helper 字段名跟生产真实输出对不上 — **经典"测试 fixture 用假字段,
绕过 bug"事故**。

### 字段名对比

| helper 读取 | 实际真名(layer5_macro 内部 helper 输出) |
|---|---|
| `btc_nasdaq_corr.correlation_60d` | `btc_nasdaq_corr.coefficient` ❌ |
| `btc_nasdaq_corr.amplified` | (不存在) |

VIX 字段 1.5c.4 已 fallback 处理(`level or regime` / `latest_value or latest`),
但 `btc_nasdaq_corr` 没修。

### 1.5c.4 测试为什么没抓到

`tests/test_l5_structured_macro_round2.py::test_build_structured_macro_full_data`
fixture 写了:
```python
btc_nasdaq_corr = {"correlation_60d": 0.45, "amplified": False}  # 假字段
```
helper 读这个假字段返回 `{"value": 0.45, "amplified": False}`,测试 assert
`sm["btc_nasdaq_corr"]["value"] == 0.45` 通过。**生产真实数据的 `coefficient`
字段 helper 永远读不到 → 永远 None**。

---

## 二、改动

### 任务 A:`src/evidence/layer5_macro.py::_build_structured_macro_rule`

把 `btc_nasdaq_corr` 改为读真名 `coefficient` 并**展开为 float**:

```python
# BTC-纳指相关性 — _compute_btc_nasdaq_correlation 真实返回
# {coefficient, strength_label, lookback_days, n_samples}
if isinstance(btc_nasdaq_corr, dict):
    coef = btc_nasdaq_corr.get("coefficient")
    if coef is not None:
        sm["btc_nasdaq_corr"] = float(coef)
elif isinstance(btc_nasdaq_corr, (int, float)):
    sm["btc_nasdaq_corr"] = float(btc_nasdaq_corr)
```

VIX entry 同时显式优先真名 `level` / `latest_value`(`regime` / `latest` 仍兼容),
顺手把 `is_spike` 也 export(展示更丰富)。

### 任务 B:`src/evidence/pillars.py::_pillars_l5`

把 `corr` 取值从读 `corr["value"]`(老 dict 形态)改为兼容 float / dict 两种:
```python
corr = structured.get("btc_nasdaq_corr")
corr_val = None
if isinstance(corr, (int, float)):
    corr_val = float(corr)
elif isinstance(corr, dict):
    cv = corr.get("coefficient") or corr.get("value")
    try:
        corr_val = float(cv) if cv is not None else None
    except (TypeError, ValueError):
        corr_val = None
if corr_val is not None:
    pieces.append(f"BTC-NDX corr={corr_val:.2f}")
```

### 任务 C:更新 1.5c.4 翻车测试 + 新增真实 fixture 测试

`tests/test_l5_structured_macro_round2.py::test_build_structured_macro_full_data`:
fixture 字段名换成真实(`coefficient` / `level` / `latest_value`),断言改为
`sm["btc_nasdaq_corr"] == 0.45`(不再 dict)。

新文件 `tests/test_l5_structured_macro_round3.py`(7 测试)用**生产 SSH 实测拷贝
的 fixture 常量** `_PROD_DXY_TREND` / `_PROD_VIX_REGIME` / `_PROD_BTC_NASDAQ_CORR`
做测试输入,确保未来任何 helper 改动直接对真实生产 shape 验证。

---

## 三、测试

`tests/test_l5_structured_macro_round3.py`(7 测试):

| 测试 | 验证 |
|---|---|
| `test_helper_with_production_field_names` | 用 `_PROD_*` 常量(SSH 实测拷贝)→ DXY/US10Y/VIX/btc_nasdaq_corr 全字段值正确 |
| `test_helper_btc_nasdaq_corr_unwraps_dict_to_float` | dict + coefficient → float;**反退化 guard** |
| `test_helper_btc_nasdaq_corr_accepts_plain_float_too` | 直接传 float → 也接受 |
| `test_helper_vix_uses_level_and_latest_value` | VIX 真名 level/latest_value → entry 正确(防回退) |
| `test_e2e_layer5_compute_to_pillars_l5_status_ok` | 真跑 Layer5Macro.compute 120 天 → sm 4 类全有 + corr 是 float + pillars ok |
| `test_pillars_l5_corr_float_in_interp` | sm.btc_nasdaq_corr=0.4403(float)→ interp "BTC-NDX corr=0.44" |
| `test_pillars_l5_corr_dict_legacy_compat` | 老 dict 形态({value, amplified})也能解析(向后兼容) |

**回归**:全量 `pytest tests/` = **798 passed, 1 skipped, 5.11s**(791 + 7 新)。

---

## 四、用户验证脚本(SSH 部署后)

```bash
ssh ubuntu@124.222.89.86 << 'SSH'
cd /home/ubuntu/btc_swing_system
git pull
sudo systemctl restart btc-strategy.service
sleep 5

.venv/bin/python -c "
import sqlite3, json
conn = sqlite3.connect('data/btc_strategy.db')
row = conn.execute(
    'SELECT full_state_json FROM strategy_runs '
    'ORDER BY reference_timestamp_utc DESC LIMIT 1'
).fetchone()
state = json.loads(row[0])
l5 = state['evidence_reports']['layer_5']
sm = l5.get('structured_macro') or {}
print('structured_macro keys:', list(sm.keys()))
for k, v in sm.items():
    print(f'  {k}: {v}')
for p in l5.get('pillars') or []:
    if p.get('id') == 'structured_macro':
        print(f'pillar status: {p.get(\"status\")}')
        print(f'pillar interp: {p.get(\"interpretation\")}')
"
# 预期:
# structured_macro keys: ['DXY', 'US10Y', 'VIX', 'btc_nasdaq_corr', 'data_completeness_pct']
# DXY: {'trend': 'falling', 'magnitude_30d_pct': -0.01512, 'latest': 99.x}
# US10Y: {'trend': 'rising', 'magnitude_30d_pct': 0.02837, 'latest': 4.x}
# VIX: {'regime': 'normal', 'latest': 18.02, 'is_spike': False}
# btc_nasdaq_corr: 0.4403  ← float
# data_completeness_pct: 90.0
# pillar status: ok
# pillar interp: DXY=99.x; US10Y=4.x; VIX=18.02; BTC-NDX corr=0.44
SSH
```

---

## 五、§X / §Y / §Z 自检

### §X(只修字段名,不再造)
- helper 单点(`_build_structured_macro_rule`),改读真字段名
- `_pillars_l5` 加 dict / float 双形态兼容(老形态向后兼容)
- 不动业务计算 / AI 启用路径

### §Y
本 commit 立即 push。

### §Z 端到端断言 + **测试 fixture 必须用真生产格式**
- 新文件用 `_PROD_DXY_TREND` / `_PROD_VIX_REGIME` / `_PROD_BTC_NASDAQ_CORR`
  常量(SSH 实测拷贝),禁止用假字段名造测试输入
- 端到端测试真跑 `Layer5Macro.compute` 120 天数据,从输出取 sample 验证
- 1.5c.4 翻车测试 fixture 已修(`correlation_60d` → `coefficient`)

### 教训(写入 sprint 报告 + 后续 §Z 自检模板)

> **"测试 fixture 必须用上游真实输出格式"** — 任何 helper 接受其他模块的 dict
> 输出时,测试输入的 dict key 名必须从该上游 helper 实际返回的 dict 抄,
> 不能凭空造。1.5c.4 翻车的根因是测试用 `correlation_60d` 这种凭空捏的 key,
> 让 helper 字段名 mismatch bug 测试通过但生产仍空。
>
> **修复模式**:写测试时优先用 helper 真实返回值做 fixture 常量,
> 或定义 `_PROD_<thing>` 常量并加注释标注"SSH 实测拷贝"。

---

## 六、改动文件

| 文件 | 改动 |
|---|---|
| `src/evidence/layer5_macro.py` | `_build_structured_macro_rule` btc_nasdaq_corr 用 `.coefficient` 展开为 float;VIX 显式优先 `level`/`latest_value`+`is_spike` |
| `src/evidence/pillars.py` | `_pillars_l5` corr 解析兼容 float / dict 两种形态 |
| `tests/test_l5_structured_macro_round2.py` | 修 1.5c.4 测试用真字段名(`coefficient` / `level` / `latest_value`)+ 断言 corr 为 float |
| `tests/test_l5_structured_macro_round3.py` | 新文件 7 测试(全部用 `_PROD_*` 常量做 fixture)|

---

## 七、未覆盖项

- 1.5c 系列(.0/.1/.2/.3/.4/.5)修了用户截图所有 missing
- L5 AI 启用 timeline 留 v0.5
