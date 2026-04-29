#!/usr/bin/env python3
"""scripts/check_coinglass_endpoints.py — Sprint 1.5e CoinGlass v4 端点契约体检。

跑 6 类端点 × 6 组 variant,输出 markdown 表格,推荐"首个成功 variant"。

用途:CoinGlass / 中转站契约 drift 早期发现 — 每次部署后跑一次,
未来 contract 再变能立即定位是哪个 endpoint。

用法:
    .venv/bin/python scripts/check_coinglass_endpoints.py
    .venv/bin/python scripts/check_coinglass_endpoints.py --markdown > /tmp/cg_check.md
"""

from __future__ import annotations

import argparse
import logging
import sys
import traceback
from pathlib import Path
from typing import Any

# 让脚本可独立执行
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


_VARIANTS_SINGLE = [
    {"symbol": "BTCUSDT", "exchange": "Binance"},
    {"symbol": "BTCUSDT", "exchange": "Bybit"},
    {"symbol": "BTCUSDT", "exchange": "OKX"},
    {"symbol": "BTC", "exchange": "Binance"},
    {"symbol": "BTC"},
    {"pair": "BTCUSDT", "exchange": "Binance"},
]

_VARIANTS_AGG = [
    {"symbol": "BTC"},
    {"symbol": "BTCUSDT"},
    {"symbol": "BTC", "exchange_list": "Binance,OKX,Bybit"},
]


_ENDPOINTS = [
    # name, path_attr, category(single/aggregate)
    ("liquidation",          "_PATH_LIQUIDATION",   "single"),
    ("global_long_short",    "_PATH_LONG_SHORT",    "single"),
    ("net_position",         "_PATH_NET_POSITION",  "single"),
    ("funding_single",       "_PATH_FUNDING",       "single"),
    ("open_interest_agg",    "_PATH_OI",            "agg"),
    ("funding_agg",          "_PATH_FUNDING_AGG",   "agg"),
]


def _check_one(cg, name: str, path: str, params: dict[str, Any]) -> tuple[str, int, str]:
    """返回 (status, n_rows, sample_keys)。"""
    try:
        body = cg._request(
            "GET", path,
            params={**params, "interval": "1h", "limit": 24},
        )
        rows = cg._unwrap_data(body) or []
        n = len(rows) if isinstance(rows, list) else 0
        sample_keys = ""
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            sample_keys = ",".join(list(rows[0].keys())[:6])
        if n > 0:
            return "✅ OK", n, sample_keys
        return "⚠️ empty", 0, sample_keys
    except Exception as e:
        return f"❌ {type(e).__name__}", 0, str(e)[:60]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--markdown", action="store_true",
                    help="只输出 markdown(给 sprint 报告嵌入)")
    args = ap.parse_args(argv)

    # quiet logger;只用 print
    logging.basicConfig(level=logging.WARNING)

    from src.data.collectors.coinglass import CoinglassCollector
    cg = CoinglassCollector()

    out: list[str] = []
    out.append("# CoinGlass v4 endpoint contract check")
    out.append("")
    out.append(f"| endpoint | category | variant | result | n_rows | sample_keys |")
    out.append(f"|---|---|---|---|---|---|")

    recommendations: dict[str, str] = {}
    for name, path_attr, category in _ENDPOINTS:
        path = getattr(cg, path_attr)
        variants = _VARIANTS_AGG if category == "agg" else _VARIANTS_SINGLE
        first_ok: str | None = None
        for v in variants:
            status, n, keys = _check_one(cg, name, path, v)
            row_ok = "OK" in status
            v_str = ",".join(f"{k}={v[k]}" for k in v)
            out.append(
                f"| `{name}` | {category} | `{v_str}` | {status} "
                f"| {n} | `{keys}` |"
            )
            if row_ok and first_ok is None:
                first_ok = v_str
        recommendations[name] = first_ok or "❌ 全部 variant 失败"

    out.append("")
    out.append("## Recommended variants(首个成功)")
    out.append("")
    for name, rec in recommendations.items():
        out.append(f"- `{name}` → `{rec}`")

    print("\n".join(out))
    # exit 1 if any endpoint has no successful variant
    if any("❌" in v for v in recommendations.values()):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
