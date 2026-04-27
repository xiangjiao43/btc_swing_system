# Security Incident 2026-04-27 — `.env.save` 泄露 + 全历史擦除

**Date:** 2026-04-27
**Branch:** main · 当前 HEAD = `88da7e8`
**Severity:** High(6 个真实 API key 在公网仓库泄露 ~30 分钟)
**Status:** ✅ git 历史已擦除 + .gitignore 强化 + pre-commit gitleaks 启用;**4/6 key 已 rotate,2 个 alphanode 中转 key 等中介确认**

---

## 一、事件经过

| 时间 | 事件 |
|---|---|
| Sprint 2.6-A.4 Commit 2 | `git add -A` 时 `.env.save`(本地编辑器备份,内含 6 个真 key)被 stage |
| 11:08 (commit `f9457c2`) | push 到公网 main,泄露 30+ 分钟 |
| 用户立即决策 | 4 个 key(OpenAI / FRED 等)用户自己 rotate;2 个 alphanode 中转(CoinGlass / Glassnode)需中介加急 |
| 11:30 起 | 安全事故响应启动:filter-repo 全历史擦除 |

---

## 二、根因

### 2.1 `.gitignore` 模式漏洞

旧 `.gitignore` 第 5 行:
```
*.env
```

只匹配以 `.env` **结尾**的文件(如 `prod.env`),不匹配 `.env.save`(以 `.env` **开头**)。`.env.save` 是 `nano -B` 编辑器在保存时创建的备份文件,内容是上次保存前的 `.env` 完整快照。

### 2.2 `git add -A` 全量暂存

Commit 2 用了 `git add -A`(stage 所有改动 + 删除 + 新文件),没有过滤。如果用 `git add scripts/ src/ tests/ -- ':!*.env*'` 的精准模式就不会出事。

---

## 三、修复执行

### Stage A — 本地全量备份
```
cp -r /Users/xuanmingfeng/Projects/btc_swing_system /tmp/btc_swing_system_backup_before_filter
ls .env*  → .env / .env.example / .env.save 三件齐全(真 key 含)
```
**保留位置**:`/tmp/btc_swing_system_backup_before_filter`,事故响应完成后由用户验证再删。

### Stage B — `git filter-repo` 擦除 `.env.save`
```
brew install git-filter-repo  # v2.47.0
git filter-repo --path .env.save --invert-paths --force
```
- 擦除范围:**所有历史 + 工作树** 中的 `.env.save`
- 影响:仅有 1 个 commit 触碰过 `.env.save`(`f9457c2`),改写为 `5c6a186`;其它 109 个 commit hash 完全保留(filter-repo 是精准擦除,不触碰未引用文件的 commit)
- 副作用:filter-repo 自动移除 `origin` remote(防意外推到错误地方),后续手动重添

### Stage C — 重新挂载 origin
```
git remote add origin git@github.com:xiangjiao43/btc_swing_system.git
```

### Stage D — sanity check + force-push
```
$ git ls-files | grep -i env
.env.example
docs/cc_reports/sprint_1_2_envfix.md
src/_env_loader.py
# (无 .env.save)

$ git rev-list --count HEAD
110

$ git push origin main --force
   + f9457c2...5c6a186 main -> main (forced update)
```
✅ 远程 main 已切到清理后的 `5c6a186`,旧的 `f9457c2`(含 .env.save)在 GitHub 上不再可达。

### Stage E — `.gitignore` 强化(commit `88da7e8`)
```diff
- # ---- Secrets ----
- .env
- .env.local
- .env.*.local
- *.env
+ # ============= ENV FILES (CRITICAL: never commit) =============
+ # 历史教训:Sprint 2.6-A.4 的 .env.save 因 *.env 不匹配 .env.save 而被 commit。
+ .env
+ .env.*       # ← 新增:覆盖 .env.local / .env.save / .env.bak / .env.production
+ *.env
+ *.env.*      # ← 新增
+ # 编辑器 / 工具备份(防误提交带凭据的备份文件)
+ *.bak
+ *.backup
+ *.save       # ← 关键:.env.save 走这条
+ *.swp
+ *.swo
+ *~
```

测试:
```
$ touch .env.save .env.bak some.env
$ git check-ignore -v .env.save .env .env.bak some.env config/prod.local
.gitignore:12:*.save           .env.save        ✓
.gitignore:7:*.env             .env             ✓
.gitignore:10:*.bak            .env.bak         ✓
.gitignore:7:*.env             some.env         ✓
.gitignore:26:config/prod.*    config/prod.local ✓
```

### Stage F — pre-commit gitleaks
`.pre-commit-config.yaml` 在 Sprint 2.5-public commit `1c2e1c8` 已建,本次只是
确保 hook 真的安装到本地 git:
```
$ .venv/bin/pip install pre-commit  # via uv
$ .venv/bin/pre-commit install
pre-commit installed at .git/hooks/pre-commit
$ .venv/bin/pre-commit run --all-files
Detect hardcoded secrets.................................................Passed
```

### Stage G — 防护 commit
`88da7e8` security: harden .gitignore + add pre-commit gitleaks

push 时 hook 自动跑,Passed → 上传成功。

---

## 四、验证

| 检查项 | 结果 |
|---|---|
| `.env.save` 在 git 历史中 | ❌ 已擦除(`git log --all -- .env.save` 空) |
| `.env.save` 在工作树中 | ❌ 已删除 |
| 真实 .env 文件保留 | ✅ 510 bytes,未受影响 |
| 远程 main HEAD | `88da7e8`(`5c6a186` 清理基础上加防护) |
| tracked 文件中的字面量 API key | 0 命中 |
| pre-commit hook 安装 | ✅ `.git/hooks/pre-commit` |

---

## 五、剩余风险

### 5.1 已经被扫描器 / 镜像抓走的不可回收
- GitHub 公网搜索引擎可能在 30 分钟窗口内已索引,会逐步过期
- 自动 secret-scanner 服务(GitGuardian / TruffleHog 等)可能已抓
- `f9457c2` commit 在被 filter-repo 改写前如果有人 git fetch,本地仍有

### 5.2 未 rotate 的 2 个 key
- **CoinGlass API key**(alphanode 中转商,共享 key)
- **Glassnode API key**(同上,与 CoinGlass 共用)
- 用户已联系中介加急,等中介确认后用户自己 rotate
- **风险窗口**:从 11:08 commit 到 alphanode 完成 rotate 期间,任何抓到旧 key 的人可访问中转站,但只能查 BTC 公开行情数据,无下单能力(中转站只读)

### 5.3 已 rotate 的 4 个 key 风险已归零
- OpenAI(Anthropic 中转,通过 OPENAI_API_KEY 字段)
- FRED API key
- (用户 rotate 的另外 2 个 key,具体名称未传给 CC,符合"绝不在对话中重复 key"约束)

---

## 六、防护强化总结(防类似事故)

1. **`.gitignore` 模式扩到 `.env.*` + `*.env.*` + `*.save` + `*.bak`**:覆盖编辑器 / 工具产生的常见备份文件名
2. **pre-commit gitleaks** 强制本地 commit 时扫描:即使 .gitignore 漏配,也能在 commit 时拦截高熵字符串
3. **CLAUDE.md 已有"报告写作纪律"段**(Sprint 2.5-public):明确禁止报告中出现真 key 字面量,这次事故说明仅靠纪律不够,需要工具兜底
4. **下次工作流**:CC 用 `git add` 显式列文件路径,避免 `git add -A` 全量暂存

---

## 七、用户必须确认 / 操作

- [ ] 中介通知后,完成 CoinGlass + Glassnode key rotate
- [ ] 服务器 .env 更新所有 6 个新 key:`scp .env ubuntu@124.222.89.86:~/btc_swing_system/`
- [ ] 重启服务:`ssh ubuntu@124.222.89.86 'sudo systemctl restart btc-strategy'`
- [ ] 验证服务正常:curl + log 确认 AI / CoinGlass / Glassnode 调用成功
- [ ] 验证后:`rm -rf /tmp/btc_swing_system_backup_before_filter`(删除本地备份,该备份含旧 key)
- [ ] 6 个 key 全部 rotate + 服务验证完毕后,再继续 Sprint 2.6-A.4 的 Commit 3-4(部署 FRED 扩展验证 L5)

---

## 八、git log(本次事故响应)

```
88da7e8 security: harden .gitignore + add pre-commit gitleaks
5c6a186 chore: remove Yahoo/Stooq/batch dead code (FRED is sole macro source now)  ← 原 f9457c2 改写后
aca8873 feat(fred): expand to cover dxy/vix/sp500/nasdaq, replacing Yahoo
... (109 个老 commit hash 不变)
```
