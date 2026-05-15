# Layer A P0 原始数据因子网页同步

## 1. 任务目标

本轮补齐上一轮审计提出的 A1 P0 数据展示要求：把 `monthly_ohlc_structure`、`major_support_resistance_zones`、`hodl_waves_1y_plus_aggregate` 接入 Layer A context，并同步显示到网页现有「原始数据因子」模块。

本轮只做 Layer A 数据处理与网页展示同步；不改 Layer B，不改交易逻辑，不跑完整 pipeline。

## 2. 改动文件

- `src/ai/spot_cycle_context_builder.py`
- `src/evidence/plain_reading.py`
- `web/assets/app.js`
- `tests/test_layer_a_spot_context_builder.py`
- `tests/test_plain_reading.py`
- `tests/test_web_modules_4_5_rp_failure.py`
- `docs/codex_reports/layer_a_p0_raw_factor_web_sync.md`

## 3. 三个 P0 因子显示情况

| 因子 | 中文名 | 是否进入 Layer A context | 是否进入 A1 lightweight context | 是否显示在原始数据因子模块 |
|---|---|---:|---:|---:|
| `monthly_ohlc_structure` | 月线结构 | 是 | 是 | 是 |
| `major_support_resistance_zones` | 长期支撑 / 阻力区 | 是 | 是 | 是 |
| `hodl_waves_1y_plus_aggregate` | HODL Waves 1Y+ 长期持有占比 | 是 | 是 | 是 |

## 4. 网页显示字段

### 月线结构

- 标题：月线结构
- 右上角值：`monthly_trend`，显示为 `recovering / up / sideways / down`，网页人读说明翻译为修复中 / 上行 / 震荡 / 下行
- 状态：使用现有原始因子卡片 `状态:可用 / 当前缺值 / 不可用`
- 抓取时间：使用生成月线结构所依赖的 1D K 线 `inserted_at_utc`

### 长期支撑 / 阻力区

- 标题：长期支撑 / 阻力区
- 右上角值：`支撑 x / 阻力 y`
- 状态：使用现有原始因子卡片状态行
- 抓取时间：优先使用 1W K 线抓取时间，缺失时回退 1D K 线抓取时间

### HODL Waves 1Y+

- 标题：HODL Waves 1Y+
- 右上角值：`hodl_waves_1y_2y` 到 `hodl_waves_more_10y` 的聚合百分比
- 状态：使用现有原始因子卡片状态行
- 抓取时间：使用相关 HODL Waves bucket 的最新写入时间

## 5. plain_reading 模板说明

本轮新增了 deterministic plain_reading 模板：

- 月线结构：解释高周期价格处于修复、上行、震荡或下行，并说明连续月线收盘站稳关键阻力会提高趋势确认度。
- 长期支撑 / 阻力区：解释当前价格位于主要支撑和阻力之间，用于辅助判断牛熊过渡或趋势确认，不单独决定买卖。
- HODL Waves 1Y+：解释长期持有筹码占比，上升偏吸筹，下降需警惕派发。

这些说明全部由代码模板生成，不调用 AI。

## 6. 不可用 fallback 规则

如果某项暂时不可用：

- 右上角值显示 `-`
- 状态显示 `当前缺值 / 不可用 / 未接入` 等现有状态
- plain_reading 显示因子用途和当前状态
- 不显示 raw JSON、完整数组、endpoint、exception 或调试字段
- 不影响其它因子卡片显示
- 不影响 Layer A 运行

## 7. 数据来源与实现方式

- 月线结构：从现有 1D K 线规则化 resample 成月线 OHLC，不新增外部接口。
- 长期支撑 / 阻力区：从现有 1W / 1D K 线规则化提取高周期 swing 支撑阻力，不新增外部接口。
- HODL Waves 1Y+：复用现有 Glassnode HODL Waves bucket 数据，聚合 `1y_2y`、`2y_3y`、`3y_5y`、`5y_7y`、`7y_10y`、`more_10y`。

## 8. 是否调用 AI

没有。原始数据因子说明仍使用 `src/evidence/plain_reading.py` 和 `web/assets/app.js` 的 deterministic 模板。

AI 仍只用于 Layer A A1-A5 策略综合判断，不用于每个原始因子的说明。

## 9. 测试命令和结果

已运行：

```bash
uv run pytest -q tests/test_layer_a_spot_context_builder.py tests/test_plain_reading.py
uv run pytest -q tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py
uv run pytest -q tests/test_layer_a_spot_context_builder.py tests/test_layer_a_spot_normalize.py tests/test_layer_a_spot_validator.py tests/test_layer_a_orchestrator_integration.py
git diff --check
```

结果：

- `42 passed`
- `140 passed`
- `37 passed`
- `git diff --check` 通过

## 10. 删除清单 / 废弃清单

| 删除 / 废弃对象 | 位置 | 原因 | 替代 |
|---|---|---|---|
| `monthly_structure_1m` 未接入候选 | `src/ai/spot_cycle_context_builder.py` | 本轮已用现有 1D K 线派生 `monthly_ohlc_structure`，不应继续显示为未接入候选 | `monthly_ohlc_structure` |
| `major_support_resistance` 未预计算候选 | `src/ai/spot_cycle_context_builder.py` | 本轮已用现有 1W/1D K 线规则化派生 `major_support_resistance_zones` | `major_support_resistance_zones` |

## 11. 是否影响 Layer B / 虚拟账户 / 真实交易

- 是否影响 Layer B：否
- 是否影响虚拟账户：否
- 是否影响真实交易：否
- 是否改 Layer A A1-A5 AI 策略逻辑：否，只补 A1 context 输入摘要和网页 raw factor 展示

## 12. 风险和未完成

- 月线结构和支撑阻力是规则化派生摘要，不是外部新增数据源；它们适合 A1 辅助判断，不应被理解为自动买卖信号。
- HODL Waves 1Y+ 依赖 Glassnode bucket 是否成功采集；如果 bucket 缺失，会如实显示缺值，不伪造。
- 本轮未跑完整 Layer A pipeline，生产端需要用户部署后再跑 Layer A 才会在最新 run 中刷新这些字段。

## 13. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | 是 |
| GitHub push | 待提交后完成 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行 |
| 生产健康检查 `/api/system/health` | 待用户执行 |

## 14. 用户后续命令

```bash
ssh ubuntu@124.222.89.86
cd /home/ubuntu/btc_swing_system
git pull --ff-only
sudo systemctl restart btc-strategy.service
```

如需刷新 Layer A 最新结果：

```bash
.venv/bin/python scripts/run_layer_a_once.py --trigger manual
```

然后刷新：

```text
http://124.222.89.86/
```
