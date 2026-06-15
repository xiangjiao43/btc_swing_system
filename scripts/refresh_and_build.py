#!/usr/bin/env python3
"""scripts/refresh_and_build.py — 一键:fetch → 校验 → 打包 → 告警

流程:
  1) 跑 fetch_btc_onchain_history.py --full       (大周期 13 列)
  2) 跑 fetch_btc_swing_history.py --full          (波段 A+B+C 全 4 CSV)
  3) 校验 5 项硬指标(任何 1 项失败 → 不打包 + 告警):
       a) 5 个 CSV 最新日期都不早于"今日 -2 天"(允许 T-1 + 1 天容忍)
       b) 新增列(批 1/2/3 加的 10 列)latest 行非空
       c) snapshot.md "真异常" 数 = 0
       d) 锚点:snapshot 的 BTC 现价 vs btc_swing_deriv_1d.csv 最新 close,
          相对差 < 1%
       e) snapshot 端点 HTTP 200(API 服务存活)
  4) 通过 → 跑 build_analysis_package.py,zip 写到 packages/
  5) 失败 → 告警(Server酱/邮件/log 任一,见 NOTIFY_BACKEND env)

cron 用法(BJT 11:00,在服务器 crontab 里):
    0 11 * * * cd /home/ubuntu/btc_swing_system && \\
        /usr/bin/env -i HOME=/home/ubuntu PATH=/usr/bin:/usr/local/bin \\
        SERVER_CHAN_KEY=<your_key> \\
        /home/ubuntu/btc_swing_system/.venv/bin/python \\
        scripts/refresh_and_build.py >> logs/refresh.log 2>&1

环境变量:
    COINGLASS_API_KEY / GLASSNODE_API_KEY / GN_API_KEY / FRED_API_KEY
        必需(同 fetch 脚本)
    SERVER_CHAN_KEY   可选,Server 酱 SENDKEY → 推微信
    NOTIFY_EMAIL      可选,SMTP 收件人(需配合 SMTP_* 环境变量)
    SNAPSHOT_URL      可选,默认 http://127.0.0.1:8000/api/export/snapshot.md
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKAGES_DIR = PROJECT_ROOT / "packages"
LOGS_DIR = PROJECT_ROOT / "logs"
STATE_FILE = PROJECT_ROOT / ".pipeline_state.json"
BJT = timezone(timedelta(hours=8))


def _load_dotenv() -> int:
    """启动时自源 .env(根治 2026-06-15 5 天 cron 全失败的根因:
    cron 命令行不 source .env → 所有 API_KEY 全空 → 脚本 1 秒退出)。
    手动 SSH 跑也兼容(os.environ.setdefault 不覆盖已有值)。返回加载的 KV 数。
    """
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return 0
    n = 0
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v
            n += 1
    return n

DEFAULT_SNAPSHOT_URL = os.environ.get(
    "SNAPSHOT_URL", "http://127.0.0.1:8000/api/export/snapshot.md",
)

# 5 CSV → 各自 "最新日期最少不能早于今日-N天"
# (考虑 Glassnode T-1 + 周末 + FRED H.10 周更)
CSV_FRESHNESS: dict[str, int] = {
    "btc_onchain_history.csv": 2,      # Glassnode T-1
    "btc_swing_deriv_4h.csv": 1,       # CG 实时
    "btc_swing_deriv_1d.csv": 1,       # CG 实时
    "btc_swing_macro.csv": 7,          # FRED H.10 周更 + 周末
    "btc_swing_options.csv": 2,        # Glassnode T-1
}

# 新增列(批 1+2+3)latest 行非空检查
NEW_COLS_CHECK: dict[str, list[str]] = {
    "btc_onchain_history.csv": [
        "liveliness", "illiquid_supply_btc", "nrpl_usd",
        "lth_profit_btc", "lth_loss_btc", "sopr", "sopr_adjusted",
        "lth_nupl_ratio",   # 批 2026-06-10b
    ],
    "btc_swing_options.csv": [
        "est_leverage_ratio", "pcr_volume", "atm_iv_1w",
        "sth_mvrv", "sth_realized_price_usd",   # 批 2026-06-10b
    ],
}


# ============================================================
# 工具
# ============================================================
def log(msg: str) -> None:
    ts = datetime.now(BJT).strftime("%Y-%m-%d %H:%M:%S BJT")
    print(f"[{ts}] {msg}", flush=True)


def _prepare_env() -> dict[str, str]:
    """父进程继承 + key 别名映射(项目历史 env 名不统一)。"""
    env = os.environ.copy()
    # onchain 脚本读 GN_API_KEY;服务器 .env 里通常是 GLASSNODE_API_KEY
    if not env.get("GN_API_KEY") and env.get("GLASSNODE_API_KEY"):
        env["GN_API_KEY"] = env["GLASSNODE_API_KEY"]
    return env


def run_subprocess(cmd: list[str], label: str) -> int:
    """跑子进程,实时输出。返 exit code。"""
    log(f"=== 跑 {label} ===")
    log(f"    {' '.join(cmd)}")
    try:
        res = subprocess.run(cmd, cwd=str(PROJECT_ROOT), env=_prepare_env())
        log(f"    {label} exit={res.returncode}")
        return res.returncode
    except Exception as e:
        log(f"    {label} 启动失败: {e}")
        return -1


def http_get(url: str) -> tuple[int, str]:
    req = Request(url, headers={"User-Agent": "refresh-and-build/1.0"})
    try:
        with urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8")
    except URLError as e:
        return -1, f"URL err: {e}"
    except Exception as e:
        return -2, f"{type(e).__name__}: {e}"


# ============================================================
# 告警(Server 酱默认 / log 兜底)
# ============================================================
def notify(title: str, content: str) -> None:
    """告警通道。SERVER_CHAN_KEY 配置 → 推微信;否则 stdout 显眼标记。"""
    log(f"⚠️  ALERT: {title}")
    log(f"    {content}")

    key = os.environ.get("SERVER_CHAN_KEY")
    if key:
        url = f"https://sctapi.ftqq.com/{key}.send"
        data = urllib.parse.urlencode({
            "title": title,
            "desp": content,
        }).encode()
        try:
            with urlopen(url, data=data, timeout=10) as resp:
                body = resp.read().decode("utf-8", errors="replace")[:200]
                if resp.status == 200:
                    log(f"    ✅ Server酱推送成功")
                else:
                    log(f"    ❌ Server酱推送返 {resp.status}: {body}")
        except Exception as e:
            log(f"    ❌ Server酱推送异常: {e}")
        return

    # TODO:其他渠道(邮件 / TG / Webhook)按需扩展
    log("    (未设置 SERVER_CHAN_KEY,仅 log 显示;cron 用户请检查 stderr)")


# ============================================================
# 校验 5 项
# ============================================================
def validate() -> list[str]:
    """返回 errors 列表;空 = 全部通过。"""
    errors: list[str] = []
    today_bjt = datetime.now(BJT).date()
    log("=== 校验 ===")

    # a) 5 CSV 新鲜度
    log("--- a) CSV 最新日期 ---")
    for csv_name, max_lag in CSV_FRESHNESS.items():
        p = PROJECT_ROOT / csv_name
        if not p.exists():
            errors.append(f"[a] CSV 缺失: {csv_name}")
            continue
        try:
            df = pd.read_csv(p)
            if "date" not in df.columns:
                errors.append(f"[a] {csv_name}: 没有 date 列")
                continue
            # date 可能是 "YYYY-MM-DD" 或 "YYYY-MM-DD HH:MM"
            latest_str = str(df["date"].max())[:10]
            latest = datetime.strptime(latest_str, "%Y-%m-%d").date()
            lag_days = (today_bjt - latest).days
            if lag_days > max_lag:
                errors.append(
                    f"[a] {csv_name}: latest {latest} (lag {lag_days}d > 阈值 {max_lag}d)"
                )
            else:
                log(f"    ✅ {csv_name}: latest {latest} (lag {lag_days}d)")
        except Exception as e:
            errors.append(f"[a] {csv_name}: 读取异常 {type(e).__name__}: {e}")

    # b) 新增列非空
    log("--- b) 新增列 latest 行非空 ---")
    for csv_name, cols in NEW_COLS_CHECK.items():
        p = PROJECT_ROOT / csv_name
        if not p.exists():
            continue   # a) 已报
        try:
            df = pd.read_csv(p)
            # 按 date 排序找最新行
            df = df.sort_values("date").reset_index(drop=True)
            if df.empty:
                errors.append(f"[b] {csv_name}: 空表")
                continue
            latest_row = df.iloc[-1]
            for col in cols:
                if col not in df.columns:
                    errors.append(f"[b] {csv_name}: 缺列 {col}")
                elif pd.isna(latest_row[col]):
                    errors.append(f"[b] {csv_name} 最新行 {col} 为空")
                else:
                    log(f"    ✅ {csv_name}.{col}: {latest_row[col]}")
        except Exception as e:
            errors.append(f"[b] {csv_name}: 异常 {type(e).__name__}: {e}")

    # c+e) snapshot 端点 + 真异常
    log("--- c+e) snapshot 端点 + 真异常 ---")
    status, body = http_get(DEFAULT_SNAPSHOT_URL)
    if status != 200:
        errors.append(f"[e] snapshot HTTP {status}: {body[:200]}")
        snapshot_body = ""
    else:
        snapshot_body = body
        log(f"    ✅ snapshot HTTP 200 ({len(body)} bytes)")
        m = re.search(r"真异常\s+(\d+)", body)
        if not m:
            errors.append("[c] snapshot 缺真异常统计行")
        else:
            n = int(m.group(1))
            if n == 0:
                log(f"    ✅ snapshot 真异常 = 0")
            else:
                detail_m = re.search(r"真异常：([^\n]+)", body)
                detail = detail_m.group(1) if detail_m else "?"
                errors.append(f"[c] snapshot 真异常 = {n}: {detail}")

    # d) 锚点:BTC 现价 snapshot vs CSV 1d close
    log("--- d) 锚点 BTC 现价 ---")
    if snapshot_body:
        m = re.search(r"BTC 现价: \$([\d,]+\.?\d*)", snapshot_body)
        csv_1d = PROJECT_ROOT / "btc_swing_deriv_1d.csv"
        if not m:
            errors.append("[d] snapshot 没找到 BTC 现价行")
        elif not csv_1d.exists():
            pass   # a) 已报
        else:
            try:
                snap_price = float(m.group(1).replace(",", ""))
                df = pd.read_csv(csv_1d).sort_values("date").reset_index(drop=True)
                csv_close = float(df["close"].iloc[-1])
                rel = abs(snap_price - csv_close) / snap_price
                # 5% 容差(2026-06-12 由 1% 放宽):snapshot 现价是 HTTP 调用
                # 时刻的实时值,CSV 是 BJT 11:00 cron 那一刻的截图,**同一日内
                # 不同时刻**,BTC 盘中波动 2-4% 常态。5% 才是"正常波动 vs
                # 数据错乱"的合理分界。CSV 真停在旧日期由 gate (a) 单独抓。
                if rel > 0.05:
                    errors.append(
                        f"[d] 锚点偏离: snapshot ${snap_price:.2f} "
                        f"vs CSV ${csv_close:.2f} (差 {rel * 100:.2f}% > 5%)"
                    )
                else:
                    log(f"    ✅ 锚点: snapshot ${snap_price:.2f} ≈ CSV ${csv_close:.2f} (差 {rel * 100:.2f}%, 阈值 5%)")
            except Exception as e:
                errors.append(f"[d] 锚点计算异常: {type(e).__name__}: {e}")

    return errors


# ============================================================
# Main
# ============================================================
def _load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {"last_success_at": None, "consecutive_failures": 0,
                "last_failure_reason": None, "last_failure_at": None}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"last_success_at": None, "consecutive_failures": 0,
                "last_failure_reason": None, "last_failure_at": None}


def _save_state(state: dict[str, Any]) -> None:
    try:
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    except Exception as e:
        log(f"⚠️  state 写入失败: {e}")


def _mark_success(state: dict[str, Any]) -> None:
    state["last_success_at"] = datetime.now(BJT).strftime("%Y-%m-%d %H:%M BJT")
    state["consecutive_failures"] = 0
    state["last_failure_reason"] = None
    state["last_failure_at"] = None
    _save_state(state)


def _mark_failure(state: dict[str, Any], reason: str) -> int:
    state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
    state["last_failure_reason"] = reason
    state["last_failure_at"] = datetime.now(BJT).strftime("%Y-%m-%d %H:%M BJT")
    _save_state(state)
    return state["consecutive_failures"]


def run_with_retry(cmd: list[str], label: str, max_retries: int = 1,
                   retry_sleep: int = 60) -> int:
    """跑子进程,失败自动重试 max_retries 次,间隔 retry_sleep 秒。返 final exit code。"""
    for attempt in range(max_retries + 1):
        rc = run_subprocess(cmd, label + (
            f" (重试 {attempt}/{max_retries})" if attempt > 0 else ""
        ))
        if rc == 0:
            return 0
        if attempt < max_retries:
            log(f"  ⏳ {label} 失败,{retry_sleep}s 后重试")
            time.sleep(retry_sleep)
    return rc


def main() -> int:
    LOGS_DIR.mkdir(exist_ok=True)
    PACKAGES_DIR.mkdir(exist_ok=True)

    # 2026-06-15 根治:启动时自加载 .env(crontab 不 source .env 也能跑)
    n_env = _load_dotenv()

    log("=" * 60)
    log("refresh_and_build 启动")
    log(f"  .env 加载: {n_env} 个 KV")
    log("=" * 60)

    state = _load_state()

    # Step 1: fetch onchain — 1 次重试
    rc = run_with_retry(
        [sys.executable, "scripts/fetch_btc_onchain_history.py", "--full"],
        "fetch onchain --full",
    )
    if rc != 0:
        n_fail = _mark_failure(state, f"onchain fetch exit={rc}")
        notify(f"BTC pipeline failed: onchain fetch (连续 {n_fail} 天)",
               f"fetch_btc_onchain_history.py exit={rc}\n"
               f"上次成功: {state.get('last_success_at') or '(从未)'}\n"
               f"详情:`tail -100 logs/refresh.log`")
        return 10

    # Step 2: fetch swing — 1 次重试
    rc = run_with_retry(
        [sys.executable, "scripts/fetch_btc_swing_history.py", "--full"],
        "fetch swing --full",
    )
    if rc != 0:
        n_fail = _mark_failure(state, f"swing fetch exit={rc}")
        notify(f"BTC pipeline failed: swing fetch (连续 {n_fail} 天)",
               f"fetch_btc_swing_history.py exit={rc}\n"
               f"上次成功: {state.get('last_success_at') or '(从未)'}\n"
               f"详情:`tail -100 logs/refresh.log`")
        return 11

    # Step 3: 校验
    errors = validate()
    if errors:
        n_fail = _mark_failure(state, f"校验未过 {len(errors)} 项")
        body = "\n".join(f"  - {e}" for e in errors)
        notify(
            f"BTC pipeline failed: 校验未过 ({len(errors)} 项,连续 {n_fail} 天)",
            f"今日不打包。失败项:\n{body}\n\n"
            f"上次成功:{state.get('last_success_at') or '(从未)'}\n"
            f"快照: {DEFAULT_SNAPSHOT_URL}",
        )
        return 20
    log("✅ 校验 5 项全过")

    # Step 4: 打包
    rc = run_subprocess(
        [sys.executable, "scripts/build_analysis_package.py",
         "--output-dir", str(PACKAGES_DIR)],
        "build_analysis_package",
    )
    if rc != 0:
        n_fail = _mark_failure(state, f"build exit={rc}")
        notify(f"BTC pipeline failed: build_analysis_package (连续 {n_fail} 天)",
               f"build_analysis_package exit={rc}")
        return 30

    today_bjt = datetime.now(BJT).strftime("%Y-%m-%d")
    pkg = PACKAGES_DIR / f"analysis_package_{today_bjt}.zip"
    if pkg.exists():
        size_kb = pkg.stat().st_size / 1024
        log(f"✅ {pkg.name} ({size_kb:.0f} KB)")
        log(f"   下载 URL:http://124.222.89.86/api/export/pack/today.zip")
        _mark_success(state)
    else:
        n_fail = _mark_failure(state, f"build exit=0 but zip missing")
        notify(f"BTC pipeline 异常 (连续 {n_fail} 天)",
               f"build 报 exit=0 但 zip 不存在: {pkg}")
        return 31

    log("=" * 60)
    log("refresh_and_build 完成 ✅")
    log("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
