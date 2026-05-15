# remove_only_middle_container_borders_in_layer_b

## 1. 任务目标

本轮只处理网页「波段策略」大模块里的边框层级：保留最外层大模块边框，也保留最小内容小卡片边框，只删除夹在两者之间、仅用于分组的中间层容器边框。

本轮不改任何交易逻辑、字段内容、模块顺序、数据来源、字号、颜色，也不运行 pipeline。

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
- `docs/codex_reports/remove_only_middle_container_borders_in_layer_b.md`

## 4. 只删除中间层容器边框

本轮只删除了两个中间层外框：

1. `region-swing-account-execution`
   - 删除包住「虚拟账户 / 当前持仓 / 挂单 thesis / THESIS 历史时间线」的中间层外框边框。
   - 同步去掉该中间层标题 header 的底部分隔线，避免看起来仍像一个额外卡片外框。

2. `region-layer-cards`
   - 删除包住「交易员结论 + L1/L2/L3/L4/L5/主裁」的中间层外框边框。

## 5. 保留的小卡片边框

以下最小内容卡片边框仍保留：

- `region-virtual-account`：虚拟账户
- `region-position-summary`：当前持仓
- `region-active-thesis`：挂单 / thesis
- `region-thesis-timeline`：THESIS 历史时间线
- `region-swing-adjudicator-summary`：交易员结论
- L1/L2/L3/L4/L5/主裁 六张五层分析小卡片

「波段策略」最外层 `region-layer-b-swing` 仍保留 `audit-card` 大模块边框。

## 6. 是否改内容

否。

本轮没有删除任何文字、字段、表格、按钮、数据绑定或模块内容。

## 7. 是否改数据逻辑

否。

本轮只是 HTML class 层面的前端边框调整，不改变任何数据读取、计算、AI 输出或状态归一化逻辑。

## 8. 是否改 Layer B 逻辑

否。

没有修改 Layer B L1-L5、Master、Validator、thesis、虚拟账户、挂单、持仓、A/B/C 机会行为。

## 9. 是否改 Layer A 逻辑

否。

没有修改 Layer A A1-A5、大周期策略、Layer A context 或任何现货仓判断逻辑。

## 10. 是否影响真实交易

否。

系统仍然只是前端展示调整；没有新增真实交易接口，没有触发下单，没有修改仓位、止损、止盈、开平仓或反手规则。

## 11. 测试命令和结果

已运行：

```bash
uv run pytest -q tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py
git diff --check
```

结果：

- `135 passed in 0.08s`
- `git diff --check` 通过，无空白错误

## 12. 删除清单 / 废弃清单

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| 中间层边框 class | `web/index.html` 的 `region-swing-account-execution` | 仅用于分组，和内部小卡片边框形成重复外框 |
| 中间层 header 底部分隔线 | `web/index.html` 的 `region-swing-account-execution` header | 属于中间层容器视觉边框的一部分 |
| 中间层边框 class | `web/index.html` 的 `region-layer-cards` | 仅用于包住五层卡片组，和内部小卡片边框形成重复外框 |

无业务代码删除项。

## 13. 风险和未完成

- 风险较低：改动只涉及两个中间层容器的 class。
- 页面最终视觉仍需用户刷新生产网页后肉眼确认，因为本轮不启动浏览器、不跑完整 pipeline。
- `uv.lock` 在本轮开始前已有未提交改动，本轮没有触碰，也不会提交。

## 14. 用户后续命令

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

## 15. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push | 待执行 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | 待用户执行 |
