# nginx: 新增 /english/ 与 /english/api/ 公开免密 location

## Triggers(偏离建模的自主决策)

- 本任务是**服务器 nginx 系统配置**改动(`/etc/nginx/sites-available/btc-strategy`),
  不在 git 仓库内,故走 SSH 直接改 `/etc/nginx`(与 `deploy/systemd` 同类:dev_setup.md
  已确立"systemd/nginx 系统文件部署时 SSH 同步"模式)。这是 §Z 的合理边界外用例
  (§Z 约束的是仓库内代码/配置/模板,不是 `/etc/nginx` 系统文件)。
- 用户选择静态目录路径:`/home/ubuntu/english/web/`(AskUserQuestion 确认)。
- `/home/ubuntu` 原权限 `750`,`www-data` 无法 traverse → 静态服务会 403。
  自主决策:`chmod o+x /home/ubuntu`(**仅 traverse,不开 read/list**),
  最小化变更让 nginx 能进入已 775 的 `english/web/`。未给 home 加可读位。
- 后端 8010 当前**无服务**,nginx 已就绪;放了占位 `index.html` 让 `/english/`
  验证返回 200(而非空目录 403),证明免密生效。真静态文件与 8010 后端待用户后续部署。

## 改动对象

| 对象 | 路径 | 说明 |
|---|---|---|
| nginx server 块 | `/etc/nginx/sites-available/btc-strategy`(服务器) | server 块内**新增** 2 个 location;`/` 与 server 级 auth 原样不动 |
| 备份 | `/etc/nginx/sites-available/btc-strategy.bak_20260616_153646` | 改前自动备份 |
| 静态目录 | `/home/ubuntu/english/web/` | 新建 + 占位 `index.html` |
| home 权限 | `/home/ubuntu` `750 → 751`(`drwxr-x--x`) | 仅给 other 加 execute(traverse),无 read |

## 新增的 nginx 配置(server 块内)

```nginx
    # === English app (公开免密) ===
    # /english/api/ 是更长前缀,nginx 自动最长前缀匹配,排在 /english/ 之前
    location /english/api/ {
        auth_basic off;                     # 显式关掉 server 级 auth_basic 继承
        proxy_pass http://127.0.0.1:8010/;  # 末尾斜杠:剥掉 /english/api/ 前缀
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_read_timeout 24h;
        proxy_send_timeout 24h;
    }

    location /english/ {
        auth_basic off;                     # 显式关掉 server 级 auth_basic 继承
        alias /home/ubuntu/english/web/;
        index index.html;
        try_files $uri $uri/ =404;
    }
```

`location /`(proxy 到 8000)与 server 级 `auth_basic "BTC Strategy System"` /
`auth_basic_user_file /etc/nginx/.btcauth` **完全未改**,BTC 站仍全站需密码。

## 设计决策

1. **两个新 location 各写一行 `auth_basic off;`** —— server 级 `auth_basic`
   被各 location 继承,必须在子 location 显式 `off` 才能免密。已照做。
2. **`proxy_pass` 末尾斜杠** `http://127.0.0.1:8010/` —— 把 `/english/api/foo`
   重写为后端的 `/foo`(剥前缀),符合用户要求。
3. **最长前缀匹配** —— `/english/api/` 比 `/english/` 长,nginx 自动优先匹配,
   无需担心顺序;静态与 api 不会互相吃请求。
4. **占位 index.html** —— 让外网验证返回 200 而非 403,直观证明"打开即见、不弹密码"。

## 验收记录(从本机外网经公网 IP 124.222.89.86)

| 请求 | 期望 | 实测 |
|---|---|---|
| `GET /english/` | 200,无 `WWW-Authenticate` | ✅ `HTTP/1.1 200 OK`,无 auth 头,返回占位页 |
| `GET /` (BTC 根) | 401 + `WWW-Authenticate`(auth 仍在) | ✅ `HTTP/1.1 401 Unauthorized` realm="BTC Strategy System" |
| `GET /english/api/` | **非 401**(免密生效);8010 无后端时 502 可接受 | ✅ `HTTP/1.1 502 Bad Gateway`(非 401,证明免密 + proxy 已配) |

`sudo nginx -t` 通过;`sudo systemctl reload nginx` 后 `is-active = active`。

## 未覆盖项 / 风险提示

1. **8010 后端尚未部署** —— `/english/api/` 现返回 502,待用户起 127.0.0.1:8010 服务。
2. **真静态文件未上传** —— `/english/web/` 仅占位 index.html,待用户放真文件。
3. **HTTP 明文** —— `/english/` 公开免密且走 80 端口明文,任何人有网即可访问;
   若后续放敏感内容需考虑。当前按用户明确要求"免密公开"实现。
4. nginx 配置在服务器本地,不在 git;回滚用上方 `.bak_20260616_153646`。

## 本 sprint 删除清单

**本任务无替代关系,无删除项** —— 纯新增 2 个 nginx location + 新建静态目录,
未替代任何旧配置,`location /` 与原 auth 原样保留。

## 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | N/A(纯 nginx 系统配置,无 Python 改动) |
| GitHub push(本报告) | 待执行(仅本 md 报告入库) |
| 服务器 nginx 配置改动 | ✅ 已改 `/etc/nginx/sites-available/btc-strategy` + 备份 |
| 服务器 `nginx -t && reload` | ✅ test ok + reload + is-active=active |
| 外网 IP 验证 | ✅ `/english/` 200 免密、`/` 仍 401、`/english/api/` 502 非 401 |
