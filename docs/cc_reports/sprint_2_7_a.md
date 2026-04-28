# Sprint 2.7-A — scheduler.yaml 整点 cron 改造

**Date:** 2026-04-27
**Branch:** main
**Status:** ✅ 完成,等用户 SSH 部署 + journalctl 验证

---

## 一、改动

### `config/scheduler.yaml`(完全重写)
- timezone:`UTC` → **`Asia/Shanghai`**(BJT)
- 老配置 **删除**(§X):
  - `pipeline_run interval='4h'`
  - `data_collection interval='1h'` 整个 yaml 条目
- 新增 8 个 yaml 条目(7 logical jobs):

| 条目 | cron / interval | 描述 |
|---|---|---|
| `collect_klines_1h` | `cron: {minute: 0}` 每整点 :00 BJT | 1h K 线 + 衍生品 1h(2.7-B 实施)|
| `collect_klines_daily` | `cron: {hour: 8, minute: 1}` | 1d/4h K 线 |
| `collect_klines_weekly` | `cron: {day_of_week: 'mon', hour: 8, minute: 1}` | 1w K 线 |
| `collect_macro` | `cron: {hour: 6, minute: 0}` | FRED 9 series |
| `collect_onchain` | `cron: {hour: 8, minute: 35}` | Glassnode 13 metric |
| `pipeline_run_regular` | `cron: {hour: '0,4,12,16,20', minute: 5}` | 5 档常规 pipeline |
| `pipeline_run_8h_onchain` | `cron: {hour: 8, minute: 40}` | 8 点链上档 pipeline |
| `event_listener` | `interval: '60s'` | 事件常驻(2.7-D 实施)|

### `src/scheduler/jobs.py`
- 6 个新 stub 函数(2.7-B 替换 5 个 + 2.7-D 替换 event_listener):
  - `job_collect_klines_1h / job_collect_klines_daily / job_collect_klines_weekly /
     job_collect_macro / job_collect_onchain / job_event_listener`
- `_JOB_FUNCTIONS` 注册 7 个新名 + 老的 `pipeline_run / data_collection / cleanup`
  (老 `data_collection` 在 2.7-B 删除)
- `build_job_configs` 加 `func` 字段支持 — 允许多 yaml 条目共享同函数
  (`pipeline_run_regular` + `pipeline_run_8h_onchain` 都跑 `pipeline_run`)。
  默认 `func = name` 向后兼容。

---

## 二、测试

`tests/test_scheduler_2_7_a_cron.py`(15 测试):
- yaml timezone = Asia/Shanghai
- yaml 8 条目结构
- §X:`data_collection` + `pipeline_run interval` 已删除
- 每个 cron job 时间戳精确匹配(:00 / 08:01 / Mon 08:01 / 06:00 / 08:35 /
  '0,4,12,16,20':05 / 08:40 / 60s)
- `pipeline_run_regular` 与 `pipeline_run_8h_onchain` `func is` 同一 callable
- `build_scheduler()` 注册 8 个 job id 完全匹配预期集合
- 所有 cron job 用 cron trigger,event_listener 用 interval

```
$ python -m pytest tests/test_scheduler_2_7_a_cron.py -q
15 passed in 0.10s
```

---

## 三、用户验证(SSH 部署后)

```bash
ssh ubuntu@124.222.89.86 << 'SSH'
cd /home/ubuntu/btc_swing_system
git pull
sudo systemctl restart btc-strategy.service
sleep 5
journalctl -u btc-strategy.service -n 80 | grep -E "next run|Scheduler"
SSH
```

预期:8 个 job_id (`collect_klines_1h / collect_klines_daily / ... / event_listener`),`next_run_time` 都是 BJT 整点(:00 / :01 / :05 / :35 / :40)。

---

## 四、§X / §Y / §Z

- ✅ §X:`config/scheduler.yaml` 老 4h interval 配置整段删除,**没保留 enabled:false 的注释**
- ✅ §Y:本 commit 立即 push
- ✅ §Z:测试用真 yaml 文件 + 真 `build_scheduler()` 注册到真 APScheduler 实例,断言 job ids 完全匹配集合 + cron kwargs 字段值精确

---

## 五、后续

- 2.7-B:job_collect_klines_1h / daily / weekly / macro / onchain stub 替换为真实实现 + 衍生品 1h interval + §X 删除老 `job_data_collection`
- 2.7-C:state_builder pre-flight 数据就绪检查
- 2.7-D:`job_event_listener` 实施 + 4 种 event + `events_calendar.triggered_at` 列 + `event_throttle` 表
