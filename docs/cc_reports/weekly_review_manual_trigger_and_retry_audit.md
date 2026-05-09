# weekly_review 手动触发 + retry 兜底机制审查(纯查 + 一次手动跑)

**日期**:2026-05-09 BJT
**类型**:事实核查 + 手动触发验证
**触发**:用户希望确认 weekly_review 真能跑出有质量的输出 + 失败兜底机制

## 结论一句话

**手动触发成功 ✅**:50 秒 AI 调用,成功写入 `weekly_reviews` 表 1 行,
critical_count=3,5 段全部填齐,**输出质量很高**(具体识别 AI 失败率 43% +
validator_16 激活率 46% + 给出 5 条具体改进建议含目标/建议/优先级);
**没有任何 retry**(`_wrap_job` 通用 wrapper,**不走** `job_pipeline_run_with_retry`
那条 30/60/60 重试链路);**周日 22:00 失败 → 直接 fallback_output 写 1 行
+ 写 alerts info,等下周日**(即周日 22:00 那次的具体 cron 跑只发生 1 次,
失败也写一行 fallback 输出,**没有跨日补救**;misfire_grace_time=1h 只是
"cron 错过 1h 内补跑",不是失败重试);告警 severity=critical 时插入 alerts
表,但 `notification_sent=0` 永远(无 outbound channel,延续 ai_failure_handling_audit
报告里的同样问题)。

## 段 2 — 关键事实

### A. 手动触发命令(无 CLI / 无 run-now API,直接 python -c)

```bash
ssh ubuntu@124.222.89.86 "cd /home/ubuntu/btc_swing_system && \
  set -a; source .env; set +a; \
  .venv/bin/python -c \"
from src.scheduler.jobs import job_weekly_review
result = job_weekly_review()
import json; print(json.dumps(result, default=str, indent=2))
\""
```

**关键**:必须 `source .env`(否则 `OPENAI_API_KEY not set` →
`degraded_client_unavailable` fallback)。生产 cron 走 systemd service 自带
.env(`EnvironmentFile=` 或 working-directory 自动读)— 周日 22:00 自然
触发不需要手动 source。

### B. 5 段输出实际内容(精简版)

**Section 1 — performance_summary**:
```
total_runs=65, successful_runs=37, ai_failures=28(43% 失败率)
thesis_created=0, closed_profit=0, closed_loss=0
weekly_pnl_pct=0.0, max_drawdown_pct=0.0
```

**Section 2 — system_health_diagnosis**(4 条):
- 🔴 critical:AI 失败率 43%(28/65),系统未能稳定生成 thesis
- 🔴 critical:系统完全冷启动,thesis_created=0,所有 PnL 0
- 🟡 warning:validator_16_change_mind 激活率 46%(19/41 days)异常高
- 🟡 warning:validator_23_conflict_missing 激活率 32%(13/41 days)偏高

**Section 3 — strategy_quality**:
```
thesis_quality: poor
break_conditions_calibration: 无法评估(0 thesis)
false_signals: ["系统未生成任何 thesis,无法判断信号质量"]
missed_opportunities: ["过去 7 天 BTC 市场可能存在波段机会,但系统完全
                       未捕捉(0 thesis 创建)"]
```

**Section 4 — hard_constraint_activation_review**(逐条 23 V,只摘 触发的几条):
```
validator_16_change_mind:    19/41 days,46% 触发,偏高
validator_23_conflict_missing: 13/41 days,32%,偏高
其他 21 条:0/41 days(无 thesis 创建,大部分 V 不触发)
position_cap_compressed_avg: null
thesis_lock_blocks_count: 0
channel_c_uses_count: 0
overall_evaluation: "数据不足,大多数 V 因 0 thesis 无法评估"
```

**Section 5 — adjustment_recommendations**(5 条,**3 条 high**):
1. 🔴 high:**降低 AI 失败率** — 检查 L3/L4 日志定位 28 次失败原因(数据源/
   模型超时/prompt 错误)+ 增加 AI 层重试和降级
2. 🔴 high:**稳定 AI 输出质量** — 审查 L4 prompt thesis 方向判断逻辑,
   消除矛盾指令;强化 counter_argument 必填要求 + schema 校验
3. 🔴 high:**排查系统冷启动** — 检查市场数据推送 / AI 层初始化 / 硬约束
   是否过严;手动触发一次完整运行
4. 🟡 medium:建立 AI 输出质量监控机制
5. 🟢 low:待系统稳定后(2-4 周 / 至少 10 thesis)重新评估硬约束阈值

**质量评估**:
- ✅ 提及具体的 AI 失败率 43% / validator 激活率百分比
- ✅ 把 19/41 days 这种统计写入 evidence
- ✅ 优先级 + 影响清晰
- ⚠️ 建议偏宽泛(没具体 "X 阈值改 Y 数值")— 跟 weekly_review_audit 报告
  一致(prompt 没强制数值)
- ❌ 没对比"5/3 系统 long → 实际涨"成败回顾(prompt 没问 + input 没接
  price_candles)— 跟 weekly_review_audit 报告一致

### C. retry 路径核实

```python
# src/scheduler/jobs.py:1305
def job_weekly_review(...):
    def _body(conn):
        ...
        try:
            out = agent.analyze(inp, client=build_anthropic_client())
        except Exception as e:
            logger.warning("weekly_review: agent raised: %s", e)
            out = agent._fallback_output()       # ← 失败:fallback,不 retry
        out = WeeklyReviewAnalyst.normalize_output(out)
        critical_count = ... count_critical_recommendations(out)
        # UPSERT weekly_reviews(失败也写 fallback 内容)
        ...
        AlertsDAO.insert_alert(...)
        conn.commit()
        return {...}
    return _wrap_job("weekly_review", _body, conn_factory=conn_factory)
                    # ↑ 通用 wrapper(只捕获 conn 异常 + 计时),
                    #   非 job_pipeline_run_with_retry(后者才走 30/60/60 重试)
```

**关键事实**:
- `_wrap_job`:只捕异常 + 计时,**没有 retry**(对比 `job_pipeline_run_with_retry`
  会跨 cron 调度 retry)
- AI 失败 → `_fallback_output()` → 仍写 1 行(fallback 内容)
- `misfire_grace_time: 3600`(1h)只是 "scheduler 错过周日 22:00 时,1h 内
  补跑一次" — 不是失败重试,是 scheduler 自身错过容忍

**结论**:周日 22:00 失败 = 当周 fallback 写 1 行 + 等下周日 22:00 重试
(即没有跨日补救机制)。

### D. cron 配置

```yaml
weekly_review:
  enabled: true
  cron: {day_of_week: 'sun', hour: 22, minute: 0}    # 周日 22:00 BJT
  misfire_grace_time: 3600                            # 1h 容忍
  max_instances: 1
```

### E. alerts 链路(继承 ai_failure_handling_audit 的同样问题)

job 末尾插入 1 行 alert:
```python
severity = "critical" if critical_count > 0 else "info"
alert_type = ("weekly_review_critical_recommendation"
              if critical_count > 0 else "weekly_review")
AlertsDAO.insert_alert(
    conn, alert_type=alert_type, severity=severity, message=msg,
    raised_at_utc=triggered_iso, related_run_id=None,
)
```

**手动触发后**:5/9 那行 alert(severity=critical,message="weekly_review
2026-05-04 完成:3 条 high priority 建议;weekly_pnl_pct=0.0")**已写入
DB**,但 `notification_sent=0`(无 telegram/webhook/smtp,跟其他 alert 一样
**用户不打开网页就看不到**)。

## 段 3 — 风险扫描

### 1. 失败兜底**单层**:fallback_output 仍写 1 行

AI 失败时:
- ✅ `agent._fallback_output()` 给一个最小合法 dict
- ✅ `normalize_output` 补齐缺漏 V
- ✅ UPSERT weekly_reviews 表(fallback 内容)
- ✅ 写 alerts(severity 取决于 fallback 含 critical 数 — 第一次 fallback 我
  实际看到 critical_count=1,因为 system_health_diagnosis 含一条
  "weekly_review_analyst AI 失败" warning,但 critical_count 算法可能把它
  算成 critical;待追查)

**好的一面**:不会"什么都没写",起码用户能在网页看到一行 fallback 报告。
**坏的一面**:用户可能误以为系统正常出报告(fallback 内容 ≈ "无法评估"
的样板),没主动告警就发现不了。

### 2. 跨日 / 跨周 重试缺失

- `weekly_review` 走 `_wrap_job` 而非 `_with_retry`
- `RetryPolicy(30/60/60)` **不应用**于 weekly_review
- 周日 22:00 失败 → 当晚 fallback 写 1 行 → **下次有效 review 是下周日**

7 天间隙内,如果用户依赖 weekly_review 调阈值,**会延迟 1 周拍板**。
对中长线策略影响有限(本来就是周级反馈),但存在。

### 3. alerts 是否接通 — **没有**

跟 `ai_failure_handling_audit.md` 同样问题:
- alerts 行写入 ✅
- `notification_sent` 永远 0(`mark_sent` 方法 0 caller)
- 没 telegram / webhook / smtp / server 酱

**用户感知方式**:周一打开网页 → 模块 5「📊 周复盘」直接显示最新 review
output(severity=critical 用红色标记)。如果用户连续几周不开网页 → 累积
若干 critical alerts,但都静默躺 DB。

### 4. notification_sent 何时被置 1?

`grep mark_sent src/`(我之前 audit 已确认)只在 dao.py 定义,**0 caller**。
所有 alerts 永远 notification_sent=0。这是 v1.0 上线纪律(主动推送通道
至少接通一种)的同一个未达成项。

### 5. 用户三个诉求被本次手动触发回答

| 诉求 | 答案 |
|---|---|
| weekly_review 手动触发成功? | ✅ 50s,1 行写入,critical_count=3 |
| 有 retry 吗? | ❌ 无 retry,fallback 仍写一行 |
| 周日 22:00 失败会怎样? | 当晚 fallback 写一行,等下周日 22:00 |

### 6. 手动触发的 weekly_review row 是否影响 5/10 自然触发?

`weekly_reviews` PK = `week_start_utc`(周一日期)。
- 我手动触发的 row:`week_start_utc='2026-05-04'`(本周一)
- 5/10 自然 cron 触发:`week_start_utc='2026-05-04'`(同一周,周日 5/10 还
  在 5/4-5/10 这周内)→ **UPSERT 会覆盖**手动触发那行
- 5/11(周一)是新一周,5/17 周日的 cron 才会写 `week_start_utc='2026-05-11'`

**所以**:本次手动触发不会污染 5/10 自然触发的结果(同周覆盖 → 5/10
新跑会刷新)。安全。

## 段 4 报告路径

`docs/cc_reports/weekly_review_manual_trigger_and_retry_audit.md`(本文件)

## 给用户的建议(纯查不改)

1. **5/10 周日 22:00 BJT 等自然触发**,看与本次手动触发输出是否一致 +
   是否有变化(thesis_created 应该仍是 0,Sprint G P0 5/10 当天首次自然
   master 11:35 跑通且给 A/B 才会 +1)
2. **现有 weekly_review 输出**已有可观察性(critical_count 红色 / 模块 5
   网页展示 + alerts 表行),用户主动开网页能看到。**没主动推送是已知
   缺口**(Sprint G+ 候选 P0:加 telegram bot)
3. **本次手动触发输出已揭示 3 条 high 优先级 critical**(AI 失败率 43% +
   validator_16/23 激活率偏高 + 系统冷启动)— 用户可参考,但用户应等
   Glassnode quota 恢复后 1-2 周再启动调整(报告里 5 条 #3 #4 #5 都说
   "稳定 2-4 周再评估")
4. **prompt 没强制 X→Y 数值**:weekly_review_audit 已说明,Sprint H 候选
   P2 改 prompt 强制具体数值
5. **没接 price_candles**:weekly_review_audit 已说明,Sprint H 候选 P0
   接入实际走势对比
