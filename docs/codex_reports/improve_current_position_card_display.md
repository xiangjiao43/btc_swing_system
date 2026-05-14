# 优化当前持仓卡片展示

## 1. 任务目标

优化网页「波段策略 → 账户与执行 → 当前持仓」小模块：

- 无持仓时不再只显示一句“当前无持仓 / 等待入场信号”；
- 无论有无持仓，都按固定字段结构展示；
- 有持仓时尽量显示真实数据；
- 无持仓或缺数据时显示 `none` 或 `-`；
- 不修改任何交易逻辑、持仓计算逻辑或虚拟账户逻辑。

## 2. 读取文件

- `AGENTS.md`
- `web/index.html`
- `web/assets/app.js`
- `src/web_helpers/normalize_state.py`
- `tests/test_web_modules_1_2_3.py`
- `tests/test_web_modules_4_5_rp_failure.py`
- `tests/web_helpers/test_normalize_state.py`
- `docs/codex_reports/restructure_layer_b_swing_strategy_dashboard.md`
- `docs/codex_reports/layer_a_ui_and_layer_b_c_grade_final_cleanup.md`

## 3. 改动文件

- `web/index.html`
- `web/assets/app.js`
- `tests/test_web_modules_1_2_3.py`
- `docs/codex_reports/improve_current_position_card_display.md`

## 4. 当前持仓字段清单

当前持仓卡片固定展示 9 个字段：

1. 方向
2. 仓位
3. 入场均价
4. 当前价格
5. 浮盈
6. 止损
7. 目标
8. 持仓时长
9. 状态

## 5. 无持仓 fallback 规则

无持仓或未触发入场时：

- 方向：`none`
- 仓位：`none`
- 入场均价：`-`
- 当前价格：优先复用页面已有 BTC 当前价格，取不到显示 `-`
- 浮盈：`-`
- 止损：`-`
- 目标：`-`
- 持仓时长：`-`
- 状态：`等待入场信号`

## 6. long / short 持仓展示规则

有持仓时：

- 方向显示 `long` / `short`
- `long` 使用绿色文字，`short` 使用红色文字
- 仓位优先显示 BTC 数量；如果有仓位百分比字段，则追加百分比
- 入场均价来自 `positionSummary.avg_entry_price`
- 当前价格复用页面已有 `livePrice()`
- 浮盈使用已有持仓数量、入场均价、当前价格做前端展示计算
- 止损与目标继续复用现有 trade plan 展示 helper
- 持仓时长优先读 `positionSummary` 的入场时间字段，缺失时用 active thesis 创建时间兜底

这些都只是网页展示，不改变持仓、订单或账户计算。

## 7. 测试命令和结果

```bash
uv run pytest -q tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py
```

结果：`134 passed`

后续还会执行：

```bash
git diff --check
```

结果：通过，无 whitespace / patch 格式问题。

## 8. 是否改交易逻辑

否。

## 9. 是否改虚拟账户逻辑

否。

虚拟账户卡片及其数据计算不受影响。

## 10. 是否影响 Layer A

否。

## 11. 是否影响真实交易

否。

本项目仍然不是自动实盘下单系统，本轮也没有触碰真实交易接口。

## 12. 删除清单 / 废弃清单

本轮无代码删除项。

展示层废弃：

- 当前持仓卡片中只显示“当前无持仓 / 等待入场信号”的单行空状态。

它被固定 9 字段持仓快照展示替代。

## 13. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push(commit hash) | 待提交后记录 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | 待用户执行 |

## 14. 风险和未完成

- 本轮没有跑 pipeline，因为只是前端展示调整。
- 如果后端当前没有提供部分持仓字段，前端会显示 `-`，不会伪造数据。
- 持仓浮盈是前端展示计算，用于审计台显示，不改变虚拟账户账本。

## 15. 用户后续命令

```bash
ssh ubuntu@124.222.89.86
cd /home/ubuntu/btc_swing_system
git pull --ff-only
sudo systemctl restart btc-strategy.service
```

然后刷新：

```text
http://124.222.89.86/
```
