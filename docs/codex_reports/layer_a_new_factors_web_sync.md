# layer_a_new_factors_web_sync

## 1. 任务目标

把 Layer A 新增因子同步到现有网页「原始数据因子」模块中显示。

本轮只改网页渲染层和报告：

- 不新增独立模块。
- 不改 Layer A / Layer B AI 判断逻辑。
- 不改虚拟账户。
- 不改真实交易。
- 保持现有「原始数据因子」模块的卡片、字体、badge、折叠/分组方式。

## 2. 改动文件

| 文件 | 说明 |
|---|---|
| `web/assets/app.js` | 新增 Layer A 因子转 factor card 的 helper，并合并进原 `factorGroups()` |
| `web/index.html` | 原始数据因子总数改为读取 `rawFactorCards().length` |
| `tests/test_web_modules_4_5_rp_failure.py` | 增加静态测试，确保新因子进原始因子模块且没有新模块 |
| `docs/codex_reports/layer_a_new_factors_web_sync.md` | 本轮报告 |

## 3. 新因子网页显示清单

本轮 10 个因子都进入「原始数据因子」模块：

| 因子 | 分组 | 数据来源 | 显示状态 |
|---|---|---|---|
| `lth_sopr` | 链上数据 | Glassnode | 若 Layer A context 有值显示数值；否则显示 unavailable / 404 等状态 |
| `sth_sopr` | 链上数据 | Glassnode | 同上 |
| `percent_supply_in_profit` | 链上数据 | Glassnode | 可用时显示数值 |
| `percent_supply_in_loss` | 链上数据 | Glassnode | 当前多为 unavailable / proxy_endpoint_404 |
| `exchange_balance` | 链上数据 | Glassnode | 可用时显示数值 |
| `exchange_net_position_change` | 链上数据 | Glassnode | 当前多为 unavailable / uncertain_rate_limited |
| `us2y` | 宏观 | FRED | 可用时显示数值 |
| `fed_funds_rate` | 宏观 | FRED | 可用时显示数值 |
| `m2` | 宏观 | FRED | 可用时显示数值 |
| `fed_balance_sheet` | 宏观 | FRED | 可用时显示数值 |

实现方式：

- 从 `layer_a_spot_strategy.input_context_snapshot.available_factors` 读取可用值。
- 从 `layer_a_spot_strategy.unavailable_factors` 或 `input_context_snapshot.unavailable_factors` 读取不可用状态。
- 转成现有 `factor_cards` 同形状对象，再交给原来的 `factorGroups()`。

## 4. 是否保持原 UI 风格

是。

本轮没有新增独立模块，没有新增 CSS，没有改颜色、字体、字号、间距、badge 样式。

新因子复用原来的：

- `region-4`
- `audit-card`
- 3 列卡片网格
- `formatFactorValue()`
- `directionClass()`
- `freshnessColor()`
- `fetchedAtPrimary()`

## 5. factor_coverage 与网页显示是否一致

一致。

网页不重新计算 coverage，只展示 Layer A context 里的因子状态：

- `status = available` 且有 `actual_value`：显示数值，绿点按原 data_fresh 逻辑展示。
- `status = missing/stale`：显示 `-`，解释文案显示 `Layer A context: missing/stale`。
- `unavailable_factors` 中的 `not_found / proxy_endpoint_404 / uncertain_rate_limited`：显示 `-`，解释文案显示对应状态。

这保证网页和 `factor_coverage` 的口径一致，不把未验证因子伪装成可用。

## 6. 是否影响 Layer B / 虚拟账户 / 真实交易

不影响。

本轮没有修改：

- Layer B L1-L5
- Layer B Master
- Layer B Validator
- thesis / C 级机会逻辑
- 仓位、止损、止盈、开仓、平仓、反手规则
- 虚拟账户
- 真实交易接口

## 7. 测试命令和结果

```bash
uv run pytest -q tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py
```

结果：`117 passed`

```bash
git diff --check
```

结果：通过。

## 8. pipeline run 结果

本地执行：

```bash
uv run python scripts/run_pipeline_once.py --trigger manual
```

结果：命令超过约 4 分钟无输出，表现为外部 AI / 网络请求长时间等待；为避免网页展示小改被外部服务卡住，本轮手动停止该本地 pipeline。

说明：

- 本轮没有改 AI 判断逻辑，pipeline 超时不来自本轮网页代码。
- 线上已有最新 run `c41d13eb2f0143f3b21b2dafcfc23191`，其中 Layer A context 已包含新增因子状态。
- 部署后会继续验证服务和网页文件。

## 9. 最新 run_id

沿用上一轮生产最新 run：

`c41d13eb2f0143f3b21b2dafcfc23191`

该 run 中：

- `layer_a_spot_strategy` 存在
- `A1 cycle_stage = mid_bull`
- `A5 spot_action = hold`
- `critical_unavailable_count = 10`
- `confidence_cap = medium`

## 10. 线上网页验证

已部署到服务器：

- GitHub commit：`b24c875 Sync Layer A factors into raw data web module`
- 服务器目录：`/home/ubuntu/btc_swing_system`
- 服务器已 `git pull --ff-only`
- 已执行 `sudo systemctl restart btc-strategy.service`
- 服务状态：`active`

线上验证结果：

- 服务器本机 API `http://127.0.0.1:8000/api/strategy/current` 返回最新 run `c41d13eb2f0143f3b21b2dafcfc23191`。
- API 中 `layer_a_spot_strategy` 存在。
- `input_context_snapshot.available_factors` 中存在：
  - `onchain_holder_behavior`
  - `macro_liquidity`
- `unavailable_factors` 中正确显示：
  - `lth_sopr = proxy_endpoint_404`
  - `sth_sopr = proxy_endpoint_404`
  - `percent_supply_in_loss = proxy_endpoint_404`
  - `exchange_net_position_change = uncertain_rate_limited`
- 服务器网页文件已包含：
  - `rawFactorCards()`
  - `layerAFactorCards()`
  - `lth_sopr`
  - `fed_balance_sheet`

公网 `http://124.222.89.86/` 返回 `401 Basic Auth`，说明有登录保护。我没有读取或输出网页登录凭据。用户用已有登录状态刷新即可看到新因子。

## 11. 风险和未完成

- 公网 `http://124.222.89.86/` 有 Basic Auth 保护；Codex 不读取或输出网页登录凭据。
- 因子显示依赖最新 run 里是否有 `layer_a_spot_strategy.input_context_snapshot`。旧 run 没有该字段时，新卡会显示 unavailable，不会报错。
- `lth_sopr`、`sth_sopr`、`percent_supply_in_loss`、`exchange_net_position_change` 目前仍按不可用/未确认状态显示，这是正确口径。
- `uv.lock` 是本轮开始前已有本地遗留修改，本轮不提交。

## 12. 审查包路径

`/private/tmp/layer_a_new_factors_web_sync_audit_bundle.zip`

## 13. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push | ✅ `b24c875` |
| 服务器 git pull | ✅ 到 `b24c875` |
| 服务器 systemctl restart | ✅ `btc-strategy.service` active |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | ✅ 本机接口 `status=ok` |
