# Sprint 1.9-A Step 5.2 — 真 API 诊断脚本(本地不切生产)

**日期:** 2026-05-01
**范围:** 写诊断脚本 + 等用户 SSH 跑出真 stdout 后回贴
**状态:** 脚本已 push,**等用户跑**
**前置:** Sprint 1.9-A.5.1 完成(commit 7b46c2e)+ AI SDK 诊断(04c4358)

---

## 1. 脚本设计

`scripts/diagnose_orchestrator_real_api.py` — 5 步逐层诊断:

| Step | 做什么 | 失败影响 |
|---|---|---|
| 0 | 检查 DB 路径 + 项目根目录 | 无 DB → exit 2 |
| 1 | `build_anthropic_client(timeout=60)` 验 .env 读取 | 返回 None → exit 2 |
| 2 | `ContextBuilder.build_full_context()` 验数据形态 | 抛异常 → exit 2,traceback 打印 |
| 3 | `chart_renderer.render_l1/l2/l4_chart()` 各自独立 try | 失败用 None,不阻塞 |
| 4 | 逐层 `agent.analyze()` × 6,各自独立 try + 60s timeout + 计时 | 单层 fail 不停,后续层用 fallback dict 输入,可看完整链路 |
| 5 | 汇总表 + exit code(任一 fail → exit 1) |

**成本提示**:每次成功跑全链路 ≈ **$0.30**(全 6 AI 输入 ~50k tokens + 输出 ~10k tokens)。失败的层不消耗 token。

**关键设计**:
- 每层独立 try + 单独打印 START/OK/FAIL + traceback
- 60s timeout 通过 `build_anthropic_client(timeout=60)` 在 client 层设置
- 后续层用 fallback dict 输入(L1 fail → L2 用 L1.fallback_output 继续),
  可一次跑出**所有层的失败模式**,不用反复跑(节省 token)

---

## 2. 用户 SSH 跑命令

```bash
ssh ubuntu@124.222.89.86
cd /home/ubuntu/btc_swing_system
git pull origin main

# 真 API 诊断(消耗 ~$0.30 token)
.venv/bin/python scripts/diagnose_orchestrator_real_api.py 2>&1 | tee /tmp/diag.log

# 看汇总表
tail -20 /tmp/diag.log

# 把全文贴回这个对话(或贴关键 FAIL traceback)
```

---

## 3. 期望输出格式(脚本会打印)

```
============================================================
=== Step 5: 汇总表
============================================================
层       状态   耗时        输出/错误
--------------------------------------------------------------------------------
l1       OK       5.2s    status=success, tokens=8500/1200, model=claude-sonnet-4-5
l2       OK       6.5s    status=success, tokens=12000/1500, model=claude-sonnet-4-5
l3       OK       4.1s    status=success, tokens=4500/800, model=claude-sonnet-4-5
l4       OK       7.8s    status=success, tokens=15000/1700, model=claude-sonnet-4-5
l5       OK       4.8s    status=success, tokens=6000/1100, model=claude-sonnet-4-5
master   OK       8.0s    status=success, tokens=22000/3000, model=claude-sonnet-4-5
--------------------------------------------------------------------------------
TOTAL          36.4s

All 6 layers OK
```

或失败时:

```
l1       FAIL     2.3s    BadRequestError: image content_block not supported
l2       FAIL     0.5s    KeyError: 'klines_1d_30d_close'
...
FAILED layers: ['l1', 'l2', ...]
```

---

## 4. 已知潜在卡点(从 AI SDK 诊断 04c4358 推测)

| 卡点 | 症状 | 处置 |
|---|---|---|
| novaiapi proxy 不支持多模态 image content block | L1/L2/L4 fail with BadRequest / 400 | 改 chart_b64 → text-only 描述,或换真 anthropic api.anthropic.com |
| Claude 输出 JSON 不达预期 | status='degraded_ai_failed',JSON parse failed in log | 看 BaseAgent fallback 路径 last_error,prompt 微调 |
| ContextBuilder 在生产 DB 数据形态差异 | Step 2 ContextBuilder 抛异常(traceback 在日志) | 看异常类型,可能是 onchain/derivatives 字段名 / 时间格式差异 |
| L5 prompt 字段引用 sp500(已删 1.8.1)| L5 输出 degraded,提示某字段缺 | 不应该(1.8.1 已 NASDAQ 化),但若现 → 检查 prompt 残余 |

---

## 5. 等用户回填的 stdout 区域

(用户跑完贴这里,CC 会更新结论)

```
<待用户填入完整 stdout>
```

---

## 6. 待写的诊断结论

(根据用户 stdout,CC 后续填入:卡在哪层 / 总耗时 / 真实 token 消耗 / 推测原因 / 修法)
