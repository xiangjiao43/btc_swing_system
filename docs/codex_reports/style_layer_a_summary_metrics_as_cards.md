# style_layer_a_summary_metrics_as_cards

## 1. 任务目标

本轮把网页「大周期策略」模块顶部四个摘要指标改成和「波段策略」顶部摘要一致的小卡片样式。

改动只涉及前端展示样式，不改变显示内容、字段名称、数值来源、Layer A A1-A5 卡片、交易员结论框、波段策略模块或任何交易逻辑。

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
- `docs/codex_reports/style_layer_a_summary_metrics_as_cards.md`

## 4. 复用的波段策略摘要卡片样式

复用了「波段策略」顶部摘要小卡片的 class 组合：

```html
rounded border border-slate-200 dark:border-slate-800 p-2
```

大周期策略顶部四个指标现在每项都是单独小卡片：

- 大周期阶段
- 策略
- 置信度
- 风险

外层摘要容器新增 `region-layer-a-summary`，仍保持 `grid grid-cols-2 md:grid-cols-4 gap-3 text-[12px]` 横向排列。

## 5. 是否只改 UI

是。

本轮只改 HTML class 和前端静态测试，没有改任何数据读取、计算、AI 输出或状态归一化逻辑。

## 6. 是否改 Layer A 逻辑

否。

没有修改 Layer A A1-A5 prompt、context、normalizer、validator 或策略判断逻辑。

## 7. 是否改 Layer B 逻辑

否。

没有修改 Layer B L1-L5、Master、Validator、thesis、虚拟账户、挂单、持仓或 A/B/C 机会行为。

## 8. 是否影响真实交易

否。

系统仍然只是前端展示调整；没有新增真实交易接口，没有触发下单，没有修改仓位、止损、止盈、开平仓或反手规则。

## 9. 测试命令和结果

已运行：

```bash
uv run pytest -q tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py
git diff --check
```

结果：

- `137 passed in 0.08s`
- `git diff --check` 通过，无空白错误

## 10. 删除清单 / 废弃清单

本轮无业务删除项。

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| 无 | N/A | 本轮只是给现有摘要项补充卡片样式，没有替代旧业务实现 |

## 11. 风险和未完成

- 风险较低：只改大周期策略顶部四项摘要的样式。
- 页面最终视觉仍需用户刷新生产网页后肉眼确认。
- `uv.lock` 在本轮开始前已有未提交改动，本轮没有触碰，也不会提交。

## 12. 用户后续命令

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

## 13. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push | 待执行 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | 待用户执行 |
