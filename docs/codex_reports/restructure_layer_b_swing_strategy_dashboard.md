# restructure_layer_b_swing_strategy_dashboard

## 1. 任务目标

本轮按确认后的页面结构，把 Layer B 波段相关内容整理成一个统一的大模块「波段策略」。

本轮只做前端结构和展示优化，不改任何策略逻辑、不跑完整 pipeline、不触碰真实交易。

## 2. 改动文件

| 文件 | 改动 |
|---|---|
| `web/index.html` | 重构「波段策略」内部结构：新增摘要区、账户与执行、AI 主裁结论、五层分析三段式布局；保留系统自检三列。 |
| `web/assets/app.js` | 新增 Layer B 展示 helper：状态、方向、主裁动作、置信度、交易员式结论、执行计划、失效条件等，只读现有 state。 |
| `tests/test_web_modules_1_2_3.py` | 更新 Layer B 仪表盘结构测试。 |
| `tests/test_web_modules_4_5_rp_failure.py` | 更新 thesis 时间线和 AI 失败提示在新结构下的测试。 |

## 3. 系统自检三列布局说明

系统自检保持三列：

1. Layer A 五层
   - A1 大周期阶段
   - A2 链上与宏观
   - A3 现货策略机会
   - A4 现货风险
   - A5 大周期主裁
2. Layer B 五层
   - 继续使用原 `systemHealth.evidence_layers`
   - 不改 L1-L5 名称和状态逻辑
3. 数据源
   - 继续使用原 `dataSourcesFreshness`
   - 不改数据源状态逻辑

## 4. 波段策略大模块结构说明

「波段策略」现在是一个完整 Layer B 仪表盘：

1. 标题区
   - 标题：波段策略
   - 标识：Layer B · 波段仓
   - 副标题：判断 BTC 中长线波段;可做多、可做空;创建 thesis、管理虚拟账户和挂单持仓
   - 更新时间：波段策略更新时间
2. 摘要区
   - 当前状态
   - 方向
   - 机会等级
   - 主裁动作
   - 置信度
3. 账户与执行
   - 虚拟账户
   - 当前持仓
   - 挂单 / thesis
   - 待触发挂单
   - thesis 历史时间线
4. AI 主裁结论
   - 结论
   - 理由
   - 执行计划
   - 失效条件
   - 详细区保留原策略小字段
5. 五层分析 L1-L5 + 主裁
   - 保留原卡片内容
   - 首屏仍是标题、主结论、摘要、查看详细

## 5. 合并了哪些旧模块

| 旧展示 | 新位置 |
|---|---|
| 虚拟账户 | 波段策略 → 账户与执行 → 虚拟账户 |
| 当前 thesis | 波段策略 → 账户与执行 → 挂单 / thesis |
| 挂单 + 持仓 | 波段策略 → 账户与执行 → 当前持仓 / 待触发挂单 |
| AI 策略建议 | 波段策略 → AI 主裁结论 |
| 五层分析 | 波段策略 → 五层分析 |
| thesis 历史时间线 | 波段策略 → 账户与执行 |

## 6. 删除 / 废弃了哪些旧一级标题

| 旧一级标题 | 处理 | 原因 |
|---|---|---|
| 虚拟账户 | 废弃为一级模块，改为「账户与执行」内的小卡 | 避免 Layer B 页面碎片化。 |
| 当前 thesis | 废弃为一级模块，改为「挂单 / thesis」小卡 | 与挂单和执行状态放在一起更易读。 |
| 挂单 + 持仓 | 废弃为一级模块，拆入「当前持仓」和「待触发挂单」 | 让用户先看账户和执行状态。 |
| AI 策略建议 | 废弃为旧一级标题，改成「AI 主裁结论」 | 更贴近用户要看的最终交易员建议。 |

说明：本轮没有删除业务数据，只是废弃旧的一级展示标题和分散布局。

## 7. UI 是否复用大周期策略风格

是。

本轮继续复用：

- `audit-card` 大容器
- 现有边框、字号、间距
- 现有 `stat-label`
- 现有折叠详情按钮
- 现有浅色 / 深色模式 class

没有引入新前端库，没有改全站 UI 风格。

## 8. 是否改 Layer A 逻辑

否。

没有修改 A1-A5 prompt、normalizer、validator、运行入口或数据逻辑。

## 9. 是否改 Layer B 逻辑

否。

没有修改 L1-L5、Master、Validator、thesis persistence、虚拟账户、挂单、A/B/C 机会行为。

## 10. 是否影响虚拟账户逻辑

否。

虚拟账户仍读取原有 API 和字段。本轮只是把它显示到「账户与执行」小节里。

## 11. 是否影响真实交易

否。

本轮没有新增或修改任何真实交易接口，没有下单，没有改仓位、止损、止盈、开平仓或反手规则。

## 12. 测试命令和结果

已运行：

```bash
uv run pytest -q tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py
git diff --check
```

结果：

- 网页相关测试：`126 passed`
- `git diff --check`：通过

## 13. 风险和未完成

- 本轮没有跑完整 pipeline，符合任务要求。
- 本轮没有用浏览器截图做人工视觉确认，只做了静态结构测试。
- 工作区里 `uv.lock` 仍有本轮开始前遗留的未提交改动，本轮不提交它。

## 14. 用户后续命令

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

## 15. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push | 待提交后完成 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | 待用户执行 |
