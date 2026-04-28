# Sprint 2.8-E — 价格技术卡 fetched_at_bjt 按真实 timeframe 取时间

**Date:** 2026-04-28
**Branch:** main
**Status:** ✅ 完成,19 个新测试 + 665/665 全量回归过

---

## 一、问题与决策

**Bug**:网页硬刷,8 张价格技术卡"抓取于"全部显示 13:38:33(stale)。
诊断 `latest_factor_cards.cards_json`:同一份数据,衍生品卡=16:00:04(对),
价格技术卡=13:38:33(旧,4-24 那条 inserted_at)。

**根因**:`src/strategy/factor_card_emitter.py::_stamp_fetched_at` 的
`price_structure` 分支(原 line 396-398):

```python
elif category == "price_structure":
    ts_utc = klines_by_tf.get("1d") or klines_by_tf.get("4h") \
             or klines_by_tf.get("1h")
```

所有价格卡共用 `klines_by_tf['1d']`。但:
- 1d cron 只在 BJT 08:01 跑,今天还没跑
- `klines_by_tf['1d']` 是 4-24 legacy 旧 inserted_at
- 1h 衍生卡(距 ATH / 多周期一致性)被 1d 旧时间盖掉

**决策**:每张卡按真实依赖的 timeframe 取 `klines_by_tf[tf]`;新增 helper
`_resolve_price_structure_timeframe(card_id) -> str`。

---

## 二、改动

### 2.1 `src/strategy/factor_card_emitter.py`

**新增 helper**(行 ~410):
```python
def _resolve_price_structure_timeframe(card_id: str) -> str
```
8 个原始价格卡的映射规则:

| card_id 模式 | timeframe | 理由 |
|---|---|---|
| `price_drawdown_from_ath_*` | 1h | 距 ATH 跌幅靠 1h tick 实时刷 |
| `price_tf_alignment_4h_1d_1w_*` | 1h | 多周期一致性靠 1h 实时校验 |
| `price_adx_14_1d_*` | 1d | ADX-14 是 1d K 线衍生 |
| `price_atr_percentile_180d_*` | 1d | ATR 180 日分位是 1d 衍生 |
| `price_ma_20_*` ~ `price_ma_200_*` | 1d | MA 20/60/120/200 都是 1d 衍生 |

匹配优先级:`_1h 后缀 / 业务关键词 → _4h → _1w → _1d / MA / ADX / ATR-180`。
所有 8 张已知卡都有显式匹配(不走 default 1d)。

**改 _stamp_fetched_at**(行 396-398):
```python
elif category == "price_structure":
    tf = _resolve_price_structure_timeframe(c.get("card_id", ""))
    ts_utc = klines_by_tf.get(tf)
    if ts_utc is None:
        # legacy fallback:目标 tf 暂无数据
        ts_utc = (klines_by_tf.get("1d") or klines_by_tf.get("4h")
                  or klines_by_tf.get("1h") or klines_by_tf.get("1w"))
```

老的单行三元退化已删(§X)。

### 2.2 `tests/test_factor_card_emitter_timeframe.py`(新)

19 个测试:
- 8 个 parametrize 的 resolver 直测(每个原始 card_id 都断言对的 tf)
- 1 个 default fallback(未知 card_id → 1d)
- 6 个端到端:1h 衍生卡盖 1h 时间 / 1d 衍生卡盖 1d 时间(drawdown / tf_alignment / ma_20 / ma_200 / adx_14 / atr_180)
- 1 个组合断言:8 张卡同批 stamp,1h 组与 1d 组得到不同 fetched_at_bjt
- 3 个 legacy fallback(目标 tf 缺失 → 退回上一档)

---

## 三、测试

| 测试 | 验证 |
|---|---|
| `test_resolver_maps_known_price_cards[*]` | 8 张原始 price 卡都映射到正确 tf,不走 default |
| `test_resolver_default_falls_to_1d_for_unknown` | 未知 card_id → 默认 1d |
| `test_drawdown_from_ath_uses_1h` | 1h 盖到 17:00:01 BJT(1h 数据),不是 13:38:33(1d stale) |
| `test_tf_alignment_uses_1h` | 同上,多周期一致性 |
| `test_ma_20_uses_1d` / `test_ma_200_uses_1d` | MA 卡盖 1d 时间(真实业务期望) |
| `test_adx_14_uses_1d` / `test_atr_180_uses_1d` | 1d 衍生卡 |
| `test_full_set_distinguishes_1h_vs_1d` | **关键**:同批 8 张卡,1h 组 ≠ 1d 组(反"全卡共用 1d"退化) |
| `test_falls_back_to_1d_when_target_tf_missing` | 1h 缺 → drawdown 退到 1d |
| `test_falls_back_to_1h_when_1d_4h_missing` | 1d / 4h 缺 → MA 退到 1h |
| `test_no_klines_at_all_keeps_fetched_at_none` | 完全无 klines → 保留 None,前端走 captured_at |

**回归**:全量 `pytest tests/` = **665 passed, 1 skipped, 4.40s**(646 + 19 新)。

---

## 四、用户验证脚本(SSH 部署后)

```bash
ssh ubuntu@124.222.89.86 << 'SSH'
cd /home/ubuntu/btc_swing_system
git pull
sudo systemctl restart btc-strategy.service
sleep 5

# 1. 等下次 collect_klines_1h 整点(:00),latest_factor_cards 表会刷新
sleep $(( ( 60 - $(date +%M) ) * 60 + 60 ))

# 2. 浏览器硬刷 → 看 8 张价格技术卡的"抓取于"
#    1h 组:距 ATH 跌幅 / 多周期方向一致性 → 当下整点 + 几秒
#    1d 组:MA 20/60/120/200 / ADX-14 / ATR 180d → 仍是 4-24 13:38(因为 1d 没跑)

# 3. 命令行直接看 latest_factor_cards
sqlite3 data/btc_strategy.db <<EOF
SELECT json_extract(value, '\$.card_id') AS cid,
       json_extract(value, '\$.fetched_at_bjt') AS fetched
FROM latest_factor_cards, json_each(cards_json)
WHERE json_extract(value, '\$.category') = 'price_structure'
ORDER BY cid;
EOF
# 预期:drawdown / tf_alignment 是 1h 时间;MA / ADX / ATR 是 1d 时间

# 4. 明早 08:02 BJT 后(collect_klines_daily 跑完)
#    MA / ADX / ATR 等 1d 衍生卡 → 更新到 08:01:xx
SSH
```

---

## 五、§X / §Y / §Z 自检

### §X(旧代码必须删除)
- 老的 `ts_utc = klines_by_tf.get("1d") or ...` 单行三元已被新的两阶段(resolver + fallback)替代,旧逻辑代码删除
- 没新增重复实现:resolver 是单点,8 张卡通过 card_id 匹配;legacy fallback 沿用原优先级

### §Y
本 commit 立即 push。

### §Z 端到端断言
- `test_full_set_distinguishes_1h_vs_1d`:一次性 8 张卡同批 stamp,
  断言 1h 组 fetched=`"2026-04-28 17:00:01 (BJT)"`,
  1d 组 fetched=`"2026-04-24 13:38:33 (BJT)"`
- legacy fallback 三个测试,断言 tf 缺失时退到下一档,而非 None

### 同类风险扫描
1. **新加的价格卡(未来)** — 若 card_id 不在 resolver 匹配规则内,
   走 default 1d。可能再次出现"1h 衍生被 1d 时间盖"。**缓解**:
   `test_resolver_maps_known_price_cards` 列了所有当前已知 8 张卡;
   未来加新卡时,顺手在 parametrize 里加一行,即可强制开发者考虑映射
2. **`tf_alignment_4h_1d_1w` card_id 含 "_4h" / "_1d" / "_1w"** — 我的 resolver
   先匹配 "tf_alignment" 关键词,return 1h,不会被后面的 "_4h" / "_1d" 干扰。
   测试明确覆盖这种"多 tf 串"的 card_id
3. **`atr_percentile_180d` 不含 "_1d" / "_180d"** — 用 "atr_" + "180" 双关键词命中
4. **klines_by_tf 缺 1w** — 老 fallback 没有 1w,现在我加上 1w 兜底。
   生产 1w cron 周一早上跑,平时是有数据的,fallback 顺序末位即可

---

## 六、部署 checklist

- [ ] git pull
- [ ] `sudo systemctl restart btc-strategy.service`(无 schema 变更,无迁移)
- [ ] 等下次 1h cron(整点)
- [ ] 浏览器硬刷 → 价格技术 8 张卡"抓取于" 1h vs 1d 区分
- [ ] 明早 08:02 BJT 后,MA/ADX/ATR 1d 衍生卡更新
