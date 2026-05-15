# tighten_layer_b_inner_module_width_and_spacing

## 1. 任务目标

本轮只优化网页「波段策略」大模块内部的宽度对齐和上下间距，让红框内的账户执行、THESIS 历史时间线、交易员结论、五层分析区域与上方摘要栏左右边界对齐，并让模块之间更紧凑。

本轮不改任何内容、字段、模块顺序、数据、颜色、字号、交易逻辑，也不运行 pipeline。

## 2. 读取文件

- `AGENTS.md`
- `web/index.html`
- `web/assets/app.js`
- `tests/test_web_modules_1_2_3.py`
- `tests/test_web_modules_4_5_rp_failure.py`
- `tests/web_helpers/test_normalize_state.py`

## 3. 改动文件

- `web/index.html`
- `tests/test_web_modules_1_2_3.py`
- `docs/codex_reports/tighten_layer_b_inner_module_width_and_spacing.md`

## 4. 宽度对齐方式

本轮让以下区域统一使用 `w-full`，并移除额外内层 `p-3` 缩进：

- `region-swing-summary`
- `region-swing-account-execution`
- `region-layer-cards`

这样「账户与执行」三张小卡片、THESIS 历史时间线、交易员结论、五层分析卡片区域会和顶部摘要栏使用同一条左右边界，不再比摘要栏窄一圈。

## 5. 上下间距收紧说明

本轮只收紧布局间距，不压缩内容文字：

- 「波段策略」内部总间距从 `space-y-4` 调整为 `space-y-3`。
- 「账户与执行」内部 wrapper 从 `p-3 space-y-3` 调整为 `space-y-2`，去掉额外左右缩进并减少纵向空隙。
- 「交易员结论 / 五层分析」外层 wrapper 从 `p-3 space-y-3` 调整为 `space-y-2`。
- 五层分析卡片网格从 `gap-3` 调整为 `gap-2`，减少两行卡片之间的空隙。

小卡片自身的 `p-3`、边框、字号、颜色保持不变。

## 6. 哪些内容保持不变

以下内容没有变化：

- 波段策略标题区、更新时间、顶部摘要栏字段。
- 虚拟账户字段和数据显示。
- 当前持仓字段和数据显示。
- 挂单 / thesis 字段和数据显示。
- THESIS 历史时间线内容。
- 交易员结论内容。
- L1/L2/L3/L4/L5/主裁卡片内容、排序和展开逻辑。
- 大周期策略、原始数据因子、周复盘模块。

## 7. 是否改 Layer B 逻辑

否。

没有修改 Layer B L1-L5、Master、Validator、thesis、虚拟账户、挂单、持仓、A/B/C 机会行为。

## 8. 是否改 Layer A 逻辑

否。

没有修改 Layer A A1-A5、大周期策略、Layer A context 或任何现货仓判断逻辑。

## 9. 是否影响真实交易

否。

系统仍然只是前端展示调整；没有新增真实交易接口，没有触发下单，没有修改仓位、止损、止盈、开平仓或反手规则。

## 10. 测试命令和结果

已运行：

```bash
uv run pytest -q tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py
git diff --check
```

结果：

- `136 passed in 0.08s`
- `git diff --check` 通过，无空白错误

## 11. 删除清单 / 废弃清单

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| 额外内层缩进 `p-3` | `web/index.html` 的 `region-swing-account-execution` 内层 wrapper | 造成账户执行区域比摘要栏左右窄一圈 |
| 额外内层缩进 `p-3` | `web/index.html` 的 `region-layer-cards` 内层 wrapper | 造成交易员结论和五层分析区域比摘要栏左右窄一圈 |

无业务代码删除项。

## 12. 风险和未完成

- 风险较低：改动只涉及前端 class 布局，不改数据或策略。
- 页面最终视觉仍需用户刷新生产网页后肉眼确认。
- `uv.lock` 在本轮开始前已有未提交改动，本轮没有触碰，也不会提交。

## 13. 用户后续命令

```bash
ssh ubuntu@124.222.89.86
cd /home/ubuntu/btc_swing_system
git pull --ff-only
sudo systemctl restart btc-strategy.service
```

刷新：

```text
http://124.222.89.86/
```

## 14. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push | 待执行 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | 待用户执行 |
