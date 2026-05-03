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

### Commit 2:11 个新 API + ThesesDAO.get_by_id + HealthResponse.review_pending + 26 单测
- hash: `d8c2557`
- `src/data/storage/dao.py`:`ThesesDAO.get_by_id` 新加 1 行 SQL(1.10-A DAO 完整性补漏)
- `src/api/models.py`:HealthResponse 加 `review_pending: dict | None`(D2=a)
- `src/api/routes/health.py`:get_health 同 conn 复用查 RP 状态
- `src/api/routes/account.py`(NEW)— current / history / returns 3 个 API
- `src/api/routes/theses.py`(NEW)— active / history / {thesis_id} 3 个 API
- `src/api/routes/orders.py`(NEW)— pending / history 2 个 API
- `src/api/routes/review_weekly.py`(NEW)— latest / history 2 个 API
- `src/api/routes/review_pending.py`(NEW)— POST resolve(D4=b+c Pydantic 校验)
- `src/api/app.py`:5 新 router include
- `tests/test_api_v14_routes.py`(26 单测)

### Commit 3:GET /api/strategy/current 加 4 v1.4 摘要字段(向后兼容)+ 8 单测
- hash: `60e9f55`
- `src/api/routes/strategy.py`:`_build_v14_summaries` 4 字段(account_summary /
  active_thesis / position_summary / pending_orders_summary),`_row_to_model` 加
  `v14_summaries` kwarg 追加到 normalized state(向后兼容)
- 任一摘要失败 → 该字段返 null,前端可降级渲染
- `tests/test_api_strategy_v14_summaries.py`(8 单测,含向后兼容 + 加权均价计算)

### Commit 4:模块 1+2+3(虚拟账户 / thesis 卡 / 挂单状态)+ 27 渲染测试
- hash: `c2ab887`
- `web/index.html`(+223):3 个 audit-card section 插入 region-1 与 region-layer-cards 之间
- 模块 1 含 30 天资金曲线 sparkline(D1=c 纯 SVG `<polyline>`,无 Chart.js)
- `web/assets/app.js`(+87):新 state(virtualAccount / accountReturns / accountHistory /
  activeThesis / positionSummary / ordersPending)+ `_refreshV14Modules` 5 fetch +
  sparklinePoints / formatUsd / distanceFromLive helpers
- 不引入新 JS 库(audit-card / font-mono / 12 卡平铺风格沿用)
- `tests/test_web_modules_1_2_3.py`(27 渲染测试)

### Commit 5:模块 4+5 + RP 红色横幅 + 失败状态显示 + 29 渲染测试
- hash: `cbd8ff2`
- ⚠ 体量观察:459 prod + 280 test = 739 行,**超 500 阈值未拆 5a/5b**。
  原因:`_refreshV14Modules` Promise.all 9 endpoints 共享 fetch lifecycle,
  RP / 失败状态 / 模块 4+5 共享同一 Alpine state — 拆分会重写 fetch 函数两次。
  教训:启动确认时把测试文件量也算进预测(memory feedback_pre_split_commits 更新)
- 模块 4(thesis 时间线):五层 ↓,7 列表
- 模块 5(周复盘):底部,D3=a 下拉切换 12 周 + 23 V 折叠表
- RP 红色横幅(§9.3):sticky top-10,bg-rose-600,数据源 health.review_pending
- RP 解除模态框(D4=b+c):4 EXIT 选 + reason min 10 + disabled until valid
- 失败状态(§9.4):`aiFailureStatus()` 处理 retry_log 5 类(retry_exhausted /
  failed_layers + master + thesis_aware / 仅 master / macro fallback / retry_next)
- `tests/test_web_modules_4_5_rp_failure.py`(29 渲染测试)

### Commit 6:verify_web_modules.py(54 §Z)+ 报告 + 1.10-J/L checklists(本 commit)
- hash: 待 push 后填
- `scripts/verify_web_modules.py` — 9 段共 54 项 §Z 真实断言:
  - A. 11 新 API 200/422/404(11)
  - B. /strategy/current 4 字段扩展 + 向后兼容(7)
  - C. /health.review_pending(D2=a)无/有 active(4)
  - D. POST /resolve EXIT_A 端到端 + system_states.exit_reason 含 user_reason(4)
  - E. web/index.html 5 模块 + RP 横幅 + 失败状态(8)
  - F. 风格硬约束 audit-card / font-mono / 现有 4 region 保留 + sparkline 纯 SVG(8)
  - G. app.js Alpine state + 23 V key 完整 + 5 类失败(5)
  - H. ThesesDAO.get_by_id + /api/theses/{id} API(3)
  - I. StaticFiles 挂载 / 200(2)
  - 加 cleanup pre/post(继承 1.10-H §Z 教训:DELETE WHERE 时间戳 LIKE '2099-%')

---

## 部署四件事 / 测试记录

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ 1483 passed (+90 vs 1.10-H), 1 skipped, 0 regression |
| GitHub push(commit hash) | ✅ commits 1-5 已推:cbd8ff2 / c2ab887 / 60e9f55 / d8c2557 / d3ca00b;commit 6 本次 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行(11 新 API 路由需 uvicorn 重启注册) |
| 生产 DB migration | N/A — 本 sprint 无 migration(纯 API/web 层,DAO/schema 复用 1.10-A → H) |

### §Z verify 真实运行结果

```
$ .venv/bin/python scripts/verify_web_modules.py
通过:54 项
失败:0 项
✅ 全部通过
```

### 单元测试矩阵

| 测试文件 | 单测数 | 覆盖 |
|---|---|---|
| `tests/test_api_v14_routes.py` | 26 | commit 2 — 11 新 API + DAO + health.review_pending |
| `tests/test_api_strategy_v14_summaries.py` | 8 | commit 3 — 4 字段 + 向后兼容 + 加权均价 |
| `tests/test_web_modules_1_2_3.py` | 27 | commit 4 — 模块 1+2+3 渲染 + Alpine state |
| `tests/test_web_modules_4_5_rp_failure.py` | 29 | commit 5 — 模块 4+5 + RP + 失败状态 |
| **小计** | **90** | 1.10-I 全覆盖 |

### 浏览器验证(用户手动)

部署后浏览器打开应看到:
- 顶部全局横幅(若 active RP 时)红色 + "解除" 按钮 → 点击弹出 4 选模态框
- 5 个新 audit-card section(虚拟账户 / thesis 卡 / 挂单状态 / thesis 时间线 / 周复盘)
- 模块 1 资金曲线 sparkline(SVG polyline,简洁灰色趋势线)
- 模块 5 23 V 折叠表(<details> 默认关闭,点击展开)
- 失败状态橙色提示(若 retry_log_json 含失败标记)

---

## 未覆盖 / 留 1.10-J/L 处理

### 1.10-J 累积清单(本 sprint 不动,继承 + 新增)

| # | 留 1.10-J 项 | 来源 sprint |
|---|---|---|
| 1 | `AlertsDAO` 重构(裸 INSERT 多处) | 1.10-H |
| 2 | `events_calendar.triggered_at_utc` migration 路径迁主 schema.sql | 1.10-G/H |
| 3 | 1.10-G verify event_macro 报错(同 #2 根因) | 1.10-G |
| 4 | (本 sprint 新增)`ThesesDAO.get_by_id` — 统一 DAO 重构时 review | 1.10-I |

### 1.10-L 留处理(真用户 + 真 API 验证)

| # | 项 | 验证场景 |
|---|---|---|
| 1 | 真用户测试 RP 模态框 4 选(A/B/C/D)+ reason 输入流 | 用户在浏览器实际操作 |
| 2 | sparkline 在真生产 30 天 snapshots 数据下渲染美观度 | 真生产数据 |
| 3 | 周复盘 23 V 折叠表在真 weekly_review_analyst 输出下结构化展示 | 真 API |
| 4 | 失败状态 5 类文本在真 retry_log_json 5 种场景下准确触发 | 真生产 retry 触发 |
| 5 | 移动端响应式布局(本 sprint 仅做 grid-cols-2/3/6 桌面适配,移动端未测) | 浏览器 mobile mode |
| 6 | dark mode 与新模块兼容性(本 sprint 沿用现有 dark: prefix) | 浏览器切换 dark/light |

### v1.4 §11.3 路径错误清单(继承,本 sprint 无新增)

| # | v1.4 §11.3 文档路径 | 真实路径 | 发现 sprint |
|---|---|---|---|
| 1 | `src/ai/adjudicator.py` | `src/ai/agents/master_adjudicator.py` | 1.10-D |
| 2 | `src/decision/validator.py` | `src/ai/validator.py` | 1.10-E |

---

## 本 sprint 删除清单

本 sprint **纯新增**:5 新 API 路由 + 5 新 web 模块 + RP 横幅 + 失败状态显示 +
ThesesDAO.get_by_id + HealthResponse.review_pending 字段。

| # | 删除/修改 | 说明 |
|---|---|---|
| 1 | (无删除) | 现有 12 卡 + 五层分析 6 卡 100% 保留(test_existing_regions_preserved 验证) |
| 2 | (修改:HealthResponse 加字段) | 向后兼容(原字段不动,前端旧版会忽略 review_pending) |
| 3 | (修改:GET /api/strategy/current 加 4 字段) | 向后兼容(state dict 追加,原字段不动 — test_current_does_not_break_existing_state_fields 验证) |

§X 老代码清理留 1.10-J(AlertsDAO 重构 + events_calendar.triggered_at_utc 路径)。

**自检清单**(commit 6 前 CC 已跑):
- [x] 1483 pytest 0 regression
- [x] 54 §Z 全过
- [x] git grep `account_summary` / `active_thesis` / `position_summary` / `pending_orders_summary` 调用方齐
- [x] git grep `reviewPending` Alpine 用法一致(modal + banner + state)
- [x] 11 新 API 都注册在 src/api/app.py
- [x] 风格硬约束:无 Chart.js / D3 / lightweight-charts 引入

---

## 段 4 — 报告路径

详细报告:`docs/cc_reports/sprint_1_10_i.md`
