#!/usr/bin/env python3
"""scripts/fetch_btc_onchain_history.py — 拉 BTC 6 指标日频历史 → 宽表 CSV

通过 Glassnode / CoinGlass alphanode 中转站拉:
  1. MVRV-Z Score
  2. NUPL
  3. LTH 净仓位变化 (Net Position Change)
  4. LTH Realized Price (派生:supply 加权聚合 ≥6m 桶)
  5. Realized Price
  6. BTC Close Price

时间范围:2023-01-01 至今(中转站给多少就拉多少)。

用法:
    export GN_API_KEY=<你的 alphanode key>
    python3 scripts/fetch_btc_onchain_history.py --probe        # 先看样本
    python3 scripts/fetch_btc_onchain_history.py --full         # 拉全量 + 写 CSV

输出:btc_onchain_history.csv(当前目录)。

中转站配置(若你的不同,改下面常量):
  BASE_URL          = https://api.alphanode.work
  AUTH_HEADER_NAME  = x-key
  SPACING_SEC       = 5    请求间间隔,避免触发中转站对单 endpoint 的突发限流
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd


# ============================================================
# 中转站配置
# ============================================================
BASE_URL: str = "https://api.alphanode.work"
AUTH_HEADER_NAME: str = "x-key"
START_DATE: datetime = datetime(2021, 1, 1, tzinfo=timezone.utc)
SPACING_SEC: float = 5.0
TIMEOUT_SEC: int = 30
OUTPUT_PATH: str = "btc_onchain_history.csv"


# ============================================================
# 指标 → endpoint(简单 {t, v} 格式)
# ============================================================
SIMPLE_ENDPOINTS: dict[str, dict[str, str]] = {
    "mvrv_z_score": {
        "path": "/v1/metrics/market/mvrv_z_score",
        "col": "mvrv_z_score",       # 无单位,标准差归一
    },
    "nupl": {
        "path": "/v1/metrics/indicators/net_unrealized_profit_loss",
        "col": "nupl_ratio",         # -1 ~ +1
    },
    "lth_net_position_change": {
        "path": "/v1/metrics/supply/lth_net_change",
        "col": "lth_net_position_change_btc",   # BTC, 30d 净变化 (Glassnode 自带)
    },
    "realized_price": {
        "path": "/v1/metrics/market/price_realized_usd",
        "col": "realized_price_usd",
    },
    "close": {
        "path": "/v1/metrics/market/price_usd_close",
        "col": "close_usd",
    },
    # ---- 批次 2026-06-10:大周期补 7 项(只加进手动脚本,**不**进 cron)----
    "liveliness": {
        "path": "/v1/metrics/indicators/liveliness",
        "col": "liveliness",                 # 0-1 比率(累积销毁/创建 coin-days)
    },
    "illiquid_sum": {
        "path": "/v1/metrics/supply/illiquid_sum",
        "col": "illiquid_supply_btc",        # BTC 量(流动性已锁仓)
    },
    "net_realized_profit_loss": {
        "path": "/v1/metrics/indicators/net_realized_profit_loss",
        "col": "nrpl_usd",                   # USD(净实现盈亏 = realized_profit - realized_loss)
    },
    "lth_profit_sum": {
        "path": "/v1/metrics/supply/lth_profit_sum",
        "col": "lth_profit_btc",             # BTC 量(LTH 浮盈)
    },
    "lth_loss_sum": {
        "path": "/v1/metrics/supply/lth_loss_sum",
        "col": "lth_loss_btc",               # BTC 量(LTH 浮亏 — 投降信号)
    },
    "sopr": {
        "path": "/v1/metrics/indicators/sopr",
        "col": "sopr",                       # 1 上下(基础版,未做 1 日内 UTXO 调整)
    },
    "sopr_adjusted": {
        "path": "/v1/metrics/indicators/sopr_adjusted",
        "col": "sopr_adjusted",              # 1 上下(剔除 1 日内回收 UTXO 后)
    },
    # ---- 批次 2026-06-10b:LTH-NUPL(大周期专属 NUPL 分群)----
    "lth_nupl": {
        "path": "/v1/metrics/indicators/nupl_more_155",
        "col": "lth_nupl_ratio",             # -1~+1,LTH 整体浮盈浮亏比
    },
}


# LTH Realized Price 是派生指标(无 single endpoint):用 supply 加权
# 聚合"price_realized_usd_by_age" 的 ≥6m 桶。这是本系统生产代码
# (src/data/collectors/glassnode.py:_aggregate_lth_sth_realized_price)
# 的相同口径。STH 用 <6m 桶。
LTH_REALIZED_PATHS: dict[str, str] = {
    "price_by_age": "/v1/metrics/breakdowns/price_realized_usd_by_age",
    "supply_by_age": "/v1/metrics/breakdowns/supply_by_age",
}
LTH_BUCKETS: tuple[str, ...] = (
    "6m_12m", "1y_2y", "2y_3y", "3y_5y", "5y_7y", "7y_10y", "more_10y",
)
LTH_REALIZED_COL: str = "lth_realized_price_usd"


# ============================================================
# HTTP 工具
# ============================================================
def _get_key() -> str:
    k = os.environ.get("GN_API_KEY")
    if not k:
        sys.exit("ERROR: 环境变量 GN_API_KEY 未设置")
    return k


def _fetch(path: str, *, since_unix: int | None) -> Any:
    """GET base_url + path(BTC, 24h)。返回解析后 JSON 或 {_err*: ...}。

    2026-06-15:加 3 次重试。5xx/超时 → 退避(5s/10s) 重试,429 → 1 次直接跳
    (等下次 cron 兜底,避免烧 quota)。
    """
    params: dict[str, Any] = {"a": "BTC", "i": "24h"}
    if since_unix:
        params["s"] = since_unix
    url = f"{BASE_URL}{path}?{urlencode(params)}"
    req = Request(url, headers={
        AUTH_HEADER_NAME: _get_key(),
        "Accept": "application/json",
        "User-Agent": "btc-onchain-history-fetcher/1.0",
    })
    # 2026-06-16:backoff 升级 5/10 → 10/30/60(4 次尝试,累计 ~100s)
    # 覆盖更长的上游抖动(alphanode 偶发 60-90s 不通的网络/中转故障)
    _RETRY_STATUSES = {500, 502, 503, 504, 408}  # 注:不含 429
    _BACKOFF_SEQ = [10, 30, 60]  # 第 1 次失败等 10s,第 2 次失败等 30s,第 3 次等 60s
    last_err: dict[str, Any] = {}
    for attempt in range(1, len(_BACKOFF_SEQ) + 2):  # 4 attempts: 1, 2, 3, 4
        try:
            with urlopen(req, timeout=TIMEOUT_SEC) as resp:
                return json.loads(resp.read())
        except HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:300]
            last_err = {"_err_http": e.code, "_body": body}
            if e.code == 429:
                # 429 → 直接跳,不重试(秒级窗口限频,等下一次 cron 兜底)
                print(f"  [429_SKIP] {path} (attempt {attempt}/1)", flush=True)
                return last_err
            if e.code in _RETRY_STATUSES and attempt <= len(_BACKOFF_SEQ):
                delay = _BACKOFF_SEQ[attempt - 1]
                print(f"  HTTP {e.code} on {path} (attempt {attempt}/4), "
                      f"retry in {delay}s", flush=True)
                time.sleep(delay)
                continue
            return last_err
        except URLError as e:
            last_err = {"_err_url": str(e)}
            if attempt <= len(_BACKOFF_SEQ):
                delay = _BACKOFF_SEQ[attempt - 1]
                print(f"  URLError (attempt {attempt}/4), retry in {delay}s",
                      flush=True)
                time.sleep(delay)
                continue
            return last_err
        except Exception as e:
            return {"_err_other": f"{type(e).__name__}: {e}"}
    return last_err


# 2026-06-16:共享 .last_failures.json 跟踪上次跑哪些 endpoint 失败,
# 下次跑时优先重试 + 二次 pass + 持久化失败列表给监控用。
_FAILURES_FILE = Path(__file__).resolve().parent.parent / ".last_failures.json"


def _load_last_failures(script_key: str) -> list[dict[str, Any]]:
    """读 .last_failures.json 里指定 script 的失败 endpoint 列表。"""
    if not _FAILURES_FILE.exists():
        return []
    try:
        data = json.loads(_FAILURES_FILE.read_text(encoding="utf-8"))
        return data.get(script_key, [])
    except Exception:
        return []


def _save_last_failures(script_key: str,
                        failures: list[dict[str, Any]]) -> None:
    """更新本 script 的失败列表(merge 其他 script 的不动)。"""
    data: dict[str, Any] = {}
    if _FAILURES_FILE.exists():
        try:
            data = json.loads(_FAILURES_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data[script_key] = failures
    data["_last_updated"] = (
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    try:
        _FAILURES_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8",
        )
    except Exception as e:
        print(f"⚠️  write .last_failures.json failed: {e}", flush=True)


def _to_iso_date(t_sec: int) -> str:
    """Glassnode t 是 Unix 秒 → UTC YYYY-MM-DD。"""
    return datetime.fromtimestamp(int(t_sec), tz=timezone.utc).strftime("%Y-%m-%d")


def _parse_tv(raw: Any) -> list[tuple[str, float]]:
    """[{"t": <sec>, "v": <num>}, ...] → [(YYYY-MM-DD, value), ...]"""
    if not isinstance(raw, list):
        return []
    out: list[tuple[str, float]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        t = row.get("t")
        v = row.get("v")
        if t is None or v is None:
            continue
        try:
            out.append((_to_iso_date(int(t)), float(v)))
        except (TypeError, ValueError):
            continue
    return out


def _parse_by_age(raw: Any) -> dict[int, dict[str, float]]:
    """[{"t": <sec>, "o": {"24h": ..., "1y_2y": ..., ...}}, ...]
       → {t_sec: {bucket: float}}"""
    out: dict[int, dict[str, float]] = {}
    if not isinstance(raw, list):
        return out
    for row in raw:
        if not isinstance(row, dict):
            continue
        t = row.get("t")
        o = row.get("o")
        if t is None or not isinstance(o, dict):
            continue
        buckets: dict[str, float] = {}
        for k, v in o.items():
            try:
                buckets[k] = float(v)
            except (TypeError, ValueError):
                continue
        out[int(t)] = buckets
    return out


def _aggregate_lth_realized(
    price_by_t: dict[int, dict[str, float]],
    supply_by_t: dict[int, dict[str, float]],
) -> list[tuple[str, float]]:
    """LTH realized price = Σ(price_b × supply_b) / Σ(supply_b),b ∈ LTH_BUCKETS"""
    out: list[tuple[str, float]] = []
    for t in sorted(set(price_by_t) & set(supply_by_t)):
        p = price_by_t[t]
        s = supply_by_t[t]
        num = 0.0
        denom = 0.0
        for b in LTH_BUCKETS:
            pv = p.get(b)
            sv = s.get(b)
            if pv is None or sv is None:
                continue
            num += pv * sv
            denom += sv
        if denom > 0:
            out.append((_to_iso_date(t), num / denom))
    return out


# ============================================================
# Probe 模式 — 看字段结构 + 日期格式
# ============================================================
def cmd_probe() -> None:
    print("=== Probe 模式:逐个 endpoint 看样本(确认字段 + 日期格式)\n")
    print(f"Base URL:    {BASE_URL}")
    print(f"Auth header: {AUTH_HEADER_NAME}: ****\n")

    # 5 个简单 endpoint
    for key, info in SIMPLE_ENDPOINTS.items():
        print(f"——— {key:30s} ———")
        print(f"  path: {info['path']}")
        raw = _fetch(info["path"], since_unix=None)
        if isinstance(raw, dict) and any(k.startswith("_err") for k in raw):
            print(f"  ❌  {raw}")
            print()
            time.sleep(SPACING_SEC)
            continue
        sample = raw[:2] if isinstance(raw, list) else raw
        print(f"  raw[:2]: {json.dumps(sample, ensure_ascii=False)[:300]}")
        normalized = _parse_tv(raw)
        if normalized:
            print(f"  ✅  parsed: date={normalized[0][0]}, value={normalized[0][1]}")
        else:
            print("  ⚠️  非 {t, v} 格式 — 需自定义解析或换 endpoint")
        print()
        time.sleep(SPACING_SEC)

    # LTH Realized(派生)
    print(f"——— {'lth_realized_price':30s} ———")
    print("  (派生指标:price_realized_usd_by_age + supply_by_age 加权聚合 ≥6m 桶)")
    for k, p in LTH_REALIZED_PATHS.items():
        print(f"  path[{k}]: {p}")
        raw = _fetch(p, since_unix=None)
        if isinstance(raw, dict) and any(x.startswith("_err") for x in raw):
            print(f"    ❌  {raw}")
            time.sleep(SPACING_SEC)
            continue
        sample = raw[:1] if isinstance(raw, list) else raw
        print(f"    raw[:1]: {json.dumps(sample, ensure_ascii=False)[:300]}")
        if isinstance(raw, list) and raw and isinstance(raw[0], dict):
            o = raw[0].get("o")
            if isinstance(o, dict):
                missing = [b for b in LTH_BUCKETS if b not in o]
                if missing:
                    print(f"    ⚠️  LTH 桶缺失: {missing}")
                else:
                    print(f"    ✅  含全部 7 个 LTH 桶: {list(LTH_BUCKETS)}")
            else:
                print("    ⚠️  响应顶层无 'o' 字典 — 桶结构不符,需调整")
        time.sleep(SPACING_SEC)
    print()
    print("如全部 ✅ → 跑 --full;如有 ❌/⚠️ → 改 SIMPLE_ENDPOINTS/LTH_REALIZED_PATHS。")


# ============================================================
# Full 模式 — 拉全量 + outer-join + 写 CSV
# ============================================================
def _try_fetch_endpoint(key: str, info: dict[str, Any],
                       since_unix: int) -> tuple[pd.Series, bool]:
    """单 endpoint 拉 + 解析。返 (series, ok)。ok=False 说明失败,series 为空。"""
    raw = _fetch(info["path"], since_unix=since_unix)
    col = info["col"]
    if isinstance(raw, dict) and any(k.startswith("_err") for k in raw):
        return pd.Series(dtype=float, name=col), False
    pairs = _parse_tv(raw)
    if not pairs:
        return pd.Series(dtype=float, name=col), False
    df = pd.DataFrame(pairs, columns=["date", col])
    df = df.drop_duplicates("date", keep="last")
    return df.set_index("date")[col], True


def _try_fetch_lth_realized(since_unix: int) -> tuple[pd.Series, bool]:
    """LTH realized 派生(2 个 breakdowns endpoints + 桶聚合)。"""
    price_raw = _fetch(LTH_REALIZED_PATHS["price_by_age"], since_unix=since_unix)
    time.sleep(SPACING_SEC)
    supply_raw = _fetch(LTH_REALIZED_PATHS["supply_by_age"], since_unix=since_unix)
    if (isinstance(price_raw, dict) and any(k.startswith("_err") for k in price_raw)) \
       or (isinstance(supply_raw, dict) and any(k.startswith("_err") for k in supply_raw)):
        return pd.Series(dtype=float, name=LTH_REALIZED_COL), False
    price_by_t = _parse_by_age(price_raw)
    supply_by_t = _parse_by_age(supply_raw)
    pairs = _aggregate_lth_realized(price_by_t, supply_by_t)
    if not pairs:
        return pd.Series(dtype=float, name=LTH_REALIZED_COL), False
    df = pd.DataFrame(pairs, columns=["date", LTH_REALIZED_COL])
    df = df.drop_duplicates("date", keep="last")
    return df.set_index("date")[LTH_REALIZED_COL], True


def cmd_full() -> None:
    print(f"=== Full 模式:从 {START_DATE.date()} UTC 拉 6 指标日频\n")
    since_unix = int(START_DATE.timestamp())

    # 上轮失败记录:本轮优先重试(顺序提前 + 日志高亮)
    prev_failures = _load_last_failures("onchain")
    prev_failed_keys = {f["key"] for f in prev_failures}
    if prev_failures:
        print(f"⚠️  上轮 {len(prev_failures)} 个 endpoint 失败,本轮优先重试:")
        for f in prev_failures:
            print(f"    - {f['key']}")
        print()

    # Phase 1:常规主 loop
    results: dict[str, pd.Series] = {}
    failed_keys: list[str] = []
    # 先跑上次失败的,再跑其他(保证失败 endpoint 在 fresh quota 下先打)
    ordered_items = (
        [(k, SIMPLE_ENDPOINTS[k]) for k in prev_failed_keys
         if k in SIMPLE_ENDPOINTS]
        + [(k, v) for k, v in SIMPLE_ENDPOINTS.items()
           if k not in prev_failed_keys]
    )

    for key, info in ordered_items:
        marker = " (优先)" if key in prev_failed_keys else ""
        print(f"  fetching {info['col']:36s}{marker}", end=" ... ", flush=True)
        s, ok = _try_fetch_endpoint(key, info, since_unix)
        if ok:
            print(f"{len(s)} rows  ({s.index.min()} ~ {s.index.max()})")
            results[key] = s
        else:
            print("FAIL")
            results[key] = s
            failed_keys.append(key)
        time.sleep(SPACING_SEC)

    # LTH Realized(派生 — 单独处理因为 2 endpoints)
    print(f"  fetching {LTH_REALIZED_COL:36s}", end=" ... ", flush=True)
    s, ok = _try_fetch_lth_realized(since_unix)
    if ok:
        print(f"{len(s)} rows  ({s.index.min()} ~ {s.index.max()})")
        results["__lth_realized__"] = s
    else:
        print("FAIL")
        results["__lth_realized__"] = s
        failed_keys.append("__lth_realized__")
    time.sleep(SPACING_SEC)

    # Phase 2:second-pass 自愈 — 失败 endpoint 等 90s 重试一次
    if failed_keys:
        print(f"\n⏳ Second-pass 自愈:{len(failed_keys)} 个 endpoint 失败,"
              f"等 90s 后重试")
        time.sleep(90)
        still_failed: list[str] = []
        for key in failed_keys:
            if key == "__lth_realized__":
                print(f"  retry {LTH_REALIZED_COL:36s}", end=" ... ", flush=True)
                s, ok = _try_fetch_lth_realized(since_unix)
                col = LTH_REALIZED_COL
            else:
                info = SIMPLE_ENDPOINTS[key]
                print(f"  retry {info['col']:36s}", end=" ... ", flush=True)
                s, ok = _try_fetch_endpoint(key, info, since_unix)
                col = info["col"]
            if ok:
                print(f"RECOVERED ({len(s)} rows)")
                results[key] = s
            else:
                print("STILL FAIL")
                still_failed.append(key)
            time.sleep(SPACING_SEC)
        failed_keys = still_failed

    # Phase 3:持久化最终失败列表(供下次 cron 优先重试 + 监控)
    final_failures = []
    for key in failed_keys:
        if key == "__lth_realized__":
            final_failures.append({
                "key": key, "col": LTH_REALIZED_COL,
                "paths": list(LTH_REALIZED_PATHS.values()),
            })
        elif key in SIMPLE_ENDPOINTS:
            info = SIMPLE_ENDPOINTS[key]
            final_failures.append({
                "key": key, "col": info["col"], "path": info["path"],
            })
    _save_last_failures("onchain", final_failures)
    if final_failures:
        print(f"\n⚠️  最终 {len(final_failures)} 个 endpoint 失败(已写 "
              f".last_failures.json,下次 cron 自动优先重试)")
    elif prev_failures:
        print(f"\n✅ 上轮失败的 {len(prev_failures)} 个 endpoint 本轮全部恢复 "
              f"(.last_failures.json 已清空)")

    # 重组 series(按原始顺序)
    series: list[pd.Series] = []
    for key in SIMPLE_ENDPOINTS:
        series.append(results.get(key, pd.Series(
            dtype=float, name=SIMPLE_ENDPOINTS[key]["col"],
        )))
    series.append(results.get("__lth_realized__", pd.Series(
        dtype=float, name=LTH_REALIZED_COL,
    )))

    # outer join on date
    merged = pd.concat(series, axis=1, join="outer").sort_index()
    merged.index.name = "date"
    merged.to_csv(OUTPUT_PATH, na_rep="")
    print(f"\n✅ 写入 {OUTPUT_PATH}  ({len(merged)} 行 × {len(merged.columns)} 列)")
    print(f"   日期范围: {merged.index.min()} ~ {merged.index.max()}")
    print(f"   各列非空数:\n{merged.notna().sum().to_string(header=False)}")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="拉 BTC 6 个 Glassnode 日频指标 → 宽表 CSV",
    )
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument(
        "--probe", action="store_true",
        help="拉每个 endpoint 2 条样本看字段结构(请先跑这个)",
    )
    g.add_argument(
        "--full", action="store_true",
        help="拉全量历史 + outer-join + 写 CSV",
    )
    args = ap.parse_args()
    if args.probe:
        cmd_probe()
    else:
        cmd_full()


if __name__ == "__main__":
    main()
