"""scripts/probe_stooq_tickers.py — Sprint 2.6-A.2 临时探测工具。

逐个测试 Stooq 候选 ticker 是否真实可用。Stooq.com 不强制 API key,
通过 CSV 下载接口拉取历史数据。
不同 ticker 命名规则各不相同(指数 ^XXX、期货 .F 后缀、外汇直接全大写),
本脚本枚举每个宏观指标的多个候选,选第一个返回有效 CSV 的作为 winner。

用法:
    .venv/bin/python scripts/probe_stooq_tickers.py

输出:
    控制台逐 ticker 打印 ✓/✗ + 行数 + 最新收盘价
    末尾打印"最终选定 ticker map",可直接搬到 stooq.py 的 SYMBOL_TO_METRIC

修改 ticker 映射前必须重跑本脚本验证!
"""

from __future__ import annotations

import sys
from io import StringIO

import pandas as pd
import requests


CANDIDATES: list[tuple[str, list[str]]] = [
    # (metric_name, [ticker 候选,按优先级排])
    ("dxy",        ["^DXY", "DX.F", "DX-Y.NYB"]),
    ("us10y",      ["^TNX", "10USY.B", "US10Y"]),
    ("vix",        ["^VIX", "VIX.US"]),
    ("sp500",      ["^SPX", "SPX", "^GSPC"]),
    ("nasdaq",     ["^NDQ", "^IXIC", "^NDX", "NDX"]),
    ("gold_price", ["XAUUSD", "GC.F", "GC=F"]),
]

BASE_URL = "https://stooq.com/q/d/l/?s={ticker}&i=d"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; btc_swing_system/0.1)"}
TIMEOUT = 15


def probe(ticker: str) -> dict:
    try:
        url = BASE_URL.format(ticker=ticker)
        r = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
        if not r.ok:
            return {"ok": False, "reason": f"HTTP {r.status_code}"}
        text = r.text
        if "No data" in text or len(text) < 50:
            return {"ok": False, "reason": "empty/no data"}
        df = pd.read_csv(StringIO(text))
        if df.empty or "Close" not in df.columns:
            return {"ok": False,
                    "reason": f"bad CSV cols={list(df.columns)[:5]}"}
        return {
            "ok": True,
            "rows": len(df),
            "latest_date": str(df.iloc[-1].get("Date")),
            "latest_close": float(df.iloc[-1].get("Close")),
        }
    except Exception as e:
        return {"ok": False, "reason": f"{type(e).__name__}: {e}"}


def main() -> int:
    print(f"{'metric':12s} {'ticker':12s} {'status':6s} {'rows':>6s}  "
          f"{'latest':12s}  notes")
    print("-" * 90)
    final_map: dict[str, str] = {}
    for metric, candidates in CANDIDATES:
        winner = None
        for ticker in candidates:
            res = probe(ticker)
            if res["ok"]:
                print(f"{metric:12s} {ticker:12s} {'OK':6s} "
                      f"{res['rows']:>6d}  {res['latest_date']:12s}  "
                      f"close={res['latest_close']:.4f}")
                if winner is None:
                    winner = ticker
            else:
                print(f"{metric:12s} {ticker:12s} {'FAIL':6s} "
                      f"{'':>6s}  {'':12s}  {res['reason']}")
        if winner:
            final_map[metric] = winner
        else:
            print(f"  ⚠ {metric} 无可用 ticker")
    print()
    print("=== 最终选定 ticker map(可直接搬到 stooq.py SYMBOL_TO_METRIC)===")
    for metric, ticker in final_map.items():
        print(f'    "{ticker}": "{metric}",')
    return 0 if len(final_map) >= 5 else 1


if __name__ == "__main__":
    sys.exit(main())
