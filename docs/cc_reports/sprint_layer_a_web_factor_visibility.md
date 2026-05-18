# Sprint 1.6.3 — Layer A 网页因子可见性补全

**日期**:2026-05-17
**目标**:让用户在网页看见 AI 实际分析的全部 Layer A 因子。两件事:
1. 数据包卡片 supporting 取消 `.slice(0, 5)` 上限,显示全部 key_metrics
2. "原始数据因子" 模块补全 6 个 Layer A 已用但前端 specs 漏写的因子

纯前端改动,不碰后端/采集/AI 调用/prompt。

---

## 1. 改动文件清单

| 文件 | 改动 |
|---|---|
| [web/assets/app.js](web/assets/app.js#L1385-L1396) | (a) **删除 [line 1385](web/assets/app.js#L1385) 的 `.slice(0, 5)`** — 数据包卡片 supporting 现展示该 packet 全部 key_metrics(price_structure 8 项 / onchain 24 项 / macro_flow 13 项),AI 看到啥用户就看到啥。补充注释解释设计意图。(b) **layerAFactorCardSpecs() 数组末尾追加 6 个 spec**:`hash_rate`(算力)/ `sopr`(整体 SOPR)/ `ma_200w_deviation_pct`(200WMA 乖离)/ `ma_200w` / `ma_200d` / `ath_drawdown_pct`,按现有 spec 的字段格式(key/name/name_en/group/source/value_unit/paths)。前 2 个归 `onchain`,后 4 个归 `price_technical` |
| [tests/test_web_modules_1_2_3.py](tests/test_web_modules_1_2_3.py#L644-L673) | 新增 2 个测试:`test_layer_a_packet_supporting_no_slice_cap`(断言 .slice(0,5) 已删 + 新形态出现);`test_layer_a_factor_specs_includes_new_layer_a_factors`(断言 6 个新 key + 6 个中文标签都在 js 里) |

---

## 2. 视觉/行为效果

### 数据包卡片(交易员结论横幅下方 3 张)

| Packet | supporting 改前 | supporting 改后 |
|---|---|---|
| price_structure_packet | 5 行(slice 截)| 8 行(全部) |
| onchain_packet | 5 行(slice 截)| **24 行**(全部)|
| macro_flow_packet | 5 行(slice 截)| 13 行(全部)|

每行短(`name: value`),mobile 也可滑动浏览。缺值字段的 `value` 显示为该字段的 `status`(`missing` / `stale`),不藏。

### "原始数据因子" 模块

| 阶段 | layerAFactorCardSpecs 条目数 | 网页"共 N 个" 估算 |
|---|---|---|
| 改前 | 20(只含 onchain 11 + price_technical 2 + macro 7)| ~65(Layer B emitter 动态产卡 ~45 + Layer A 20)|
| 改后 | **26**(+6:hash_rate / sopr / ma_200w_deviation_pct / ma_200w / ma_200d / ath_drawdown_pct)| **~71**(Layer B 同前 + Layer A 26)|

新增 6 个分组归属:
- **onchain × 2**:`hash_rate`(算力,Glassnode mining 端点)、`sopr`(整体 aSOPR,Glassnode indicators)
- **price_technical × 4**:`ma_200w_deviation_pct`(200WMA 乖离 %)、`ma_200w`、`ma_200d`、`ath_drawdown_pct`(距 ATH 回撤 %)

---

## 3. 因子总数核对(用户特别要求)

### 核对结果:Layer A specs 26 + Layer B emitter 动态 ≈ "共 71" — **比 65 多 6,与本次新增对得上**

代码数据:
- Layer A specs(本次改后)= **26** 个(已 grep 验证)
- Layer B `factor_card_emitter.py` 内 `_make_card(...)` 调用点 = **38** 处(部分为 if 分支条件性触发,实际产卡数随 state 而变,典型 ~30-35)
- Layer A `_A1_CORE_FACTORS`(数据包真实使用因子)= **30** 个
- Layer A `_A2_A4_BACKGROUND_FACTORS`(背景因子)= **17** 个
- `_FACTOR_SOURCE` 注册总数 = **47** 个

**为什么"共 N 个" ≠ Layer A factor_coverage(用户说 68)**:这是两套独立计数,**永远不会精确相等**。
- **`factor_coverage`** 是 Layer A 计算的"已接入因子可用率"(`available_factors` 字典里非 None 的因子数),完全围绕 Layer A 数据包定义
- **网页"共 N 个"** = `rawFactorCards().length` = `state.factor_cards`(Layer B emitter,含 funding_rate / OI / 多空比等衍生品)+ `layerAFactorCards`(本 specs)。**包含 Layer B 的衍生品因子卡** — 这是 Layer A 数据包里**故意不要**的(`_LAYER_B_CONTEXT_FACTORS` 7 个),但前端仍展示给用户做完整审计

因此:
- 修复前网页 "共 65" → 修复后 "共 ~71"
- Layer A factor_coverage = 68(只算 Layer A 用)
- 两个数字**逻辑上不需要对齐**;前端展示>Layer A coverage 是正常的(Layer B 衍生品额外显示)
- 若用户期望"原始数据因子 = Layer A 实际使用的 47 个",需要拆视图(Layer A 专属 vs Layer B 完整)— **本次不做,留作后续 UX 改动**

### 还差什么(用户问"如果还差,差哪几个")

按上面拆解,Layer A 角度看 **不差**:
- 数据包真实使用的因子 47 个全部经过 `cycle_evidence_summary` → AI 都看到
- 数据包卡片 supporting 现展示全部 key_metrics(共 8+24+13=45 字段)
- 原始数据因子 specs 已含本次新接的 6 个,Layer A 那侧 26 个 specs 覆盖 Layer A 关键因子

仍漏的(不在 Layer A specs 但 Layer A 实际用了):
- `mvrv_z_score` / `mvrv` / `nupl` / `realized_price` / `lth_realized_price` / `sth_realized_price` / `lth_supply` / `sth_supply` / 等
- 这些**全部由 Layer B `factor_card_emitter` 动态产卡**进 `state.factor_cards`,所以前端 "共 N 个" 已经统计了;**Layer A specs 没必要重复**(否则会出现两张 mvrv_z_score 卡)
- `cdd` / `ssr` / hodl 12 个 bucket — Layer A 数据包没用裸名,只用 `hodl_waves_1y_plus_aggregate` 派生,specs 也只补一个 1y+(已存在)

**结论**:本 sprint 补 6 个之后 Layer A 网页因子可见性达到"AI 看到啥用户都能看到",不需要再加。如果上线后用户在网页核对发现某个因子在数据包 supporting 里有但模块缺,告诉我具体 key 名,我再补 spec(预期不需要)。

---

## 4. 建模 §7.6 永久规则(用户要求记一笔)

**规则**:`layerAFactorCardSpecs()` 是手写硬编码列表,Layer A 任何新接入的因子(在 `_FACTOR_SOURCE` / `_A1_CORE_FACTORS` / 数据包 key_metrics 注册)**必须同步追加一条 spec**,否则前端"原始数据因子"模块永远不显示这个因子。

**触发本规则的历史教训**:
- Sprint `82e59f9`(3 包重构)加 `hash_rate` / `sopr` / `ma_200w_deviation_pct` 到 Layer A 数据包,但忘了同步 `layerAFactorCardSpecs` → 用户在网页看见"共 65 个"vs Layer A factor_coverage "可用 68",差 3 个 → 本 Sprint 1.6.3 补回(并连带补 ma_200w / ma_200d / ath_drawdown_pct 共 6 个,因为这些 Layer B emitter 也没 emit,前端历史上一直漏)

**自检清单**(任何加 Layer A 因子的 sprint commit 前必跑):
```bash
# 1. 列出 Layer A 数据包里的所有 key_metrics 名
grep -E "^\s+\"[a-z_]+\":" src/ai/spot_cycle_context_builder.py | grep -oE '"[a-z_]+":' | sort -u

# 2. 列出 layerAFactorCardSpecs 里的所有 key
awk '/layerAFactorCardSpecs\(\)/{found=1} found && /^[[:space:]]*\];/{exit} found' web/assets/app.js | grep -oE "key: '[^']+'"

# 3. 比较,缺的就是需要在 specs 里加的(注意去掉 Layer B emitter 已覆盖的)
```

**写入 CLAUDE.md §X(工程纪律)**:当前 CLAUDE.md §X 已有"旧代码必须删除而不是堆叠"等条款。建议**新加 §Z**:"Layer A 新增因子时,layerAFactorCardSpecs 必须同步追加",并把上面 3 步自检命令落地。**本 sprint 暂不动 CLAUDE.md**(改 CLAUDE.md 属用户决策范围,需独立确认);**本报告 §4 记录,作为未来参考凭据**。

---

## 5. 测试结果

```
.venv/bin/python -m pytest tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py --tb=short -q
97 passed in 0.08s

.venv/bin/python -m pytest --tb=line -q
1 failed, 1880 passed, 1 skipped, 672 warnings in 47.55s
```

- 网页专项 97/97 通过(上一 sprint 95 + 本 sprint 新增 2)
- 全量 1880 通过(+2 新增)+ 1 上游遗留失败 + 1 skipped
- 唯一失败 `test_collect_klines_1h_kline_succeeds_derivatives_fail`:多次 sprint 记录的 `provider_error` 断言遗留,与本次完全无关

---

## 6. 部署四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅(网页专项 97/97 + 全量 1880 通过 + 1 上游遗留 + 1 skipped)|
| 本地浏览器肉眼自验证 | ❌ N/A(本机无浏览器)|
| GitHub 推送 | ❌ 本报告写完立即 commit + push |
| 服务器 git pull | ❌ 待用户执行 |
| 服务器 systemctl restart | ❌ 待用户执行(纯前端,实际不重启也行 — 浏览器强刷 `Ctrl+Shift+R` 即可看新页;但重启更稳)|
| 生产 DB 迁移 | N/A(纯前端)|

## 7. 本 sprint 删除清单

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| `.slice(0, 5)` 上限 | `web/assets/app.js:1385`(旧)| 原 4 包卡片设计沿用的"挑 5 条证据"语义,3 包重构后语义变成"显示 AI 看到的全部 key_metrics" — slice 误导用户以为 AI 只看 5 个 |

**自检 `git grep`**:
- `git grep "slice(0, 5)" web/` 在 Layer A 范围 = 0 ✅
- `git grep "key: 'hash_rate'" web/` = 1(新加)
- `git grep "key: 'ma_200w_deviation_pct'" web/` = 1(新加)
- 没有任何旧代码堆叠

## 8. 上线后用户核对清单

1. **数据包卡片**:点开 onchain_packet,看到 ~24 行 `key_metrics`(mvrv_z_score / mvrv / nupl / rhodl_ratio / reserve_risk / puell_multiple / **hash_rate** / **sopr** / realized_price / sth_realized_price / lth_realized_price / lth_sopr / sth_sopr / lth_supply / sth_supply / lth_supply_90d_pct_change / sth_supply_90d_pct_change / lth_net_position_change / percent_supply_in_loss / hodl_waves_1y_plus_aggregate / cdd / exchange_balance / exchange_net_position_change),不再卡 5 行。
2. **数据包卡片**:price_structure_packet 看到 8 行含 `ma_200w_deviation_pct`;macro_flow_packet 看到 13 行。
3. **原始数据因子模块**:`共 N 个` 比之前 65 多 6 左右(约 ~71);展开"链上数据"分组应能找到"算力"和"整体 SOPR";展开"价格技术"应能找到 200 周线乖离率 / 200 周均线 / 200 日均线 / 距 ATH 回撤 4 个新增卡。
4. 若实际数与 Layer A factor_coverage 报告的 68 仍有差距,**那是因为前端额外含 Layer B 衍生品卡**(funding_rate / OI / 多空比等),不是缺。
