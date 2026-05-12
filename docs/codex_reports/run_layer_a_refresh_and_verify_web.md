# Run Layer A Refresh And Verify Web

## 1. 当前分支和 commit

- 当前分支：`main`
- 开始时最新 commit：`afafe55 Update Layer A web display report status`
- `git pull --ff-only` 结果：`Already up to date.`
- 本轮开始前已有本地未提交改动：`uv.lock`
- 说明：`uv.lock` 是遗留本地修改，本轮未提交、未打包。

## 2. 是否拉取最新代码

已执行：

```bash
git pull --ff-only
```

结果：

```text
Already up to date.
```

## 3. Layer A 网页代码确认

已执行：

```bash
rg "大周期策略|layer_a_spot_strategy|layer-a-web-display" web src tests
```

确认结果：

- `web/index.html` 有“大周期策略”模块。
- `web/assets/app.js` 有 `layer_a_spot_strategy` 读取和 A1-A5 渲染逻辑。
- `web/index.html` 引用 `/assets/app.js?v=layer-a-web-display-20260512`，已有 cache-busting。
- `src/web_helpers/normalize_state.py` 会返回 `layer_a_spot_strategy`。
- API `/api/strategy/current` 走 normalize 后会把字段放到 `state.layer_a_spot_strategy`。

## 4. 找到的真实命令

### 4.1 本地 API / 网页服务启动命令

代码证据：`scripts/run_api.py`

脚本注释给出的命令：

```bash
uv run python scripts/run_api.py --host 0.0.0.0 --port 8000
```

本轮为了避免本地 API 自己启动 scheduler 产生额外定时任务，使用：

```bash
SCHEDULER_ENABLED=false uv run python scripts/run_api.py --host 127.0.0.1 --port 8000
```

### 4.2 手动运行一次策略 run 的命令

代码证据：`scripts/run_pipeline_once.py`

脚本注释给出的命令：

```bash
uv run python scripts/run_pipeline_once.py
```

本轮实际使用：

```bash
uv run python scripts/run_pipeline_once.py --trigger manual
```

### 4.3 查询最新 strategy_run 的命令

本轮使用 SQLite 只读查询：

```bash
sqlite3 data/btc_strategy.db "SELECT run_id, reference_timestamp_utc, generated_at_utc, json_type(full_state_json,'$.layer_a_spot_strategy') AS layer_a_json_type FROM strategy_runs ORDER BY reference_timestamp_utc DESC, generated_at_utc DESC LIMIT 3;"
```

## 5. 是否重启服务

已启动本地 API 服务。

服务启动方式：

```bash
SCHEDULER_ENABLED=false uv run python scripts/run_api.py --host 127.0.0.1 --port 8000
```

健康检查：

```bash
curl --noproxy '*' http://127.0.0.1:8000/api/system/health
```

结果：HTTP `200`。

说明：

- 后台启动方式在当前沙盒里会被回收，所以本轮用前台会话方式启动服务完成验证。
- 本轮没有启用 scheduler。

## 6. 策略 run 结果

本轮先跑了一次策略 run，生成：

- run_id：`cfb41816e9c746ccb16614c5c48a1d67`
- 时间：`2026-05-12T05:55:42Z`
- `layer_a_spot_strategy`：存在
- 但发现 Layer A validator 对资金费率解释里的“做多需支付做空”误判为做空行动。

随后只修复 Layer A validator/normalizer 的文本误判，再跑第二次策略 run。

最终用于验证的最新 run：

- run_id：`9780c94deffa48c893aa8d9fcfa864df`
- 时间：`2026-05-12T06:03:01Z`
- `full_state_json.layer_a_spot_strategy`：存在，类型为 object
- `layer_a_spot_strategy.enabled`：`true`
- A1 `cycle_stage`：`bear_transition`
- A5 `spot_action`：`dca_buy`
- `validator.passed`：`true`
- `validator.violations`：`[]`
- `validator.warnings`：`[]`

策略 run 脚本退出码为 `1`，原因不是写入失败，而是本地数据 freshness 过期，L1-L5 进入 degraded/fallback：

- `ai_status=degraded_l1_data_missing`
- degraded stages：`l1, l2, l5, l3, l4`
- `persisted=true`

解释给小白：

- 新 run 已经真的写进数据库。
- Layer A 已经写进 `full_state_json`。
- 退出码 1 是“数据太旧，所以策略层降级”，不是“Layer A 没生成”。

## 7. 数据库 / full_state_json 验证

已执行：

```bash
sqlite3 data/btc_strategy.db "SELECT run_id, reference_timestamp_utc, json_extract(full_state_json,'$.layer_a_spot_strategy.enabled'), json_extract(full_state_json,'$.layer_a_spot_strategy.a1_cycle_stage.cycle_stage'), json_extract(full_state_json,'$.layer_a_spot_strategy.a5_spot_adjudicator.spot_action'), json_extract(full_state_json,'$.layer_a_spot_strategy.validator.passed'), json_extract(full_state_json,'$.layer_a_spot_strategy.validator.violations'), json_extract(full_state_json,'$.layer_a_spot_strategy.validator.warnings') FROM strategy_runs ORDER BY reference_timestamp_utc DESC, generated_at_utc DESC LIMIT 1;"
```

结果摘要：

```text
9780c94deffa48c893aa8d9fcfa864df | 2026-05-12T06:03:01Z | enabled=1 | bear_transition | dca_buy | validator_passed=1 | [] | []
```

## 8. API 验证

已执行：

```bash
curl --noproxy '*' http://127.0.0.1:8000/api/strategy/current
```

验证摘要：

```text
run_id=9780c94deffa48c893aa8d9fcfa864df
has_layer_a=True
enabled=True
a1_cycle_stage=bear_transition
a5_spot_action=dca_buy
validator_passed=True
validator_violations=[]
validator_warnings=[]
```

结论：API 最新状态会返回真实 Layer A，不再是旧 run 的 fallback。

## 9. 网页显示验证

已通过本地服务拉取首页和 JS：

```bash
curl --noproxy '*' http://127.0.0.1:8000/
curl --noproxy '*' 'http://127.0.0.1:8000/assets/app.js?v=layer-a-web-display-20260512'
```

确认：

- 首页 HTML 含 `id="region-layer-a-spot"`。
- 首页 HTML 含“大周期策略”。
- 首页 HTML 引用新版 `app.js?v=layer-a-web-display-20260512`。
- app.js 含 `spotStrategy()`。
- app.js 含 `layer_a_spot_strategy`。
- app.js 含 `spotLayerCards()`。
- 模块顺序为：
  - `region-1` AI 策略建议
  - `region-layer-a-spot` 大周期策略
  - `region-layer-cards` 五层分析

因为 API 已返回真实 `layer_a_spot_strategy`，网页端应显示真实 A1-A5 内容，而不是 fallback。

如需人工确认，打开：

```text
http://127.0.0.1:8000/
```

应该看到：

- “大周期策略”模块；
- 大周期阶段：转熊阶段；
- 策略：分批买入；
- A1-A5 卡片；
- Layer B “五层分析”仍在后面。

## 10. 如果网页仍不显示，排查结论

本轮已排除：

- HTML 未插入模块：已排除。
- app.js 没有读取字段：已排除。
- API 丢字段：已排除。
- 最新 run 还是旧数据：已排除，最新 run 已有 Layer A。
- app.js 缓存：已有 `?v=layer-a-web-display-20260512`。
- Layer B 五层分析被移除：已排除。

如果用户浏览器仍不显示，最可能是：

- 浏览器还缓存旧 HTML，需要 Cmd+Shift+R 强刷；
- 用户打开的不是本地 `127.0.0.1:8000`；
- 服务器端如果是生产环境，还没有 pull 最新代码和重启。

## 11. 本轮是否改代码

有改代码，但只改 Layer A validator/normalizer 误判和测试：

- `src/ai/spot_validator.py`
- `src/ai/spot_strategy_normalizer.py`
- `tests/test_layer_a_spot_validator.py`
- `tests/test_layer_a_spot_normalize.py`

改动原因：

- 真实 Layer A 输出里出现“负资金费率说明做多需支付做空”。
- 这是资金费率机制说明，不是“建议做空”。
- 原 validator 仍误判成违规，所以本轮收紧中文做空文本判断：
  - 继续拦截“建议做空 / 开空 / hedge short / trend_short”；
  - 不拦截“做多需支付做空”这种解释性文本。

## 12. 测试命令和结果

已运行：

```bash
uv run pytest -q tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py
```

结果：

```text
115 passed
```

已运行：

```bash
uv run pytest -q tests/test_layer_a_spot_validator.py tests/test_layer_a_spot_normalize.py tests/test_layer_a_orchestrator_integration.py
```

结果：

```text
18 passed
```

待最终提交前继续运行：

```bash
git diff --check
```

## 13. 是否影响 Layer B

不影响。

本轮没有修改：

- Layer B L1-L5
- Master
- Validator
- thesis
- C 级机会行为
- 仓位、止损、止盈、开仓、平仓、反手规则

## 14. 是否影响虚拟账户

不影响。

Layer A 仍不进入虚拟账户。虚拟账户仍只管理 Layer B。

## 15. 是否影响真实交易

不影响。

本轮没有新增真实交易接口，没有执行真实交易，没有修改 API key、token、secret。

## 16. 风险和未完成

- 本地数据 freshness 过期，所以 pipeline run 返回 degraded，但已经成功持久化最新 run。
- Layer A 的内容基于当前可用数据生成，数据过期会降低策略含义的可靠度。
- 本轮没有清空数据库、没有手动改数据库。
- `uv.lock` 仍是本轮前遗留的本地未提交修改，本轮未处理。

## 17. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push | 待提交后更新 |
| 服务器 git pull | N/A，本轮是本地验证 |
| 服务器 systemctl restart | N/A，本轮是本地验证 |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | N/A，本轮检查的是本地 `/api/system/health` |

