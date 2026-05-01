"""scripts/diagnose_orchestrator_real_api.py — Step 5.2 前置真 API 诊断。

目的:逐层调用 6 个 AI(L1/L2/L3/L4/L5/master),独立计时 + 独立 try/except
+ 60s timeout,定位卡点。

不切 BTC_USE_ORCHESTRATOR(.env 不动);用现有 .env 的真 anthropic key。

成本提示:**每次跑约 $0.30**(全 6 AI 输入 ~50k token + 输出 ~10k token)。
失败的层不消耗 token(尚未调出 messages.create)。

用法:
    cd /home/ubuntu/btc_swing_system
    .venv/bin/python scripts/diagnose_orchestrator_real_api.py
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
import traceback
from pathlib import Path

from src.ai.agents import (
    L1RegimeAnalyst,
    L2DirectionAnalyst,
    L3OpportunityAnalyst,
    L4RiskAnalyst,
    L5MacroAnalyst,
    MasterAdjudicator,
)
from src.ai.agents.chart_renderer import ChartRenderer
from src.ai.anti_pattern_signals import compute_anti_pattern_signals
from src.ai.client import build_anthropic_client
from src.ai.context_builder import ContextBuilder
from src.ai.orchestrator import AIOrchestrator


# ============================================================
# 配置
# ============================================================

DB_PATH = "data/btc_strategy.db"
TIMEOUT_SEC = 300.0  # Sprint 1.9-A.5.2 fix:多模态调用慢,提到 300s


def _section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"=== {title}")
    print(f"{'=' * 60}")


def _layer_run(name: str, fn) -> tuple[str, float, str]:
    """跑单层,返回 (status, elapsed_sec, info)。

    fn 是无参 callable,返回 dict(agent.analyze 输出)或 raise。
    """
    print(f"\n--- {name} START ---")
    t0 = time.time()
    try:
        out = fn()
        elapsed = time.time() - t0
        keys = list(out.keys())[:6] if isinstance(out, dict) else "non-dict"
        status_field = (
            out.get("status", "unknown") if isinstance(out, dict) else "unknown"
        )
        # token / model audit
        toks_in = out.get("tokens_in") if isinstance(out, dict) else None
        toks_out = out.get("tokens_out") if isinstance(out, dict) else None
        model = out.get("model_used") if isinstance(out, dict) else None
        print(f"--- {name} OK in {elapsed:.1f}s")
        print(f"    status={status_field!r}, keys={keys}")
        print(f"    tokens_in={toks_in}, tokens_out={toks_out}, model={model}")
        return ("OK", elapsed,
                f"status={status_field}, tokens={toks_in}/{toks_out}, model={model}")
    except Exception as e:
        elapsed = time.time() - t0
        print(f"--- {name} FAIL in {elapsed:.1f}s: {type(e).__name__}: {e}")
        traceback.print_exc(file=sys.stdout)
        return ("FAIL", elapsed, f"{type(e).__name__}: {str(e)[:120]}")


def main() -> int:
    # ------------------------------------------------------------
    # Step 0 — 检查 DB 路径
    # ------------------------------------------------------------
    _section("Step 0: DB + 环境")
    db = Path(DB_PATH)
    if not db.exists():
        print(f"ERROR: DB not found at {DB_PATH} — 请在项目根目录跑")
        return 2
    print(f"DB: {db.resolve()}")

    # ------------------------------------------------------------
    # Step 1 — build_anthropic_client(.env 检查)
    # ------------------------------------------------------------
    _section("Step 1: build_anthropic_client(timeout=60)")
    try:
        client = build_anthropic_client(timeout=TIMEOUT_SEC)
    except Exception as e:
        print(f"build_anthropic_client raised: {type(e).__name__}: {e}")
        traceback.print_exc(file=sys.stdout)
        return 2
    if client is None:
        print("ERROR: build_anthropic_client() returned None")
        print("→ 检查 .env:OPENAI_API_KEY / OPENAI_API_BASE / OPENAI_MODEL")
        return 2
    print(f"client OK (type={type(client).__name__})")

    # ------------------------------------------------------------
    # Step 2 — ContextBuilder.build_full_context()
    # ------------------------------------------------------------
    _section("Step 2: ContextBuilder.build_full_context()")
    t0 = time.time()
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        ctx = ContextBuilder(conn).build_full_context()
    except Exception as e:
        print(f"ContextBuilder raised: {type(e).__name__}: {e}")
        traceback.print_exc(file=sys.stdout)
        return 2
    elapsed = time.time() - t0
    print(f"ContextBuilder OK in {elapsed:.2f}s")
    print(f"  top keys: {sorted(ctx.keys())}")
    print(f"  l1 keys: {sorted(ctx['l1'].keys())}")
    print(f"  l5 keys: {sorted(ctx['l5'].keys())}")
    shared = ctx["_shared"]
    print(f"  current_close={shared.get('current_close')}, "
          f"events_count_72h={shared.get('events_count_72h')}, "
          f"klines_1d rows={len(shared.get('klines_1d'))}")

    # ------------------------------------------------------------
    # Step 3 — render charts(独立测试,失败也继续)
    # ------------------------------------------------------------
    _section("Step 3: chart_renderer(L1 / L2 / L4)")
    chart = ChartRenderer()
    chart_l1 = chart_l2 = chart_l4 = None
    try:
        chart_l1 = chart.render_l1_chart(
            shared["klines_1d"],
            ema_20=shared.get("ema_20_1d"),
            ema_50=shared.get("ema_50_1d"),
            ema_200=shared.get("ema_200_1d"),
            adx=shared.get("adx_14_1d"),
            atr_180d_pct=shared.get("atr_180d_pct_1d"),
            swing_points=shared.get("swing_points_1d"),
        )
        print(f"chart_l1 OK (base64 len={len(chart_l1) if chart_l1 else 'None'})")
    except Exception as e:
        print(f"chart_l1 FAIL: {type(e).__name__}: {e}")
    try:
        chart_l2 = chart.render_l2_chart(
            shared["klines_1d"],
            klines_4h=shared.get("klines_4h"),
            ema_20_1d=shared.get("ema_20_1d"),
            ema_50_1d=shared.get("ema_50_1d"),
            ema_20_4h=shared.get("ema_20_4h"),
            ema_50_4h=shared.get("ema_50_4h"),
            swing_points_1d=shared.get("swing_points_1d"),
        )
        print(f"chart_l2 OK (base64 len={len(chart_l2) if chart_l2 else 'None'})")
    except Exception as e:
        print(f"chart_l2 FAIL: {type(e).__name__}: {e}")
    try:
        chart_l4 = chart.render_l4_chart(
            shared["klines_1d"],
            ema_50=shared.get("ema_50_1d"),
            ema_200=shared.get("ema_200_1d"),
            atr_14=shared.get("atr_14_1d"),
            funding_rate=shared.get("funding_rate_series"),
            open_interest=shared.get("open_interest_series"),
            exchange_net_flow=shared.get("exchange_net_flow_series"),
        )
        print(f"chart_l4 OK (base64 len={len(chart_l4) if chart_l4 else 'None'})")
    except Exception as e:
        print(f"chart_l4 FAIL: {type(e).__name__}: {e}")

    # ------------------------------------------------------------
    # Step 4 — 逐层调用 6 AI
    # ------------------------------------------------------------
    _section("Step 4: 逐层 AI 调用(每层 60s timeout)")
    results: dict[str, tuple[str, float, str]] = {}

    # L1
    def _call_l1():
        l1_input = dict(ctx["l1"])
        l1_input["chart_b64"] = chart_l1
        agent = L1RegimeAnalyst(client=client)
        # 打印 prompt size
        prompt_text = agent._build_user_prompt(l1_input)
        print(f"    L1 user prompt len={len(prompt_text)} char, image={'Y' if chart_l1 else 'N'}")
        return agent.analyze(l1_input)
    results["l1"] = _layer_run("L1", _call_l1)
    l1_out = (
        L1RegimeAnalyst(client=None)._fallback_output()
        if results["l1"][0] != "OK" else None
    )
    # 重新跑一次取真 output(因 _layer_run 没把 out 暴露出来)
    if results["l1"][0] == "OK":
        try:
            l1_input = dict(ctx["l1"]); l1_input["chart_b64"] = chart_l1
            l1_out = L1RegimeAnalyst(client=client).analyze(l1_input)
        except Exception:
            l1_out = L1RegimeAnalyst(client=None)._fallback_output()

    # L2(注入 l1_out)
    def _call_l2():
        l2_input = dict(ctx["l2"])
        l2_input["l1_output"] = l1_out
        l2_input["chart_b64"] = chart_l2
        agent = L2DirectionAnalyst(client=client)
        prompt_text = agent._build_user_prompt(l2_input)
        print(f"    L2 user prompt len={len(prompt_text)} char, image={'Y' if chart_l2 else 'N'}")
        return agent.analyze(l2_input)
    results["l2"] = _layer_run("L2", _call_l2)
    l2_out = (
        L2DirectionAnalyst(client=None)._fallback_output()
        if results["l2"][0] != "OK" else None
    )
    if results["l2"][0] == "OK":
        try:
            l2_input = dict(ctx["l2"]); l2_input["l1_output"] = l1_out
            l2_input["chart_b64"] = chart_l2
            l2_out = L2DirectionAnalyst(client=client).analyze(l2_input)
        except Exception:
            l2_out = L2DirectionAnalyst(client=None)._fallback_output()

    # L5(独立,先于 L3 跑 — orchestrator 同样顺序)
    def _call_l5():
        l5_input = dict(ctx["l5"])
        agent = L5MacroAnalyst(client=client)
        prompt_text = agent._build_user_prompt(l5_input)
        print(f"    L5 user prompt len={len(prompt_text)} char, image=N")
        return agent.analyze(l5_input)
    results["l5"] = _layer_run("L5", _call_l5)
    l5_out = (
        L5MacroAnalyst(client=None)._fallback_output()
        if results["l5"][0] != "OK" else None
    )
    if results["l5"][0] == "OK":
        try:
            l5_out = L5MacroAnalyst(client=client).analyze(dict(ctx["l5"]))
        except Exception:
            l5_out = L5MacroAnalyst(client=None)._fallback_output()

    # L3(注入 l1+l2+anti_pattern)
    def _call_l3():
        anti = compute_anti_pattern_signals(
            l1_output=l1_out, l2_output=l2_out,
            current_close=shared.get("current_close"),
            extreme_event_flags=ctx["l5"].get("extreme_event_flags") or {},
        )
        l3_input = dict(ctx["l3"])
        l3_input["l1_output"] = l1_out
        l3_input["l2_output"] = l2_out
        l3_input["anti_pattern_signals"] = anti
        agent = L3OpportunityAnalyst(client=client)
        prompt_text = agent._build_user_prompt(l3_input)
        print(f"    L3 user prompt len={len(prompt_text)} char, image=N")
        return agent.analyze(l3_input)
    results["l3"] = _layer_run("L3", _call_l3)
    l3_out = (
        L3OpportunityAnalyst(client=None)._fallback_output()
        if results["l3"][0] != "OK" else None
    )
    if results["l3"][0] == "OK":
        try:
            anti = compute_anti_pattern_signals(
                l1_output=l1_out, l2_output=l2_out,
                current_close=shared.get("current_close"),
                extreme_event_flags=ctx["l5"].get("extreme_event_flags") or {},
            )
            l3_input = dict(ctx["l3"])
            l3_input["l1_output"] = l1_out
            l3_input["l2_output"] = l2_out
            l3_input["anti_pattern_signals"] = anti
            l3_out = L3OpportunityAnalyst(client=client).analyze(l3_input)
        except Exception:
            l3_out = L3OpportunityAnalyst(client=None)._fallback_output()

    # L4(注入 l1+l2+l3 + chart)
    def _call_l4():
        l4_input = dict(ctx["l4"])
        l4_input["l1_output"] = l1_out
        l4_input["l2_output"] = l2_out
        l4_input["l3_output"] = l3_out
        l4_input["chart_b64"] = chart_l4
        agent = L4RiskAnalyst(client=client)
        prompt_text = agent._build_user_prompt(l4_input)
        print(f"    L4 user prompt len={len(prompt_text)} char, image={'Y' if chart_l4 else 'N'}")
        return agent.analyze(l4_input)
    results["l4"] = _layer_run("L4", _call_l4)
    l4_out = (
        L4RiskAnalyst(client=None)._fallback_output()
        if results["l4"][0] != "OK" else None
    )
    if results["l4"][0] == "OK":
        try:
            l4_input = dict(ctx["l4"])
            l4_input["l1_output"] = l1_out
            l4_input["l2_output"] = l2_out
            l4_input["l3_output"] = l3_out
            l4_input["chart_b64"] = chart_l4
            l4_out = L4RiskAnalyst(client=client).analyze(l4_input)
        except Exception:
            l4_out = L4RiskAnalyst(client=None)._fallback_output()

    # master(注入 l1-l5 + _system_provided)
    def _call_master():
        crowding_mult = AIOrchestrator._compute_crowding_multiplier(l4_out)
        events_72h = ctx["l5"].get("events_calendar_72h") or []
        event_mult = AIOrchestrator._compute_event_multiplier(events_72h)
        master_input = dict(ctx["master"])
        master_input["l1_output"] = l1_out
        master_input["l2_output"] = l2_out
        master_input["l3_output"] = l3_out
        master_input["l4_output"] = l4_out
        master_input["l5_output"] = l5_out
        master_input["_system_provided"] = {
            "crowding_multiplier": crowding_mult,
            "event_multiplier": event_mult,
            "current_close": shared.get("current_close"),
        }
        agent = MasterAdjudicator(client=client)
        prompt_text = agent._build_user_prompt(master_input)
        print(f"    master user prompt len={len(prompt_text)} char, image=N")
        return agent.analyze(master_input)
    results["master"] = _layer_run("master", _call_master)

    # ------------------------------------------------------------
    # Step 5 — 汇总表
    # ------------------------------------------------------------
    _section("Step 5: 汇总表")
    print(f"{'层':<8} {'状态':<6} {'耗时':<10} {'输出/错误'}")
    print("-" * 80)
    total = 0.0
    for k in ("l1", "l2", "l3", "l4", "l5", "master"):
        status, elapsed, info = results.get(k, ("MISS", 0, "-"))
        total += elapsed
        print(f"{k:<8} {status:<6} {elapsed:>5.1f}s    {info}")
    print("-" * 80)
    print(f"{'TOTAL':<8} {'':<6} {total:>5.1f}s")

    # exit code
    fails = [k for k, v in results.items() if v[0] != "OK"]
    if fails:
        print(f"\nFAILED layers: {fails}")
        return 1
    print(f"\nAll 6 layers OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
