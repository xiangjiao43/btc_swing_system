# Sprint 1.8.2-A — 后端 normalize_state + i18n 翻译函数

**日期:** 2026-05-01
**Sprint 范围:** 后端 schema normalize 层 + i18n 翻译模块(网页改造前置)
**状态:** 完成,1 commit `d63206b` push origin/main
**前置:** Sprint 1.8.2 调研(commit b25xx 网页架构 + AI 输出语言)

---

## 0. 用户硬约束遵守

| 约束 | 状态 |
|---|---|
| 不暴露 regime/stance/phase/14 档状态机的英文枚举 | ✅ 全经 labels.py 翻译 |
| narrative + key_observations 直接透传(已是中文) | ✅ 不重新生成 |
| 卡片密度 C(标签 + 摘要 + 详细展开) | ✅ summary_card + layer_cards{label, summary, key_observations, narrative, supporting_data} |
| 原值保留(ADX 28 / EMA / OI 等) | ✅ supporting_data 带 value + explanation |
| 金融术语保留英文(OI / funding / EMA / ADX / ATR / RSI) | ✅ 翻译表只覆盖枚举,不动金融术语 |
| 翻译表 v0 锁定不擅改 | ✅ 一字不改 |
| 不调 LLM(headline / summary 规则拼装) | ✅ if/elif + 第一句截断 |
| 不动前端 | ✅ web/* 0 改动 |
| 不删 v12 路径 | ✅ _normalize_v12 graceful degrade |

---

## 1. 改动文件清单

| 文件 | 行数 | 说明 |
|---|---|---|
| `src/web_helpers/__init__.py` | +14(新) | 暴露 translate / normalize_state |
| `src/web_helpers/labels.py` | +198(新) | i18n 翻译表 v0(11 dict)+ translate() |
| `src/web_helpers/normalize_state.py` | +354(新) | normalize_state 主函数 + v13/v12 双路径 + helpers |
| `src/api/routes/strategy.py` | +12/-1 | _row_to_model 加 normalize_state 调用 + passthrough factor_cards/meta |
| `tests/web_helpers/__init__.py` | +0(新) | 包标记 |
| `tests/web_helpers/test_normalize_state.py` | +302(新) | 35 tests |

---

## 2. labels.py 翻译表 v0(锁定)

11 个字典,完全按用户规格:

| 字典 | 档位数 | 示例 |
|---|---|---|
| L1_REGIME | 9 | "trend_up" → "上升趋势(明确向上)" |
| L1_VOLATILITY | 4 | "extreme" → "波动极端" |
| L2_STANCE | 3 | "bullish" → "看多" |
| L2_PHASE | 6+1 容错 | "exhausted" → "趋势衰竭(可能要反转)" |
| L3_OPPORTUNITY_GRADE | 4+1 容错 | "C" → "C 级机会(一般,谨慎)" |
| L3_EXECUTION_PERMISSION | 5 | "watch" → "观望(暂不开)" |
| L4_RISK_TIER | 4 | "moderate" → "中等风险" |
| L5_MACRO_STANCE | 4 | "supportive" → "宏观顺风(对 BTC 有利)" |
| MASTER_STATE | 14 | "LONG_PLANNED" → "准备做多(还没开)" |
| MASTER_ACTION | 7+1 容错 | "open" → "开仓" |
| ANTI_PATTERN_LABELS | 5+5 容错 | "is_extending_late_phase" → "⚠️ 趋势末段追单..." |
| EXTREME_EVENT_LABELS | 5 | "flash_crash_detected_24h" → "🚨 闪崩(24h 内 1 小时跌幅 > 8%)" |

`translate(table, key, default="未知")`:找不到返回 "未知",不抛异常。

---

## 3. normalize_state 输出 schema

```python
{
  "schema_version": "v13" | "v12" | "unknown",
  "summary_card": {
    "action_state_label": "空仓观察",       # 翻译后
    "stance_label": "看多",                 # 翻译后
    "headline": "保持空仓观察(机会一般)",  # if/elif 拼装
    "validator_passed": True | False | None,
    "decision_time": "2026-05-01T17:49:58Z+08:00",
    "ai_status": "ok",
  },
  "layer_cards": [
    {
      "layer": "l1",
      "title": "L1 市场状态",
      "label": "上行过渡(方向偏多但还没确立)",
      "secondary_labels": ["波动正常"],
      "summary": "BTC 处于上行过渡阶段。",            # narrative 第一句
      "key_observations": ["EMA 排列开始向上", ...], # 直接透传
      "narrative": "BTC 处于上行过渡阶段。EMA-20 已...",
      "contradicting_signals": [],
      "supporting_data": {"rule_cycle_position": {"value": "early_bull",
                                                    "explanation": "..."}},
      "confidence": 0.65,
    },
    # l2 / l3 / l4 / l5 / master 同结构
  ],
  "anti_patterns_active": [],         # 翻译后,只显示 true 的
  "extreme_events_active": [],         # 翻译后,只显示 true 的
  "raw": {<原始 state>},                # 调试用,前端不渲染
  "factor_cards": [...],               # passthrough(前端 overlay)
  "meta": {"strategy_flavor": "swing"},  # passthrough
}
```

### Headline 拼装规则(简单 if/elif)

| 条件 | headline |
|---|---|
| state == "PROTECTION" | "保护模式(极端事件,只清仓不开新仓)" |
| state ∈ {LONG_HOLD, LONG_OPEN} | "持有多单" |
| state ∈ {SHORT_HOLD, SHORT_OPEN} | "持有空单" |
| state == "LONG_TRIM" | "多单减仓中" |
| state ∈ {LONG_EXIT, SHORT_EXIT} | "已清仓" |
| state == "LONG_PLANNED" | "准备做多(等待入场)" |
| state == "FLIP_WATCH" | "刚平仓,反手冷却中" |
| state == "FLAT" + grade=A | "建议开仓(高级别机会)" |
| state == "FLAT" + grade=B | "可考虑开仓(中级别机会)" |
| state == "FLAT" + grade=C | "保持空仓观察(机会一般)" |
| state == "FLAT" + grade=none | "保持空仓观察(暂无机会)" |

---

## 4. _row_to_model 改动

```python
def _row_to_model(row):
    state = row.get("state")  # ← 已是 dict(从 DAO 解析)
    # ... 原 strategy_flavor 设置 ...

    # Sprint 1.8.2-A:经 normalize_state 把 v12/v13 统一
    try:
        normalized = normalize_state(state or {}, row.get("run_mode"))
    except Exception:
        normalized = {"schema_version": "unknown", ...}  # fallback

    return StrategyStateRow(..., state=normalized, ...)
```

**所有 4 个 endpoint 自动统一**:`/current` / `/latest` / `/history` / `/runs/{run_id}` 全经此 helper。

---

## 5. 35 个新测试清单

| 测试组 | 数量 | 验证什么 |
|---|---|---|
| v13 完整 state | 12 | schema_version / summary_card 翻译 / 6 layer_cards / l1+l3 label / narrative 透传 / supporting_data / position_cap 显示 / raw 保留 |
| anti_pattern + extreme_event 过滤 | 4 | 全 false → 空数组;单 true → 只显示该一项;闪崩 +"🚨 闪崩..." |
| v12 graceful degrade | 4 | 不抛异常 + 6 cards + label 翻译 + summary_card |
| 边界 | 4 | translate unknown → "未知";空 state;invalid input → schema=unknown |
| schema 检测 | 3 | run_mode='ai_orchestrator' → v13;layers 键 → v13;无标记 → v12 |
| Headline 拼装 | 4 | LONG_HOLD / PROTECTION / FLAT+A / FLAT+none |
| first_sentence helper | 3 | 中文截断 / 空 / 长文截 + 省略号 |
| v13 检测无 run_mode | 1 | layers 键存在但 run_mode=None → 仍识别 v13 |

### 4 个 collateral test 修复(passthrough factor_cards/meta 后):

- `test_strategy_current_stamps_flavor_swing`
- `test_api_strategy_current_reads_from_latest_factor_cards`
- `test_api_strategy_current_falls_back_when_latest_empty`
- `test_current_endpoint_still_overlays_after_refactor`

---

## 6. pytest 输出

```
$ uv run pytest tests/
================ 976 passed, 1 skipped, 360 warnings in 7.81s ================
```

- 1.9-A.5.3 + 1.9-B 完成时:941 passed
- 本 sprint +35 tests → **976 passed, 0 failed, 0 regression**

---

## 7. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ tests/ 976 passed, 0 failed |
| GitHub push(commit d63206b) | ✅ push origin/main |
| 服务器 git pull | ⏳ 待用户 SSH |
| 服务器 systemctl restart | ⏳ 待用户(API 路由代码改了,必须 restart 加载新 _row_to_model) |
| 生产 DB 迁移 | N/A |

**说明**:本 sprint 改的是 API 序列化层 + 新 web_helpers 模块。
Restart 后,前端调 `/api/strategy/current` 等 endpoint 拿到的是**新 schema**
(含 schema_version + summary_card + layer_cards 等);现有 `web/index.html`
+ `web/assets/app.js` 仍按 v12 形态读 `state.evidence_reports.layer_X` →
**前端会显示空白 / 报错**(预期,1.8.2-B 重写前端)。

**临时缓解**:`raw` 字段保留原始 v12/v13 state,前端 1.8.2-B 之前可访问
`state.raw` 兼容老路径。

---

## 8. 用户 SSH 验证脚本

```bash
ssh ubuntu@124.222.89.86
cd /home/ubuntu/btc_swing_system
git pull origin main

echo "=== 1. labels.py 翻译表锁定(v0)==="
head -10 src/web_helpers/labels.py
grep -c "L1_REGIME\|L2_STANCE\|MASTER_STATE\|MASTER_ACTION\|EXTREME_EVENT" src/web_helpers/labels.py
# 期望:11 个翻译字典

echo ""
echo "=== 2. pytest web_helpers ==="
.venv/bin/pytest tests/web_helpers/ -v 2>&1 | tail -10
# 期望:35 passed

echo ""
echo "=== 3. pytest 全套 ==="
.venv/bin/pytest tests/ 2>&1 | tail -3
# 期望:976 passed, 1 skipped, 0 failed

echo ""
echo "=== 4. service restart 加载新 _row_to_model ==="
sudo systemctl restart btc-strategy.service && sleep 5
sudo systemctl status btc-strategy.service | head -3

echo ""
echo "=== 5. curl /api/strategy/current 看新 schema ==="
curl -s -u admin:Y_RhcxeApFa0H- http://localhost:8000/api/strategy/current \
  | python3 -m json.tool | head -50
# 期望:
#   "state": {
#     "schema_version": "v13" 或 "v12",
#     "summary_card": {"action_state_label": "...", "headline": "..."},
#     "layer_cards": [{...}, ...],
#     ...
#   }

echo ""
echo "=== 6.(可选)看 v13 行的完整翻译 ==="
curl -s -u admin:Y_RhcxeApFa0H- http://localhost:8000/api/strategy/current \
  | python3 -c "
import sys, json
data = json.load(sys.stdin)
state = data['state']
print('schema:', state.get('schema_version'))
print('headline:', state['summary_card'].get('headline'))
print('action_state_label:', state['summary_card'].get('action_state_label'))
for card in state.get('layer_cards', []):
    print(f\"  {card['title']}: {card['label']}\")
"
```

---

## 9. 同类风险扫描

1. **前端 1.8.2-B 之前网页会显示空白/报错** —— `web/index.html` 仍按 v12 路径
   读 `state.evidence_reports.layer_X` / `state.adjudicator`。**临时缓解**:
   normalize 输出含 `raw` 字段,前端可访问 `state.raw.evidence_reports`(老路径)。

2. **其他 API 端点未经 normalize**:`/api/system/health-detail`(可能读
   evidence_reports)、`/api/lifecycle/current` 等仍按 v12 形态读 full_state_json。
   1.8.2-B 实施时如发现这些 endpoint 也需新 schema,统一在 _normalize_state 调用点
   加(目前只 strategy.py 经过)。

3. **factor_cards passthrough 仅在 v12 路径触发**:v13 路径的 state 暂无
   factor_cards 子结构(orchestrator 没填)。前端 overlay 逻辑仍 OK
   (raw 中保留,passthrough 字段可能为 None)。1.10 时把 factor_cards 接入
   v13 输出。

4. **headline 规则覆盖率**:目前 14 档 state + 4 档 grade 组合 ≈ 56 种,
   if/elif 只覆盖了 11 个最常见组合,其他 fallback "空仓观察"。1.10 时
   补全或评估是否需要。

5. **AI 输出枚举值非标准**:如果 AI 偶发输出非枚举字符串(如 stance="一般"
   而非"bullish"),translate 会返回"未知",summary 字段降级。
   实际生产应该不会发生(prompt 严格要求枚举),但**Validator 不检查 stance/
   regime 等枚举一致性**(只检查 master 输出),漏网概率非零。1.10 时考虑
   把所有 layer 输出枚举一致性检查并入 Validator。

---

## 10. Sprint 1.8.2-A commit

```
d63206b Sprint 1.8.2-A: 后端 normalize_state + i18n 翻译函数(网页改造前置)
```

---

## 11. 总结

Sprint 1.8.2-A 完成网页改造的后端基础设施:

- ✅ `src/web_helpers/labels.py`(11 翻译字典 + translate helper)
- ✅ `src/web_helpers/normalize_state.py`(v12/v13 统一 schema + 6 layer_cards)
- ✅ `src/api/routes/strategy.py::_row_to_model` 加 normalize 调用,4 个
  endpoint 自动统一
- ✅ 35 个新测试,**pytest tests/ 976 passed, 0 regression**
- ✅ 1 commit `d63206b` push origin/main
- ✅ 红线全守:翻译表锁定 / 不动前端 / 不删 v12 / 不调 LLM /
  schema_version 必出

**下一步**:Sprint 1.8.2-B —— 重写 `web/index.html` + `web/assets/app.js`
读新 schema(`state.summary_card` / `state.layer_cards`),展示中文卡片。
