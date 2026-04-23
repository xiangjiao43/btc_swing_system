# Scenario 3 — Ranging / Pre-ETF Equilibrium (2023-07-01)

## 历史背景

2023 年 7 月 1 日是 BTC **震荡观望区**的典型节点,选在 **BlackRock ETF 申请(2023-06-15)之后、批准(2024-01)之前**的等待期:

- BTC 从 2023-01 低点 $16,800 反弹至 3 月银行危机时的 $26,000
- 5-7 月进入 $27,000-$31,000 区间震荡,整体 sideways 态
- 当日价格 $30,500,位于区间中位
- MA-20/MA-60 基本持平,无明显方向
- 链上 MVRV Z 0.4 和 NUPL 0.22 处于 early_bull / accumulation 边界,**指标本身对方向不明确**

## 宏观环境(平静)

- DXY 几乎持平(20 日 -0.3%)
- US10Y 3.82%,30 日 +18bp,低于 +30bp 触发阈值
- **VIX 13.6** —— 极低!2022 年以来首次回到此水平,反映市场情绪显著缓和
- 纳指 +2.6% 20 日,未触发 MacroHeadwind 任何项
- BTC-纳指相关性 0.42,脱钩走强(BTC 开始受 crypto-specific 催化驱动)

## 衍生品(平静)

- 资金费率 0.005%,几乎为零
- OI $11.2B 稳定
- PCR 0.92,接近中性
- 基差年化 3%,温和
- 24h 清算 $1800 万,远低于压力日

## 为什么选这一天

这一天是 **M26 可交易性验收场景 3 的理想样本** —— 系统必须能**抵抗震荡陷阱**:

| 检验目标 | 期望触发 |
|---|---|
| L1 regime 识别 range_mid(非 trend_*)| ADX(1d) < 20,多 TF 方向不一致,truth_trend ≤ 5 |
| L1 volatility low 或 normal | ATR 分位 20-45 |
| L2 stance neutral(或弱 bullish)| stance_confidence < 0.58,**不应**清 0.55 阈值 |
| L2 phase unclear 或 late | 涨幅已消化,未创新高 |
| L2 cycle_position 模糊(early_bull / accumulation / unclear) | 主指标读数在多档边界 |
| L3 opportunity_grade = none | 失败 long_rules.A/B/C(regime 非 trend_up;stance 非 bullish) |
| L3 execution_permission = watch | 默认兜底 |
| L4 overall_risk = low | 无拥挤无事件无极端 |
| L5 macro = risk_neutral | 全项未触发 |
| 状态机应保持 FLAT | 无合法迁移条件被满足 |

## 预期 M26 可交易性验收结果

- **场景类型**:震荡区(ranging)
- **M26 要求**(thresholds.kpi_tracker.prolonged_watch + §10.7 场景 3):震荡区内**累计状态迁移次数 ≤ 8 次**(不被震荡打脸)
- **预期结果**:PASS。系统应**保持 FLAT**,不触发任何 PLANNED 迁移
- **验收失败信号**:如果系统在此场景触发 LONG_PLANNED 或 SHORT_PLANNED,然后在 1-2 天内反向,说明被震荡噪音打脸
- **验收失败补救**:
  - 检查 L2 stance_confidence 计算是否过激(可能 exchange_momentum 修正过度)
  - 检查 L3 long_grade_rules 是否真的需要 stance_confidence 清动态门槛(而不只是 stance=bullish)
  - 考虑提高 regime 切换的 `min_consecutive` 次数(thresholds.layer_1_regime.regime_switch_min_consecutive)

## 特别关注点

### A. observation_category 边界案例

此场景下 stance 可能在 neutral(触发 disciplined)和弱 bullish(触发 watchful)之间反复。两种分类都合理,**只要不是 possibly_suppressed**(这需要 grade=none + confidence ≥ 阈值 + 持续 ≥ 7 天,此场景 confidence 偏低不会达阈值)。

### B. truth_trend 的 180d 窗口陷阱

K 线数据的 180 日窗口包含 **1-3 月大涨 + 4-7 月 sideways**。如果 truth_trend 评分给整个窗口等权,会误读为"真趋势";但建模 §3.8.1 的评分项中 ADX 和多 TF 一致性都基于**最近**的数据。单元测试应验证 truth_trend_score < 6(不误入"真趋势"档)。如果 ≥ 6,说明指标受"旧数据"污染。

### C. cycle_position 投票模糊

MVRV Z 0.4 同时命中 `accumulation`(< -0.5 否)、`early_bull`([-0.5, 2] 是)、`mid_bear`([-0.5, 2] 且趋势向下 否,因 MVRV Z 是上行的)。NUPL 0.22 仅命中 early_bull。LTH +0.8% 命中 early_bull 或 mid_bull。投票:2 票 early_bull,1 票 mid_bull → early_bull with confidence 0.6。**但辅助条件 `aux_min_days_since_last_accumulation: 60`**:如果 accumulation 档位的"最后一次"在 180 天内,可能不满足。这个边界 Sprint 1 时需要代码精确实现。

## 使用方式

同 scenario 1 + 2。**此场景最重要的断言**:

```python
assert state_machine_output["chosen_action_state"] == "FLAT"
assert opportunity_grade == "none"
```

---

**注意**:本场景 K 线种子化构造(numpy seed=1234)。数据路径从 $16,800 升到 $30,500 并不是完全 sideways —— 这正是关键挑战:系统应识别"**最近**是 sideways"而非被"**全窗口**上涨"误导。
