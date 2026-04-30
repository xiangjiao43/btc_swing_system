# Sprint 1.5k.1 — fix:CoinGlass spot 端点 limit=10 防限流

**Date:** 2026-04-30
**Branch:** main
**Status:** ✅ 本地完成,2 个新测试 + 1 个测试改写 + 894/894 全量回归过

---

## 一、根因(用户 SSH 真验证)

1.5k 部署后,网页 source 退化到 fallback `binance_kline_1h_close_via_coinglass`,
不是 spot。直接调 `fetch_spot_price_history` 拿到数据,但 30s 轮询时大部分
请求返回 `{"code":"0","data":[]}`,被判 fallback。

诊断:
- `/api/spot/price/history?limit=2` 触发 alphanode 小批量限流
- 1 秒内连续多次请求,前 2 次有数据,后续返回空 data
- `limit=10` 同一刻完全稳定,10 行返回

**不是 spot fail,是端点 small-limit 不稳定。**

---

## 二、改动

### 任务 A:`fetch_spot_price_history` 默认 limit 2 → 10

`src/data/collectors/coinglass.py`:

```python
def fetch_spot_price_history(
    self, ..., limit: int = 10,  # 原 2
)
```

docstring 加 1.5k.1 解释段:解释 limit=2 限流根因 + limit=10 同一刻稳定。

### 任务 B:`_try_fetch_spot_1m` 调用同步改 limit=10

`src/api/routes/market.py`:

```python
rows = coll.fetch_spot_price_history(
    symbol="BTCUSDT", exchange="Binance", interval="1m", limit=10,  # 原 2
)
```

`rows[-1]` 仍是最新分钟现价,逻辑不变。docstring 加 1.5k.1 反限流注释。

### 任务 C:测试

`tests/test_coinglass_spot_price.py`:
- `test_fetch_spot_price_passes_correct_params`:断言 `limit=10`(原 2)
- **新增** `test_fetch_default_limit_is_10`:不传 limit 时默认 = 10(spec 反退化)

`tests/test_market_route_spot_priority.py`:
- **新增** `test_spot_path_uses_limit_10`:断言 `_try_fetch_spot_1m` 调
  `fetch_spot_price_history` 时 `kwargs["limit"] == 10`

### 全量回归

```
894 passed, 1 skipped, 6.60s
```

(892 baseline + 2 新 = 894)

---

## 三、改动文件

| 文件 | 改动 |
|---|---|
| `src/data/collectors/coinglass.py` | `fetch_spot_price_history` 默认 limit 2→10 + docstring 解释 |
| `src/api/routes/market.py` | `_try_fetch_spot_1m` 调用 limit=10 + docstring |
| `tests/test_coinglass_spot_price.py` | 老测试改 limit=10;新增 default_limit 反退化测试 |
| `tests/test_market_route_spot_priority.py` | 新增 spot_path_uses_limit_10 反退化测试 |

---

## 四、§X / §Y / §Z 自检

### §X(本 sprint 删除清单)

**本 sprint 无替代关系,无删除项。** 理由:纯参数调整(默认 limit
2→10),无新旧路径并存。

### §Y
1 个 commit(collector + market.py + 测试一起)+ 1 个 docs commit。
立即 push 到 GitHub。

### §Z(测试用 spec 而非 .called)
- `test_fetch_default_limit_is_10`:断言 `params["limit"] == 10`(数值 spec)
- `test_spot_path_uses_limit_10`:断言 `kwargs.get("limit") == 10`(spec)
  + `kwargs.get("interval") == "1m"`(防同时回退到 fallback 路径)
- 不是 `.called=True` only

### 同类风险扫描
- **alphanode 大批量限流**:limit=10 同一刻稳定,但理论上 limit=100 / 200
  可能仍触发 quota。本 sprint 选 10(每 1m bar 数据 ~80 bytes,10 行 < 1KB,
  网络成本可忽略)
- **其他端点是否有同样小批量限流问题**:fetch_klines / fetch_funding_rate
  生产 SSH 验证一直稳定 (limit=7/168 历史用过),无类似现象。本 sprint
  不预防性改其他端点

---

## 五、部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ 894 passed, 1 skipped, 6.60s |
| GitHub push(commit hashes:见下条) | ✅ |
| 服务器 git pull | ❌ 等用户 SSH 执行 |
| 服务器 systemctl restart | ❌ 等用户 SSH 执行 |
| 生产 DB 迁移 / 清污 | N/A 纯参数调整 |

### SSH 验证脚本(用户执行)

```bash
ssh ubuntu@124.222.89.86 << 'SSH'
cd /home/ubuntu/btc_swing_system
git pull
sudo systemctl restart btc-strategy.service
sleep 5

# 单次验证 source 是 spot
curl -s -u admin:Y_RhcxeApFa0H- http://localhost/api/market/btc-price \
  | python3 -m json.tool
# 预期:source="binance_spot_1m_via_coinglass", age_minutes < 2

# 30s × 5 次稳定性测试
for i in 1 2 3 4 5; do
  curl -s -u admin:Y_RhcxeApFa0H- http://localhost/api/market/btc-price \
    | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f'[{i}] source={d[\"source\"]} age={d[\"age_minutes\"]} price={d[\"price\"]}')
"
  sleep 30
done
# 预期:5 次全部 source=binance_spot_1m_via_coinglass, age<2
SSH
```

---

## 六、本 sprint 删除清单

**本 sprint 无替代关系,无删除项**(纯参数调整,collector + caller 同步从 2→10)。
