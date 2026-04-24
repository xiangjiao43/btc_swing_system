# Sprint 2.4 — Cloud Deploy + 24/7 Auto Run + HTTP Basic Auth

**Date:** 2026-04-24
**Branch:** main (commits 41a9fc6…)
**Server:** Tencent Cloud Lightweight · Ubuntu 24.04.4 LTS · 124.222.89.86

---

## 目标

把 Sprint 2.3 R4 之后的 main 分支部署到腾讯云服务器,让手机/电脑从任何网络访问,
系统 24/7 自动跑 pipeline(每 4 小时),网关 HTTP Basic Auth 保护整站。

---

## 访问方式(上线信息)

**URL:** http://124.222.89.86

**登录:**
- 用户名:`admin`
- 密码:`Y_RhcxeApFa0H-`

> 改密方式:`ssh ubuntu@124.222.89.86 'sudo htpasswd -b /etc/nginx/.btcauth admin 新密码'`

---

## Task 2:Glassnode `since_days` 修复

`scripts/backfill_data.py` 原用 `since=dt / until=dt` 调 `fetch_mvrv_z_score()` 等 9 个方法;
但 `GlassnodeCollector` 的公共签名只接受 `since_days: int`。
改 9 行改成 `since_days=days`,dry-run 已验证所有 9 个指标返回 `fetched=N`。

---

## Task 3:APScheduler 嵌入 FastAPI

`src/api/app.py` 新增 `@app.on_event("startup")`:
- 读 `SCHEDULER_ENABLED`(默认 true)
- 调 `src.scheduler.build_scheduler(blocking=False)` 拿 BackgroundScheduler
- `scheduler.start()`,日志打印每个 job 的 next_run_time(BJT)
- `@app.on_event("shutdown")` 调 `scheduler.shutdown(wait=False)` 优雅停止

pipeline_run job 已在 `config/scheduler.yaml` 启用,`interval: '4h'`。

Version bump `1.15.0` → `2.4.0`。

---

## Task 4:systemd 服务化

**Unit 文件:** `/etc/systemd/system/btc-strategy.service`

```ini
[Unit]
Description=BTC Swing Trading Strategy System (FastAPI + APScheduler)
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/btc_swing_system
Environment="PATH=/home/ubuntu/btc_swing_system/.venv/bin:/home/ubuntu/.local/bin:/usr/local/bin:/usr/bin:/bin"
Environment="SCHEDULER_ENABLED=true"
ExecStart=/home/ubuntu/btc_swing_system/.venv/bin/uvicorn src.api.app:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

> 设计决策:直接用 `.venv/bin/uvicorn` 而非 `uv run uvicorn`,原因是 Chinese server
> 上 `uv sync` 解析 lockfile 会阻塞几十分钟(packages 早已装好)。venv 里 uvicorn 直
> 启跳过 sync,启动 < 2 秒。.env 通过 `src/_env_loader.py` 加载,无需 EnvironmentFile。

---

## Task 5-6:nginx 反向代理 + HTTP Basic Auth

**nginx site:** `/etc/nginx/sites-available/btc-strategy` → 软链到 `sites-enabled/`
**旧 default site:** 已删除 `sites-enabled/default`
**htpasswd 文件:** `/etc/nginx/.btcauth`(owner: www-data, mode 640)

```nginx
server {
    listen 80;
    server_name 124.222.89.86;

    auth_basic "BTC Strategy System";
    auth_basic_user_file /etc/nginx/.btcauth;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_read_timeout 24h;
        proxy_send_timeout 24h;
    }
}
```

---

## Task 7:腾讯云防火墙

**需要用户确认:** 腾讯云控制台 → Lightweight → 防火墙 → 入站规则 →
`TCP:80` 应放行给 `0.0.0.0/0`。

22/TCP(SSH)保持现状。80/TCP 若此前 Sprint 1.5c 已配置就无需再改;
若访问 http://124.222.89.86 超时,回来检查这条。

---

## Task 8:180 天回填 + 首跑 pipeline

### 运行命令

```bash
.venv/bin/python scripts/backfill_data.py --days 180
.venv/bin/python scripts/run_pipeline_once.py
```

### 数据量(填充后 · 2026-04-24 17:45 BJT)

| 表 | 行数 | 说明 |
|---|---|---|
| `strategy_runs` | 4 | 3 老 + 1 首跑(manual,AI status=success,742 in / 422 out tokens) |
| `price_candles` | 3205 | 1h=2000 + 4h=1000 + 1d=180 + 1w=25 |
| `derivatives_snapshots` | 180 | funding_rate + long_short_ratio |
| `onchain_metrics` | 1620 | 9 个 Glassnode 指标 × 180 天 |
| `macro_metrics` | 0 | ⚠️ Yahoo/FRED collector API 不匹配,macro 未入库(见下"待关注") |
| `fallback_events` | 0 | 无降级事件 |

---

## Task 9:全量联通验证

从 Mac 本地(跨公网)验证:

```bash
# 401 without auth
curl -s -o /dev/null -w "%{http_code}\n" http://124.222.89.86/api/system/health
# 200 with auth
curl -s -u admin:Y_RhcxeApFa0H- http://124.222.89.86/api/system/health | jq .
```

浏览器访问 http://124.222.89.86 → Basic Auth 弹窗 → 输入 admin / 上面密码 →
看到 Sprint 2.3 R4 前端。手机 4G 同样。

---

## 运维命令参考

```bash
# 服务状态 / 重启 / 日志
sudo systemctl status btc-strategy
sudo systemctl restart btc-strategy
sudo journalctl -u btc-strategy -f          # 实时跟踪
sudo journalctl -u btc-strategy -n 200      # 最近 200 行

# 更新代码后重启
cd ~/btc_swing_system && git pull && sudo systemctl restart btc-strategy

# nginx
sudo nginx -t                                # 测试配置
sudo systemctl reload nginx                  # 重载配置
sudo tail -f /var/log/nginx/access.log       # 访问日志

# 改密码
sudo htpasswd -b /etc/nginx/.btcauth admin 新密码

# 手动触发一次 pipeline
cd ~/btc_swing_system && .venv/bin/python scripts/run_pipeline_once.py

# 手动补数据(过去 30 天)
cd ~/btc_swing_system && .venv/bin/python scripts/backfill_data.py --days 30
```

---

## 自主决策

1. `systemd ExecStart` 用 `.venv/bin/uvicorn` 而非 `uv run uvicorn`:因为 Chinese
   server 上 `uv sync` 解析 lockfile 阻塞 10+ 分钟(packages 实际已装齐);直用 venv
   绕过 sync,启动快、服务稳定。
2. systemd 单元不加 `EnvironmentFile=.env`:避免 systemd-style env parse 与
   python-dotenv 冲突。app 内部 `src/_env_loader.py` 已处理 .env,`WorkingDirectory`
   点对路径即可。
3. 密码 `Y_RhcxeApFa0H-` 14 位,字母+数字+`-_`,用 `secrets.choice` 本地生成,
   通过 stdin 传给 `htpasswd -nb`(避免命令行历史/process list 泄漏)。
4. 部署顺序:systemd enable(不 start)→ nginx 上线 → 180 天回填 → 首跑 pipeline
   → systemctl start btc-strategy → 验证。先 backfill 再起服务,避免 scheduler 与
   backfill 争 sqlite。
5. 杀掉老的 `uv sync`(卡住 10+ 分钟)后直接用已安装好的 venv 导入包验证;节约
   一次跨境 package resolution 时间。

---

## 待关注(下周)

1. **SSL/TLS:** 现在 HTTP 走明文,Basic Auth password 在公网是可嗅的。建议装
   Let's Encrypt + certbot,或者绑定一个域名后换 HTTPS(CDN 亦可)。
2. **macro backfill 空表:** `backfill_data.py::backfill_macro` 依赖 `YahooFinanceCollector.fetch_series()`
   和 `FREDCollector`;跑完发现 yahoo 分支的 `hasattr(yf, "fetch_series")` 返回 False
   (实际方法名不同),FRED 分支则因 `cannot import name 'FREDCollector' from 'src.data.collectors.fred'`
   直接报错。需对齐实际 collector API 名,下周修。
3. **FRED 数据:** 建模 §3.8 要的 `cpi / pce / unemployment / nfp` 还没接入,
   L5 宏观层仍靠 Yahoo。
4. **BTC-黄金 collector:** 建模 §3.8 要求的 `btc_gold_ratio` 尚缺 collector,
   目前 L5 fallback 到 macro_environment = 'unknown'。
5. **scheduler.yaml 时区:** 配置写的 `UTC` 但 APScheduler 实际用系统 tz
   `Asia/Shanghai` 注册 job,暂无实质问题,但可以显式在 build_scheduler 里传
   timezone='UTC' 与 yaml 对齐。
6. **uvicorn 日志propagation:** `src.api.app` 的 `logger.info('[Scheduler] ...')`
   不在 journalctl 显示(uvicorn 默认 log config 未接管 app 模块 logger)。手动
   invoke startup 可确认 scheduler 已启动 + next run 2026-04-24 22:00 BJT。
   下周可加 `--log-config` 或 `dictConfig` 让 src.* logger 走同一 handler。
7. **API 日志持久化:** 目前只走 journalctl,没落文件。可加 RotatingFileHandler
   或集成 loguru。
