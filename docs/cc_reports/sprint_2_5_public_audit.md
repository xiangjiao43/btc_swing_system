# Sprint 2.5-public — 公开化前安全审计

**Date:** 2026-04-25
**Branch:** main
**Type:** security audit
**触发:** 用户拟把 `xiangjiao43/btc_swing_system` 从 private 改为 public,以便 Claude 直接 web_fetch

---

## 一、扫描方法与命令

```bash
# Task 1: 历史 commit 凭据扫描
git log -p --all 2>/dev/null | grep -iE "(api[_-]?key|password|secret|token|apikey|bearer|authorization)" | wc -l
# → 424 hits(其中绝大多数是 token 计数 / 报告文档讨论 / 变量名,需要二次过滤)

# 二次过滤:实际凭据值
git log -p --all 2>/dev/null | grep -E "sk-ant-"          # Anthropic key
git log -p --all 2>/dev/null | grep "Y_RhcxeApFa0H-"      # nginx Basic Auth
git log -p --all 2>/dev/null | grep -ciE "(api_key|apikey|token|secret|password)\s*[=:]\s*[\"'][a-zA-Z0-9_\-]{20,}[\"']"
git log -p --all 2>/dev/null | grep -E "(GLASSNODE_API_KEY|COINGLASS_API_KEY|FRED_API_KEY|OPENAI_API_KEY|ANTHROPIC_API_KEY|novaiapi)"

# Task 2: 当前跟踪敏感文件
git ls-files | grep -iE "(\.env|secrets|credentials|\.key$|\.pem$|\.db$|\.sqlite|config/local|config/prod|\.htpasswd|\.btcauth)"

# Task 3: .gitignore 状态
cat .gitignore

# Task 4: 工作区敏感文件 + .env 是否被忽略
ls -la | grep -E "^-.*\.env"
git check-ignore -v .env
git ls-files .env

# Task 5: 当前跟踪文件中是否存在密码字面量
git grep "Y_RhcxeApFa0H-"
```

---

## 二、历史 commit 扫描结果

### ⚠ 真实泄露:1 项

**项目 #1**:nginx HTTP Basic Auth 凭据(`admin / Y_RhcxeApFa0H-`)出现在多个 commit 的报告文件中,且这些报告文件**当前仍在跟踪**(不只是历史)。

**详细位置**(`git grep "Y_RhcxeApFa0H-"`):
```
docs/cc_reports/sprint_2_4.md:- 密码:`Y_RhcxeApFa0H-`
docs/cc_reports/sprint_2_4.md:curl -s -u admin:Y_RhcxeApFa0H- http://124.222.89.86/api/system/health | jq .
docs/cc_reports/sprint_2_4.md:3. 密码 `Y_RhcxeApFa0H-` 14 位,字母+数字+`-_`,用 `secrets.choice` 本地生成,
docs/cc_reports/sprint_2_5b.md:6. curl -u admin:Y_RhcxeApFa0H- http://124.222.89.86/api/strategy/current | grep -o "current_analysis" | wc -l  # 应为 6
docs/cc_reports/sprint_2_5b_rewrite.md:5. curl -u admin:Y_RhcxeApFa0H- http://124.222.89.86/api/strategy/current
```

**关联泄露**:同时泄露了**生产服务器的公网 IP**(`124.222.89.86`)和**用户名**(`admin`),三者凑齐即可登录系统。

**威胁评估**:
- 对应资源:`http://124.222.89.86`,nginx 反向代理后面是 FastAPI(只读策略状态接口,无下单功能)
- 攻击面:信息披露(看到当前 BTC 策略 / 数据)+ 服务器存在性确认(端口扫描线索)
- 不影响:无下单接口,不会造成资金损失

**首次引入**:`9b0dbe7`(Sprint 2.4 cloud deploy report,2026-04-24)

### ✅ 误报:多项(详见过滤逻辑)

| 模式 | 命中数 | 说明 |
|---|---|---|
| `tokens_in / tokens_out / max_tokens` | 大量 | API 响应 token 计数,非凭据 |
| `_MAX_TOKENS / _COMPOSITE_KEYS / etc.` | 多处 | Python 常量名,非凭据值 |
| `your_alphanode_key_here / your_api_key_here` | `.env.example` 中 | 占位符 |
| `OPENAI_API_KEY / ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL` | 报告 / 代码中 | 仅环境变量名引用,无具体值 |
| `novaiapi.com` | 注释 / docstring | 中转站域名公开,非凭据 |
| `ssh ubuntu@124.222.89.86` | 报告中 | SSH 用户名 + 公网 IP(用户使用 SSH key 而非密码,无凭据本身) |

### ✅ 未发现的潜在泄露(已扫但 0 命中)

- Anthropic API key 前缀 `sk-ant-` → 0 命中
- 任何 `.env` 文件被 commit → 0 命中
- 长 base64-ish 凭据值字符串(`[A-Za-z0-9_\-]{20,}` 配合 KEY/PASSWORD 关键字)→ 0 命中(除上述 `Y_RhcxeApFa0H-`,14 字符不匹配 ≥20 但被针对性扫到)
- Glassnode / CoinGlass / FRED API key 实际值 → 0 命中

### ⚠ 不确定:0 项

无需用户判断的边界案例。

---

## 三、当前跟踪的敏感文件

`git ls-files | grep -iE "(\.env|secrets|credentials|\.key$|\.pem$|\.db$|\.sqlite|config/local|config/prod|\.htpasswd|\.btcauth)"`

**只有一个命中**:`.env.example`

```
$ git ls-files | grep -iE "(\.env|secrets|credentials|\.key$|\.pem$|\.db$|\.sqlite|config/local|config/prod|\.htpasswd|\.btcauth)"
.env.example
```

**评估**:`.env.example` 内容**全部是占位符**(`your_alphanode_key_here` / `your_api_key_here`),不含任何真实凭据。这是预期/良性的模板文件。

---

## 四、.gitignore 现状与补强

### 现状(commit 03f7902 前)
```
.env
.env.local
.env.*.local
data/*.db
data/*.db-journal
data/*.db-wal
data/*.db-shm
data/*.db.bak*
logs_*.txt
*.log
data/logs/
data/reviews/
```

✅ 覆盖:
- `.env` — 已忽略(`git check-ignore -v .env` 命中规则 `.gitignore:2`)
- 数据库 `data/*.db` — 已忽略
- 运行日志 — 已忽略

### 补强(commit `03f7902`)— 新加入 12 行

```diff
 .env
 .env.local
 .env.*.local
+*.env
+secrets/
+credentials/
+*.key
+*.pem
+*.p12
+*.pfx
+.htpasswd
+*.htpasswd
+config/local.*
+config/prod.*
+config/*.secret.*
```

防御未来:任何 `.htpasswd` / SSH key / TLS 证书 / 自定义 secrets/ 目录被误 commit。

### 当前工作区 .env 状态

```
$ ls -la .env
-rw-r--r--@ 1 xuanmingfeng  staff  479  4月 23 14:36 .env
$ git check-ignore -v .env
.gitignore:2:.env	.env       # ✅ 命中规则
$ git ls-files .env
(empty)                          # ✅ 未被跟踪
```

---

## 五、公开化决策建议

### ⚠️ 需先处理再公开

**阻塞项 (1)**:nginx Basic Auth 密码 `Y_RhcxeApFa0H-` + 公网 IP `124.222.89.86` + 用户名 `admin` 三件套出现在 3 个 tracked 报告文件,公开后 = 直接公开生产系统访问凭据。

**非阻塞但建议处理**:无。

### 决策矩阵

| 路径 | 操作 | 历史是否还泄露? | 复杂度 | 推荐度 |
|---|---|---|---|---|
| **A · 旋转密码 + 替换文件** | 改 nginx htpasswd 密码 + 把报告里 5 处字面量改成 "<see private notes>" | 历史里旧密码仍可见,但已失效;ip + admin 仍可见 | 低 | ⭐⭐⭐⭐⭐ |
| **B · git filter-repo 重写历史** | 用 filter-repo 全历史擦除 `Y_RhcxeApFa0H-` 字面量 + force-push | 干净 | 高(改写历史,需用户授权 force-push) | ⭐⭐ |
| **C · 接受现状直接公开** | 不动 | 旧密码 + IP 永远公开 | 0 | ⭐(有人扫到就能登录) |

---

## 六、处置建议详细 — 推荐选项 A

### A 步骤(等用户授权后,我可以代执行)

1. **生成新密码**:
   ```bash
   .venv/bin/python -c "import secrets, string; print(''.join(secrets.choice(string.ascii_letters+string.digits+'_-') for _ in range(16)))"
   ```
2. **服务器旋转** (新密码不写进任何 commit,只在本次对话告知用户):
   ```bash
   ssh ubuntu@124.222.89.86 'sudo htpasswd -b /etc/nginx/.btcauth admin <NEW_PASSWORD>'
   ```
3. **替换 3 个报告文件中的密码字面量**(改成 `<rotated post-public-audit>` 等占位):
   - `docs/cc_reports/sprint_2_4.md`(3 处)
   - `docs/cc_reports/sprint_2_5b.md`(1 处)
   - `docs/cc_reports/sprint_2_5b_rewrite.md`(1 处)
4. **commit** `chore(reports): redact rotated nginx auth password from history`
5. **告知用户新密码** — 通过对话私下传达,不进 commit
6. 历史 commit 中的旧密码仍存在,但已失效,attacker 拿到无效

### B 步骤(若用户偏好彻底干净的历史)

1. 安装 `git-filter-repo`:`brew install git-filter-repo`
2. 跑 `git filter-repo --replace-text <(echo "Y_RhcxeApFa0H-==>***REDACTED***")`
3. 重新对齐远程:`git push --force --all`(危险,需明确授权)
4. 通知任何 fork / clone 用户重新 clone

⚠ B 选项的代价:任何依赖 commit hash 的引用(包括我之前生成的报告里写的 `b67a75a` / `a57d174` 等)都会失效;commit hash 全部变化。

### 顺带建议 — 可与 A 一起做

- 报告里把 `124.222.89.86` 也替换为 `<server-ip-redacted>`,降低被扫描器命中的概率(虽然 IP 公开本身不是高风险,但减少 footprint)
- 未来报告默认不写公网 IP / 不写凭据 — 已经在 CLAUDE.md 双轨原则段加注?待用户确认是否补一条「报告写作纪律」

---

## 决策项

请用户回复其中一个:
- **走 A**(推荐):我执行步骤 1-4,把新密码私下传给你,你登录 GitHub 改 visibility
- **走 B**:你授权 force-push,我执行 git filter-repo
- **走 C**:你接受历史泄露,直接改 visibility(我不建议,但是你的决定)

我**不会主动改仓库 visibility**(用户拍板动作)。
