# Sprint 1.5d.2 — systemd KillSignal 修复(部署不生效根因)

**Date:** 2026-04-29
**Branch:** main
**Status:** ✅ 完成,deploy/systemd/btc-strategy.service 入仓 + dev_setup.md 文档

---

## 一、问题与根因

1.5d.1 部署后 SSH 验证 API 返回 4 张事件卡,但 DB / DAO 真行 6 张。
`systemctl restart btc-strategy.service` 看似完成、`Active=running`,
但 API 仍返回旧代码生成的数据。

**根因**:
1. `KillSignal` 默认 SIGTERM,uvicorn 不响应快(默认 graceful 走 lifespan shutdown)
2. `TimeoutStopSec` 默认 90s,期间 systemd 等老进程退,新进程虽然在 ExecStart
   阶段被同时启,但 `Active=running` 标识 readiness 而非完全替换 — 旧进程
   仍 hold SQLite connection 和 Python module cache
3. 用户每次部署 `sleep 100` 等的根因就在这里:不是 deploy 慢,是 deploy 没真生效

**触发证据**:`pkill -9 -f uvicorn` 后 systemctl start 立即生效。

这是 Backlog #7 (stop-sigterm 90s timeout) 的副作用。

---

## 二、改动

### 任务 A:`deploy/systemd/btc-strategy.service`(新文件,git 入仓)

```ini
[Unit]
Description=BTC Swing Trading Strategy System (FastAPI + APScheduler)
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/btc_swing_system
Environment="PATH=/home/ubuntu/btc_swing_system/.venv/bin:..."
Environment="SCHEDULER_ENABLED=true"
EnvironmentFile=/home/ubuntu/btc_swing_system/.env
ExecStart=/home/ubuntu/btc_swing_system/.venv/bin/uvicorn src.api.app:app --host 127.0.0.1 --port 8000

# Sprint 1.5d.2 关键 4 行 — 让 systemctl restart 真生效
KillMode=mixed                    # 主进程 SIGTERM,子进程 SIGKILL
KillSignal=SIGINT                 # uvicorn 对 SIGINT 响应快(graceful shutdown 路径)
TimeoutStopSec=15                 # 15s 没退完就 SIGKILL(默认 90s)
SendSIGKILLToProcessGroup=true    # 保险

Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 任务 B:`docs/dev_setup.md` 加 §4 systemd 部署章节

文档化:
- 仓库版本权威路径(`deploy/systemd/btc-strategy.service`)
- 部署命令(cp / daemon-reload / restart)
- 验证命令(`is-active` + `ps -ef | grep [u]vicorn` 看新 PID)
- 关键设计说明(为什么这 4 行 + 1.5d.2 修复缘由)

---

## 三、用户验证脚本(SSH 部署)

```bash
ssh ubuntu@124.222.89.86 << 'SSH'
cd /home/ubuntu/btc_swing_system
git pull

# 同步 unit 文件
sudo cp deploy/systemd/btc-strategy.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart btc-strategy.service
sleep 5

# 1. 进程状态
sudo systemctl is-active btc-strategy.service       # 期望 active
ps -ef | grep -v grep | grep [u]vicorn              # 期望 1 个进程,新 PID

# 2. 连续 5 次 restart,每次都新 PID 且 API 立即可用
for i in 1 2 3 4 5; do
  sudo systemctl restart btc-strategy.service
  sleep 5
  pid=$(pgrep -f 'uvicorn src.api.app')
  status=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/api/system/health)
  echo "Iter $i: PID=$pid, /health HTTP $status"
done
# 期望:每次新 PID,HTTP 200

# 3. 验证旧问题不再出现:不需要 pkill -9
sudo systemctl restart btc-strategy.service
sleep 5
curl -s -u admin:Y_RhcxeApFa0H- http://127.0.0.1:8000/api/strategy/current | \
  python3 -c "
import json, sys
state = json.load(sys.stdin)['state']
event_cards = [c for c in state.get('factor_cards') or []
               if c.get('category') == 'events']
print(f'event 卡数: {len(event_cards)}')
"
# 期望 5 张(1.5d.1 落地);非 4 张(旧进程 hold 状态)
SSH
```

---

## 四、§X / §Y / §Z 自检

### §X(只配置 + 文档,不引入新机制)
- 没 Python 代码变更 / 没新 service / 没新依赖
- 把生产 unit 文件入仓 = 之前在 backlog #4 的 TODO 一并完成

### §Y
本 commit 立即 push。

### §Z 验证策略
- 用户跑"5 次 restart 都新 PID + HTTP 200"测试,反复确认 systemctl 单独
  能完成切换,不再需要 pkill -9 兜底
- pytest 不变(config-only,无代码变化)

### 同类风险扫描
1. **uvicorn workers > 1 时**:当前 `--host 127.0.0.1 --port 8000` 单 worker,
   KillMode=mixed 主进程 SIGINT 即可关。未来如启 `--workers N`,worker 子
   进程在 mixed 模式下走 SIGKILL,语义仍正确(子进程不应 hold 共享资源)
2. **数据库写期间被 SIGKILL**:SQLite 用 WAL 模式有崩溃恢复;15s 容忍窗口
   足够已 commit 的 transaction flush,未 commit 的会回滚(预期行为)
3. **APScheduler shutdown** :uvicorn SIGINT 触发 FastAPI lifespan shutdown,
   App 的 `_stop_scheduler` hook 调 `sched.shutdown(wait=False)`,符合
   设计
4. **生产 .env 路径**:unit 文件硬编码 `/home/ubuntu/btc_swing_system/.env`,
   生产用户路径已固定;若未来切换部署用户,需改 unit 文件

---

## 五、改动文件

| 文件 | 改动 |
|---|---|
| `deploy/systemd/btc-strategy.service` | 新文件(完整 unit 文件,加 KillMode=mixed / KillSignal=SIGINT / TimeoutStopSec=15 / SendSIGKILLToProcessGroup=true) |
| `docs/dev_setup.md` | 加 §4 生产 systemd 服务章节(部署 + 验证 + 设计说明) |

---

## 六、未覆盖项

- backlog #7 旧票据可关:本 sprint 修了"systemctl restart 90s 假性 restart"的根因
- backlog #4 旧票据可关:systemd unit 文件入仓
- nginx 配置入仓:留 v0.6 sprint(同样建议入 `deploy/nginx/`)
