# simplify_layer_b_container_borders_only

## 1. 任务目标

只优化“波段策略”大模块的视觉边框和排版层级：保留外层大容器边框，减少内部小模块强边框，让模块更像一个连续的信息区。  
本轮只改边框、间距、容器 class，不改内容、不改字段、不改 AI 输出、不改交易逻辑、不跑 pipeline。

## 2. 改动文件

- `web/index.html`
- `tests/test_web_modules_1_2_3.py`
- `docs/codex_reports/simplify_layer_b_container_borders_only.md`

说明：工作区里仍有本轮无关的 `uv.lock` 修改，本轮没有 stage，也不会提交它。

## 3. 哪些内部边框被弱化或移除

已保留：

- `region-layer-b-swing` 外层 `audit-card` 大模块边框

已弱化 / 移除内部强边框：

- 顶部摘要行
- 虚拟账户
- 当前持仓
- 挂单 / thesis
- THESIS 历史时间线
- 交易员结论
- 五层分析 L1-L5 + 主裁小卡

处理方式：

- 内部模块不再使用明显的 `border border-slate-200` 卡片边框
- 不新增背景色块
- 使用留白、标题、轻分隔线组织内容

## 4. 哪些内容保持不变

以下业务内容保留：

- 波段策略标题区、说明、更新时间
- 顶部摘要行：当前状态、方向、机会等级、主裁动作、置信度
- 虚拟账户：权益、现金、PnL、回撤、初始资金、资金曲线
- 当前持仓：方向、BTC 数量、入场价、浮盈亏
- 挂单 / thesis：失效条件、待触发挂单表
- THESIS 历史时间线
- 交易员结论
- 五层分析 L1-L5 + 主裁卡片和“查看详细”

继续保持不显示：

- 等待入场区
- thesis_id
- 阶段 / planned / active
- 距当前

## 5. 是否加了底色

没有。  
本轮明确移除了上一版内部浅色底，波段策略内部保持白底，只用留白和轻分隔线。

## 6. 是否改 Layer B 逻辑

否。  
没有修改 Layer B L1-L5、Master、Validator、thesis persistence、虚拟账户、A/B/C 机会行为或任何交易规则。

## 7. 是否改 Layer A 逻辑

否。

## 8. 是否影响虚拟账户逻辑

否。  
虚拟账户计算、持仓、PnL、回撤逻辑均未修改。

## 9. 是否影响真实交易

否。  
没有接触真实交易接口，没有运行 pipeline。

## 10. 测试命令和结果

已运行：

```bash
uv run pytest -q tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py
git diff --check
```

结果：

- `132 passed in 0.07s`
- `git diff --check` 通过

## 11. 删除清单 / 废弃清单

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| 波段策略内部强边框 class | `web/index.html` 内部区块 | 用户要求只保留外层大容器边框，内部用留白/轻分隔线 |
| 波段策略内部浅色底 class | `web/index.html` 内部区块 | 用户明确要求不加底色、不新增背景色块 |

## 12. 风险和未完成

- 本轮没有浏览器截图验证，只运行了静态网页测试。
- 服务器尚未部署，需要用户执行 git pull 和重启服务。
- 本轮没有跑 pipeline，符合用户要求。

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

