# Sprint 2.8-B — pre-flight degraded 监控告警

**Date:** 2026-04-28
**Branch:** main
**Status:** ✅ 完成,8 个新测试 + 17 个相关回归全过

---

## 一、问题与决策

**Bug**:Sprint 2.7-C 加了 pre-flight 数据就绪检查,失败时只写
`degraded_stages.append(f"pre_flight.{group}")`,但没有告警通道,
用户没法知道何时发生 / 何因 degraded。

**用户决策**:观察 + 告警(选项 A+C)。每次 pipeline_run 跑完,
若 `degraded_stages` 含 `pre_flight.*`,就写一条 alerts 表行,让用户能查到。
不发邮件 / 不推送(避免引入新依赖),只写库 + 提供 CLI 查询脚本。

---

## 二、改动

### 2.1 改动文件
- `src/pipeline/state_builder.py`:
  - 新增 module 级 helper `_write_preflight_degraded_alert(conn, *, run_id,
    run_ts_utc, degraded_stages, metric_inserted_at) -> bool`(行 ~1003)
    - 仅当 `degraded_stages` 含 `pre_flight.<group>` 时写 alert,无则返回 False
    - message 文本:`"pre-flight degraded for groups: [...]; latest inserted_at per group: {...}"`
    - alert_type='pre_flight_degraded',severity='warning',
      raised_at_utc=run_ts_utc,related_run_id=run_id
    - exception 这种伪 group(`pre_flight.exception`)inserted_at 写 None
  - `run_with_context()` 在 persist + commit 之后调 helper(行 ~625-640)
    - 用 try/except 包,任何写失败只 log warning,不影响 BuildResult
- `src/api/models.py`:
  - `HealthResponse` 加字段 `preflight_alerts_24h: int = 0`
- `src/api/routes/system.py`:
  - 新增 `_count_preflight_alerts_24h(conn)`:查 24h 内 pre_flight_degraded
    alert 数
  - `_health_impl()` 在 db_ok 路径调上面 helper,塞进 `preflight_alerts_24h`
  - 任何 DB 错误 → 字段降级为 0,不影响 health 接口本身

### 2.2 新建文件
- `scripts/show_preflight_alerts.py` — CLI 查询脚本
  - 默认查最近 7 天:`uv run python scripts/show_preflight_alerts.py`
  - 自定义天数:`--days 1` / 自定义起点:`--since 2026-04-28`
  - 自定义 DB:`--db /path/to/x.db`(默认走 config/base.yaml)
  - 输出格式:`[N] alerts since YYYY-...` + `timestamp_bjt | groups | run_id`
- `tests/test_preflight_alert_writer.py`(8 测试)
- 本报告

---

## 三、测试

`tests/test_preflight_alert_writer.py`(8 测试 / 真 SQLite + 真 alerts 表):

| 测试 | 验证 |
|---|---|
| `test_writer_inserts_row_when_pre_flight_degraded` | 端到端:helper 写一行,SELECT * 真出 alert_type='pre_flight_degraded',message 含 group 名 + inserted_at 时间戳 |
| `test_writer_returns_false_when_no_pre_flight_degraded` | degraded_stages 没 pre_flight.* → 不写,COUNT=0 |
| `test_writer_handles_pre_flight_exception` | `pre_flight.exception` 伪 group → inserted_at=None,但仍记录 |
| `test_health_preflight_alerts_24h_reflects_count` | 24h 内 2 条 pre_flight + 1 条 25h 前 + 1 条其他 type → /api/system/health 返回 2 |
| `test_health_preflight_alerts_24h_zero_when_no_alerts` | 空 alerts → 字段=0 |
| `test_show_preflight_alerts_script_default_7days` | subprocess 跑 CLI,5 天前 alert 出现,8 天前的不出现 |
| `test_show_preflight_alerts_script_with_days_arg` | `--days 1`:1 天内 1 条,30h 前的过滤掉 |
| `test_show_preflight_alerts_script_no_alerts` | 无数据 → `[0] alerts since` |

**回归**:
- 8/8 新文件 pass
- `test_factor_cards_refresher.py`(2.8-A) 11/11 pass
- `test_strategy_stream_overlays_latest.py`(2.8-A.1) 6/6 pass

> 注:全量 pytest 在 60% 处发现一个**预先存在的 hang**
> (`test_layer5_macro::test_clear_risk_on_tailwind` 受测试污染),
> 经 `git stash` 验证与本 sprint 无关。已在下一个 Sprint 2.8-C 单独修。

---

## 四、用户验证脚本(SSH 部署后)

```bash
ssh ubuntu@124.222.89.86 << 'SSH'
cd /home/ubuntu/btc_swing_system
git pull
sudo systemctl restart btc-strategy.service
sleep 5

# 1. health 接口看新字段
curl -s -u admin:Y_RhcxeApFa0H- http://127.0.0.1:8000/api/system/health | \
  python3 -c "import json,sys; d=json.load(sys.stdin); \
              print('preflight_alerts_24h:', d.get('preflight_alerts_24h'))"

# 2. CLI 查最近 7 天
.venv/bin/python scripts/show_preflight_alerts.py
.venv/bin/python scripts/show_preflight_alerts.py --days 1

# 3. 等下次 pipeline_run(整点 + 5min 之后)
#    若任一组数据 stale → alerts 表会出现一行
sqlite3 data/btc_strategy.db <<EOF
SELECT raised_at_utc, message FROM alerts
WHERE alert_type='pre_flight_degraded'
ORDER BY raised_at_utc DESC LIMIT 5;
EOF
SSH
```

---

## 五、§X / §Y / §Z 自检

### §X(旧代码必须删除)
- `alerts` 表已存在(Sprint 1.x 建模 §10.4),没新建表
- 没有重复实现:helper 是单点,API 路由 + CLI 脚本各自调一次,语义统一

### §Y
本 commit 立即 push。

### §Z 端到端断言
- 8 个测试都用真 SQLite + alerts 表 + SELECT 断言真实写入
- /api/system/health 测试用真 TestClient + alerts 表 seed,断言 JSON 字段
- CLI 脚本测试用真 subprocess + 真 DB,断言 stdout 行数
- 无 mock-only 测试

### 同类风险扫描
1. **alert 写入失败不能拖累 pipeline** — 已包 try/except,只 log warning
2. **alert 表暴涨** — 当前每次 pipeline_run 最多写一条;6 次/天 × 365 天 < 2200 行,
   alerts 表索引正常,无运维压力
3. **/api/system/health 慢** — `_count_preflight_alerts_24h` 是一次 COUNT(*),
   有 `idx_alerts_raised` 索引,微秒级
4. **CLI 脚本默认 DB 路径** — 走 `get_db_path()`(读 config/base.yaml),
   测试用 `--db` 显式覆盖 → 无环境耦合
5. **acknowledged 字段未用** — 当前不区分已读/未读;未来如果用户想"清空已确认告警",
   可加 `--ack` 参数 + UPDATE 路径(暂不做,YAGNI)

---

## 六、部署 checklist

- [ ] git pull
- [ ] `sudo systemctl restart btc-strategy.service`(无 schema 变更,无需迁移)
- [ ] curl /api/system/health 看 preflight_alerts_24h 字段
- [ ] CLI 脚本可用
