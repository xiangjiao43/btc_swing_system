# 精简挂单 / thesis 前端展示

## 1. 任务目标

按用户最新要求，只调整网页「挂单 / thesis」卡片展示：

- 删除独立的完整待触发挂单大表；
- 删除「等待入场区」字段；
- 不展示 `thesis_id`、`阶段`、`距当前`；
- 在「挂单 / thesis」卡片内部保留「失效条件」；
- 在同一卡片内部保留精简待触发挂单表，只显示：类型 / 价格 / 仓位；
- 不修改任何交易逻辑或数据逻辑。

## 2. 读取文件

- `AGENTS.md`
- `web/index.html`
- `web/assets/app.js`
- `tests/test_web_modules_1_2_3.py`

## 3. 改动文件

- `web/index.html`
- `web/assets/app.js`
- `tests/test_web_modules_1_2_3.py`
- `docs/codex_reports/update_thesis_display_simplified.md`

## 4. 前端展示调整

### 删除 / 隐藏的展示项

- 「等待入场区」
- `thesis_id`
- `阶段`
- 「距当前」列
- 独立的完整待触发挂单大表

### 保留展示项

- 「失效条件」
- 「待触发挂单」表
- 表格列：类型 / 价格 / 仓位

### 清理内容

- 删除了不再被页面使用的 `distanceFromLive()` 前端 helper。

## 5. 保持不变

- 没有修改 Layer A A1-A5 策略逻辑。
- 没有修改 Layer B L1-L5 / Master / Validator / thesis / 虚拟账户逻辑。
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

本轮只改网页展示和对应静态测试，没有触碰交易、AI、数据库、调度、虚拟账户或真实交易相关逻辑。

## 8. 删除清单 / 废弃清单

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| `distanceFromLive()` 前端 helper | `web/assets/app.js` | 「距当前」列已按用户要求删除，该 helper 不再被页面使用 |

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
- 生产页面需要用户执行 `git pull` 和服务重启后才会生效。

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
