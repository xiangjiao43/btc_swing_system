# 替换虚拟账户收益字段展示

## 1. 任务目标

按用户要求，更新网页「虚拟账户」卡片里的字段展示：

- 保留原有卡片 UI 样式、大小、位置和底色；
- 删除原来 `PnL` 下方单独的日 / 月 / 年收益布局；
- 替换为 9 个字段；
- 不修改任何交易逻辑或数据计算。

## 2. 读取文件

- `AGENTS.md`
- `web/index.html`
- `tests/test_web_modules_1_2_3.py`

## 3. 改动文件

- `web/index.html`
- `tests/test_web_modules_1_2_3.py`
- `docs/codex_reports/replace_virtual_account_return_fields.md`

## 4. 新字段展示

「虚拟账户」卡片现在显示：

1. 初始资金
2. 权益
3. 现金
4. 历史收益率
5. 盈利/回撤
6. 日收益
7. 周收益
8. 月收益
9. 年收益

字段来源：

- `virtualAccount.initial_capital`
- `virtualAccount.total_equity`
- `virtualAccount.available_cash`
- `accountReturns.total_pct`
- `accountReturns.daily_pct`
- `accountReturns.weekly_pct`
- `accountReturns.monthly_pct`
- `accountReturns.yearly_pct`
- 现有 `cardDistanceToStop()` 展示回撤占位/现有值

颜色规则继续沿用现有收益显示：

- 正值 / 0：绿色；
- 负值：红色。

## 5. 保持不变

- 没有修改虚拟账户收益计算。
- 没有修改 Layer A 策略逻辑。
- 没有修改 Layer B 策略逻辑。
- 没有修改开仓、平仓、仓位、止损、止盈、反手规则。
- 没有修改真实交易接口。
- 没有运行 pipeline。

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

本轮只改网页展示和对应静态测试。

## 8. 删除清单 / 废弃清单

本轮无代码删除项。

展示层废弃：

- 虚拟账户卡片中的旧 `PnL` 标签展示；
- 旧的单独「日收益 / 月收益 / 年收益」分隔行。

它们被新的 9 字段展示替代。

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

- 如果后端某个收益字段为空，前端会继续按现有 `formatPct` 规则显示 `-`。
- 本轮没有运行 pipeline，因为只是前端展示调整。

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
