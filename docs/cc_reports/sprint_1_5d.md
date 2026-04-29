# Sprint 1.5d — events 扩展:加 PCE + 季度期权区分

**Date:** 2026-04-29
**Branch:** main
**Status:** ✅ 完成,10 个新测试 + 812/812 全量回归过

---

## 一、决策依据(Backlog #11)

加:
- **PCE**(headline + core 同一份"Personal Income and Outlays"报告)
- **季度期权 Q1/Q2/Q3/Q4 区分**(impact_level=4 vs 月度=2)

不加(NY Fed Benigno & Rosa 2023 实证显示对 BTC orthogonal,加进去稀释信号):
- 零售销售 / ISM / GDP / JOLTS / ADP / 消费者信心
- PPI(Fed 不看 PPI;PCE 已涵盖核心通胀传导链路)

---

## 二、改动

### 任务 A:`data/seeds/events_2026.json` +12 PCE

12 条 PCE,日期来自 White House PFEI 2026 schedule:
```
1-29 / 2-26 / 3-27 / 4-30 / 5-28 / 6-25 /
7-30 / 8-26 / 9-30 / 10-29 / 11-25 / 12-23
```
DST 自动判:Mar 8 - Nov 1 = EDT → UTC 12:30;其他 = EST → UTC 13:30。

`pce_2026_01_29` / `pce_2026_02_26` notes 加 `Actual release Mar 13 / Apr 9
due to 2025 government shutdown`(用户追加)。

`event_name` 含 prior month data + headline + core PCE 说明。
`impact_level=4`(同 FOMC,NY Fed Pinchuk 2024 实证 1σ 通胀意外 → BTC -24bps,
与 CPI 等量级,且 PCE 是 Fed 决策核心输入)。

### 任务 A.5:`options_expiry_major` Q vs 月度 impact 重排

| 月份 | impact_level | notes |
|---|---|---|
| 03 (Q1) / 06 (Q2) / 09 (Q3) / 12 (Q4) | **4** | "Q? quarterly expiry (Deribit + IBIT); historically 30-50% of OI" |
| 01 / 02 / 04 / 05 / 07 / 08 / 10 / 11 | **2** | "Monthly expiry (Deribit); lower OI concentration than quarterly" |

12 月加额外 notes:`Christmas-adjacent: Deribit may shift to prior Friday`。

`event_name` 区分 "BTC monthly options expiry" vs "BTC quarterly options expiry"。

### 任务 B:`config/thresholds.yaml` event_type_weights 加 pce

```yaml
event_type_weights:
  fomc: 4
  cpi:  3
  nfp:  3
  pce:  4   # Sprint 1.5d:Fed 偏好通胀指标
  options_expiry_major: 2
  other: 1
```

### 任务 C:`src/composite/event_risk.py::_US_MACRO_TYPES` 加 pce

```python
_US_MACRO_TYPES: set[str] = {"fomc", "cpi", "nfp", "pce"}
```

→ BTC-纳指相关性 > 0.7 时 PCE 也享受 +1 美宏事件加成(同 FOMC/CPI/NFP 待遇)。

EventRiskFactor.compute 已用 `weights_cfg.get(event_type_raw, ...)` 动态读
thresholds,**无需改主流程** — pce 类型自动按 weight=4 评分。

### 任务 D:`src/pipeline/state_builder.py::_assemble_context`

`get_next_events_by_type` query types 从
`["fomc","cpi","nfp","options_expiry_major"]` 扩到
`["fomc","cpi","nfp","pce","options_expiry_major"]`。

### 任务 E:`src/strategy/composite_composition.py::_event_risk`

composition 加 PCE 行(`event_pce_next`),并把 weights 重新分配:

| factor_id | weight 旧 | weight 新 |
|---|---|---|
| event_fomc_next | 0.35 | **0.30** |
| event_cpi_next | 0.25 | **0.20** |
| event_pce_next | (新) | **0.20** |
| event_nfp_next | 0.20 | **0.15** |
| event_options_expiry | 0.10 | 0.10 |
| event_vol_extreme_bonus | 0.10 | **0.05** |

PCE 显示行:`role="重要度 4;Fed 偏好通胀(headline + core);时间衰减同上"`。
options_expiry 行 role 改为 `"重要度 2(月度)/ 4(季度)"` 反映新区分。

---

## 三、测试

`tests/test_events_pce_extension.py`(10 测试):

| 测试 | 验证 |
|---|---|
| `test_events_seed_contains_12_pce` | events_2026.json pce 数量 = 12 |
| `test_pce_utc_trigger_time_format_and_dst` | 全 pce ISO 格式 + EDT/EST 切换正确 |
| `test_pce_jan_feb_have_shutdown_reschedule_notes` | 1/2 月 PCE notes 含 "shutdown" |
| `test_options_expiry_quarterly_impact_4` | Q1/Q2/Q3/Q4 季度期权 impact=4 + notes 含 "quarterly" |
| `test_options_expiry_monthly_impact_2` | 8 个月度 impact=2 |
| `test_events_seeder_loads_pce_into_db` | 真 init_db + EventsSeeder + COUNT by type:pce=12, fomc=8, cpi=12, nfp=12, options=12,总数 ≥ 56 |
| `test_thresholds_pce_weight` | thresholds.yaml event_type_weights.pce=4 |
| `test_event_risk_composition_includes_pce_row` | composite_composition._event_risk 含 event_pce_next 行,从 next_events_by_type.pce 拾取距离 |
| `test_event_risk_pce_in_us_macro_types` | _US_MACRO_TYPES 含 pce |
| `test_event_risk_compute_picks_pce_event` | 真 EventRiskFactor.compute,pce event 36h 距离 → base_weight=4 + effective_score=4.0(24-48h × 1.0) |

**回归**:全量 `pytest tests/` = **812 passed, 1 skipped, 5.06s**(802 + 10 新)。

---

## 四、用户验证脚本(SSH 部署后)

```bash
ssh ubuntu@124.222.89.86 << 'SSH'
cd /home/ubuntu/btc_swing_system
git pull
sudo systemctl restart btc-strategy.service
sleep 5

# 1. 重 seed events
.venv/bin/python -c "
from src.data.collectors.events_seeder import seed_events
from src.data.storage.connection import get_connection
conn = get_connection()
print(seed_events(conn))
conn.close()
"

# 2. 验证类型分布
.venv/bin/python -c "
import sqlite3
conn = sqlite3.connect('data/btc_strategy.db')
for r in conn.execute(
    'SELECT event_type, COUNT(*) AS n FROM events_calendar '
    'GROUP BY event_type ORDER BY event_type'
):
    print(f'  {r[0]:25s} n={r[1]}')
"
# 预期:cpi=12 / fomc=8 / nfp=12 / options_expiry_major=12 / pce=12

# 3. 验证季度 vs 月度
.venv/bin/python -c "
import sqlite3
conn = sqlite3.connect('data/btc_strategy.db')
for r in conn.execute(
    \"SELECT event_id, impact_level, notes FROM events_calendar \"
    \"WHERE event_type = 'options_expiry_major' ORDER BY date\"
):
    print(f'  {r[0]} impact={r[1]} | {(r[2] or \"\")[:60]}')
"
# 预期:03/06/09/12 月 impact=4,其他 impact=2

# 4. 等下次 pipeline_run,检查 event_risk.composition 含 PCE
curl -s -u admin:Y_RhcxeApFa0H- http://127.0.0.1:8000/api/strategy/current | \
  python3 -c "
import json, sys
state = json.load(sys.stdin)['state']
er = state.get('composite_factors', {}).get('event_risk', {})
for it in er.get('composition') or []:
    fid = it.get('factor_id', '')
    if 'pce' in fid or 'cpi' in fid or 'fomc' in fid or 'nfp' in fid:
        print(f'  {fid}: value={it.get(\"value\")}')
"
# 预期:event_pce_next, event_fomc_next, event_cpi_next, event_nfp_next
# 各自有数值(小时数,可能 > 100,因下次距离都不在 72h 窗口内)

# 5. 浏览器刷新事件日历卡 → 显示"下次 PCE 距离"
SSH
```

---

## 五、§X / §Y / §Z 自检

### §X(只扩展,不重写)
- events_seeder 不动(它已 schema-agnostic)
- event_risk.compute 主流程不动(已动态读 thresholds)
- composite_composition 加一行 + 调权重(其他 4 行结构不变)
- thresholds.yaml 加一行 + 改 options_expiry 注释

### §Y
本 commit 立即 push。

### §Z 端到端断言
- 真 init_db + EventsSeeder + COUNT by type 验证 56 条
- 真 EventRiskFactor.compute 输入 PCE event 36h 距离,断言 base_weight=4
- DST 切换边界(Mar 8 / Nov 1)逐月验证
- 1/2 月政府关门重排 notes 显式断言

### 同类风险扫描
1. **PCE 13 日估算 vs 真实日期** — 用了 BEA 官方 calendar 真实日期,
   不是估算
2. **季度期权 Q1=Mar 27 vs IRS 季度报告(Mar 31)** — Deribit 是月末最后周五,
   非 IRS 日期。事件名标 "BTC quarterly options expiry"(限定 Deribit)
3. **12 月圣诞调整** — notes 标 verify on Deribit;实际日期 12-25 万一调整,
   sprint 1.5e+ 再人工修
4. **PCE event_risk 加 weight=4 提分** — 与 CPI 同月时事件密度可能升档;
   建模 §3.8.6 评分上限 100,出现 fomc + cpi + pce + nfp 同 72h 窗口时
   理论最高 30 分,band → high(× 0.7),符合"宏观重灾周谨慎"语义

---

## 六、改动文件

| 文件 | 改动 |
|---|---|
| `data/seeds/events_2026.json` | 44→56 events(+12 PCE),options_expiry Q1/2/3/4 重新 impact=4 |
| `config/thresholds.yaml` | event_type_weights 加 pce:4;options_expiry 注释 |
| `src/composite/event_risk.py` | _US_MACRO_TYPES 加 pce |
| `src/pipeline/state_builder.py` | next_events_by_type 加 pce |
| `src/strategy/composite_composition.py` | _event_risk composition 加 PCE 行 + 重排 weights |
| `tests/test_events_pce_extension.py` | 新文件 10 测试 |

---

## 七、未覆盖项

- 期权 IBIT(美股 ETF)单独 calendar 暂不接入;若未来发现 IBIT 期权对 BTC
  spot 有显著影响,可加 `event_type="options_expiry_ibit"`(留 v0.6)
- BEA 真实公布日期偏移(如 PCE 4-30 实际改 5-1)无监控;next_review_date
  设 2026-12-15 提示人工查 BEA 2027 schedule
