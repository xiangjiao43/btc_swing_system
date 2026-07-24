# BTC Swing System — 数据字段清单

> 只读扫描,未改任何代码。数据样例取自**最近一次成功生成的数据包**
> `packages/analysis_package_2026-07-17.zip`(2026-07-17 14:32 BJT 生成,5 项校验全过)。
> 端点路径均为 alphanode 中转的 Glassnode 路径;分辨率参数统一 `i=24h`(日频)、`a=BTC`。

来源三分类图例:**GN** = Glassnode(经 alphanode 中转)｜ **CG** = CoinGlass ｜ **FRED** = FRED ｜ **计算** = 本地计算。

---

## 1. CSV 文件逐列清单

### 1.1 `btc_onchain_history.csv`
- 时间粒度:**日频**(日期列 `date`,格式 `YYYY-MM-DD`)
- 现有数据起止:**2021-01-01 … 2026-07-16**(2023 行)
- 采集脚本:`scripts/fetch_btc_onchain_history.py --full`(每次重拉 2021 至今全量)

| 列名 | 类型 | 单位 | 来源 | 来源明细(端点 / 公式) |
|---|---|---|---|---|
| date | str | — | — | 日期主键 |
| mvrv_z_score | float | 无(标准差归一) | GN | `/v1/metrics/market/mvrv_z_score` |
| nupl_ratio | float | -1~+1 | GN | `/v1/metrics/indicators/net_unrealized_profit_loss` |
| lth_net_position_change_btc | float | BTC(30d 净变化) | GN | `/v1/metrics/supply/lth_net_change` |
| realized_price_usd | float | USD | GN | `/v1/metrics/market/price_realized_usd` |
| close_usd | float | USD | GN | `/v1/metrics/market/price_usd_close` |
| liveliness | float | 0~1 比率 | GN | `/v1/metrics/indicators/liveliness` |
| illiquid_supply_btc | float | BTC | GN | `/v1/metrics/supply/illiquid_sum` |
| nrpl_usd | float | USD | GN | `/v1/metrics/indicators/net_realized_profit_loss` |
| lth_profit_btc | float | BTC | GN | `/v1/metrics/supply/lth_profit_sum` |
| lth_loss_btc | float | BTC | GN | `/v1/metrics/supply/lth_loss_sum` |
| sopr | float | ~1 比率 | GN | `/v1/metrics/indicators/sopr` |
| sopr_adjusted | float | ~1 比率 | GN | `/v1/metrics/indicators/sopr_adjusted` |
| lth_nupl_ratio | float | -1~+1 | GN | `/v1/metrics/indicators/nupl_more_155` |
| lth_realized_price_usd | float | USD | 计算 | 供给加权聚合 ≥6m 桶;依赖 `/v1/metrics/breakdowns/price_realized_usd_by_age` + `/v1/metrics/breakdowns/supply_by_age`(桶:6m_12m,1y_2y,2y_3y,3y_5y,5y_7y,7y_10y,more_10y) |

最后两行样例:
| date | mvrv_z_score | nupl_ratio | lth_net_position_change_btc | realized_price_usd | close_usd | liveliness | illiquid_supply_btc | nrpl_usd | lth_profit_btc | lth_loss_btc | sopr | sopr_adjusted | lth_nupl_ratio | lth_realized_price_usd |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-07-15 | 0.403805 | 0.182423 | -19185.270488 | 52908.577571 | 64713.876053 | 0.633437 | 12998380 | -284128200 | 9471294 | 5475982 | 0.994715 | 0.991453 | 0.241355 | 47889.600820 |
| 2026-07-16 | 0.374479 | 0.170641 | -23758.038270 | 52907.886977 | 63793.690740 | 0.633590 | 13008010 | -18186290 | 9351216 | 5594068 | 0.999649 | 0.999604 | 0.230539 | 47838.242386 |

### 1.2 `btc_swing_deriv_1d.csv`
- 时间粒度:**日频**(`date` = `YYYY-MM-DD`)
- 现有数据起止:**2018-02-01 … 2026-07-17**(3069 行)
- 采集脚本:`scripts/fetch_btc_swing_history.py`(模块 A,CoinGlass)

| 列名 | 类型 | 单位 | 来源 | 来源明细 |
|---|---|---|---|---|
| date | str | — | — | 日期主键 |
| open / high / low / close | float | USD | CG | `/futures/price/history`(BTC 永续/聚合) |
| volume_usd | float | USD | CG | `/futures/price/history` |
| funding_rate | float | 比率(单期) | CG | `/futures/funding-rate/history` |
| oi | float | USD | CG | `/futures/open-interest/aggregated-history` |
| long_short_ratio | float | 比率 | CG | `/futures/global-long-short-account-ratio/history` |
| liquidation_usd | float | USD | CG | `/futures/liquidation/history` |
| etf_flow_usd | float | USD | CG | `/etf/bitcoin/flow-history`(仅交易日,周末 NaN) |
| fear_greed | float | 0~100 指数 | CG | `/index/fear-greed-history` |

最后两行样例:
| date | open | high | low | close | volume_usd | funding_rate | oi | long_short_ratio | liquidation_usd | etf_flow_usd | fear_greed |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-07-16 | 64721.4 | 64974.5 | 63712.6 | 63801.0 | 8.376e9 | 0.007639 | 4.7399e10 | 1.18 | 2.760e7 | 79100000 | 26.0 |
| 2026-07-17 | 63801.1 | 64041.6 | 62655.0 | 62859.4 | 3.325e9 | 0.005017 | 4.6982e10 | 1.69 | 1.090e7 | NaN | 28.0 |

### 1.3 `btc_swing_deriv_4h.csv`
- 时间粒度:**4 小时**(`date` = `YYYY-MM-DD HH:MM`)
- 现有数据起止:**2025-07-15 16:00 … 2026-07-17 04:00**(2200 行)
- 采集脚本:同上(CoinGlass,4h resolution);比 1d 少 `etf_flow_usd` / `fear_greed`(那两个仅日频)

| 列名 | 类型 | 单位 | 来源 | 来源明细 |
|---|---|---|---|---|
| date | str | — | — | 4h 时间戳主键 |
| open / high / low / close | float | USD | CG | `/futures/price/history` |
| volume_usd | float | USD | CG | `/futures/price/history` |
| funding_rate | float | 比率(单期) | CG | `/futures/funding-rate/history` |
| oi | float | USD | CG | `/futures/open-interest/aggregated-history` |
| long_short_ratio | float | 比率 | CG | `/futures/global-long-short-account-ratio/history` |

最后两行样例:
| date | open | high | low | close | volume_usd | funding_rate | oi | long_short_ratio |
|---|---|---|---|---|---|---|---|---|
| 2026-07-17 00:00 | 63801.1 | 64041.6 | 63358.0 | 63538.1 | 1.507e9 | 0.007183 | 4.7135e10 | 1.43 |
| 2026-07-17 04:00 | 63538.0 | 63560.0 | 62655.0 | 62831.9 | 1.806e9 | 0.005057 | 4.6937e10 | 1.69 |

### 1.4 `btc_swing_macro.csv`
- 时间粒度:**日频/交易日**(`date` = `YYYY-MM-DD`;FRED 非交易日留空)
- 现有数据起止:**2024-06-03 … 2026-07-16**(550 行)
- 采集脚本:`scripts/fetch_btc_swing_history.py`(模块 B,FRED 直连官方 API,非 alphanode)

| 列名 | 类型 | 单位 | 来源 | 来源明细(FRED series_id) |
|---|---|---|---|---|
| date | str | — | — | 日期主键 |
| dxy | float | 指数 | FRED | `DTWEXBGS`(广义美元指数) |
| us10y | float | %(年化) | FRED | `DGS10` |
| us2y | float | %(年化) | FRED | `DGS2` |
| vix | float | 指数 | FRED | `VIXCLS` |
| nasdaq | float | 点 | FRED | `NASDAQCOM` |
| tips10y | float | %(实际利率) | FRED | `DFII10` |

最后两行样例(注:`dxy` 近期常空 = DTWEXBGS 周更滞后;07-16 行多列空 = FRED 当日未出点):
| date | dxy | us10y | us2y | vix | nasdaq | tips10y |
|---|---|---|---|---|---|---|
| 2026-07-15 | NaN | 4.55 | 4.13 | 15.67 | 26269.23 | 2.32 |
| 2026-07-16 | NaN | NaN | NaN | NaN | 25881.95 | NaN |

### 1.5 `btc_swing_options.csv`
- 时间粒度:**日频**(`date` = `YYYY-MM-DD`)
- 现有数据起止:**2024-06-01 … 2026-07-16**(776 行)
- 采集脚本:`scripts/fetch_btc_swing_history.py`(模块 C,Glassnode + 1 派生)

| 列名 | 类型 | 单位 | 来源 | 来源明细 |
|---|---|---|---|---|
| date | str | — | — | 日期主键 |
| atm_iv_1m | float | %(年化) | GN | `/v1/metrics/derivatives/options_atm_implied_volatility_1_month` |
| skew_25d_1m | float | 比率(put IV − call IV) | GN | `/v1/metrics/derivatives/options_25delta_skew_1_month` |
| max_pain_1m | float | USD | GN | `/v1/metrics/options/max_pain` |
| est_leverage_ratio | float | 比值(OI/交易所余额) | GN | `/v1/metrics/derivatives/futures_estimated_leverage_ratio` |
| pcr_volume | float | ~1 比率 | GN | `/v1/metrics/derivatives/options_volume_put_call_ratio` |
| atm_iv_1w | float | %(年化) | GN | `/v1/metrics/derivatives/options_atm_implied_volatility_1_week` |
| sth_mvrv | float | ~0.5~2 比率 | GN | `/v1/metrics/market/mvrv_less_155` |
| sth_realized_price_usd | float | USD | 计算 | 供给加权聚合 STH 5 桶(24h,1d_1w,1w_1m,1m_3m,3m_6m);依赖 `price_realized_usd_by_age` + `supply_by_age` |

最后两行样例:
| date | atm_iv_1m | skew_25d_1m | max_pain_1m | est_leverage_ratio | pcr_volume | atm_iv_1w | sth_mvrv | sth_realized_price_usd |
|---|---|---|---|---|---|---|---|---|
| 2026-07-15 | 33.371873 | 0.147123 | 63000.0 | 0.288231 | 0.241806 | 30.47704 | 0.931756 | 73893.629163 |
| 2026-07-16 | 34.341897 | 0.141851 | 64000.0 | 0.286466 | 0.866570 | 32.10005 | 0.919156 | 73905.754402 |

---

## 2. Glassnode 调用次数统计 + 三 job 重复拉取

一次「完整采集」= 3 个 job 各跑一遍(两个 APScheduler 每日 job + 每周 refresh cron)。**只统计 Glassnode(alphanode)调用;CoinGlass / FRED 不算。**

| Job | 触发 | Glassnode 指标数 | Glassnode HTTP 调用数 |
|---|---|---|---|
| `collect_onchain`(`_GLASSNODE_FETCHERS`) | APScheduler 每日 09:30 主 + 10:30 补救 | 22 个 fetcher | ~22–24(`lth_realized`/`sth_realized` 各需 2 个 breakdown 端点) |
| `collect_glassnode_extras`(`_GLASSNODE_EXTRAS_FETCHERS`) | APScheduler 每日 10:50 | 4(cvdd, atm_iv_1m, 25delta_skew_1m, max_pain_1m) | 4 |
| `refresh_and_build` → `fetch_btc_onchain_history.py` | cron(原每日,7/14 起每周五) | 13 简单 + 1 派生 | 15(含 lth_realized 2 端点) |
| `refresh_and_build` → `fetch_btc_swing_history.py` 模块 C | 同上 cron | 7 简单 + 1 派生 | 9(含 sth_realized 2 端点) |
| **合计(一次完整采集)** | — | — | **≈ 50 次 Glassnode 调用** |

> 注:`collect_onchain` 的 10:30 是「per-fetcher 补救档」——只重试当天还没入库的 fetcher;健康日 ≈ 0 额外调用。
> 每日固定消耗(不含每周 refresh)= collect_onchain ~22 + extras 4 ≈ **26 次/天**。

### 2.1 三 job 重复拉取的同一 metric

以下 **10 个 metric 被 ≥2 个 job 各拉一次**(同一份 Glassnode 数据重复消耗配额):

| metric | 端点 | 被哪些 job 拉 | 重复次数 |
|---|---|---|---|
| mvrv_z_score | `/market/mvrv_z_score` | collect_onchain + refresh(onchain) | 2× |
| nupl | `/indicators/net_unrealized_profit_loss` | collect_onchain + refresh(onchain) | 2× |
| realized_price | `/market/price_realized_usd` | collect_onchain + refresh(onchain) | 2× |
| sopr_adjusted | `/indicators/sopr_adjusted` | collect_onchain + refresh(onchain) | 2× |
| lth_net_position_change | `/supply/lth_net_change` | collect_onchain + refresh(onchain) | 2× |
| lth_realized_price | breakdowns ×2 | collect_onchain + refresh(onchain) | 2×(各 2 端点) |
| sth_realized_price | breakdowns ×2 | collect_onchain + refresh(模块 C) | 2×(各 2 端点) |
| atm_iv_1m | `/derivatives/options_atm_implied_volatility_1_month` | collect_glassnode_extras + refresh(模块 C) | 2× |
| skew_25d_1m (25delta_skew) | `/derivatives/options_25delta_skew_1_month` | collect_glassnode_extras + refresh(模块 C) | 2× |
| max_pain_1m | `/options/max_pain` | collect_glassnode_extras + refresh(模块 C) | 2× |

- **重复浪费**:10 个 metric × 第 2 次拉 ≈ **10–12 次冗余 HTTP 调用 / 完整采集**(≈ 占 ~50 次里的 **~24%**)。
- **额外的 job 内重复**:`collect_onchain` 里 `lth_realized_price` 与 `sth_realized_price` **都各自**拉 `price_realized_usd_by_age` + `supply_by_age` 这**同 2 个 breakdown 端点** → 这 2 个端点在一个 job 内被拉 2 遍。
- **根因**:`collect_onchain`/`collect_glassnode_extras` 已把数据写进 DB,但 `refresh_and_build` 的两个 fetch 脚本**又重新调 Glassnode 拉一遍**写 CSV,而不是读 DB。若 refresh 改读 DB,可把它那 24 次 Glassnode 调用降到 **0**。

---

## 3. `snapshot.md` 每字段取值来源

来源判定依据:snapshot 每行的 `抓取于 <时刻>` / `计算于 <时刻>` 标注 + 采集器时刻(GN collect_onchain≈13:0x、GN extras≈10:50、CG≈14:01、FRED≈08:0x)。

### 3.1 价格技术
| 字段 | 来源 | 明细 |
|---|---|---|
| BTC 现价 | CG | 实时价(build 时) |
| 距 ATH 跌幅 / MA200(日)/ MA200(周)/ 距 MA200W 偏离 / 月线结构 / 主要支撑阻力 | 计算 | CoinGlass K 线派生 |
| 4h EMA20 / 4h EMA50 / EMA50 30d 斜率 / ADX(14,1d)/ ADX 5d 均值 / ATR(14,1d)/ ATR 180d 百分位 / 90d 区间相对位置 / 60d 最大回撤 / 最近 3 swing high / 最近 3 swing low | 计算 | CoinGlass K 线派生 |

### 3.2 大周期估值/择时
| 字段 | 来源 | 明细 |
|---|---|---|
| Pi Cycle Ratio(SMA111/SMA350×2) | 计算 | close 派生 |
| Mayer Multiple(close/SMA200) | 计算 | close 派生 |
| CVDD | GN | `/v1/metrics/indicators/cvdd`(collect_glassnode_extras) |

### 3.3 链上
| 字段 | 来源 | 明细 |
|---|---|---|
| MVRV-Z 分数 | GN | `/market/mvrv_z_score` |
| MVRV | GN | `/market/mvrv` |
| NUPL | GN | `/indicators/net_unrealized_profit_loss` |
| Realized Price | GN | `/market/price_realized_usd` |
| LTH Realized Price | GN(派生) | breakdowns ≥6m 桶聚合 |
| STH Realized Price | GN(派生) | breakdowns <6m 桶聚合 |
| LTH MVRV | GN(派生) | collect_onchain(抓取 13:08);LTH realized price + close 派生 |
| STH MVRV | GN | `/v1/metrics/market/mvrv_less_155` |
| 盈利供给占比 | GN | `/v1/metrics/supply/profit_relative` |
| RHODL Ratio | GN | `/v1/metrics/indicators/rhodl_ratio` |
| Reserve Risk | GN | `/v1/metrics/indicators/reserve_risk` |
| Puell Multiple | GN | `/v1/metrics/indicators/puell_multiple` |
| 算力 Hash Rate | GN | `/v1/metrics/mining/hash_rate_mean` |
| LTH 持仓量 | GN | `/v1/metrics/supply/lth_sum` |
| STH 持仓量 | GN | `/v1/metrics/supply/sth_sum` |
| SOPR (Adjusted) | GN | `/v1/metrics/indicators/sopr_adjusted` |
| CDD | GN | `/v1/metrics/indicators/cdd` |
| SSR | GN | `/v1/metrics/indicators/ssr` |
| LTH SOPR | GN | `/v1/metrics/indicators/sopr_more_155` |
| STH SOPR | GN | `/v1/metrics/indicators/sopr_less_155` |
| LTH 净仓位变化 | GN | `/v1/metrics/supply/lth_net_change` |
| 交易所余额 | GN | `/v1/metrics/distribution/balance_exchanges` |
| 交易所净流量 | GN | `/v1/metrics/transactions/transfers_volume_exchanges_net` |
| LTH 90d 持仓变化 / STH 90d 持仓变化 / HODL 1y+ 占比 / 亏损供给占比 / 交易所净持仓变化 / 交易所 30d 累计净流量 | 计算 | 上面 GN 列的窗口派生(计算于 14:32) |

### 3.4 衍生品
| 字段 | 来源 | 明细 |
|---|---|---|
| BTC ETF 日净流入 | CG | `/etf/bitcoin/flow-history` |
| BTC Dominance | CG | 实时 |
| 资金费率 | CG | `/futures/funding-rate/history` |
| 未平仓 OI | CG | `/futures/open-interest/aggregated-history` |
| 多空比 | CG | `/futures/global-long-short-account-ratio/history` |
| 24h 全网爆仓 | CG | `/futures/liquidation/history` |
| BTC ETF 7d/30d 累计 / 资金费率 90d Z / OI 90d Z | 计算 | CG 列窗口派生 |
| ATM IV 1月 | GN | `/derivatives/options_atm_implied_volatility_1_month`(extras) |
| 25Δ Skew 1月 | GN | `/derivatives/options_25delta_skew_1_month`(extras) |
| Max Pain 1月 | GN | `/options/max_pain`(extras) |

### 3.5 宏观(FRED 走 `collect_macro`,9 个 series,比 CSV 的 6 列多)
| 字段 | 来源 | 明细(FRED series) |
|---|---|---|
| Fear & Greed Index(CoinGlass) | CG | `/index/fear-greed-history` |
| 美元指数 DXY | FRED | `DTWEXBGS` |
| 美 10y 国债收益率 | FRED | `DGS10` |
| 美 2y 国债收益率 | FRED | `DGS2` |
| 10y TIPS 真实利率 | FRED | `DFII10` |
| 联邦基金利率 | FRED | `DFF`/`FEDFUNDS` |
| CPI(月度) | FRED | `CPIAUCSL` |
| Core CPI(月度) | FRED | `CPILFESL` |
| M2 货币供应 | FRED | `M2SL` |
| 美联储资产负债表 | FRED | `WALCL` |
| VIX 恐慌指数 | FRED | `VIXCLS` |
| 纳斯达克指数 | FRED | `NASDAQCOM` |
| 收益率曲线(10Y-2Y)/ BTC-纳指 60d 相关性 | 计算 | 上面 FRED 列派生 |

### 3.6 事件日历
| 字段 | 来源 | 明细 |
|---|---|---|
| 已发生(过去 72h)/ 即将发生(未来 168h) | 计算/DB | 本地 `events_calendar` 表 |

---

## 4. 5 项校验的判定逻辑与阈值

逻辑源:`scripts/refresh_and_build.py::validate()`。任一项失败 → **当日不打包 zip**。

| 校验项 | 判定逻辑 | 阈值 |
|---|---|---|
| **a) CSV 新鲜度** | 逐个读 5 CSV,取最新 `date`,算 `lag = 今日(BJT) − 最新日期`。`lag > 阈值` 或读取抛异常 → 失败 | onchain **≤2d**、deriv_4h **≤1d**、deriv_1d **≤1d**、macro **≤7d**、options **≤2d** |
| **b) 新增列非空** | 指定「新增列」在**最新一行**必须非空;空表 / 缺列 / 最新行该列为空 → 失败 | onchain 查 8 列:liveliness, illiquid_supply_btc, nrpl_usd, lth_profit_btc, lth_loss_btc, sopr, sopr_adjusted, lth_nupl_ratio ｜ options 查 5 列:est_leverage_ratio, pcr_volume, atm_iv_1w, sth_mvrv, sth_realized_price_usd |
| **c) snapshot 真异常 = 0** | 拉 `/api/export/snapshot.md`,正则抓「真异常 N」。`N>0` 或找不到统计行 → 失败(附真异常明细) | **真异常必须 = 0**(「真异常」= 日频数据超出周末/节假日窗口仍未更新;慢变量/结构性滞后不计) |
| **d) BTC 现价锚点** | 从 snapshot 抓 BTC 现价,与 `btc_swing_deriv_1d.csv` 最新 `close` 比,相对差 `rel = |snap−csv|/csv` | **rel ≤ 5%**(commit dfd6b91 由 1% 放宽到 5%) |
| **e) snapshot 端点存活** | 请求 `/api/export/snapshot.md`,HTTP 状态码 | **必须 200**(非 200 → API 服务未存活) |

> 与今日(2026-07-24)状态页对应:a) onchain 读取 ValueError('nan')+ options lag 8d>2d 失败；b) onchain 空表失败；c) 真异常 20 失败；d)/e) 通过。根因见 `docs/cc_reports/`(Glassnode 周期配额耗尽,链上/期权全 403)。
