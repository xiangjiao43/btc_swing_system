# Sprint 1.1 — `src/data/storage/`(SQLite 存储层)

**日期**:2026-04-23
**Sprint**:1.1(数据存储基础)
**对应建模文档章节**:§3.2(M29 时序契约)、§3.11(数据目录规范)、§8.5(监控告警)、§10.4(DB schema)

---

## ⚠️ Triggers for Human Attention

> 以下是本次任务需要人类注意的决策点,可直接摘录给审阅者。

### 1. `uv sync` 已执行,首次安装了全部依赖并生成 `uv.lock`

本次是项目第一次真正安装 Python 依赖(之前几批只是登记到 pyproject.toml)。`uv sync` 执行后:
- 创建了 `.venv/`(已被 `.gitignore` 忽略)
- 生成了 `uv.lock`(**会进入本批 commit**;lock 文件应入库以保证环境可复现)
- 安装了 20+ 依赖(pandas / numpy / pydantic / pyyaml / requests / fastapi / uvicorn / apscheduler / pytest + 递归依赖)

**需要人类注意**:
- `uv.lock` 第一次入库,以后每次改 `pyproject.toml` 依赖都要重跑 `uv sync` 更新 lock 再提交
- 你当前 shell 可能有残留的 `VIRTUAL_ENV` 环境变量指向 `/Library/Developer/CommandLineTools/.../Python3.9`,会让 uv 报 warning 并尝试用不兼容的 Python。**建议在 `~/.zprofile` 里 `unset VIRTUAL_ENV`**,或每次开 Terminal 先执行 `unset VIRTUAL_ENV`
- `uv run` 默认用项目 `.venv/`(Python 3.12),所有校验都是在 3.12 下跑通的

### 2. SQLite 表结构与建模文档 §10.4 **有结构性差异**,我按本次任务定义优先

建模 §10.4 原始 SQL(节选)用的是:
- `price_candles`(symbol + timeframe + open_time_utc 三主键,单列 volume)
- `derivatives_snapshots`(时间主键 + 固定列 funding_rate / open_interest / long_short_ratio + full_data_json)
- `onchain_metrics`(metric + time 长表)

**本批实现**(按你本次任务定义):
- `btc_klines`(timeframe + timestamp 两主键,拆 volume_btc / volume_usdt)
- `derivatives_snapshot`(timestamp + metric_name **长表**;建模原版是宽表)
- `onchain_snapshot`(长表,加 source ∈ {glassnode_primary/display/delayed})
- `macro_snapshot`(长表,加 source ∈ {yahoo_finance/fred})

**差异的权衡**:
- **长表优势**(本批选择):新增指标不改表结构;查询单一指标更快;与 data_catalog.yaml 的逐因子注册思路一致
- **宽表优势**(建模原版):查询"某时刻的所有衍生品"只需一次 SELECT;结构直观
- **后果**:如果后续 v1.0 上云要改回宽表以契合建模原版,需要迁移脚本

**结论**:本批实现与你的任务定义一致,但与建模 §10.4 略有偏离。如果你希望严格对齐建模,说一声我改回宽表。

### 3. `btc_klines` 表没有 `symbol` 列(建模原版有)

本批假设"系统只交易 BTC",所以省了 `symbol` 列,节省索引空间与查询复杂度。如果未来要扩展到 ETH 等多标的,需要加列 + 改主键为 `(symbol, timeframe, timestamp)`。

### 4. `DATABASE_URL` 的 `.env` 条目**目前没被 `get_db_path()` 消费**

`.env.example` 里有 `DATABASE_URL=sqlite:///data/btc_strategy.db`,但 `connection.py.get_db_path()` 只读 `config/base.yaml → paths.db_path`。

**原因**:统一的 .env 解析器还没实现(需要 python-dotenv 之类);如果现在读环境变量,两个来源(base.yaml 和 .env)的优先级规则要定义,我不想在本次 scope 里拍。

**处理**:注释里标了"`.env` 的 DATABASE_URL 被设置为 sqlite:/// 形式,暂不在此解析"。后续做 config loader 时统一处理。

### 5. `run_id` 在 `run_metadata` 和 `strategy_state_history` 之间的关系未强制

两个表都有 `run_id`,语义上同一个 run_id 应该先在 run_metadata 里 started,最后在 strategy_state_history 里归档。**但没有外键约束**(因为 `strategy_state_history` 的主键是 `run_timestamp_utc`,不是 `run_id`)。

**原因**:外键会要求 run_metadata 先写入才能写 state_history,而实际流程中两者写入时序可能交错(特别是 Fallback 场景)。

**对应建议**:src/scheduler/ 或 src/strategy/ 里写一个 `RunContext` 类统一管理 run_id 生命周期,显式调用 `start_run / insert_state / finish_run`,避免孤儿记录。

### 6. DAO 的三个长表共用父类 `_MetricLongTableDAO`

`DerivativesDAO` / `OnchainDAO` / `MacroDAO` 有大量重复逻辑(upsert / get_at / get_latest / get_series),我抽出了一个**私有**父类 `_MetricLongTableDAO`,通过类变量 `_table` / `_has_source` 差异化。

**权衡**:
- **好处**:600+ 行 dao.py 里三个类每个只有 3 行
- **坏处**:类型检查器对 classmethod 继承 + 子类没重写的情况有时会报 "cannot infer type" 警告

如果 IDE 静态类型提示不满意,未来可以用 ABC + 泛型或显式重写每个方法。

### 7. Row dataclasses(KlineRow / DerivativeMetric 等)是 slots=True

用 `@dataclass(slots=True)` 是 Python 3.10+ 特性,实例化更快且内存占用更少。Sprint 1 里大量 K 线数据通过 dataclass 进入 upsert,这点性能有意义。

---

## 1. 产出概览

| 文件 | 行数 | 大小 | 作用 |
|---|---|---|---|
| `src/data/storage/schema.sql` | 175 | 8.2 KB | 9 表 + 22 索引 SQL DDL |
| `src/data/storage/connection.py` | 104 | 3.2 KB | get_db_path / get_connection / init_db |
| `src/data/storage/dao.py` | 621 | 20.3 KB | 5 row dataclasses + 9 DAO 类 |
| `src/data/storage/__init__.py` | 62 | 1.1 KB | 公共 API 暴露 |
| `uv.lock` | — | ~1 MB | 首次生成 |

### 9 张表 + 22 个索引验证结果

```
tables (9 user + sqlite_sequence):
  btc_klines:            9 cols, 2 idx
  derivatives_snapshot:  4 cols, 2 idx
  events_calendar:       9 cols, 3 idx
  fallback_log:          6 cols, 3 idx
  macro_snapshot:        5 cols, 2 idx
  onchain_snapshot:      5 cols, 2 idx
  review_reports:        5 cols, 2 idx
  run_metadata:          7 cols, 2 idx
  strategy_state_history: 7 cols, 4 idx
total user indices: 22
```

### DAO 端到端烟测结果(已通过)

```
  klines count 1d: 2
  latest 1d close: 65800.0 at 2026-04-21T00:00:00Z
  deriv row count: 2 ; sample: funding_rate = 0.0001
  onchain latest mvrv_z: 2.1
  next event after 2026-04-25: FOMC_decision at 2026-05-06T18:00:00Z
  latest state action: FLAT
  state json roundtrip ok
  consecutive level_1: 2
  run status: completed
SMOKE TEST PASS
```

---

## 2. 架构决策

### 2.1 为什么用长表(long format)存衍生品/链上/宏观

**长表**(timestamp + metric_name 主键,每条一个值)vs **宽表**(timestamp 主键,每列一个指标)。本批选长表:

1. **扩展性** — 新增指标不改表。data_catalog.yaml 的 single_factors 今后会持续增长
2. **稀疏性** — 某指标可能不是每个 timestamp 都有(例如 Glassnode delayed 档只偶尔抓),长表不 NULL fill
3. **查询语义** — `get_series(metric_name, start, end)` 是最高频操作,长表天然高效(metric_name 索引)
4. **一致性** — 与建模文档的"因子目录 + 每因子独立"思路一致

代价是"给定时刻的所有指标"查询要 `GROUP BY timestamp + pivot`,略繁琐,但这是低频操作。

### 2.2 为什么所有时间戳用 TEXT 而非 INTEGER

- 人读方便,调试/导出 CSV 可直接看
- SQLite 比较 ISO 8601 字符串与比较 INTEGER 同等高效(词典序与时间序一致)
- 与 `scenario_notes.md` / `schemas.yaml` 的格式一致,减少转换

### 2.3 为什么 state_json / report_json 用 TEXT 存 JSON 而非多列展开

- StrategyState 有 12 业务块共 ~100+ 字段,展开成列会让表 schema 爆炸
- JSON1 extension(SQLite 默认启用)可 `SELECT json_extract(state_json, '$.block_4.action_state')` 查子字段,灵活够用
- schema 演进时不用 ALTER TABLE,直接改 Pydantic model

顶层列(run_timestamp_utc / run_id / run_trigger / rules_version / ai_model_actual)是为了"按规则版本筛选"等常见过滤做了反规范化。

---

## 3. 自主决策汇总

| 编号 | 决策 | 理由 |
|---|---|---|
| A | 9 张表按任务定义,与建模 §10.4 略有不同 | 任务定义更契合 data_catalog 长表思路 |
| B | 所有时间戳 TEXT ISO 8601 | 可读性 + 词典序可比 |
| C | Row dataclasses 用 `slots=True` | Python 3.10+ 特性,实例化更快 |
| D | DAO 方法全部 `@staticmethod`,显式传 conn | 事务控制权在调用方;便于测试注入 |
| E | 抽私有父类 `_MetricLongTableDAO` | 三个长表去重,600 行变 200 行 |
| F | `DATABASE_URL` env 暂不消费 | 优先级规则未定;base.yaml 优先 |
| G | `get_db_path()` 从仓库根推导 | 4 层 parent,代码稳定 |
| H | state_json / report_json 用 TEXT | 12 业务块展开成列会爆炸 |
| I | `FallbackLogDAO.count_consecutive_level_1_ending_at` | 直接封装"M33 连续 5 次升级"的查询 |
| J | `init_db(verbose=True)` 打印表/索引统计 | 用户首次验证时看到建了啥 |
| K | 烟测后删除测试 DB | 留个干净状态给用户自己验证 |

---

## 4. 用户验证路径

按你的任务描述,请执行:

```bash
cd ~/Projects/btc_swing_system
unset VIRTUAL_ENV   # 避免 Xcode Python 3.9 干扰
uv run python -c "from src.data.storage import init_db; init_db()"
```

预期输出:

```
[init_db] db_path = /Users/xuanmingfeng/Projects/btc_swing_system/data/btc_strategy.db
[init_db] tables (10): btc_klines, derivatives_snapshot, events_calendar, fallback_log,
          macro_snapshot, onchain_snapshot, review_reports, run_metadata,
          sqlite_sequence, strategy_state_history
[init_db] user indices: 22
```

然后可以用任意 SQLite 浏览器(或 `sqlite3 data/btc_strategy.db`)看表结构。

---

## 5. 下一步 Sprint 1.2 候选

按建模 §10.5 的 v0.1 目标"数据管道通(币安 K 线 + 资金费率),L1+L2 规则",下一步候选:

- **Sprint 1.2a**:`src/common/config.py` — 统一的 base.yaml / thresholds.yaml / schemas.yaml 加载器(替代当前在 connection.py 里的 hardcode 路径)
- **Sprint 1.2b**:`src/data/proxy_client.py` — 中转站 HTTP 请求封装(带 retry / rate_limit / 新鲜度追踪)
- **Sprint 1.2c**:`src/data/collectors/binance.py` — 第一个真实 collector,测通"Binance API → SQLite" 链路

建议顺序:先 1.2a(config loader,所有模块要用),再 1.2b(network 层),再 1.2c(第一个真实 collector)。

---
