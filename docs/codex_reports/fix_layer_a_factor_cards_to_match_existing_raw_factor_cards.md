# fix_layer_a_factor_cards_to_match_existing_raw_factor_cards

## 1. 任务目标

返工修复 Layer A 新增因子在「原始数据因子」模块中的卡片展示，让它们和老因子一致：

- 标题
- 右上角数值
- 一句话解释
- 单一状态行
- 抓取时间

本轮不改 Layer A AI 判断，不改 Layer B，不改 thesis、C 级机会、虚拟账户和真实交易。

## 2. 改动文件

- `web/assets/app.js`
- `tests/test_web_modules_4_5_rp_failure.py`
- `docs/codex_reports/fix_layer_a_factor_cards_to_match_existing_raw_factor_cards.md`

## 3. 修复前问题

截图暴露的问题是：新增 Layer A 因子虽然进入了「原始数据因子」模块，但不像老卡片：

- 主解释行显示 `Layer A context` 这类内部来源文案。
- 有些卡片出现两行状态。
- 可用因子没有解释数值含义。
- 不可用因子容易暴露 `proxy_endpoint_404` / `uncertain_rate_limited` 这类内部状态。

## 4. 修复后显示规则

Layer A 新因子现在生成与老因子一致的 `plain_interpretation`：

- 可用因子：显示 `📊 当前... 🔍 ...` 的一句话解释。
- 不可用因子：显示该因子的用途，并用中文说明当前未接入 / 数据受限。
- 状态行只保留一行：`状态:可用 · Layer A`、`状态:未接入 · Layer A`、`状态:数据受限 · Layer A`。
- 抓取时间只显示真实 `fetched_at_bjt` 或可用的 captured/as_of 时间；不可用且没有真实时间时不造假时间。

## 5. 每个新增因子的一句话说明来源

说明由 `web/assets/app.js` 中的 `layerAFactorPlainReading()` 规则化生成，不调用 AI，不显示原始 JSON。

| 因子 | 说明口径 |
|---|---|
| LTH SOPR | 长期持有人是否在获利卖出，`>1` 获利卖出，`<1` 亏损卖出 |
| STH SOPR | 短期持有人是否接近盈亏平衡，`<1` 代表短期筹码承压 |
| 盈利供给比例 | 市场筹码盈利面是否过热或偏底部 |
| 亏损供给比例 | 市场是否仍有恐慌或承压筹码 |
| 交易所余额 | 可交易供给压力，余额上升偏卖压，下降偏长期持有 |
| 交易所净头寸变化 | 资金流入/流出交易所，流入偏卖压，流出偏囤币 |
| 美国 2 年期收益率 | 短端利率压力，上升通常压制风险资产 |
| 联邦基金利率 | 政策利率环境，高利率通常压制风险资产估值 |
| M2 | 美元流动性规模，扩张偏利好风险资产 |
| 美联储资产负债表 | 基础流动性环境，扩表偏宽松，缩表偏紧缩 |

## 6. unavailable / 数据受限显示规则

内部状态只做映射，不作为主卡片文案：

- `proxy_endpoint_404` → `未接入`
- `uncertain_rate_limited` → `数据受限`
- `not_found` → `未接入`
- `config_only` → `未启用`
- `deprecated_candidate` → `已废弃`
- `stale` → `数据过期`

## 7. 测试命令和结果

已运行：

```bash
uv run pytest -q tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py
```

结果：`118 passed`

```bash
uv run pytest -q tests/test_layer_a_spot_context_builder.py tests/test_layer_a_spot_normalize.py tests/test_layer_a_spot_validator.py tests/test_layer_a_orchestrator_integration.py
```

结果：`24 passed`

```bash
git diff --check
```

结果：通过

## 8. 线上 pipeline run 结果

待部署后补充。

## 9. http://124.222.89.86/ 验证结果

待部署后补充。

## 10. 是否影响范围

- 是否影响 Layer A AI 判断：否。
- 是否影响 Layer B：否。
- 是否影响虚拟账户：否。
- 是否影响真实交易：否。

## 11. 删除清单 / 废弃清单

本轮无替代关系，无删除项。原因：本轮只修复已有 Layer A 原始因子卡片生成方式，没有新增替代模块。

## 12. 风险和未完成

- 线上页面若有认证保护，自动截图可能只能记录保护页；最终仍需用户登录后刷新确认。
- 服务器 pipeline 若再次出现 Master AI 降级，会如实记录，但该降级不影响本轮网页显示修复。

## 13. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push(commit hash) | 待执行 |
| 服务器 git pull | 待执行 |
| 服务器 systemctl restart | 待执行 |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | 待执行 |

## 14. 审查包路径

待生成。
