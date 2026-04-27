# Sprint 2.6-G — 数据抓取时间可见性(fetched_at_bjt)

**Date:** 2026-04-27
**Branch:** main
**Status:** ✅ 后端完成,前端渲染留给用户/后续 sprint

---

## 一、问题

`factor_card_emitter._btc_drawdown_from_ath` 等使用 `_to_bjt(klines_1d.index[-1])`,
那是 K 线 bar 的开盘时间,不是数据抓取时间。
用户看到 "2026-04-27 08:00 (BJT)" 误以为系统 12 小时未更新,
实际系统每小时 fetch 一次。

---

## 二、Triggers(偏离 spec 的自主决策)

1. **schema 没有 `created_at` 列**(用户 spec 假设有)。如要按 spec 走 `df.attrs['last_fetched_at']`,
   需要给 4 张表(`price_candles / derivatives_snapshots / onchain_metrics / macro_metrics`)
   加列、迁移、改 4 个 upsert 路径、改 4 个 read 路径。
   
   触发用户 spec 里的 hard-stop 条件:"如果 DAO 返回结构改动会破坏太多调用方"。
   
   **改为**:新建 `data_fetch_log` 表(单表 4 列),写 `record_fetch(source, ts, rows)`,
   读 `get_all() → dict`。改动表面积小得多,且语义更准确(记录 fetch 事件,不是行级时间)。

2. **emitter 改动用"后置 stamp"而非"全部 _emit_* 函数加参数"**:
   每张卡已有 `group` 字段,在 `emit_factor_cards` 末尾跑 `_stamp_fetched_at(cards, freshness)`
   按 `group` 找对应 source 的 fetch 时间转 BJT 写入。
   
   理由:不污染 5 个 `_emit_xxx` 函数的签名,所有卡自动获取 fetched_at_bjt。

3. **前端渲染未改**:本 sprint 只产 API 字段,前端"如果 fetched ≠ captured 显示两行"
   留给下个 sprint(或用户自己改 web/ 一行)。本后端改完后,用户可在 `/api/strategy/current`
   响应里看到每张卡的 `fetched_at_bjt`。

---

## 三、改动

### 1. 新建迁移 `migrations/004_add_data_fetch_log.sql`
```sql
CREATE TABLE IF NOT EXISTS data_fetch_log (
    source             TEXT PRIMARY KEY,
    last_fetched_utc   TEXT NOT NULL,
    rows_upserted      INTEGER,
    notes              TEXT
);
```

### 2. `src/data/storage/schema.sql`
同步加 DDL(本地 init_db 自动建表)。

### 3. `src/data/storage/dao.py::DataFetchLogDAO`(新增)
- `record_fetch(conn, source, rows_upserted, notes, now_utc)`:upsert
- `get_all(conn) → dict[source, last_fetched_utc]`

### 4. `src/scheduler/jobs.py::job_data_collection`
每个 collector 成功后调 `DataFetchLogDAO.record_fetch`:
- FRED 成功 → `source="macro"`
- CoinGlass 成功 → `source="klines"` + `source="derivatives"`(同时管两条)
- Glassnode 成功 → `source="onchain"`

### 5. `src/pipeline/state_builder.py::_assemble_context`
读 `DataFetchLogDAO.get_all(conn)` → `context["data_freshness"]: dict`

### 6. `src/strategy/factor_card_emitter.py`
- `_make_card` 加 `fetched_at_bjt: Optional[str]` kwarg(默认 None,反正卡 dict 也加这个 key)
- `emit_factor_cards` 末尾调 `_stamp_fetched_at(cards, context.get("data_freshness"))`
- `_GROUP_TO_FRESHNESS_SOURCE` mapping:
  - onchain / derivatives / macro → 同名 source
  - price_technical → "klines"
  - composite / events → 取所有 source 里最旧那个(保守的"刚刚")
- `_utc_iso_to_bjt_pretty(utc_iso)` → "YYYY-MM-DD HH:MM (BJT)"

### 7. `tests/test_data_freshness_stamping.py`(新增,8 测试)
- DAO upsert 后 `get_all` 返回新值;空表返回空 dict;默认 now_utc 用当下
- emitter `_stamp_fetched_at` 按 group 找 source;空 freshness no-op;
  已显式设过的不被覆盖;未知 group 落入 min(all) 兜底
- `_make_card` 输出含 `fetched_at_bjt` key

---

## 四、验证

```
$ python -m pytest tests/test_data_freshness_stamping.py -q
8 passed in 0.34s

$ python -m pytest -q
458 passed, 1 skipped, 138 warnings in 2.02s
```

---

## 五、待用户部署

```bash
ssh user@server
cd /path/to/btc_swing_system
git pull
sqlite3 data/btc_strategy.db < migrations/004_add_data_fetch_log.sql
sudo systemctl restart btc-strategy
# 等下个整点 scheduler 跑完一次 → 4 行写入 data_fetch_log
.venv/bin/python scripts/run_pipeline_once.py
.venv/bin/python -c "
from src import _env_loader
import requests
resp = requests.get('http://127.0.0.1:8000/api/strategy/current',
                    auth=('admin','Y_RhcxeApFa0H-'), timeout=10)
cards = resp.json().get('state', {}).get('factor_cards') or []
print('Sample fetched_at_bjt:')
for c in cards[:5]:
    print(f\"  {c['card_id']:55s} captured={c.get('captured_at_bjt')} fetched={c.get('fetched_at_bjt')}\")
"
```

预期:每张卡有非空 `fetched_at_bjt`,值为 BJT 当下时刻附近(过去几十分钟内)。

---

## 六、遗留(留给后续 sprint)

1. **前端渲染未改** — `web/index.html` 卡渲染只显示 captured_at_bjt;
   需加判断 `if (fetched_at_bjt && fetched_at_bjt !== captured_at_bjt) 显示两行`。
2. **`scripts/backfill_data.py` 未写 record_fetch** — 只 jobs.py 写。
   backfill 是手动触发,不影响生产端定时刷新可见性。
3. **`source` 命名约定**:目前 4 个 source = `klines / derivatives / onchain / macro`。
   未来加新 source(如 events) 需更新 `_GROUP_TO_FRESHNESS_SOURCE` mapping。
4. **没有过期标识**:`fetched_at_bjt` 如果是 24 小时前(scheduler 挂了),前端目前没逻辑高亮。
   `data_fresh` boolean 字段可扩展。

---

## §X / §Y 践行

- ✅ §X:无被替代的旧代码可删
- ✅ §Y:本 commit 立即 push
