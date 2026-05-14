# 对齐虚拟账户卡片与当前持仓卡片排版

## 1. 任务目标

按用户要求，将「虚拟账户」卡片改成和「当前持仓」卡片一致的呈现方式：

- 保持卡片大小、位置、字体字号和底色不变；
- 保持字段内容不变；
- 使用固定两列字段结构；
- 无账户数据时也显示字段，值显示 `-`；
- 不修改任何交易逻辑或数据计算。

## 2. 读取文件

- `AGENTS.md`
- `web/index.html`
- `web/assets/app.js`
- `tests/test_web_modules_1_2_3.py`

## 3. 改动文件

- `web/index.html`
- `web/assets/app.js`
- `tests/test_web_modules_1_2_3.py`
- `docs/codex_reports/align_virtual_account_card_with_position_layout.md`

## 4. 展示调整

「虚拟账户」卡片现在和「当前持仓」一样：

- 直接显示固定字段网格；
- 不再先显示 `virtual_account 未初始化(冷启动)` 这一整块占位；
- 没有账户数据时，各字段值通过 helper 返回 `-`；
- 继续显示原字段：
  - 初始资金
  - 权益
  - 现金
  - 历史收益率
  - 盈利/回撤
  - 日收益
  - 周收益
  - 月收益
  - 年收益

新增 helper 只做前端展示 fallback：

- `virtualInitialCapitalLabel()`
- `virtualEquityLabel()`
- `virtualCashLabel()`
- `accountReturnLabel(key)`
- `accountReturnClass(key)`
- `accountProfitDrawdownLabel()`

## 5. 保持不变

- 不改虚拟账户收益计算。
- 不改账户接口。
- 不改 Layer A 策略逻辑。
- 不改 Layer B 策略逻辑。
- 不改开仓、平仓、仓位、止损、止盈、反手规则。
- 不跑 pipeline。

## 6. 测试命令和结果

```bash
uv run pytest -q tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py
```

结果：`135 passed`

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

- 虚拟账户卡片中只显示 `virtual_account 未初始化(冷启动)` 的空状态块。

它被固定字段展示替代。

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
- 如果账户接口没有返回数据，前端会显示 `-`，不会伪造账户数值。

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
