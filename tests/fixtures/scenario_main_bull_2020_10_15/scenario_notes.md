# Scenario 1 — Main Bull Breakout (2020-10-15)

## 历史背景

2020 年 10 月 15 日是 BTC 进入**主升浪前夜**的典型节点:

- BTC 刚从 9 月底的 $10,100 低点反弹至 $11,400,突破关键的 $11K 阻力
- 3 月新冠崩盘后 6 个月,市场已从 $3,800 低点修复,并站稳 MA-200 日线上方
- 前 60 天呈现标准的牛市吸筹走势:多次 HH+HL,MA-20 > MA-60 > MA-120 向上排列
- 减半(2020-05-11)过去约 5 个月,正是建模 §3.8.4 中 `early_bull` 档位的经典时间窗
- 链上 MVRV Z-Score 约 1.2(mid-range),NUPL 约 0.37(optimism zone)—— 明确的 early_bull 特征
- LTH(长期持有者)在 90 日滚动窗口内持续增持 ~+1.5%,典型牛市吸筹

## 宏观环境

- 美元指数 DXY 走弱(20 日 -1.2%),VIX 27.5 偏高(大选前溢价),但纳指 +2.5% 20日 呈上升势
- US10Y 利率 0.72%,零利率环境提供风险资产长期顺风
- BTC-纳指 60 日相关性约 0.35,仍较独立于美股

## 衍生品

- 资金费率温和正(0.012%),无拥挤迹象
- OI $2.4B(2020 年水平,现在看很小)
- 多空账户比 1.6,轻度多头偏置但非极端
- 基差年化 4%,健康

## 为什么选这一天

这一天**能触发一系列关键证据层规则**,用于单元测试:

| 检验目标 | 期望触发 |
|---|---|
| L1 regime 识别 transition_up | 4H/1D/1W 方向一致 + ADX 刚过 22-25 边界 |
| L2 stance bullish + 通过 early_bull 门槛 | stance_confidence 应落在 [0.60, 0.72],清 0.55 阈值 |
| L2 cycle_position → early_bull | MVRV Z 1.2 + NUPL 0.37 + LTH +1.5% 三指标投票 |
| L3 opportunity_grade = B(可能 A) | 符合 long_grade_rules.B 全部条件 |
| L4 overall_risk = moderate | 无拥挤无事件无极端 → moderate 兜底 |
| L5 macro neutral-to-tailwind | DXY 弱 + 纳指上 + VIX 偏高 → 混合信号 |
| 状态机 FLAT → LONG_PLANNED | Grade B + bullish + can_open 满足迁移条件 |

## 预期 M26 可交易性验收结果

- **场景类型**:主升浪(uptrend)
- **M26 要求**(thresholds.kpi_tracker.uptrend_capture):主升浪区间(涨幅 > 40%,持续 > 60 天)内**至少一次 A 或 B 级 LONG_PLANNED 或 LONG_OPEN 触发**
- **预期结果**:PASS。此场景下系统应输出 `chosen_action_state = LONG_PLANNED`,opportunity_grade 为 B(或 A)
- **验收失败信号**:如果系统在此场景输出 `FLAT` 或 `neutral` 或 `grade=none`,说明 L2/L3 阈值设定过严,漏掉早期趋势
- **验收失败补救**:thresholds.layer_1_regime.adx.strong_threshold 从 25 降到 22,或 layer_2_direction.dynamic_direction_thresholds.early_bull.long 从 0.55 降到 0.50(并 bump rules_version)

## 使用方式(Sprint 1 单元测试)

```python
import json
from pathlib import Path

FIXTURE_DIR = Path("tests/fixtures/scenario_main_bull_2020_10_15")
raw = json.loads((FIXTURE_DIR / "raw_data.json").read_text())
expected = json.loads((FIXTURE_DIR / "expected_evidence_outputs.json").read_text())

# 把 raw.klines_1d.series 输入 L1 计算
from src.evidence.layer1_regime import compute as l1_compute
l1_result = l1_compute(raw["klines_1d"]["series"], ...)

# 验证落在预期范围内
assert l1_result.regime in {
    expected["expected_layer_1_regime"]["regime_primary"],
    *expected["expected_layer_1_regime"]["regime_primary_alternatives"],
}
```

---

**注意**:本场景的 K 线数据为**种子化构造**(numpy seed=42),非真实历史数据。数值经过校准以触发预期证据层输出。真实历史数据可在 Sprint 1 后通过 `scripts/backfill_data.py` 从 Binance 拉取并替换。
