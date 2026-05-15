# normalize_raw_factor_card_borders

## 1. 任务目标

本轮统一网页「原始数据因子」大模块内所有因子卡片的边框样式：删除主要因子卡片左侧绿色竖线 / 绿色左边框，让所有因子卡片都使用普通浅灰边框。

本轮不改变卡片内容、数值、说明、状态、抓取时间、状态小圆点、状态文字颜色、数据逻辑或任何策略逻辑。

## 2. 读取文件

- `AGENTS.md`
- `web/index.html`
- `web/assets/app.js`
- `tests/test_web_modules_1_2_3.py`
- `tests/test_web_modules_4_5_rp_failure.py`
- `tests/web_helpers/test_normalize_state.py`

## 3. 改动文件

- `web/index.html`
- `tests/test_web_modules_4_5_rp_failure.py`
- `docs/codex_reports/normalize_raw_factor_card_borders.md`

## 4. 移除了哪些绿色左边框样式

移除了原始数据因子卡片上的主要因子左侧绿色竖线：

```html
:class="c.is_primary ? 'border-l-2 border-l-emerald-500 dark:border-l-emerald-400' : ''"
```

同时删除了页面说明中的「左绿边=主要」文案，并把注释里的「主要因子在前(左绿边)」改为「主要因子在前」。

现在所有原始因子卡片统一使用普通浅灰边框：

```html
border border-slate-200 dark:border-slate-800 rounded px-2.5 py-2
```

## 5. 保留了哪些状态样式

以下状态展示保留不变：

- 右上角状态小圆点仍由 `freshnessColor(c.data_fresh ? 'green' : 'red')` 控制。
- 状态文字仍由 `factorStatusLine(c)` 显示。
- 数值颜色、偏多 / 偏空影响方向颜色仍由 `directionClass(c.impact_direction)` 控制。
- 抓取时间仍由 `fetchedAtPrimary(c) || '-'` 显示。
- plain reading 一句话说明不变。

## 6. 是否改数据逻辑

否。

没有修改 `rawFactorCards()`、factor 分组、freshness、plain_reading、数据状态判断、抓取时间或任何数值来源。

## 7. 是否改 Layer A

否。

没有修改 Layer A A1-A5、context、normalizer、validator 或大周期策略逻辑。

## 8. 是否改 Layer B

否。

没有修改 Layer B L1-L5、Master、Validator、thesis、虚拟账户、挂单、持仓或 A/B/C 机会行为。

## 9. 是否影响真实交易

否。

本轮只是前端边框样式调整；没有新增真实交易接口，没有触发下单，没有修改仓位、止损、止盈、开平仓或反手规则。

## 10. 测试命令和结果

已运行：

```bash
uv run pytest -q tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py
git diff --check
```

结果：

- `138 passed in 0.08s`
- `git diff --check` 通过，无空白错误

## 11. 删除清单 / 废弃清单

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| `border-l-2 border-l-emerald-500 dark:border-l-emerald-400` 动态 class | `web/index.html` 原始数据因子卡片 article | 用户要求原始因子卡片统一普通浅灰边框，不再用绿色左侧竖线 |
| 「左绿边=主要」说明文字 | `web/index.html` 原始数据因子分组标题 | 绿色左边框已取消，继续显示会误导用户 |

无业务代码删除项。

## 12. 风险和未完成

- 风险较低：只改原始数据因子模块的卡片边框样式。
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
| GitHub push | ✅（commit hash: `7caa711`） |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | 待用户执行 |
