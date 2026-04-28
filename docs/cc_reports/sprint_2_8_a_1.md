# Sprint 2.8-A.1 — SSE /strategy/stream 接入 latest_factor_cards 覆盖

**Date:** 2026-04-28
**Branch:** main
**Status:** ✅ 完成,6 个新测试 + 47 个相关回归全过

---

## 一、问题与决策

**Bug**:Sprint 2.8-A 让 `/api/strategy/current` 读 `latest_factor_cards` 表覆盖
`state.factor_cards`,但 `/api/strategy/stream`(SSE)没改 — 它仍然把
`strategy_state_history` 里 4h 前的 `factor_cards` 快照推下去。

**用户场景**:浏览器打开网页 → 前端立即用 `/current` 拿到最新卡片 → 30s 后 SSE
推送一条 event,`state.factor_cards` 是 4h 前快照 → 前端把刚显示的最新卡片
revert 回旧值,"抓取于"时间又跳回过去。

**用户决策**:抽公共函数 `_overlay_latest_factor_cards`,
`/current` 与 `/stream` 共用(§X 不允许两路重复实现);SSE 在 initial push +
polling loop 两处都要调。

---

## 二、改动

### 2.1 改动文件
- `src/api/routes/strategy.py`:
  - 新增 `_overlay_latest_factor_cards(row, conn)` helper(行 62–89)
  - `_get_current_impl` 从原来内联覆盖改为调 helper(行 92–105)
  - `strategy_stream.event_gen()` 在 initial push(行 143)和 polling loop
    (行 167)都调 helper

### 2.2 新建文件
- `tests/test_strategy_stream_overlays_latest.py`(6 测试)

---

## 三、测试

`tests/test_strategy_stream_overlays_latest.py`:

| 测试 | 验证 |
|---|---|
| `test_overlay_latest_factor_cards_dict_state` | helper 直测,state 是 dict 时原地覆盖 + 写 `meta.factor_cards_refreshed_at_utc` |
| `test_overlay_latest_factor_cards_string_state` | helper 直测,state 是 JSON 字符串时,解析后再覆盖 |
| `test_overlay_returns_row_when_latest_table_empty` | 冷启动:`latest_factor_cards` 表为空 → 原样返回 row |
| `test_overlay_handles_none_row` | 空 DB:row=None → 返回 None,不抛错 |
| `test_current_endpoint_still_overlays_after_refactor` | TestClient 回归:`/current` 抽公共函数后行为不变 |
| `test_stream_initial_and_loop_both_call_overlay` | source-level guard:`inspect.getsource(strategy_stream).count("_overlay_latest_factor_cards") >= 2` |

**为什么 SSE 用 source-level guard 而不是真 stream?**
TestClient 的 `iter_lines()` 在 SSE async generator(永远不关闭)上会无限阻塞,
break 不掉。最稳的反退化保护就是检查源码:`event_gen()` 里至少出现 2 次
`_overlay_latest_factor_cards`(initial + polling),
`_get_current_impl` 也用同 helper(确保不出现两路重复)。

**回归**:
- 新文件 6/6 pass
- `test_factor_cards_refresher.py`(2.8-A) 11/11 仍 pass
- 整个 `strategy or api or factor_cards` 范围 47/47 pass

---

## 四、用户验证脚本(SSH 部署后)

```bash
ssh ubuntu@124.222.89.86 << 'SSH'
cd /home/ubuntu/btc_swing_system
git pull
sudo systemctl restart btc-strategy.service
sleep 5

# 浏览器开页面,F12 Network → 找 /api/strategy/stream(EventStream tab)
# 1. 第一条 message(initial push):state.factor_cards 内 captured_at_bjt
#    应该是当下整点附近(latest_factor_cards 表的最新值)
# 2. 等 30 秒,看下一条 message:state.factor_cards 还是最新值
#    (而不是 4h 前 strategy_state_history 的旧快照)
# 3. 浏览器开页面什么都不动等 30s,衍生品卡"抓取于"时间不会跳回旧值
SSH
```

---

## 五、§X / §Y / §Z 自检

### §X(旧代码必须删除,不允许两路重复)
- `_get_current_impl` 原内联的覆盖逻辑已被 helper 替代,旧逻辑代码块已删
- SSE 之前没有覆盖逻辑,本次新增 — 用同一 helper(初始 + 轮询都调一次)
- `test_stream_initial_and_loop_both_call_overlay` 检查 `_get_current_impl`
  也用同 helper,防止未来有人退回到 inline 实现

### §Y
本 commit 立即 push(commit hash 见 commit message)。

### §Z 端到端断言
- `test_current_endpoint_still_overlays_after_refactor` 用真 TestClient + 真 SQLite +
  真 DAO,断言响应 JSON 的 `state.factor_cards[0].card_id == "NEW_C"`(不是 "OLD_C")
- helper 直测用真 SQLite,seed 双数据后断言 dict identity 内容

### 同类风险扫描
1. **SSE keep-alive heartbeat** — polling loop 没新数据时仍发 `: keep-alive\n\n`,
   行为不变
2. **conn 生命周期** — initial push 和 polling loop 各自获取独立 conn 并关闭,
   helper 不持有 conn 引用
3. **state 是 str 还是 dict** — `StrategyStateDAO.get_latest_state` 返回 dict 后
   `state` 字段已是 dict;但 helper 兼容 str 输入(`json.loads`),给 future-proof
4. **latest_factor_cards 表为空(冷启动 / 单测无 seed)** — helper 早返回 row,
   覆盖不生效 → SSE 推送的 `factor_cards` 退回 strategy_state_history 快照
5. **`_get_run_impl` 历史详情接口** — 未走 helper(`/runs/{run_id}` 是历史归档
   查询,应展示当时的 factor_cards 不应被实时数据覆盖,符合建模意图)

---

## 六、部署 checklist

- [ ] git pull
- [ ] `sudo systemctl restart btc-strategy.service`(无 schema 变更,无需迁移)
- [ ] 浏览器 F12 Network → /api/strategy/stream → 看 initial + 30s polling 的
      `state.factor_cards` 都是最新值
