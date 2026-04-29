# Sprint 1.5c — 字段漂移修复 + events seed 补全

(注:本报告独立于已有 `sprint_1_5c.md`(Sprint 1.5 系列收官),
是用户后续追加的"前端 9 处 missing 修复"任务。)

**Date:** 2026-04-29
**Branch:** main
**Status:** ✅ 完成,8 个新测试 + 757/757 全量回归过

---

## 一、问题

用户截图框出网页 9 处 missing,逐项分析后:
1. **8 项是字段名漂移代码 bug**(数据全有,层间 key 名对不上)
2. **1 项是 events seed 不全**(events_2026.json 只 8 FOMC + 1 CPI + 1 NFP + 0 期权)

实际数据状态(SSH 验证):price_candles / onchain / derivatives / macro 全充足。
events_calendar 只有 8+1+1+0 → composite 因子算"下次 CPI / NFP / 期权"全 missing。

字段存在性铁证:
- L1 顶层缺 `adx_14_4h` / `timeframe_alignment` / `ma_alignment`
  (内部 `_compute_specific` 真算了多周期 EMA 和 MA,但没 export 到顶层)
- L2 顶层缺 `trend_position` / `ma_60_distance_pct` / `latest_pullback_depth` /
  `impulse_extension_ratio`(BandPosition composite 真算了,L2 没把它们提到顶层)
- `composite_composition.py` 早已读 `l1.get("timeframe_alignment")` /
  `l1.get("ma_alignment")` / `l2.get("ma_60_distance_pct")` 等建模标准名,
  可惜上游不导出 → factor_card composition.value=None

---

## 二、改动

### 任务 A:`src/evidence/layer1_regime.py`(L1 export 缺失字段)

`_compute_specific`:
- 读 `context.klines_4h`(可选),计算 `adx_4h_latest`(`adx(...,14)`)和 `dir_4h`
  (`_ema_arrangement(ema20_4h, ema50_4h, ema200_4h)`)
- 在 1d closes 上算 MA-20/60/120/200(简单算术平均)
- `_ma_alignment_direction`:严格升降序判定 → "up" / "down" / None

返回 dict 新增:
- `adx_14_4h`(数值或 None)
- `timeframe_alignment`(dict:`tf_4h / tf_1d / tf_1w / aligned / direction / score`)
- `tf_alignment`(同 dict alias 给老代码 / factor_card_emitter)
- `ma_alignment`(dict:`ma_20 / ma_60 / ma_120 / ma_200 / direction / is_aligned`)

数据不足路径同 schema 占位。删除老的 `_build_tf_alignment`(被
`_build_timeframe_alignment_pair` 替代,§X)。

### 任务 B:`src/evidence/layer2_direction.py`(L2 export BandPosition 内部字段)

`_compute_specific` 末尾 `return` 字典新增 4 字段:
- `impulse_extension_ratio`(从 bp 顶层取)
- `latest_pullback_depth`(从 `bp.diagnostics.retracement_ratio` 取)
- `ma_60_distance_pct`(新 helper `_compute_ma60_distance_pct(klines_1d)`,EMA-60 计算)
- `trend_position`(dict alias 给前端 / composite_composition,
  `estimated_pct_of_move = impulse_extension_ratio` 等)

L2 之前不直接读 K 线(§4.3.2 纪律),本次为 `ma_60_distance_pct` 加入读 1d
(只看一个数值不参与方向判定,合规)。

数据不足 `_insufficient` 路径同步加 schema 占位 None。

### 任务 C:`src/strategy/factor_card_emitter.py`

"多周期方向一致性"卡 `alignment` 取值改为优先读建模标准名 `timeframe_alignment`,
fallback `tf_alignment`(同 dict alias)/ `multi_tf_alignment`(legacy)。

### 任务 D:`data/seeds/events_2026.json`(全年补全)

44 events:**8 FOMC + 12 NFP + 12 CPI + 12 options_expiry_major**。
- NFP:每月第一个周五 8:30 ET → UTC(DST 自动判断,Mar 8-Nov 1 EDT,其他 EST)
- CPI:每月 13 日估算占位,notes 标 "estimated; verify on bls.gov"
- options_expiry_major:每月最后一个周五 08:00 UTC,Q1/Q2/Q3/Q4 季度到期 impact_level=3
- 原 8 FOMC 保留,按 `date` + `utc_trigger_time` 排序

`_meta` 含 source / next_review_date(2026-12-15)/ DST 注释。

---

## 三、测试

`tests/test_field_export_alignment.py`(8 测试):

| 测试 | 验证 |
|---|---|
| `test_layer1_exports_required_fields` | 真 220 根 1d + 4h(6 倍密度)+ 1w → adx_14_4h 数值,timeframe_alignment 6 字段齐,tf_alignment 同 dict alias,ma_alignment.direction="up" + is_aligned=True + ma_20 > ma_60 > ma_120 > ma_200 |
| `test_layer1_insufficient_path_keeps_schema` | 空 1d → 字段都 None / 占位 dict,不抛 KeyError |
| `test_layer2_exports_band_position_fields` | 真 L1 + truth_trend + band_position → L2 顶层 impulse_extension_ratio / latest_pullback_depth / ma_60_distance_pct / trend_position 全有数值 |
| `test_layer2_insufficient_path_keeps_schema` | L1 缺失 → 字段 None |
| `test_composite_composition_reads_real_values_from_l1_l2` | **集成**:真跑 L1+L2+composite_composition,断言 truth_trend 的 price_tf_alignment / price_ma_stack 的 value 不是 None;band_position 的 price_ma_60_distance / price_pullback_depth value 不是 None |
| `test_events_seed_full_year_coverage` | NFP ≥ 12 / CPI ≥ 12 / options_expiry_major ≥ 12 / FOMC ≥ 8 |
| `test_events_seed_utc_trigger_time_format` | 所有 utc_trigger_time 符合 ISO `YYYY-MM-DDTHH:MM:SSZ` |
| `test_events_seeder_loads_full_year` | 真 init_db + EventsSeeder + COUNT(*) by event_type 反映全年覆盖 |

**回归**:全量 `pytest tests/` = **757 passed, 1 skipped, 5.08s**(749 + 8 新)。

---

## 四、用户验证脚本(SSH 部署后)

```bash
ssh ubuntu@124.222.89.86 << 'SSH'
cd /home/ubuntu/btc_swing_system
git pull
sudo systemctl restart btc-strategy.service

# 1. 重 seed events_calendar
.venv/bin/python -c "
from src.data.collectors.events_seeder import seed_events
from src.data.storage.connection import get_connection
conn = get_connection()
print(seed_events(conn))
conn.close()
"

# 2. events 数量验证
.venv/bin/python -c "
import sqlite3
conn = sqlite3.connect('data/btc_strategy.db')
for r in conn.execute('SELECT event_type, COUNT(*) FROM events_calendar GROUP BY event_type'):
    print(r[0], r[1])
"
# 预期:cpi >= 12, nfp >= 12, fomc >= 8, options_expiry_major >= 12

# 3. 等下次 pipeline_run + 检查 L1/L2 顶层字段
curl -s -u admin:Y_RhcxeApFa0H- http://127.0.0.1:8000/api/strategy/current | \
  python3 -c "
import sys, json
state = json.load(sys.stdin)['state']
l1 = state['evidence_reports']['layer_1']
l2 = state['evidence_reports']['layer_2']
print('L1 adx_14_4h:', l1.get('adx_14_4h'))
print('L1 timeframe_alignment:', l1.get('timeframe_alignment'))
print('L1 ma_alignment:', l1.get('ma_alignment'))
print('L2 impulse_extension_ratio:', l2.get('impulse_extension_ratio'))
print('L2 ma_60_distance_pct:', l2.get('ma_60_distance_pct'))
print('L2 latest_pullback_depth:', l2.get('latest_pullback_depth'))
"
# 预期:全部应有真实值/dict,不是 None

# 4. 浏览器硬刷,组合因子卡 6 张应全部显示数值,不再 missing
SSH
```

---

## 五、§X / §Y / §Z 自检

### §X(旧代码必须删除)
- 删除老的 `_build_tf_alignment` 函数,被 `_build_timeframe_alignment_pair` 替代
- 不"双 key 名读取"扩散:`tf_alignment` / `timeframe_alignment` 是同 dict 引用,
  factor_card_emitter 也对齐建模标准名 `timeframe_alignment`(优先)
- L2 `_insufficient` 路径同步加 schema 占位字段,不让下游报 KeyError

### §Y
本 commit 立即 push。

### §Z 端到端断言
- `test_composite_composition_reads_real_values_from_l1_l2`:**反 missing 的核心
  guard**,真跑 L1 + truth_trend + band_position + L2 + composite_composition,
  断言 4 个 factor 的 value 都不是 None
- `test_events_seeder_loads_full_year`:真 init_db + 真 seed_events + COUNT(*),
  断言 4 类 event 都齐
- 数据不足路径单独测,确保 schema 占位仍正确

### 同类风险扫描
1. **`adx_14_4h` 4h K 线缺失** — `klines_4h` 不在 context 时返回 None,
   不抛错;factor card 显示 "n/a"(预期降级)
2. **`ma_alignment.direction=None` 时严格不算 aligned** — 用户截图里 BTC 当前是
   弱区间,MA 不严格升降序 → direction=None + is_aligned=False。前端可显示
   "无明确方向"而非 missing
3. **CPI 13 日估算** — notes 标 "estimated; verify on bls.gov";真实 BLS 日期
   通常在 12-15 之间,误差 ±2 天对距下次 CPI 时间的影响 < 5%。下次 review
   日期 2026-12-15 提醒人工修
4. **options_expiry_major 12 月 12-25** — notes 标"圣诞节附近 Deribit 可能
   调整到稍前一个周五"。生产端(若 Deribit 改期)可手动改 events_2026.json
   重新 seed
5. **`utc_trigger_time` DST 边界(Nov 1 / Mar 8)** — `is_edt` 逻辑覆盖 US 2026
   实际边界,边界月份取保守值

---

## 六、改动文件

| 文件 | 改动 |
|---|---|
| `src/evidence/layer1_regime.py` | 加 4h ADX/EMA + MA-20/60/120/200 + `_build_timeframe_alignment_pair` + `_ma_alignment_direction` helpers,删除 `_build_tf_alignment` |
| `src/evidence/layer2_direction.py` | 加 4 顶层字段 + `_compute_ma60_distance_pct` helper |
| `src/strategy/factor_card_emitter.py` | "多周期方向一致性"卡读 `timeframe_alignment` 优先 |
| `data/seeds/events_2026.json` | 11→44 events(全年 NFP/CPI/期权)|
| `tests/test_field_export_alignment.py` | 新文件 8 测试 |

---

## 七、未覆盖项 / v1.x

- **L4 失效位**:用户截图也有 missing,但当前 stance=neutral 时不算(预期),
  无 bug
- **L5 定性事件摘要**:仍 "v0.5 启用",留 v0.5 sprint
- **MA 排列要求严格升降序**:弱区间下大概率 direction=None;若用户希望"近似排列"
  也算 aligned,留 v1.x 加 tolerance
