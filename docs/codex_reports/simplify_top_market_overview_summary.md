# simplify_top_market_overview_summary

## 1. 任务目标

本轮优化网页顶部行情总览卡片：

- 保留左侧 BTC 现价和采集时间。
- 删除右侧重复的旧策略字段。
- 改成更符合双层架构的 3 个摘要块：大周期策略、波段策略、系统状态。

本轮只改网页展示，不改策略逻辑，不跑完整 pipeline。

## 2. 改动文件

| 文件 | 改动 |
|---|---|
| `web/index.html` | 顶部行情卡片右侧改为 3 个摘要块。 |
| `web/assets/app.js` | 新增顶部摘要 helper，读取现有 state 生成简短展示文本。 |
| `tests/test_web_modules_1_2_3.py` | 增加顶部摘要结构测试，锁定旧字段不再出现。 |

## 3. 删除了哪些顶部重复字段

顶部右侧已不再展示：

- 生命周期
- 机会 / 许可
- 观察类别
- 下次运行
- 数据 / Fallback

这些信息下方已有更完整模块展示：系统自检、大周期策略、波段策略、原始数据因子、周复盘。

## 4. 新增的 3 个摘要块

1. 大周期策略
   - spot_action 中文
   - cycle_stage 中文
   - 更新时间简写
2. 波段策略
   - 当前状态
   - 主裁动作，必要时 fallback 到机会等级
   - 更新时间简写
3. 系统状态
   - 系统自检摘要
   - 数据状态摘要
   - fallback 摘要

## 5. 字段来源

| 摘要块 | 字段来源 |
|---|---|
| 大周期策略 | `layer_a_spot_strategy.a5_spot_adjudicator.spot_action`、`cycle_stage`、`spotStrategyUpdatedAt()` |
| 波段策略 | `state.main_strategy`、`summary_card.action_state_label`、`swingStrategyUpdatedAt()` |
| 系统状态 | `systemHealth.overall_status`、`state.data_health.overall`、`state.meta.fallback_level` |

所有 helper 都只是读取和翻译已有前端 state，不新增交易判断。

## 6. fallback 显示规则

- 没有 Layer A 数据：显示 `暂无` / `暂无更新`
- 没有 Layer B 数据：显示 `暂无`
- 没有系统健康数据：显示 `未知`
- 没有 fallback：显示 `无 fallback`

## 7. UI 是否保持原风格

是。

本轮继续使用原顶部卡片的：

- `audit-card`
- `stat-label`
- 现有字体、字号、边框、间距
- 现有 Tailwind class

没有新增图表，没有引入新库，没有改变顶部 BTC 价格区域。

## 8. 是否改 Layer A 逻辑

否。没有修改 A1-A5、prompt、normalizer、validator 或数据处理逻辑。

## 9. 是否改 Layer B 逻辑

否。没有修改 L1-L5、Master、Validator、thesis、虚拟账户或 A/B/C 机会行为。

## 10. 是否影响虚拟账户

否。虚拟账户逻辑不变。

## 11. 是否影响真实交易

否。没有修改真实交易接口，没有下单，没有改仓位、止损、止盈、开平仓或反手规则。

## 12. 测试命令和结果

已运行：

```bash
uv run pytest -q tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py
git diff --check
```

结果：

- 网页相关测试：`129 passed`
- `git diff --check`：通过

## 13. 风险和未完成

- 本轮没有跑完整 pipeline，符合任务要求。
- 本轮没有做浏览器截图验证，只做了静态结构测试。
- 工作区里 `uv.lock` 仍有此前遗留未提交改动，本轮未提交它。

## 14. 用户后续命令

```bash
ssh ubuntu@124.222.89.86
cd /home/ubuntu/btc_swing_system
git pull --ff-only
sudo systemctl restart btc-strategy.service
```

本轮不需要跑 pipeline。刷新网页：

```text
http://124.222.89.86/
```

## 15. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push | 待提交后完成 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | 待用户执行 |
