# english-frames:进度后端 + 真练习页上线(独立仓库,git pull 部署)

承接 `nginx_english_public_location.md`。本次补齐英语站剩余两样:8010 进度后端
+ 真正的练习页,并把英语站做成**独立 GitHub 仓库**走 git pull 部署。全程未碰
BTC 代码 / BTC 的 nginx location / BTC 的 auth。

## Triggers(偏离 / 需登记的自主决策)

1. **英语站独立仓库**(用户 AskUserQuestion 选定"新建独立仓库,我装 gh"):
   - 本机 `brew install gh`(2.94.0) → 用户浏览器 device-flow 授权(one-time code)
     → `gh repo create xiangjiao43/english-frames --private` → 本机 push → 服务器 clone。
   - 仓库 = `git@github.com:xiangjiao43/english-frames.git`(**PRIVATE**)。
   - 服务器 clone 到 `/home/ubuntu/english`(替换上一次手建的占位目录)。
2. **后端路由 = `/api/progress`,nginx 改 `proxy_pass` 末尾 `/api/`**:
   用户原话"nginx 已把 /english/api/ 映射到后端的 /,所以后端路由用 /api/progress"
   两句在当前 nginx(`proxy_pass .../`)下自相矛盾(`/` 会把 `/api/progress` 映射成
   `/english/api/api/progress`)。为让"后端路由真的是 /api/progress"且"前端相对路径
   `api/progress` 能用",把 `/english/api/` 的 `proxy_pass` 由 `http://127.0.0.1:8010/`
   改为 `http://127.0.0.1:8010/api/`。`/english/api/progress` → 后端 `/api/progress`。
3. **新增 `location = /english` → 301 `/english/`**:不带斜杠时相对路径 `api/progress`
   会错解析成 `/api/progress`,且会落进 `location /`(BTC,弹 401)。加跳转兜底。
4. **静态仍用 nginx alias**(没用方案 3 的 FastAPI 托管):上一次验证 `/english/` 已返回
   200(`/home/ubuntu` 已加 traverse 位),alias 正常,无需 FastAPI 托管静态。
5. **粘贴版 index.html 不可用**:用户附件里的 index.html 中文是双重编码 mojibake,
   UTF-8 续字节已丢失、不可逆(已用 Python 验证)。改为直接读本机原文件
   `/Users/shenjun/Downloads/index.html`(UTF-8 完好)再改造。

## 新建仓库 english-frames(独立于 BTC)

```
english-frames/
  server/__init__.py
  server/app.py                       # FastAPI + SQLite 进度同步
  web/index.html                      # 真练习页(157 句型)+ 同步改造
  deploy/systemd/english-frames.service
  requirements.txt                    # fastapi / uvicorn / pydantic
  README.md  .gitignore               # data/ .venv/ *.db 忽略
```

服务器 clone 在 `/home/ubuntu/english`,故:
- nginx 静态 alias `/home/ubuntu/english/web/` ✅ 对齐
- systemd `WorkingDirectory=/home/ubuntu/english`、`uvicorn server.app:app` ✅

## 后端 `server/app.py` 要点

| 项 | 实现 |
|---|---|
| GET `/api/progress?code=XXXX` | 返回 `{"pos": <int>}`,未知码返回 `{"pos":0}` |
| POST `/api/progress` `{code,pos}` | upsert,返回 `{"ok":true,"pos":<int>}` |
| GET `/api/health` | `{"ok":true}`(探活) |
| 表 | `progress(code TEXT PRIMARY KEY, pos INTEGER, updated_at REAL)`,`data/progress.db` |
| 校验 | `code` ∈ `[A-Za-z0-9_-]{1,64}`;`pos` ∈ `0..100000`;违规 400/422 |
| 限流 | 内存定窗,每 IP 240 次/60s,超限 429;取 `X-Forwarded-For`/`X-Real-IP` |
| CORS | 无需(前端与 API 同源 `/english/*`) |

## 前端 `web/index.html` 改造(在原页基础上**增量**,未改原视觉/数据)

- 顶栏加 `🔑 练习码` 按钮(`#codebtn`):`prompt` 输入,存 `localStorage['frameCode']`,
  按钮回显当前码;输入做 `[A-Za-z0-9_-]` 过滤 + 截断 64,对齐后端校验。
- 翻页:`savePos(i)` 内新增 `serverSyncPos(i)`,**debounce 600ms** POST `api/progress`。
- 打开:`load` 改 async — 若设了码先 GET 服务器 pos;**服务器有进度则服务器为准**,
  服务器空但本地有则把本地 seed 上去;取不到/离线回退 `localStorage`(原逻辑保留)。
- 路径用**相对** `api/progress`(配合 301 兜底,保证带斜杠时解析为 `/english/api/progress`)。
- 所有 `fetch` 包 `try/catch` + `.catch(()=>{})`:**后端挂了页面照常能开能用**(纯本地)。
- 加一条 `@media (max-width:430px)` 仅在窄屏收紧顶栏间距,防 4 按钮溢出;桌面视觉不变。

JS 经 `node --check` 通过;文件 UTF-8 完好;中文正常(练习码/你来造/Frame Deck)。

## nginx 改动(只动我自己上次加的 english location;BTC 的 `/`、auth 原样)

```nginx
location = /english { auth_basic off; return 301 /english/; }          # 新增
location /english/api/ {
    auth_basic off;
    proxy_pass http://127.0.0.1:8010/api/;   # 由 .../  改为 .../api/
    ...
}
location /english/ { auth_basic off; alias /home/ubuntu/english/web/; index index.html; try_files $uri $uri/ =404; }
```

备份:`/etc/nginx/sites-available/btc-strategy.bak_20260616_162109`。`nginx -t` 通过 + reload。

## systemd 服务 english-frames

`User=ubuntu`、venv、`Restart=always`、`KillSignal=SIGINT`/`TimeoutStopSec=15`、
`enable --now`(开机自启)。`is-active=active`、`is-enabled=enabled`、
`ss -ltnp` 见 `127.0.0.1:8010`(uvicorn)。

## 验收记录(从本机外网经公网 IP 124.222.89.86)

| 检查 | 结果 |
|---|---|
| `GET /english/api/health` | ✅ 200 `{"ok":true}` 免密 |
| POST `/english/api/progress` (写 pos=88) | ✅ `{"ok":true,"pos":88}` |
| GET `/english/api/progress?code=...` 回读 | ✅ `{"pos":88}`(跨"设备"同步成立) |
| 非法 pos=999999 | ✅ HTTP 422 拒绝 |
| `/english`(无斜杠) | ✅ 301 → `/english/` |
| `/english/` | ✅ 200,真练习页(62235 bytes,中文正常) |
| `/`(BTC 根) | ✅ 仍 401(未碰) |
| `ss -ltnp` 8010 | ✅ uvicorn 监听,不再 502 |

收尾:已删除联调测试行(`selftest`/`extbeta`/`phonedemo`),生产 DB `progress` 表清空。

## 最终访问网址

- 练习页(公开免密):**http://124.222.89.86/english/**
- 进度 API:`http://124.222.89.86/english/api/progress`(`health` 探活)
- 用法:顶栏 `🔑 练习码` 输入任意码(如 `bruce`),手机/电脑用**同一个码**即可同步进度。

## 本 sprint 删除清单

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| 占位目录 `/home/ubuntu/english`(手建,非 git) | 服务器 | 被 `git clone english-frames` 替代 |
| 仓库内占位 `web/index.html`(c35a62b) | english-frames | 同 PR 内被真练习页(e806783)替换 |
| 测试行 selftest/extbeta/phonedemo | 生产 `data/progress.db` | 联调产物,收尾清空 |
| nginx `proxy_pass .../`(上一版) | btc-strategy | 改为 `.../api/`,旧值有 `.bak_20260616_162109` |

BTC 仓库 `btc_swing_system`:本 sprint **零改动**(仅本报告 md 入库)。

## 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 JS `node --check` / 后端 import 自检 | ✅ JS OK;服务器 `import fastapi,uvicorn,pydantic` OK |
| GitHub push(english-frames) | ✅ `e806783`(私有仓库 xiangjiao43/english-frames) |
| 服务器 git clone + pull | ✅ clone 到 /home/ubuntu/english;pull 到 HEAD e806783,tree clean |
| 服务器 systemctl(english-frames) | ✅ install + `enable --now`,active/enabled,8010 在听 |
| 服务器 nginx -t && reload | ✅ test ok + reload + active |
| 外网 IP 验证 | ✅ /english/ 真页、/english/api/ 读写、/ 仍 401 |
| 本报告(btc 仓库) | 待 push(仅 md) |
