# Sprint 1.5c.4 — 1.5c.3 收尾(L2 phase=n_a + L5 structured_macro 真实填充)

**Date:** 2026-04-29
**Branch:** main
**Status:** ✅ 完成,8 个新测试 + 791/791 全量回归过

---

## 一、问题

1.5c.3 部署后 SSH 验证发现 4 项 missing 中还有 2 项 status=missing:

**问题 1:L2 相对位置**
当前生产 phase 不是 unclear 而是 `n_a`。1.5c.3 把 unclear 改成 ok,但 n_a 仍
判 missing。**事实**:`n_a` 是 layer2_direction 在 stance=neutral 时主动设
的标准枚举(看 `_compute_specific` 末尾 `phase = "n_a" if stance == "neutral"`),
跟 L4 失效位 neutral 时空 list 一样是设计行为,不是数据缺。

**问题 2:L5 structured_macro 显示空**
1.5c.3 写了 `_build_structured_macro_rule` helper,但生产 keys=[]。诊断后
有两层原因:
1. helper 严苛过滤:dxy_trend 是 None 时整个 DXY sub-dict 不填(即便 macro
   还有 dxy series 可读 latest)
2. `_pillars_l5` 判断 `if structured` 为真,但 1.5c.3 起 helper 总是会写
   `data_completeness_pct=...` sentinel,导致 dict truthy 但实际无可显示数据
   → 走 ok 分支但 `pieces=[]` 导致 interp = "已就绪但字段未命名"(假象 ok)

---

## 二、改动

### 任务 A:`src/evidence/pillars.py::_pillars_l2` 把 `n_a` 改 ok

```python
elif phase == "n_a":
    # n_a 是 layer2_direction 在 stance=neutral 时主动设的标准枚举
    # (设计行为,跟 L4 失效位 neutral 同思路)— 不是数据缺
    pos_interp = "波段位置 n/a(方向中性时不输出阶段)"
    pos_status = "ok"
```

### 任务 B:`src/evidence/layer5_macro.py::_build_structured_macro_rule` 放松过滤

每个字段独立判断,只要有 trend OR latest 任一即填:
- DXY:`dxy_trend is not None or dxy_latest is not None` → 填 entry
  (entry 内只放有数据的 sub-key,无的不放)
- US10Y:同 DXY
- VIX:vix_regime is not None 时,内部按 regime / latest 各自判断
- btc_nasdaq_corr:有 dict 就填
- `data_completeness_pct`:总是写入(给 _pillars_l5 提示)

### 任务 C:`src/evidence/pillars.py::_pillars_l5` 过滤 sentinel

```python
real_keys = [
    k for k in structured
    if k != "data_completeness_pct" and structured.get(k) is not None
]
if real_keys:
    pieces = []
    for k in ("DXY", "US10Y", "VIX"):
        v = structured.get(k)
        if isinstance(v, dict):
            latest = v.get("latest")
            if latest is not None:
                pieces.append(f"{k}={latest}")
    corr = structured.get("btc_nasdaq_corr")
    if isinstance(corr, dict) and corr.get("value") is not None:
        pieces.append(f"BTC-NDX corr={float(corr['value']):.2f}")
    sm_interp = "; ".join(pieces) if pieces else f"已就绪({len(real_keys)} 项)"
    sm_status = "ok"
else:
    sm_interp = "结构化宏观指标未就绪(macro 数据 0 项可用)"
    sm_status = "missing"
```

**关键差别**:
- 旧:`if structured` 真假判断(总是真)
- 新:`real_keys` 过滤掉 `data_completeness_pct` sentinel + None 值
- interp 改为读 `v.latest`(数值)而非把整个 sub-dict 拼字符串

---

## 三、测试

### `tests/test_l5_structured_macro_round2.py`(8 个新测试)

| 测试 | 验证 |
|---|---|
| `test_build_structured_macro_partial_dxy_only` | 只 dxy series → DXY entry + sentinel,US10Y/VIX 不在 sm 里 |
| `test_build_structured_macro_full_data` | 全有 → 4 类 key 都填,字段值正确 |
| `test_build_structured_macro_all_none_returns_only_sentinel` | 全 None → sm 仅含 `data_completeness_pct` |
| `test_pillars_l5_only_sentinel_is_missing` | sentinel-only → status=missing(真伪空) |
| `test_pillars_l5_partial_data_is_ok_with_latest_in_interp` | DXY+US10Y latest → interp 含 "DXY=105.5" / "US10Y=4.3" |
| `test_pillars_l5_with_btc_nasdaq_corr_in_interp` | corr.value=0.42 → interp 含 "BTC-NDX corr=0.42" |
| `test_l5_pillars_structured_macro_ok_with_partial_real_data` | 真 Layer5Macro.compute(80 天 dxy+nasdaq,缺 us10y/vix)→ status=ok |
| `test_l5_pillars_structured_macro_ok_with_full_real_data` | 真 compute 120 天全数据 → 4 类 key 齐 + ok |

### 同时更新 1.5c.3 的旧测试

`tests/test_pillars_status_classification.py::test_l2_relative_position_n_a_is_missing` →
重命名为 `test_l2_relative_position_n_a_is_ok`,断言改为 `status=ok` + interp 含 "n/a" 或 "中性"。

**回归**:全量 `pytest tests/` = **791 passed, 1 skipped, 5.17s**(783 + 8 新)。

---

## 四、用户验证脚本(SSH 部署后)

```bash
ssh ubuntu@124.222.89.86 << 'SSH'
cd /home/ubuntu/btc_swing_system
git pull
sudo systemctl restart btc-strategy.service
sleep 5

# 验证 5 层 pillars 全 ok + L5 structured_macro 真实填
.venv/bin/python -c "
import sqlite3, json
conn = sqlite3.connect('data/btc_strategy.db')
row = conn.execute(
    'SELECT full_state_json FROM strategy_runs '
    'ORDER BY reference_timestamp_utc DESC LIMIT 1'
).fetchone()
state = json.loads(row[0])
for lid in (2, 5):
    l = state['evidence_reports'].get(f'layer_{lid}', {})
    for p in l.get('pillars') or []:
        st = p.get('status')
        nm = p.get('name')
        ip = (p.get('interpretation') or '')[:60]
        print(f'L{lid} {nm}: {st} | {ip}')
l5 = state['evidence_reports'].get('layer_5', {})
sm = l5.get('structured_macro') or {}
print()
print('L5 structured_macro keys:', list(sm.keys()))
print('  DXY:', sm.get('DXY'))
print('  US10Y:', sm.get('US10Y'))
print('  VIX:', sm.get('VIX'))
print('  btc_nasdaq_corr:', sm.get('btc_nasdaq_corr'))
"
# 预期:L2 相对位置=ok / L5 结构化宏观=ok / 包含 latest 数值
SSH
```

---

## 五、§X / §Y / §Z 自检

### §X(只补充 / 放松,不重写)
- 任务 A 仅扩展 _pillars_l2 的 phase 分支,n_a 走 ok(原代码逻辑 + 老 unclear→ok 仍保持)
- 任务 B 把 `if dxy_trend` 严苛过滤拆成"任一可用即填",旧字段名 / 行为对齐
- 任务 C `_pillars_l5` 加 sentinel 过滤,旧"全 ok 分支"行为保留,只是更精准
- 不动 layer5_macro 业务逻辑(_compute_trend / _compute_vix_regime 等)
- 不动 AI 启用路径(rule_output.update 仍能覆盖)

### §Y
本 commit 立即 push。

### §Z 端到端断言
- 真 Layer5Macro.compute 80 天 / 120 天 + partial / full → 断言 structured_macro
  含 latest 数值
- helper 单测覆盖 partial-only / full / all-None 三档边界
- _pillars_l5 三档(missing / partial ok / corr in interp)

### 同类风险扫描
1. **生产偏极端"宏观 0 数据"** — _build_structured_macro_rule 仍写 sentinel,
   _pillars_l5 正确判 missing(`real_keys=[]`)
2. **AI 启用后覆盖 structured_macro** — `rule_output.update(...)` 行为不变,
   AI 输出的字段会替换规则路径产物
3. **VIX latest_value vs latest 字段名** — 1.5c.3 已 fallback,本次保持
4. **`pieces` 为空时 interp** — 旧版可能输出 "已就绪但字段未命名",新版改为
   `f"已就绪({len(real_keys)} 项)"` 提示 key 数量

---

## 六、改动文件

| 文件 | 改动 |
|---|---|
| `src/evidence/pillars.py` | _pillars_l2 phase=n_a→ok;_pillars_l5 加 sentinel 过滤 + interp 读 latest |
| `src/evidence/layer5_macro.py` | _build_structured_macro_rule 每个字段独立判断,放松过滤 |
| `tests/test_pillars_status_classification.py` | 更新旧 test_l2_relative_position_n_a_is_missing → _is_ok |
| `tests/test_l5_structured_macro_round2.py` | 新文件 8 测试 |

---

## 七、未覆盖项

- 1.5c 系列(.0/.1/.2/.3/.4)修了用户截图所有 missing
- L4 失效位"有方向但 swing 不足"、L5 AI 启用 timeline 留 v0.5 sprint
