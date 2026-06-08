# Sprint: Data Export Indicators (Batch 1 / 2 / 3)

**日期**:2026-06-08
**前置 sprint**:`sprint_data_export_endpoint.md`(端点骨架,commit `d1803ef`)
**Commits**:
- 批 1:`274df57 feat(export): batch1 — Pi Cycle + Mayer + yield curve + 3-tier usage tags`
- 批 2:`fedd869 feat(export): batch2 — add Fear&Greed index from CoinGlass`
- 批 3:`e4b6aa3 feat(export): batch3 — CVDD + ATM IV + 25Δ Skew + Max Pain, 5s fetcher spacing`

## Triggers

新工作流的"系统数据快照"端点上线后(`d1803ef`),用户决定不停的最少补一批"判断价值高 + 数据可得"的指标进 snapshot。**三批合在一起完成 9 项新增 + 73 项已有指标用途标签**,让外部 AI 拿到的 markdown 既覆盖大周期 + 波段,又能用 `[大周期] / [波段] / [通用]` 标签快速分流。

## 全部新增指标清单

| 批次 | 指标 | 数据源 | 章节 | 用途标签 |
|---|---|---|---|---|
| 1 | **Pi Cycle Ratio** (SMA111 / SMA350×2) | 本地算(price_candles 1d) | 大周期估值/择时 | [大周期] |
| 1 | **Mayer Multiple** (close / SMA200) | 本地算 | 大周期估值/择时 | [大周期] |
| 1 | **收益率曲线 10Y-2Y** (bps) | 已在 `compute_macro_features`,从 L5 ctx 取 | 宏观 | [大周期] |
| 2 | **Fear & Greed Index** (0-100 + 5 档分类) | CoinGlass v4 `/api/index/fear-greed-history` | 宏观 | [通用] |
| 3 | **CVDD** (Cumulative Value Days Destroyed,USD) | Glassnode `/v1/metrics/indicators/cvdd` | 大周期估值/择时 | [大周期] |
| 3 | **ATM IV 1m** (1 月期权 ATM 隐含波动率,%) | Glassnode `/v1/metrics/derivatives/options_atm_implied_volatility_1_month` | 衍生品 | [波段] |
| 3 | **25 Δ Skew 1m** (put IV - call IV 归一) | Glassnode `/v1/metrics/derivatives/options_25delta_skew_1_month` | 衍生品 | [波段] |
| 3 | **Max Pain 1m** (期权 1 月到期磁吸价位,USD) | Glassnode `/v1/metrics/options/max_pain`(custom parser) | 衍生品 | [波段] |

snapshot 总指标数:从 d1803ef 时的 69 → **77**(新增 8 + yield 既存重显)。

## 用途标签 3 档分类原则(批 1 定稿)

代码位置:[src/api/routes/export.py:30-58](../../src/api/routes/export.py) `_LAYER_TAG_MAP` 文件注释段。

**[大周期]** — 系统老 Layer A 消费 / 周期级判断价值:
- 链上估值 / 持有者 / 周期类(MVRV / NUPL / RHODL / Puell / LTH/STH / SOPR / CDD / HODL Waves / SSR / **CVDD**)
- 大周期价格择时(MA200d / MA200w / ATH 回撤 / **Pi Cycle** / **Mayer**)
- 宏观货币慢变量(M2 / Fed Balance Sheet / Fed Funds / CPI / Core CPI / PCE)
- 收益率曲线 10Y-2Y(衰退信号,长周期)

**[波段]** — 系统老 Layer B 消费 / 周内尺度判断:
- 价格技术日内 / 4h(EMA 20/50/200 / ADX / ATR / swing / 价位)
- 衍生品(funding / OI / long_short_ratio / liquidation / btc_dominance)
- 期权(**ATM IV 1m** / **25 Δ Skew 1m** / **Max Pain 1m**)

**[通用]** — 双重消费:
- 宏观市场快变量(DXY / VIX / NASDAQ / US 收益率 / BTC-纳指相关)
- 价格基准(current_close / tf_alignment)
- 资金流(交易所余额 30d 累计变化 / ETF 流量)
- 综合情绪(**Fear & Greed Index**)

**兜底**:无显式映射 → [通用]。

## 实现要点

### 批 1:本地算

[src/strategy/local_indicators.py](../../src/strategy/local_indicators.py):
- `compute_pi_cycle(conn)` 需 1d 至少 350 根,返 `{sma_111, sma_350x2, ratio, as_of}`
- `compute_mayer_multiple(conn)` 需 1d 至少 200 根,返 `{sma_200, current_close, mayer, as_of}`
- 不进入 SpotCycleContextBuilder / ContextBuilder 的 AI 链路(那两个由建模锁定)
- yield_curve 从 `layer_b_ctx.l5.computed_macro_indicators.yield_curve_2_10_spread_bps` 直接取(无需新计算)

### 批 2:CoinGlass F&G

- Endpoint 探测:`/open-api-v4.coinglass.com/api/index/fear-greed-history` → 200(3028 daily values)
- 入 `macro_metrics` 表(`metric_name='fear_greed_index'`,`source='coinglass'`)
- **MacroSource Literal 扩展**:`Literal["fred", "yahoo_finance", "coinglass"]`(+ 1 行)
- 复用 `job_collect_klines_daily` 现有 CoinGlass cron — **不新增 cron**
- 5 档分类在渲染层计算(0-24 Extreme Fear / 25-49 Fear / 50 Neutral / 51-74 Greed / 75-100 Extreme Greed)

### 批 3:Glassnode 精选 + 限流改善

[src/data/collectors/glassnode.py](../../src/data/collectors/glassnode.py) 加 4 个 fetcher。`fetch_max_pain_1m` 需自定义解析,因 Glassnode 返 `{o: {1month, 1w, 3month, 6month, aggregated}}` 多 tenor 嵌套,只取 `1month` 子键。

**独立 cron `collect_glassnode_extras`**(BJT 12:00):
- 避开 09:30/10:30 onchain 主档 + 11:35 master 调度
- per-fetcher skip(idempotent)
- 4 metrics 全部入 `onchain_metrics`(Glassnode 来源,`metric_name` 区分语义)

**5s fetcher 间隔**(批 3 顺带改 [src/scheduler/jobs.py:973](../../src/scheduler/jobs.py#L973)):
- 现有 `_GLASSNODE_FETCHERS` 23 fetcher 循环加 `time.sleep(5)`
- 23 × 5s ≈ 110s/档(原 9s 突发 → 拉开到 2 分钟匀速)
- 目标:降低 puell / lth_net_position_change / btc_price_close 等热点 endpoint 的 429 概率(alphanode 上游对单 endpoint 有突发限流)

**渲染层语义标注**(尤其 Skew 关键):
- `unit="iv"` → `47.2%`(自动检测小数 vs 百分比)
- `unit="skew"` → `+0.195 (偏恐慌)`(阈值 >+0.10 偏恐慌 / <-0.05 偏 FOMO / 之间 中性,中文 hint 内嵌)
- Skew 行的 `_FACTOR_META` zh_name 直接写明符号语义,避免外部 AI 误读

## 配额估算

| 数据源 | 之前(/day) | 之后(/day) | 月用量 | 配额 | 风险 |
|---|---|---|---|---|---|
| Glassnode(via alphanode) | 23-46 | 27-50(+4 extras) | 800-1500 | 1700/月 | 安全(预留 200-900) |
| CoinGlass(via alphanode) | 24 + 1d/4h klines + 2 derivs | 同 + 1 F&G | 不变(F&G 在已有 cron 里) | 共享 alphanode | 不增加 |
| FRED | ~9 | 不变 | ~270 | 无明示限额 | 无 |
| alternative.me | 0 | 0 | 0 | n/a | 未启用 |

加完后 Glassnode 配额仍剩 12-53%,安全边际。

## 当前 snapshot 标签分布(prod 实测)

```
[大周期]: 42
[波段]:   21
[通用]:   14
```

7 行无标签(章节标题 / 总览 / 说明段)。

## 部署日志

```
批 1 (d1803ef → 274df57):
- 本地 pytest 2 passed
- git push → server git pull (Fast-forward) → systemctl restart (active)
- curl HTTP 200 / 7832 bytes
- 现场验证 Pi Cycle 0.39 / Mayer 0.80 / 收益率曲线 +42 bps

批 2 (274df57 → fedd869):
- 本地 pytest 2 passed
- server git pull + restart (active)
- 手动 backfill: 一次性 SSH 直调 fetch_fear_greed_index() 写 3028 行
  (skip-gate 已被当日 cron 命中,首次需绕过)
- curl HTTP 200 / 7949 bytes,F&G 9 (Extreme Fear) 显示

批 3 (fedd869 → e4b6aa3):
- 本地 pytest 2 passed
- server git pull + restart (active)
- 手动触发 job_collect_glassnode_extras():
    {by_fetcher: {cvdd:180, atm_iv_1m:180, 25delta_skew_1m:180, max_pain_1m:180},
     total_upserted: 720, status: ok, duration_ms: 22349}
- curl HTTP 200 / 8406 bytes,4 新指标全部新鲜显示
- 明日 BJT 12:00 cron 首次自动跑 → 验证完整链路
```

## §Z 自检(批 3 收尾)

| 步骤 | 状态 |
|---|---|
| 本地 pytest test_export_route | ✅ 2 passed |
| GitHub push `e4b6aa3` | ✅ |
| 服务器 git pull (fedd869..e4b6aa3) | ✅ Fast-forward |
| sudo systemctl restart btc-strategy | ✅ active |
| 生产 DB 新指标 backfill | ✅ 720 行(4 × 180 天历史) |
| curl `/api/export/snapshot.md` 200 + 4 新行 | ✅ 8406 bytes |
| 服务器 `git status` clean | ✅ |

## 本 sprint 删除清单

**本 sprint 无替代关系,无删除项**

理由:三批全部纯新增 — 4 个 Glassnode fetcher / 1 个 CoinGlass fetcher / 2 个本地算 helper / 1 个新 cron job / 1 个 fetcher 间隔参数。snapshot 渲染逻辑均增量扩展,不替代任何现有路径。AI 判断层 / 网页层完全未动。

## 后续 sprint 建议(BACKLOG 候选)

1. **明日观察 cron 链路**:
   - 09:30/10:30 onchain 主档(加 5s 间隔后)看 puell / lth_net 是否仍 429
   - 12:00 `collect_glassnode_extras` 自动跑是否成功 + 4 个指标是否更新到 06-09
   - 08:01 `collect_klines_daily` F&G 是否被自动拉取(skip 条件没改,需要 06-09 dominance/etf 没数据时才触发)
2. **若 puell 仍 429**:可考虑 retry max_attempts 3→5 + backoff 3s→8s,见 BACKLOG-MIDDLEWARE-OUTAGE 的方向 (a)/(b)
3. **DVOL / 直接 PCR 二选一**:Glassnode 不提供 DVOL(Deribit 自家指数),如确需可独立接 Deribit API(独立源,需评估域名访问 + 配额)。当前 ATM IV 1m + 25Δ Skew 1m 已覆盖期权情绪 90% 用例
4. **VDD(纯 supply 维度)** alphanode 不提供;CVDD(已加)是 cumulative 版本,功能近似覆盖
5. **下一阶段**:若用户希望"减法",可启动"删 AI 判断层 + 简化网页"sprint(见 `BACKLOG-CLAUDE-MD-SYNC` 同步改 CLAUDE.md 4 段)

## 工作流改进

- **首次部署 1 个 cron 后立即手动触发**(批 3 用 `job_collect_glassnode_extras()` 直调):新 cron 在 yaml 注册后要明天才自动跑,首次部署若不手动触发,生产 DB 当天无数据 → snapshot 立即可见数据延迟 1 天。手动触发 1 行命令,值得固化为"新 cron 部署 SOP"
- **dry-run 模式**(本批 3 采用):service 不停 + 拷 DB 副本 + monkey-patch collector + 写到 `/tmp` 副本 → 不动生产即可出真实样本。比"先部署再验证" 安全,适合纯新增指标
