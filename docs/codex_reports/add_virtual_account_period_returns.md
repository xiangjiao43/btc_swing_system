# 虚拟账户增加日 / 月 / 年收益展示

## 1. 任务目标

按用户要求，在网页「虚拟账户」卡片中增加一行展示指标：

- 日收益
- 月收益
- 年收益

本轮只改前端展示，不修改任何交易逻辑、收益计算逻辑或数据接口。

## 2. 读取文件

- `AGENTS.md`
- `web/index.html`
- `tests/test_web_modules_1_2_3.py`

## 3. 改动文件

- `web/index.html`
- `tests/test_web_modules_1_2_3.py`
- `docs/codex_reports/add_virtual_account_period_returns.md`

## 4. 展示调整

在「虚拟账户」卡片的原有字段下方新增一行三列指标：

- `accountReturns.daily_pct` → 日收益
- `accountReturns.monthly_pct` → 月收益
- `accountReturns.yearly_pct` → 年收益

颜色规则：

- 正值 / 0：绿色
- 负值：红色

使用现有 `formatPct(..., true)` 格式化，不新增计算逻辑。

## 5. 保持不变

保留原有字段：

- 权益
- 现金
- PnL
- 回撤
- 初始资金
- 30 天资金曲线

没有修改：

- Layer A 策略逻辑
- Layer B 策略逻辑
- 虚拟账户计算逻辑
- 真实交易接口
- 数据库
- pipeline

## 6. 测试命令和结果

```bash
uv run pytest -q tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py
```

结果：`133 passed`

后续还会执行：

```bash
git diff --check
```

结果：通过，无 whitespace / patch 格式问题。

## 7. 是否触碰高风险区域

否。

本轮只展示已有收益字段，没有改变收益计算、交易行为或账户状态。

## 8. 删除清单 / 废弃清单

本轮无替代关系，无删除项。

原因：本轮只是新增前端展示指标，没有替代旧实现。

## 9. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push(commit hash) | 待提交后记录 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | 待用户执行 |

## 10. 风险和未完成

- 本轮没有运行 pipeline，因为只是前端展示调整。
- 如果后端某个周期收益字段为空，前端会按现有 `formatPct` 显示 `-`。

## 11. 用户后续命令

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
