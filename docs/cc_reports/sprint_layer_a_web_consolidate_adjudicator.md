# Sprint Layer A 网页布局调整 — 大周期裁决并入交易员结论横幅

**日期**:2026-05-17
**目标**:Layer A 网页板块取消"大周期裁决"卡片(原 4 卡之一),把它的全部内容并入上方的"交易员结论"横幅,横幅下方仅保留 3 个数据包卡片。
**触发**:用户指令(纯前端布局调整;Python / 数据 / AI 调用 / prompt / 状态机一概不动)。

---

## 1. 改动文件清单

| 文件 | 改动 |
|---|---|
| [web/assets/app.js](web/assets/app.js#L1368-L1414) | (a) `spotLayerCards()` 删除第 4 张 `cycle_adjudicator` 卡片的 push,函数从返 4 项变成返 3 项,只保留 `packetCards`;(b) 新增 `cycleAdjudicatorDetails()` getter,返回 5 段分离的对象 `{supporting, next_stage_signals, opposing, invalidation_signals, data_quality}`,**两两分离不合并**(按用户指令 prompt 字段语义对齐) |
| [web/index.html](web/index.html#L420-L477) | (a) `region-layer-a-summary` 下方的"交易员结论"框扩展成大块,顶部保留 `spotFinalAdvice() / spotFinalSummary()` 原两行;**新增 5 段详情区**(支持证据 / 下一阶段确认条件 / 反方证据 / 当前阶段失效条件 / 数据质量备注),**默认全部展开**(无折叠按钮),视觉风格照搬旧卡片的 `stat-label + ul` 套路;(b) 数据包卡片网格 `lg:grid-cols-5` → `lg:grid-cols-3`(3 张卡片填满一行) |
| [tests/test_web_modules_1_2_3.py](tests/test_web_modules_1_2_3.py#L587-L645) | (a) 旧断言 `"layer_a_cycle_adjudicator" in js` 删除(card 已不在 js);(b) 替换为 `"cycleAdjudicatorDetails()" in js`(验证新数据路径);(c) `test_layer_a_spot_summary_is_compact_and_trader_like` 改为检查新横幅 + 5 段中文 stat-label;(d) **新增 `test_layer_a_spot_layer_cards_only_three_packets`** —— 直接验证 spotLayerCards 不再含 cycle_adjudicator + region-layer-a-spot 区域内网格已是 3 列(用 region 字符串切片精确锚定,避开 dashboard 顶部别的 `lg:grid-cols-5`) |

## 2. 决策记录

- **支持证据 vs 下一阶段确认条件 分开展示**(不合并):用户明确选 1,理由"prompt 第八节本来就分开,用途不同"。反方证据 vs 失效条件同理。所以横幅下方 5 段,不是 3 段。
- **默认展开**(不折叠):用户选 2 + 我自决"统一展开比 mobile 折叠实现简单"。Tailwind grid `md:grid-cols-2` 让 4 个文字段在桌面 2×2、mobile 1 列堆叠;数据质量备注 `md:col-span-2` 全行占据。Mobile 长度可控,因为每段 typically ≤ 5 条短句。

## 3. 不动的部分(按指令严格保护)

- 顶部 6 状态框(`region-layer-a-summary`,index.html:382-416)— 完整保留
- `spotStrategy()?.a1_cycle_stage?.stage_change_reason` 那行独立显示(index.html:417-418)— 完整保留
- `spotFinalAdvice()` / `spotFinalSummary()` 两个 JS 方法 — 完整保留,横幅顶部继续读它们
- Python 任何代码、prompt 文件、normalizer / validator / state_machine — 0 改动
- 因子卡片 region(`layerAFactorCardSpecs`,app.js:1432+)— 0 改动
- Layer B 整片 — 0 改动

## 4. 测试结果

```
.venv/bin/python -m pytest tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py
95 passed in 0.07s

.venv/bin/python -m pytest --tb=line -q
1 failed, 1876 passed, 1 skipped, 672 warnings in 47.65s
```

- Web 专项 95/95 通过(原 94 通过 + 我新增 1 项 `test_layer_a_spot_layer_cards_only_three_packets`)
- 全量 1876 通过(比上次 +1,因新加测试)+ 1 上游遗留失败(`test_collect_klines_1h_kline_succeeds_derivatives_fail`,自 commit `16cad4f` 以来历次 sprint 都记录过的 `provider_error` 断言遗留,与本次无关)+ 1 skipped

## 5. 视觉/交互效果(无法跑浏览器,文字描述)

改造后 Layer A 板块从上到下:

1. **页面头** 🌕 大周期策略(Layer A · 现货仓)+ 更新时间副标题 — 不变
2. **顶部 6 状态框**(正式阶段 / 当前特征 / 确认状态 / 策略 / 置信度 / 风险)— 不变
3. **stage_change_reason 独立一行**(状态机阶段变更原因)— 不变
4. **交易员结论大块**(新版本):
   - 上半:`spotFinalAdvice()` 粗体一句话标题(action · stage · headline)
   - 下半:`spotFinalSummary()` 灰体 1-2 句话摘要(trader_summary)
   - 一条横分隔线
   - 详情 2×2(桌面)/ 1 列(mobile)网格:
     | 支持证据(supporting_evidence) | 下一阶段确认条件(what_would_confirm_next_stage) |
     | 反方证据(opposing_evidence) | 当前阶段失效条件(what_would_invalidate_current_stage) |
   - 横跨整行:数据质量备注(data_quality_notes + validator.warnings)
   - **全部默认展开,无折叠按钮**
5. **3 张数据包卡片**(`grid lg:grid-cols-3` 横向并排;mobile 1 列)
   - 价格结构 · 链上估值与持有者 · 资金流与宏观
   - 卡片自身的"查看详细 ▼"折叠保持不变

## 6. 删除清单(本 sprint)

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| `spotLayerCards()` 内 cycle_adjudicator 卡片的 push 块(共 ~22 行) | `web/assets/app.js:1399-1420`(旧版) | 大周期裁决从数据包卡片网格中移走,内容已并入交易员结论横幅;卡片本身就此消失 |
| 测试断言 `assert "layer_a_cycle_adjudicator" in js` | `tests/test_web_modules_1_2_3.py:600`(旧版) | 该字符串确实已从 app.js 移除(配合改动 1)|
| 网格列数 `lg:grid-cols-5`(Layer A 区域) | `web/index.html:427`(旧版) | 4 卡 → 3 卡,列数随之改 3 |

**自检 `git grep`**:
- `git grep "key: 'layer_a_cycle_adjudicator'"` 在 src/ web/ = 0
- `git grep "title: '大周期裁决'"` 在 src/ web/ = 0
- 索引 `region-layer-a-cycle-adjudicator`(新加的 HTML id)在 index.html 出现 1 次 + tests 1 次(断言),无残留
- `cycle_adjudicator`(下划线变量名,数据字段名)在 app.js 仍出现 5 次,**这是数据字段引用,不是死代码** —— `spotFinalAdvice/spotFinalSummary/cycleAdjudicatorDetails` 都需要读 `s.cycle_adjudicator.xxx`,保留正确

## 7. 部署四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅(95/95 web + 1876/1876 非遗留 + 1 已知上游遗留)|
| 本地浏览器肉眼检查 | ❌ N/A(本机无法跑浏览器自验证,UI 视觉效果以用户上线后实际查看为准)|
| GitHub 推送 | ❌ 待执行(本报告写完后立即 commit + push)|
| 服务器 git pull | ❌ 待用户执行 |
| 服务器 systemctl restart | ❌ 待用户执行(restart 后浏览器强刷 / `Ctrl+Shift+R` 清缓存即可看到新布局)|

## 8. 给用户上线后核对的清单

1. 大周期裁决卡片应**完全消失**;下方一行只剩 3 张卡片(价格结构 / 链上估值与持有者 / 资金流与宏观)
2. 交易员结论横幅展开后应**直接看见 5 段标题**:支持证据 / 下一阶段确认条件 / 反方证据 / 当前阶段失效条件 / 数据质量备注
3. 这 5 段的内容应非空(假设 AI 输出正常),分别对应 prompt 第八节的:
   - supporting_evidence ✓
   - what_would_confirm_next_stage ✓
   - opposing_evidence ✓
   - what_would_invalidate_current_stage ✓
   - data_quality_notes + validator warnings ✓
4. 顶部 6 状态框 + stage_change_reason 那行均保持原样,字段值不变
