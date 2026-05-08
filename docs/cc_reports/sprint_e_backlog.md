# Sprint E backlog — 待 Sprint D 上线后观察 1-2 周再决定

**创建日期**:2026-05-08(Sprint D 收官时)
**触发条件**:观察 1-2 周后,如果发现 master AI 单独决策不够稳(比如 sub-agent
输出 stale 时 master 没"压住",或者 narrative 关键词检查不够细)→ 启动 Sprint E。

## 待办项

### Item E1:5 个 sub-agent prompt 注入 freshness(深度 AI 行为侧改造)

**Sprint D 走的是 (A) 显示侧覆盖**:`_apply_layer_stale_overrides` 只覆盖网页
`evidence_layers.health` 字段,AI 内部 confidence_tier 不动。

**Sprint E (B) 选项**:把 freshness summary 注入 6 个 agent 的 prompt
(L1 / L2 / L3 / L4 / L5 + master),让 AI 自己在每层基础上感知 stale,
narrative 主动写"L2 onchain 数据过期 N 小时,本层置信度自降至 medium"。

实施:
- 改 5 个 sub-agent 的 `_build_user_prompt` 注入 [数据新鲜度] 段(类似 master)
- 改 5 个 .txt prompt 加各自的 stale 纪律(L1 关心 binance_kline,L2 关心
  binance + onchain,...)
- validator 加 5 条规则,各 L_x 输出健康度若 stale 时未自降 → flag

**风险**:
- 5 prompts × 24 条已有 validator 的总组合可能产生意外冲突
- AI 拿到 stale 信息后可能过度保守,降所有 confidence
- 测试 fixture 需更新(预计 10+ 个测试)

**预计工作量**:1-2 个完整工作日

**触发条件**:
- 观察生产 1-2 周
- 若 fetch_attempts 显示 Glassnode 长期 stale,但 master narrative 仍偶尔"忘
  提"过期(VStale validator 频繁触发 needs_retry)→ 上 Sprint E
- 若用户读 strategy_runs 历史 narrative 觉得 AI 对过期数据反应不够明显 → 上
  Sprint E

---

### Item E2:LAYER_SOURCE_DEPS 动态化

当前 `src/data/freshness.py:LAYER_SOURCE_DEPS` 是写死 dict,L2 永远依赖
glassnode_onchain。如果未来:
- Glassnode 永久退役,onchain 改抓 CryptoQuant 等新源 → 需改 deps
- 加新数据源(比如 Whalemap on-chain 衍生指标) → 需 dispatch

考虑 Sprint E 把 LAYER_SOURCE_DEPS 改成 yaml 配置或者从 modeling.md §X 自动抽取。

---

### Item E3:strategy_runs.full_state_json["data_freshness"] 周复盘消费

Sprint D 把 4 源 freshness 块写入 state.full_state_json["data_freshness"]
(state_builder.py:_build_data_freshness_block)。

周复盘 AI(`weekly_review_analyst`)应能消费这个字段,统计:
- 7 天内每源平均 hours_since_last_success
- stale 触发次数
- AI 是否真的在 stale 时降 confidence(交叉验证 strategy_runs.confidence_tier
  vs data_freshness.is_stale)

需要扩 `weekly_review_input_builder` + 改对应 prompt + 输出新一段「数据健康
回顾」。

---

### Item E4:onchain_metrics 老 captured_at_utc 数据清理

历史 derived_mvrv 行带 source='computed',Sprint A 之前不区分 source 时被
当成"新数据"。现在 freshness 模块 + _onchain_today_complete 都加了 source
过滤,但表里仍有这些行(无害,但占空间)。

Sprint E 可加 migration 清理:
```sql
-- 18_drop_legacy_computed_rows.sql
DELETE FROM onchain_metrics WHERE source = 'computed' AND captured_at_utc < '2026-04-01';
```

需先做 backup + 数据归档评估。

---

### Item E5:freshness 阈值改 yaml 配置

`STALE_THRESHOLD_SECONDS` 在 freshness.py 顶部硬编码:
```python
{
    "binance_kline":         3 * 3600,
    "coinglass_derivatives": 3 * 3600,
    "glassnode_onchain":    48 * 3600,
    "fred_macro":           72 * 3600,
}
```

挪到 `config/thresholds.yaml`,与现有阈值结构对齐。
