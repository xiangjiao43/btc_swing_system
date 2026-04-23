# Scenario 2 — Main Bear Breakdown (2022-05-01)

## 历史背景

2022 年 5 月 1 日是 BTC **主跌浪中段**的典型节点,选在 **Luna/UST 崩盘(5 月 9-12 日)前 1-1.5 周**:

- BTC 从 2021-11 的 $69,000 ATH 持续下跌,5 月初跌至 $38,000(回撤约 45%)
- 4 月下旬刚跌破 $40,000 心理位和 200 日 MA,技术面严重破位
- MA 排列转为典型熊市:MA-20 < MA-60 < MA-120 < MA-200
- 链上 MVRV Z 从 distribution 区间(> 6)下行至 0.3,接近已实现价格
- LTH 在 90 日窗口内首次持续减持 ~-1.8%,典型早期熊市分发
- NUPL 0.18 进入 fear 区间

## 宏观环境(关键)

这一天是 **FOMC 2022-05-04 决议前 3 天**,市场已在 pricing in 50bp+ 加息:

- DXY +2.8% 20 日涨势(远超 +2% 阈值)—— 强烈风险厌恶
- US10Y 30 日上行 45bp(远超 +30bp 阈值)—— 利率加速上行
- VIX 33.4 处于 elevated 区间
- 纳指 20 日 -8.7%(远超 -5% 阈值)—— 科技股崩塌
- BTC-纳指 60 日相关性 0.81(> 0.7)—— 强联动触发 MacroHeadwind 权重 × 1.5
- 四项宏观逆风全部触发 → macro_headwind_score 饱和至 -10

## 衍生品(压力信号集中)

- 资金费率持续负(-0.015%),多头已持续支付空头
- OI $14.5B 虽高但 24h -4%,强制去杠杆开始
- 多空账户比跌至 0.82(散户偏空),但大户偏多轻微转变
- PCR(put/call OI 比)1.35 —— 看跌期权主导,恐慌明显
- 基差年化压缩至 1.5%(从牛市的 15%+ 崩塌)
- 24h 清算 $2.1 亿,远高于正常值

## 为什么选这一天

这一天是 **M26 可交易性验收场景 2 的理想样本** —— 系统必须能在此场景给出**多头离场或空头建议**:

| 检验目标 | 期望触发 |
|---|---|
| L1 regime 识别 trend_down | ADX(1d) ≥ 25 向下,多 TF 一致,truth_trend ≥ 6 |
| L1 volatility elevated | ATR 分位 70-85 |
| L2 stance bearish + 通过 early_bear 门槛 | stance_confidence 0.62-0.75,清 0.55(early_bear) |
| L2 cycle_position → early_bear | MVRV Z 0.3 + NUPL 0.18 + LTH -1.8% + ath_drawdown 45% 触发 aux_min_ath_drawdown_pct 0.20 |
| L3 opportunity_grade = A 或 B(做空)| 符合 short_grade_rules:cycle ∈ {dist, early_bear, mid_bear} + bearish + truth_trend ≥ 6 + crowding 大致 ≥ 5 |
| L4 overall_risk = elevated | funding extreme + leverage stretched + 事件窗口 |
| L4 position_cap 触发硬下限 | 0.7 × 0.7-0.85 × 0.7 × 0.7 → 约 15-20% → 硬下限 15% 生效 |
| L5 macro_headwind 饱和 -10 | 4 项全触发 × 1.5 相关性放大 |
| EventRisk 高档 | FOMC +3 天(< 72h) |
| 状态机 FLAT → SHORT_PLANNED 或 LONG_EXIT | 视上一态;两者都合法 |

## 预期 M26 可交易性验收结果

- **场景类型**:主跌浪(downtrend)
- **M26 要求**(thresholds.kpi_tracker.downtrend_response):主跌浪区间(从 ATH 跌 > 30%,持续 > 45 天)内**至少一次 LONG_EXIT 或 SHORT 信号**
- **预期结果**:PASS。系统应输出 `chosen_action_state = SHORT_PLANNED`(若上一态为 FLAT)或 `LONG_EXIT`(若持多)
- **验收失败信号**:如果系统在此场景依然 `FLAT` 或 `LONG_HOLD`,说明 L2 方向识别或 L3 做空判档过保守
- **验收失败补救**:可能是 L2 的 early_bear 辅助条件(ath_drawdown)过严,或 L3 做空的 truth_trend 门槛过严

## 特别关注点

1. **position_cap 硬下限测试**:此场景 position_cap 合成链路各乘数均触发,是**验证 M19 串行合成 + 硬下限 15%** 的最佳样本
2. **MacroHeadwind 相关性放大**:BTC-nasdaq 相关性 0.81 > 0.7 应触发全项 × 1.5 放大,score 应被 clamp 到 -10
3. **EventRisk 距离加权**:FOMC +3 天处于 [0-24h] × 1.5 权重的边界;代码应精确处理时间 bucket

## 使用方式

同 scenario 1。对于 L4 crowding 和 EventRisk 的细粒度验证,可以单独单元测试。

---

**注意**:本场景 K 线种子化构造(numpy seed=777),非真实历史数据。链上 / 衍生品 / 宏观快照按建模逻辑构造,确保能触发预期证据层输出。
