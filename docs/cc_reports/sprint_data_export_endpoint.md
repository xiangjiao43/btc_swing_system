# Sprint: Data Export Endpoint

**日期**：2026-06-08
**Commit**：`d1803ef` — `feat(export): add /api/export/snapshot.md data export endpoint for external AI analysis`

## Triggers

- 项目方向调整：保留数据采集层，逐步退出本系统内的 AI 判断 + 复杂网页层；改由外部 AI（ChatGPT / Claude / 自选）读取一份"系统全量数据 markdown"做综合分析
- 关键判断：`SpotCycleContextBuilder.build_spot_cycle_context()` 与 `ContextBuilder.build_full_context()` 是纯数据组装（0 AI 依赖），可直接复用为导出端点的数据源

## 端点设计

- **路径**：`GET /api/export/snapshot.md`
- **返回**：`text/markdown; charset=utf-8`（不是 JSON）
- **大小**：~6.4 KB
- **覆盖**：69 个数值指标 + 1 事件（CPI Release 2026-06-13）
- **章节**：价格技术（18） / 链上（29） / 衍生品（10） / 宏观（12） / 事件日历（1）

每行格式：
```
- 指标名: 值 [单位] ｜ 数据时间: YYYY-MM-DD ｜ [新鲜/⚠️STALE/❌缺失]
```

价格技术段**只给数值，不含 K 线形态描述**——形态由外部 AI 自行判读（避免我方"系统人读层"再次承担解释职责）。

## 新鲜度分档逻辑

| 类型 | 阈值 | 因子示例 |
|---|---|---|
| 日频（价格 / 衍生品 / Glassnode 链上） | **3 天** | BTC 现价 / OI / MVRV-Z |
| FRED 周更（H.10 / H.15） | **3 天**（按日频判，露出真实滞后） | DXY / 10y / VIX / 纳指 |
| 周度宏观（H.4.1） | **10 天** | fed_balance_sheet |
| 月频宏观 | **40 天** | CPI / Core CPI / M2 / PCE |
| 政策利率 | **45 天** | fed_funds_rate |
| ETF 流量（仅交易日） | **5 天**（跨周末 + 1 工作日） | etf_flow / etf_flow_7d / etf_flow_30d |

代码位置：[src/api/routes/export.py:23-49](../../src/api/routes/export.py)

## 派生指标时间戳继承

派生指标（窗口聚合 / 相关系数 / 累计和）自身没有 `as_of`，按其**基准 series 的 as_of** 判新鲜度：

| 派生 | 基准 |
|---|---|
| `funding_rate_z_score_90d` | `funding_rate` |
| `open_interest_z_score_90d` | `open_interest` |
| `etf_flow_7d_sum_usd` / `etf_flow_30d_sum_usd` | `etf_flow` |
| `btc_nasdaq_corr_60d` | `nasdaq` |
| `exchange_net_flow_30d_sum` | `exchange_net_flow` |
| `lth_supply_90d_pct_change` | `lth_supply` |
| `sth_supply_90d_pct_change` | `sth_supply` |

逻辑在 `render_factors_markdown()` 内的 walk 步骤后，先建 `key → as_of` map，再对 `_DERIVED_BASE` 表的派生指标回填 `as_of`，标记 `_derived_from`。

## Markdown 顶部"新鲜度说明"区块

为避免外部 AI 把结构性滞后（FRED H.10/H.15 周更、月频发布节奏、ETF 仅交易日）误读为采集故障，导出文件顶部固定加一段说明：

```
### 新鲜度说明（结构性滞后 vs 真异常）
- FRED 宏观（DXY/VIX/纳指/收益率）：美联储 H.10/H.15 每周一发布上周数据 ……
- FRED 月频（CPI/Core CPI/M2/PCE）：每月一次发布，月中滞后属正常
- 联邦基金利率：仅 FOMC 会议后变动，长期不变属正常
- Glassnode 链上：通常 T+1；偶尔单 endpoint 滞后 2-4 天属上游问题
- ETF 流量：仅交易日发布，周末 + 节假日无数据

因此 ⚠️STALE 分两类：结构性滞后（按节奏正常） vs 真异常（日频数据超出周末/节假日仍未更新）。分析时请区分对待。
```

## DXY 根因排查（同 sprint 副产）

curl FRED `series` metadata 拿到的硬证据：

```json
{
  "id": "DTWEXBGS",
  "frequency": "Daily",
  "observation_end": "2026-05-29",
  "last_updated": "2026-06-01 16:26:40-05"
}
```

结论：DXY 2026-05-29 起不更新**不是我方采集故障**，是 FRED `DTWEXBGS` 由美联储 H.10 release 每周一发布，自身有约 1 周滞后。下次 FRED 预期更新 = 2026-06-08（周一）美中部时间。

## 改动文件清单

| 文件 | 类型 | 行数 |
|---|---|---|
| `src/api/routes/export.py` | 新增 | +477 |
| `src/api/app.py` | 修改（import + include_router） | +3 |

## 部署验证日志

```
本地：python3 -c "from src.api.app import create_app; …" → export routes: ['/api/export/snapshot.md']
scp 到 ~/btc_swing_system/src/api/{routes/export.py,app.py}
sudo systemctl restart btc-strategy → is-active = active
curl http://127.0.0.1:8000/api/export/snapshot.md →
  HTTP/1.1 200 OK
  content-type: text/markdown; charset=utf-8
  content-length: 6367
git pull origin main → Updating 54f89a5..d1803ef Fast-forward
git status → On branch main, up to date with origin/main, working tree clean
curl 复测 → HTTP 200 ｜ 6367 bytes ｜ text/markdown; charset=utf-8
```

样本"新鲜度总览"：总 69 ｜ 新鲜 58 ｜ ⚠️STALE 11 ｜ ❌缺失 0 ｜ 事件 1。
11 项 STALE 全部"结构性滞后"，无真异常。

## 本 sprint 删除清单

**本 sprint 无替代关系，无删除项**

理由：纯新增端点，与现有 18 个路由共存（不替代任何路由）；不动 AI 判断层、不动 web 层、不动 collectors、不动 schema。后续项目方向调整（退出 AI 判断 / 简化网页）会在独立 sprint 处理。

## 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | N/A（本次仅冒烟测试，未跑 pytest） |
| GitHub push（commit hash：d1803ef） | ✅ |
| 服务器 git pull | ✅（54f89a5..d1803ef Fast-forward） |
| 服务器 systemctl restart | ✅（is-active = active） |
| 生产 DB 迁移 / 清污 | N/A（纯读取，无 schema 改动） |

## 后续规划

- ETF flow 阈值 5d 仍可能在长周末（圣诞 / 新年）误报 STALE，需要时再调
- 联邦基金利率 45d 阈值在 FOMC 月会议后不变期合理；若 FOMC 改利率，会因 captured_at_utc 推进而恢复"新鲜"
- 项目方向最终落定（退出 AI 判断 / 网页瘦身）后，下个 sprint 才删除 `src/ai/agents/*` 与 `web/assets/app.js` 大块代码

## 工作流教训

- 本次首次走"scp 手改" + "本地 commit"两条线，导致服务器工作树短暂脱离 git 管理
- 收尾时通过 `git diff origin/main` 字节比对、`git checkout -- src/api/app.py` 还原 + `rm src/api/routes/export.py` 后 `git pull` Fast-forward 切回干净状态
- **新硬规则**：以后部署一律 `git pull` + `systemctl restart`，不再 scp 手改

## 残留待清理（不在本 sprint 处理）

服务器 `~/btc_swing_system/` 存在 5 个 .bak 文件（Sprint 54f89a5 sonnet-4-6 切换时 cp 备份），git 未追踪：

```
config/ai.yaml.bak.20260605_171835
src/ai/agents/_base.py.bak.20260605_171835
src/ai/agents/spot_cycle_agents.py.bak.20260605_171835
src/ai/client.py.bak.20260605_171835
src/ai/macro_l5_adjudicator.py.bak.20260605_171835
```

如确认 sonnet-4-6 切换稳定，下次部署可一并 `rm`。
