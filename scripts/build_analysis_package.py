#!/usr/bin/env python3
"""scripts/build_analysis_package.py — 打包外部 AI 分析材料 → 1 个 zip

zip 内容(只这 5 类,不读上次报告,不上传):
  1) data/ — 5 个 CSV(项目根目录现有)
  2) snapshot.md — 当前生产 /api/export/snapshot.md 内容
  3) prompts/large_cycle_prompt.txt — Layer A 大周期裁决 prompt
  4) prompts/swing_prompt.md — L1+L2+L3+L4+L5+Master 拼接的波段 prompt
  5) README.md — 包内清单 + 提醒你额外手动加哪些文件

用法:
    python3 scripts/build_analysis_package.py
    # 默认从生产 http://124.222.89.86 拉 snapshot(带 basic auth)
    # 也可指向本地:--snapshot-url http://127.0.0.1:8000/api/export/snapshot.md --no-auth

输出:analysis_package_YYYY-MM-DD.zip(当前目录)。
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

LARGE_CYCLE_PROMPT: str = "src/ai/agents/prompts/layer_a_cycle_adjudicator.txt"

# 波段 prompt 拼接顺序:L1 → L2 → L3 → L4 → L5 → Master
SWING_PROMPT_PARTS: tuple[tuple[str, str], ...] = (
    ("L1 市场状态(regime / 波动率)",
     "src/ai/agents/prompts/l1_regime.txt"),
    ("L2 方向结构(stance / phase / key levels)",
     "src/ai/agents/prompts/l2_direction.txt"),
    ("L3 机会执行(grade / permission / anti-pattern)",
     "src/ai/agents/prompts/l3_opportunity.txt"),
    ("L4 风险失效(risk score / hard invalidation / position cap)",
     "src/ai/agents/prompts/l4_risk.txt"),
    ("L5 宏观(macro stance / extreme event / event risk)",
     "src/ai/agents/prompts/l5_macro.txt"),
    ("Master 综合裁决(thesis / trade plan / break conditions)",
     "src/ai/agents/prompts/master_adjudicator.txt"),
)

DEFAULT_SNAPSHOT_URL = "http://124.222.89.86/api/export/snapshot.md"
# CLAUDE.md 已声明此凭据为公开,可硬编码
DEFAULT_BASIC_AUTH = "btcuser:EF9SiQ1ItWRCZAtt"

README_TEMPLATE = """# BTC 分析包 — {today}

## 📦 本 zip 内容
- `data/` — 5 个 CSV 历史数据
  · `btc_onchain_history.csv`     大周期链上(MVRV-Z/NUPL/SOPR/Liveliness 等 13 列)
  · `btc_swing_deriv_4h.csv`      4h 衍生品(OHLC + funding + OI + 多空比)
  · `btc_swing_deriv_1d.csv`      1d 衍生品(同 4h + 爆仓 + ETF 流 + F&G)
  · `btc_swing_macro.csv`         FRED 宏观(DXY/收益率/VIX/纳指/TIPS)
  · `btc_swing_options.csv`       Glassnode 期权(IV/Skew/Max Pain/PCR/Leverage)
- `snapshot.md`                   当前数据快照(77 个指标 + 抓取时间)
- `prompts/large_cycle_prompt.txt`  大周期裁决 prompt(Layer A)
- `prompts/swing_prompt.md`         波段 prompt(L1+L2+L3+L4+L5+Master 拼接)

## ⚠️ 别忘了!以下文件**不在本包内**,请手动一起上传给外部 AI:
1. **上次大周期报告**(你本地保存的最新一份)
2. **上次波段报告**(同上)
3. **4 张 K 线图**:1m / 4h / 1d / 1w 截图

## 推荐使用流程
1. 把本 zip 解压,**连同**上面 3 类手动文件一起上传到外部 AI 对话
2. 先让 AI 读 `prompts/large_cycle_prompt.txt` + 大周期相关数据(snapshot 链上段 +
   `btc_onchain_history.csv` + `btc_swing_macro.csv`)+ 上次大周期报告 + 1d/1w 图
   → 拿大周期判断
3. 再让 AI 读 `prompts/swing_prompt.md` + 波段相关数据(snapshot 衍生品/期权段 +
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

    # 3. 大周期 prompt(单文件)
    large_cycle_path = PROJECT_ROOT / LARGE_CYCLE_PROMPT
    if not large_cycle_path.exists():
        print(f"❌ 缺 prompt: {LARGE_CYCLE_PROMPT}")
        sys.exit(1)
    print(f"✅ 大周期 prompt {large_cycle_path.stat().st_size} bytes")

    # 4. 波段 prompt(L1-L5 + Master 拼接)
    swing_parts: list[str] = []
    for label, path in SWING_PROMPT_PARTS:
        p = PROJECT_ROOT / path
        if not p.exists():
            print(f"❌ 缺 prompt: {path}")
            sys.exit(1)
        swing_parts.append(f"# ══════════════════════════ {label} ══════════════════════════\n\n")
        swing_parts.append(p.read_text(encoding="utf-8"))
        swing_parts.append("\n\n")
    swing_combined = "".join(swing_parts)
    print(f"✅ 波段 prompt(6 段拼接){len(swing_combined)} bytes")

    # 5. README
    readme = README_TEMPLATE.format(today=today, now_bjt=now_bjt)

    # 6. 打 zip
    print(f"\n打包 → {out_path}")
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in csv_paths:
            z.write(p, arcname=f"{pkg_name}/data/{p.name}")
        z.writestr(f"{pkg_name}/snapshot.md", snapshot_md)
        z.write(large_cycle_path,
                arcname=f"{pkg_name}/prompts/large_cycle_prompt.txt")
        z.writestr(f"{pkg_name}/prompts/swing_prompt.md", swing_combined)
        z.writestr(f"{pkg_name}/README.md", readme)

    size_kb = out_path.stat().st_size / 1024
    print(f"\n✅ 写入 {out_path}")
    print(f"   {size_kb:.0f} KB,9 个文件:")
    print(f"     5 CSV + snapshot.md + 2 prompts + README.md")
    print(f"\n⚠️  上传给 AI 时,别忘了**手动加**:")
    print(f"     - 上次大周期报告")
    print(f"     - 上次波段报告")
    print(f"     - 4 张 K 线图(1m / 4h / 1d / 1w)")


if __name__ == "__main__":
    main()
