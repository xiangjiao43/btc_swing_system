# Sprint 2.6-M — 全量字段诊断 + 一次性修所有真 bug

**Date:** 2026-04-27
**Branch:** main
**Commits:** `c754106` (B1) → `f3f75d9` (B2) → `40d3343` (C2) → 本报告
**Status:** ✅ 3 个真 bug 全部修完;A 类等冷启动 / D 类入 backlog

---

## 段 1 — 全量字段诊断表

| 字段 / 模块 | 子项 | 当前状态(本机) | 真实根因 | 类别 |
|---|---|---|---|---|
| **AI 策略建议** | action / direction / opportunity_grade | watch / None / none | L3=none → AI 短路(_should_call_ai 返 False) | A |
| | confidence / rationale / narrative / one_line_summary | 规则降级文案 | 同上 | A |
| | trade_plan / primary_drivers / counter_arguments / what_would_change_mind | None / [] / [] / [] | grade=none → trade_plan 必为 None | A |
| | confidence_breakdown / transition_reason / constraints / evidence_gaps | dict / "" / dict / [冷启动] | 规则路径默认 | A |
| | model_used / tokens_in / tokens_out / latency_ms / status / notes | success 0/0/0 | AI 没被调 | A |
| **组合因子** | truth_trend.score | 0.0(items_triggered=[]) | ADX=22.86<25,MA mixed | A(冷启动+regime 转换中)|
| | band_position.phase | 'late' (cv=0.43) | 真实计算,卡 current_value=phase | OK |
| | cycle_position.cycle_position | 'early_bull' (cv=0.6) | 真实计算 | OK |
| | crowding.score | 2.0 (funding_rate_high_3x 命中) | 真实计算;基差/期权 D 类未实现 | OK |
| | macro_headwind.completeness_pct | 0.0(本机)/ 应 ≥80%(生产 9 series) | 本机 macro 0 行;生产已修 | A(本机)/ OK(生产)|
| | event_risk.score | 0.0(本机 events 0 行)/ 生产 ≥4 | 本机数据缺;生产 Sprint 2.6-D 已 seed | A |
| **L1 三支柱** | trend_strength | 老 run missing / Sprint 2.6-C 后 ok | 字段名 adx_14_1d 在 2.6-C dac5867 已加顶层 | OK(生产)|
| | structure_coherence | 同上 | 字段名 tf_alignment 在 2.6-C 已加 | OK(生产)|
| | volatility_regime | ok ('low') | 真实计算 | OK |
| **L2 三支柱** | structure_sequence | **missing 永远** | **B 类 bug**:l2 从未输出 structure_features | **B**(Sprint 2.6-L 已修)|
| | relative_position | n_a | stance=neutral → phase=n_a 设计行为 | A |
| | long_cycle_context | ok ('early_bull') | 真实计算 | OK |
| | exchange_momentum_score | None + "not provided in context" | **C 类 bug**:single_factors 字典从未被写入 | **C**(本 sprint 已修)|
| **L3** | opportunity_grade | 'none' | stance=neutral → 规则不命中任何档位 | A |
| **L4 三支柱** | structural_invalidation | missing | stance=neutral → _find_structural_invalidation 返 None(设计) | A |
| | crowding | ok | 同 composite | OK |
| | event_window | ok | event_risk.score=0 是合法 low 档 | OK |
| **L4 衍生** | hard_invalidation_levels | [] | stance=neutral 设计 | A |
| | scale_in_plan / overall_risk_level / position_cap | ok | 真实计算 | OK |
| **L5 四支柱** | structured_macro | missing(本机)/ 应 ok(生产) | 本机 macro 0 行;生产 ≥80% completeness 应触发 AI | A(本机)/ OK(生产)|
| | event_calendar | ok | 真实计算 | OK |
| | qualitative_events | missing 永远 | **C 类**:需新闻源,modeling §6.8 设计但代码无 producer | C(跨 sprint,见 backlog)|
| | extreme_event | ok (False) | 真实计算 | OK |
| **L5 §6.8 字段** | macro_stance / macro_trend / macro_headwind_score / adjustment_guidance | unclear / None / None | L5 AI completeness 触发后才有 | A |
| **factor cards** | macro_btc_nasdaq_corr_60d | hardcoded `current_value=None` | **B 类 bug**:复制粘贴漏改 | **B**(本 sprint 已修)|
| | event_fomc_next / event_cpi_next / event_nfp_next | None(72h 外的看不到) | **B 类 bug**:用 events_upcoming_48h 的 72h 窗 | **B**(本 sprint 已修)|
| | macro_btc_gold_corr_60d | None | GOLDPMGBD228NLBM discontinued | D(backlog)|
| | derivatives_liquidation_24h / funding_rate_aggregated / lth_realized_price / sth_realized_price / adx_14_1d / tf_alignment_4h_1d_1w | 本机 missing(老 run)/ 生产 ok | Sprint 2.6-B/C/F.4/I 已修;本机 04-24 老 run 不反映 | OK(生产)|

---

## 段 2 — 本 sprint 修了哪些 B 类(真 bug)

### B1 `c754106` — fix(emitter): macro_btc_nasdaq_corr_60d 卡 hardcoded None

| 项 | 详情 |
|---|---|
| **文件** | `src/strategy/factor_card_emitter.py:1512-1547`(_emit_macro_reference)|
| **改动** | 删除 `current_value=None` 写死,复用 `_compute_corr_60d(klines_1d, macro["nasdaq"])`(与 Sprint 2.6-F 黄金卡同模板) |
| **测试** | `tests/test_macro_btc_nasdaq_corr_card.py`(5 测试):filled-when-present(corr≈1→bullish)、强负相关合成数据(corr≈-1→bearish)、随机走 → neutral、nasdaq 缺失降级、klines 缺失降级 |

### B2 `f3f75d9` — fix(emitter): 'next of type' 事件卡突破 72h 窗

| 项 | 详情 |
|---|---|
| **文件** | `src/data/storage/dao.py`(新方法 `EventsCalendarDAO.get_next_events_by_type`)+ `src/pipeline/state_builder.py`(注入 `context["next_events_by_type"]`)+ `src/strategy/factor_card_emitter.py:_emit_events_reference` 加 `next_by_type` kwarg |
| **改动** | 老路径用 events_upcoming_48h(72h 内),Apr 27 看不到 May 1 NFP / May 13 CPI。新方法不限距离,只取每类最近 1 个事件 |
| **测试** | `tests/test_event_next_cards_beyond_72h.py`(5 测试):DAO 三类全返回 + hours_to 计算;DAO 跳过过去事件;emitter 优先 next_by_type;无 next_by_type 时退回 events;state_builder 注入 |

---

## 段 3 — 本 sprint 修了哪些 C 类(未实现的设计)

### C2 `40d3343` — feat(single_factors): exchange_momentum_score producer

| 项 | 详情 |
|---|---|
| **文件** | 新建 `src/single_factors/__init__.py` + `src/single_factors/exchange_momentum.py` + `src/pipeline/state_builder.py` 注入 `context["single_factors"]` |
| **背景** | modeling §3.8 把 ExchangeMomentum 从 composite 降级为 L2 §B5 stance_confidence 修正项。L2 自 Sprint 1.5 起 read `single_factors.exchange_momentum_score`,但**没 producer 写入**,L2 cold_notes 永远是 "exchange_momentum not provided in context, skipped" |
| **算法** | `raw = mean(last 7d exchange_net_flow)`,`scale = max(|series|, 180d)`,`em_score = clamp(-raw/scale, -1, 1)`。符号约定:正 = bullish(流出),负 = bearish(流入)。与 L2:209 line 期望一致 |
| **测试** | `tests/test_exchange_momentum_score.py`(9 测试):4 个符号约定单元(inflow→neg / outflow→pos / balanced→~0 / clamp)+ 3 个降级(短序列 / 缺 key / 非 Series)+ 2 个 §Z 端到端(真 OnchainDAO seed → state_builder → context.single_factors;L2.compute 不再 skip) |

### B + C 已修小结

| 真 bug 修复 | commit | 测试新增 |
|---|---|---|
| L2 structure_features(Sprint 2.6-L 已修)| `faf479d` | 11 |
| B1 BTC-纳指 corr 卡 | `c754106` | 5 |
| B2 事件 next 卡 72h 窗 | `f3f75d9` | 5 |
| C2 exchange_momentum_score | `40d3343` | 9 |
| **合计**(L + M)| 4 commit | **30 测试** |

557 pytest pass(从 527 → 538(L)→ 557(M),无回归)。

---

## 段 4 — 类别 A(真冷启动)+ 类别 D(跨 sprint backlog)

### A 类(等今晚 ~20:30 BJT cold_start runs_completed=42 完成自动恢复)

预计 4-5 小时后这些字段从 missing/none → 有真值:

- **AI 21 字段**:`_should_call_ai()` 解锁需 cold_start_warming_up=False + L3 ≥ C
- **L2 phase / relative_position 支柱**:stance ≠ neutral 后 phase 不再 n_a
- **L4 structural_invalidation 支柱 + hard_invalidation_levels**:stance ∈ {bullish, bearish} 后 _find_structural_invalidation 返非 None
- **L5 §6.8 字段** (`macro_stance / macro_trend / macro_headwind_score / adjustment_guidance`):L5 AI 在 macro completeness ≥ 50% 时才跑(生产 9/10 已齐)
- **truth_trend.score** + items_triggered:regime 出 transition 后 ADX/MA alignment 命中

### D 类(跨 sprint backlog,需新数据源,docs/cc_reports/sprint_2_6_chain_verify.md 已记)

1. **L5 qualitative_events**:需接新闻源(NewsAPI / RSS / CryptoPanic / CoinDesk RSS / Anthropic web_search 5 候选已在 Sprint 2.6-L Part 2 对比表)
2. **macro_btc_gold_corr_60d**:GOLDPMGBD228NLBM discontinued,Yahoo banned,Stooq apikey-walled,LBMA paid-only
3. **Crowding `basis_high` / `put_call_low`**:需 Deribit options 数据源(2 项 +1+1 评分,当前 items_skipped 注明)
4. **derivatives_snapshots wide 表精度天花板**(Sprint 2.6-J backlog)
5. **`data_fetch_log` dead 表清理**(Sprint 2.6-J backlog)

---

## 段 5 — 用户验证脚本 + 完整 missing → ok 统计

### 部署后服务器一站式验证

```bash
ssh user@124.222.89.86 << 'SSH'
cd /path/to/btc_swing_system
git pull   # cc7515 → 40d3343 = 6 commits since 2.6-L
sudo systemctl restart btc-strategy
sleep 5
.venv/bin/python scripts/run_pipeline_once.py 2>&1 | tail -5
SSH

# 本地 curl 验证 6 个 missing 字段
curl -s -u admin:Y_RhcxeApFa0H- http://124.222.89.86/api/strategy/current | \
  python3 -c "
import json, sys
s = json.load(sys.stdin)['state']

# B1 验证:BTC-Nasdaq corr 卡
cards = s.get('factor_cards') or []
nas = next((c for c in cards if 'btc_nasdaq_corr' in c['card_id']), None)
print(f'[B1] macro_btc_nasdaq_corr_60d: cv={nas[\"current_value\"]}  expect: 数值(非 None)')

# B2 验证:三个事件 next 卡
for t in ('fomc', 'cpi', 'nfp'):
    c = next((c for c in cards if f'event_{t}_next' in c['card_id']), None)
    print(f'[B2] event_{t}_next: cv={c[\"current_value\"]}  expect: 数值(小时)')

# C2 验证:L2 输出 + 不再 skip
l2 = (s.get('evidence_reports') or {}).get('layer_2') or {}
notes = ' '.join(l2.get('notes') or [])
print(f'[C2] L2.exchange_momentum_score: {l2.get(\"exchange_momentum_score\")}')
print(f'[C2] L2.notes 含 'not provided': {\"not provided\" in notes}  expect: False')

# L 验证:structure_features 真有值
sf = l2.get('structure_features')
print(f'[L]  L2.structure_features: {sf}  expect: dict 含 hh/hl/lh/ll/latest_structure')
"
```

### 完整 missing → ok 统计

| 修复 | sprint | 修复前 | 修复后 |
|---|---|---|---|
| L2 `structure_features` | L | missing 永远 | 真实 HH/HL/LH/LL 计数 |
| `macro_btc_nasdaq_corr_60d` 卡 | M (B1) | hardcoded None | 真实相关系数 ∈ [-1, +1] |
| `event_fomc_next / cpi_next / nfp_next` 卡(3 张)| M (B2) | 72h 外 None | 真实 hours_to(任何距离)|
| `L2.exchange_momentum_score` | M (C2) | "not provided in context, skipped" | 真实 em_score ∈ [-1, +1] |

**6 个字段**(1 个 L 类 + 5 个 M 类:1 corr + 3 events + 1 em_score)从 永久 missing 升级为按真实数据动态值。

类别 A 字段(~30 项)等今晚 20:30 BJT 后自动恢复,无代码工作。
类别 D 字段(5 项)等用户决定数据源后单独 sprint。

---

## §X / §Y / §Z 践行

- ✅ §X:旧的 hardcoded None / 老 fallback 路径已删除(B1 删 `current_value=None` 行;B2 改写 _emit_events_reference 加 next_by_type 路径)
- ✅ §Y:每个 commit 立即 push origin/main(B1 / B2 / C2 各独立)
- ✅ §Z 端到端 DB 字段值断言:每个修复都有真 SQLite + 真 DAO + 真 emitter 测试,断言 `current_value is not None` / `em_score is not None` / `notes` 不含老错误字符串
