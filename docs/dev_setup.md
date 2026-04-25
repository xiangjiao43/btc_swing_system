# 开发者本地环境设置

本文档只覆盖**新开发者首次 clone 仓库后**需要在本地执行的一次性步骤。
日常运行 / 部署相关命令在各 `docs/cc_reports/sprint_*.md` 报告里。

---

## 1. 启用 pre-commit gitleaks 扫描(强烈建议)

`docs/cc_reports/sprint_2_5_public_audit.md` 完成的安全审计后,仓库已公开。
为防止未来 commit 误带真实 API key / 凭据,项目根目录配置了
`.pre-commit-config.yaml`,集成 [gitleaks](https://github.com/gitleaks/gitleaks)
作为 pre-commit hook。

### 安装步骤

1. 安装 `pre-commit`(用 pip 或 pipx):

   ```bash
   # 选项 A:pip(系统全局)
   pip install pre-commit --break-system-packages

   # 选项 B:pipx(隔离环境,推荐)
   pipx install pre-commit
   ```

2. 在项目根目录注册 hook:

   ```bash
   cd ~/Projects/btc_swing_system
   pre-commit install
   ```

   成功输出:`pre-commit installed at .git/hooks/pre-commit`

### 触发时机

之后**每次 `git commit` 前**会自动扫描 staged 文件,如检测到疑似 secret(API key、token、私钥等),会:

- 阻止 commit
- 在终端打印命中文件 + 行号 + 模式

### 手动跑一次(不依赖 commit)

```bash
pre-commit run --all-files
```

如要绕过(**仅限确认是误报时**):

```bash
git commit --no-verify -m "..."
```

`--no-verify` 是逃生通道,默认禁止使用 — 误用会让真泄露漏过。

---

## 2. 兜底:GitHub Secret Scanning

仓库公开后,GitHub 会自动启用免费的 [Secret Scanning](https://docs.github.com/en/code-security/secret-scanning/about-secret-scanning) — push 时自动扫已知 provider 的 key 格式(Anthropic / OpenAI / AWS / GitHub PAT 等)。这是云端兜底,不能替代本地 pre-commit(本地命中阻止 commit,云端命中只发告警)。

---

## 3. 其它一次性环境

详见仓库根目录 `README.md` + 各 sprint 报告:

- Python 环境 / `uv sync`:见 `README.md`(待补)或 `docs/cc_reports/sprint_2_4.md`
- `.env` 配置:复制 `.env.example` → `.env`,填实际 key
- 服务器部署:`docs/cc_reports/sprint_2_4.md`
