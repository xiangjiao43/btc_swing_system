# Cleanup Layer A Redundant And Required Factors

## 1. 任务目标

本轮把用户给出的伪代码落到项目真实实现里：

1. 清理 Layer A 中不适合作为“待补关键因子”的冗余/遗留候选项；
2. 确认必需因子仍按“已接入但缺值/过期”进入 `factor_coverage`；
3. 不伪造数据，不把缺失因子硬标成 available；
4. 不改 Layer B、虚拟账户或真实交易。

## 2. 改动文件

| 文件 | 改动 |
|---|---|
| `src/ai/spot_cycle_context_builder.py` | 清空 `_UNAVAILABLE_MODEL_FACTORS`，不再把已废弃/未验证/不适合项列入 Layer A unavailable 候选池。 |
| `tests/test_layer_a_spot_context_builder.py` | 新增断言，锁住这些冗余因子不再出现在 `unavailable_factors`，并确认 `total_unavailable_factors=0`。 |
| `docs/codex_reports/cleanup_layer_a_redundant_and_required_factors.md` | 本报告。 |

## 3. 被移除的冗余候选因子

以下因子不再作为 Layer A 当前待补的 unavailable 候选项：

| 因子 | 原状态 | 本轮处理 | 原因 |
|---|---|---|---|
| `futures_basis_premium` | `deprecated_candidate` | 移除 | 衍生品结构，更适合 Layer B 或已废弃，不适合作为 Layer A 大周期必需因子。 |
| `liquidation_heatmap_levels` | `not_found` | 移除 | 清算热力图偏短线执行/拥挤，不应污染 Layer A 大周期缺口。 |
| `liveliness` | `config_only` | 移除当前 unavailable 候选 | 未稳定采集；未来若重新验证接口，可作为可选链上因子单独接入，而不是长期挂在缺口里。 |
| `market_cap_realized_cap` | `not_found` | 移除 | MVRV / realized price 已覆盖主要含义，不作为独立待补因子。 |
| `options_iv_skew` | `not_found` | 移除 | 期权偏风险/情绪，不应作为 Layer A 阶段主判断缺口。 |
| `stablecoin_supply_liquidity` | `not_found` | 移除当前 unavailable 候选 | 当前无稳定数据源，不再把未验证项显示成当前待补；若后续用户确认，可单独做稳定币数据接入。 |
| `unemployment` | `deprecated_candidate` | 移除 | 宏观低优先级历史项，不作为 Layer A 当前必需因子。 |

## 4. 必需因子完整性检查

用户列出的必需因子与当前项目字段映射如下：

| 用户字段 | 项目字段 | 当前处理 |
|---|---|---|
| `btc_price` | `price_structure.current_close` / `technical_packet.btc_price` | 已接入；缺值时进入 `missing_integrated_factor_count`。 |
| `weekly_structure` | `technical_packet.weekly_structure` | 已进入单层裁决输入。 |
| `monthly_structure` | `monthly_ohlc_structure` | 已进入单层裁决输入和原始数据因子展示。 |
| `ma_200d` | `technical_packet.ma_200d` | 已接入；缺值/过期按真实状态显示。 |
| `ma_200w` | `technical_packet.ma_200w` | 已接入；缺值/过期按真实状态显示。 |
| `support_resistance` | `major_support_resistance_zones` | 已进入单层裁决输入和原始数据因子展示。 |
| `MVRV` | `mvrv` | 已接入。 |
| `NUPL` | `nupl` | 已接入。 |
| `RHODL` | `rhodl_ratio` | 已接入。 |
| `hodl_waves` | `hodl_waves` / `hodl_waves_1y_plus_aggregate` | 已接入。 |
| `etf_flow_7d_sum_usd` | 同名字段 | 已进入流动性/宏观数据包。 |
| `etf_flow_30d_sum_usd` | 同名字段 | 已进入流动性/宏观数据包。 |
| `real_yield` | 同名字段 | 已进入流动性/宏观数据包。 |
| `fed_funds_rate` | 同名字段 | 已进入流动性/宏观数据包。 |
| `confidence_cap` | `factor_coverage.confidence_cap` | 已生成。 |
| `critical_unavailable_count` | `factor_coverage.critical_unavailable_count` | 已生成。 |

本轮没有调用不存在的 `LayerA.fetch_factor()`，也没有把缺失数据直接写成可用。缺失因子仍由真实 collector / pipeline 写入后才能变成 available。

## 5. 数据状态变化

空库诊断结果：

```json
{
  "unavailable_factors": [],
  "factor_coverage": {
    "total_unavailable_factors": 0,
    "critical_unavailable_count": 0,
    "confidence_cap": "low",
    "confidence_cap_reason": "Layer A 已接入因子可用率低于 50%"
  }
}
```

这对交易系统的含义是：

- 冗余/未验证候选项不再让页面和风险包看起来“还有一堆模型预留因子没接”；
- 真正必需但当前没数据的因子，仍会作为 `missing_integrated_factor_count` 进入数据质量；
- 系统不会因为清理 unavailable 候选而伪造 AI 精度。

## 6. 是否补齐缺失因子

本轮没有直接抓取外部数据，也没有写数据库。

原因：

1. 用户给的是伪代码，项目中不存在 `system_layer.LayerA.fetch_factor()`；
2. 直接把缺失因子标成 `available` 会伪造数据；
3. 真正补齐必须走项目已有 collector / pipeline，并由实际数据源返回数值。

本轮完成的是“清理冗余缺口 + 保留真实缺值统计”。如果要真正补齐数值，下一步应专项运行或修复 collector，让这些已接入字段写入真实数据。

## 7. 测试命令和结果

| 命令 | 结果 |
|---|---|
| `uv run pytest -q tests/test_layer_a_spot_context_builder.py tests/test_layer_a_spot_normalize.py tests/test_layer_a_spot_validator.py tests/test_layer_a_orchestrator_integration.py` | 39 passed |
| `uv run pytest -q tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py` | 140 passed |
| 空库只读诊断脚本 | `unavailable_factors=[]`，`total_unavailable_factors=0` |
| `git diff --check` | 通过 |

## 8. 高风险区域确认

| 项目 | 结果 |
|---|---|
| 是否改 Layer A 裁决逻辑 | 否 |
| 是否改 Layer B 逻辑 | 否 |
| 是否改虚拟账户 | 否 |
| 是否改真实交易接口 | 否 |
| 是否真实下单 | 否 |
| 是否泄露 secret | 否 |
| 是否清空数据库 | 否 |

## 9. 删除清单 / 废弃清单

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| `_UNAVAILABLE_MODEL_FACTORS` 中 7 个冗余候选项 | `src/ai/spot_cycle_context_builder.py` | 不再把未验证/已废弃/不适合项计入 Layer A 当前 unavailable 候选池。 |

## 10. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push | 待提交后完成 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | 待用户执行 |

## 11. 风险和未完成

1. 本轮没有补实际数值，只清理了冗余候选项。
2. `missing_integrated_factor_count` 仍会如实显示已接入但当前缺值的必需因子。
3. 如果后续确实要接入 stablecoin liquidity 或 liveliness，需要重新做接口验证，不能直接恢复到 unavailable 候选池。
4. 生产端需要 `git pull` 和重启后才能看到代码变化。

## 12. 用户后续命令

```bash
ssh ubuntu@124.222.89.86
cd /home/ubuntu/btc_swing_system
git pull --ff-only
sudo systemctl restart btc-strategy.service
```

本轮不需要跑完整 pipeline。若要刷新 Layer A 数据，需要另行运行安全 Layer A pipeline。
