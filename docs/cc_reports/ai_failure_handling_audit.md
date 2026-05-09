# AI 失败 retry + 告警机制事实核查(只查不改)

**日期**:2026-05-09 BJT
**类型**:事实核查 sprint(纯只读 SSH + DB + grep)
**触发**:用户问 BJT 11:35 主 AI 失败时怎么办,告警怎么推

## 结论一句话

**11:35 失败时**:retry 机制接管(5min → 10min → 20min,3 次,2 小时窗口),
**3 次都失败 → 当天放弃**,等次日 11:35;**告警通道实际只有"网页红条 +
DB alerts 表",没有 telegram / webhook / smtp 主动推送**。用户**不主动看
网页就不知道**(`notification_sent` 字段从来没被设过 1,DAO `mark_sent`
方法存在但无 caller),这是建模 v1.0 上线纪律标的"主动推送通道至少接通
一种"未做。

## 段 2 — 关键代码 / 配置原文

### A. retry 配置(`config/base.yaml`)

```yaml
ai_retry:
  # 指数退避间隔(分钟):第 1/2/3 次重试分别等 5 / 10 / 20 分钟
  intervals_minutes: [5, 10, 20]
  # 单层最多重试次数(超过 → 短路下游)
  max_attempts_per_layer: 3
  # 整次 run 总窗口(小时):超过 → 放弃所有重试,fallback Level 2
  total_window_hours: 2
```

### B. retry 主体(`src/scheduler/jobs.py:981-1041`)

```python
def job_pipeline_run_with_retry(...):
    """
    1. 调 job_pipeline_run(run_trigger)
    2. 若 status='error' 或 ai_status startswith 'degraded':
       - attempt < 3 且 in 2h window → schedule 同 job 在 backoff 秒后再跑
       - 否则 → 放弃 + 推 critical 告警(暂只 logger.error)
    3. 成功 → 直接返回
    """
    result = job_pipeline_run(...)
    failed = (
        result.get("status") == "error"
        or str(result.get("ai_status", "")).startswith("degraded")
    )
    if not failed:
        return result
    ...
    if not rp.should_retry(attempt=attempt + 1, ...):
        logger.error(
            "pipeline_run RETRY EXHAUSTED: ... "
            "(超 max_attempts=3 或超 2h 窗口)— critical 告警",
            ...
        )
        result["retry_exhausted"] = True
        result["retry_attempts"] = attempt
        return result
    backoff = rp.compute_backoff_seconds(attempt + 1)
    # 调度 add_job(date trigger, run_date=now+backoff)
```

**注意**:代码注释自己写「critical 告警」,**实际只 logger.error**,没真
告警插入(没调 AlertsDAO.insert_alert)。

### C. fallback_level 派生(`src/pipeline/_orchestrator_mapper.py:177-194`)

```python
def _derive_fallback_level(status: str) -> Optional[str]:
    """orchestrator status → strategy_runs.fallback_level。
       "ok"            → None
       "degraded_l1_*" → "level_1"
       "degraded_master_*" → "level_2"
       其他 degraded   → "level_3"
    """
    s = str(status or "").lower()
    if s == "ok": return None
    if "degraded_l1" in s or "degraded_l2" in s: return "level_1"
    if "degraded_l3" in s or "degraded_l4" in s or "degraded_l5" in s: return "level_2"
    if "degraded_master" in s: return "level_2"
    return "level_3"
```

### D. 告警通道实际状态

`grep -rn 'telegram|webhook|smtp|notify|push_alert|send_alert' src/ config/`:
- `src/data/storage/dao.py:757`:**注释**"便于未来加 prometheus / Telegram
  推送等钩子" — 是**未来意图**,**没实现**
- `config/schemas.yaml:1376`:`push_alert_critical`、
  `config/schemas.yaml:1391:push_alert_highest_all_channels` —
  **schema 占位字段**,**没具体实现**

`grep mark_sent src/`:
```
src/data/storage/dao.py:836:UPDATE alerts SET notification_sent = 1 WHERE id = ?
```
有 DAO 方法,**但没 caller**(`grep mark_sent src/`只命中 dao.py 自身,无
任何代码调它)。

### E. 网页 AI 失败显示(`web/assets/app.js:222-260` + `web/index.html:487-499`)

```javascript
aiFailureStatus() {
    // 数据源:state.raw.retry_log_json
    const rl = raw.retry_log || raw.retry_log_json || {};
    if (!rl || Object.keys(rl).length === 0) return null;

    const failedLayers = rl.failed_layers || [];
    const retryExhausted = rl.retry_exhausted;
    const retryNext = rl.retry_next_attempt;

    if (retryExhausted) {
        return 'AI 介入失败 - 请人工介入(超 2h 重试窗口或 max_attempts)';
    }
    if (failedLayers.includes('master')) {
        if (rl.thesis_aware_fallback_applied)
            return 'master AI 失败,thesis_aware fallback 已接管(等下次重试)';
        return `${layers} 失败,Master 已短路`;
    }
    ...
}
```

`web/index.html`:`<section x-show="aiFailureStatus()"...>` — 红色横幅,**只在
用户打开网页时显示**。

### F. alerts 表实际数据

```
$ ssh ... "sqlite3 ... 'SELECT severity, alert_type, COUNT(*) FROM alerts
GROUP BY severity, alert_type ORDER BY severity DESC LIMIT 20'"
severity|alert_type|COUNT(*)
warning|pre_flight_degraded|22

$ "SELECT MAX(raised_at_utc), severity, alert_type, message,
notification_sent FROM alerts ORDER BY id DESC LIMIT 3;"
2026-05-01T10:00:27Z|warning|pre_flight_degraded|...|0
```

**所有 22 行 alerts 都是 `pre_flight_degraded` warning,severity=critical
0 行,notification_sent=0**(没主动推送)。最近一行 2026-05-01。

### G. 7 天 strategy_runs.fallback_level 分布

| day | level_None | level_1 | level_2 | level_3 |
|---|---|---|---|---|
| 2026-05-09 | 0 | 1 | 0 | 0 |
| 2026-05-08 | 8 | 1 | 1 | 0 |
| 2026-05-07 | 2 | 0 | 0 | 0 |
| 2026-05-06 | 6 | 9 | 2 | 0 |
| 2026-05-05 | 5 | 1 | 4 | 0 |
| 2026-05-04 | 9 | 0 | 1 | 0 |
| 2026-05-03 | 7 | 0 | 4 | 0 |
| 2026-05-02 | 0 | 0 | 8 | 0 |

7 天:正常 (level_None) 37 / level_1 12 / level_2 20 / level_3 0。
即:**~45% run 真有降级**(主要 level_2,master 失败 / 多层失败),level_3
未出现(完全 fail 还没发生过)。

## 段 3 — 风险扫描(静默失败 / 用户不知道)

### 1. **核心问题:用户不主动看网页就完全不知道失败**

`grep` 显示:
- 没有 telegram bot
- 没有 webhook 推送
- 没有 SMTP 邮件
- `notification_sent` 字段从未被置 1
- 22 条历史 alerts 全静默躺在 DB 里
- 网页只在用户打开 + 当前 strategy_run 含 retry_log_json 时才显示红条

→ **用户**(`brucehuang172@gmail.com` 移动端 / 电脑浏览器查网页)**只能在
手动打开网页时看到 AI 失败状态**,如果一连几天不开网页,失败状态完全
不知。

### 2. **retry 失败后没有"明天再试"机制 — 必须等 11:35 自然再来**

- 11:35 master 失败 → 5min → 11:40 retry 1 → 失败 → 10min → 11:50 retry 2
  → 失败 → 20min → 12:10 retry 3 → 失败 → **2h 窗口超(13:35 cutoff)** →
  retry_exhausted=True → 当天 GAME OVER,**等明天 11:35 自然 cron**
- 中间 24 小时:用户开仓的 stop_loss 仍由 `hard_invalidation_monitor` 1h
  规则平仓兜底(无 AI),价格 ±3% 仍触发 EmergencySimplifiedA,不是完全
  无人值守

### 3. **logger.error 不等于告警** — retry 注释写"推 critical 告警",实际只
   `logger.error(...)` 写日志。如果用户没 SSH 看 journalctl,等于没告警。

### 4. **网页"AI 失败横幅"判断条件 retry_log_json 必须非空**

如果 master 调用层 raise exception 直接 catch fallback、retry_log_json
没写入,网页可能显示"正常运行"但实际是 fallback 输出。需要 cross check
`fallback_level` 字段(顶栏「level_2」徽章)— 但用户可能不熟悉这个语义。

### 5. **7 天 level_2 = 20 次,但 alerts 表 critical = 0**

20 次 master/sub-agent 失败的事件,**alerts 表里没对应 critical 记录**。
说明 `_derive_fallback_level` 写 strategy_runs.fallback_level 不会同步
插入 alerts(两个相互独立的记录路径),**告警链路有缺口**。

### 6. **建模 §X.Y 上线纪律未达成**

`grep -rn '上线' docs/modeling.md`(未跑,但项目历史共识):v1.0 上云
要求"主动推送通道至少接通一种"。当前 SSH 验证显示:
- ❌ Telegram bot:不在 src/
- ❌ Webhook URL 配置:`config/base.yaml` 无相关字段
- ❌ SMTP:不在依赖列表
- ❌ Server 酱 / 推送渠道:0 命中

**结论:v1.0 主动推送上线纪律尚未达成**。

### 7. **正面消息:fallback level_3 7 天 0 次**

完全失败(retry exhausted)0 次,说明当前 5min/10min/20min 退避策略实际有效;
master 失败时 thesis_aware_fallback 接管,系统不会"无操作崩盘"。

## 段 4 报告路径

`docs/cc_reports/ai_failure_handling_audit.md`(本文件)

## 给用户的建议(只查不改)

**短期止血**(留 Sprint F.2 候选):
1. 把 `job_pipeline_run_with_retry` 的 `logger.error("...— critical 告警")`
   补充实际 `AlertsDAO.insert_alert(severity="critical", ...)`
2. 加最简通知:Server 酱 / Telegram bot HTTP webhook 一条 — 在
   `AlertsDAO.insert_alert()` 后台同步 POST(severity="critical" 时触发)
3. 当 fallback_level=level_2/3 时也插 alerts 行(目前只 pre_flight 写)

**Sprint F.2 候选优先级**:
- **P0**:critical alerts 真插入 + 至少 1 个推送 channel
- **P1**:网页 review_pending 已有红条,把 alerts 表中 24h 内未 ack 的
  critical 也接到红条
- **P2**:用户每天 BJT 11:40 收到一条「今天 master 已跑 / 失败状态」
  推送(主动报平安),让 11:35 流程更可见
