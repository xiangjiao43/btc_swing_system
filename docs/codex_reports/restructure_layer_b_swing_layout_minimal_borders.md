# restructure_layer_b_swing_layout_minimal_borders

## 1. 任务目标

按用户手绘示意继续重排“波段策略”模块，只调整 UI 布局、边框和间距：

- 保留外层“波段策略”大模块边框
- 内部小模块去掉强边框
- 不新增底色
- 顶部摘要改为“当前状态 + 方向”横向信息条
- 三列显示虚拟账户、当前持仓、挂单 / thesis
- 历史时间线、交易员结论、五层分析保留

本轮不改数据、不改字段来源、不改 AI 输出、不改交易逻辑、不跑 pipeline。

## 2. 改动文件

- `web/index.html`
- `tests/test_web_modules_1_2_3.py`
- `docs/codex_reports/restructure_layer_b_swing_layout_minimal_borders.md`

说明：工作区里仍有本轮无关的 `uv.lock` 修改，本轮没有 stage，也不会提交它。

## 3. 布局调整

波段策略内部现在按以下顺序展示：

1. 标题区
2. 当前状态 + 方向横向信息条
3. 虚拟账户
4. 当前持仓
5. 挂单 / thesis
6. THESIS 历史时间线
7. 交易员结论
8. 五层分析 L1-L5 + 主裁

顶部摘要行已从 5 个小块收敛为：

- 当前状态
- 方向

机会等级、主裁动作等仍通过交易员结论和下方分析承载，不在顶部重复堆字段。

## 4. 边框和视觉调整

已保留：

- `region-layer-b-swing` 外层 `audit-card` 边框

已移除 / 弱化：

- 顶部摘要行内部小框边框
- 虚拟账户小卡边框
- 当前持仓小卡边框
- 挂单 / thesis 小卡边框
- THESIS 历史时间线小卡边框
- 交易员结论小框边框
- 五层分析小卡边框

没有新增底色或背景色块。

## 5. 内容保持不变

保留原有数据展示：

- 虚拟账户：权益、现金、PnL、回撤、初始资金、资金曲线
- 当前持仓：有持仓显示明细，无持仓显示“当前无持仓 / 等待入场信号”
- 挂单 / thesis：失效条件、待触发挂单表
- 待触发挂单表：类型 / 价格 / 仓位
- THESIS 历史时间线
- 交易员结论
- 五层分析 L1-L5 + 主裁

继续不显示：

- 等待入场区
- thesis_id
- 阶段 / planned / active
- 距离当前

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

- `133 passed in 0.08s`
- `git diff --check` 通过

## 11. 删除清单 / 废弃清单

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| 顶部摘要行中的机会等级 / 主裁动作 / 置信度小块 | `web/index.html` 的 `region-swing-summary` | 用户要求当前状态 + 方向合并为一条横向条，减少重复字段 |
| 波段策略内部强边框 class | `web/index.html` 内部区块 | 用户要求内部用留白、标题、轻分隔线组织 |
| 波段策略内部浅色底 class | `web/index.html` 内部区块 | 用户明确要求不要加底色 |

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

