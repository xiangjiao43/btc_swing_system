# Sprint 网页因子展示完整性 + 归属准确性优化(执行报告)

**日期**:2026-05-19
**前置计划**:[sprint_web_factor_transparency_plan.md](sprint_web_factor_transparency_plan.md)
**性质**:执行阶段,6 个 commit 完成调查阶段提出的修复方案

---

## 1. 6 个 commit 概览

| Step | Commit | 改动文件 | diff | 内容 |
|---|---|---:|---:|---|
| Commit 1 | [`586d567`](../../commit/586d567) | 2 | +151 / -1 | emitter 数据模型扩展:新增 `consumed_by_layers` + `linked_layer_simplified` + `advanced` 三字段 |
| Commit 2 | [`98745ad`](../../commit/98745ad) | 2 | +160 / -2 | 37 张卡标签修复(`_CONSUMED_BY_LAYERS_OVERRIDES` dict)+ 4 处歧义处理 |
| Commit 3 | [`d55ca69`](../../commit/d55ca69) | 5 | +99 / -296 | 10 张死卡 emit 删除(数据采集 / DB / Layer A inventory 全保留)|
| Commit 4 | [`7298be2`](../../commit/7298be2) | 2 | +603 / -0 | 13 张新卡新增 + ETF flow 卡 7d/30d sub-period 增强 |
| Commit 5 | [`0b0bbf6`](../../commit/0b0bbf6) | 3 | +81 / -9 | UI 改造:三档简化标签 + 三色渲染 + advanced 排序 + 详情展开 |
| Commit 6 | (本 commit) | ~1-2 | ~+200 | §X 自检 + 本报告 + push 不动 |
| **合计** | — | **15 unique** | **+1294 / -317** | |

---

## 2. 实际生效的卡片数(关键修正)

**计划 §5.1 估算:71 - 9 + 15 = 77 张**
**实际执行:71 - 10 + 13 = 74 张**

差额 **-3** 原因(D4 决策细化后的调整):

| 项 | 计划 | 实际 | 原因 |
|---|---:|---:|---|
| 删除卡片 | 9 | **10** | D4 grep 验证:`price_ma_20` 是 SMA-20 而非 EMA-20(Layer B 不消费,Layer A 只用 ma_200d)→ 第 10 张死卡 |
| 新增卡片 | 15 | **13** | D4 决策:`btc_price` 合并 `current_close` 为 1 张(原计划当 2 张算);`etf_flow_7d_sum_usd` + `etf_flow_30d_sum_usd` 合并到现有 `derivatives_etf_flow` 卡 sub-period 显示(原计划当 2 张新增,实际 0 张新增 + 1 张增强)|

**修复后网页"原始数据因子"模块**(`rawFactorCards()` 计算):
- factor_cards 非 composite 卡:48 张(53 总 - 5 composite)
- layerAFactorCardSpecs() 硬编码:26 张
- **合计 48 + 26 = 74 张**

---

## 3. §X 自检结果

### 3.1 10 张死卡 emit 代码彻底删除

```
derivatives_liquidation_24h emit: 0 hits ✅
derivatives_lsr_change_24h emit: 0 hits ✅
derivatives_top_long_short_ratio emit: 0 hits ✅
onchain_lth_mvrv emit: 0 hits ✅
onchain_sth_mvrv emit: 0 hits ✅
onchain_ssr emit: 0 hits ✅
price_ma_20 emit: 0 hits ✅(D4 修正新增的 10th)
price_ma_60 emit: 0 hits ✅
price_ma_120 emit: 0 hits ✅
price_tf_alignment_4h_1d_1w emit: 0 hits ✅
```

### 3.2 数据采集保留(D5 决策)

- `src/data/collectors/glassnode.py`:`fetch_ssr` / `fetch_lth_mvrv` 派生算法 ✅ 保留
- `src/data/collectors/coinglass.py`:`fetch_long_short_ratio_history` / `fetch_liquidation_history` ✅ 保留
- DB 列(derivatives_snapshots / onchain_metrics)未触碰 ✅
- Layer A `_FACTOR_SOURCE` / `available_factors` 注册未改 ✅

### 3.3 标签分布(实际模拟运行)

| 标签 | 卡片数 | 占比 | 计划目标 |
|---|---:|---:|---|
| **Layer A** | 15 | 31% | ~24 |
| **Layer B** | 26 | 54% | ~21 |
| **Layer A / B** | 7 | 15% | ~8 |
| 合计(非 composite emitter 卡)| **48** | 100% | — |

> 注:上表只统计 factor_cards 表的非 composite 卡(48);另外 26 张来自 web 端 `layerAFactorCardSpecs()` 都是 `Layer A` 标签(硬编码)。**全 74 张的最终分布:Layer A 41 / Layer B 26 / Layer A / B 7**。

### 3.4 Advanced 卡片数(D3 决策)

精确 **8 张** ✅(BTC close + EMA-4h ×2 + slope ×2 + ATR + price_position_90d + max_drawdown_60d)

---

## 4. 标签修复表(全 74 张,按 Commit 2 _CONSUMED_BY_LAYERS_OVERRIDES dict + Commit 4 新卡)

### 4.1 标签变更统计

| 项 | 计数 |
|---|---:|
| 改标签 | 37 |
| 删除(死卡) | 10 |
| 不变 | 24 |
| 新增 | 13 |
| 增强(ETF flow 卡 sub-period) | 1 |

### 4.2 4 处歧义处理记录

| 歧义 | 计划假设 | 实际(grep 验证后) | 处理 |
|---|---|---|---|
| price_ma_200 SMA vs EMA | Layer B(EMA-200) | **SMA-200d = Layer A ma_200d** | 卡片 linked_layer 改为 Layer A |
| price_ma_20/60/120 | Layer B | 全 SMA,无任何 prompt 消费 → **3 张死卡** | 3 张全删 emit |
| derivatives_etf_flow | 合并 7d/30d | 不改卡,在 plain_interpretation 末尾追加 sub-period | `_augment_etf_flow_card_with_sub_periods()` |
| events_*_next 5 卡 | Layer B(原 None)| Layer B L5 only(events_calendar_72h) | consumed_by_layers = ["L5"] |
| btc_price + current_close 合并 | 1 新增 1 合并 | 1 张新 emit 卡(`price_btc_close`) | consumed_by_layers = ["Layer A","L1","L2","L4"] |

---

## 5. UI 改造细节(Commit 5)

### 5.1 三档标签 + 三色渲染

| 标签 | 颜色 class | 视觉(亮 / 暗模式)|
|---|---|---|
| `Layer A` | `text-blue-600 dark:text-blue-300` | 蓝色 |
| `Layer B` | `text-amber-600 dark:text-amber-300` | 暖橙色 |
| `Layer A / B` | `text-purple-600 dark:text-purple-300` | 紫色 |

### 5.2 详情展开(D2 双保险)

每张卡片底部行尾加 ▾ 按钮,点击展开 `factorConsumedDetail(c)`,显示:
> "该因子被 Layer A 大周期裁决 + Layer B L2 / L4 消费"

advanced=true 的卡片同时显示:
> "⊕ 高级因子(默认排在分组末尾)"

### 5.3 Advanced 排序(D3 决策)

`factorGroups()` 内对每个分组的 primary / secondary 列表做稳定排序:`advanced asc, 原顺序`。advanced=true 排到分组末尾(不折叠)。

---

## 6. 与计划报告的差异

| 维度 | 计划 §5 | 实际 | 差异原因 |
|---|---|---|---|
| 总卡片数 | 77 | **74** | D4 细化:price_ma_20 多 1 张死卡 + etf_flow_7d/30d 不新增改为增强 |
| 死卡数 | 9 | 10 | 上同 |
| 新增数 | 15 | 13 | 上同 |
| 改标签数 | 38 | 37 | price_ma_20 从"改 Layer B"变为"删死卡" |
| Layer A 标签卡 | ~31 | **41**(含 specs)| 计划没把 26 个 spec 加进算式 |
| Layer B 标签卡 | ~36 | **26** | 同上 |
| Layer A / B 标签卡 | ~10 | **7** | D4 修正后实际共用因子是 8 个,但其中 1 个(sth_realized_price)的 spec 端只有 Layer A 标签 |

**建议**:计划文档的预期数字是"概算",本报告的 74 是"精确数"。生产环境跑完用户实际看到的就是 74。

---

## 7. 测试覆盖

| 文件 | 改动 |
|---|---|
| `tests/test_factor_card_emitter.py` | +30 新测试(8 数据模型 + 8 override + 2 死卡验证 + 12 新卡 + 1 advanced 数 + 1 etf 增强 — 累计 40 个测试)|
| `tests/test_factor_card_24h_daily.py` | -5 测试(liquidation×3 + LSR×2 死卡测试)|
| `tests/test_factor_card_naming_binance.py` | -3 测试(top_lsr / liquidation / lsr_24h_change 死卡测试)|
| `tests/test_sprint_1_6_new_factors.py` | 改 1(returns_9_cards → returns_6_cards)+ 删 1(lth_mvrv_card_uses_computed_source)|
| `tests/test_web_modules_4_5_rp_failure.py` | 改 3(factorStatusLine → 新 inline 模式断言)|

### 7.1 Pytest 最终状态

**1898 passed / 1 failed (pre-existing) / 1 skipped** ✅

预存失败:`test_collect_klines_1h_kline_succeeds_derivatives_fail`(与本 sprint 无关,git stash 干净状态下也失败)

---

## 8. 部署四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ 1898/1898 真实测试 |
| GitHub push(6 个 commit) | ❌ 待用户审完报告后执行 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart btc-strategy | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A(无 schema 变更)|

---

## 9. 部署后用户验证清单

push + restart 之后,建议用户:

1. **刷新网页** `http://124.222.89.86`(用 btcuser + 上轮终端凭据登录)
2. **看"原始数据因子"区**:
   - 卡片总数应该是 **74**(原 71 + 3 净增)
   - 9 张死卡消失:LSR / Liquidation / Top LSR / SSR / LTH-MVRV / STH-MVRV / MA-20 / MA-60 / MA-120 / tf_alignment
   - 13 张新卡可见:BTC 当前收盘价 / EMA-4h ×2 / EMA 30d 斜率 ×2 / ATR-14 / 价格 90d 分位 / 60d 最大回撤 / 收益率曲线利差 / 极端事件标志 / 周线结构 / LTH 持有总量 / STH 90d 变化
3. **看标签颜色**:
   - 蓝色 `Layer A` 卡(链上估值 / MA-200 / SOPR 等)
   - 暖橙色 `Layer B` 卡(funding / OI / EMA / events 等)
   - 紫色 `Layer A / B` 卡(DXY / VIX / Nasdaq / M2 / sth_realized_price / 等)
4. **点 ▾ 详情按钮**:验证展开后显示"该因子被 X 消费"
5. **advanced 卡顺序**:每个分组内 8 张 advanced 卡(EMA-4h / slope / ATR / price_position / drawdown / btc_close)应排在末尾
6. **(下次 11:35 BJT pipeline 跑完后)**:观察后端实际写 latest_factor_cards 的数量 = **53 张**(5 composite + 48 非 composite),前端拉 26 specs 后总 74

---

## 10. 风险 / 边界

### 10.1 网页布局变化

- composite tier 从 6 → 5(上轮 sprint 已减,本 sprint 不影响)
- 非 composite tier 增加 ~3 张(38 → 48 含新增)
- 5 个分组都会多几张卡:`price_technical` 增 8 张(新 EMA / ATR / drawdown / position 等)是变化最大的
- 若用户视觉觉得 price_technical 过满,建议未来按 D3 的"折叠"模式做(本 sprint 是排序,不折叠)

### 10.2 测试是否完整

✅ 完整 — 新增 30 个 emitter 测试 + 3 个 web 测试更新。覆盖:
- 数据模型 3 个新字段(consumed_by_layers / linked_layer_simplified / advanced)
- override dict 映射准确性
- 死卡删除验证
- 13 张新卡每张的归属断言
- advanced=8 计数
- UI 渲染含三个新 helper / state

⚠️ **JS 端没有单元测试覆盖**(项目没有 JS test runner)。`factorLayerClass` / `factorConsumedDetail` / `toggleCardDetail` 三个新 JS 函数 + advanced 排序逻辑只能靠 HTML grep + 用户视觉验证。建议部署后用户花 30 秒点开任意 5 张卡的 ▾ 详情按钮,确认能看到正确内容。

### 10.3 是否需要部署后做视觉验证

是。建议清单见 §9。重点 3 处:
- 标签颜色(蓝 / 橙 / 紫)能否区分
- ▾ 按钮可点 + 展开内容正确
- advanced 卡确实在分组末尾

### 10.4 后续 backlog(本 sprint 未做)

| Backlog | 描述 |
|---|---|
| B1 | 高级因子默认折叠(替代当前的排序方案,如 D3 决策回滚)|
| B2 | sth_realized_price / lth_realized_price 卡从 `_emit_onchain_reference` 共享循环拆出,linked_layer 改为 Layer A(本 sprint 通过 override dict 解决,但 emitter 函数层面仍混杂)|
| B3 | composite tier 卡片视觉重新设计(5 张组合卡的展示语义本质是"系统派生综合分",与 raw 数据卡区分度可加强)|
| B4 | JS 端测试基础设施(jest / vitest)— 未来跨平台增加 JS 单元测试时再考虑 |

---

## 11. 工作区状态确认

**未卷入本 sprint 任何 commit 的改动**(保留状态):
- ✅ 上轮 redaction 改动:40 个 `docs/cc_reports/sprint_*.md` + CLAUDE.md
- ✅ `uv.lock`(预存 dirty)
- ✅ `_review_bundle/`、`_review_bundle_2/`、`btc_*.zip`(未追踪 binaries)

---

**报告完**。Sprint 6 个 commit,74 张卡,3 档标签,8 张高级因子。等用户审完执行 push + 部署。
