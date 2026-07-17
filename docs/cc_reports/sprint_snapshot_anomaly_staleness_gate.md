# Sprint: 修复分析包"真异常=13"误报(健康哨兵改为新鲜度窗口口径)

## Triggers（偏离建模的自主决策）

- 无建模冲突。本次为 export 端点健康哨兵 bug 修复,使实现对齐其自身文档定义
  (§export snapshot 行内注释:"真异常 = 日频数据超出周末/节假日仍未更新")。
  未改 docs/modeling.md 主线,未改核心状态机 / 证据层。

## 问题现象

生产页面 `/api/export/pack`(2026-07-17)校验 c)「snapshot 真异常 = 0」失败,
报 13 项真异常:

> Realized Price, LTH Realized Price, STH Realized Price, 盈利供给占比,
> STH 持仓量, SOPR (Adjusted), CDD, SSR, LTH 净仓位变化, 交易所余额,
> 美 10y 国债收益率, 美 2y 国债收益率, 10y TIPS 真实利率

**同一页面底部 CSV 新鲜度表却全绿**:
- `btc_onchain_history.csv` = 2026-07-16(距今 1d,阈值 ≤2d ✅)
- `btc_swing_macro.csv` = 2026-07-15(距今 2d,阈值 ≤7d ✅)

→ 同页两套新鲜度口径自相矛盾。

## 根因

`src/api/routes/export.py::render_snapshot_markdown` 里的「真异常」分类器与
`_fresh_tag`(新鲜度总览 / CSV 表 / 逐项标签用的口径)判据不同:

| 判据 | 用什么 | 结果 |
|---|---|---|
| `_fresh_tag`（新鲜度表） | 数据日期 `as_of` vs 每因子阈值 `_STALE_DAYS_BY_FACTOR`（链上 3d / FRED 利率 8d…） | 13 项全部「新鲜」 |
| 真异常分类器（旧） | 「今天 BJT 0:00 起是否插入了新 DB 行」`inserted_at_utc >= today_bjt_midnight` | 13 项「真异常」 |

对 **T+1 链上**(realized_price / cdd / ssr / STH 持仓量 …)和 **周更 FRED 利率**
(us10y / us2y / real_yield),"当天没有新行"是正常节奏,不是故障。旧分类器把
"当天没写新行"直接当故障,于是每逢上游按慢节奏发布就误报。

这也是**逐批往 `_SLOW_UPDATE_FACTORS` 白名单打补丁**循环的根源(近期 commit
`4616774` 刚把 fed_funds_rate + fed_balance_sheet 塞进白名单,治标不治本)。

代码行内注释早已把真异常定义为"日频数据**超出**周末/节假日仍未更新",但旧实现
从未对任何"窗口"做比较 —— 修复即让代码符合它自己写的定义。

## 改动

### `src/api/routes/export.py`

1. 新增 `_exceeds_stale_threshold(factor_key, leaf)`(紧接 `_fresh_tag` 后):
   与 `_fresh_tag` 用**同一张阈值表**判断数据 `as_of` 是否超期。这是唯一的
   "真异常"判据。缺失(无值)亦算异常。

2. 重构分类循环(原 lines 847–866):当天没抓到新行的项,
   - **先**看 `_exceeds_stale_threshold` —— 超期才进 `anomaly`;
   - 未超期则按原因归档到新桶 `structural_lag`(结构性滞后,非故障),
     `_TODAY_PENDING_CRON_FACTORS` / `_SLOW_UPDATE_FACTORS` 仍分别驱动
     `pending_cron` / `monthly_pending` 展示桶。

3. 摘要行新增「结构性滞后 N」档;明细区新增一行
   「结构性滞后(当天源未出新点,但数据仍在新鲜度窗口内,非故障):…」。

**未删除** `_SLOW_UPDATE_FACTORS` / `_TODAY_PENDING_CRON_FACTORS`:两者仍用于
把慢变量 / 待 cron 项与结构性滞后项分桶展示(语义区分),不是死代码。

### `tests/test_export_route.py`

- `test_snapshot_summary_has_structural_lag_bucket`:摘要含新桶。
- `test_stale_threshold_within_window_not_anomaly`:回归锁 —— 链上 1d/2d、
  FRED 利率 6d 均**不**判真异常(复现 2026-07-17 的 13 项误报场景)。
- `test_stale_threshold_beyond_window_is_anomaly`:链上 5d、us10y 10d、缺失
  **仍**判真异常(哨兵未被削弱)。

## 校验行为(修复后)

- 13 项(链上 T+1 + FRED 周更利率)数据都在窗口内 → 不再进真异常 → 校验 c) 通过,
  分析包可正常打包下载。
- 若上游真的断更超窗(链上 >3d / us10y >8d / 缺失),仍会触发真异常拦截 —— 哨兵保留。
- 门禁解析正则 `真异常\s+(\d+)` / `真异常：([^\n]+)` 不受影响(已验证)。

## 验收记录

- `pytest tests/test_export_route.py` → 5 passed(2 原 + 3 新)
- `pytest tests/test_export_route.py tests/test_web_modules_4_5_rp_failure.py` → 52 passed
- 门禁正则 sanity:摘要新增「结构性滞后」档后仍正确抽出真异常计数 = 0

## 本 sprint 删除清单

**本 sprint 无替代关系,无删除项。** 纯 bug 修复 + 新增防御分类桶;
`_SLOW_UPDATE_FACTORS` / `_TODAY_PENDING_CRON_FACTORS` 保留(仍驱动展示分桶)。

## 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push(commit hash: 见下方 commit) | ✅（push 后回填）|
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart btc-strategy | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A（无 DB 改动，仅分类逻辑）|

**部署命令(待用户在服务器执行)**:
```
cd ~/btc_swing_system && git pull origin main
sudo systemctl restart btc-strategy
# 重建今日分析包(让页面刷新到新口径):
python3 scripts/refresh_and_build.py
```
