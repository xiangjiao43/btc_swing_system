# group_layer_b_swing_strategy_modules_and_health_layout

## 1. 任务目标

本轮只做网页结构、展示顺序和文案布局优化：

- 将 Layer B 波段相关展示组合成统一大模块「波段策略」。
- 将「系统自检」内部改为三列：Layer A 五层、Layer B 五层、数据源。
- 保持大周期策略、原始数据因子、周复盘、交易逻辑、虚拟账户逻辑不变。

## 2. 改动文件

| 文件 | 改动 |
|---|---|
| `web/index.html` | 新增系统自检 Layer A 列；新增「波段策略」大容器；将当前 thesis、AI 策略建议、虚拟账户、挂单 + 持仓、五层分析、thesis 时间线收纳到波段策略容器内；更新 app.js cache-busting 版本。 |
| `web/assets/app.js` | 新增 `layerAHealthItems()` 和 `swingStrategyUpdatedAt()` 展示 helper。 |
| `tests/test_web_modules_1_2_3.py` | 更新网页结构测试，锁定系统自检三列顺序和波段策略内部顺序。 |

## 3. 系统自检三列布局说明

系统自检现在按固定顺序展示：

1. Layer A 五层
   - A1 大周期阶段
   - A2 链上与宏观
   - A3 现货策略机会
   - A4 现货风险
   - A5 大周期主裁
2. Layer B 五层
   - 保留原 `systemHealth.evidence_layers` 渲染，不改 L1-L5 名称和状态逻辑。
3. 数据源
   - 保留原 `dataSourcesFreshness` 渲染，不改数据源状态逻辑。

## 4. Layer A A1-A5 状态来源

Layer A 自检状态只读 `layer_a_spot_strategy`：

- 对应 A 层输出存在且 `validator` 未失败：显示 `healthy`。
- 对应 A 层输出缺失：显示 `missing`。
- Layer A validator failed 或存在 violations：显示 `degraded`。

本轮没有重新调用 AI，也没有修改 Layer A 判断逻辑。

## 5. 波段策略模块组合方式

新增「波段策略」大模块，副标题为 `Layer B · 波段仓`，说明为：

> 判断 BTC 中长线波段;可做多、可做空;创建 thesis、管理虚拟账户和挂单持仓

模块时间使用当前 Layer B 主状态时间：

- 优先 `state.meta.generated_at_bjt`
- 其次 `state.meta.generated_at_utc`
- 最后 `state.summary_card.decision_time`

## 6. 波段策略模块顺序

波段策略内部顺序固定为：

1. 当前 thesis
2. AI 策略建议
3. 虚拟账户
4. 挂单 + 持仓
5. 五层分析 L1-L5 + 主裁

`thesis 历史时间线` 也保留在波段策略容器内，放在五层分析之后，避免删除既有 Layer B 审计内容。

## 7. UI 是否复用大周期策略风格

已复用现有 `audit-card`、标题层级、副标题、更新时间文本、间距和字体风格。

本轮没有新增前端库，没有改颜色系统，没有改原始数据因子、周复盘或大周期策略布局。

## 8. 是否改 Layer B 逻辑

否。

本轮只移动和包装网页展示模块，没有修改：

- Layer B L1-L5
- Master
- Validator
- thesis persistence
- 虚拟账户
- 挂单 / 持仓
- A/B/C 机会行为

## 9. 是否改 Layer A 逻辑

否。

本轮只新增 Layer A 在系统自检里的展示状态，不修改 A1-A5 prompt、normalizer、validator 或运行入口。

## 10. 是否影响虚拟账户

否。虚拟账户内容仍使用原有 `region-virtual-account`，只是被收纳到「波段策略」容器里。

## 11. 是否影响真实交易

否。本项目仍是策略建议和虚拟账户系统，本轮没有接入或修改任何真实交易。

## 12. 测试命令和结果

已运行：

```bash
uv run pytest -q tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py
git diff --check
```

结果：

- 网页相关测试：`125 passed`
- `git diff --check`：通过，无空白错误

## 13. 删除清单 / 废弃清单

| 对象 | 路径 / 位置 | 处理 | 原因 |
|---|---|---|---|
| 旧「核心建议与高阶信号」分栏 wrapper | `web/index.html` | 废弃并移除 wrapper | 新结构使用「大周期策略」和「波段策略」两个清晰大模块，不再需要旧 60/40 分栏。 |
| Layer B 多个一级分散入口的展示关系 | `web/index.html` | 废弃旧布局关系 | 当前 thesis、AI 策略建议、虚拟账户、挂单 + 持仓、五层分析统一归入「波段策略」。 |

说明：本轮没有删除任何业务模块内容，只改变网页组合关系。

## 14. 风险和未完成

- 本轮没有启动浏览器做人工截图验证，只做了静态网页测试。
- `uv.lock` 在本轮开始前已存在未提交改动，本轮未触碰、未提交。
- 波段策略容器内仍保留原来的子卡片样式；这是为了不大改 UI 和不丢内容。

## 15. 用户后续命令

```bash
ssh ubuntu@124.222.89.86
cd /home/ubuntu/btc_swing_system
git pull --ff-only
sudo systemctl restart btc-strategy.service
```

本轮不需要跑 pipeline。刷新网页：

```text
http://124.222.89.86/
```

## 16. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push | ✅（commit hash 见最终对话） |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | 待用户执行 |
