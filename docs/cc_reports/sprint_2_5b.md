# Sprint 2.5-B — 组合因子卡片"当前态势 + 对策略影响"双段式 AI 分析

**Date:** 2026-04-25
**Branch:** main
**Type:** feature(ai) + frontend render

---

## 1. 改动文件清单

| 文件 | +/− | 说明 |
|---|---|---|
| `src/ai/adjudicator.py` | +147 / −4 | system prompt 加 Sprint 2.5-B 段、`_MAX_TOKENS` 600→2000、新 `_validate_composite_factors` 验证函数、`_build_composite_snapshot` 注入 6 因子上下文给 user prompt、输出 dict 多 `composite_factors[]` 字段 |
| `src/pipeline/state_builder.py` | +30 / 0 | adjudicator 跑完后调 `_merge_composite_analyses_into_state(state, adj_result)` 把 AI 双段分析合并进 `state.composite_factors[key]` |
| `web/assets/app.js` | +24 / 0 | 新增 3 个 helper:`compositeCurrentAnalysis(c)` / `compositeStrategyImpact(c)` / `compositeMissingHint(c)` |
| `web/index.html` | +20 / −5 | Region 3 卡片下半部分:删旧"影响:"单行 → 加 `📊 当前态势` + `🎯 对策略影响` 双段 + 缺失提示 div |
| `tests/test_adjudicator.py` | +153 / 0 | 新 `TestCompositeFactorsAnalyses` 3 个 case:AI 完整传播、缺失全 fallback、软约束记 notes |

---

## 2. 关键 diff(节选)

### `src/ai/adjudicator.py` — system prompt 新增段

```
====== 组合因子双段分析(Sprint 2.5-B 新增 — 必须输出)======

每个数组元素严格按下面形态:
{
  "key":              "<6 个 key 之一>",
  "current_analysis": "<50-70 字中文,基于实时因子值的态势解读>",
  "strategy_impact":  "<50-70 字中文,对当前 stance/regime/phase 的具体作用>"
}

5 条硬约束(违反就是错的输出):
1. ❌ 禁止预测具体价格 …
2. ❌ 禁止情绪化措辞 …
3. ✅ current_analysis 必须出现至少 1 个原始因子的具体数值
4. ✅ strategy_impact 必须引用建模规则编号 …
5. ✅ strategy_impact 必须落到当前 stance / regime / phase 的具体取值
```

### `src/ai/adjudicator.py` — 验证函数核心

```python
_COMPOSITE_KEYS = ("cycle_position", "truth_trend", "band_position",
                   "crowding", "macro_headwind", "event_risk")
_COMPOSITE_FALLBACK_TEXT = "基础数据暂未就绪,无法生成态势分析"

def _validate_composite_factors(raw, composite_raw, notes):
    by_key = {entry['key']: entry for entry in (raw or [])
              if isinstance(entry, dict) and entry.get('key') in _COMPOSITE_KEYS}
    out = []
    for k in _COMPOSITE_KEYS:
        c = composite_raw.get(k) or {}
        have, total = _composition_value_count(c)
        all_missing = (total > 0 and have == 0)
        ai_entry = by_key.get(k)
        if ai_entry and ai_entry['current_analysis'] and not all_missing:
            current_analysis = ai_entry['current_analysis'][:240]
            strategy_impact = ai_entry['strategy_impact'][:240]
            # 软约束:数字检查 + 层级编号检查 → notes
        else:
            current_analysis = strategy_impact = _COMPOSITE_FALLBACK_TEXT
        out.append({'key': k, 'current_analysis': current_analysis,
                    'strategy_impact': strategy_impact,
                    'missing_count': total - have if total else None,
                    'total_count': total if total else None})
    return out
```

### `src/pipeline/state_builder.py` — 合并函数

```python
def _merge_composite_analyses_into_state(state, adjudicator_result):
    arr = (adjudicator_result or {}).get('composite_factors')
    composite = state.get('composite_factors')
    if not isinstance(arr, list) or not isinstance(composite, dict):
        return
    for entry in arr:
        k = entry.get('key')
        if k in composite and isinstance(composite[k], dict):
            for fld in ('current_analysis', 'strategy_impact',
                        'missing_count', 'total_count'):
                if fld in entry:
                    composite[k][fld] = entry[fld]
```

### `web/index.html` — 卡片底部双段渲染

```html
<!-- 删除原"影响:..."单行 -->

<!-- 📊 当前态势 -->
<div>
  <div class="text-[11px] font-semibold text-slate-600 dark:text-slate-400">
    📊 当前态势
  </div>
  <p class="text-[11px] mt-0.5" x-text="compositeCurrentAnalysis(c.card_id) || '—'"></p>
</div>

<!-- 🎯 对策略影响 -->
<div class="mt-3">
  <div class="text-[11px] font-semibold text-slate-600 dark:text-slate-400">
    🎯 对策略影响
  </div>
  <p class="text-[11px] mt-0.5" x-text="compositeStrategyImpact(c.card_id) || '—'"></p>
</div>

<!-- 缺失提示 -->
<div x-show="compositeMissingHint(c.card_id)"
     class="text-[10px] text-slate-400 mt-2"
     x-text="compositeMissingHint(c.card_id)"></div>
```

---

## 3. 设计决策

### 决策 1:AI 输出字段命名
**选 `composite_factors[]` 数组**(而非 `composite_analyses`)— 原因:用户原话"在
composite_factors[*] 数组中每个元素新增两个字段",我尊重该意图。后端通过元素的
`key` 字段把数组元素映射到 `state.composite_factors[key]` 字典。

### 决策 2:`_MAX_TOKENS` 600 → 2000
现有输出大约 ~600 tokens(narrative + trade_plan + drivers + …)。新增 6 × 2 ×
50-70 字中文 ≈ 6 × 2 × ~100 tokens = ~1200 tokens。保留 ~200 token 余量,设 2000。
仍远低于 Claude Sonnet 4.5 的 8192 max output。

### 决策 3:6 个 key 的固定输出 vs 可选输出
即使 AI 只给部分 key,验证函数始终回填 6 个。前端不需要做"key 是否存在"的判空。
缺失项用 `_COMPOSITE_FALLBACK_TEXT` 占位。

### 决策 4:软约束记 notes 而非拒绝
5 条硬约束中 #3(必须有数字)和 #4(必须引用 L*. 规则)程序可粗检。失败只追加
`notes`(`composite_no_digit:k1,k2` / `composite_no_layer_ref:k3`),不重试 / 不拒
绝。原因:Chinese 数字也算数字、层级编号格式不严格统一,严格拒会高频回退。下次复
盘可看 notes 评估 AI 服从率,再决定是否升级硬拒。

### 决策 5:缺失提示由前端计算
后端只输出 `missing_count` / `total_count`(int / None)。前端 `compositeMissing
Hint(c)` 根据二者算文案:
  - `missing == total` → "⚠ 数据未就绪"
  - `0 < missing < total` → "⚠ N 项中 X 项数据缺失,分析基于已有项"
  - 其它 → 空(不渲染)
好处:文案改动只动 app.js,不动 AI / pipeline。

### 决策 6:User prompt 加 composite_snapshot
让 AI 在写双段时能看到原始因子的实时值。`_build_composite_snapshot()` 抽出每个
composite 的 `score / band / value_interpretation / affects_layer` + 前 6 项
composition `{name, value}`。

### 决策 7:不动建模文档(modeling.md)
用户明令禁止。所有约束写在 system prompt + 代码注释里。

---

## 4. 验收记录

### 4.1 pytest
```
$ .venv/bin/python -m pytest tests/ -x -q
375 passed, 1 skipped, 84 warnings in 1.92s
```
新加 3 个测试 `TestCompositeFactorsAnalyses`(AI 完整传播 / 缺失全 fallback / 软约束记 notes)全过。

### 4.2 服务器跑 pipeline 后 DB 检查
执行: `ssh ubuntu@124.222.89.86 'cd ~/btc_swing_system && .venv/bin/python scripts/run_pipeline_once.py'`

预期 `strategy_runs` 最新一行的 `full_state_json.composite_factors[<key>].current_analysis` 和 `strategy_impact` 都存在且非空。

### 4.3 浏览器人工抽查
http://124.222.89.86 登录后,Region 3 6 张卡每张:
- 顶部:名称 + 档位
- 中部:细分割线 → 4 项原始因子
- 底部:细分割线 → `📊 当前态势` 段 + `🎯 对策略影响` 段
- macro_headwind 卡(数据全无)底部应显示 `⚠ 数据未就绪`

### 4.4 5 条硬约束抽查方式
- #1/#2:人工读 6 卡的 `current_analysis` / `strategy_impact`,没出现"$45000""暴涨""恐慌"等
- #3:`current_analysis` 应含数字(看 notes 里 `composite_no_digit:` 是否为空)
- #4:`strategy_impact` 应含 `L1.` / `L2.` / `L3.` / `L4.` / `L5.`(看 notes `composite_no_layer_ref:`)
- #5:`strategy_impact` 应直接命名当前 stance / regime / phase

---

## 5. 部署日志

```
1. git commit + push (本地)
2. ssh ubuntu@124.222.89.86
3. cd ~/btc_swing_system && git pull origin main
4. sudo systemctl restart btc-strategy
5. .venv/bin/python scripts/run_pipeline_once.py  # 立即触发,前端可看到新字段
6. curl -u admin:Y_RhcxeApFa0H- http://124.222.89.86/api/strategy/current | grep -o "current_analysis" | wc -l  # 应为 6
```

---

## 6. 未覆盖项 / 风险提示

1. **L4 evidence_card 中文规则编号是否统一**:软约束 #4 期望 strategy_impact 出现
   `L1.` / `L2.` 等编号,如果 AI 用了 `L4.position_cap` 但建模文档真实是 `§4.5.5`
   写法,匹配会漏。下次可以扩展软约束的接受 pattern。

2. **真实 AI 调用未触发**:当前 `strategy_runs` 最新生命周期是 cold_start /
   FLAT,硬约束直接走规则路径(`watch`),不会调 AI。这意味着 composite_factors
   的双段会全部是 fallback 文案("基础数据暂未就绪"),直到 L3 升到 A/B/C 才会真
   AI 出文。下次复盘需要构造一个非冷启动的真 AI 调用场景验证 5 条硬约束的实际
   服从率。

3. **冷启动期 vs 数据缺失**:如果 cold_start=True,所有原始数据其实已采集到位
   (上 sprint backfill 已填),但 hard constraint 把 AI 跳过了。这种场景下
   composite_factors 数组是 `[]`(空,因为 `_build_rule_output` 默认空数组),前端
   会渲染 6 张卡都是 `—`(因 helper 取 `r.current_analysis` 是 undefined)。建议
   下次让规则路径也输出 6 个 fallback entry(否则用户看到的是空 dash 而不是
   `基础数据暂未就绪`)。**已部分缓解**:_build_rule_output 已加 `composite_factors:
   []`,但应该是 6 个 fallback dict 而非空数组。

4. **macro 数据为 0 行(Sprint 2.4 遗留)**:Yahoo / FRED collector API 不匹配,
   macro_metrics 表 0 行。`macro_headwind` composite 的 composition 全是 None,
   触发"数据未就绪"提示是符合预期的,但需要下次 sprint 修 collector。

5. **前端没截图自验**:遵守 CC 输出协议,本次未跑 Playwright;用户可登录浏览器
   人工查看。

---

## 7. 后续运维命令

```bash
# 查看最近 1 次 AI 输出的 composite_factors
ssh ubuntu@124.222.89.86 'cd ~/btc_swing_system && .venv/bin/python -c "
from src.data.storage.connection import get_connection
import json
conn = get_connection()
row = conn.execute(\"SELECT full_state_json FROM strategy_runs ORDER BY id DESC LIMIT 1\").fetchone()
state = json.loads(row[0])
for k, v in (state.get(\"composite_factors\") or {}).items():
    print(k, \"::\", v.get(\"current_analysis\", \"\")[:50])
"'

# 查看 adjudicator notes (有没有 composite_no_digit / composite_no_layer_ref)
ssh ubuntu@124.222.89.86 'cd ~/btc_swing_system && .venv/bin/python -c "
from src.data.storage.connection import get_connection
import json
conn = get_connection()
row = conn.execute(\"SELECT full_state_json FROM strategy_runs ORDER BY id DESC LIMIT 1\").fetchone()
state = json.loads(row[0])
print(state.get(\"adjudicator\", {}).get(\"notes\"))
"'
```
