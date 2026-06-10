#!/usr/bin/env python3
"""scripts/build_analysis_package.py — 打包外部 AI 分析材料 → 1 个 zip

zip 内容(只这 3 类,prompt 和上次报告都由用户手动上传):
  1) data/ — 5 个 CSV(项目根目录现有)
  2) snapshot.md — 当前生产 /api/export/snapshot.md 内容
  3) README.md — 包内清单 + 提醒你额外手动加哪些文件

用法:
    python3 scripts/build_analysis_package.py
    # 默认从生产 http://124.222.89.86 拉 snapshot(带 basic auth)
    # 也可指向本地:--snapshot-url http://127.0.0.1:8000/api/export/snapshot.md --no-auth

输出:analysis_package_YYYY-MM-DD.zip(当前目录,7 个文件)。
"""
from __future__ import annotations

import argparse
import base64
import datetime
import sys
import zipfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parent.parent

CSV_FILES: tuple[str, ...] = (
    "btc_onchain_history.csv",
    "btc_swing_deriv_4h.csv",
    "btc_swing_deriv_1d.csv",
    "btc_swing_macro.csv",
    "btc_swing_options.csv",
)

DEFAULT_SNAPSHOT_URL = "http://124.222.89.86/api/export/snapshot.md"
# CLAUDE.md 已声明此凭据为公开,可硬编码
DEFAULT_BASIC_AUTH = "btcuser:EF9SiQ1ItWRCZAtt"

README_TEMPLATE = """# BTC 分析包 — {today}

## 📦 本 zip 内容(7 个文件)
- `data/` — 5 个 CSV 历史数据
  · `btc_onchain_history.csv`     大周期链上(MVRV-Z/NUPL/SOPR/Liveliness 等 13 列)
  · `btc_swing_deriv_4h.csv`      4h 衍生品(OHLC + funding + OI + 多空比)
  · `btc_swing_deriv_1d.csv`      1d 衍生品(同 4h + 爆仓 + ETF 流 + F&G)
  · `btc_swing_macro.csv`         FRED 宏观(DXY/收益率/VIX/纳指/TIPS)
  · `btc_swing_options.csv`       Glassnode 期权(IV/Skew/Max Pain/PCR/Leverage)
- `snapshot.md`                   当前数据快照(77 个指标 + 抓取时间)
- `README.md`                     本文件

## ⚠️ 记得手动加!以下文件**不在本包内**,请一起上传给外部 AI:
1. **大周期 prompt**(你本地自己版本管理)
2. **波段 prompt**(同上)
3. **上次大周期报告**(你本地保存的最新一份)
4. **上次波段报告**(同上)
5. **4 张 K 线图**:1m / 4h / 1d / 1w 截图

## 推荐使用流程
1. 把本 zip 解压,**连同**上面 5 类手动文件一起上传到外部 AI 对话
2. 先让 AI 读你的大周期 prompt + 大周期相关数据(snapshot 链上段 +
   `btc_onchain_history.csv` + `btc_swing_macro.csv`)+ 上次大周期报告 + 1d/1w 图
   → 拿大周期判断
3. 再让 AI 读你的波段 prompt + 波段相关数据(snapshot 衍生品/期权段 +
   `btc_swing_deriv_4h.csv` + `btc_swing_deriv_1d.csv` + `btc_swing_options.csv`)+
   上次波段报告 + 1m/4h 图 → 拿波段判断
4. 把 AI 给的两份报告保存到本地,作为下次的"上次报告"

---
*生成时间: {now_bjt} BJT*
"""


def fetch_snapshot(url: str, basic_auth: str | None) -> str:
    """curl snapshot.md,返回 str。失败抛 RuntimeError。"""
    headers = {"User-Agent": "build-analysis-package/1.0"}
    if basic_auth:
        b64 = base64.b64encode(basic_auth.encode()).decode()
        headers["Authorization"] = f"Basic {b64}"
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8")
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:200]
        raise RuntimeError(f"HTTP {e.code} on snapshot: {body}") from e
    except URLError as e:
        raise RuntimeError(f"URL error: {e}") from e


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--snapshot-url", default=DEFAULT_SNAPSHOT_URL,
                    help=f"默认 {DEFAULT_SNAPSHOT_URL}")
    ap.add_argument("--basic-auth", default=DEFAULT_BASIC_AUTH,
                    help="格式 user:password;--no-auth 关闭")
    ap.add_argument("--no-auth", action="store_true",
                    help="不带 basic auth(本地端点用这个)")
    ap.add_argument("--output-dir", default=".")
    args = ap.parse_args()

    today = datetime.date.today().strftime("%Y-%m-%d")
    now_bjt = (datetime.datetime.utcnow()
               + datetime.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")
    pkg_name = f"analysis_package_{today}"
    out_path = Path(args.output_dir).resolve() / f"{pkg_name}.zip"

    print(f"=== 构建 {pkg_name}.zip ===\n")

    # 1. 检查 5 个 CSV
    csv_paths: list[Path] = []
    missing: list[str] = []
    for name in CSV_FILES:
        p = PROJECT_ROOT / name
        if p.exists():
            csv_paths.append(p)
        else:
            missing.append(name)
    if missing:
        print(f"❌ 缺少 CSV: {missing}")
        print("   请先跑 fetch_btc_onchain_history.py --full + fetch_btc_swing_history.py --full")
        sys.exit(1)
    print(f"✅ 5 个 CSV 都在")
    for p in csv_paths:
        size_kb = p.stat().st_size / 1024
        print(f"    {p.name}  ({size_kb:.0f} KB)")

    # 2. 拉 snapshot
    print(f"\n拉取 snapshot: {args.snapshot_url}")
    auth = None if args.no_auth else args.basic_auth
    try:
        snapshot_md = fetch_snapshot(args.snapshot_url, auth)
    except RuntimeError as e:
        print(f"❌ snapshot 拉取失败: {e}")
        sys.exit(1)
    print(f"✅ snapshot.md {len(snapshot_md)} bytes")

    # 3. README
    readme = README_TEMPLATE.format(today=today, now_bjt=now_bjt)

    # 4. 打 zip
    print(f"\n打包 → {out_path}")
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in csv_paths:
            z.write(p, arcname=f"{pkg_name}/data/{p.name}")
        z.writestr(f"{pkg_name}/snapshot.md", snapshot_md)
        z.writestr(f"{pkg_name}/README.md", readme)

    size_kb = out_path.stat().st_size / 1024
    print(f"\n✅ 写入 {out_path}")
    print(f"   {size_kb:.0f} KB,7 个文件:")
    print(f"     5 CSV + snapshot.md + README.md")
    print(f"\n⚠️  上传给 AI 时,别忘了**手动加**:")
    print(f"     - 大周期 prompt")
    print(f"     - 波段 prompt")
    print(f"     - 上次大周期报告")
    print(f"     - 上次波段报告")
    print(f"     - 4 张 K 线图(1m / 4h / 1d / 1w)")


if __name__ == "__main__":
    main()
