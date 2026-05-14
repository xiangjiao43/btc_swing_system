# remove_layer_b_thesis_entry_zone_display

## 1. 任务目标

按用户补充要求，简化“波段策略 → 挂单 / thesis”卡片：

- 删除“等待入场区”
- 继续不显示 `thesis_id`
- 继续不显示阶段 / planned / active
- 删除“距当前”
- 不再把待触发挂单作为独立大表展示
- 保留失效条件
- 保留待触发挂单表，表格只保留：类型 / 价格 / 仓位

本轮只改网页展示，不改交易逻辑。

## 2. 读取过的关键文件

- `AGENTS.md`
- `web/index.html`
- `web/assets/app.js`
- `tests/test_web_modules_1_2_3.py`
- `tests/test_web_modules_4_5_rp_failure.py`
- `tests/web_helpers/test_normalize_state.py`

## 3. 改动文件

- `web/index.html`
- `web/assets/app.js`
- `tests/test_web_modules_1_2_3.py`
- `docs/codex_reports/remove_layer_b_thesis_entry_zone_display.md`

说明：工作区里仍有本轮无关的 `uv.lock` 修改，本轮没有 stage，也不会提交它。

## 4. 前端展示调整

“挂单 / thesis”卡片现在只展示：

- 失效条件
- 待触发挂单表

待触发挂单表已收进“挂单 / thesis”卡片内部，不再作为单独大块展示。表格列固定为：

- 类型
- 价格
- 仓位

已删除：

- 等待入场区
- thesis_id
- 阶段 / planned / active
- 距当前
- `distanceFromLive` 前端 helper

## 5. 是否改 Layer B 逻辑

否。  
本轮没有修改 Layer B L1-L5、Master、Validator、thesis persistence、虚拟账户、A/B/C 机会行为或任何交易规则。

## 6. 是否改 Layer A 逻辑

否。

## 7. 是否影响虚拟账户

否。  
虚拟账户计算、持仓、PnL、回撤逻辑均未修改。

## 8. 是否影响真实交易

否。  
没有接触真实交易接口，没有运行 pipeline。

## 9. 测试命令和结果

已运行：

```bash
uv run pytest -q tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py
git diff --check
```

结果：

- `131 passed in 0.08s`
- `git diff --check` 通过

## 10. 删除清单 / 废弃清单

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| 等待入场区展示 | `web/index.html` 的 `region-active-thesis` | 与更具体的分批 entry 挂单价重复，经常显示 `-` |
| 独立待触发挂单大表外框 | `web/index.html` 原 `region-orders-position` 外层 | 待触发挂单表已收进“挂单 / thesis”卡片 |
| 距当前列 | `web/index.html` 的待触发挂单表 | 用户要求表格只保留类型 / 价格 / 仓位 |
| `distanceFromLive` helper | `web/assets/app.js` | 只服务已删除的“距当前”列 |

## 11. 风险和未完成

- 本轮没有浏览器截图验证，只运行了静态网页测试。
- 服务器尚未部署，需要用户执行 git pull 和重启服务。
- 本轮没有跑 pipeline，符合用户要求。

## 12. 用户后续命令

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

## 13. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | 通过 |
| GitHub push | 本轮 commit 后执行，最终状态见对话收尾 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | 待用户执行 |

