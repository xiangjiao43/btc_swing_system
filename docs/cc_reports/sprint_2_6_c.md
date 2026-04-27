# Sprint 2.6-C — ADX 数据链路 + 24h 清算卡 metric_name 修复

**Date:** 2026-04-27
**Branch:** main · 当前 HEAD = `c62a326`(本 sprint 2 commit + 1 报告 commit)
**Status:** ✅ Commit 1+2 落地;Commit 3 reframed 为 no-op(scheduler 已实现);Commit 4(部署)留给用户;Commit 5(本报告)落档

---

## Triggers(偏离用户原 spec 的自主决策)

1. **Commit 3 reframed 为 no-op**:用户 spec 假设 `src/scheduler/jobs.py::job_data_collection` 仍是 skeleton(`logger.info("skeleton no-op")`)。实际 Sprint 2.6-A `01ad99f` 已完整实现该函数,Sprint 2.6-B `e0cbfbd` 又补了 OI/liquidation。当前函数已 100% 覆盖 spec 描述的功能(FRED + CoinGlass(K线 + funding/OI/LSR/liquidation)+ Glassnode,优雅失败,返回 status/total_upserted/by_collector)。按 §X 工程纪律"不堆叠重复代码",未做替换。
2. **未创建 `tests/test_job_data_collection.py`**:已有 `tests/test_data_collection_job.py` 覆盖 5 个 case(status_ok / all_failed / fatal_error / fred_skipped / partial_collector_failure),Sprint 2.6-B 已扩展 fixture 覆盖 OI/liquidation。重复创建会违反 §X。
3. **Commit 4(部署)未自动执行**:生产部署是 hard-to-reverse + shared system,留给用户手动触发(`git pull` + restart + manual `job_data_collection()` trigger)。

---

## 一、本 sprint commits

| commit | 摘要 |
|---|---|
| `dac5867` | feat(layer1): expose adx_14_1d/atr/tf_alignment as top-level fields |
| `c62a326` | refactor(emitter): drop dead _compute_adx/_atr_percentile, fix liquidation key |
| (本 commit) | docs(reports): sprint_2_6_c complete — ADX wired, liquidation card fixed |

420 pytest pass(无回归),pre-commit gitleaks 每次 commit 自动 Passed。

---

## 二、Recon 关键发现:Commit 3 spec 假设有误,reframed 为 no-op

### 用户原 spec(Commit 3)
> "scheduler/jobs.py 的 job_data_collection 仍是空骨架(只 logger.info 'skeleton no-op'),
> 尽管 Sprint 2.6-A 把 scheduler.yaml 的 data_collection.enabled 改成 true,
> 实际 scheduler 1 小时跑这个 job 什么都不做"

### 实际诊断
读 `src/scheduler/jobs.py:123-296`,`job_data_collection` 已是完整实现:

- **入口**:`def job_data_collection(*, conn_factory=None, since_days=7) -> dict`
- **调用顺序**:FRED → CoinGlass(K线 1h/4h/1d × funding/OI/LSR/liquidation)→ Glassnode(9 个链上指标)
- **优雅失败**:每个 collector 独立 try/except;FRED 无 key 时优雅 skip;全部失败 → `status='all_failed'`(不抛);conn_factory 抛 → `status='fatal_error'`
- **返回**:`{status, total_upserted, by_collector, errors, duration_ms, since_days}`

### 触发本纪律的历史
Sprint 2.6-A commit `01ad99f` 标题就是 `feat(scheduler): implement data_collection job with 4 collectors`。
Sprint 2.6-B commit `e0cbfbd` 标题是 `fix(coinglass): wire OI + liquidation fetches into scheduler/backfill`。
两次 commit 已把这个 spec 的功能做完。本 sprint 的 spec 写于 commit 之前,信息陈旧。

### Reframed 决策
- 不替换函数:已实现,且行为 100% 匹配 spec 期望
- 不新建测试文件:`tests/test_data_collection_job.py` 已覆盖 5 个 case + Sprint 2.6-B 已扩展 OI/liquidation fixture
- 按 §X 鉴别测试 (a) 部署后旧代码不会被调用 → 替换会留死代码 → 应保留;(b) 一个调用方走老一个走新?不,只有一个 `job_data_collection`,不存在并存

---

## 三、Commit 1+2 改动清单

### Commit 1 `dac5867`:layer1 暴露 ADX/ATR/tf_alignment 顶层字段

**为什么需要:** factor_card_emitter 之前去 `l1.get("adx_14_1d")`,但 layer1 把 adx 放在 `diagnostics` 子 dict 里,顶层没有,所以 emitter 永远拿不到 → ADX-14 卡片永远 None。

**改动:**
- `src/evidence/layer1_regime.py::Layer1Regime.compute()` 主返回 dict(line ~329)新增 4 个顶层字段:
  - `adx_14_1d`(2 位小数)
  - `atr_14_1d`(2 位小数)
  - `atr_percentile_180d`(1 位小数)
  - `tf_alignment`(`{aligned, direction, score}` dict)
- `_insufficient(...)` 数据不足分支(line ~51)同步加 4 个 None / placeholder 字段,保持 schema 一致(下游不会 KeyError)
- 新增 helper `_build_tf_alignment(ema_arrangement, weekly_macd_direction)`:
  - 都 up → `{aligned: True, direction: "up", score: 3}`
  - 都 down → `{aligned: True, direction: "down", score: 3}`
  - 其它 → `{aligned: False, direction: "mixed" 或 "unknown", score: 1 或 None}`

**未改动:** `src/indicators/trend.py::adx()`(已工作,不动);`diagnostics["adx_latest"]` 仍保留(向下兼容,可能有人读)。

### Commit 2 `c62a326`:emitter 删死函数 + 修清算卡 key

**改动:**

1. **简化 ADX/ATR 读取**(`src/strategy/factor_card_emitter.py::_emit_price_tech_primary`):
   - `adx = l1.get("adx_14_1d") or l1.get("adx_1d") || _compute_adx_latest(klines_1d)` → `adx = l1.get("adx_14_1d")`
   - `atr_pct = l1.get("atr_percentile_180d") or l1.get("atr_pct") || _compute_atr_percentile(klines_1d)` → `atr_pct = l1.get("atr_percentile_180d")`

2. **删除两个死函数**(line 946-979 原占位):
   - `_compute_adx_latest(klines_1d)`:`return None` 写死的占位,从未被调用过且永远返回 None
   - `_compute_atr_percentile(klines_1d)`:重复实现 layer1 已经算过的 atr_percentile_180d
   - 替换为注释块解释为什么删除,引用 §X 工程纪律

3. **修 24h 清算卡 metric_name**(`_emit_derivatives_primary` ~line 1165):
   ```python
   # 原:derivatives.get("liquidation") or derivatives.get("liquidation_24h") (都拿不到)
   # 新:优先 liquidation_total,然后 fallback liquidation / liquidation_24h
   liq_series = None
   if isinstance(derivatives, dict):
       for k in ("liquidation_total", "liquidation", "liquidation_24h"):
           v = derivatives.get(k)
           if v is not None:
               liq_series = v
               break
   ```

**Sprint 2.6-B 已落库 `liquidation_total/long/short` 三列**(见 `derivatives_snapshots`),`DerivativesDAO.get_all_metrics` 现在返回的 dict key 是 `liquidation_total`(不是老的 `liquidation`),所以 emitter 必须对齐。

---

## 四、未触动的清单(按 spec 硬约束)

| 文件 | 状态 |
|---|---|
| `src/indicators/trend.py::adx()` | ✅ 未动(已工作) |
| `src/data/collectors/fred.py` | ✅ 未动 |
| `src/data/collectors/coinglass.py` | ✅ 未动 |
| `src/data/collectors/glassnode.py` | ✅ 未动 |
| `src/evidence/layer2_*.py` ~ `layer5_*.py` | ✅ 未动 |
| `docs/modeling.md` | ✅ 未动 |
| `CLAUDE.md` | ✅ 未动 |

---

## 五、测试验证

```
$ python -m pytest tests/test_data_collection_job.py -q
.....                                                                    [100%]
5 passed in 0.11s

$ python -m pytest -q
420 passed, 1 skipped, 84 warnings in 1.94s
```

无回归。pre-commit gitleaks 每次 commit 自动 Passed。

---

## 六、待用户手动执行(原 Commit 4 部署)

本 sprint 是纯代码层修复,需要重启生产 scheduler 让新代码生效:

```bash
# 服务器(124.222.89.86)
ssh user@server
cd /path/to/btc_swing_system
git pull
sudo systemctl restart btc-scheduler   # 或对应服务名
# 触发一次 pipeline 验证 ADX / 清算卡
```

### 预期验收(Region 4 因子卡片网页)

| card_id | Sprint 2.6-C 前 | 预期 Sprint 2.6-C 后 |
|---|---|---|
| `price_adx_14_1d` | None | **数值(layer1 直接给)** ✅ |
| `derivatives_liquidation_24h` | None | **数值(读 liquidation_total)** ✅ |
| L1 `health_status` | `cold_start_warming_up` | **可能转 `healthy`**(ADX 这个缺口补上) |

---

## 七、遗留问题(明确不在本 sprint 范围)

### 7.1 `derivatives_funding_rate_aggregated` 仍 "数据不足"
该 card 期待跨交易所聚合资金费率,但 coinglass 提供的接口可能是单交易所(Binance)。
属于 collector 接口能力问题,不在本 sprint 修复范围(Sprint 2.6-B 也已标注)。

### 7.2 测试 fixture 残留 `derivatives_snapshot/macro_snapshot/onchain_snapshot` JSON keys
按 §X 规则应删,但删 3 个大型 fixture JSON 风险高(可能破坏其他测试的 pipeline 输入)。
保留 + 标注:这是历史 fixture 数据快照的格式,不影响当前生产(Sprint 2.6-B 已说明)。

### 7.3 Layer1 `diagnostics["adx_latest"]` 仍存在
本次只是把 ADX 提到顶层,没删 diagnostics 里的副本。理由:diagnostics 是给调试/AI 上下文用的,
保留不算"旧代码堆叠"。如果未来确认无人读 `diagnostics["adx_latest"]` 可再清。

---

## 八、§X 工程纪律本次践行

- ✅ 删除 `_compute_adx_latest` / `_compute_atr_percentile`(被 layer1 顶层字段替代,不留死代码)
- ✅ 简化 `l1.get("adx_14_1d") or l1.get("adx_1d")` 为单一来源(layer1 是唯一 owner)
- ✅ Reframed Commit 3 为 no-op(避免堆叠重复 `job_data_collection` 实现)
- ✅ 没新建 `tests/test_job_data_collection.py`(已有 `test_data_collection_job.py` 覆盖)

---

## 九、git log(本 sprint)

```
c62a326 refactor(emitter): drop dead _compute_adx/_atr_percentile, fix liquidation key
dac5867 feat(layer1): expose adx_14_1d/atr/tf_alignment as top-level fields
```
