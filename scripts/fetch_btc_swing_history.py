#!/usr/bin/env python3
"""scripts/fetch_btc_swing_history.py — 拉 BTC 波段历史 → 4 CSV

同款风格(参考 fetch_btc_onchain_history.py):probe + full + CSV + 限频。
分 3 模块,源/频率不同,**各出独立 CSV**(不硬塞一张表):

  A) CoinGlass 衍生品 + OHLC  → btc_swing_deriv_4h.csv  +  btc_swing_deriv_1d.csv
  B) FRED 宏观                → btc_swing_macro.csv
  C) Glassnode 期权           → btc_swing_options.csv

用法:
    export COINGLASS_API_KEY=xxx        # alphanode key,同一把
    export GLASSNODE_API_KEY=xxx        # 同 alphanode key
    export FRED_API_KEY=xxx             # FRED 单独 key(免费注册)
    python3 scripts/fetch_btc_swing_history.py --probe              # 先看样本
    python3 scripts/fetch_btc_swing_history.py --full               # 拉全量,3 模块齐跑
    python3 scripts/fetch_btc_swing_history.py --full --module a    # 只跑 A
    python3 scripts/fetch_btc_swing_history.py --probe --module c   # 只 probe C
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd


# ============================================================
# 配置
# ============================================================
CG_BASE: str = "https://api.alphanode.work/open-api-v4.coinglass.com/api"
GN_BASE: str = "https://api.alphanode.work"
FRED_BASE: str = "https://api.stlouisfed.org/fred/series/observations"

SPACING_CG: float = 5.0          # CoinGlass 限频:5s/请求(同主项目)
SPACING_GN: float = 5.0          # Glassnode 同
SPACING_FRED: float = 1.0        # FRED 直连官方,可快一点

TIMEOUT_SEC: int = 30

# 回溯起点
START_FRED_DATE: str = "2024-06-01"
START_GN_UNIX: int = int(datetime(2024, 6, 1, tzinfo=timezone.utc).timestamp())

# limit 取够覆盖 1 年
LIMIT_4H: int = 2200   # 365 * 6 = 2190
LIMIT_1D: int = 400

OUT_DERIV_4H: str = "btc_swing_deriv_4h.csv"
OUT_DERIV_1D: str = "btc_swing_deriv_1d.csv"
OUT_MACRO: str = "btc_swing_macro.csv"
OUT_OPTIONS: str = "btc_swing_options.csv"


# ============================================================
# Env
# ============================================================
def _env_or_die(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        sys.exit(f"ERROR: 环境变量 {name} 未设置")
    return v


# ============================================================
# HTTP 通用
# ============================================================
def _http_get(url: str, *, headers: dict[str, str] | None = None) -> Any:
    """GET → 解析后 JSON 或 {_err*: ...} 字典。

    2026-06-15:5xx/超时 退避重试 3 次(5s/10s),429 → 1 次直接跳。
    """
    req = Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "btc-swing-history-fetcher/1.0",
        **(headers or {}),
    })
    # 2026-06-16:backoff 升级 5/10 → 10/30/60(4 次尝试,~100s 累计)
    _RETRY_STATUSES = {500, 502, 503, 504, 408}
    _BACKOFF_SEQ = [10, 30, 60]
    last_err: dict[str, Any] = {}
    for attempt in range(1, len(_BACKOFF_SEQ) + 2):  # 4 attempts: 1,2,3,4
        try:
            with urlopen(req, timeout=TIMEOUT_SEC) as resp:
                return json.loads(resp.read())
        except HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                pass
            last_err = {"_err_http": e.code, "_body": body}
            if e.code == 429:
                print(f"  [429_SKIP] {url[:80]} (attempt {attempt}/1)", flush=True)
                return last_err
            if e.code in _RETRY_STATUSES and attempt <= len(_BACKOFF_SEQ):
                delay = _BACKOFF_SEQ[attempt - 1]
                print(f"  HTTP {e.code} (attempt {attempt}/4), retry in {delay}s",
                      flush=True)
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


# 2026-06-16:共享 .last_failures.json,跟踪上次跑哪些 endpoint 失败,
# 下次跑时优先重试 + 二次 pass + 持久化失败列表给监控用。
_FAILURES_FILE = (
    Path(__file__).resolve().parent.parent / ".last_failures.json"
)


def _load_last_failures(script_key: str) -> list[dict[str, Any]]:
    if not _FAILURES_FILE.exists():
        return []
    try:
        data = json.loads(_FAILURES_FILE.read_text(encoding="utf-8"))
        return data.get(script_key, [])
    except Exception:
        return []


def _save_last_failures(script_key: str,
                        failures: list[dict[str, Any]]) -> None:
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


def _is_err(body: Any) -> bool:
    return isinstance(body, dict) and any(
        k.startswith("_err") for k in body
    )


# ============================================================
# 时间戳归一(秒 / 毫秒 / ISO 都吃)
# ============================================================
def _ts_to_utc_dt(t: Any) -> datetime | None:
    if t is None or t == "":
        return None
    if isinstance(t, str):
        s = t.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            try:
                t = float(s)
            except ValueError:
                return None
    try:
        n = float(t)
    except (TypeError, ValueError):
        return None
    # > 1e12 视为毫秒,否则秒
    if abs(n) > 1e12:
        n /= 1000.0
    try:
        return datetime.fromtimestamp(n, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _fmt_date(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")


def _fmt_datetime_4h(dt: datetime | None) -> str | None:
    """4h 数据需要小时精度。"""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")


# ============================================================
# 模块 A — CoinGlass
# ============================================================
def _cg_get(path: str, *, params: dict[str, Any]) -> Any:
    url = f"{CG_BASE}{path}?{urlencode(params)}"
    return _http_get(url, headers={"x-key": _env_or_die("COINGLASS_API_KEY")})


def _cg_unwrap(body: Any) -> Any:
    """CoinGlass v4:{code: '0', data: [...]} 或 {code, data: {...}}。
    返回 data 字段;响应错误抛 RuntimeError。"""
    if _is_err(body):
        return body
    if isinstance(body, dict):
        if body.get("code") not in ("0", 0, None):
            return {
                "_err_cg_code": body.get("code"),
                "_msg": body.get("msg") or body.get("message"),
            }
        return body.get("data")
    return body


def _cg_detect_ts_field(row: dict) -> str | None:
    for k in ("timestamp", "t", "time", "ts", "createTime"):
        if k in row:
            return k
    return None


def _cg_parse_ohlc_rows(rows: list, value_field: str) -> list[tuple[Any, float]]:
    """OHLC 类响应:取 'close' 或指定字段。
    返回 [(timestamp_raw, value), ...]。"""
    out: list[tuple[Any, float]] = []
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        ts_field = _cg_detect_ts_field(row)
        if ts_field is None:
            continue
        v_raw = row.get(value_field)
        if v_raw is None or v_raw == "":
            continue
        try:
            out.append((row[ts_field], float(v_raw)))
        except (TypeError, ValueError):
            continue
    return out


def _cg_parse_klines(rows: list) -> list[tuple[Any, dict[str, float]]]:
    """K 线响应:每行 open/high/low/close/volume_usd。"""
    out: list[tuple[Any, dict[str, float]]] = []
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        ts_field = _cg_detect_ts_field(row)
        if ts_field is None:
            continue
        try:
            ohlc = {
                "open": float(row.get("open") or row.get("o") or 0),
                "high": float(row.get("high") or row.get("h") or 0),
                "low":  float(row.get("low")  or row.get("l") or 0),
                "close": float(row.get("close") or row.get("c") or 0),
                "volume_usd": float(
                    row.get("volume_usd") or row.get("volume") or
                    row.get("v") or 0
                ),
            }
        except (TypeError, ValueError):
            continue
        out.append((row[ts_field], ohlc))
    return out


def _cg_parse_etf_flow(rows: list) -> list[tuple[Any, float]]:
    out: list[tuple[Any, float]] = []
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        ts_field = _cg_detect_ts_field(row)
        v = row.get("flow_usd")
        if ts_field is None or v is None:
            continue
        try:
            out.append((row[ts_field], float(v)))
        except (TypeError, ValueError):
            continue
    return out


def _cg_parse_liquidation(rows: list) -> list[tuple[Any, float]]:
    """爆仓:取 total_liquidation_usd 或 long+short 合计。"""
    out: list[tuple[Any, float]] = []
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        ts_field = _cg_detect_ts_field(row)
        if ts_field is None:
            continue
        total = (
            row.get("total_liquidation_usd")
            or row.get("liquidation_usd")
            or row.get("total")
        )
        if total is None:
            ll = row.get("long_liquidation_usd")
            sl = row.get("short_liquidation_usd")
            if ll is not None and sl is not None:
                try:
                    total = float(ll) + float(sl)
                except (TypeError, ValueError):
                    continue
        if total is None:
            continue
        try:
            out.append((row[ts_field], float(total)))
        except (TypeError, ValueError):
            continue
    return out


def _cg_parse_fng(data: Any) -> list[tuple[Any, float]]:
    """F&G:{data_list: [..值..], time_list: [..ms..]}"""
    if not isinstance(data, dict):
        return []
    vals = data.get("data_list") or []
    times = data.get("time_list") or []
    if len(vals) != len(times):
        return []
    out: list[tuple[Any, float]] = []
    for t, v in zip(times, vals):
        if t is None or v is None:
            continue
        try:
            out.append((t, float(v)))
        except (TypeError, ValueError):
            continue
    return out


# ---- 模块 A endpoint 定义(spec 风格)----
# (name, path, params_extra, parser, output_col, interval_kinds)
# interval_kinds: {"4h", "1d", "none"}
_CG_ENDPOINTS: list[dict[str, Any]] = [
    {
        "name": "klines",
        "path": "/futures/price/history",
        "params": {"symbol": "BTCUSDT", "exchange": "Binance"},
        "kind": "klines",            # 多列
        "intervals": ("4h", "1d"),
    },
    {
        "name": "funding_rate",
        "path": "/futures/funding-rate/history",
        "params": {"symbol": "BTCUSDT", "exchange": "Binance"},
        "kind": "ohlc_close",
        "col": "funding_rate",
        "intervals": ("4h", "1d"),
    },
    {
        # 聚合 OI 跨交易所,要 symbol=BTC(资产,不是 BTCUSDT 合约)+ 不传 exchange
        "name": "open_interest",
        "path": "/futures/open-interest/aggregated-history",
        "params": {"symbol": "BTC"},
        "kind": "ohlc_close",
        "col": "oi",
        "intervals": ("4h", "1d"),
    },
    {
        # LSR 响应是 flat 字段(非 OHLC),直接取 global_account_long_short_ratio
        "name": "long_short_ratio",
        "path": "/futures/global-long-short-account-ratio/history",
        "params": {"symbol": "BTCUSDT", "exchange": "Binance"},
        "kind": "flat_field",
        "value_field": "global_account_long_short_ratio",
        "col": "long_short_ratio",
        "intervals": ("4h", "1d"),
    },
    {
        "name": "liquidation",
        "path": "/futures/liquidation/history",
        "params": {"symbol": "BTCUSDT", "exchange": "Binance"},
        "kind": "liquidation",
        "col": "liquidation_usd",
        "intervals": ("1d",),
    },
    {
        "name": "etf_flow",
        "path": "/etf/bitcoin/flow-history",
        "params": {},                   # 无 symbol
        "kind": "etf_flow",
        "col": "etf_flow_usd",
        "intervals": ("1d",),
    },
    {
        "name": "fear_greed",
        "path": "/index/fear-greed-history",
        "params": {},                   # 无参数
        "kind": "fng",
        "col": "fear_greed",
        "intervals": ("none",),          # 历史全量,日频
    },
]


def _cg_fetch_one(
    ep: dict[str, Any], *, interval: str | None, limit: int,
) -> tuple[Any, Any]:
    """返回 (data_raw, parsed_pairs)。"""
    params = dict(ep["params"])
    if interval is not None and interval != "none":
        params["interval"] = interval
        params["limit"] = limit
    body = _cg_get(ep["path"], params=params)
    data = _cg_unwrap(body)
    if _is_err(data) or (isinstance(data, dict) and "_err_cg_code" in data):
        return data, None
    if ep["kind"] == "klines":
        return data, _cg_parse_klines(data)
    if ep["kind"] == "ohlc_close":
        return data, _cg_parse_ohlc_rows(data, "close")
    if ep["kind"] == "flat_field":
        return data, _cg_parse_ohlc_rows(data, ep["value_field"])
    if ep["kind"] == "liquidation":
        return data, _cg_parse_liquidation(data)
    if ep["kind"] == "etf_flow":
        return data, _cg_parse_etf_flow(data)
    if ep["kind"] == "fng":
        return data, _cg_parse_fng(data)
    return data, None


def probe_module_a() -> None:
    print("=== Module A — CoinGlass 衍生品 + OHLC ===\n")
    print(f"Base: {CG_BASE}\nAuth: x-key: ****\n")
    # probe 用极小 limit,看响应格式
    for ep in _CG_ENDPOINTS:
        for interval in ep["intervals"]:
            label = f"{ep['name']}" + (f" [{interval}]" if interval != "none" else "")
            print(f"——— {label:30s} ———")
            print(f"  path: {ep['path']}")
            params = dict(ep["params"])
            if interval != "none":
                params["interval"] = interval
                params["limit"] = 2
            print(f"  params: {params}")
            data, pairs = _cg_fetch_one(
                ep, interval=interval if interval != "none" else None, limit=2,
            )
            if _is_err(data):
                print(f"  ❌  {data}")
                print()
                time.sleep(SPACING_CG)
                continue
            # 显示原始
            preview = (
                json.dumps(data, ensure_ascii=False)[:280]
                if not isinstance(data, dict)
                else json.dumps(
                    {k: (data[k][:2] if isinstance(data[k], list) else data[k])
                     for k in list(data)[:6]},
                    ensure_ascii=False,
                )[:280]
            )
            print(f"  raw[:2]: {preview}")
            if isinstance(data, list) and data and isinstance(data[0], dict):
                ts_field = _cg_detect_ts_field(data[0])
                print(f"  时间戳字段: {ts_field!r}; "
                      f"原值: {data[0].get(ts_field)!r}")
            # 解析后第 1 行
            if pairs:
                if ep["kind"] == "klines":
                    t0, ohlc = pairs[0]
                    dt = _ts_to_utc_dt(t0)
                    ms_hint = "ms" if dt and abs(float(t0)) > 1e12 else "sec"
                    print(f"  ✅  parsed: ts={t0} ({ms_hint}) → "
                          f"{_fmt_datetime_4h(dt)} UTC, ohlc={ohlc}")
                else:
                    t0, v0 = pairs[0]
                    dt = _ts_to_utc_dt(t0)
                    ms_hint = "ms" if dt and isinstance(t0, (int, float)) and abs(t0) > 1e12 else "sec/iso"
                    print(f"  ✅  parsed: ts={t0} ({ms_hint}) → "
                          f"{_fmt_datetime_4h(dt)} UTC, value={v0}")
            else:
                print("  ⚠️  parser 没拿到 row(字段名可能不符,看 raw 调整)")
            print()
            time.sleep(SPACING_CG)


def _cg_build_df_for_interval(
    interval: str, *, want_extras: bool,
) -> pd.DataFrame:
    """组装 4h 或 1d 一张表。"""
    use_ts_fmt = _fmt_datetime_4h if interval == "4h" else _fmt_date
    limit = LIMIT_4H if interval == "4h" else LIMIT_1D
    series: list[pd.Series] = []
    pieces: list[pd.DataFrame] = []

    for ep in _CG_ENDPOINTS:
        # 跳过不属于本档的 endpoint
        if interval == "4h" and "4h" not in ep["intervals"]:
            continue
        if interval == "1d" and "1d" not in ep["intervals"] and not (
            want_extras and ep["intervals"] == ("none",)
        ):
            continue
        if interval == "4h" and want_extras:
            pass  # 4h 不要 extras
        if not want_extras and ep["intervals"] == ("none",):
            continue

        # 决定本档拉的 interval(对 F&G 这种"无 interval"用 "none")
        fetch_interval = "none" if ep["intervals"] == ("none",) else interval
        label = f"{ep['name']}[{fetch_interval}]"
        print(f"  fetching {label:40s}", end=" ... ", flush=True)
        data, pairs = _cg_fetch_one(
            ep,
            interval=None if fetch_interval == "none" else fetch_interval,
            limit=limit,
        )
        time.sleep(SPACING_CG)
        if _is_err(data) or pairs is None:
            print(f"FAIL {data!r}"[:140])
            continue
        if not pairs:
            print("0 rows")
            continue

        # 转 DataFrame
        if ep["kind"] == "klines":
            rows = []
            for t, ohlc in pairs:
                dt = _ts_to_utc_dt(t)
                d = use_ts_fmt(dt)
                if d is None:
                    continue
                rows.append({
                    "date": d, "open": ohlc["open"], "high": ohlc["high"],
                    "low": ohlc["low"], "close": ohlc["close"],
                    "volume_usd": ohlc["volume_usd"],
                })
            df = pd.DataFrame(rows).drop_duplicates("date", keep="last").set_index("date")
            pieces.append(df)
            print(f"{len(df)} rows ({df.index.min()} ~ {df.index.max()})")
        else:
            rows = []
            for t, v in pairs:
                dt = _ts_to_utc_dt(t)
                d = use_ts_fmt(dt)
                if d is None:
                    continue
                rows.append((d, v))
            df = pd.DataFrame(rows, columns=["date", ep["col"]])
            df = df.drop_duplicates("date", keep="last").set_index("date")
            pieces.append(df)
            print(f"{len(df)} rows ({df.index.min()} ~ {df.index.max()})")

    if not pieces:
        return pd.DataFrame()
    merged = pd.concat(pieces, axis=1, join="outer").sort_index()
    merged.index.name = "date"
    return merged


def full_module_a() -> None:
    print("\n=== Module A — Full(4h + 1d 两张表) ===\n")
    print("--- 4h ---")
    df_4h = _cg_build_df_for_interval("4h", want_extras=False)
    if df_4h.empty:
        print("\n⚠️  4h 表空,跳过写文件")
    else:
        df_4h.to_csv(OUT_DERIV_4H, na_rep="")
        print(f"\n✅ {OUT_DERIV_4H}  ({len(df_4h)} 行 × {len(df_4h.columns)} 列)")
        print(f"   日期范围: {df_4h.index.min()} ~ {df_4h.index.max()}")

    print("\n--- 1d (含 liquidation/etf_flow/fear_greed) ---")
    df_1d = _cg_build_df_for_interval("1d", want_extras=True)
    if df_1d.empty:
        print("\n⚠️  1d 表空,跳过写文件")
    else:
        df_1d.to_csv(OUT_DERIV_1D, na_rep="")
        print(f"\n✅ {OUT_DERIV_1D}  ({len(df_1d)} 行 × {len(df_1d.columns)} 列)")
        print(f"   日期范围: {df_1d.index.min()} ~ {df_1d.index.max()}")


# ============================================================
# 模块 B — FRED
# ============================================================
_FRED_SERIES: list[tuple[str, str]] = [
    ("DTWEXBGS", "dxy"),
    ("DGS10",    "us10y"),
    ("DGS2",     "us2y"),
    ("VIXCLS",   "vix"),
    ("NASDAQCOM", "nasdaq"),     # = IXIC NASDAQ Composite
    ("DFII10",   "tips10y"),
]


def _fred_get(series_id: str, *, observation_start: str) -> Any:
    params = {
        "series_id": series_id,
        "api_key": _env_or_die("FRED_API_KEY"),
        "file_type": "json",
        "observation_start": observation_start,
    }
    return _http_get(f"{FRED_BASE}?{urlencode(params)}")


def _fred_parse(body: Any) -> list[tuple[str, float]]:
    """{observations: [{date: 'YYYY-MM-DD', value: '4.55' or '.'}]}
    '.' 表示 FRED 当日无数据,跳过(留空,不当 0)。"""
    if _is_err(body) or not isinstance(body, dict):
        return []
    obs = body.get("observations") or []
    out: list[tuple[str, float]] = []
    for row in obs:
        if not isinstance(row, dict):
            continue
        d = row.get("date")
        v = row.get("value")
        if not d or v is None or v == "." or v == "":
            continue
        try:
            out.append((d, float(v)))
        except (TypeError, ValueError):
            continue
    return out


def probe_module_b() -> None:
    print("=== Module B — FRED 宏观 ===\n")
    print(f"Base: {FRED_BASE}\nAuth: query api_key=****\n")
    for series_id, col in _FRED_SERIES:
        print(f"——— {col:10s} ({series_id}) ———")
        body = _fred_get(series_id, observation_start=START_FRED_DATE)
        if _is_err(body):
            print(f"  ❌  {body}")
            print()
            time.sleep(SPACING_FRED)
            continue
        obs = body.get("observations") if isinstance(body, dict) else None
        sample = (obs or [])[:2]
        print(f"  raw obs[:2]: {json.dumps(sample, ensure_ascii=False)[:280]}")
        pairs = _fred_parse(body)
        if pairs:
            print(f"  ✅  parsed: date={pairs[0][0]}, value={pairs[0][1]}")
        else:
            n_dot = sum(
                1 for o in (obs or []) if isinstance(o, dict) and o.get("value") == "."
            )
            print(f"  ⚠️  0 解析 row(原始 {len(obs or [])} 条,其中 {n_dot} 个 '.')")
        print()
        time.sleep(SPACING_FRED)


def full_module_b() -> None:
    print("\n=== Module B — Full ===\n")
    pieces: list[pd.DataFrame] = []
    for series_id, col in _FRED_SERIES:
        print(f"  fetching {col:10s}", end=" ... ", flush=True)
        body = _fred_get(series_id, observation_start=START_FRED_DATE)
        pairs = _fred_parse(body)
        if not pairs:
            print(f"0 rows  {body if _is_err(body) else ''}"[:140])
            time.sleep(SPACING_FRED)
            continue
        df = pd.DataFrame(pairs, columns=["date", col])
        df = df.drop_duplicates("date", keep="last").set_index("date")
        pieces.append(df)
        print(f"{len(df)} rows ({df.index.min()} ~ {df.index.max()})")
        time.sleep(SPACING_FRED)
    if not pieces:
        print("\n⚠️  全部 series 空,跳过写文件")
        return
    merged = pd.concat(pieces, axis=1, join="outer").sort_index()
    merged.index.name = "date"
    merged.to_csv(OUT_MACRO, na_rep="")
    print(f"\n✅ {OUT_MACRO}  ({len(merged)} 行 × {len(merged.columns)} 列)")
    print(f"   日期范围: {merged.index.min()} ~ {merged.index.max()}")
    print(f"   各列非空数:\n{merged.notna().sum().to_string(header=False)}")


# ============================================================
# 模块 C — Glassnode 期权
# ============================================================
def _gn_get(path: str, *, params: dict[str, Any]) -> Any:
    url = f"{GN_BASE}{path}?{urlencode(params)}"
    return _http_get(url, headers={"x-key": _env_or_die("GLASSNODE_API_KEY")})


def _gn_parse_tv(raw: Any) -> list[tuple[str, float]]:
    """Glassnode [{t, v}] → [(YYYY-MM-DD, v)]。"""
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
        dt = _ts_to_utc_dt(int(t))
        if dt is None:
            continue
        try:
            out.append((_fmt_date(dt), float(v)))
        except (TypeError, ValueError):
            continue
    return out


def _gn_parse_max_pain_1m(raw: Any) -> list[tuple[str, float]]:
    """Max Pain:[{t, o:{1month, 1w, 3month, 6month, aggregated}}] → 取 1month。"""
    if not isinstance(raw, list):
        return []
    out: list[tuple[str, float]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        t = row.get("t")
        o = row.get("o") or {}
        v = o.get("1month") if isinstance(o, dict) else None
        if t is None or v is None:
            continue
        dt = _ts_to_utc_dt(int(t))
        if dt is None:
            continue
        try:
            out.append((_fmt_date(dt), float(v)))
        except (TypeError, ValueError):
            continue
    return out


_GN_ENDPOINTS: list[dict[str, Any]] = [
    {
        "name": "atm_iv_1m",
        "path": "/v1/metrics/derivatives/options_atm_implied_volatility_1_month",
        "col": "atm_iv_1m",
        "parser": "tv",
    },
    {
        "name": "skew_25d_1m",
        "path": "/v1/metrics/derivatives/options_25delta_skew_1_month",
        "col": "skew_25d_1m",
        "parser": "tv",
    },
    {
        "name": "max_pain_1m",
        "path": "/v1/metrics/options/max_pain",
        "col": "max_pain_1m",
        "parser": "max_pain_1m",
    },
    # ---- 批次 2026-06-10:波段补 3 项(只加进手动脚本,**不**进 cron)----
    {
        "name": "est_leverage_ratio",
        "path": "/v1/metrics/derivatives/futures_estimated_leverage_ratio",
        "col": "est_leverage_ratio",          # 比值(perp OI / 交易所余额),杠杆拥挤度
        "parser": "tv",
    },
    {
        "name": "pcr_volume",
        "path": "/v1/metrics/derivatives/options_volume_put_call_ratio",
        "col": "pcr_volume",                  # 1 上下(成交量口径 PCR)
        "parser": "tv",
    },
    {
        "name": "atm_iv_1w",
        "path": "/v1/metrics/derivatives/options_atm_implied_volatility_1_week",
        "col": "atm_iv_1w",                   # 百分比(年化),1 周 ATM IV
        "parser": "tv",
    },
    # ---- 批次 2026-06-10b:STH 维度(波段尺度的"新钱"行为)----
    {
        "name": "sth_mvrv",
        "path": "/v1/metrics/market/mvrv_less_155",
        "col": "sth_mvrv",                    # ~0.5-2,STH 整体浮盈浮亏比(<1=浮亏)
        "parser": "tv",
    },
    {
        # 派生:供给加权聚合 STH 5 桶(24h/1d_1w/1w_1m/1m_3m/3m_6m)
        "name": "sth_realized_price",
        "path": "DERIVED_STH_REALIZED",
        "col": "sth_realized_price_usd",      # USD,STH 整体平均成本
        "parser": "sth_realized_derived",
    },
]


# STH realized 派生:复用 onchain LTH realized 同样 2 endpoints,但桶反过来
_STH_REALIZED_PATHS: dict[str, str] = {
    "price_by_age": "/v1/metrics/breakdowns/price_realized_usd_by_age",
    "supply_by_age": "/v1/metrics/breakdowns/supply_by_age",
}
_STH_BUCKETS: tuple[str, ...] = ("24h", "1d_1w", "1w_1m", "1m_3m", "3m_6m")


def _gn_parse_by_age(raw: Any) -> dict[int, dict[str, float]]:
    """[{"t": <sec>, "o": {"24h": ..., ...}}, ...] → {t_sec: {bucket: float}}"""
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


def _gn_aggregate_sth_realized(
    price_by_t: dict[int, dict[str, float]],
    supply_by_t: dict[int, dict[str, float]],
) -> list[tuple[str, float]]:
    """STH realized = Σ(price_b × supply_b) / Σ(supply_b),b ∈ _STH_BUCKETS"""
    out: list[tuple[str, float]] = []
    for t in sorted(set(price_by_t) & set(supply_by_t)):
        p = price_by_t[t]
        s = supply_by_t[t]
        num = 0.0
        denom = 0.0
        for b in _STH_BUCKETS:
            pv = p.get(b)
            sv = s.get(b)
            if pv is None or sv is None:
                continue
            num += pv * sv
            denom += sv
        if denom > 0:
            dt = _ts_to_utc_dt(t)
            d = _fmt_date(dt)
            if d:
                out.append((d, num / denom))
    return out


def _gn_fetch_sth_realized(*, since_unix: int | None) -> list[tuple[str, float]]:
    """拉 2 个 breakdowns endpoints + 聚合 STH 5 桶,返 [(date, value), ...]。"""
    p_params: dict[str, Any] = {"a": "BTC", "i": "24h"}
    s_params: dict[str, Any] = {"a": "BTC", "i": "24h"}
    if since_unix:
        p_params["s"] = since_unix
        s_params["s"] = since_unix
    price_raw = _gn_get(_STH_REALIZED_PATHS["price_by_age"], params=p_params)
    time.sleep(SPACING_GN)
    supply_raw = _gn_get(_STH_REALIZED_PATHS["supply_by_age"], params=s_params)
    if _is_err(price_raw) or _is_err(supply_raw):
        return []
    return _gn_aggregate_sth_realized(
        _gn_parse_by_age(price_raw), _gn_parse_by_age(supply_raw),
    )


def probe_module_c() -> None:
    print("=== Module C — Glassnode 期权 + STH on-chain ===\n")
    print(f"Base: {GN_BASE}\nAuth: x-key: ****\n")
    for ep in _GN_ENDPOINTS:
        print(f"——— {ep['name']:20s} ———")
        if ep["parser"] == "sth_realized_derived":
            print(f"  (派生:price_realized_usd_by_age + supply_by_age,STH 5 桶聚合)")
            pairs = _gn_fetch_sth_realized(since_unix=None)
            if pairs:
                print(f"  ✅  parsed: date={pairs[0][0]}, value={pairs[0][1]:.2f}")
                print(f"      latest: date={pairs[-1][0]}, value={pairs[-1][1]:.2f}")
            else:
                print("  ⚠️  STH 派生 0 rows(看 LTH realized 同样路径是否通)")
            print()
            time.sleep(SPACING_GN)
            continue
        print(f"  path: {ep['path']}")
        raw = _gn_get(ep["path"], params={"a": "BTC", "i": "24h"})
        if _is_err(raw):
            print(f"  ❌  {raw}")
            print()
            time.sleep(SPACING_GN)
            continue
        sample = raw[:1] if isinstance(raw, list) else raw
        print(f"  raw[:1]: {json.dumps(sample, ensure_ascii=False)[:280]}")
        if ep["parser"] == "tv":
            pairs = _gn_parse_tv(raw)
        else:
            pairs = _gn_parse_max_pain_1m(raw)
        if pairs:
            print(f"  ✅  parsed: date={pairs[0][0]}, value={pairs[0][1]}")
        else:
            print("  ⚠️  parser 没拿到 row")
        print()
        time.sleep(SPACING_GN)


def _gn_try_fetch_one(ep: dict[str, Any]) -> tuple[pd.DataFrame | None, bool]:
    """单 endpoint 拉 + 解析,返 (df, ok)。"""
    if ep["parser"] == "sth_realized_derived":
        pairs = _gn_fetch_sth_realized(since_unix=START_GN_UNIX)
        if not pairs:
            return None, False
        df = pd.DataFrame(pairs, columns=["date", ep["col"]])
        return df.drop_duplicates("date", keep="last").set_index("date"), True
    raw = _gn_get(ep["path"], params={
        "a": "BTC", "i": "24h", "s": START_GN_UNIX,
    })
    if _is_err(raw):
        return None, False
    pairs = (_gn_parse_tv(raw) if ep["parser"] == "tv"
             else _gn_parse_max_pain_1m(raw))
    if not pairs:
        return None, False
    df = pd.DataFrame(pairs, columns=["date", ep["col"]])
    return df.drop_duplicates("date", keep="last").set_index("date"), True


def full_module_c() -> None:
    print("\n=== Module C — Full ===\n")

    prev_failures = _load_last_failures("swing_module_c")
    prev_failed_names = {f["name"] for f in prev_failures}
    if prev_failures:
        print(f"⚠️  上轮 {len(prev_failures)} 个 endpoint 失败,本轮优先重试:")
        for f in prev_failures:
            print(f"    - {f['name']}")
        print()

    # 优先跑上次失败的
    ordered = (
        [ep for ep in _GN_ENDPOINTS if ep["name"] in prev_failed_names]
        + [ep for ep in _GN_ENDPOINTS if ep["name"] not in prev_failed_names]
    )

    results: dict[str, pd.DataFrame] = {}
    failed_names: list[str] = []
    for ep in ordered:
        marker = " (优先)" if ep["name"] in prev_failed_names else ""
        print(f"  fetching {ep['col']:25s}{marker}", end=" ... ", flush=True)
        df, ok = _gn_try_fetch_one(ep)
        if ok and df is not None:
            results[ep["name"]] = df
            print(f"{len(df)} rows ({df.index.min()} ~ {df.index.max()})")
        else:
            failed_names.append(ep["name"])
            print("FAIL")
        time.sleep(SPACING_GN)

    # Second-pass 自愈
    if failed_names:
        print(f"\n⏳ Second-pass:{len(failed_names)} 个失败,等 90s 后重试")
        time.sleep(90)
        still_failed: list[str] = []
        ep_by_name = {ep["name"]: ep for ep in _GN_ENDPOINTS}
        for name in failed_names:
            ep = ep_by_name[name]
            print(f"  retry {ep['col']:25s}", end=" ... ", flush=True)
            df, ok = _gn_try_fetch_one(ep)
            if ok and df is not None:
                results[name] = df
                print(f"RECOVERED ({len(df)} rows)")
            else:
                still_failed.append(name)
                print("STILL FAIL")
            time.sleep(SPACING_GN)
        failed_names = still_failed

    # 持久化最终失败列表
    final_failures = [
        {"name": ep["name"], "col": ep["col"], "path": ep["path"]}
        for ep in _GN_ENDPOINTS if ep["name"] in failed_names
    ]
    _save_last_failures("swing_module_c", final_failures)
    if final_failures:
        print(f"\n⚠️  最终 {len(final_failures)} 个 endpoint 失败 "
              f"(已写 .last_failures.json,下次 cron 自动优先重试)")
    elif prev_failures:
        print(f"\n✅ 上轮失败的 {len(prev_failures)} 个 endpoint 本轮全部恢复")

    # 重组按原顺序
    pieces: list[pd.DataFrame] = []
    for ep in _GN_ENDPOINTS:
        if ep["name"] in results:
            pieces.append(results[ep["name"]])

    if not pieces:
        print("\n⚠️  全部 endpoint 空,跳过写文件")
        return
    merged = pd.concat(pieces, axis=1, join="outer").sort_index()
    merged.index.name = "date"
    merged.to_csv(OUT_OPTIONS, na_rep="")
    print(f"\n✅ {OUT_OPTIONS}  ({len(merged)} 行 × {len(merged.columns)} 列)")
    print(f"   日期范围: {merged.index.min()} ~ {merged.index.max()}")
    print(f"   各列非空数:\n{merged.notna().sum().to_string(header=False)}")


# ============================================================
# Main
# ============================================================
def main() -> None:
    ap = argparse.ArgumentParser(
        description="BTC 波段历史拉取(CoinGlass + FRED + Glassnode 期权)→ 4 CSV",
    )
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--probe", action="store_true",
                   help="逐 endpoint 拉 2 条样本看字段(请先跑)")
    g.add_argument("--full", action="store_true",
                   help="拉全量 + 写 CSV")
    ap.add_argument("--module", choices=["a", "b", "c"], default=None,
                    help="只跑某个模块(默认 3 模块全跑)")
    args = ap.parse_args()

    do = args.module
    if args.probe:
        if do in (None, "a"):
            probe_module_a()
            print()
        if do in (None, "b"):
            probe_module_b()
            print()
        if do in (None, "c"):
            probe_module_c()
            print()
        print("如全部 ✅ → 跑 --full;如有 ❌/⚠️ → 改 endpoint 配置后重 probe。")
    else:
        if do in (None, "a"):
            full_module_a()
        if do in (None, "b"):
            full_module_b()
        if do in (None, "c"):
            full_module_c()


if __name__ == "__main__":
    main()
