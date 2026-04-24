# Sprint 1.5c 报告:硬纪律最终修复 + 对外契约对齐建模 §9.10/§10.4(Sprint 1.5 系列收官)

## Triggers(偏离建模 / 自主决策)

1. **DAO 类名保持 Sprint 1 命名(BTCKlinesDAO / StrategyStateDAO / FallbackLogDAO)**,只改 SQL 内部指向新表。新加的 lifecycles / evidence_card_history / alerts / kpi_snapshots 后续按需再开新 DAO 类;v1 暂由 API 路由直接 SQL 操作。
2. **derivatives_snapshots 宽表 + 长式 API 保留**:§10.4 规定宽表,但老代码(collectors)按长式 DerivativeMetric 产出。采用混合方案:upsert 时按 timestamp 分组 pivot 到宽表三主字段 + 其余 JSON;读取时 `_explode_row` 反向展开,老 API(`get_series` / `get_all_metrics`)照常返回长式 dict。
3. **run_metadata 表不再存在**,相关信息折入 strategy_runs(run_trigger / fallback_level / state_transitioned 等)。`RunMetadataDAO.start_run` / `finish_run` 改成 no-op stub 以向后兼容调用方。
4. **review_reports PK 改了**(run_timestamp_utc → review_id),迁移用 `DROP TABLE IF EXISTS` 重建(原表 0 行,数据零损失)。
5. **AI 中转站 env 变量沿用原名**:用户明确不动 .env,所以 OPENAI_API_BASE / OPENAI_API_KEY / OPENAI_MODEL 保留;anthropic SDK 的 base_url / api_key 在代码里读这三个 env 赋值。新代码不能假设将来必然改到 AI_BASE_URL 之类。
6. **hard_invalidation_levels 升级为 list + 结构性 HL/LH**:§4.5.2 要求;但 v1 只返回 priority=1(结构性)+ priority=2(stop_loss 兜底)共 ≤2 条。更精细的失效位(如主要支撑线)留给 Sprint 2+。
7. **scripts/backfill_data.py 对 Yahoo Finance / FRED 采集器用 hasattr 探测**:这两个 collector 的 public method 命名不统一,为防止脚本因接口不一致就 crash,用 hasattr 做能力探测。

## Task 执行结果

### Task C1:L4 读 previous_state 处理 PROTECTION 例外

- [src/evidence/layer4_risk.py](src/evidence/layer4_risk.py):`state_machine_state` 读取顺序 `previous_state_machine_state` → `state_machine_hint` → `state_machine_output.current_state` → 默认 `"FLAT"`。
- [src/pipeline/state_builder.py](src/pipeline/state_builder.py):新增 `_read_previous_state_machine_state()`,从 DB `StrategyStateDAO.get_latest_state()` 取上次的 `state_machine.current_state`,注入到 `context["previous_state_machine_state"]`。
- 双保险:Adjudicator 的硬约束前置拦截保留(首次进入 PROTECTION 那轮 L4 还没见到)。
- 单测:`test_12b_protection_override_via_previous_state`

### Task C2:hard_invalidation_levels 升级为 list + 结构性 HL/LH

- `_find_structural_invalidation()` 在最近 60 根 1D 上调 `swing_points(lookback=5)`:
  - bullish:最近 swing_low > 前一 swing_low(Higher Low 结构)→ 作 priority=1 失效位
  - bearish:最近 swing_high < 前一 swing_high(Lower High 结构)→ 作 priority=1 失效位
- 合并成 list:`[{priority:1 structural, priority:2 stop_loss 兜底}]`,neutral 方向返回空 list。
- 每条含 `{price, direction, basis, priority, confirmation_timeframe='4H'}`(§4.5.7 结构)。
- Adjudicator `_extract_facts` 新增 `l4_hard_invalidation_levels` 字段,供 AI prompt 读取(已在 Sprint 1.5b 做过,字段正式有值了)。
- 单测:`test_18b_hard_invalidation_structural_hl_priority_1` / `test_19b_...` / `test_18_...priority_2`。

### Task C3:cold_start 检查合并到 utility

- 新建 [src/utils/cold_start.py](src/utils/cold_start.py):`is_cold_start(state, threshold_runs=42)` 单一事实源,`DEFAULT_COLD_START_RUNS=42`。
- observation_classifier 和 adjudicator 都 import 此函数,删除各自的 inline 检查。
- 单测:[tests/test_cold_start_util.py](tests/test_cold_start_util.py) 7 case。

### Task C4:数据库 Schema 改名对齐建模 §10.4

**迁移前备份**:`data/btc_strategy.db.bak.before_c4`(未 commit,在 .gitignore)。

**重写 [src/data/storage/schema.sql](src/data/storage/schema.sql)** 为建模 §10.4 权威 11 张表(+ events_calendar 保留):

| 旧表 | 新表 | 字段变化 |
|---|---|---|
| `btc_klines` | `price_candles` | +symbol, timestamp→open_time_utc, volume_btc→volume, 删 volume_usdt/fetched_at |
| `derivatives_snapshot`(长式) | `derivatives_snapshots`(宽式) | captured_at_utc PK + funding_rate/open_interest/long_short_ratio 主列 + full_data_json |
| `onchain_snapshot` | `onchain_metrics` | timestamp→captured_at_utc, metric_value→value |
| `macro_snapshot` | `macro_metrics` | 同上 |
| `strategy_state_history` | `strategy_runs` | PK 改为 run_id;+ v1.2 新字段:reference_timestamp_utc/rules_version/strategy_flavor/observation_category/cold_start/ai_model_actual/action_state/stance/btc_price_usd/state_transitioned/run_mode/previous_run_id |
| `review_reports` | 同名(重建) | PK 改为 review_id,+ rules_version_at_review |
| `fallback_log` | `fallback_events` | triggered_at_utc/reason/resolved_at_utc/resolution_note |
| `run_metadata` | 删除 | 信息折入 strategy_runs |
| - | **新增 lifecycles** | ai_models_used / rules_versions_used |
| - | **新增 evidence_card_history** | data_fresh |
| - | **新增 alerts** | notification_sent |
| - | **新增 kpi_snapshots** | 全新表 |

**[migrations/001_align_to_modeling_schema.sql](migrations/001_align_to_modeling_schema.sql)**:BEGIN/COMMIT 原子事务迁移,INSERT OR IGNORE + json_extract 从旧表搬数据到新表,然后 DROP 旧表。derivatives 长式 pivot 到宽式用 `GROUP BY timestamp + MAX(CASE WHEN metric_name='funding_rate' THEN value END)`。

**DAO 层改造**(src/data/storage/dao.py,981 → ~1030 行):类名不变,SQL 指向新表,读取时把新字段映射回老 API 期待的名字(`_map_row`/`_map_strategy_run_to_legacy`);DerivativesDAO 做 pivot(upsert)和 explode(read)两个方向的转换。

**下游更新**:`src/api/routes/*`、`src/review/generator.py`、`src/monitoring/alerts.py`、`src/kpi/collector.py` 的 SQL 全部改成读新表。tests/test_state_builder.py 和 tests/test_api_routes.py 断言更新。

**数据保留**:迁移后 strategy_runs=9,price_candles=1844,derivatives_snapshots=500,onchain_metrics=2520,fallback_events=3;全部旧 DB 数据保留。

### Task C5:FastAPI 路由对齐 §9.10 + SSE

新增完整的 §9.10 10 个路由,老路径作为 alias 保留:

| # | 路径 | 说明 | 实现 |
|---|---|---|---|
| 1 | GET `/api/strategy/current` | 最新策略 | [strategy.py](src/api/routes/strategy.py) |
| 2 | GET `/api/strategy/stream` | SSE 实时推送 | 同上,`StreamingResponse` + 异步生成器 |
| 3 | GET `/api/strategy/history` | 分页历史 | 同上(Sprint 1.15 已有,改表名即可)|
| 4 | GET `/api/strategy/runs/{run_id}` | 单次详情 | 同上 |
| 5 | GET `/api/evidence/card/{card_id}/history` | 证据指标时序 | 新 [evidence.py](src/api/routes/evidence.py) |
| 6 | GET `/api/lifecycle/current` | 当前生命周期 | 新 [lifecycle.py](src/api/routes/lifecycle.py)(v1 从 state.lifecycle 读)|
| 7 | GET `/api/lifecycle/history` | 生命周期归档 | 同上 |
| 8 | GET `/api/review/{lifecycle_id}` | 复盘报告 | 新 [review.py](src/api/routes/review.py) |
| 9 | GET `/api/system/health` | 系统健康 | 新 [system.py](src/api/routes/system.py) |
| 10 | POST `/api/system/run-now` | 手动触发 | 同上 |

**meta.strategy_flavor** 固定 `"swing"` 自动补齐在 `_row_to_model()`。不接受 `?flavor=xxx` 过滤(§9.10 v1.2 规则)。

SSE 实现:
- `StreamingResponse(event_gen(), media_type="text/event-stream")`
- 每 30 秒轮询 `StrategyStateDAO.get_latest_state()`,若 `run_id` 变化就 emit 新 payload
- 其它时刻发 `: keep-alive\n\n` heartbeat
- 客户端断开通过 `request.is_disconnected()` 检测

单测:[tests/test_api_routes_new.py](tests/test_api_routes_new.py) 10 case 覆盖 9 个非 SSE 端点。

### Task C6:openai SDK → anthropic SDK

- `uv add anthropic` 加入依赖(0.97.0)
- 新建 [src/ai/client.py](src/ai/client.py):
  - `build_anthropic_client()` 工厂
  - `normalize_base_url()` 去除 `/v1` 后缀(anthropic SDK 会自动拼 /v1/messages)
  - `effective_model()`、`extract_text()`、`extract_usage()`、`extract_model()` 工具函数
- 代码层把 `openai.OpenAI` 全部换成 `anthropic.Anthropic`:
  - [src/ai/summary.py](src/ai/summary.py):`client.messages.create(system=..., messages=[{"role":"user",...}])`
  - [src/ai/adjudicator.py](src/ai/adjudicator.py):同上;`_extract_text` / `_usage` 双兼容 anthropic(content[0].text / input_tokens / output_tokens)和老 openai 风格(mocks 过渡用)
  - [src/review/generator.py](src/review/generator.py)`_default_ai_narrative`:同上
- env 变量保持 `OPENAI_API_BASE / OPENAI_API_KEY / OPENAI_MODEL`(用户要求)
- 验证:`novaiapi.com` 支持 anthropic `/v1/messages` 协议,真实调用返回 `resp.content[0].text="Hi there friend!"`,`resp.model="claude-sonnet-4-5-20250929"`(v1.2 M37 的 `ai_model_actual` 来源)
- 单测更新:test_adjudicator / test_ai_summary 把 mock 的 `client.chat.completions.create` 全部改成 `client.messages.create`;MagicMock 的 `content=[block(text=...)]` 和 `usage.input_tokens/output_tokens` 对齐 anthropic 形态
- 新单测:[tests/test_ai_client.py](tests/test_ai_client.py) 6 case

### Task C7:backfill_data.py 180 天回填

[scripts/backfill_data.py](scripts/backfill_data.py) 新建:

用法:
```bash
uv run python scripts/backfill_data.py              # 默认 180 天
uv run python scripts/backfill_data.py --days 30    # 快速测试
uv run python scripts/backfill_data.py --only price # 单类
uv run python scripts/backfill_data.py --dry-run    # 不写库
```

四类数据源:
- **price**:CoinGlass 1h/4h/1d/1w K 线,目标条数按 days 推导
- **derivatives**:CoinGlass 资金费率 + 多空比(1d 粒度)
- **onchain**:Glassnode 9 个指标(mvrv_z / nupl / lth_supply / exchange_net_flow / mvrv / realized_price / sopr / reserve_risk / puell_multiple)
- **macro**:Yahoo Finance(DXY/SP500/Nasdaq/VIX/US10Y)+ FRED(DFF/DGS10/VIXCLS),hasattr 能力探测

幂等:DAO upsert 语义;单 collector 异常不中断全局(`_safe` 包装)。

验收:`uv run python scripts/backfill_data.py --days 7 --only price` 跑通,`price_candles` 新增行;日志形如 `[price.1h] fetched=168 upserted=168 elapsed_ms=2550`。

### Task C8:单测 + 集成测试 + 验收

- **pytest**:**325 passed / 1 skipped**(从 Sprint 1.5b 末尾 299 → +13 new(ai_client 6 + api_routes_new 10 + cold_start_util 7 - test_cold_start_util 本身已在 1.5c-1 加)- 一些重构的改动不改总数)
- `uv run python scripts/run_pipeline_once.py --dry-run` 端到端成功,无 failures 无 degraded
- `curl http://localhost:8000/api/system/health` → 200 + `{status:ok, db_accessible:true}`
- `curl http://localhost:8000/api/strategy/current` → 200,`body.state.meta.strategy_flavor="swing"`
- `curl http://localhost:8000/api/strategy/stream` → 200 + `Content-Type: text/event-stream`(SSE)
- `sqlite3 data/btc_strategy.db ".schema"` → 11 张 §10.4 表 + events_calendar,无旧表残留

### Commits

1. `5a2c2b1` — Sprint 1.5c-1: L4 reads previous_state, hard_invalidation_levels list, cold_start utility
2. `6df54fa` — Sprint 1.5c-2: database schema aligned to modeling §10.4
3. `ba3a038` — Untrack db backup; expand gitignore
4. `5c24806` — Sprint 1.5c-3: API routes aligned to modeling §9.10 + SSE stream
5. `ed7e036` — Sprint 1.5c-4a: switch AI SDK from openai to anthropic
6. (本 commit) — Sprint 1.5c-4b: 180-day backfill + final tests + report

## 简短三段汇报

**结果**:Sprint 1.5c 完成,Sprint 1.5 系列收官。硬纪律修复:L4 读前一次 state_machine.current_state 处理 PROTECTION 例外、hard_invalidation_levels 升级为 list 含结构性 HL/LH、cold_start 检查合并到 `src/utils/cold_start.is_cold_start`。对外契约全部对齐建模:11 张 §10.4 表(price_candles / strategy_runs / lifecycles / evidence_card_history / alerts / fallback_events / kpi_snapshots / derivatives_snapshots / onchain_metrics / macro_metrics / review_reports)迁移脚本幂等,§9.10 十个 API 路由 + SSE 齐备,openai SDK 换成 anthropic SDK 并通过 novaiapi 中转站验证实际调用成功,scripts/backfill_data.py 支持 180 天冷启动回填。全仓库 **325 passed / 1 skipped**。

**自主决策**(都记 Triggers 段):
- DAO 类名保持 Sprint 1 命名(BTCKlinesDAO 等),只改内部 SQL;新表 API 路由直接 SQL
- derivatives_snapshots 宽表 + 老长式 API 保留(upsert pivot,read explode)
- run_metadata 表删除,信息折入 strategy_runs;DAO stub 保留兼容
- review_reports PK 改名(run_timestamp_utc → review_id),空表所以 DROP 重建
- env 变量沿用 OPENAI_API_BASE / OPENAI_API_KEY / OPENAI_MODEL(.env 不动)
- hard_invalidation_levels v1 只输出 ≤2 条(结构性 + stop_loss 兜底),更精细的留给 Sprint 2+
- scripts/backfill_data.py 对 Yahoo/FRED collector 用 hasattr 能力探测(接口命名不统一)

**待关注**(给 Sprint 2+):
1. **lifecycles / evidence_card_history / alerts / kpi_snapshots 四张新表目前 0 行**,需要 Sprint 2+ 的 lifecycle_manager / evidence_card_emitter / alerts writer / kpi persister 真正填充
2. **observation / position_cap 等系统自身产物**仍是从 `strategy_runs.full_state_json` 抽,没落成独立字段;上了规模后可考虑抽字段建索引
3. **SSE `/api/strategy/stream`** 轮询间隔 30s 写死,生产可改成事件驱动(pipeline 一跑完就 notify)
4. **backfill_data.py 的 macro 部分依赖 collector 的 public API 命名**,Sprint 2 应该统一成 `fetch_series(symbol, period, interval)` 接口
5. **RunMetadataDAO stub** 仍在,应该 Sprint 2 清理完全
6. **anthropic SDK 响应中 resp.content 可能是多个 block**(模型输出带思考块时),当前 `extract_text` 只取第一个 text block,复杂场景要扩展
