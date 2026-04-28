# Sprint 2.8-A — factor_cards 实时刷新

**Date:** 2026-04-28
**Branch:** main
**Status:** ✅ 完成,11 个新测试 + 35 个相关回归全过

---

## 一、问题与决策

**Bug**:`/api/strategy/current` 读 `strategy_state_history` 最新一行的
`factor_cards` 字段。该字段是 `pipeline_run`(每 4h)生成的快照,
所以网页"抓取于"显示的是 4h 前的旧时刻,即便 collector 5 分钟前刚抓了新数据。

**用户决策(spec 中已建议)**:
- **Decision 1 = (a)** strategy_state_history 仍写 factor_cards 列(历史归档),
  前端不再读它
- **Decision 2 = (a)** latest_factor_cards 单行(`PRIMARY KEY DEFAULT 1 CHECK (id=1)`),
  覆盖更新

---

## 二、改动

### 2.1 新建表 + 列
- `latest_factor_cards(id PK=1, cards_json, refreshed_at_utc)` — 单行覆盖

### 2.2 新建文件
- `migrations/007_add_latest_factor_cards.sql` — 全新 DB 用
- `src/strategy/factor_cards_refresher.py` — 核心 refresh 函数
- `tests/test_factor_cards_refresher.py` — 11 测试
- 本报告

### 2.3 改动文件
- `src/data/storage/schema.sql`:加 latest_factor_cards 表 DDL
- `src/data/storage/dao.py`:新增 `LatestFactorCardsDAO.upsert / get_latest`
- `scripts/migrate_2_7_d.py`:扩展为同时跑 2.7-D + 2.8-A 迁移(idempotent)
- `src/scheduler/jobs.py`:
  - `_wrap_job` 新增 kwarg `refresh_cards_on_success=False`
  - 5 个 collector(klines_1h / daily / weekly / macro / onchain)成功后调
    `refresh_factor_cards(conn)`,失败只 log warning
- `src/api/routes/strategy.py::_get_current_impl`:读 strategy_runs 后,
  用 `LatestFactorCardsDAO.get_latest` 覆盖 `state.factor_cards`,
  并在 `state.meta.factor_cards_refreshed_at_utc` 写诊断字段。
  latest_factor_cards 表为空时退回 strategy_state_history 的快照。
- `web/index.html`:footer 文本从 "由 X 生成" 改为 "**AI 输出于** YYYY-MM-DD HH:MM (BJT) · model"
  明确与因子卡片"抓取于"区分

---

## 三、refresh_factor_cards 流程

```
collector job 成功(status='ok')
   └─→ _wrap_job 调 refresh_factor_cards(conn)
         ├─ StrategyStateBuilder._assemble_context(conn) → fresh context
         │   (含最新 metric_inserted_at,Sprint 2.6-J 起带秒级精度)
         ├─ StrategyStateDAO.get_latest_state(conn)
         │   → 取上次 pipeline_run 完整 state(composite + evidence_reports 缓存,不重算)
         ├─ emit_factor_cards(last_state, fresh_context)
         │   → 卡片的 captured_at_bjt + fetched_at_bjt 用最新值;
         │     composite/evidence 字段用上次 pipeline 的快照
         └─ LatestFactorCardsDAO.upsert(conn, cards, refreshed_at_utc=now)
```

**5 层证据 / 6 组合 / AI 仍只在 pipeline_run 跑**(2.7-A cron 6 次/天)。
refresh 是轻量级的 — 只做数据查询 + emitter 渲染,不跑 AI 也不算 evidence。

---

## 四、测试

`tests/test_factor_cards_refresher.py`(11 测试):
- DAO upsert/read/单行覆盖/空读(3)
- refresh_factor_cards e2e:写入 + 时间戳精确性 + emit 失败时降级(2)
- 5 个 collector 任一调用都触发 refresh:
  - klines_1h 成功 → DB row 出现 + result.factor_cards_refresh.refreshed=True
  - macro 成功 → 同上
  - macro skipped(无 FRED key)→ 不调 refresh
  - refresh 内部异常 → collector 仍 status='ok',factor_cards_refresh 含 error
- API e2e:
  - latest_factor_cards 有内容 → 覆盖 strategy_state.factor_cards
  - latest_factor_cards 空 → 退回 strategy_state_history 快照(冷启动友好)

35 个相关回归(scheduler + events + state_builder + api + factor_cards_refresher)全过。

---

## 五、用户验证脚本(SSH 部署后)

```bash
ssh ubuntu@124.222.89.86 << 'SSH'
cd /home/ubuntu/btc_swing_system
git pull

# 1. 跑迁移(idempotent;2.7-D + 2.8-A 共用同一脚本)
.venv/bin/python scripts/migrate_2_7_d.py
# 预期输出:event_throttle_table: ok / triggered_at_utc_column: skipped /
#          latest_factor_cards_table: ok

# 2. 重启服务
sudo systemctl restart btc-strategy.service
sleep 5

# 3. 等 1 个整点 collector_klines_1h 跑完(:00)
# 然后查 latest_factor_cards 表
sqlite3 data/btc_strategy.db <<EOF
SELECT
  refreshed_at_utc,
  json_array_length(cards_json) AS card_count
FROM latest_factor_cards;
EOF
# 预期:refreshed_at_utc 是当下整点 + 几秒(秒级精度)

# 4. curl /api/strategy/current,看 factor_cards 时间戳
curl -s -u admin:Y_RhcxeApFa0H- http://127.0.0.1:8000/api/strategy/current | \
  python3 -c "
import json, sys
s = json.load(sys.stdin)['state']
print('factor_cards_refreshed_at_utc:', s['meta'].get('factor_cards_refreshed_at_utc'))
sample = next(c for c in s['factor_cards']
              if 'derivatives_funding_rate_current' in c.get('card_id', ''))
print('Sample card fetched_at_bjt:', sample.get('fetched_at_bjt'))
"

# 5. 浏览器硬刷新 → 衍生品卡片"抓取于"应显示当下整点附近;
#    底部 footer 应是 "AI 输出于 HH:MM (BJT) · model"(上次 pipeline_run 时间)
SSH
```

---

## 六、§X / §Y / §Z + 同类风险扫描

### §X
- frontend "由 X 生成" 文本改为"AI 输出于 X · model"(语义更明确,删除了模糊的"由...生成")
- migrations/006 + 007 共用 `scripts/migrate_2_7_d.py` runner — 没新建独立的 migrate_2_8_a 脚本,避免脚本爆炸
- strategy_state_history.factor_cards 字段保留(decision 1 = a),不算 §X 违反 — 字段仍被 review_reports 等历史归档读

### §Y
本 commit 立即 push。

### §Z 端到端断言
- 真 SQLite + 真 emit_factor_cards + DB COUNT(*) == 1 + cards_json 解析后是 list + refreshed_at_utc 在 now ± 1s
- API e2e 用 TestClient + 真 DAO + 断言 fresh card_ids 含 "FRESH_*",老 card_ids "OLD" 不再出现

### 同类风险扫描
1. **refresh 在 collector 失败时不调用** — 已通过 `if result.get("status") == "ok"` 显式守护;skipped status 也不触发(避免空数据写入)
2. **refresh 自身异常** — 包了 try/except,collector 仍返回 ok + 在 result["factor_cards_refresh"] 写 error
3. **emit_factor_cards 读上次 strategy_run 的 state** — 如果 strategy_state_history 表为空(全新部署),`last_state={}`,emit 仍能渲染基础卡片(空 composite 字段会显示"数据不足")
4. **API endpoint /strategy/stream(SSE)未更新** — 它只在 `run_id` 变化时推送整个 state,推送的 factor_cards 仍是 strategy_state_history 的旧快照。**遗留**:下次 sprint 让 SSE 也用 latest_factor_cards 覆盖。当前 SSE 不是主路径,影响有限
5. **factor_cards JSON 体积** — 单行覆盖,~50 张卡 × ~500 字节 = ~25KB,SQLite TEXT 列轻松吞下
6. **race condition**:event_listener 60s tick 期间 refresh 同时触发同一个 conn(单 sqlite 连接是 serial)— APScheduler `max_instances=1` 控制单 job;5 collector 不互斥但每个用独立 conn,不冲突

---

## 七、部署 checklist

- [ ] git pull
- [ ] `.venv/bin/python scripts/migrate_2_7_d.py`(创建 latest_factor_cards 表)
- [ ] `sudo systemctl restart btc-strategy.service`
- [ ] 等 1 个 collector tick(下个整点)
- [ ] curl + 浏览器硬刷新验证
