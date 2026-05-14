# layer_a_ui_and_layer_b_c_grade_final_cleanup

## 1. 任务目标

本轮做 Layer A UI 和 Layer B C 级机会语义的最后一轮收尾：

1. 让 Layer A 大周期策略摘要更短、更像交易员最终建议。
2. 让 A1-A5 卡片首屏文字长度更合理，长证据继续折叠。
3. 确认新增原始数据因子仍然使用 deterministic plain_reading，不调用 AI。
4. 清理 Layer B C 级机会残留的误导文案：C 级只观察，不创建 thesis。
5. 只跑短单元测试和网页静态测试，不跑完整 pipeline。

## 2. 读取过的关键文件

- `AGENTS.md`
- `README.md`
- `config/data_catalog.yaml`
- `config/data_sources.yaml`
- `src/ai/spot_cycle_context_builder.py`
- `src/evidence/plain_reading.py`
- `src/ai/agents/prompts/l3_opportunity.txt`
- `src/ai/agents/prompts/master_adjudicator.txt`
- `src/strategy/thesis_persistence.py`
- `src/strategy/state_machine.py`
- `src/ai/validator.py`
- `src/ai/orchestrator.py`
- `web/index.html`
- `web/assets/app.js`
- `tests/test_layer_a_spot_context_builder.py`
- `tests/test_plain_reading.py`
- `tests/test_web_modules_1_2_3.py`
- `tests/test_web_modules_4_5_rp_failure.py`

## 3. 改动文件

| 文件 | 改动说明 |
|---|---|
| `web/assets/app.js` | 新增 `compactSpotText`、`spotFinalAdvice`、`spotFinalSummary`、`spotCardSummary`，只压缩网页展示文字，不改 AI 输出和策略逻辑。 |
| `web/index.html` | Layer A 顶部摘要改为“交易员结论:策略 · 阶段”，A1-A5 卡片摘要走短句显示，完整原文放 `title`。同时 bump `app.js` cache 参数。 |
| `src/ai/agents/prompts/l3_opportunity.txt` | 将 L3 角色描述和 `watch` 文案改成“C 只观察 / future watch”，避免 C 级被误解成开仓候选。 |
| `src/strategy/no_opportunity_narrator.py` | post-protection 兜底文案从 “A/B/C 级进入候选” 改成 “A/B 级进入 thesis 候选，C 级只作为观察”。 |
| `tests/test_web_modules_1_2_3.py` | 增加 Layer A 摘要短句、交易员结论、折叠详情静态测试。 |
| `tests/test_web_modules_4_5_rp_failure.py` | 增加新增原始因子复用旧卡片结构的测试。 |
| `tests/test_no_opportunity_narrator.py` | 增加 post-protection 不把 C 级当 thesis 候选的测试。 |
| `tests/test_master_adjudicator_v14.py` | 测试样例中旧 “L3 升 B/C” 改成 “L3 升 B”。 |

## 4. Layer A UI 收尾说明

本轮没有改 A1-A5 的 AI prompt 和策略判断。

网页展示层做了三个小处理：

1. 顶部大周期摘要显示为：`交易员结论:分批买入 · 底部吸筹。...`
2. A5 主裁摘要前加“最终建议”，更像交易员给用户看的结论。
3. A1-A5 卡片首屏只显示短摘要，支持证据、反方证据、数据质量备注仍然通过“查看详细”折叠展示。

这对交易系统意味着：用户打开网页先看到简洁结论，不会被长段 AI 输出淹没；但审计证据仍然保留，可以展开看。

## 5. 原始数据因子显示确认

新增因子仍然沿用现有「原始数据因子」模块：

- 不新增独立模块。
- 不改字体、字号、颜色、badge、卡片布局。
- 显示结构仍是：标题、右上角数值、一句话 plain_reading、状态行、抓取时间。
- plain_reading 仍由规则模板生成，不调用 AI。
- 内部错误如 `proxy_endpoint_404` 不在主卡片展示。

本轮没有改新增因子的数据抓取、context builder 或 factor coverage 逻辑。

## 6. Layer B C 级机会文案收尾

统一后的 C 级语义：

| 等级 | 语义 |
|---|---|
| A | 高质量波段机会，可进入 thesis 创建候选。 |
| B | 合格波段机会，可进入 thesis 创建候选。 |
| C | 观察型 / 低质量 / 埋伏关注机会，只能作为 future watch / observation note，不创建 thesis，不进虚拟账户，不触发订单。 |
| NONE | 无交易机会。 |

本轮清理了两个容易误导的文案：

1. L3 prompt 开头不再说 A/B/C 都是“开仓好时机”。
2. post-protection 兜底说明不再说 A/B/C 都能进入候选。

## 7. 删除清单 / 废弃清单

| 对象 | 路径 / 位置 | 处理方式 | 原因 |
|---|---|---|---|
| “opportunity_grade 是不是开仓好时机(A/B/C/none)” | `src/ai/agents/prompts/l3_opportunity.txt` | 已替换 | C 级不是开仓候选，只是观察。 |
| `watch — grade=B/C` 的模糊说明 | `src/ai/agents/prompts/l3_opportunity.txt` | 已替换 | 明确 B 是等确认，C 是观察 / future watch。 |
| “机会层重新出现 A/B/C 级 → 可重新规划机会” | `src/strategy/no_opportunity_narrator.py` | 已替换 | C 级不创建 thesis，应避免误导。 |
| 测试样例 “L3 升 B/C” | `tests/test_master_adjudicator_v14.py` | 已替换 | 测试文案不应暗示 C 级可进入 thesis 候选。 |

本轮没有删除文件。

## 8. 实际运行命令

```bash
uv run pytest -q tests/test_layer_a_spot_context_builder.py tests/test_plain_reading.py
uv run pytest -q tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py
uv run pytest -q tests/test_no_opportunity_narrator.py tests/test_master_adjudicator_v14.py tests/test_validator_v14_part1.py tests/test_validator_v14_part2.py tests/test_validator_v14_integration.py tests/test_sprint_g_p0_thesis_persistence.py tests/web_helpers/test_normalize_state.py
uv run pytest -q tests/test_web_modules_*.py tests/web_helpers/test_normalize_state.py
git diff --check
```

## 9. 测试结果

| 测试 | 结果 |
|---|---|
| Layer A context + plain_reading | 39 passed |
| Web modules 1/2/3 + 4/5 | 74 passed |
| C 级文案 / Master / Validator / persistence / normalize | 173 passed |
| Web modules 通配 + normalize | 120 passed |
| `git diff --check` | 通过 |

## 10. 是否触碰高风险区域

| 区域 | 是否触碰 | 说明 |
|---|---|---|
| Layer A 核心 AI / 策略逻辑 | 否 | 只改网页展示短摘要，不改 A1-A5 判断。 |
| Layer A 数据逻辑 | 否 | 未改 context builder、collector、factor coverage。 |
| Layer B A/B thesis 创建逻辑 | 否 | 未改 persistence、state machine、A/B 行为。 |
| Layer B C 级真实行为 | 否 | 仍然不创建 thesis，本轮只清文案。 |
| 虚拟账户 | 否 | 未改。 |
| 真实交易 | 否 | 未改。 |
| 网页布局 / UI 风格 | 否 | 只改文案绑定和 cache 参数，不改整体布局样式。 |

## 11. 风险和未完成

1. 本轮没有跑完整 pipeline，也没有生成新的线上 run；这是按用户要求避免长时间 AI pipeline。
2. 网页截图未生成；本轮使用静态 HTML / JS 测试锁住显示结构。
3. 历史报告中可能仍保留旧 C 级语义，那些是历史记录，不作为当前运行规则。
4. `uv.lock` 是本轮开始前已有未提交改动，本轮不提交它。

## 12. 用户后续命令

```bash
ssh ubuntu@124.222.89.86
cd /home/ubuntu/btc_swing_system
git pull --ff-only
sudo systemctl restart btc-strategy.service
```

刷新网页：

```text
http://124.222.89.86/
```

## 13. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push(commit hash: 本报告随本轮 commit 提交,最终 hash 见对话收尾) | 待提交 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | 待用户执行 |

