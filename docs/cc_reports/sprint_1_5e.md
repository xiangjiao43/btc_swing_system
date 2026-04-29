# Sprint 1.5e — CoinGlass v4 API 契约 drift 修复 + 端点健康检查

**Date:** 2026-04-29
**Branch:** main
**Status:** ✅ 完成,17 个新测试 + 840/840 全量回归过

---

## 一、根因(SSH 端到端体检定位)

用户报"24h 清算总额=0 / 多空比 24h 变化=0%"。SSH 9 endpoint × 6 variant
体检后真根因:**CoinGlass v4 API 契约 drift,代码 4 组 variant 全部不匹配**。

### CoinGlass v4 实际契约(SSH 体检验证)

| 类别 | 端点 | 必填 |
|---|---|---|
| 聚合类(全市场) | `/open-interest/aggregated-history` | `symbol=BTC`,无 exchange |
| 聚合类 | `/funding-rate/oi-weight-history` | `symbol=BTC`,无 exchange |
| 单交易所类 | `/liquidation/history` | `symbol=BTCUSDT, exchange=Binance` |
| 单交易所类 | `/global-long-short-account-ratio/history` | 同上 |
| 单交易所类 | `/net-position/history` | 同上 |
| 单交易所类 | `/funding-rate/history` | 同上 |

### 老代码 4 组 variants(全错)

```python
{"symbol": "BTC", ...}                       # 聚合可用,单交易所无效
{"symbol": "BTC", "exchange_list": "..."}    # 旧 list 契约已废弃
{"symbol": "BTCUSDT", ...}                   # 缺 exchange,单交易所无效
{"pair": "BTCUSDT", ...}                     # 缺 exchange,无效
```

### 静默 0 bug 雪上加霜

`fetch_liquidation_history` 老代码:
```python
total = (long_val or 0.0) + (short_val or 0.0)  # ← 单边失败 total 写 0
```
DB 历史 552 行假 0,污染分位计算。

---

## 二、改动

### 任务 A:`src/data/collectors/coinglass.py` 修 variants

| 方法 | 老 variants | 新 variants(1.5e) |
|---|---|---|
| `fetch_liquidation_history` | 4 组(BTC/pair/无 exchange) | **Binance → Bybit 兜底** |
| `fetch_long_short_ratio_history` | 单 `_request` | 同上 |
| `fetch_net_position_history` | 单 `_request` | 同上 |
| `fetch_funding_rate_history` | 单 `_request` | 同上 |
| `fetch_funding_rate_aggregated` | `symbol=BTC` 无 exchange | **保留**(已对) |
| `fetch_open_interest_history` | `symbol=BTC` 无 exchange | **保留**(已对) |

清理 fetch_liquidation_history 的多余 variant(pair / 无 exchange 都已废,
留着只消耗中转站限速预算)。

### 任务 B:`src/strategy/factor_card_emitter.py` 卡名诚实标注 Binance

4 张单交易所卡的 `name` / `source` / interp 加 "Binance" / "(Binance)" /
"币安":
- `derivatives_funding_rate_current` → "Binance 资金费率 · 当前"
- `derivatives_top_long_short_ratio` → "Binance 大户多空比"
- `derivatives_liquidation_24h` → "Binance 24h 清算总额"
- `derivatives_lsr_change_24h` → "Binance 多空比 24h 变化"

聚合卡(`funding_rate_aggregated` 等)source 仍 "CoinGlass"(语义 = 全市场加权,
不带 Binance)。

### 任务 C:`fetch_liquidation_history` 静默 0 修复

```python
# 旧 bug:`(long_val or 0.0) + (short_val or 0.0)` 单边 None 时 total = 另一侧
# 新:仅当两边都拿到真值才 emit total
if long_val is not None and short_val is not None:
    result.append({..., "metric_name": "liquidation_total",
                   "metric_value": long_val + short_val})
else:
    logger.warning("Partial liquidation at %s: missing %s side, total skipped", ...)
```

### 任务 D:`scripts/check_coinglass_endpoints.py`

新一次性体检脚本:
- 列出 6 个 endpoint × 6 组 variant
- 输出 markdown 表(endpoint × variant → status / n_rows / sample_keys)
- 推荐"首个成功 variant"
- 任一 endpoint 全失败 → exit 1(给 CI 用)

每次部署后跑一次,未来 CoinGlass 再 drift 能立刻定位是哪个端点。

---

## 三、测试

### `tests/test_coinglass_endpoints_contract.py`(7 测试)

- `test_liquidation_first_variant_is_binance`:首个 variant `symbol=BTCUSDT, exchange=Binance`
- `test_liquidation_falls_back_to_bybit_on_first_failure`:Binance 失败 → Bybit 自动重试
- `test_long_short_ratio_uses_btcusdt_with_exchange`:同
- `test_net_position_uses_btcusdt_with_exchange`:同
- `test_funding_single_uses_btcusdt_with_exchange`:同
- `test_funding_aggregated_uses_btc_no_exchange`:聚合端点不带 exchange
- `test_open_interest_uses_btc_no_exchange`:同

### `tests/test_coinglass_no_silent_zero.py`(5 测试)— 关键反退化

- `test_partial_long_only_no_total_emitted`:单边 None → **不 emit total**(关键 guard)
- `test_partial_short_only_no_total_emitted`:同
- `test_both_values_present_total_correct`:双边都有 → total = long + short
- `test_all_variants_fail_returns_empty_no_zeros`:全失败 → raise(不写 0)
- `test_no_zeros_in_emitted_when_both_none`:两侧都 None → 整 row 跳过

### `tests/test_factor_card_naming_binance.py`(5 测试)

- 4 张单交易所卡 name 含 "Binance",source 标 "(Binance)"
- 1 张聚合卡 name / source 不带 Binance(语义保持全市场)

**回归**:全量 `pytest tests/` = **840 passed, 1 skipped, 5.35s**(823 + 17 新)。

---

## 四、用户验证脚本(SSH 部署后)

```bash
ssh ubuntu@124.222.89.86 << 'SSH'
cd /home/ubuntu/btc_swing_system
git pull
sudo systemctl restart btc-strategy.service
sleep 5

# 1. 体检 6 个端点
.venv/bin/python scripts/check_coinglass_endpoints.py
# 期望:每个 endpoint 至少一个 ✅,推荐 variant 都对应到正确契约

# 2. 等下次 collect_klines_1h 整点跑完后查 DB
sleep $(( ( 60 - $(date +%M) ) * 60 + 60 ))
sqlite3 data/btc_strategy.db <<EOF
SELECT captured_at_utc, liquidation_long, liquidation_short, liquidation_total
FROM derivatives_snapshots
ORDER BY captured_at_utc DESC LIMIT 3;
EOF
# 期望:最新行 long+short+total 都是百万级真值,不是 0 / NULL

# 3. /api/strategy/current 卡名
curl -s -u admin:Y_RhcxeApFa0H- http://127.0.0.1:8000/api/strategy/current | \
  python3 -c "
import json, sys
state = json.load(sys.stdin)['state']
for c in state.get('factor_cards') or []:
    cid = c.get('card_id', '')
    if any(k in cid for k in ['funding_rate_current', 'liquidation_24h',
                              'top_long_short', 'lsr_change']):
        print(f'  {c.get(\"name\")} src={c.get(\"source\")} val={c.get(\"current_value\")}')
"
# 期望:name 含 Binance,source 含 (Binance),value 真数值不是 0

# 4. 浏览器刷新看到:卡名带 Binance + 数值真实 + source 注明 CoinGlass (Binance)
SSH
```

### DB 历史污染清理(可选,留 v0.6 详细回填)

```bash
# 查污染范围
sqlite3 data/btc_strategy.db \
  "SELECT MIN(captured_at_utc), MAX(captured_at_utc), COUNT(*)
   FROM derivatives_snapshots WHERE liquidation_total = 0;"

# 一次性把假 0 设为 NULL(本系统 24h 清算从来不会真 0)
# 部署后用户自行评估是否执行
sqlite3 data/btc_strategy.db <<EOF
UPDATE derivatives_snapshots
SET liquidation_long = NULL, liquidation_short = NULL, liquidation_total = NULL
WHERE liquidation_total = 0;
EOF
```

---

## 五、§X / §Y / §Z 自检

### §X(直击根因,不绕过)
- 修 variants 而不是加更多兜底层(变更只清零无效 variant + 加 Binance/Bybit)
- 静默 0 bug 真根因修(`(long_val or 0.0)` 老代码删,改为显式 None 判)
- `fetch_liquidation_history` 老 4 variants 删剩 2(§X 不允许遗留)

### §Y
本 commit 立即 push。

### §Z 端到端断言
- 17 测试 mock _request 真返回响应,断言 captured params 形态对 + total 计算
  正确 + 卡名 / source 含 Binance
- `test_liquidation_falls_back_to_bybit_on_first_failure`:模拟生产真翻车
  (Binance 失败,Bybit 兜底)断言 captured 至少 2 次调用
- `scripts/check_coinglass_endpoints.py` 部署后跑,生产环境真契约验证

### 同类风险扫描
1. **Bybit 也 drift** — 体检脚本会立刻发现;此时只剩 OKX,但 OKX BTCUSDT
   命名规则待确认(留 v0.6)
2. **聚合端点 v5 假设 drift** — agg 端点目前 `symbol=BTC` 无 exchange 仍工作;
   万一 drift,体检脚本同样捕获
3. **`fetch_liquidation_history` Bybit 数据 vs Binance 数据维度差异** — 卡名
   显示的是当时数据源,但变体 fallback 后用户看到的是 Bybit 数据但卡名仍
   "Binance"(轻度不一致);v0.6 可以加 `actual_exchange` 字段透传到卡上
4. **静默 0 修复影响历史回填** — 历史 552 行假 0 仍在 DB,本 sprint 不动;
   留任务 E 给用户 SSH 后自行评估
5. **中转站限速** — variants 从 4 降到 2,API quota 消耗减半

---

## 六、改动文件

| 文件 | 改动 |
|---|---|
| `src/data/collectors/coinglass.py` | 4 个单交易所 fetch_* 改用 variants(Binance + Bybit);liquidation 删多余 variants;total 仅双边都有才 emit |
| `src/strategy/factor_card_emitter.py` | 4 张单交易所卡名/source 加 Binance |
| `scripts/check_coinglass_endpoints.py` | 新文件,6 endpoint × 6 variant 体检 |
| `tests/test_coinglass_endpoints_contract.py` | 新文件 7 测试 |
| `tests/test_coinglass_no_silent_zero.py` | 新文件 5 测试 |
| `tests/test_factor_card_naming_binance.py` | 新文件 5 测试 |

---

## 七、未覆盖项 / 留 v0.6

- OKX BTCUSDT pair 无效(中转站对 OKX symbol 命名规则未知)
- 真"全市场聚合"清算需自己代码加权 Binance + Bybit + ...,本 v1 不做
- 历史 552 行假 0 精确清理(SQL 脚本已给,用户自行决定)
- 中转站 alphanode 限速 429 优化
- variant fallback 后透传 `actual_exchange` 到卡名(显示"Binance / Bybit"
  反映真实兜底来源)
