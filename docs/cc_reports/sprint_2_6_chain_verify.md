# Sprint 2.6 D.1 + F + G + E — 一站式部署 + 验证脚本

**Date:** 2026-04-27
**适用 commits:** `cd5666b` (D.1) → `0c05dca` (E)

---

## A. 部署(服务器一次性跑)

```bash
ssh user@124.222.89.86
cd /path/to/btc_swing_system
git pull

# Sprint 2.6-G:新增 data_fetch_log 表
sqlite3 data/btc_strategy.db < migrations/004_add_data_fetch_log.sql

# Sprint 2.6-F:拉黄金 365d 历史(GOLDPMGBD228NLBM)+ funding_rate_aggregated
.venv/bin/python scripts/backfill_data.py --only macro --days 365
.venv/bin/python scripts/backfill_data.py --only derivatives --days 7

# 重启:触发 Sprint 2.6-D.1 的 events seed startup hook
sudo systemctl restart btc-strategy
sleep 5

# 触发一次 pipeline 跑 → 写 fetch_log + 跑 L5 AI(若 OPENAI_API_KEY 在)
.venv/bin/python scripts/run_pipeline_once.py 2>&1 | tail -10
```

---

## B. 一站式验证脚本(贴到服务器跑)

```bash
.venv/bin/python << 'EOF'
"""验证 Sprint 2.6-D.1 + F + G + E 全部生效。"""
from src import _env_loader
import requests
import sqlite3
from pathlib import Path

print("=" * 70)
print("Sprint 2.6 D.1 + F + G + E 验证")
print("=" * 70)

# === D.1: events_calendar 已 seed ===
print("\n--- [D.1] events_calendar 已 seed ---")
conn = sqlite3.connect("data/btc_strategy.db")
cur = conn.cursor()
cur.execute("SELECT COUNT(*) FROM events_calendar")
n_events = cur.fetchone()[0]
print(f"  events_calendar 行数: {n_events}  {'✅' if n_events >= 10 else '❌ 期望 >= 10'}")
cur.execute("""SELECT event_id FROM events_calendar
               WHERE event_type='fomc' AND date LIKE '2026-04%'""")
apr_fomc = cur.fetchone()
print(f"  Apr FOMC:  {apr_fomc[0] if apr_fomc else '❌ 缺失'}")

# === F: 5 个数据缺失补全 ===
print("\n--- [F] 数据缺失补全 ---")
# 1. Glassnode lth/sth realized + sopr_adjusted
for metric in ("lth_realized_price", "sth_realized_price", "sopr_adjusted"):
    cur.execute("SELECT COUNT(*) FROM onchain_metrics WHERE metric_name=?",
                (metric,))
    n = cur.fetchone()[0]
    print(f"  Glassnode {metric:25s}: {n} 行  {'✅' if n > 0 else '❌'}")
# 2. CoinGlass funding_rate_aggregated(extras 里)
cur.execute("""SELECT COUNT(*) FROM derivatives_snapshots
               WHERE full_data_json LIKE '%funding_rate_aggregated%'""")
n_fra = cur.fetchone()[0]
print(f"  CoinGlass funding_rate_aggregated: {n_fra} 行  {'✅' if n_fra > 0 else '❌'}")
# 3. FRED gold_price
cur.execute("SELECT COUNT(*) FROM macro_metrics WHERE metric_name='gold_price'")
n_gold = cur.fetchone()[0]
print(f"  FRED gold_price:            {n_gold} 行  {'✅' if n_gold > 0 else '❌'}")

# === G: data_fetch_log 有数据 ===
print("\n--- [G] data_fetch_log ---")
cur.execute("SELECT source, last_fetched_utc FROM data_fetch_log")
fetch_rows = cur.fetchall()
if fetch_rows:
    for src, ts in fetch_rows:
        print(f"  {src:15s} last={ts}  ✅")
else:
    print("  ❌ data_fetch_log 空(scheduler 未跑过 / 表未建)")

conn.close()

# === API: L5 AI + factor cards fetched_at_bjt + EventRisk + BTC-gold ===
print("\n--- API /api/strategy/current ---")
try:
    r = requests.get("http://127.0.0.1:8000/api/strategy/current",
                     auth=("admin", "Y_RhcxeApFa0H-"), timeout=15)
    s = r.json().get("state", {})

    # E: L5 AI
    print("\n[E] L5 §6.8 Output")
    l5 = (s.get("evidence_reports") or {}).get("layer_5") or {}
    method = l5.get("computation_method")
    print(f"  computation_method:        {method}  "
          f"{'✅ ai_assisted' if method == 'ai_assisted' else '⚠️ rule_based(检查 OPENAI_API_KEY)'}")
    print(f"  macro_stance:              {l5.get('macro_stance')}")
    print(f"  macro_trend:               {l5.get('macro_trend')}")
    print(f"  macro_headwind_score:      {l5.get('macro_headwind_score')}")
    guidance = l5.get("adjustment_guidance") or {}
    print(f"  adjustment_guidance.position_cap_multiplier: "
          f"{guidance.get('position_cap_multiplier')}")
    print(f"  adjustment_guidance.permission_adjustment:    "
          f"{guidance.get('permission_adjustment')}")

    # E: L5 → L4 loopback audit
    print("\n[E] L4 position_cap loopback audit")
    l4 = (s.get("evidence_reports") or {}).get("layer_4") or {}
    comp = l4.get("position_cap_composition") or {}
    if comp.get("l5_ai_override_applied"):
        print(f"  l5_ai_override_applied:  True  ✅")
        print(f"  macro_headwind_score_source: {comp.get('macro_headwind_score_source')}")
        print(f"  step 4 multiplier (pre→post AI): "
              f"{comp.get('l5_macro_headwind_multiplier_pre_ai')} → "
              f"{comp.get('l5_macro_headwind_multiplier')}")
    else:
        print(f"  l5_ai_override_applied:  False  ⚠️ (AI 未启用或失败)")
    print(f"  final position_cap_pct: {l4.get('position_cap_pct')}%")

    # G: factor cards fetched_at_bjt
    print("\n[G] factor cards fetched_at_bjt 抽查")
    cards = s.get("factor_cards") or []
    samples = [c for c in cards if c.get("group") in
               ("onchain", "derivatives", "price_technical", "macro")][:4]
    for c in samples:
        print(f"  {c['card_id']:55s} captured={c.get('captured_at_bjt')} "
              f"fetched={c.get('fetched_at_bjt')}")

    # F: BTC-gold + EventRisk
    print("\n[F] BTC-gold 60d corr + EventRisk")
    gold_card = next((c for c in cards
                      if "btc_gold_corr_60d" in c.get("card_id", "")), None)
    if gold_card:
        v = gold_card.get("current_value")
        print(f"  BTC-gold 60d corr:     {v}  "
              f"{'✅' if v is not None else '⚠️ 数据不足或未抓取'}")
    er = (s.get("composite_factors") or {}).get("event_risk") or {}
    print(f"  EventRisk score:       {er.get('score')}  band={er.get('band')}")
    contrib = er.get("contributing_events") or []
    if contrib:
        print(f"  EventRisk top event:   {contrib[0].get('name')} "
              f"(hours_to={contrib[0].get('hours_to'):.1f if contrib[0].get('hours_to') else 'n/a'})")

except Exception as e:
    print(f"  ❌ API 调用失败: {e}")

print("\n" + "=" * 70)
print("验证结束")
print("=" * 70)
EOF
```

---

## C. 期望输出汇总(参考)

```
[D.1] events_calendar 行数: 10  ✅
       Apr FOMC:  fomc_2026_04_29

[F]   Glassnode lth_realized_price:    XXX 行  ✅
       Glassnode sth_realized_price:    XXX 行  ✅
       Glassnode sopr_adjusted:         XXX 行  ✅
       CoinGlass funding_rate_aggregated:  XX 行  ✅
       FRED gold_price:                 XXX 行  ✅

[G]   data_fetch_log:
        macro       last=2026-04-27T14:00:00Z  ✅
        klines      last=2026-04-27T14:00:00Z  ✅
        derivatives last=2026-04-27T14:00:00Z  ✅
        onchain     last=2026-04-27T14:00:00Z  ✅

[E]   computation_method:  ai_assisted  ✅
       macro_stance:        risk_off / risk_neutral / ...
       macro_headwind_score: -3.5(范围 -10..+10)
       adjustment_guidance.position_cap_multiplier: 0.85

[E]   l5_ai_override_applied:  True  ✅
       step 4 multiplier (pre→post AI): 1.0 → 0.85
       final position_cap_pct: 30.09%

[G]   onchain_mvrv_z_score_xxx       captured=2026-04-27 08:00 (BJT)  fetched=2026-04-27 14:00 (BJT)
       (captured 与 fetched 不同 = 后端字段已就位,前端可改样式)

[F]   BTC-gold 60d corr:     0.234  ✅
[D.1] EventRisk score:       4.0  band=medium
       EventRisk top event:   FOMC Rate Decision (Apr 28-29) (hours_to=48.0)
```

---

## D. 失败排查

| 症状 | 可能原因 | 排查 |
|---|---|---|
| `events_calendar` 0 行 | systemd 没重启 / startup hook 未触发 | `journalctl -u btc-strategy -n 100 \| grep "Events seeded"` |
| `data_fetch_log` 空 | scheduler 1h job 未跑过 | 等下个整点,或手动跑 `python -c "from src.scheduler.jobs import job_data_collection; job_data_collection()"` |
| `gold_price` 0 行 | FRED key 失效 / GOLDPMGBD228NLBM series 不在 SERIES_TO_METRIC | grep `SERIES_TO_METRIC` `src/data/collectors/fred.py` |
| `funding_rate_aggregated` 0 行 | CoinGlass `oi-weight-history` 端点 404 / 中转站不支持 | `tail -n 200 logs/scheduler.log \| grep funding_rate_aggregated` |
| `computation_method='rule_based'` 总是 | OPENAI_API_KEY 未配 / data_completeness < 50% | `grep OPENAI_API_KEY .env` + 看 L5 输出 `data_completeness_pct` |
| `l5_ai_override_applied=False` | L5 走 rule 路径 / state_builder Stage 13b 异常 | 看 logger.warning "L5 AI loopback failed" |
| factor card `fetched_at_bjt` 全 None | data_fetch_log 空 / state_builder 没注入 data_freshness | 先看 `data_fetch_log` 表 |

---

## 总 commits (Sprint 2.6 D.1 + F + G + E)

```
0c05dca feat(layer5): AI-assisted macro analysis (rule-based fallback) + L4 loopback
5ea0c5c feat(ai): MacroL5Adjudicator (§6.8 verbatim System Prompt + Layer5Output)
c208092 feat(emitter): expose fetched_at_bjt alongside K-line bar time
49e7681 feat(macro): add gold price + BTC-gold 60d correlation
d247ff0 feat(coinglass): add OI-weighted funding rate across exchanges
43e468f test(glassnode): regression guard for 13 metrics in collect_and_save_all
cd5666b fix(api): move events seed hook to FastAPI startup (was scheduler/main.py)
```

---

## Backlog

**Sprint 2.6-F 子任务遗留:BTC-黄金 60 日相关性数据源问题。**
GOLDPMGBD228NLBM 已 discontinued,且 Yahoo IP banned / Stooq apikey wall /
LBMA paid-only,目前无可行免费日级数据源。卡保持"数字黄金叙事监测,Sprint 2.x
再接入",待找到可靠数据源后单独 sprint 处理。
