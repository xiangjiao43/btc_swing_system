# align_layer_b_c_grade_opportunity_semantics

## 1. 任务目标

本轮目标是对齐 Layer B 中 C 级机会的语义：prompt、文档、测试、Validator 和网页文案都要与当前真实持久化行为一致。

小白版结论：系统现在真实行为是 **C 级不会创建 thesis，不会进虚拟账户，也不会触发订单**。本轮没有让 C 级开始交易，而是把容易误导 AI 或用户的旧说法改掉。

## 2. 读取过的关键文件

- `AGENTS.md`
- `README.md`
- `config/ai.yaml`
- `config/state_machine.yaml`
- `config/schemas.yaml`
- `src/ai/agents/prompts/l3_opportunity.txt`
- `src/ai/agents/prompts/master_adjudicator.txt`
- `src/ai/agents/master_adjudicator.py`
- `src/strategy/thesis_persistence.py`
- `src/strategy/state_machine.py`
- `src/ai/validator.py`
- `src/ai/orchestrator.py`
- `src/api/routes/`
- `web/index.html`
- `web/assets/app.js`
- `src/web_helpers/normalize_state.py`
- `src/strategy/no_opportunity_narrator.py`
- `tests/` 中 Validator、thesis persistence、网页 normalize、周复盘、Layer A 相关测试
- `docs/codex_reports/dual_layer_factor_inventory_and_data_source_audit.md`
- `docs/codex_reports/layer_a_spot_cycle_strategy_full_model_and_implementation.md`
- `docs/codex_reports/schedule_layer_a_spot_strategy_at_10am.md`

## 3. 当前 C 级真实行为审查

| 链路 | 当前真实行为 |
|---|---|
| L3 prompt | C 级表示低质量机会、可观察，但原先没有足够明确写“不会创建 thesis”。 |
| Master prompt | 旧文案曾写 `L3 grade ∈ {A, B, C}` 可以 `new_thesis`，这是主要冲突点。 |
| Master fallback | 旧 fallback 的 `what_would_change_mind` 写过 `{A, B, C}`，容易暗示 C 级也可建仓。 |
| persistence | `src/strategy/thesis_persistence.py` 明确 `_ALLOWED_GRADES = ("A", "B")`，C 级不会创建 thesis。 |
| state machine | `src/strategy/state_machine.py` 进入 `LONG_PLANNED` / `SHORT_PLANNED` 要求 `l3_grade in {"A", "B"}`。 |
| Validator | 旧 V5 / V10 / V21 还残留 “C + ambush_only / A,B,C 可 new_thesis” 的语义。 |
| 测试 | persistence 已有 `C 级不创建 thesis` 测试；Validator 部分测试还按旧 C 级 ambush thesis 假设。 |
| 网页 | C 级展示为“保持空仓观察”，方向基本正确，但未明确“不创建 thesis”。 |
| Layer A | 未读取 Layer B C 级，不受本轮影响。 |

判断：当前真实行为是 **C 级不会创建 thesis**。本轮以这个真实行为为准对齐。

## 4. 发现的冲突点

1. `src/ai/agents/prompts/master_adjudicator.txt` 曾要求 A/B/C 都可以创建 `new_thesis`。
2. `docs/modeling.md` 仍保留旧 v1.3 “C 级也创建 thesis、强制 ambush_only” 说明。
3. `src/ai/validator.py` 的 V5 / V10 / V21 仍把 C 级当成可创建 thesis 的弱机会。
4. Validator 测试里仍有 “C 级 permission=can_open → 强制 ambush_only” 的旧假设。
5. 网页标题没有明确告诉用户 C 级只是观察，不创建 thesis。

## 5. 统一后的 C 级定义

| 等级 | 统一语义 |
|---|---|
| A | 高质量波段机会，可进入 thesis 创建候选。 |
| B | 合格波段机会，可进入 thesis 创建候选，但受风险和 Validator 约束。 |
| C | 观察型 / 低质量 / 埋伏关注机会。可以写入分析说明、观察理由、future watch condition，但默认不创建 active swing thesis，不进入虚拟账户，不触发订单。 |
| NONE | 无交易机会。 |

C 级仍然是 Layer B 内部机会等级，不属于 Layer A，也不会触发 Layer A 现货分批买入。

## 6. 改动文件

| 文件 | 改动说明 |
|---|---|
| `src/ai/agents/prompts/l3_opportunity.txt` | 补充 C 级是观察型机会，不创建 thesis、不进虚拟账户、不触发订单。 |
| `src/ai/agents/prompts/master_adjudicator.txt` | 将 thesis 创建候选从 A/B/C 改为 A/B；C 级改为 silent / 观察 / future watch。 |
| `src/ai/agents/master_adjudicator.py` | fallback 的改变条件从 `{A,B,C}` 改为 `{A,B}`。 |
| `src/ai/validator.py` | V5 阻止 C 级 `new_thesis`；V10 不再维护 C 级建仓分数区间；V21 只对 A/B silent 触发软抗拒。 |
| `src/strategy/no_opportunity_narrator.py` | no opportunity fallback 条件从 `{A,B,C}` 改为 `{A,B}`。 |
| `src/web_helpers/normalize_state.py` | C 级 headline 改为“C 级观察型机会，不创建 thesis”。 |
| `docs/modeling.md` | 对齐 C 级不创建 thesis 的建模说明。 |
| `tests/test_validator_v14_part1.py` | 更新 V5/V10 C 级测试。 |
| `tests/test_validator_v14_part2.py` | 新增 C 级 silent 不触发 V21 软抗拒测试。 |
| `tests/test_validator_v14_integration.py` | 新增 C 级被 Validator 改为 silent 的集成测试；A/B 旧逻辑保持覆盖。 |
| `tests/web_helpers/test_normalize_state.py` | 锁定网页 C 级 headline 不暗示开仓。 |

## 7. 是否改实际交易行为

没有。

更准确地说：真实持久化行为本来就是 C 级不创建 thesis。本轮没有让 C 级新增任何下单能力、持久化能力或虚拟账户能力，只把 prompt、Validator 语义、测试和用户展示对齐到这个事实。

## 8. 是否改 C 级 persistence 行为

没有。

`src/strategy/thesis_persistence.py` 仍然只允许 A/B 创建 thesis：`_ALLOWED_GRADES = ("A", "B")`。

## 9. 是否影响 Layer A

没有。

Layer A 仍然是独立的大周期现货策略，不读取 Layer B C 级机会，不使用 A/B/C/NONE，不创建 thesis，不进入虚拟账户。

## 10. 是否影响 Layer B A/B 机会

没有。

A/B 仍然是 thesis 创建候选；本轮测试也保留了 B 级 permission 被 Validator 规范化的覆盖。

## 11. 是否影响虚拟账户

没有。

C 级不会进入虚拟账户。A/B 的原有虚拟账户链路没有改。

## 12. 是否影响真实交易

没有。

本项目仍然不是自动真实下单机器人；本轮没有新增或修改任何真实交易接口。

## 13. 删除清单 / 废弃清单

| 对象 | 路径 / 位置 | 处理方式 | 原因 |
|---|---|---|---|
| “C 级也创建 thesis” prompt 表述 | `src/ai/agents/prompts/master_adjudicator.txt` | 已替换 | 与当前 persistence 真实行为冲突。 |
| “C 级强制 ambush_only thesis” 建模表述 | `docs/modeling.md` | 已替换 | 旧 v1.3 语义与当前 A/B-only persistence 冲突。 |
| Validator 中 C 级可建 thesis 的弱机会假设 | `src/ai/validator.py` V5/V10/V21 | 已废弃并改为 C 级 silent / observe | 防止 C 级被误判成应创建 thesis。 |
| 旧 Validator C 级 ambush 测试假设 | `tests/test_validator_v14_part1.py` 等 | 已替换 | 测试应锁定真实行为，而不是历史假设。 |
| 历史报告中的 C 级冲突记录 | `docs/cc_reports/`、旧 `docs/codex_reports/` | 保留为历史资料 | 这些是历史审计记录，不作为当前运行规则。 |

本轮没有删除文件。

## 14. 实际运行命令

```bash
rg "opportunity_grade|ambush_only|C级|grade C|thesis|persistence|create thesis|watch|观察" tests src web docs config
rg -n "C 级.*thesis|C级.*thesis|C 级.*创建|C级.*创建|C.*ambush_only|grade=C|grade ∈ \\{A, B, C\\}|A/B/C.*创建|ambush_only.*持久化|ambush_only.*thesis" src tests web config docs/modeling.md docs/codex_reports README.md
uv run pytest -q tests/test_validator_v14_part1.py tests/test_validator_v14_part2.py tests/test_validator_v14_integration.py tests/test_sprint_g_p0_thesis_persistence.py tests/web_helpers/test_normalize_state.py tests/test_no_opportunity_narrator.py
uv run pytest -q tests/test_layer_a_spot_context_builder.py tests/test_layer_a_spot_normalize.py tests/test_layer_a_spot_validator.py
uv run pytest -q tests/test_jobs_weekly_review_and_health_check.py tests/test_weekly_review_input_builder.py tests/test_weekly_review_analyst.py
uv run pytest -q tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py
uv run pytest -q tests/ai/test_validator_v14_retry.py tests/ai/test_orchestrator_retry.py tests/pipeline/test_orchestrator_mapper.py
git diff --check
```

## 15. 测试结果

| 测试 | 结果 |
|---|---|
| Validator / thesis persistence / normalize / no opportunity | 151 passed |
| Layer A context / normalize / spot validator | 25 passed |
| 周复盘回归 | 68 passed |
| 网页模块回归 | 118 passed |
| Validator retry / orchestrator retry / mapper | 66 passed |
| `git diff --check` | 通过 |

## 16. 高风险区域检查

| 区域 | 是否触碰 | 说明 |
|---|---|---|
| Layer B 开仓 / 平仓 / 仓位 / 止损 / 止盈 / 反手规则 | 否 | 未改交易规则。 |
| Layer B thesis persistence 真实行为 | 否 | 仍只允许 A/B 创建。 |
| Layer B Validator 交易硬约束 | 轻微语义对齐 | 只把 C 级从旧“可 ambush thesis”对齐为“不创建 thesis”，没有放宽交易。 |
| Layer A 逻辑 | 否 | 未改。 |
| 虚拟账户 | 否 | 未改。 |
| 真实交易接口 | 否 | 未改。 |
| `.env` / key / token / secret | 否 | 未读取或输出。 |

## 17. 风险和未完成

1. 历史报告里仍会看到旧 C 级描述，这些保留为历史记录，不是当前运行口径。
2. `config/schemas.yaml` 仍保留 `opportunity_grade` 可取 A/B/C/NONE，这是正确的；C 级仍可作为观察等级存在。
3. 如果未来用户想让 C 级成为“观察单”或“非交易 watchlist”机制，需要单独设计，不应复用 thesis / virtual account。

## 18. 用户后续命令

```bash
ssh ubuntu@124.222.89.86
cd /home/ubuntu/btc_swing_system
git pull --ff-only
sudo systemctl restart btc-strategy.service
```

本轮不需要立即跑 pipeline。

刷新网页：

```text
http://124.222.89.86/
```

## 19. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push(commit hash: 本报告随本轮 commit 提交,最终 hash 见对话收尾) | 待提交 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | 待用户执行 |
