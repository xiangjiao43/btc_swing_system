# Sprint 2.6-D.1 — startup hook 错位修复(events seed 移到 FastAPI)

**Date:** 2026-04-27
**Branch:** main · 当前 HEAD = (本 commit)
**Status:** ✅ 完成

---

## 一、根因

systemd 跑 `uvicorn src.api.app:app`,**不会**经过 `src/scheduler/main.py::run_forever`。
Sprint 2.6-D Commit 4 把 `_seed_events_on_startup()` 挂在 `run_forever()` 顶部,
所以生产端从未触发 seeding,`events_calendar` 始终为空。

诊断证据:journalctl 启动日志只有 "uvicorn ... Application startup complete",
无任何 `[Events] seeded` 行,但手动 `seed_events(conn)` 成功 → seeder 本身正常,
唯一问题是入口错误。

---

## 二、改动

### `src/api/app.py`(新增 startup hook)
在 `_start_scheduler` 之前新加 `@app.on_event("startup")` `_seed_events_on_startup_api()`,
异常吞掉,记 warning。复用现有 `EventsSeeder` 路径。

### `src/scheduler/main.py`(§X 删旧)
删除 `_seed_events_on_startup()` 函数 + `run_forever()` 顶部的调用。
原理:scheduler/main 路径生产端不走,留着是死代码。

### `tests/test_scheduler.py`(§X 删旧测试)
删除 `test_seed_events_on_startup_swallows_exceptions` + `test_seed_events_on_startup_calls_seeder`
(测试的对象已删)。

### `tests/test_api_lifespan_seed.py`(新增)
2 个测试用 `TestClient` + `create_app()`:
- happy path:启动时 `seed_events` 被调一次
- failure path:`seed_events` 抛异常 → app 仍能起,health 端点仍响应

---

## 三、验证

```
$ python -m pytest tests/test_api_lifespan_seed.py tests/test_scheduler.py -q
9 passed in 0.82s

$ python -m pytest -q
436 passed, 1 skipped, 138 warnings in 1.90s
```

---

## 四、待用户部署

```bash
ssh user@server
cd /path/to/btc_swing_system
git pull
sudo systemctl restart btc-strategy
# 看日志:journalctl -u btc-strategy -n 50 应有
#   [Events] seeded on FastAPI startup: {'valid': 10, ...}
```

---

## 五、§X / §Y 践行

- ✅ §X:`src/scheduler/main.py` 旧 hook + 对应测试一起删除,不留死代码
- ✅ §Y:commit 后立即 push
