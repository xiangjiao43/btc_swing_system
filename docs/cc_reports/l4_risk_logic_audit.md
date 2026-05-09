# L4 风险评估 + 机会触发频率事实核查(只查不改)

**日期**:2026-05-09 BJT
**类型**:事实核查 sprint
**触发**:用户反馈系统迟迟无法开单,期望 C 级机会 3-4 次/月、B 级 1-2 次/月、
A 级 1-2 次/年

## 结论一句话

**L4 是 AI 主导(非规则)**;**L4 不是卡点 — elevated tier 只是削仓位不阻断
开仓**;真正卡死开仓是 **master AI 在 5/2-5/9 期间 13 次失败 fallback silent
+ 20 次 L3 grade=none 直接 silent + 5 次"数据降级 Level 2" + 1 次 Sprint E
关键层守卫**(刚好 5/9 触发);**L3 给 B/C 频率(月化 ~50 B + ~17 C)反而**
**远超用户期望(B 1-2/月 / C 3-4/月)**,问题不在"L3 难给 B/C",而在
"master 收到 B/C 之后无法做出 new_thesis 决策"。

## 段 2 — 关键代码 / 阈值原文 + 历史数据

### A. L3 opportunity_grade 4 档定性(`src/ai/agents/prompts/l3_opportunity.txt`)

```
A — 高质量机会:L1+L2+风险三维度齐心 + 反模式全 0
B — 中质量机会:核心结构对,有 1-2 个减分项(phase late / crowding 偏
    拥挤但未极端 / 长周期 ai_assessment=neutral),permission 通常
    cautious_open
C — 低质量机会:方向有,但多重减分(L1 transition + L2 stance_confidence=
    medium / risk_preview funding_z 偏高 + events ≥2),permission 通常
    watch
none — 无机会(任一硬约束)
```

**硬约束 H1-H5**(prompt §十):
```
H1. L1 regime=chaos → grade=none
H2. L2 stance=neutral → grade=none
H3. L1 transition_* + L2 stance_confidence=low → grade ≤ C
H4. 反模式触发数:0→不降,1→降1级,≥2→强制 none
H5. current_state ∈ {LONG_HOLD/TRIM/SHORT_HOLD/TRIM} → grade=none(L3 不
    重复给开仓)
```

### B. L4 是 AI 主导(`src/ai/agents/prompts/l4_risk.txt`)

```
L4 输入:1 张图(K 线 + funding/OI/exchange_flow 副图)+ 文本数据
+ L1/L2/L3 输出
L4 输出:risk_score(0-100)/ risk_tier / hard_invalidation_levels(2-4 个)
+ position_cap_multiplier(0.0-1.0)+ risk_breakdown(structure/crowding/
liquidity/event 4 类各 0-100)
```

**risk_tier 4 档**(prompt §四):
```
low(0-25):多维度清洁
moderate(25-50):1-2 项中等风险信号(funding 偏高但未极端)
elevated(50-75):多重风险同时(funding 极端 + OI Z>1.5,价格贴主支撑
                  或破)
extreme(75-100):多重 funding/OI 同时极端 + 破支撑 + 链上恐慌流入
```

**关键**:**L4 risk_tier 不直接否决开仓**,而是通过 `position_cap_multiplier`
削仓位:
- low → 0.85-1.0(几乎不削)
- moderate → 0.65-0.85(削 15-35%)
- elevated → 0.40-0.65(削 35-60%)
- extreme → 0.15-0.40(接近建模 §4.5.5 硬下限)

L4 prompt 没有"硬约束"段(对比 L3 H1-H5),input 没有规则结论标签,
**全部由 AI 看图 + 数值自己识别**。

### C. permission 归并 — `merge_permissions()` 取最严

`src/utils/permission.py` + `config/thresholds.yaml::permission_strictness_order`:
```yaml
permission_strictness_order:  # 索引越大越严
  - can_open
  - cautious_open
  - ambush_only
  - no_chase
  - hold_only
  - watch
  - protective
```

`merge_permissions(*perms)` 取列表索引最大的(最严)。
**L3 给 cautious_open + L4 reasoning 间接给 watch → 归并后 watch**(永远取
最严)。

`master_adjudicator.txt` 第十节(Sprint E)**最终策略保险**:
```
关键层 = L1/L2/L4
- 任一 data_missing → 空仓 silent_cooldown / 持仓 hold_only
- 任一 degraded → 空仓 watch / 持仓 cautious_open
- L5(非关键)→ 仅 narrative 提及
```

### D. 5/1 至今 v1.3 orchestrator 真实数据(9 天 84 runs)

**L3 grade × L4 risk_tier 联合分布**:
```
l3      | l4_risk_tier  | cnt
--------|---------------|----
none    | elevated      | 41
        | (空,master fail)| 13
B       | moderate      | 11   ← 应该开仓但实际 0 active_thesis
none    | (空)          | 8
none    | moderate      | 4
C       | elevated      | 3
B       | elevated      | 2
C       | moderate      | 2
合计                     | 84
```

**L3 grade 60 天分布(filtered scheduled/event/manual)**:
```
l3_grade | cnt
---------|----
(空)    | 79  ← 老 v1.2 路径 + master fail
B       | 5
none    | 3
C       | 2
A       | 0
```

实际 v1.3 orchestrator 期(5/1 起)L3 给 grade 84 次中:
- A:0(0%)
- B:13(15%)
- C:5(6%)
- none:53(63%)
- empty:13(16%,master fail 时 L3 也无法回写)

**月化外推**(9 天 → 30 天):
- A 月化 0 vs 用户期望 ~0.1/月 → ✅ 符合
- B 月化 ~43 vs 期望 1-2/月 → **超 21x**
- C 月化 ~17 vs 期望 3-4/月 → **超 4x**
- none 月化 ~177 vs 期望 ~25/月(其他都是机会)→ 多

**结论:L3 给 grade 频率比用户期望高很多,问题不是"卡在 L3 不给"**。

### E. master.mode 60 天分布

```
mode             | cnt
-----------------|----
(空)            | 85    ← 老 v1.2 + master fail / fallback
silent_cooldown | 4
合计             | 89
```

**0 个 evaluate_existing,0 个 new_thesis**。

### F. silent_cooldown 真实原因(5/1 至今,共 ~30 次):

```
reason                                                     | cnt
-----------------------------------------------------------|----
master AI 失败,fallback silent(等下次重试)               | 13
L3 grade=none,无开仓机会(若干变体合并)                   | 20
数据降级 Level 2(单独 + 与其他组合)                      | 6
关键层 L2 数据降级(链上数据 stale,Sprint E 守卫)         | 1
反模式 extending_late_phase 触发                          | 1
L3 grade=C 但 execution_permission=watch(非 ambush_only)| 1
```

### G. 反模式 anti_pattern_flags(5/1 至今,有 v13 layers.l3 数据)

```
flags                              | cnt
-----------------------------------|----
[]                                 | 36
["extending_late_phase"]          | 35   ← 牛市后期触发率极高
["failing_at_resistance"]         | 1
```

**`extending_late_phase` 反模式触发 35/72 ≈ 49%** — L2 phase=late 时
触发,牛市行至高位很容易命中。L3 H4 规定 1 个反模式 → 降 1 级,所以这 35
次中部分本来可能给 A,被强制降到 B/C/none。

**这是 L3 给 grade 偏宽松但仍有相当 none 的原因之一**。

### H. fallback_level 60 天:

```
day        | none | level_1 | level_2 | level_3
-----------|------|---------|---------|--------
2026-05-09 | 0    | 1       | 0       | 0
2026-05-08 | 8    | 1       | 1       | 0
2026-05-07 | 2    | 0       | 0       | 0
2026-05-06 | 6    | 9       | 2       | 0
2026-05-05 | 5    | 1       | 4       | 0
2026-05-04 | 9    | 0       | 1       | 0
2026-05-03 | 7    | 0       | 4       | 0
2026-05-02 | 0    | 0       | 8       | 0
合计:67 normal / 12 level_1 / 20 level_2 / 0 level_3
```

5/2 单日 8 次全 level_2(master 失败)是**最严重的卡点日**。

### I. 关键层(L1/L2/L4)stale 真实情况

`/api/system/health-detail` 当前(5/9)显示:
- L2 / L4:health=degraded,reason="依赖的 Glassnode 链上 数据已过期 69.2 小时"
- L1 / L3 / L5:healthy
- overall_status=critical(因 Glassnode quota_exceeded)

**Sprint E 守卫触发条件**:关键层 data_missing(`fresh_ratio=0`)→ 强制
silent_cooldown。当前 L2/L4 是 degraded(`fresh_ratio<1` 但 >0),所以走的
是"上限 cautious_open / hold_only",**不是 data_missing 强制 silent**。
silent_cooldown 主要由 master AI 自己判定(L3=none 占 20 次,master fail
13 次)。

## 段 3 — 风险扫描:数据是否反映"系统正常运行"?

### 1. 历史数据严重不全(只 9 天 v1.3 orchestrator 期)

DB earliest=4/24,但 v1.3 orchestrator 在 2026-05-01 才启用
(`config/scheduler.yaml` 注释:"Sprint 1.9-B(2026-05-01)启用")。
4/24-4/30 数据是老 v1.2 路径,**l3/l4 字段全空**,统计上不可比。

实际可分析窗口只有 **5/1-5/9 共 9 天**。

### 2. quota 爆之前 vs 之后

ai_frequency_audit 显示 Glassnode quota 从 5/2 起开始大量返 403。9 天里
只有 **5/1 一天没受 quota 影响**。5/1 数据:
- C 级 1 次(C, moderate)
- none 级 1 次(none, elevated)
- 其他 13 次 layers 字段空

**5/1 数据太薄弱,无法据其断言"系统正常运行时的真实频率"**。

### 3. event_onchain 拖累

5/2-5/8 期间一日 9-17 次 event_onchain 触发,**推高 master fail 总数**
(因 Glassnode 偶尔返成功 + 部分 fail 让 master 跑完整 6 AI 中部分 stale
导致 fail)。Sprint F.1 已删 event_onchain enqueue,**未来生产仅 1 次/天
scheduled**,数据频率会大幅下降。

### 4. 用户期望与设计不一致

prompt §四 L3 grade 定性定义里,B 级要求"核心结构对 + 1-2 个减分项",
牛市趋势中很容易成立(stance bullish high tier + phase mid 很常见)。
**L3 当前定义产出 B 频率 ~5/天**,远超用户期望"1-2 次/月"。

要把 B 减少到月 1-2 次,需要**收紧 B 的定义**(比如要求 phase=early
+ stance_confidence=high + 反模式严格 0 + L4 risk_tier ≤ moderate),或者
干脆把 cautious_open 也禁止开新仓,只 active_open(对应 grade=A)才开。

### 5. 卡点优先级(给用户决策用)

|阻塞原因 | 9 天频率 | 月化 | 建议处理方向 |
|---|---|---|---|
| master AI 失败 | 13 次 | 43 次 | 等 Glassnode quota 恢复(根因)/ Sprint G alerts 推送 |
| L3=none 直接 silent | 20 次 | 67 次 | 等 master 真出 mode 后看是否仍卡 |
| 数据降级 Level 2 | 6 次 | 20 次 | 同上 |
| 反模式 extending_late_phase | 35 次(影响 grade 但不直接 silent) | 117 次 | L3 prompt 调整,或 Sprint E 后置守卫降低本反模式权重 |
| Sprint E 关键层守卫 | 1 次 | 3 次 | 现行设计正确,Glassnode 恢复后自然消失 |

### 6. 反向问题:用户是否真希望"几乎不开仓"

数据里 60 天 0 active_thesis 创建,**全部 silent_cooldown**。这跟用户拍板
"中长线 1 次/天 master + 严守 hold_only" 设计自洽 — 系统在 stale 数据
+ master AI 失败期间**就应该不开仓**。

期望 B 级 1-2 次/月对应"正常运行的牛市后期",但实际**正常运行还没开始**
(Glassnode quota 恢复 + L4 不老报 elevated)。建议**等 1-2 周完整 quota
恢复后重新 audit**,而不是现在调 L3/L4 阈值。

## 段 4 报告路径

`docs/cc_reports/l4_risk_logic_audit.md`(本文件)

## 给用户的建议(只查不改本 sprint 不动)

1. **不要现在改 L3/L4 prompt 阈值** — 历史数据太短(9 天 v1.3 + Glassnode
   quota 全程影响),改了也无法验证。
2. **优先解决 master AI 失败的根因** — 等 quota 恢复或换 Glassnode 数据源,
   再评估 1-2 周的实际 grade 分布。
3. **如果 quota 恢复后 B 级仍 ~5/天**,Sprint G 候选:
   - 收紧 L3 prompt §四 B 定义(增加 phase=early 强约束 + L4 risk_tier ≤
     moderate 双门槛)
   - 把 master "L3 grade=B + permission=cautious_open" 默认走 silent_cooldown,
     只 active_open 才创建 thesis(等价于"只开 A 级")
4. **`extending_late_phase` 反模式触发率 49% 是值得关注的二级问题**,但
   只影响"L3 给 B/C 级被降到 C/none",不直接阻止开仓 — 可在 Sprint G 评估
   是否调整反模式 phase=late 判定阈值。
5. **当前 silent_cooldown 13 次 master fail 是首要解决项**,与 L3/L4 阈值
   无关。
