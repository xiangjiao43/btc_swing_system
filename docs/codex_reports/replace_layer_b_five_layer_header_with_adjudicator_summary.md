# replace_layer_b_five_layer_header_with_adjudicator_summary

## 1. 任务目标

在“波段策略”模块中，删除五层分析上方的标题说明栏，并在原位置新增一个“交易员结论”横向摘要框。  
本轮只改网页展示，不改 Layer B AI 输出、不改交易逻辑、不改 thesis、不改虚拟账户、不跑 pipeline。

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
- `docs/codex_reports/replace_layer_b_five_layer_header_with_adjudicator_summary.md`

说明：工作区里仍有本轮无关的 `uv.lock` 修改，本轮没有 stage，也不会提交它。

## 4. 删除了哪些标题栏

已删除波段策略内部 `region-layer-cards` 顶部的标题说明栏：

- `五层分析`
- `L1-L5 + 主裁`
- `每层 AI 独立分析,综合判断;点"查看详细"展开关键观察 / 完整分析 / 矛盾信号`

这些只是展示标题，不是策略逻辑。

## 5. 新增了什么摘要框

在原位置新增：

- `region-swing-adjudicator-summary`
- 第一行：`swingAdjudicatorAdvice()`
- 第二行：`swingAdjudicatorSummary()`

展示逻辑：

- 正常时显示类似：`交易员结论：准备开仓 · B级机会 · 看多`
- 第二行读取已有 Master / adjudicator / summary / thesis 字段，压缩成一句主裁理由，并附带关键失效条件
- 如果 Master AI 失败或 degraded，显示：`交易员结论：主裁 AI 降级，系统使用 fallback。`
- fallback 第二行显示 `aiFailureDetail()` 或已有失效条件，避免空白

本轮没有新增 AI 调用。

## 6. 保留了哪些内容

已保留：

- 下面的 L1-L5 + 主裁六张卡片
- 每张卡片的标题、主结论、摘要、查看详细
- 关键观察 / 完整分析 / 矛盾信号展开逻辑
- 大周期策略模块
- 原始数据因子模块
- 周复盘模块

## 7. 是否改 Layer B 逻辑

否。  
没有修改 Layer B L1-L5 / Master prompt，没有改 Validator、thesis persistence、虚拟账户、A/B/C 机会行为或任何交易规则。

## 8. 是否改 Layer A 逻辑

否。  
没有修改 Layer A A1-A5、spot validator、context builder 或大周期策略逻辑。

## 9. 是否影响虚拟账户

否。  
虚拟账户数据和计算没有变化，只是网页展示结构改变。

## 10. 是否影响真实交易

否。  
本轮没有接触真实交易接口，没有跑 pipeline，也没有修改任何开仓、平仓、仓位、止损、止盈、反手逻辑。

## 11. 测试命令和结果

已运行：

```bash
uv run pytest -q tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py
git diff --check
```

结果：

- `131 passed in 0.07s`
- `git diff --check` 通过

## 12. 删除清单 / 废弃清单

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| 五层分析标题栏 | `web/index.html` 的 `region-layer-cards` 顶部 header | 被新的主裁摘要框替代，减少重复说明 |
| 五层分析说明文案 | `web/index.html` 的 `region-layer-cards` 顶部 header | 说明内容冗余，卡片自身仍保留查看详细 |

## 13. 风险和未完成

- 本轮没有浏览器截图验证，只运行了静态网页测试。
- 本轮没有部署服务器，服务器 git pull 和重启需要用户后续执行。
- `uv.lock` 仍是本轮无关改动，未纳入提交。

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

