# optimize_layer_b_swing_strategy_layout

## 1. 任务目标

优化网页“波段策略”大模块的前端排版，让它更紧凑、整洁，并和“大周期策略”模块风格更一致。  
本轮只改前端展示，不改 Layer A / Layer B 策略逻辑，不改挂单、持仓、thesis、虚拟账户数据来源，不跑 pipeline。

## 2. 读取过的关键文件

- `AGENTS.md`
- `web/index.html`
- `web/assets/app.js`
- `tests/test_web_modules_1_2_3.py`
- `tests/test_web_modules_4_5_rp_failure.py`
- `tests/web_helpers/test_normalize_state.py`

## 3. 改动文件

- `web/index.html`
- `tests/test_web_modules_1_2_3.py`
- `docs/codex_reports/optimize_layer_b_swing_strategy_layout.md`

说明：工作区里仍有本轮无关的 `uv.lock` 修改，本轮没有 stage，也不会提交它。

## 4. 前端排版调整

本轮完成：

- 保留“波段策略”大模块外层卡片
- 波段策略内部小模块去掉边框，改成浅色底 + 留白分隔
- 删除“账户与执行”标题栏
- 虚拟账户放在上方第一列，后面紧接当前持仓和挂单 / thesis
- AI 主裁结论保留，但去掉冗余框线，使用浅色底展示
- 五层分析 L1-L5 + 主裁卡片保留，宽屏下改为横向六列排列
- 五层分析小卡去掉边框，保持查看详细逻辑不变

## 5. 已确认删除 / 保持不显示的信息

继续保持不显示：

- 等待入场区
- thesis_id
- 阶段 / planned / active
- 距当前

待触发挂单表仍只显示：

- 类型
- 价格
- 仓位

## 6. 是否保留功能和数据

保留。  
虚拟账户、当前持仓、挂单 / thesis、待触发挂单、thesis 历史、AI 主裁结论、L1-L5 + 主裁卡片仍然存在，只是排版变轻。

## 7. 是否改 Layer B 逻辑

否。  
没有修改 Layer B L1-L5、Master、Validator、thesis persistence、虚拟账户、A/B/C 机会行为或任何交易规则。

## 8. 是否改 Layer A 逻辑

否。

## 9. 是否影响虚拟账户

否。  
虚拟账户计算、持仓、PnL、回撤逻辑均未修改。

## 10. 是否影响真实交易

否。  
没有接触真实交易接口，没有运行 pipeline。

## 11. 测试命令和结果

已运行：

```bash
uv run pytest -q tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py
git diff --check
```

结果：

- `132 passed in 0.08s`
- `git diff --check` 通过

## 12. 删除清单 / 废弃清单

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| “账户与执行”标题栏 | `web/index.html` 的 `region-swing-account-execution` | 用户要求去掉该标题，让波段策略内部更紧凑 |
| 波段策略内部小模块边框 | `web/index.html` 的摘要块、账户/持仓/挂单、主裁摘要、五层卡片 | 用户要求内部小模块去边框，统一轻量展示 |

## 13. 风险和未完成

- 本轮没有浏览器截图验证，只运行了静态网页测试。
- 服务器尚未部署，需要用户执行 git pull 和重启服务。
- 本轮没有跑 pipeline，符合用户要求。

## 14. 用户后续命令

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

## 15. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | 通过 |
| GitHub push | 本轮 commit 后执行，最终状态见对话收尾 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | 待用户执行 |

