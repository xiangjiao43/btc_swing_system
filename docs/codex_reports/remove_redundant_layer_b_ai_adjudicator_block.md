# remove_redundant_layer_b_ai_adjudicator_block

## 1. 任务目标

删除网页“波段策略”模块里重复的独立“AI 主裁结论”大块，以及它下面重复展示的主裁字段区。  
本轮只做前端展示收口，不改 Layer A / Layer B 策略逻辑，不跑 pipeline。

## 2. 读取过的关键文件

- `AGENTS.md`
- `web/index.html`
- `web/assets/app.js`
- `tests/test_web_modules_1_2_3.py`
- `tests/test_web_modules_4_5_rp_failure.py`
- `tests/web_helpers/test_normalize_state.py`

## 3. 改动文件

- `web/index.html`
- `web/assets/app.js`
- `tests/test_web_modules_1_2_3.py`
- `tests/test_web_modules_4_5_rp_failure.py`
- `docs/codex_reports/remove_redundant_layer_b_ai_adjudicator_block.md`

说明：工作区里存在本轮无关的 `uv.lock` 修改，本轮没有 stage，也不会提交它。

## 4. 删除了哪些前端块

已删除 `web/index.html` 中波段策略内部的独立 `region-1`：

- 独立标题：`AI 主裁结论`
- 主裁结论卡片：`结论`、`理由`、`执行计划`、`失效条件`
- 展开详情区域：`swing_master_detail`
- 重复字段：方向、状态、机会等级、信心指数、入场区间、止损价、止盈分批、仓位上限、当前浮盈、距离止损、持仓时长、分级失效位

同时删除 `web/assets/app.js` 中只服务该独立块的 helper：

- `masterLayerCard`
- `swingTraderConclusion`
- `swingTraderReason`
- `swingExecutionPlan`

保留 `swingInvalidationPlan`，因为它仍被“挂单 / thesis”区域使用。

## 5. 保留了哪些模块

已保留：

- 波段策略顶部摘要区
- 账户与执行模块
- 虚拟账户
- 当前持仓
- 挂单 / thesis
- 五层分析 L1-L5 + 主裁
- 五层分析里的“主裁（综合决策）”卡片
- 大周期策略
- 原始数据因子
- 周复盘

额外说明：AI 失败提示仍保留为一条小告警，不再包装成“AI 主裁结论”模块。

## 6. 是否改 Layer B 逻辑

否。  
本轮没有修改 Layer B L1-L5、Master、Validator、thesis、虚拟账户、A/B/C 机会语义或任何交易规则。

## 7. 是否改 Layer A 逻辑

否。  
本轮没有修改 Layer A A1-A5、spot validator、context builder 或大周期策略展示。

## 8. 是否影响虚拟账户

否。  
本轮只删除重复前端展示，不修改虚拟账户计算、入账、持仓、PnL 或回撤逻辑。

## 9. 是否影响真实交易

否。  
本项目当前不是自动真实下单系统。本轮没有接触真实交易接口，也没有运行 pipeline。

## 10. 测试命令和结果

已运行：

```bash
uv run pytest -q tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py
git diff --check
```

结果：

- `130 passed in 0.09s`
- `git diff --check` 通过

## 11. 删除清单 / 废弃清单

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| 独立 `AI 主裁结论` 区块 | `web/index.html` 原 `region-1` | 与波段策略摘要区、账户与执行、五层分析里的主裁卡片重复 |
| `swing_master_detail` 展开详情 | `web/index.html` 原 `region-1` 内 | 重复展示方向、状态、机会等级、仓位、止损等字段 |
| `masterLayerCard` | `web/assets/app.js` | 只服务已删除的独立主裁块 |
| `swingTraderConclusion` | `web/assets/app.js` | 只服务已删除的独立主裁块 |
| `swingTraderReason` | `web/assets/app.js` | 只服务已删除的独立主裁块 |
| `swingExecutionPlan` | `web/assets/app.js` | 只服务已删除的独立主裁块 |

## 12. 风险和未完成

- 本轮没有启动浏览器截图验证，只做了静态网页测试。
- 工作区有本轮无关的 `uv.lock` 修改，已明确排除，不纳入本次提交。
- 服务器尚未部署，本轮只完成本地修改和 GitHub 推送。

## 13. 用户后续命令

```bash
ssh ubuntu@124.222.89.86
cd /home/ubuntu/btc_swing_system
git pull --ff-only
sudo systemctl restart btc-strategy.service
```

本轮不需要跑 pipeline。部署后刷新：

```text
http://124.222.89.86/
```

## 14. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | 通过 |
| GitHub push | 本轮 commit 后执行，最终状态见对话收尾 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | 待用户执行 |
