# Sprint J — V1 hard_invalidation_levels 类型假设 bug 修复

**完成日期**: 2026-05-09
**Commit**: `25a667c` fix(validator): Sprint J — V1 兼容 v1.4 L4 list of dict 输入(修 latent TypeError)

**对齐建模**: docs/modeling.md §3.4.1(V1 stop_loss)+ §3.3.4(L4 hard_invalidation_levels schema)

---

## 1. 根因 — list[dict] vs list[float] schema 不一致

### v1.4 L4 实际 schema(`src/ai/agents/l4_risk_analyst.py:15`)

```python
"hard_invalidation_levels": [
    {"price": float, "direction": "below"|"above", "basis": str,
     "priority": int, "confirmation_timeframe": str},
    ...
]
```

实际生产输出(2026-05-09 16:31 BJT 真跑通的 master output):

```python
[
    {"price": 78125.0, "type": "ema_20_break",
     "description": "EMA-20 短期支撑", "distance_from_current_pct": -2.57},
    {"price": 75503.0, "type": "ema_50_break", ...},
    {"price": 74868.0, "type": "swing_low", ...},
    {"price": 71999.9, "type": "swing_high", ...},
]
```

### V1 之前的实现(`src/ai/validator.py:82`)

```python
levels = context.get("l4_hard_invalidation_levels") or []
levels_floats = [float(x) for x in levels if x is not None]
                  # ↑ TypeError: float(dict) 不合法
```

且 V1 docstring 错标 `l4_hard_invalidation_levels (list[float])`。

### 为什么之前没暴露

5/3 16:08 是过去 60 天唯一一次 master 真出 new_thesis 的成功 run。
之后所有 master AI run:
- 大量 fallback(`fallback_level=level_2`)→ V1 不被触发
- 或 `mode=silent_cooldown` / `mode=evaluate_existing` → `new_thesis=None` → V1 早返回

直到 Sprint I(5/9)修了中转站 retry,master AI 真出 new_thesis 才频繁触发,
latent bug 被暴雷。这是「系统更健壮反而暴露 latent bug」的好信号。

---

## 2. 修

`src/ai/validator.py`:

```python
def _extract_level_price(x: Any) -> Optional[float]:
    """从 hard_invalidation_levels 单元素抽 price。
    
    v1.4 L4 schema 输出 list of dict({price, type, description, distance_pct});
    历史/单测可能传 list of float。兼容两种,保留 dict 元信息(由调用者处理)。
    None / 解析失败返 None。
    """
    if x is None: return None
    if isinstance(x, dict):
        p = x.get("price")
        if p is None: return None
        try: return float(p)
        except (TypeError, ValueError): return None
    try: return float(x)
    except (TypeError, ValueError): return None


def validator_1_stop_loss(...):
    # ...
    levels_floats = [
        p for p in (_extract_level_price(x) for x in levels) if p is not None
    ]
```

不动 L4 schema(list of dict 是更好的设计,带 type/description/distance_pct
元信息)。同步修 docstring 标注新格式。

### 23 V 类型假设审计结果

| Validator | 输入格式假设 | 状态 |
|---|---|---|
| **V1** stop_loss | `l4_hard_invalidation_levels` | **修了**(本 sprint) |
| V2 position_cap | `entry_orders` list of dict | OK(一开始就 dict) |
| V3 entry_size | `entry_orders` list of dict | OK |
| V4 protection | flag bool | OK |
| V5 grade_permission | enum 字符串 | OK |
| V6-V11 | 各种业务态字段 | OK,无 list 类型混乱 |
| V12-V23 | dict / 字符串 / int | OK |

V1 是唯一有此假设错误的 validator。

---

## 3. §X 删除清单

| 删除对象 | 路径 | 删除原因 |
|---|---|---|
| (无) | (无) | 本 sprint 是兼容性修复,无旧函数被替代 |

V1 内 `[float(x) for x in levels]` 一行替换为 helper 调用 — 是改动不是删除。

---

## 4. §Z 端到端验证

### 测 1 — 单测覆盖(`tests/test_sprint_j_validator_dict_levels.py`)

16 个新测:

| 用例 | 验证 |
|---|---|
| `_extract_level_price` 8 路径 | dict-with-price / float legacy / int / numeric-string / dict 缺 price / None / dict 非数 / object — 全部正确 |
| `test_v1_v14_dict_levels_no_override` | sl 精确匹配 levels[i].price → 不覆盖 |
| `test_v1_v14_dict_levels_override_to_first_price` | **回放 16:18 真实失败**:sl=76000 不在 levels → 覆盖为 78142.0 |
| `test_v1_v14_does_not_raise_typeerror` | 显式 try/except — 修前抛 TypeError 修后不抛 |
| `test_v1_legacy_float_levels_no_override` / `_override` | 老格式 list[float] 仍走原路径(回归测) |
| `test_v1_mixed_dict_and_float` | 混合输入稳健 |
| `test_v1_dict_missing_price_skipped` | dict 缺 price → skip 该项 |
| `test_v1_all_levels_invalid_skip_override` | levels 全无解析 → 不覆盖,等同空 levels |

### 测 2 — 服务器手动触发 master pipeline(关键端到端)

```
$ curl -X POST http://127.0.0.1:8000/api/system/run-now
{"status":"success","run_id":"b76cfda04719485184fd7baa7a4855c8",
 "persisted":true,"ai_status":"ok","duration_ms":149964,
 "degraded_stages":[],"failure_count":0}
```

**修前(5/9 16:18 BJT)**:`failed_TypeError`,duration 137s,persisted=false
**修后(5/9 16:31 BJT)**:`success`,duration 150s,persisted=true,degraded_stages=[]

### 测 3 — strategy_run 各层 + thesis 真持久化

```
=== l1 success ===
=== l2 success ===
=== l3 success ===
  opportunity_grade: B          ← 今天数据 fresh 后真出 B 级
  execution_permission: cautious_open
  anti_pattern_flags: []
=== l4 success ===
  risk_tier: moderate
  hard_invalidation_levels (4 dicts):
    - price=78125 type=ema_20_break dist=-2.57%
    - price=75503 type=ema_50_break dist=-5.84%
    - price=74868 type=swing_low    dist=-6.63%
    - price=71999.9 type=swing_high dist=-10.21%
=== l5 success ===
=== master success ===
  mode: new_thesis        ← Sprint G P0 链路被触发!
  new_thesis.direction: long
  new_thesis.entry_orders: [
    {price: 78125, size_pct: 25},
    {price: 76800, size_pct: 20},
    {price: 82500, size_pct: 20},
  ]
  new_thesis.stop_loss: {price: 74868, size_pct: 100}
```

### 测 4 — theses 表 +1 行(Sprint G P0 wrapper 真生效)

```
$ sqlite3 ... "SELECT * FROM theses"
thesis_id: th_d0c0c96fa1e8
created_at_run_id: b76cfda04719485184fd7baa7a4855c8
direction: long
core_logic: BTC处于上升趋势确立中(transition_up稳定)... [592 chars]
confidence_score: 68
break_conditions: ["1D收盘跌破74868(最近swing low),HH+HL结构破坏",
                   "DXY突破120持续3天,美元强势压制风险资产",
                   "L5极端事件触发(extreme_event_detected=true)"]
lifecycle_stage: planned
status: active
```

### 测 5 — virtual_orders 表 +7 行

```
3 entry orders:
  o_e_e8984146a2b1: long entry 78125@25% pending(EMA-20 回踩)
  o_e_5705842f1774: long entry 76800@20% pending(深回踩)
  o_e_9ea2ad5b25c9: long entry 82500@20% pending(突破 EMA-200 追涨)

1 stop_loss:
  o_s_ff27e80b5abf: long stop_loss 74868@100% pending(swing_low 结构破坏位)

3 take_profit orders:
  o_t_75835b9586d6: long take_profit 85000@30% pending
  o_t_66d21bc57804: long take_profit 88000@30% pending
  o_t_095f814a7540: long take_profit 92000@40% pending
```

总计 65% entry + 100% stop + 100% take_profit,符合 v1.4 §3.4 规则。

### 测 6 — 服务器 pytest 全 suite

```
$ ssh ubuntu@... ".venv/bin/pytest --tb=no -q"
1714 passed, 1 skipped, 648 warnings in 188.94s (0:03:08)
```

(本地 1698 + Sprint J 16 = 1714,完全一致)

---

## 5. 风险扫描

### 5.1 是否还有其他 validator latent bug?

✅ 已穷举审计:
- V2/V3 用 entry_orders(list of dict)— 一开始就是 dict,无问题
- V4-V11 业务态字段(bool / int / 字符串)— 无 list 类型混乱
- V12-V23 dict 字段 — 无问题

V1 是唯一一处。审计在 §2 表格里。

### 5.2 v1.3 / v1.4 schema 一致性

- v1.4 L4 prompt 明确要求返 list of dict 元数据(`l4_risk_analyst.py:15` schema 写明)
- v1.3 历史路径已无活流量(orchestrator.run_full_a 全走 v1.4 入口)
- 老格式 list of float 兼容性留作单测桩使用

### 5.3 第一个真创建的 thesis,Sprint G P0 wrapper 真生效?

✅ 真生效:
- `theses.created_at_run_id = b76cfda04719485184fd7baa7a4855c8`(本次 run)
- 7 virtual_orders 全部 `thesis_id=th_d0c0c96fa1e8` 关联(Sprint G P0 链路完整)
- `lifecycle_stage=planned, status=active` — 正确初始状态

### 5.4 五层防线全部接通

| 层 | 修法 | 状态 |
|---|---|---|
| 数据采集 | 用户手动加 Glassnode 250 quota | ✅ |
| 中转站 retry | Sprint I:BaseAgent 2→3 + sleep 2s | ✅ |
| L4 schema | v1.4 list of dict 元信息(不变) | ✅ |
| Validator | Sprint J:V1 兼容 dict 输入 | ✅ |
| 持久化 | Sprint G P0 wrapper(已合并) | ✅ |

---

## 部署四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ 1714 passed, 1 skipped |
| GitHub push(commit 25a667c) | ✅ |
| 服务器 git pull | ✅ 已拉到 25a667c |
| 服务器 systemctl restart | ✅ active since 16:30 BJT |
| 服务器 pytest 全 suite | ✅ 1714 passed, 1 skipped(同本地) |
| 手动触发 pipeline_run | ✅ status=success, persisted=true |
| L3=B + master mode=new_thesis | ✅ |
| 1 thesis + 7 virtual_orders 真持久化 | ✅ |
| 生产 DB 迁移 | N/A |

---

## 详细报告

(本文件即详细报告)
