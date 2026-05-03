# Sprint 1.10-I:网页加 5 模块 + review_pending 红色横幅 + 失败状态显示

**对齐文档**:`docs/modeling.md` v1.4(commit `b25cfe6`)§9.1-§9.5
**Sprint 路径定位**:v1.4 §10.5 第九行 — 1.5 天工作量
**前置 sprint**:1.10-A → 1.10-H 全部完成(HEAD 在 f1c0613)

---

## Triggers / 决策记录

### 启动确认 4 个 D + 1 个 DAO 补漏 用户拍板

- **D1 = c**:30 天资金曲线用纯 SVG sparkline(<polyline>)。前端 Alpine 模板直接生成,
  不引入 Chart.js / D3 等新依赖。数据来自 `GET /api/account/history?days=30`。
- **D2 = a**:`GET /api/system/health` HealthResponse 加 `review_pending: dict | None` 字段
  (active / reason / entered_at_utc / state_id)。健康灯组件复用,RP 红色横幅一个 fetch。
- **D3 = a**:周复盘默认显示最新 + 下拉切换历史 12 周。`/history?limit=12` 一次返完整
  output_json(~36KB 可接受,避免 N+1 query)。
- **D4 = b+c 组合**:POST `/api/review_pending/resolve` body =
  `{exit_type, reason(min 10 chars), new_thesis_spec?, new_thesis_id?}`。
  后端校验 exit_type 枚举 + reason 长度,失败 422。前端 Alpine 模态框二次确认。
- **DAO 补漏**:`ThesesDAO.get_by_id` 1 行 SQL 新加(commit 2),1.10-A DAO 完整性补漏。

### 节奏

完全放手模式(用户授权一次性跑完 6 commits;commit 4/5 < 500 行预测,超了现场拆)。

---

## 调研 — 现状对照

### 已存在(1.10-A → H + Sprint 2.x 实施)

| 项 | 文件:行 | 状态 |
|---|---|---|
| `web/index.html` | 579 行 | Alpine.js x-data + Tailwind CDN + audit-card 6 处 |
| `web/assets/styles.css` | 75 行 | `.audit-card` / `.dark .audit-card` / `.stat-label` / `.subheading` |
| `web/assets/app.js` | 662 行 | Alpine app() 函数 + state |
| `src/api/app.py:127-138` | — | 11 个 router include + StaticFiles 挂 web/ |
| `src/api/routes/strategy.py:124` | — | `GET /current` 现有,response_model=StrategyStateRow |
| `src/api/routes/health.py:15` | — | `GET /health` HealthResponse |
| `StrategyStateRow.state: dict[str, Any]` | `src/api/models.py:34` | 任意 dict — 4 字段扩展不需改 model schema |
| 1.10-A → H 全套 DAO | `src/data/storage/dao.py` | VirtualAccountDAO / VirtualOrdersDAO / ThesesDAO 接口齐 |
| `src/strategy/virtual_account.py:184` | — | `compute_returns_history` 已实现 |
| `src/strategy/review_pending.py` | — | `is_in_review_pending` / `exit_a/b/c/d_thesis_resumed` |

### v1.4 期望但缺失(本 sprint 新建)

- ❌ 5 个新 API 路由文件(account / theses / orders / review_weekly / review_pending)
- ❌ `ThesesDAO.get_by_id`(1 行 SQL,commit 2 补)
- ❌ `HealthResponse.review_pending` 字段(D2=a,commit 2 加)
- ❌ `web/index.html` 5 个新 section(模块 1-5)
- ❌ `web/assets/app.js` 新 state + fetch 新 API(模块 1-5 数据加载)
- ❌ RP 红色横幅 + 失败状态显示(commit 5)
- ❌ Sparkline SVG 组件(commit 4 模块 1)
- ❌ POST `/api/review_pending/resolve`(commit 2)

### 1.10-J 累积清单 declare(本 sprint 不动)

| # | 留 1.10-J 项 | 来源 sprint |
|---|---|---|
| 1 | `AlertsDAO` 重构(裸 INSERT 多处) | 1.10-H |
| 2 | `events_calendar.triggered_at_utc` migration 路径迁主 schema.sql | 1.10-G/H |
| 3 | 1.10-G verify event_macro 报错(同 #2 根因,3 项一起修) | 1.10-G |
| 4 | (本 sprint 新增)`ThesesDAO.get_by_id` 加,统一 DAO 重构时 nicely 纳入 review | 1.10-I |

### v1.4 §11.3 路径错误清单(继承 1.10-D/E,本 sprint 无新增)

| # | v1.4 §11.3 文档路径 | 真实路径 | 发现 sprint |
|---|---|---|---|
| 1 | `src/ai/adjudicator.py` | `src/ai/agents/master_adjudicator.py` | 1.10-D |
| 2 | `src/decision/validator.py` | `src/ai/validator.py` | 1.10-E |

---

## 任务 1-11 实施记录(commit-by-commit 实时填)

### Commit 1:报告骨架 + 调研 + 1.10-J 清单 declare(本 commit)
- hash: 待 push 后填
- `docs/cc_reports/sprint_1_10_i.md`(本文件)
- 无代码改动(纯 declare + 调研)

### Commits 2-6:待执行

---

## 部署四件事 / 测试记录(commit 6 末尾填)

待 commit 6 完成。

## 本 sprint 删除清单(commit 6 末尾汇总)

本 sprint **纯新增**:5 新 API 路由 + 5 新 web 模块 + RP 横幅 + 失败状态显示。
现有 12 卡 + 五层分析 6 卡 + GET /api/strategy/current 现有字段 100% 保留(向后兼容)。
